# -*- coding: utf-8 -*-
"""기술 중요도 (Topic 적합도 + 핵심 기술기여도 + 문제·효과 중요성 + 기술 범용성).

배점은 config.COMPONENT_MAX 가 단일 기준이다.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..config import mixed_max
from .common import AreaResult, Component, make_component
from .context import AnalysisContext

LABEL = "기술 중요도"

# 5.4 기술 범용성: LLM 0~4 → 3점 환산 + CPC 백분위 1점 (합계 상한 4)
# 배점 분해는 config.COMPONENT_MIXED_SPLIT 이 단일 기준이다.
GENERALITY_CPC_MAX, _GENERALITY_LLM_MAX = mixed_max("tech.generality")
GENERALITY_LLM_WEIGHT = _GENERALITY_LLM_MAX / 4.0        # LLM 0~4 → LLM 상한으로 환산


def score(record: Dict[str, Any], analysis: Dict[str, Any], ctx: AnalysisContext) -> AreaResult:
    components: List[Component] = [
        _topic_fit(analysis, ctx),
        _contribution(analysis),
        _problem_effect(analysis),
        _generality(record, analysis, ctx),
    ]
    return AreaResult(key="tech", label=LABEL, components=components)


def topic_fit_score(fit_percent: float, mode: str = "softened") -> float:
    """적합도(%) → 기술적합점수(0~8)."""
    fit = max(0.0, min(100.0, float(fit_percent or 0.0)))
    if mode == "linear":
        return fit / 100.0 * 8.0
    return min(8.0, max(0.0, (fit - 60.0) / 40.0 * 8.0))


def _topic_fit(analysis: Dict[str, Any], ctx: AnalysisContext) -> Component:
    fit = float(analysis.get("topicFitPercent") or 0.0)
    value = topic_fit_score(fit, ctx.config.topic_fit_mode)
    notes = []
    if analysis.get("status") != "ok":
        notes.append("LLM 적합도 평가 미수행(%s)" % (analysis.get("message") or analysis.get("status")))
    return make_component(
        "tech.topicFit", "Primary Topic 적합도", value,
        llm_score=round(value, 3),
        detail={"topicFitPercent": round(fit, 1), "mode": ctx.config.topic_fit_mode,
                "gateThreshold": ctx.config.gate_topic_fit_min},
        notes=notes)


def _contribution(analysis: Dict[str, Any]) -> Component:
    value = float(analysis.get("coreContributionScore") or 0.0)
    return make_component(
        "tech.contribution", "핵심 기술기여도", value, llm_score=round(value, 3),
        detail={"rationale": analysis.get("rationale"),
                "keyFeatures": analysis.get("keyFeatures") or []},
        notes=[] if analysis.get("status") == "ok" else ["LLM 미수행으로 0점 처리"])


def _problem_effect(analysis: Dict[str, Any]) -> Component:
    problem = float(analysis.get("problemImportanceScore") or 0.0)
    effect = float(analysis.get("effectEvidenceScore") or 0.0)
    return make_component(
        "tech.problemEffect", "문제·효과 중요성", problem + effect,
        llm_score=round(problem + effect, 3),
        detail={"problemImportance": problem, "effectEvidence": effect},
        notes=[] if analysis.get("status") == "ok" else ["LLM 미수행으로 0점 처리"])


def _generality(record: Dict[str, Any], analysis: Dict[str, Any],
                ctx: AnalysisContext) -> Component:
    llm_raw = float(analysis.get("generalityScore") or 0.0)
    llm_part = llm_raw * GENERALITY_LLM_WEIGHT           # 최대 3점
    subgroups = len(record.get("cpcSubgroups") or [])
    rank, group, size = ctx.rank("cpcSubgroups", record, subgroups or None)
    cpc_part = rank * GENERALITY_CPC_MAX if subgroups else 0.0
    return make_component(
        "tech.generality", "기술 범용성", llm_part + cpc_part,
        llm_score=round(llm_part, 3), quant_score=round(cpc_part, 3),
        detail={"llmGenerality": llm_raw, "cpcSubgroupCount": subgroups,
                "cpcRank": round(rank, 3), "peerGroup": group, "peerN": size,
                "cpcPeerStats": ctx.peer_stats("cpcSubgroups", record),
                "mainGroupCount": len(record.get("cpcMainGroups") or [])},
        notes=[] if subgroups else ["CPC 정보가 없어 정량 보조점수 0점"])
