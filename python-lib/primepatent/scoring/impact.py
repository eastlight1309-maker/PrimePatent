# -*- coding: utf-8 -*-
"""영향력·경쟁성.

경쟁사 커버리지(외부TR) + 연령보정 피인용 영향력(TR) + 기술 선도성
배점은 config.COMPONENT_MAX 가 단일 기준이다.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..config import COMPONENT_MAX
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


def _fmt_max(value: float) -> str:
    """배점을 사람이 읽는 형태로(7.0 -> '7')."""
    return str(int(value)) if float(value) == int(value) else str(value)


def _max_ratio_component(record: Dict[str, Any], ctx: AnalysisContext,
                         key: str, label: str, metric: str,
                         metric_label: str) -> Component:
    """(대상 건의 값 / 모집단 최대값) x 배점.

    백분위가 아니라 **모집단 최대값 대비 비율**을 그대로 쓴다.
    모집단은 백분위 비교집단과 같은 단위(채점 대상 문헌)로 잡는다.
    """
    maximum = COMPONENT_MAX[key]
    ratio, value, population_max = ctx.max_ratio(metric, record)
    notes: List[str] = []
    if ratio is None:
        if value is None:
            notes.append("'%s' 값이 없어 0점 처리했습니다. 컬럼 매핑에서 '%s' 를 확인하세요."
                         % (metric_label, metric_label))
        else:
            notes.append("모집단의 '%s' 최대값이 0이라 비율을 계산할 수 없어 0점 처리했습니다."
                         % metric_label)
    return make_component(
        key, label, (ratio or 0.0) * maximum,
        detail={"metric": metric_label,
                "value": value,
                "populationMax": population_max,
                "ratio": None if ratio is None else round(ratio, 4),
                "populationN": len(ctx.peer_records),
                "formula": "(%s / 모집단 %s 최대값) x %s"
                           % (metric_label, metric_label, _fmt_max(maximum))},
        notes=notes)


def _competitor_coverage(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """경쟁사 커버리지 = (대상 건의 외부TR / 모집단 중 외부TR 최대값) x 7."""
    return _max_ratio_component(record, ctx, "impact.competitorCoverage",
                                "경쟁사 커버리지", "externalTr", "외부TR")


def _citation(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """연령보정 피인용 영향력 = (대상 건의 TR / 모집단 중 TR 최대값) x 13.

    연령보정은 TR 지표 자체에 이미 반영된 것으로 본다.
    """
    return _max_ratio_component(record, ctx, "impact.citation",
                                "연령보정 피인용 영향력", "totalTr", "TR")


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
