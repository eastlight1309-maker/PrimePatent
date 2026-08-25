# -*- coding: utf-8 -*-
"""분석 파이프라인: 업로드 파일 → 매핑 → 레코드 → 패밀리 → LLM → 스코어링."""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Sequence

from .config import ScoringConfig
from .family import build_families, representative_records
from .ingest import load_table
from .llm.analyzer import LLMAnalyzer, analysis_defaults
from .llm.client import LLMError, get_client
from .mapping import mapping_report, resolve_mapping
from .parsing import to_date, to_text
from .records import build_records
from .scoring.engine import score_records

logger = logging.getLogger("primepatent.pipeline")

ProgressFn = Callable[[str, float, str], None]


class PipelineCancelled(Exception):
    """사용자 취소."""


def _noop_progress(phase: str, ratio: float, message: str) -> None:
    return None


def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise PipelineCancelled("사용자가 분석을 취소했습니다.")


def llm_document(record: Dict[str, Any], char_limit: int) -> Dict[str, Any]:
    """LLM 입력용 축약 문서."""
    return {
        "_key": record.get("_key"),
        "docNumber": record.get("docNumber"),
        "country": record.get("country"),
        "title": to_text(record.get("title")) or to_text(record.get("titleTranslated")),
        "abstract": to_text(record.get("abstract")) or to_text(record.get("abstractTranslated"))
        or to_text(record.get("aiSummary")),
        "problemSummary": to_text(record.get("problemSummary")),
        "solutionSummary": to_text(record.get("solutionSummary")),
        "effectSummary": to_text(record.get("effectSummary")),
        "mainClaim": to_text(record.get("mainClaim")) or to_text(record.get("mainClaimTranslated")),
        "independentClaims": to_text(record.get("independentClaims"))
        or to_text(record.get("independentClaimsTranslated")),
        "claimCount": record.get("claimCount"),
        "independentClaimCount": record.get("independentClaimCount"),
        "cpc": (record.get("cpcSubgroups") or [])[:12],
    }


def run_analysis(headers: Sequence[str], rows: Sequence[Dict[str, Any]],
                 user_mapping: Optional[Dict] = None,
                 config: Optional[ScoringConfig] = None,
                 source_meta: Optional[Dict[str, Any]] = None,
                 progress: Optional[ProgressFn] = None,
                 cancel_event: Optional[threading.Event] = None,
                 llm_cache: Optional[Dict[str, Dict]] = None) -> Dict[str, Any]:
    """전체 분석 실행. 결과 payload(dict)를 반환한다."""
    progress = progress or _noop_progress
    config = config or ScoringConfig()
    config.validate()
    warnings: List[str] = []

    if not rows:
        raise ValueError("분석할 데이터가 없습니다.")

    # ---------------------------------------------------------------- 1. 매핑
    progress("mapping", 0.05, "컬럼 매핑 중")
    mapping = resolve_mapping(headers, user_mapping)
    report = mapping_report(headers, mapping)
    if not report["ok"]:
        raise ValueError("필수 항목이 매핑되지 않았습니다: %s"
                         % ", ".join(report["missingRequiredLabels"]))
    if report["missingImportantLabels"]:
        warnings.append("미매핑 주요 항목(관련 점수는 0점 또는 근사 처리): %s"
                        % ", ".join(report["missingImportantLabels"]))
    _check_cancel(cancel_event)

    # ---------------------------------------------------------------- 2. 레코드
    progress("records", 0.12, "레코드 변환 중 (%d건)" % len(rows))
    records = build_records(rows, mapping)
    _check_cancel(cancel_event)

    as_of = to_date(config.as_of_date) or date.today()

    # ---------------------------------------------------------------- 3. 패밀리
    progress("family", 0.2, "패밀리 대표문헌 선정 중")
    families = build_families(records, config, as_of)
    targets = representative_records(records, families, config.dedupe_by_family)
    if not targets:
        raise ValueError("채점 대상 문헌이 없습니다.")
    _check_cancel(cancel_event)

    # ---------------------------------------------------------------- 4. LLM 대상 선정
    analyses: Dict[str, Dict[str, Any]] = {}
    llm_info: Dict[str, Any] = {"enabled": config.llm_enabled, "llmId": config.llm_id,
                                "provider": "", "requested": 0, "ok": 0, "error": 0,
                                "cached": 0, "message": ""}

    if config.llm_enabled:
        selected = _select_llm_targets(targets, config, as_of, warnings)
        llm_info["requested"] = len(selected)
        progress("llm", 0.3, "LLM 분석 중 (0/%d)" % len(selected))
        try:
            client = get_client(config.llm_id, config.llm_timeout_sec, config.llm_max_retries)
        except LLMError as exc:
            warnings.append("LLM 을 사용할 수 없어 정량점수만 계산합니다: %s" % exc)
            llm_info["message"] = str(exc)
            client = None

        if client is not None:
            llm_info["provider"] = client.provider
            if client.provider == "heuristic":
                warnings.append(
                    "Dataiku LLM Mesh 에 연결할 수 없어 휴리스틱 추정치를 사용했습니다. "
                    "LLM 분석점수는 참고용이며 실제 평가로 사용하지 마십시오.")
            analyzer = LLMAnalyzer(
                client, config.topic_name, config.topic_description, config.topic_keywords,
                config.llm_text_char_limit, config.llm_max_workers, cache=llm_cache)

            def _llm_progress(done: int, total: int) -> None:
                ratio = 0.3 + 0.5 * (done / max(1, total))
                progress("llm", ratio, "LLM 분석 중 (%d/%d)" % (done, total))

            documents = [llm_document(r, config.llm_text_char_limit) for r in selected]
            analyses = analyzer.analyze_many(documents, _llm_progress, cancel_event)
            llm_info.update({"ok": analyzer.stats["ok"], "error": analyzer.stats["error"],
                             "cached": analyzer.stats["cached"]})
            if analyzer.stats["error"]:
                warnings.append("LLM 분석 실패 %d건은 LLM 점수 0점으로 처리했습니다."
                                % analyzer.stats["error"])
    else:
        warnings.append("LLM 분석이 비활성화되어 정량점수(70점 구간)만 계산했습니다.")

    _check_cancel(cancel_event)

    # ---------------------------------------------------------------- 5. 스코어링
    progress("scoring", 0.85, "스코어링 중 (%d건)" % len(targets))
    for record in targets:
        analyses.setdefault(record.get("_key"),
                            analysis_defaults(status="skipped", message="LLM 분석 대상에서 제외됨"))
    scored = score_records(targets, analyses, config, as_of, population=records)
    _check_cancel(cancel_event)

    # ---------------------------------------------------------------- 6. 결과 조립
    progress("summary", 0.95, "결과 정리 중")
    rows_out = scored["rows"]
    summary = _summarize(rows_out, scored["context"], families, records, config)
    summary["llm"] = llm_info

    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "source": dict(source_meta or {}),
        "config": config.to_dict(),
        "mapping": {k: {"column": v.get("column"), "method": v.get("method"),
                        "confidence": v.get("confidence")} for k, v in mapping.items()},
        "mappingReport": report,
        "summary": summary,
        "rows": rows_out,
        "warnings": warnings,
    }
    progress("done", 1.0, "완료")
    return payload


def _select_llm_targets(targets: List[Dict[str, Any]], config: ScoringConfig,
                        as_of: date, warnings: List[str]) -> List[Dict[str, Any]]:
    """LLM 분석 대상 선정. 상한이 설정되면 정량 사전점수 상위 N건만 분석한다."""
    limit = config.llm_max_documents
    if not limit or limit >= len(targets):
        return list(targets)
    empty: Dict[str, Dict[str, Any]] = {}
    prescored = score_records(targets, empty, config, as_of, population=targets)
    order = {row["key"]: row["totalScore"] for row in prescored["rows"]}
    ranked = sorted(targets, key=lambda r: -order.get(r.get("_key"), 0.0))
    warnings.append("LLM 분석 상한(%d건)에 따라 정량 사전점수 상위 %d건만 LLM 분석했습니다."
                    % (limit, limit))
    return ranked[:limit]


def _summarize(rows: List[Dict[str, Any]], context: Dict[str, Any],
               families: Dict[str, Any], records: List[Dict[str, Any]],
               config: ScoringConfig) -> Dict[str, Any]:
    grades: Dict[str, int] = {}
    statuses: Dict[str, int] = {}
    countries: Dict[str, int] = {}
    applicants: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        grades[row["grade"]] = grades.get(row["grade"], 0) + 1
        statuses[row["statusLabel"] or "미상"] = statuses.get(row["statusLabel"] or "미상", 0) + 1
        country = row.get("country") or "-"
        countries[country] = countries.get(country, 0) + 1
        name = row.get("applicant") or "미상"
        bucket = applicants.setdefault(name, {"applicant": name, "count": 0, "scoreSum": 0.0,
                                              "top": 0.0})
        bucket["count"] += 1
        bucket["scoreSum"] += row["totalScore"]
        bucket["top"] = max(bucket["top"], row["totalScore"])

    applicant_rows = sorted(
        ({"applicant": v["applicant"], "count": v["count"],
          "avgScore": round(v["scoreSum"] / v["count"], 2), "topScore": round(v["top"], 2)}
         for v in applicants.values()),
        key=lambda a: (-a["topScore"], -a["count"]))[:20]

    return {
        "inputRecordCount": len(records),
        "familyCount": len(families),
        "scoredCount": len(rows),
        "dedupeByFamily": config.dedupe_by_family,
        "gatePassedCount": context["gatePassedCount"],
        "llmAnalyzedCount": context["llmAnalyzedCount"],
        "scoreAverage": context["scoreAverage"],
        "scoreMax": context["scoreMax"],
        "scoreMin": context["scoreMin"],
        "asOf": context["asOf"],
        "gradeDistribution": grades,
        "statusDistribution": statuses,
        "countryDistribution": dict(sorted(countries.items(), key=lambda kv: -kv[1])[:20]),
        "topApplicants": applicant_rows,
        "routeDistribution": _count_by(rows, "reviewRoute"),
        "topRows": [{"rank": r["rank"], "docNumber": r["docNumber"], "title": r["title"],
                     "applicant": r["applicant"], "totalScore": r["totalScore"],
                     "grade": r["grade"]} for r in rows[:10]],
    }


def _count_by(rows: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "-")
        out[value] = out.get(value, 0) + 1
    return out


def analyze_file(path: str, sheet: Optional[str] = None, user_mapping: Optional[Dict] = None,
                 config: Optional[ScoringConfig] = None, progress: Optional[ProgressFn] = None,
                 cancel_event: Optional[threading.Event] = None) -> Dict[str, Any]:
    """파일 경로로부터 전체 분석 실행(배치/테스트용)."""
    progress = progress or _noop_progress
    progress("load", 0.01, "파일 읽는 중")
    headers, rows, meta = load_table(path, sheet)
    return run_analysis(headers, rows, user_mapping, config, meta, progress, cancel_event)
