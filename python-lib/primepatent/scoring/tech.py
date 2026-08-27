# -*- coding: utf-8 -*-
"""기술 중요도.

Primary Topic 적합도(IPURE AI Score) + 독립청구항 내 핵심기술 중심성
+ 핵심기술의 청구항 확장도 + 독립청구항 유형 다양성
배점은 config.COMPONENT_MAX 가 단일 기준이다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..config import COMPONENT_MAX
from .common import AreaResult, Component, make_component
from .context import AnalysisContext

LABEL = "기술 중요도"


def score(record: Dict[str, Any], analysis: Dict[str, Any], ctx: AnalysisContext) -> AreaResult:
    components: List[Component] = [
        _topic_fit(record, ctx),
        _core_centrality(analysis),
        _claim_expansion(analysis),
        _claim_type_diversity(analysis),
    ]
    return AreaResult(key="tech", label=LABEL, components=components)


def ipure_percent(record: Dict[str, Any], score_max: float) -> Optional[float]:
    """IPURE AI Score 를 0~100% 로 환산한다. 값이 없으면 None."""
    raw = record.get("ipureAiScore")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:          # NaN
        return None
    divisor = float(score_max) if score_max else 100.0
    return max(0.0, min(100.0, value / divisor * 100.0))


def _topic_fit(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """IPURE AI Score 적용: 백분율 × 8점."""
    maximum = COMPONENT_MAX["tech.topicFit"]
    percent = ipure_percent(record, ctx.config.ipure_score_max)
    notes = []
    if percent is None:
        value = 0.0
        notes.append("IPURE AI Score 컬럼이 없거나 값이 비어 있어 0점 처리했습니다. "
                     "컬럼 매핑에서 'IPURE AI Score' 를 지정하십시오.")
    else:
        value = percent / 100.0 * maximum
    return make_component(
        "tech.topicFit", "Primary Topic 적합도", value,
        detail={"source": "IPURE AI Score",
                "ipureAiScore": record.get("ipureAiScore"),
                "ipureScoreMax": ctx.config.ipure_score_max,
                "topicFitPercent": None if percent is None else round(percent, 1),
                "gateThreshold": ctx.config.gate_topic_fit_min},
        notes=notes)


def _core_centrality(analysis: Dict[str, Any]) -> Component:
    """독립청구항 내 핵심기술 중심성 (LLM).

    '혁신적인가' 가 아니라 **입력한 핵심 구성요소가 독립청구항의 필수 구성인지**,
    **구성요소 사이의 연결관계가 청구되어 있는지** 만 판정한다.
    """
    value = float(analysis.get("coreCentralityScore") or 0.0)
    return make_component(
        "tech.coreCentrality", "독립청구항 내 핵심기술 중심성", value,
        llm_score=round(value, 3),
        detail={"rationale": analysis.get("centralityRationale"),
                "coreElementsInIndependent": (analysis.get("claimAnalysis") or {})
                .get("coreElementsInIndependentClaims"),
                "linkageClaimed": (analysis.get("claimAnalysis") or {}).get("linkageClaimed"),
                "independentClaimsWithCore": (analysis.get("claimAnalysis") or {})
                .get("independentClaimsWithCore")},
        notes=[] if analysis.get("status") == "ok" else ["LLM 미수행으로 0점 처리"])


def _claim_expansion(analysis: Dict[str, Any]) -> Component:
    """핵심기술의 청구항 확장도 (LLM).

    관련 청구항 비율과 확장 종속항 수 중 **높은 쪽** 기준을 적용해,
    전체 청구항 수가 적은 특허가 불리해지지 않게 한다.
    """
    value = float(analysis.get("claimExpansionScore") or 0.0)
    claim_analysis = analysis.get("claimAnalysis") or {}
    return make_component(
        "tech.claimExpansion", "핵심기술의 청구항 확장도", value,
        llm_score=round(value, 3),
        detail={"relatedClaimCount": claim_analysis.get("relatedClaimCount"),
                "totalClaimCount": claim_analysis.get("totalClaimCount"),
                "relatedClaimRatio": claim_analysis.get("relatedClaimRatio"),
                "expansionDependentCount": claim_analysis.get("expansionDependentCount"),
                "rationale": analysis.get("expansionRationale")},
        notes=[] if analysis.get("status") == "ok" else ["LLM 미수행으로 0점 처리"])


def _claim_type_diversity(analysis: Dict[str, Any]) -> Component:
    """독립청구항 유형 다양성 (LLM).

    하나의 기술개념을 장치·방법·시스템·중간제품 등 여러 관점에서 보호하는지 본다.
    """
    value = float(analysis.get("claimTypeDiversityScore") or 0.0)
    claim_analysis = analysis.get("claimAnalysis") or {}
    return make_component(
        "tech.claimTypeDiversity", "독립청구항 유형 다양성", value,
        llm_score=round(value, 3),
        detail={"claimTypes": claim_analysis.get("claimTypes") or [],
                "claimTypeCount": len(claim_analysis.get("claimTypes") or []),
                "independentClaimCount": claim_analysis.get("independentClaimCount"),
                "rationale": analysis.get("diversityRationale")},
        notes=[] if analysis.get("status") == "ok" else ["LLM 미수행으로 0점 처리"])
