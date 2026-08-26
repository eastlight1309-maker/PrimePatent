# -*- coding: utf-8 -*-
"""출원인 표준화(명칭 통일).

같은 회사가 "삼성전자(주)", "삼성전자 주식회사", "SAMSUNG ELECTRONICS CO., LTD." 처럼
여러 표기로 흩어져 있으면 출원인 기준 통계(시장 영향력·경쟁사 커버리지·자기인용 판정)가
모두 어긋난다. 업로드 직후 후보 그룹을 자동으로 묶어 사용자에게 보여 주고,
**승인된 표준명만** 분석에 반영한다(승인 전에는 원본 표기를 그대로 쓴다).
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional, Sequence

from .parsing import to_entity_list, to_text
from .records import normalize_entity_name

# 정규화 키가 달라도 이 유사도 이상이면 같은 출원인 후보로 본다.
SIMILARITY_THRESHOLD = 0.88
MAX_GROUPS = 2000


def collect_applicants(rows: Sequence[Dict[str, Any]],
                       mapping: Dict[str, Dict]) -> List[Dict[str, Any]]:
    """업로드 데이터에서 원본 출원인 표기와 등장 건수를 모은다."""
    applicant_column = (mapping.get("applicant") or {}).get("column")
    normalized_column = (mapping.get("applicantNormalized") or {}).get("column")
    code_column = (mapping.get("applicantNormalizedCode") or {}).get("column")
    if not applicant_column and not normalized_column:
        return []

    counts: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        names = to_entity_list(row.get(applicant_column)) if applicant_column else []
        if not names and normalized_column:
            names = to_entity_list(row.get(normalized_column))
        hint = to_text(row.get(normalized_column)) if normalized_column else ""
        code = to_text(row.get(code_column)) if code_column else ""
        for name in names:
            entry = counts.setdefault(name, {"raw": name, "count": 0, "hints": {}, "codes": {}})
            entry["count"] += 1
            if hint:
                entry["hints"][hint] = entry["hints"].get(hint, 0) + 1
            if code:
                entry["codes"][code] = entry["codes"].get(code, 0) + 1
    return sorted(counts.values(), key=lambda e: (-e["count"], e["raw"]))


def cluster_applicants(entries: Sequence[Dict[str, Any]],
                       threshold: float = SIMILARITY_THRESHOLD) -> List[Dict[str, Any]]:
    """원본 표기를 표준화 후보 그룹으로 묶는다.

    1) 대표명화 코드가 같으면 같은 그룹 (WIPS 가 이미 판정한 것을 신뢰)
    2) 대표명화 영문/국문명이 같으면 같은 그룹
       (한글 표기와 영문 표기는 문자열 유사도로는 절대 묶이지 않으므로 이 신호가 필요하다)
    3) 법인격 표기를 제거한 정규화 키가 같으면 같은 그룹
    4) 정규화 키 유사도가 threshold 이상이면 같은 그룹
    """
    groups: List[Dict[str, Any]] = []
    by_code: Dict[str, int] = {}
    by_hint: Dict[str, int] = {}
    by_key: Dict[str, int] = {}

    for entry in entries:
        key = normalize_entity_name(entry["raw"])
        code = _dominant(entry.get("codes"))
        hint = normalize_entity_name(_dominant(entry.get("hints")))
        index = None

        if code and code in by_code:
            index = by_code[code]
        elif hint and hint in by_hint:
            index = by_hint[hint]
        elif key and key in by_key:
            index = by_key[key]
        elif key:
            index = _find_similar(groups, key, threshold)

        if index is None:
            groups.append({"key": key, "keys": [key] if key else [],
                           "members": [], "codes": set()})
            index = len(groups) - 1

        group = groups[index]
        group["members"].append(entry)
        if key and key not in group["keys"]:
            group["keys"].append(key)
        if code:
            group["codes"].add(code)
            by_code.setdefault(code, index)
        if hint:
            by_hint.setdefault(hint, index)
        if key:
            by_key.setdefault(key, index)

    result = [_finalize_group(group, position) for position, group in enumerate(groups)]
    result.sort(key=lambda g: (-g["count"], g["standardName"]))
    return result[:MAX_GROUPS]


def _find_similar(groups: List[Dict[str, Any]], key: str, threshold: float) -> Optional[int]:
    best_index, best_score = None, threshold
    for index, group in enumerate(groups):
        for existing in group["keys"]:
            score = difflib.SequenceMatcher(None, key, existing).ratio()
            if score >= best_score:
                best_index, best_score = index, score
    return best_index


def _dominant(counter: Optional[Dict[str, int]]) -> str:
    if not counter:
        return ""
    return max(counter.items(), key=lambda kv: (kv[1], kv[0]))[0]


def _finalize_group(group: Dict[str, Any], position: int) -> Dict[str, Any]:
    members = sorted(group["members"], key=lambda m: (-m["count"], m["raw"]))
    total = sum(member["count"] for member in members)

    # 표준명 후보: WIPS 대표명화 값 → 가장 많이 등장한 원본 표기
    hint_counter: Dict[str, int] = {}
    for member in members:
        for hint, count in (member.get("hints") or {}).items():
            hint_counter[hint] = hint_counter.get(hint, 0) + count
    standard = _dominant(hint_counter) or members[0]["raw"]

    return {
        "groupId": "g%04d" % position,
        "standardName": standard,
        "suggestedName": standard,
        "count": total,
        "variantCount": len(members),
        "codes": sorted(group["codes"]),
        "variants": [{"raw": member["raw"], "count": member["count"]} for member in members],
        # WIPS 대표명화 표기도 별칭으로 둔다. 이것을 치환하지 않으면
        # applicantPrimary 가 대표명화 값을 우선하므로 승인한 표준명이 화면에 안 보인다.
        "aliases": sorted(hint_counter.keys()),
        "needsReview": len(members) > 1,
    }


def build_name_map(groups: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    """{원본 표기: 표준명} 매핑. 표준명이 비어 있으면 원본을 유지한다."""
    mapping: Dict[str, str] = {}
    for group in groups or []:
        standard = to_text(group.get("standardName")) or to_text(group.get("suggestedName"))
        if not standard:
            continue
        names = [to_text(v.get("raw") if isinstance(v, dict) else v)
                 for v in (group.get("variants") or [])]
        names += [to_text(a) for a in (group.get("aliases") or [])]
        for name in names:
            if name and name != standard:
                mapping[name] = standard
    return mapping


def summarize(groups: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    groups = list(groups or [])
    merged = [g for g in groups if g.get("variantCount", 1) > 1]
    return {
        "groupCount": len(groups),
        "variantCount": sum(g.get("variantCount", 1) for g in groups),
        "mergedGroupCount": len(merged),
        "mergedVariantCount": sum(g.get("variantCount", 1) for g in merged),
        "documentCount": sum(g.get("count", 0) for g in groups),
    }
