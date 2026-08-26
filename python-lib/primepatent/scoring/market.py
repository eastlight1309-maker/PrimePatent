# -*- coding: utf-8 -*-
"""시장 중요도 20점 (스펙 6장).

주요 시장 진입도 8 + 출원인 시장 영향력 5 + 상업화·거래 신호 4 + 경쟁사 커버리지 3
"""

from __future__ import annotations

from typing import Any, Dict, List

from .common import AreaResult, Component, make_component
from .context import AnalysisContext

LABEL = "시장 중요도"


def score(record: Dict[str, Any], analysis: Dict[str, Any], ctx: AnalysisContext) -> AreaResult:
    components: List[Component] = [
        _market_entry(record, ctx),
        _applicant_power(record, ctx),
        _commercial(record, ctx),
        _competitor_coverage(record, ctx),
    ]
    return AreaResult(key="market", label=LABEL, components=components)


def _market_entry(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """패밀리 전체 기준 주요국 진입(가중합, 상한 8점)."""
    family = record.get("_family") or {}
    countries = family.get("countries") or []
    weights = ctx.config.market_country_weights
    breakdown = {c: weights.get(c, 0.0) for c in countries if weights.get(c, 0.0) > 0}
    total = sum(breakdown.values())
    return make_component(
        "market.entry", "주요 시장 진입도", total,
        detail={"countries": countries, "scoredCountries": breakdown,
                "weightSum": round(total, 3)},
        notes=[] if breakdown else ["가중치가 설정된 주요국에 진입하지 않았습니다."])


def _applicant_power(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """주제 내 출원인 패밀리 수 백분위 × 3 + 최근 5년 점유 백분위 × 2."""
    keys = record.get("applicantKeys") or [record.get("applicantKey")]
    family_count = max((ctx.applicant_family_count.get(k, 0) for k in keys if k), default=0)
    recent_count = max((ctx.applicant_recent_count.get(k, 0) for k in keys if k), default=0)
    family_rank = ctx.applicant_family_index.rank(family_count) if family_count else 0.0
    recent_rank = ctx.applicant_recent_index.rank(recent_count) if recent_count else 0.0
    value = family_rank * 3.0 + recent_rank * 2.0
    share = (family_count / ctx.topic_family_total) if ctx.topic_family_total else 0.0
    return make_component(
        "market.applicantPower", "출원인 시장 영향력", value,
        detail={"applicant": record.get("applicantPrimary"),
                "applicantFamilyCount": family_count,
                "applicantRecent5yCount": recent_count,
                "topicFamilyTotal": ctx.topic_family_total,
                "sharePercent": round(share * 100, 2),
                "familyRank": round(family_rank, 3), "recentRank": round(recent_rank, 3)},
        notes=[] if family_count else ["출원인 정보를 확인할 수 없습니다."])


def _commercial(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """실시권 2 + 양도 1 + 복수국 등록 1. 데이터 없음은 별도 표기."""
    family = record.get("_family") or {}
    signals = family.get("signals") or {}
    license_flag = signals.get("licenseFlag")
    assignment = signals.get("assignment")
    registered = family.get("registeredCountryCount") or 0

    value = 0.0
    available_max = 0.0
    missing: List[str] = []

    if license_flag is None:
        missing.append("실시권")
    else:
        available_max += 2.0
        if license_flag:
            value += 2.0
    if assignment is None:
        missing.append("양도이력")
    else:
        available_max += 1.0
        if assignment:
            value += 1.0
    available_max += 1.0
    if registered >= 2:
        value += 1.0

    notes: List[str] = []
    if missing:
        notes.append("데이터 없음: %s" % ", ".join(missing))
    if missing and ctx.config.rescale_missing_commercial and available_max > 0:
        rescaled = value / available_max * 4.0
        notes.append("결측 항목을 제외하고 4점 만점으로 환산했습니다(%.2f → %.2f)." % (value, rescaled))
        value = rescaled

    return make_component(
        "market.commercial", "상업화·거래 신호", value,
        detail={"licenseFlag": license_flag, "licenseeCount": signals.get("licenseeCount"),
                "assignment": assignment, "recentAssignee": signals.get("recentAssignee"),
                "registeredCountryCount": registered,
                "registeredCountries": family.get("registeredCountries") or [],
                "missingSignals": missing,
                "availableMax": available_max},
        notes=notes)


def _competitor_coverage(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """고유 비자기 피인용 출원인 수 백분위 × 3."""
    value_raw = ctx.unique_citing_applicants(record)
    rank, group, size = ctx.rank("uniqueCitingApplicants", record, value_raw)
    method = record.get("_uniqueCitingApplicantsMethod")
    notes = []
    if method == "proxy":
        notes.append("피인용 문헌의 출원인을 모집단에서 확인할 수 없어 '타인 피인용 문헌 수'를 대용지표로 사용했습니다.")
    return make_component(
        "market.competitorCoverage", "경쟁사 커버리지", rank * 3.0,
        detail={"uniqueCitingApplicants": value_raw, "method": method,
                "unresolvedCitations": record.get("_citingUnresolved"),
                "rank": round(rank, 3), "peerGroup": group, "peerN": size,
                "peerStats": ctx.peer_stats("uniqueCitingApplicants", record)},
        notes=notes)
