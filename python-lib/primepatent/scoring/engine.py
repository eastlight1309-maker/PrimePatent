# -*- coding: utf-8 -*-
"""스코어링 오케스트레이션.

총점 = 권리 30 + 기술 30 + 시장 20 + 영향력 20
     = 정량점수 + LLM 분석점수 (COMPONENT_SOURCE 기준으로 분리 집계)
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence

from ..config import AREA_MAX, ScoringConfig, mixed_max
from .. import status as status_mod
from ..llm.analyzer import analysis_defaults
from . import impact, market, rights, tech
from .common import AreaResult
from .context import AnalysisContext

GRADE_BANDS = [(80.0, "S"), (70.0, "A"), (60.0, "B"), (50.0, "C"), (0.0, "D")]
EMERGING_RECENT_YEARS = 5
EMERGING_SPEED_RANK = 0.8

AREA_MODULES = [("rights", rights), ("tech", tech), ("market", market), ("impact", impact)]


def _date_text(value) -> str:
    return value.isoformat()[:10] if hasattr(value, "isoformat") else (str(value or "") or "")


def _grade(total: float) -> str:
    for threshold, grade in GRADE_BANDS:
        if total >= threshold:
            return grade
    return "D"


def score_one(record: Dict[str, Any], analysis: Optional[Dict[str, Any]],
              ctx: AnalysisContext) -> Dict[str, Any]:
    """문헌 1건 채점."""
    analysis = analysis or analysis_defaults(status="skipped", message="LLM 분석 미수행")
    areas: List[AreaResult] = [module.score(record, analysis, ctx) for _, module in AREA_MODULES]

    weights = ctx.config.area_weights
    area_payload: Dict[str, Any] = {}
    total = 0.0
    total_max = 0.0
    quant = quant_max = llm = llm_max = 0.0

    for area in areas:
        weight = float(weights.get(area.key, 1.0))
        weighted = area.score * weight
        weighted_max = area.max * weight
        total += weighted
        total_max += weighted_max
        payload = area.to_dict()
        payload["weight"] = weight
        payload["weightedScore"] = round(weighted, 3)
        payload["weightedMax"] = round(weighted_max, 3)
        area_payload[area.key] = payload

        for component in area.components:
            if component.source == "quant":
                quant += component.score * weight
                quant_max += component.max * weight
            elif component.source == "llm":
                llm += component.score * weight
                llm_max += component.max * weight
            else:  # mixed
                q = component.quant_score or 0.0
                l = component.llm_score or 0.0
                quant += q * weight
                llm += l * weight
                # mixed 배점 분해: 정량/LLM 상한은 스펙 고정값
                q_max, l_max = mixed_max(component.key)
                quant_max += q_max * weight
                llm_max += l_max * weight

    # Gate 1 은 이제 LLM 이 아니라 IPURE AI Score 백분율로 판정한다.
    fit = tech.ipure_percent(record, ctx.config.ipure_score_max)
    gate_evaluated = fit is not None
    fit = fit or 0.0
    gate_passed = gate_evaluated and fit >= ctx.config.gate_topic_fit_min
    llm_ok = analysis.get("status") == "ok"

    notes: List[str] = []
    for area in areas:
        for component in area.components:
            for note in component.notes:
                notes.append("[%s] %s" % (component.label, note))

    speed = ctx.citation_speed(record)
    speed_rank, _, _ = ctx.rank("citationSpeed", record, speed)
    year = record.get("priorityYear")
    emerging = bool(year and year >= ctx.as_of.year - EMERGING_RECENT_YEARS
                    and speed_rank >= EMERGING_SPEED_RANK)

    return jsonable({
        "key": record.get("_key"),
        # 출원정보를 기본 식별자로 사용한다.
        # (docNumber 는 등록 여부에 따라 등록번호/공개번호가 섞이므로 목록 표기에 부적합)
        "applicationNumber": record.get("applicationNumber"),
        "applicationDateText": _date_text(record.get("applicationDate")),
        "docNumber": record.get("docNumber"),
        "publicationNumber": record.get("publicationNumber"),
        "registrationNumber": record.get("registrationNumber"),
        "registered": status_mod.is_registered(record),
        "registrationLabel": status_mod.registration_label(record),
        "country": record.get("country"),
        "title": record.get("title"),
        "applicant": record.get("applicantPrimary"),
        "currentAssignee": record.get("assigneePrimary"),
        "priorityDate": record.get("earliestPriorityDate"),
        "priorityYear": year,
        "applicationDate": record.get("applicationDate"),
        "registrationDate": record.get("registrationDate"),
        "statusCode": record.get("_statusCode"),
        "statusLabel": record.get("_statusLabel"),
        "familyKey": record.get("_familyKey"),
        "familyCountries": (record.get("_family") or {}).get("countries") or [],
        "familyMemberCount": (record.get("_family") or {}).get("memberCount"),
        "isRepresentative": bool(record.get("_isRepresentative")),
        "forwardCitations": record.get("forwardCitationCountResolved"),
        "backwardCitations": record.get("backwardCitationCountResolved"),
        "claimCount": record.get("claimCount"),
        "independentClaimCount": record.get("independentClaimCount"),
        "cpcMain": record.get("cpcMain"),
        "detailLink": record.get("detailLink"),
        "pdfLink": record.get("pdfLink"),

        "totalScore": round(total, 2),
        "totalMax": round(total_max, 2),
        "quantScore": round(quant, 2),
        "quantMax": round(quant_max, 2),
        "llmScore": round(llm, 2),
        "llmMax": round(llm_max, 2),
        "grade": _grade(total / total_max * 100.0 if total_max else 0.0),
        "areas": area_payload,
        "areaScores": {key: round(area_payload[key]["weightedScore"], 2)
                       for key, _ in AREA_MODULES},

        "gate": {
            "topicFitPercent": round(fit, 1),
            "threshold": ctx.config.gate_topic_fit_min,
            "passed": gate_passed,
            "evaluated": gate_evaluated,
            "source": "IPURE AI Score",
        },
        "llm": {
            "status": analysis.get("status"),
            "provider": analysis.get("provider"),
            "llmId": analysis.get("llmId"),
            "rationale": analysis.get("rationale"),
            "keyFeatures": analysis.get("keyFeatures") or [],
            "claimAnalysis": analysis.get("claimAnalysis") or {},
            "message": analysis.get("message"),
        },
        "flags": {
            "emergingOriginal": emerging,
            "llmAnalyzed": llm_ok,
            "citationSpeed": None if speed is None else round(speed, 3),
        },
        "notes": notes,
    })


def jsonable(value: Any) -> Any:
    """날짜/집합 등을 JSON 직렬화 가능한 형태로 변환한다.

    (변환하지 않으면 Flask 기본 인코더가 date 를 'Tue, 02 Aug 2022 00:00:00 GMT'
     형식으로 출력해 화면·엑셀에서 읽기 어렵다.)
    """
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(jsonable(item) for item in value)
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10] if isinstance(value, date) else value.isoformat()
    return value


def score_records(records: Sequence[Dict[str, Any]], analyses: Dict[str, Dict[str, Any]],
                  config: ScoringConfig, as_of: Optional[date] = None,
                  population: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """채점 대상 목록을 채점하고 순위를 매긴다.

    population 을 주면 인용 해석·출원인 통계는 모집단 전체로 계산하되,
    백분위 비교집단은 **채점 단위(records)** 로 구성한다.
    (패밀리 대표문헌만 채점하면서 비교집단만 전체 문헌으로 두면,
     다국 출원 패밀리가 분포를 지배해 백분위가 왜곡된다)
    """
    as_of = as_of or (_parse_as_of(config.as_of_date) or date.today())
    ctx = AnalysisContext(population if population is not None else records, config, as_of,
                          peer_records=records)

    rows = [score_one(record, analyses.get(record.get("_key")), ctx) for record in records]
    rows.sort(key=lambda r: (-r["totalScore"], r.get("applicationNumber") or ""))

    count = len(rows)
    for index, row in enumerate(rows):
        row["rank"] = index + 1
        row["percentile"] = round(100.0 * (count - index - 1) / max(1, count - 1), 1) if count > 1 else 100.0
        row["flags"]["topCandidate"] = bool(
            row["gate"]["passed"] and (index < max(1, int(count * 0.1)) or row["totalScore"] >= 80.0))
        row["reviewRoute"] = _review_route(row)

    return {"rows": rows, "context": _context_summary(ctx, rows, as_of)}


def _review_route(row: Dict[str, Any]) -> str:
    if not row["gate"]["passed"]:
        return "제외(Gate 미통과)"
    if row["flags"].get("topCandidate"):
        return "Route 1 (전문가 검토)"
    if row["flags"].get("emergingOriginal"):
        return "Route 2 (신흥 원천특허 검토)"
    return "Route 3 (모니터링)"


def _parse_as_of(value: str) -> Optional[date]:
    from ..parsing import to_date
    return to_date(value) if value else None


def _context_summary(ctx: AnalysisContext, rows: List[Dict[str, Any]], as_of: date) -> Dict[str, Any]:
    passed = [r for r in rows if r["gate"]["passed"]]
    analyzed = [r for r in rows if r["llm"]["status"] == "ok"]
    scores = [r["totalScore"] for r in rows] or [0.0]
    providers = sorted({r["llm"].get("provider") for r in analyzed if r["llm"].get("provider")})
    return {
        "asOf": as_of.isoformat(),
        "scoredCount": len(rows),
        "populationCount": len(ctx.records),
        "gatePassedCount": len(passed),
        "llmAnalyzedCount": len(analyzed),
        "llmProviders": providers,
        "topicFamilyTotal": ctx.topic_family_total,
        "scoreAverage": round(sum(scores) / len(scores), 2),
        "scoreMax": round(max(scores), 2),
        "scoreMin": round(min(scores), 2),
        "areaMax": dict(AREA_MAX),
    }
