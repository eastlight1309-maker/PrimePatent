# -*- coding: utf-8 -*-
"""기술 중요도 30점 (스펙 5장).

Topic 적합도 8 + 핵심 기술기여도 8 + 문제·효과 중요성 6 + 기술 범용성 4 + 후속개량·분할 신호 4
"""

from __future__ import annotations

from typing import Any, Dict, List

from .common import AreaResult, Component, make_component
from .context import AnalysisContext

LABEL = "기술 중요도"

# 5.4 기술 범용성: LLM 0~4 → 3점 환산 + CPC 백분위 1점 (합계 상한 4)
GENERALITY_LLM_WEIGHT = 0.75
GENERALITY_CPC_MAX = 1.0


def score(record: Dict[str, Any], analysis: Dict[str, Any], ctx: AnalysisContext) -> AreaResult:
    components: List[Component] = [
        _topic_fit(analysis, ctx),
        _contribution(analysis),
        _problem_effect(analysis),
        _generality(record, analysis, ctx),
        _follow_up(record, analysis),
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


def _follow_up(record: Dict[str, Any], analysis: Dict[str, Any]) -> Component:
    """분할·계속출원 2 + 패밀리 내 후속출원 1 + 복수 청구항 카테고리 1."""
    family = record.get("_family") or {}
    signals = family.get("signals") or {}
    value = 0.0
    detail: Dict[str, Any] = {}

    divisional = signals.get("divisional")
    if divisional is True:
        value += 2.0
    detail["divisional"] = divisional

    member_count = family.get("memberCount") or 1
    doc_count = record.get("familyDocCount") or record.get("epoFamilyDocCount") or member_count
    has_follow_up = (member_count > family.get("countryCount", member_count)) or \
        (doc_count and family.get("countryCount") and doc_count > family.get("countryCount"))
    if has_follow_up:
        value += 1.0
    detail["familyMemberCount"] = member_count
    detail["familyDocCount"] = doc_count
    detail["familyCountryCount"] = family.get("countryCount")

    claim_analysis = analysis.get("claimAnalysis") or {}
    multi_category = bool(claim_analysis.get("multiCategoryIndependentClaims"))
    if not multi_category and (record.get("independentClaimCount") or 0) >= 2:
        multi_category = _looks_multi_category(record)
    if multi_category:
        value += 1.0
    detail["multiCategoryIndependentClaims"] = multi_category

    return make_component("tech.followUp", "후속개량·분할 신호", value, detail=detail)


_CATEGORY_TOKENS = (
    ("장치", "패키지", "디바이스", "apparatus", "device", "package", "소자", "기판", "시스템"),
    ("방법", "제조방법", "method", "process", "공정"),
)


def _looks_multi_category(record: Dict[str, Any]) -> bool:
    text = " ".join([
        str(record.get("independentClaims") or ""),
        str(record.get("title") or ""),
    ]).lower()
    if not text.strip():
        return False
    hits = 0
    for tokens in _CATEGORY_TOKENS:
        if any(token.lower() in text for token in tokens):
            hits += 1
    return hits >= 2
