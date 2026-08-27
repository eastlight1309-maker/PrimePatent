# -*- coding: utf-8 -*-
"""시장 중요도.

주요 시장 진입도 + 출원인 시장 영향력 + 상업화·거래 신호 + 패밀리 건수
배점은 config.COMPONENT_MAX 가 단일 기준이다.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..config import (FAMILY_SIZE_BANDS, MARKET_CONSUMER_MAX, MARKET_SUPPLY_MAX)
from .common import AreaResult, Component, band_score, make_component
from .context import AnalysisContext

LABEL = "시장 중요도"

# 상업화·거래 신호 배점 분해 (합 6점)
LICENSE_POINTS = 3.0
ASSIGNMENT_POINTS = 3.0


def score(record: Dict[str, Any], analysis: Dict[str, Any], ctx: AnalysisContext) -> AreaResult:
    components: List[Component] = [
        _market_entry(record, ctx),
        _applicant_power(record, ctx),
        _commercial(record, ctx),
        _family_size(record),
    ]
    return AreaResult(key="market", label=LABEL, components=components)


def _market_entry(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """주요 시장 진입도 = 소비·권리시장 10점 + 제조·공급망시장 5점.

    'WIPS패밀리 개별국 문헌 수(출원기준)' 등에서 얻은 패밀리 국가에 대해
    **출원 유무**만 보고 가중치를 합산한다(건수는 반영하지 않는다).
    """
    family = record.get("_family") or {}
    countries = family.get("countries") or []

    consumer = {c: ctx.config.market_consumer_weights.get(c, 0.0) for c in countries}
    consumer = {c: w for c, w in consumer.items() if w > 0}
    supply = {c: ctx.config.market_supply_weights.get(c, 0.0) for c in countries}
    supply = {c: w for c, w in supply.items() if w > 0}

    consumer_score = min(MARKET_CONSUMER_MAX, sum(consumer.values()))
    supply_score = min(MARKET_SUPPLY_MAX, sum(supply.values()))

    notes = []
    if not countries:
        notes.append("패밀리 국가 정보가 없어 자국만 반영되었습니다.")
    elif not consumer and not supply:
        notes.append("가중치가 설정된 주요국에 진입하지 않았습니다.")
    return make_component(
        "market.entry", "주요 시장 진입도", consumer_score + supply_score,
        detail={"countries": countries,
                "consumerCountries": consumer, "consumerScore": round(consumer_score, 3),
                "supplyCountries": supply, "supplyScore": round(supply_score, 3),
                "countryDocCounts": record.get("familyCountryCounts") or {}},
        notes=notes)


def _applicant_power(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """주제 내 출원인 패밀리 수 백분위 × 2 + 최근 5년 점유 백분위 × 2."""
    keys = record.get("applicantKeys") or [record.get("applicantKey")]
    family_count = max((ctx.applicant_family_count.get(k, 0) for k in keys if k), default=0)
    recent_count = max((ctx.applicant_recent_count.get(k, 0) for k in keys if k), default=0)
    family_rank = ctx.applicant_family_index.rank(family_count) if family_count else 0.0
    recent_rank = ctx.applicant_recent_index.rank(recent_count) if recent_count else 0.0
    value = family_rank * 2.0 + recent_rank * 2.0
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
    """실시권 설정 존재 3점 + 타사 양도·양수 이력 존재 3점.

    데이터가 없는 것과 거래가 없는 것은 다르므로, 컬럼 자체가 없으면
    0점으로 두되 '데이터 없음' 으로 구분 표기한다.
    """
    family = record.get("_family") or {}
    signals = family.get("signals") or {}
    license_flag = signals.get("licenseFlag")
    assignment = signals.get("assignment")

    value = 0.0
    available_max = 0.0
    missing: List[str] = []

    if license_flag is None:
        missing.append("실시권")
    else:
        available_max += LICENSE_POINTS
        if license_flag:
            value += LICENSE_POINTS
    if assignment is None:
        missing.append("양도이력")
    else:
        available_max += ASSIGNMENT_POINTS
        if assignment:
            value += ASSIGNMENT_POINTS

    notes: List[str] = []
    if missing:
        notes.append("데이터 없음: %s" % ", ".join(missing))
    if missing and ctx.config.rescale_missing_commercial and available_max > 0:
        maximum = LICENSE_POINTS + ASSIGNMENT_POINTS
        rescaled = value / available_max * maximum
        notes.append("결측 항목을 제외하고 %g점 만점으로 환산했습니다(%.2f → %.2f)."
                     % (maximum, value, rescaled))
        value = rescaled

    return make_component(
        "market.commercial", "상업화·거래 신호", value,
        detail={"licenseFlag": license_flag, "licenseeCount": signals.get("licenseeCount"),
                "assignment": assignment,
                "recentAssignee": signals.get("recentAssignee"),
                "recentAssignType": signals.get("recentAssignType"),
                "recentAssignDate": signals.get("recentAssignDate"),
                "licensePoints": LICENSE_POINTS if license_flag else 0.0,
                "assignmentPoints": ASSIGNMENT_POINTS if assignment else 0.0,
                "missingSignals": missing},
        notes=notes)


def _family_size(record: Dict[str, Any]) -> Component:
    """패밀리 문헌 수 구간점수 (8건 이상 2점 … 1건 0점)."""
    count = record.get("familyDocCountResolved")
    value = band_score(float(count) if count is not None else None, FAMILY_SIZE_BANDS, 0.0)
    notes = []
    if not count:
        notes.append("패밀리 문헌 수를 확인할 수 없어 0점 처리했습니다.")
    return make_component(
        "market.familySize", "패밀리 건수", value,
        detail={"familyDocCount": count,
                "familyCountryCount": (record.get("_family") or {}).get("countryCount"),
                "source": "WIPS패밀리 문헌 수(출원기준)"},
        notes=notes)
