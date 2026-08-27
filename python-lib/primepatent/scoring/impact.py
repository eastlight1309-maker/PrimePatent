# -*- coding: utf-8 -*-
"""영향력·경쟁성.

경쟁사 커버리지 + 연령보정 피인용 영향력 + 기술 선도성
배점은 config.COMPONENT_MAX 가 단일 기준이다.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from ..config import COMPONENT_MAX
from ..parsing import safe_log1p
from .common import AreaResult, Component, make_component
from .context import AnalysisContext

LABEL = "영향력·경쟁성"


def score(record: Dict[str, Any], analysis: Dict[str, Any], ctx: AnalysisContext) -> AreaResult:
    components: List[Component] = [
        _competitor_coverage(record, ctx),
        _citation(record, ctx),
        _leadership(record, ctx),
    ]
    return AreaResult(key="impact", label=LABEL, components=components)


def _competitor_coverage(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """고유 비자기 피인용 출원인 수 백분위 × 5.

    '타인 피인용 문헌번호(F1)' 를 근거로 하되, 업로드 모집단 안에서 각 인용문헌의
    출원인을 해석해 **고유 출원인 수**를 센다(같은 회사가 여러 건 인용해도 1로 셈).
    해석률이 낮으면 문헌 수를 대용지표로 쓰고 그 사실을 method 로 표기한다.
    """
    maximum = COMPONENT_MAX["impact.competitorCoverage"]
    value_raw = ctx.unique_citing_applicants(record)
    rank, group, size = ctx.rank("uniqueCitingApplicants", record, value_raw)
    method = record.get("_uniqueCitingApplicantsMethod")
    citing_docs = len(record.get("otherForwardCitations") or [])
    notes = []
    if method == "proxy":
        notes.append("피인용 문헌의 출원인을 모집단에서 확인할 수 없어 "
                     "'타인 피인용 문헌 수'를 대용지표로 사용했습니다.")
    return make_component(
        "impact.competitorCoverage", "경쟁사 커버리지", rank * maximum,
        detail={"uniqueCitingApplicants": value_raw,
                "otherForwardCitationDocs": citing_docs,
                "method": method,
                "unresolvedCitations": record.get("_citingUnresolved"),
                "rank": round(rank, 3), "peerGroup": group, "peerN": size,
                "peerStats": ctx.peer_stats("uniqueCitingApplicants", record)},
        notes=notes)


def _raw_citation_stats(record: Dict[str, Any], ctx: AnalysisContext):
    """피인용 비교집단 분포를 원값(건수) 기준으로 환산해 돌려준다."""
    stats = ctx.peer_stats("logForward", record)
    if not stats:
        return None
    converted = dict(stats)
    for key in ("min", "p25", "median", "p75", "max", "mean"):
        if converted.get(key) is not None:
            raw = math.expm1(float(converted[key]))
            converted[key] = int(round(raw)) if abs(raw - round(raw)) < 0.01 else round(raw, 1)
    converted["unit"] = "피인용 건수(로그 역변환)"
    return converted


def _citation(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """LN(1+피인용) 의 동일주제·동일우선연도 백분위 × 15.

    비교집단 표본이 부족하면 연간 피인용 속도 백분위로 대체한다.
    """
    maximum = COMPONENT_MAX["impact.citation"]
    forward = record.get("forwardCitationCountResolved") or 0
    log_value = safe_log1p(forward)
    rank, group, size = ctx.rank("logForward", record, log_value)
    method = "logForward"
    notes: List[str] = []
    if group in ("insufficient", "none"):
        speed = ctx.citation_speed(record)
        speed_rank, speed_group, speed_size = ctx.rank("citationSpeed", record, speed)
        if speed_group not in ("insufficient", "none"):
            rank, group, size, method = speed_rank, speed_group, speed_size, "citationSpeed"
            notes.append("비교집단 표본 부족으로 연간 피인용 속도 백분위를 사용했습니다.")
    speed = ctx.citation_speed(record)
    return make_component(
        "impact.citation", "연령보정 피인용 영향력", rank * maximum,
        detail={"forwardCitations": forward, "logForward": round(log_value, 4),
                "citationSpeed": None if speed is None else round(speed, 3),
                "method": method, "rank": round(rank, 3),
                "peerGroup": group, "peerN": size,
                "peerStats": _raw_citation_stats(record, ctx)},
        notes=notes)


def _leadership(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """기술 선도성 = (1 − 동일주제 최초우선일 백분위) × 5.

    주제 안에서 얼마나 이른 시점의 출원인지만 본다(빠를수록 높은 점수).
    """
    maximum = COMPONENT_MAX["impact.leadership"]
    ordinal = ctx.priority_ordinal(record)
    date_rank, group, size = ctx.rank("priorityOrdinal", record, ordinal)
    value = (1.0 - date_rank) * maximum if ordinal is not None else 0.0
    notes = []
    if ordinal is None:
        notes.append("최초우선일 정보가 없어 0점 처리했습니다.")
    return make_component(
        "impact.leadership", "기술 선도성", value,
        detail={"priorityDate": record.get("earliestPriorityDate"),
                "priorityRank": round(date_rank, 3),
                "earlinessRank": round(1.0 - date_rank, 3),
                "peerGroup": group, "peerN": size,
                "peerStats": _priority_year_stats(ctx, record)},
        notes=notes)


def _priority_year_stats(ctx: AnalysisContext, record: Dict[str, Any]):
    """우선일 분포를 연도로 환산해 보여 준다(ordinal 숫자는 읽을 수 없으므로)."""
    from datetime import date as _date
    stats = ctx.peer_stats("priorityOrdinal", record)
    if not stats:
        return None
    converted = dict(stats)
    for key in ("min", "p25", "median", "p75", "max", "mean"):
        value = converted.get(key)
        if value is None:
            continue
        try:
            converted[key] = _date.fromordinal(int(round(float(value)))).year
        except (ValueError, OverflowError):
            converted[key] = None
    converted["unit"] = "최초우선연도"
    return converted
