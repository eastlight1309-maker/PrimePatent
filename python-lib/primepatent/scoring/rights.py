# -*- coding: utf-8 -*-
"""권리 중요도 (생존성 + 청구범위강도 + 잔존기간 + 권리유지·방어신호).

배점은 config.COMPONENT_MAX 가 단일 기준이다.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .. import status as status_mod
from ..config import REMAINING_TERM_BANDS, SURVIVAL_SCORES
from .common import AreaResult, Component, band_score, make_component
from .context import AnalysisContext

LABEL = "권리 중요도"

# 권리유지·방어 신호 배점 분해 (합 7점)
DIVISIONAL_POINTS = 2.0
DISPUTE_POINTS = 5.0


def score(record: Dict[str, Any], analysis: Dict[str, Any], ctx: AnalysisContext) -> AreaResult:
    components: List[Component] = [
        _survival(record),
        _claim_scope(record, analysis, ctx),
        _remaining_term(record),
        _defense_signal(record),
    ]
    return AreaResult(key="rights", label=LABEL, components=components)


def _survival(record: Dict[str, Any]) -> Component:
    code = record.get("_statusCode", status_mod.UNKNOWN)
    value = SURVIVAL_SCORES.get(code, SURVIVAL_SCORES["unknown"])
    notes = []
    if code == status_mod.UNKNOWN:
        notes.append("법적상태 정보가 없어 기본값(2점)을 적용했습니다.")
    if code == status_mod.INVALIDATED:
        notes.append("무효 확정 문헌은 권리 생존성 0점입니다.")
    return make_component(
        "rights.survival", "권리 생존성", value,
        detail={"statusCode": code, "statusLabel": record.get("_statusLabel"),
                "legalStatus": record.get("legalStatus")},
        notes=notes)


def _claim_scope(record: Dict[str, Any], analysis: Dict[str, Any],
                 ctx: AnalysisContext) -> Component:
    """정량 4점(독립항 수/청구항 수 백분위) + LLM 4점(권리범위 넓이)."""
    ind_rank, ind_group, ind_n = ctx.rank("independentClaimCount", record,
                                          record.get("independentClaimCount"))
    claim_rank, claim_group, claim_n = ctx.rank("claimCount", record, record.get("claimCount"))
    # 정량 2점 = 독립항 수 백분위 × 1 + 전체 청구항 수 백분위 × 1
    quant = 1.0 * ind_rank + 1.0 * claim_rank

    llm_score = float(analysis.get("claimBreadthScore") or 0.0)
    notes = []
    if analysis.get("status") != "ok":
        notes.append("LLM 청구범위 평가 미수행(%s)" % (analysis.get("message") or analysis.get("status")))
    if not record.get("hasClaimText"):
        notes.append("청구항 텍스트가 없어 LLM 평가 신뢰도가 낮습니다.")

    return make_component(
        "rights.claimScope", "청구범위 강도", quant + llm_score,
        quant_score=round(quant, 3), llm_score=round(llm_score, 3),
        detail={
            "independentClaimCount": record.get("independentClaimCount"),
            "claimCount": record.get("claimCount"),
            "independentRank": round(ind_rank, 3), "independentPeer": ind_group, "independentPeerN": ind_n,
            "claimRank": round(claim_rank, 3), "claimPeer": claim_group, "claimPeerN": claim_n,
            "claimBreadthScore": round(llm_score, 2),      # LLM 이 매긴 권리범위 넓이 0~4
            # 백분위만으로는 '이 값이 집단에서 어느 수준인지' 알 수 없으므로 분포를 함께 제공
            "claimPeerStats": ctx.peer_stats("claimCount", record),
            "independentPeerStats": ctx.peer_stats("independentClaimCount", record),
            "claimAnalysis": analysis.get("claimAnalysis") or {},
        },
        notes=notes)


def _remaining_term(record: Dict[str, Any]) -> Component:
    remaining = record.get("_remainingTerm")
    value = band_score(remaining, REMAINING_TERM_BANDS, default=0.0)
    if remaining is not None and remaining <= 0:
        value = 0.0
    notes = []
    if remaining is None:
        notes.append("출원일/우선일 정보가 없어 잔존기간을 계산할 수 없습니다(0점).")
    elif not record.get("expiryDate"):
        notes.append("만료일 컬럼이 없어 최초우선일 + 20년으로 근사했습니다.")
    return make_component(
        "rights.remainingTerm", "잔존기간", value,
        detail={"remainingYears": None if remaining is None else round(remaining, 2),
                "expiryDate": record.get("expiryDate"),
                "basisDate": record.get("earliestPriorityDate")},
        notes=notes)


def _defense_signal(record: Dict[str, Any]) -> Component:
    """분할·연속출원 존재 2점 + 심판·무효·이의 등 권리분쟁 존재 5점 (패밀리 단위 신호).

    분쟁 판정에는 심판 전체 횟수 / 심판 종류 / 소송 전체 횟수를 사용한다.
    (양도·실시권은 상업화·거래 신호로 이동했다)
    """
    signals = (record.get("_family") or {}).get("signals") or {}
    divisional = signals.get("divisional")
    dispute = signals.get("hasDispute")

    value = 0.0
    missing = []
    if divisional is True:
        value += DIVISIONAL_POINTS
    elif divisional is None:
        missing.append("분할출원 여부")
    if dispute is True:
        value += DISPUTE_POINTS
    elif dispute is None:
        missing.append("심판/소송")

    notes = []
    if missing:
        notes.append("데이터 없음: %s (0점 처리)" % ", ".join(missing))
    return make_component(
        "rights.defenseSignal", "권리유지·방어 신호", value,
        detail={"divisional": divisional, "dispute": dispute,
                "trialCount": signals.get("trialCount"),
                "trialTypes": signals.get("trialTypes"),
                "litigationCount": signals.get("litigationCount"),
                "divisionalPoints": DIVISIONAL_POINTS if divisional is True else 0.0,
                "disputePoints": DISPUTE_POINTS if dispute is True else 0.0,
                "missingSignals": missing},
        notes=notes)
