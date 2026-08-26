# -*- coding: utf-8 -*-
"""원본 행(row) + 매핑 → 표준 레코드(dict) 변환 및 파생값 계산."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

from .columns import BOOL, DATE, ENTITY_LIST, FIELD_BY_KEY, FLOAT, INT, LIST
from .parsing import (countries_of, country_of, normalize_country, to_bool,
                      to_date, to_entity_list, to_float, to_int, to_list, to_text)

_CORP_SUFFIX_RE = re.compile(
    r"(주식회사|\(주\)|\(유\)|유한회사|co\.,?\s*ltd\.?|co\.\s*ltd|corporation|corp\.?|"
    r"incorporated|inc\.?|limited|ltd\.?|llc|gmbh|s\.a\.?|n\.v\.?|b\.v\.?|kabushiki\s*kaisha|"
    r"company|holdings?|group|株式会社|有限公司|股份有限公司)", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^0-9a-z가-힣]+")


def _cast(value: Any, kind: str):
    if kind == DATE:
        return to_date(value)
    if kind == INT:
        return to_int(value)
    if kind == FLOAT:
        return to_float(value)
    if kind == ENTITY_LIST:
        return to_entity_list(value)
    if kind == LIST:
        return to_list(value)
    if kind == BOOL:
        return to_bool(value)
    return to_text(value)


def normalize_entity_name(name: Any) -> str:
    """출원인/권리자명 정규화 키(법인격 표기 제거, 공백/기호 제거)."""
    text = to_text(name).lower()
    if not text:
        return ""
    text = _CORP_SUFFIX_RE.sub(" ", text)
    text = _NON_ALNUM_RE.sub("", text)
    return text[:60]


def build_record(row: Dict[str, Any], mapping: Dict[str, Dict], row_index: int,
                 applicant_map: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """한 행을 표준 레코드로 변환한다.

    applicant_map 은 사용자가 **승인한** 출원인 표준명({원본 표기: 표준명})이며,
    승인 전에는 None 이 들어와 원본 표기를 그대로 사용한다.
    """
    rec: Dict[str, Any] = {"_rowIndex": row_index}
    available: Dict[str, bool] = {}

    for field_key, info in mapping.items():
        spec = FIELD_BY_KEY.get(field_key)
        if spec is None:
            continue
        raw = row.get(info.get("column"))
        value = _cast(raw, spec.kind)
        rec[field_key] = value
        available[field_key] = not (value is None or value == "" or value == [])

    for spec in FIELD_BY_KEY.values():
        rec.setdefault(spec.key, [] if spec.kind in (LIST, ENTITY_LIST) else None)
        available.setdefault(spec.key, False)

    rec["_available"] = available
    _apply_applicant_map(rec, applicant_map)
    _derive(rec)
    return rec


def _apply_applicant_map(rec: Dict[str, Any], applicant_map: Optional[Dict[str, str]]) -> None:
    """승인된 표준명으로 출원인·권리자 표기를 통일한다."""
    if not applicant_map:
        return
    changed = []
    for field_key in ("applicant", "currentAssignee"):
        values = rec.get(field_key) or []
        if not values:
            continue
        replaced = []
        for name in values:
            standard = applicant_map.get(name)
            if standard and standard != name:
                changed.append(name)
            replaced.append(standard or name)
        # 표준화 결과 중복이 생길 수 있으므로 순서를 유지하며 제거
        seen = set()
        rec[field_key] = [n for n in replaced if not (n in seen or seen.add(n))]
    for field_key in ("applicantNormalized", "currentAssigneeNormalized"):
        text = to_text(rec.get(field_key))
        standard = applicant_map.get(text) if text else None
        if standard:
            rec[field_key] = standard
    rec["_applicantStandardized"] = bool(changed)
    if changed:
        rec["_applicantOriginal"] = changed


def _first_date(*values) -> Optional[date]:
    dates = [v for v in values if isinstance(v, date)]
    return min(dates) if dates else None


def _derive(rec: Dict[str, Any]) -> None:
    """파생 필드 계산."""
    # --- 문헌번호 / 국가 ---
    doc = to_text(rec.get("docNumber"))
    if not doc:
        doc = to_text(rec.get("registrationNumber")) or to_text(rec.get("publicationNumber")) \
            or to_text(rec.get("applicationNumber"))
    rec["docNumber"] = doc

    country = normalize_country(rec.get("country")) or country_of(doc) \
        or country_of(rec.get("applicationNumber")) or country_of(rec.get("publicationNumber"))
    rec["country"] = country or ""

    # --- 최초 우선일 ---
    priority_dates = [to_date(v) for v in (rec.get("priorityDate") or [])]
    earliest = _first_date(rec.get("earliestPriorityDate"), *priority_dates,
                           rec.get("applicationDate"))
    rec["earliestPriorityDate"] = earliest
    rec["priorityYear"] = earliest.year if isinstance(earliest, date) else None

    # --- 패밀리 ---
    wips_id = to_text(rec.get("familyId"))
    epo_id = to_text(rec.get("epoFamilyId"))
    rec["familyIdWips"] = wips_id
    rec["familyIdEpo"] = epo_id

    wips_members = list(rec.get("familyMembers") or [])
    epo_members = list(rec.get("epoFamilyMembers") or [])
    rec["familyCountriesWips"] = countries_of(wips_members)
    rec["familyCountriesEpo"] = countries_of(epo_members)

    # --- 청구항 수 보정 ---
    if rec.get("claimCount") is None and rec.get("allClaims"):
        rec["claimCount"] = _guess_claim_count(rec.get("allClaims"))
    if rec.get("independentClaimCount") is None and rec.get("independentClaims"):
        rec["independentClaimCount"] = _guess_independent_count(rec.get("independentClaims"))

    # --- 인용 수 보정(수치 컬럼이 없으면 번호 목록 길이로 대체) ---
    rec["forwardCitationCountResolved"] = _resolve_count(
        rec.get("forwardCitationCount"), rec.get("forwardCitations"))
    rec["backwardCitationCountResolved"] = _resolve_count(
        rec.get("backwardCitationCount"), rec.get("backwardCitations"))
    rec["selfForwardCount"] = _resolve_count(None, rec.get("selfForwardCitations"))
    rec["otherForwardCount"] = _resolve_count(None, rec.get("otherForwardCitations"))
    if rec["otherForwardCount"] == 0 and rec["forwardCitationCountResolved"] and \
            not rec.get("otherForwardCitations") and rec.get("selfForwardCitations"):
        rec["otherForwardCount"] = max(
            0, rec["forwardCitationCountResolved"] - rec["selfForwardCount"])

    # --- 출원인 키 ---
    applicants = rec.get("applicant") or []
    normalized = to_text(rec.get("applicantNormalized"))
    code = to_text(rec.get("applicantNormalizedCode"))
    primary = normalized or (applicants[0] if applicants else "")
    rec["applicantPrimary"] = primary
    rec["applicantKey"] = (code.lower().strip() if code else "") or \
        normalize_entity_name(primary) or "unknown"
    rec["applicantKeys"] = sorted({
        normalize_entity_name(a) for a in ([normalized] + list(applicants)) if a
    } - {""})

    assignee = rec.get("currentAssignee") or []
    rec["assigneePrimary"] = to_text(rec.get("currentAssigneeNormalized")) or \
        (assignee[0] if assignee else "")
    rec["assigneeKey"] = normalize_entity_name(rec["assigneePrimary"])

    # --- CPC 서브그룹 ---
    cpc = rec.get("cpcAll") or []
    rec["cpcSubgroups"] = sorted({c.replace(" ", "").upper() for c in cpc if c})
    rec["cpcMainGroups"] = sorted({_cpc_main_group(c) for c in rec["cpcSubgroups"] if _cpc_main_group(c)})

    # --- 텍스트 존재 ---
    rec["hasClaimText"] = bool(to_text(rec.get("mainClaim")) or to_text(rec.get("independentClaims")))
    rec["_key"] = rec.get("docNumber") or rec.get("applicationNumber") or f"row-{rec['_rowIndex']}"


def _cpc_main_group(code: str) -> str:
    match = re.match(r"^([A-Z]\d{2}[A-Z]\d{1,4})", (code or "").upper())
    return match.group(1) if match else ""


def _resolve_count(count: Optional[int], items: Optional[Sequence[str]]) -> int:
    if count is not None:
        try:
            return max(0, int(count))
        except (TypeError, ValueError):
            pass
    return len(items or [])


def _guess_claim_count(text: Any) -> Optional[int]:
    body = to_text(text)
    if not body:
        return None
    matches = re.findall(r"(?m)^\s*(?:청구항|Claim|claim)?\s*\[?(\d{1,3})\]?[\.\)]", body)
    if matches:
        try:
            return max(int(m) for m in matches)
        except ValueError:
            return None
    return None


def _guess_independent_count(text: Any) -> Optional[int]:
    body = to_text(text)
    if not body:
        return None
    matches = re.findall(r"(?m)^\s*\[?(?:청구항\s*)?(\d{1,3})\]?[\.\)]", body)
    return len(set(matches)) if matches else None


def family_key(rec: Dict[str, Any], source: str = "wips") -> str:
    """패밀리 그룹 키. 값이 없으면 문헌 자체를 단독 패밀리로 처리."""
    primary = rec.get("familyIdEpo") if source == "epo" else rec.get("familyIdWips")
    secondary = rec.get("familyIdWips") if source == "epo" else rec.get("familyIdEpo")
    key = to_text(primary) or to_text(secondary)
    if key:
        return f"F:{key}"
    priority = to_text(rec.get("earliestPriorityNumber"))
    if priority:
        return f"P:{priority}"
    return "S:" + hashlib.md5(str(rec.get("_key")).encode("utf-8")).hexdigest()[:12]


def family_countries(rec: Dict[str, Any], source: str = "auto") -> List[str]:
    """패밀리 국가 커버리지(고유 국가). 패밀리 정보가 없으면 자국만."""
    wips = rec.get("familyCountriesWips") or []
    epo = rec.get("familyCountriesEpo") or []
    if source == "wips":
        countries = wips or epo
    elif source == "epo":
        countries = epo or wips
    else:  # auto: 넓은 쪽
        countries = wips if len(wips) >= len(epo) else epo
    countries = list(countries)
    own = rec.get("country")
    if own and own not in countries:
        countries.append(own)
    designated = rec.get("designatedStates") or []
    for item in designated:
        code = normalize_country(item)
        if code and code not in countries:
            countries.append(code)
    return countries


def build_records(rows: Sequence[Dict[str, Any]], mapping: Dict[str, Dict],
                  applicant_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """행 목록을 레코드로 변환한다.

    동일 문헌번호가 중복된 파일에서 레코드 키가 겹치면 LLM 분석 결과가
    엉뚱한 문헌에 매칭될 수 있으므로, 중복 키에는 행 번호를 덧붙여 유일성을 보장한다.
    """
    records = [build_record(row, mapping, i, applicant_map) for i, row in enumerate(rows)]
    seen: Dict[str, int] = {}
    for record in records:
        key = record["_key"]
        if key in seen:
            seen[key] += 1
            record["_duplicateKey"] = key
            record["_key"] = "%s#%d" % (key, record["_rowIndex"])
        else:
            seen[key] = 0
    return records
