# -*- coding: utf-8 -*-
"""출원인 표준화(명칭 통일).

같은 회사가 "삼성전자(주)", "삼성전자 주식회사", "SAMSUNG ELECTRONICS CO., LTD." 처럼
여러 표기로 흩어져 있으면 출원인 기준 통계(시장 영향력·자기인용 판정)가 모두 어긋난다.
업로드 직후 후보 그룹을 자동으로 묶어 사용자에게 보여 주고,
**승인된 표준명만** 분석에 반영한다(승인 전에는 원본 표기를 그대로 쓴다).

설계 원칙
  1. 공동출원 행의 '대표명화' 값은 **위치가 맞을 때만** 각 출원인에게 붙인다.
     행 단위 값을 그 행의 모든 출원인에게 붙이면 공동출원 파트너가
     대표 출원인과 한 그룹으로 병합된다(무관한 회사가 묶이는 원인).
  2. 표준명은 **한글 표기를 먼저** 추천한다(사용자가 알아보기 쉬운 이름).
  3. 표준명에서는 주식회사 / Inc. / Co.,Ltd. 같은 법인격 표기를 떼고
     **핵심 명칭만** 남긴다.
  4. 표기가 2개 이상 묶인 그룹은 사용자가 **승인**하기 전까지 병합하지 않는다.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .parsing import to_entity_list, to_text
from .records import normalize_entity_name

# 정규화 키가 달라도 이 유사도 이상이면 같은 출원인 후보로 본다.
SIMILARITY_THRESHOLD = 0.88
MAX_GROUPS = 2000

_HANGUL_RE = re.compile(r"[가-힣]")

# 이름 어디에 있어도 떼어 내는 법인격 표기(한중일)
_LEGAL_CJK_RE = re.compile(
    r"(주식회사|유한회사|유한책임회사|합자회사|합명회사|사단법인|재단법인|학교법인|"
    r"의료법인|농업회사법인|영농조합법인|\(주\)|\（주\）|\(유\)|\(재\)|\(사\)|\(학\)|\(의\)|"
    r"株式会社|有限会社|合同会社|有限公司|股份有限公司|有限责任公司)")

# 이름 **끝**에서만 떼어 내는 법인격 표기(영문). 중간에서 떼면 실제 상호가 깨진다
# (예: "AB Sciex" 의 AB, "Oy Nokia" 의 Oy).
_LEGAL_TAIL_RE = re.compile(
    r"[\s,./·-]*(?:"
    r"co\.?\s*,?\s*ltd\.?|company\s+limited|company|corporation|corp\.?|incorporated|inc\.?|"
    r"limited|ltd\.?|l\.l\.c\.?|llc|l\.l\.p\.?|llp|plc|gmbh|mbh|ag|"
    r"s\.?a\.?s\.?|s\.?a\.?|n\.?v\.?|b\.?v\.?|s\.?p\.?a\.?|s\.?r\.?l\.?|"
    r"pte\.?\s*ltd\.?|pte\.?|pty\.?\s*ltd\.?|pty\.?|k\.?k\.?|kabushiki\s+kaisha|"
    r"oy|ab|a/s|aps"
    r")\.?\s*$", re.IGNORECASE)

_LEADING_THE_RE = re.compile(r"^the\s+", re.IGNORECASE)
_TRIM_RE = re.compile(r"^[\s,./·\-()\[\]]+|[\s,./·\-()\[\]]+$")


def has_hangul(value: Any) -> bool:
    return bool(_HANGUL_RE.search(to_text(value)))


def core_name(value: Any) -> str:
    """법인격 표기를 떼고 **핵심 명칭만** 남긴다.

    "주식회사 이엔에프테크놀로지"   -> "이엔에프테크놀로지"
    "SAMSUNG ELECTRONICS CO., LTD." -> "SAMSUNG ELECTRONICS"
    "(주)엘지화학"                  -> "엘지화학"

    법인격 표기를 떼면 아무것도 남지 않는 경우(예: 이름이 "주식회사")에는
    원본을 그대로 돌려준다.
    """
    text = to_text(value).strip()
    if not text:
        return ""
    stripped = _LEGAL_CJK_RE.sub(" ", text)
    stripped = _LEADING_THE_RE.sub("", stripped)
    for _ in range(3):                       # "XYZ Co., Ltd." 처럼 겹친 표기 대응
        shorter = _LEGAL_TAIL_RE.sub("", stripped)
        if shorter == stripped:
            break
        stripped = shorter
    stripped = _TRIM_RE.sub("", re.sub(r"\s{2,}", " ", stripped)).strip()
    return stripped or text


def collect_applicants(rows: Sequence[Dict[str, Any]],
                       mapping: Dict[str, Dict]) -> List[Dict[str, Any]]:
    """업로드 데이터에서 원본 출원인 표기와 등장 건수를 모은다.

    공동출원(한 행에 출원인 2인 이상)도 각 출원인을 따로 센다.
    '대표명화' 값은 출원인 수와 개수가 맞을 때만 위치로 짝지어 붙인다.
    """
    applicant_column = (mapping.get("applicant") or {}).get("column")
    normalized_column = (mapping.get("applicantNormalized") or {}).get("column")
    code_column = (mapping.get("applicantNormalizedCode") or {}).get("column")
    if not applicant_column and not normalized_column:
        return []

    counts: Dict[str, Dict[str, Any]] = {}
    unaligned_rows = 0
    for row in rows:
        names = to_entity_list(row.get(applicant_column)) if applicant_column else []
        if not names and normalized_column:
            names = to_entity_list(row.get(normalized_column))
        if not names:
            continue
        joint = len(names) > 1

        hints = to_entity_list(row.get(normalized_column)) if normalized_column else []
        codes = to_entity_list(row.get(code_column)) if code_column else []
        hint_by_name, hint_ok = _align(hints, names)
        code_by_name, code_ok = _align(codes, names)
        if joint and not (hint_ok and code_ok):
            unaligned_rows += 1

        for name in names:
            entry = counts.setdefault(name, {"raw": name, "count": 0, "solo": 0, "joint": 0,
                                             "hints": {}, "codes": {}})
            entry["count"] += 1
            entry["joint" if joint else "solo"] += 1
            hint = hint_by_name.get(name)
            if hint:
                entry["hints"][hint] = entry["hints"].get(hint, 0) + 1
            code = code_by_name.get(name)
            if code:
                entry["codes"][code] = entry["codes"].get(code, 0) + 1

    entries = sorted(counts.values(), key=lambda e: (-e["count"], e["raw"]))
    if unaligned_rows and entries:
        entries[0].setdefault("_warnings", []).append(unaligned_rows)
    return entries


def _align(values: List[str], names: List[str]) -> Tuple[Dict[str, str], bool]:
    """행의 대표명화 값을 출원인과 위치로 짝짓는다.

    개수가 맞지 않으면(공동출원인데 대표명화 값이 1개뿐인 경우 등) **아무것도 붙이지
    않는다.** 억지로 붙이면 공동출원 파트너가 대표 출원인의 대표명화 값을 물려받아
    전혀 다른 회사가 한 그룹으로 병합된다.
    """
    if not values:
        return {}, True
    if len(values) == len(names):
        return {name: value for name, value in zip(names, values) if value}, True
    return {}, False


def cluster_applicants(entries: Sequence[Dict[str, Any]],
                       threshold: float = SIMILARITY_THRESHOLD) -> List[Dict[str, Any]]:
    """원본 표기를 표준화 후보 그룹으로 묶는다.

    1) 대표명화 코드가 같으면 같은 그룹 (WIPS 가 이미 판정한 것을 신뢰)
    2) 대표명화 영문/국문명이 같으면 같은 그룹
       (한글 표기와 영문 표기는 문자열 유사도로는 절대 묶이지 않으므로 이 신호가 필요하다)
    3) 법인격 표기를 제거한 정규화 키가 같으면 같은 그룹
    4) 정규화 키 유사도가 threshold 이상이면 같은 그룹

    3)·4) 로 묶을 때는 **대표명화 코드가 서로 다르면 묶지 않는다**
    (WIPS 가 다른 회사로 판정한 것을 문자열 유사도로 뒤집지 않는다).
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
        elif key and key in by_key and _code_compatible(groups[by_key[key]], code):
            index = by_key[key]
        elif key:
            index = _find_similar(groups, key, threshold, code)

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


def _code_compatible(group: Dict[str, Any], code: str) -> bool:
    """그룹에 이미 다른 대표명화 코드가 있으면 문자열 유사도로 합치지 않는다."""
    codes = group.get("codes") or set()
    if not code or not codes:
        return True
    return code in codes


def _find_similar(groups: List[Dict[str, Any]], key: str, threshold: float,
                  code: str = "") -> Optional[int]:
    best_index, best_score = None, threshold
    for index, group in enumerate(groups):
        if not _code_compatible(group, code):
            continue
        for existing in group["keys"]:
            score = difflib.SequenceMatcher(None, key, existing).ratio()
            if score >= best_score:
                best_index, best_score = index, score
    return best_index


def _dominant(counter: Optional[Dict[str, int]]) -> str:
    if not counter:
        return ""
    return max(counter.items(), key=lambda kv: (kv[1], kv[0]))[0]


def suggest_standard_name(members: Sequence[Dict[str, Any]],
                          hint_counter: Dict[str, int]) -> Tuple[str, str]:
    """(추천 표준명, 추천 근거). **한글 표기를 먼저** 고르고 법인격 표기를 뗀다.

    같은 핵심 명칭으로 수렴하는 표기들("(주)엘지화학", "엘지화학 주식회사")은
    건수를 합산해 비교하므로, 표기가 나뉘어 있어도 한글 후보가 밀리지 않는다.
    """
    korean: Dict[str, int] = {}
    other: Dict[str, int] = {}

    def add(bucket: Dict[str, int], name: Any, weight: int) -> None:
        core = core_name(name)
        if core:
            bucket[core] = bucket.get(core, 0) + max(1, weight)

    for member in members:
        add(korean if has_hangul(member["raw"]) else other,
            member["raw"], member.get("count", 1))
    for hint, count in (hint_counter or {}).items():
        add(korean if has_hangul(hint) else other, hint, count)

    for bucket, source in ((korean, "한글 표기"), (other, "영문 표기")):
        if bucket:
            # 건수 많은 것 → 짧은 것 → 사전순
            name = max(bucket.items(), key=lambda kv: (kv[1], -len(kv[0]), kv[0]))[0]
            return name, source
    return to_text(members[0]["raw"]), "원본 표기"


def _finalize_group(group: Dict[str, Any], position: int) -> Dict[str, Any]:
    members = sorted(group["members"], key=lambda m: (-m["count"], m["raw"]))
    total = sum(member["count"] for member in members)

    hint_counter: Dict[str, int] = {}
    for member in members:
        for hint, count in (member.get("hints") or {}).items():
            hint_counter[hint] = hint_counter.get(hint, 0) + count

    standard, source = suggest_standard_name(members, hint_counter)
    merged = len(members) > 1

    return {
        "groupId": "g%04d" % position,
        "standardName": standard,
        "suggestedName": standard,
        "suggestedSource": source,
        "count": total,
        "soloCount": sum(member.get("solo", 0) for member in members),
        "jointCount": sum(member.get("joint", 0) for member in members),
        "variantCount": len(members),
        "codes": sorted(group["codes"]),
        "variants": [{"raw": member["raw"], "count": member["count"],
                      "solo": member.get("solo", 0), "joint": member.get("joint", 0)}
                     for member in members],
        # WIPS 대표명화 표기도 별칭으로 둔다. 이것을 치환하지 않으면
        # applicantPrimary 가 대표명화 값을 우선하므로 승인한 표준명이 화면에 안 보인다.
        "aliases": sorted(hint_counter.keys()),
        "needsReview": merged,
        # 표기가 2개 이상 묶인 그룹은 사용자가 확인하기 전까지 병합하지 않는다.
        "approved": not merged,
    }


def build_name_map(groups: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    """{원본 표기: 표준명} 매핑.

    표기가 2개 이상 묶였는데 **승인되지 않은** 그룹은 병합하지 않는다
    (잘못 묶인 그룹이 그대로 반영되어 점수를 왜곡하는 것을 막는다).
    """
    mapping: Dict[str, str] = {}
    for group in groups or []:
        variants = group.get("variants") or []
        if len(variants) > 1 and not group.get("approved", True):
            continue
        standard = to_text(group.get("standardName")) or to_text(group.get("suggestedName"))
        if not standard:
            continue
        names = [to_text(v.get("raw") if isinstance(v, dict) else v) for v in variants]
        names += [to_text(a) for a in (group.get("aliases") or [])]
        for name in names:
            if name and name != standard:
                mapping[name] = standard
    return mapping


def summarize(groups: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    groups = list(groups or [])
    merged = [g for g in groups if g.get("variantCount", 1) > 1]
    pending = [g for g in merged if not g.get("approved", True)]
    return {
        "groupCount": len(groups),
        "variantCount": sum(g.get("variantCount", 1) for g in groups),
        "mergedGroupCount": len(merged),
        "mergedVariantCount": sum(g.get("variantCount", 1) for g in merged),
        "pendingGroupCount": len(pending),
        "jointDocumentCount": sum(g.get("jointCount", 0) for g in groups),
        "documentCount": sum(g.get("count", 0) for g in groups),
    }
