# -*- coding: utf-8 -*-
"""업로드 엑셀의 컬럼 → 표준 필드 자동 매핑.

규칙(우선순위)
 1) 정규화 완전일치 + 별칭 우선순위(primary alias) 가 높은 필드
 2) 느슨한 정규화 완전일치
 3) 유사도(difflib) >= threshold → 후보 제안(사용자 확인 필요)
한 컬럼은 하나의 필드에만, 한 필드에는 하나의 컬럼만 배정한다.
"""

from __future__ import annotations

import difflib
from typing import Dict, List, Optional, Sequence

from .columns import (ALIAS_LOOSE, ALIAS_STRICT, FIELD_BY_KEY, FIELDS,
                      IMPORTANT_KEYS, REQUIRED_KEYS, loose_header,
                      normalize_header)

FUZZY_THRESHOLD = 0.86

METHOD_EXACT = "exact"
METHOD_ALIAS = "alias"
METHOD_LOOSE = "loose"
METHOD_FUZZY = "fuzzy"
METHOD_MANUAL = "manual"
METHOD_NONE = "none"

_METHOD_SCORE = {
    METHOD_EXACT: 1.0,
    METHOD_ALIAS: 0.97,
    METHOD_LOOSE: 0.92,
    METHOD_FUZZY: 0.80,
    METHOD_MANUAL: 1.0,
}


def _candidates_for(header: str) -> List[Dict]:
    """컬럼 1개에 대한 필드 후보 목록(점수 내림차순)."""
    strict = normalize_header(header)
    loose = loose_header(header)
    found: Dict[str, Dict] = {}

    def _add(key: str, method: str, priority: int, similarity: float):
        score = _METHOD_SCORE[method] - priority * 0.01
        prev = found.get(key)
        if prev is None or score > prev["score"]:
            found[key] = {"field": key, "method": method, "score": round(score, 4),
                          "similarity": round(similarity, 4), "aliasPriority": priority}

    for key, priority in ALIAS_STRICT.get(strict, []):
        _add(key, METHOD_EXACT if priority == 0 else METHOD_ALIAS, priority, 1.0)
    if not found:
        for key, priority in ALIAS_LOOSE.get(loose, []):
            _add(key, METHOD_LOOSE, priority, 1.0)
    if not found and loose:
        for spec in FIELDS:
            best = 0.0
            for alias in (spec.aliases or (spec.label,)):
                ratio = difflib.SequenceMatcher(None, loose, loose_header(alias)).ratio()
                best = max(best, ratio)
            if best >= FUZZY_THRESHOLD:
                _add(spec.key, METHOD_FUZZY, 0, best)
    return sorted(found.values(), key=lambda c: (-c["score"], c["field"]))


def auto_map(headers: Sequence[str]) -> Dict[str, Dict]:
    """헤더 목록 → {field_key: mapping_info} 자동 매핑 결과."""
    per_column: List[Dict] = []
    for index, header in enumerate(headers):
        per_column.append({
            "index": index,
            "column": header,
            "candidates": _candidates_for(header),
        })

    # (컬럼, 후보) 쌍을 점수 내림차순으로 그리디 배정
    pairs = []
    for col in per_column:
        for cand in col["candidates"]:
            pairs.append((cand["score"], col["index"], cand, col["column"]))
    pairs.sort(key=lambda p: (-p[0], p[1]))

    used_columns = set()
    mapping: Dict[str, Dict] = {}
    for score, col_index, cand, column in pairs:
        if col_index in used_columns or cand["field"] in mapping:
            continue
        used_columns.add(col_index)
        mapping[cand["field"]] = {
            "field": cand["field"],
            "column": column,
            "columnIndex": col_index,
            "method": cand["method"],
            "confidence": round(min(1.0, max(0.0, cand["score"])), 3),
            "similarity": cand["similarity"],
        }
    return mapping


def mapping_report(headers: Sequence[str], mapping: Dict[str, Dict]) -> Dict:
    """매핑 현황 요약(프론트 표시 및 검증용)."""
    mapped_columns = {m.get("column") for m in mapping.values() if m.get("column")}
    unmapped_columns = [h for h in headers if h not in mapped_columns]
    missing_required = [k for k in REQUIRED_KEYS if k not in mapping]
    missing_important = [k for k in IMPORTANT_KEYS if k not in mapping]
    low_confidence = sorted(
        [m for m in mapping.values() if m.get("confidence", 0) < 0.9],
        key=lambda m: m.get("confidence", 0))
    return {
        "mappedCount": len(mapping),
        "columnCount": len(headers),
        "unmappedColumns": unmapped_columns,
        "missingRequired": missing_required,
        "missingRequiredLabels": [FIELD_BY_KEY[k].label for k in missing_required],
        "missingImportant": missing_important,
        "missingImportantLabels": [FIELD_BY_KEY[k].label for k in missing_important],
        "lowConfidence": low_confidence,
        "ok": not missing_required,
    }


def normalize_user_mapping(raw: Optional[Dict], headers: Sequence[str]) -> Dict[str, Dict]:
    """프론트에서 올라온 매핑({field: column} 또는 상세 dict)을 표준형으로 정리."""
    result: Dict[str, Dict] = {}
    if not raw:
        return result
    header_index = {h: i for i, h in enumerate(headers)}
    for field_key, value in raw.items():
        if field_key not in FIELD_BY_KEY:
            continue
        if isinstance(value, dict):
            column = value.get("column")
            method = value.get("method") or METHOD_MANUAL
            confidence = value.get("confidence")
        else:
            column = value
            method = METHOD_MANUAL
            confidence = None
        if column in (None, "", "__none__"):
            continue
        column = str(column)
        if column not in header_index:
            continue
        result[field_key] = {
            "field": field_key,
            "column": column,
            "columnIndex": header_index[column],
            "method": method,
            "confidence": float(confidence) if confidence is not None else 1.0,
            "similarity": 1.0,
        }
    return result


def cleared_fields(user_mapping: Optional[Dict]) -> List[str]:
    """사용자가 '(미사용)' 으로 명시한 필드 목록."""
    if not isinstance(user_mapping, dict):
        return []
    cleared = []
    for field_key, value in user_mapping.items():
        if field_key not in FIELD_BY_KEY:
            continue
        column = value.get("column") if isinstance(value, dict) else value
        if column in (None, "", "__none__"):
            cleared.append(field_key)
    return cleared


def resolve_mapping(headers: Sequence[str], user_mapping: Optional[Dict] = None) -> Dict[str, Dict]:
    """자동 매핑에 사용자 수정본을 반영한 최종 매핑.

    - 사용자가 지정한 컬럼이 자동 매핑의 다른 필드에서 이미 사용 중이면
      사용자 지정을 우선하고 자동 매핑 쪽을 해제한다.
    - 사용자가 값을 비운(``""``/``None``/``"__none__"``) 필드는 자동 매핑 결과에서도 제거한다.
      (화면에서 '(미사용)' 으로 바꾼 항목이 자동 매핑으로 되살아나지 않도록)
    """
    final = dict(auto_map(headers))
    if not isinstance(user_mapping, dict) or not user_mapping:
        return final

    for field_key, info in normalize_user_mapping(user_mapping, headers).items():
        for other_key, other in list(final.items()):
            if other_key != field_key and other.get("column") == info.get("column"):
                final.pop(other_key)
        final[field_key] = info

    for field_key in cleared_fields(user_mapping):
        final.pop(field_key, None)
    return final
