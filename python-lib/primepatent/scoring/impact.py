# -*- coding: utf-8 -*-
"""영향력·경쟁성 20점 (스펙 7장).

연령보정 피인용 8 + 비자기·다출원인 확산성 5 + 기술 원천성 4 + 권리충돌·경쟁 신호 3
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..parsing import safe_log1p
from .common import AreaResult, Component, make_component
from .context import AnalysisContext

LABEL = "영향력·경쟁성"

# 7.3 후방인용 적정구간(백분위) - 지나치게 적거나 많으면 감점
BACKWARD_SWEET_SPOT = (0.2, 0.8)


def score(record: Dict[str, Any], analysis: Dict[str, Any], ctx: AnalysisContext) -> AreaResult:
    components: List[Component] = [
        _citation(record, ctx),
        _diffusion(record, ctx),
        _originality(record, ctx),
        _conflict(record),
    ]
    return AreaResult(key="impact", label=LABEL, components=components)


def _citation(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """LN(1+피인용) 의 동일주제·동일우선연도 백분위 × 8.

    비교집단 표본이 부족하면 연간 피인용 속도 백분위로 대체한다.
    """
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
    return make_component(
        "impact.citation", "연령보정 피인용 영향력", rank * 8.0,
        detail={"forwardCitations": forward, "logForward": round(log_value, 4),
                "citationSpeed": None if ctx.citation_speed(record) is None
                else round(ctx.citation_speed(record), 3),
                "method": method, "rank": round(rank, 3),
                "peerGroup": group, "peerN": size},
        notes=notes)


def _diffusion(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """비자기 피인용 비율 × 2 + 고유 피인용 출원인 수 백분위 × 3."""
    forward = record.get("forwardCitationCountResolved") or 0
    other = record.get("otherForwardCount") or 0
    ratio = (other / forward) if forward else 0.0
    ratio = max(0.0, min(1.0, ratio))

    unique_applicants = ctx.unique_citing_applicants(record)
    rank, group, size = ctx.rank("uniqueCitingApplicants", record, unique_applicants)
    value = ratio * 2.0 + rank * 3.0
    notes = []
    if forward and not record.get("otherForwardCitations") and not record.get("selfForwardCitations"):
        notes.append("자기/타인 피인용 구분 컬럼이 없어 비자기 비율을 0으로 처리했습니다.")
    return make_component(
        "impact.diffusion", "비자기·다출원인 확산성", value,
        detail={"forwardCitations": forward, "otherForwardCitations": other,
                "nonSelfRatio": round(ratio, 3),
                "uniqueCitingApplicants": unique_applicants,
                "rank": round(rank, 3), "peerGroup": group, "peerN": size},
        notes=notes)


def _originality(record: Dict[str, Any], ctx: AnalysisContext) -> Component:
    """주제 내 초기 출원 1.5 + 비자기 확산성 1.5 + 적정 후방인용 구조 1."""
    ordinal = ctx.priority_ordinal(record)
    date_rank, date_group, date_size = ctx.rank("priorityOrdinal", record, ordinal)
    early = (1.0 - date_rank) * 1.5 if ordinal is not None else 0.0

    forward = record.get("forwardCitationCountResolved") or 0
    other = record.get("otherForwardCount") or 0
    ratio = (other / forward) if forward else 0.0
    unique_applicants = ctx.unique_citing_applicants(record) or 0.0
    applicant_rank, _, _ = ctx.rank("uniqueCitingApplicants", record, unique_applicants)
    diffusion = min(1.5, (max(0.0, min(1.0, ratio)) * 0.75) + applicant_rank * 0.75)

    backward = record.get("backwardCitationCountResolved")
    back_rank, back_group, back_size = ctx.rank("logBackward", record, safe_log1p(backward)) \
        if backward is not None else (0.0, "none", 0)
    low, high = BACKWARD_SWEET_SPOT
    if backward is None:
        structure = 0.0
    elif low <= back_rank <= high:
        structure = 1.0
    else:
        distance = (low - back_rank) if back_rank < low else (back_rank - high)
        structure = max(0.0, 1.0 - distance / max(low, 1.0 - high) * 0.7)

    notes = []
    if ordinal is None:
        notes.append("우선일 정보가 없어 초기 출원 점수를 계산할 수 없습니다.")
    if backward is None:
        notes.append("후방인용 정보가 없어 인용구조 점수 0점입니다.")
    return make_component(
        "impact.originality", "기술 원천성", early + diffusion + structure,
        detail={"priorityDate": record.get("earliestPriorityDate"),
                "priorityRank": round(date_rank, 3), "earlinessScore": round(early, 3),
                "peerGroup": date_group, "peerN": date_size,
                "diffusionScore": round(diffusion, 3),
                "backwardCitations": backward, "backwardRank": round(back_rank, 3),
                "backwardStructureScore": round(structure, 3)},
        notes=notes)


def _conflict(record: Dict[str, Any]) -> Component:
    """무효·심판 1.5 + 제3자 인용/이의 0.5 + 양도·실시권 1.0."""
    family = record.get("_family") or {}
    signals = family.get("signals") or {}
    value = 0.0
    detail: Dict[str, Any] = {}
    missing: List[str] = []

    dispute = signals.get("hasDispute")
    if dispute is True:
        value += 1.5
    elif dispute is None:
        missing.append("심판/소송")
    detail["dispute"] = dispute
    detail["trialCount"] = signals.get("trialCount")
    detail["trialTypes"] = signals.get("trialTypes")

    third_party = bool(signals.get("examinerCitedByOthers")) or \
        bool(record.get("otherForwardCitations"))
    if third_party:
        value += 0.5
    detail["thirdPartyCitation"] = third_party

    license_flag = signals.get("licenseFlag")
    assignment = signals.get("assignment")
    if license_flag is True or assignment is True:
        value += 1.0
    elif license_flag is None and assignment is None:
        missing.append("양도/실시권")
    detail["licenseFlag"] = license_flag
    detail["assignment"] = assignment
    detail["missingSignals"] = missing

    notes = ["데이터 없음: %s (0점 처리)" % ", ".join(missing)] if missing else []
    return make_component("impact.conflict", "권리충돌·경쟁 신호", value,
                          detail=detail, notes=notes)
