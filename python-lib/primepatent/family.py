# -*- coding: utf-8 -*-
"""패밀리 그룹핑 및 대표문헌 선정 (스펙 3.1).

대표문헌 우선순위: 등록·존속 > 등록·소멸 > 공개·심사 중 > 거절·취하
동순위 tie-break: 설정된 국가 우선순위 → 청구항 수 → 피인용 수 → 이른 우선일 → 문헌번호
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from . import status as status_mod
from .config import ScoringConfig
from .records import family_country_sources, family_key
from .parsing import to_text


def build_families(records: List[Dict[str, Any]], config: ScoringConfig,
                   as_of: Optional[date] = None) -> Dict[str, Dict[str, Any]]:
    """{familyKey: {members, representative, countries, signals}}"""
    as_of = as_of or date.today()
    groups: Dict[str, List[Dict[str, Any]]] = {}

    for record in records:
        record["_statusCode"] = status_mod.classify(record, as_of)
        record["_statusLabel"] = status_mod.STATUS_LABEL[record["_statusCode"]]
        record["_remainingTerm"] = status_mod.remaining_term_years(record, as_of)
        key = family_key(record, config.family_id_source)
        record["_familyKey"] = key
        groups.setdefault(key, []).append(record)

    priority = [c.upper() for c in (config.representative_country_priority or [])]
    families: Dict[str, Dict[str, Any]] = {}

    for key, members in groups.items():
        representative = max(members, key=lambda r: _rep_sort_key(r, priority))
        countries: List[str] = []
        country_sources: Dict[str, str] = {}
        for member in members:
            for country, origin in family_country_sources(member, config.family_country_source):
                if country and country not in countries:
                    countries.append(country)
                    country_sources[country] = origin

        registered = sorted({
            member.get("country") for member in members
            if member.get("_statusCode") in (status_mod.GRANTED_ALIVE,
                                             status_mod.GRANTED_EXPIRING,
                                             status_mod.LAPSED)
            and member.get("country")})

        signals = _aggregate_signals(members)
        family = {
            "familyKey": key,
            "memberCount": len(members),
            "members": [m.get("_key") for m in members],
            "countries": countries,
            "countrySources": country_sources,
            "countryCount": len(countries),
            "registeredCountries": registered,
            "registeredCountryCount": len(registered),
            "representativeKey": representative.get("_key"),
            "signals": signals,
            "aliveMemberCount": sum(
                1 for m in members if m.get("_statusCode") in (status_mod.GRANTED_ALIVE,
                                                              status_mod.GRANTED_EXPIRING)),
        }
        families[key] = family
        for member in members:
            member["_isRepresentative"] = member is representative
            member["_family"] = family
    return families


def _rep_sort_key(record: Dict[str, Any], country_priority: List[str]):
    code = record.get("_statusCode", status_mod.UNKNOWN)
    country = (record.get("country") or "").upper()
    try:
        country_rank = -country_priority.index(country)
    except ValueError:
        country_rank = -len(country_priority) - 1
    priority_date = record.get("earliestPriorityDate")
    date_rank = -priority_date.toordinal() if isinstance(priority_date, date) else -10 ** 9
    return (
        status_mod.STATUS_PRIORITY.get(code, 0),
        country_rank,
        record.get("claimCount") or 0,
        record.get("forwardCitationCountResolved") or 0,
        date_rank,
        to_text(record.get("_key")),
    )


def _aggregate_signals(members: List[Dict[str, Any]]) -> Dict[str, Any]:
    """패밀리 단위 이벤트 신호(하나라도 있으면 True, 정보 자체가 없으면 None)."""

    def any_flag(field: str) -> Optional[bool]:
        seen = False
        for member in members:
            value = member.get(field)
            if value is True:
                return True
            if value is False:
                seen = True
        return False if seen else None

    def any_count(field: str) -> Optional[int]:
        values = [member.get(field) for member in members if member.get(field) is not None]
        return max(int(v) for v in values) if values else None

    def any_text(field: str) -> Optional[str]:
        for member in members:
            text = to_text(member.get(field))
            if text:
                return text
        return None

    divisional = any_flag("divisionalFlag")
    if divisional is not True and any(to_text(m.get("parentApplicationNumber")) for m in members):
        divisional = True

    trial_count = any_count("trialCount")
    litigation_count = any_count("litigationCount")
    trial_types = sorted({t for m in members for t in (m.get("trialType") or []) if t})

    license_flag = any_flag("licenseFlag")
    licensee_count = any_count("licenseeCount")
    if license_flag is not True and licensee_count:
        license_flag = licensee_count > 0

    assign_flag = any_flag("rightsChangeFlag")
    if assign_flag is not True and (any_text("recentAssignee") or any_text("recentAssignDate")):
        assign_flag = True

    return {
        "divisional": divisional,
        "trialCount": trial_count,
        "trialTypes": trial_types,
        "litigationCount": litigation_count,
        "hasDispute": _has_dispute(trial_count, litigation_count, trial_types),
        "licenseFlag": license_flag,
        "licenseeCount": licensee_count,
        "assignment": assign_flag,
        "recentAssignee": any_text("recentAssignee"),
        "examinerCitedByOthers": any(bool(m.get("examinerForwardCitations")) for m in members),
    }


def _has_dispute(trial_count: Optional[int], litigation_count: Optional[int],
                 trial_types: List[str]) -> Optional[bool]:
    if trial_count is None and litigation_count is None and not trial_types:
        return None
    return bool((trial_count or 0) > 0 or (litigation_count or 0) > 0 or trial_types)


def representative_records(records: List[Dict[str, Any]], families: Dict[str, Dict[str, Any]],
                           dedupe: bool = True) -> List[Dict[str, Any]]:
    if not dedupe:
        return list(records)
    return [r for r in records if r.get("_isRepresentative")]
