# -*- coding: utf-8 -*-
"""결과 내보내기(엑셀/CSV)."""

from __future__ import annotations

import csv
import io
import logging
from typing import Any, Dict, List

from .config import AREA_LABEL, AREA_MAX, AREA_ORDER, COMPONENT_MAX, TOTAL_MAX
from .columns import FIELD_BY_KEY

logger = logging.getLogger("primepatent.export")

# 컬럼 라벨은 실제 배점에서 생성한다(지표 추가/삭제 시 헤더가 어긋나지 않도록).
COMPONENT_LABEL = {
    "rights.survival": "권리 생존성",
    "rights.claimScope": "청구범위 강도",
    "rights.remainingTerm": "잔존기간",
    "rights.defenseSignal": "권리유지·방어",
    "tech.topicFit": "Topic 적합도(IPURE)",
    "tech.coreCentrality": "핵심기술 중심성",
    "tech.claimExpansion": "청구항 확장도",
    "tech.claimTypeDiversity": "독립항 유형 다양성",
    "market.entry": "주요 시장 진입도",
    "market.applicantPower": "출원인 시장 영향력",
    "market.commercial": "상업화·거래 신호",
    "market.familySize": "패밀리 건수",
    "impact.competitorCoverage": "경쟁사 커버리지",
    "impact.citation": "연령보정 피인용",
    "impact.leadership": "기술 선도성",
}

AREA_LABELS = [(key, "%s(%g)" % (AREA_LABEL[key], AREA_MAX[key])) for key in AREA_ORDER]

COMPONENT_ORDER = [(key, "%s(%g)" % (COMPONENT_LABEL[key], COMPONENT_MAX[key]))
                   for key in COMPONENT_MAX if key in COMPONENT_LABEL]

BASE_COLUMNS = [
    ("rank", "순위"),
    ("applicationNumber", "출원번호"), ("applicationDateText", "출원일"),
    ("country", "국가"), ("title", "발명의 명칭"),
    ("applicant", "출원인"), ("currentAssignee", "현재권리자"),
    ("registrationLabel", "등록여부"), ("registrationNumber", "등록번호"),
    ("statusLabel", "법적상태"), ("priorityDate", "최초우선일"),
    ("publicationNumber", "공개번호"), ("docNumber", "문헌번호"),
    ("registrationDate", "등록일"),
    ("totalScore", "총점(%g)" % TOTAL_MAX), ("grade", "등급"),
    ("quantScore", "정량점수"), ("llmScore", "LLM점수"),
]

TAIL_COLUMNS = [
    ("gateFit", "Topic 적합도(%)"), ("gatePassed", "Gate 통과"), ("reviewRoute", "검토 루트"),
    ("familyCountries", "패밀리 국가"), ("familyMemberCount", "패밀리 문헌수"),
    ("forwardCitations", "피인용 수"), ("backwardCitations", "인용 수"),
    ("claimCount", "청구항 수"), ("independentClaimCount", "독립항 수"),
    ("cpcMain", "CPC Main"), ("llmProvider", "LLM 제공자"), ("llmRationale", "LLM 판단근거"),
    ("notes", "주의사항"), ("detailLink", "상세보기 링크"),
]


# 엑셀/CSV 수식 인젝션 방지: 아래 문자로 시작하는 문자열은 Excel 이 수식으로 해석한다.
# (업로드된 특허 명칭·출원인 등이 그대로 결과 파일에 들어가므로 내보내기 시점에 차단한다)
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: Any) -> Any:
    """수식으로 해석될 수 있는 문자열 앞에 작은따옴표를 붙여 텍스트로 고정한다."""
    if not isinstance(value, str) or not value:
        return value
    return "'" + value if value[0] in _FORMULA_PREFIXES else value


def flatten_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """결과 1행 → 평면 dict(엑셀 1행)."""
    flat: Dict[str, Any] = {}
    for key, label in BASE_COLUMNS:
        value = row.get(key)
        flat[label] = value.isoformat() if hasattr(value, "isoformat") else value
    for key, label in AREA_LABELS:
        flat[label] = (row.get("areaScores") or {}).get(key)

    component_scores: Dict[str, float] = {}
    for area in (row.get("areas") or {}).values():
        for component in area.get("components", []):
            component_scores[component["key"]] = component["score"]
    for key, label in COMPONENT_ORDER:
        flat[label] = component_scores.get(key)

    gate = row.get("gate") or {}
    llm = row.get("llm") or {}
    flat["Topic 적합도(%)"] = gate.get("topicFitPercent")
    flat["Gate 통과"] = "Y" if gate.get("passed") else "N"
    flat["검토 루트"] = row.get("reviewRoute")
    flat["패밀리 국가"] = ", ".join(row.get("familyCountries") or [])
    flat["패밀리 문헌수"] = row.get("familyMemberCount")
    flat["피인용 수"] = row.get("forwardCitations")
    flat["인용 수"] = row.get("backwardCitations")
    flat["청구항 수"] = row.get("claimCount")
    flat["독립항 수"] = row.get("independentClaimCount")
    flat["CPC Main"] = row.get("cpcMain")
    flat["LLM 제공자"] = llm.get("provider")
    flat["LLM 판단근거"] = llm.get("rationale")
    flat["주의사항"] = " / ".join(row.get("notes") or [])[:2000]
    flat["상세보기 링크"] = row.get("detailLink")
    return {key: safe_cell(value) for key, value in flat.items()}


def result_columns() -> List[str]:
    columns = [label for _, label in BASE_COLUMNS]
    columns += [label for _, label in AREA_LABELS]
    columns += [label for _, label in COMPONENT_ORDER]
    columns += [label for _, label in TAIL_COLUMNS]
    seen, ordered = set(), []
    for column in columns:
        if column not in seen:
            seen.add(column)
            ordered.append(column)
    return ordered


def to_csv_bytes(payload: Dict[str, Any]) -> bytes:
    """엑셀 호환(UTF-8 BOM) CSV."""
    columns = result_columns()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in payload.get("rows", []):
        writer.writerow(flatten_row(row))
    return buffer.getvalue().encode("utf-8-sig")


def to_excel_bytes(payload: Dict[str, Any]) -> bytes:
    """다중 시트 엑셀(요약 / 스코어 / 세부 / 매핑)."""
    try:
        import pandas as pd  # noqa: WPS433
    except ImportError:
        logger.warning("pandas 미설치 → CSV 로 대체합니다.")
        return to_csv_bytes(payload)

    rows = [flatten_row(r) for r in payload.get("rows", [])]
    frame = pd.DataFrame(rows, columns=result_columns())
    summary_frame = pd.DataFrame(_summary_rows(payload), columns=["항목", "값"])
    mapping_frame = pd.DataFrame(_mapping_rows(payload), columns=["표준 필드", "엑셀 컬럼", "매핑 방식", "신뢰도"])
    detail_frame = pd.DataFrame(_detail_rows(payload),
                                columns=["문헌번호", "세부지표", "점수", "배점", "산출근거", "주의"])

    buffer = io.BytesIO()
    try:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            summary_frame.to_excel(writer, sheet_name="요약", index=False)
            frame.to_excel(writer, sheet_name="스코어", index=False)
            detail_frame.to_excel(writer, sheet_name="세부지표", index=False)
            mapping_frame.to_excel(writer, sheet_name="컬럼매핑", index=False)
            _autofit(writer)
    except Exception as exc:
        logger.warning("엑셀 생성 실패(%s) → CSV 로 대체합니다.", exc)
        return to_csv_bytes(payload)
    return buffer.getvalue()


def _autofit(writer) -> None:
    try:
        for sheet in writer.book.worksheets:
            widths: Dict[int, int] = {}
            for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 200)):
                for cell in row:
                    if cell.value is None:
                        continue
                    length = min(60, len(str(cell.value)) + 2)
                    widths[cell.column] = max(widths.get(cell.column, 10), length)
            for column, width in widths.items():
                sheet.column_dimensions[sheet.cell(row=1, column=column).column_letter].width = width
            sheet.freeze_panes = "A2"
    except Exception as exc:  # 서식은 실패해도 데이터는 유지
        logger.debug("열 너비 조정 생략: %s", exc)


def _summary_rows(payload: Dict[str, Any]) -> List[List[Any]]:
    meta = payload.get("meta") or {}
    summary = payload.get("summary") or {}
    config = payload.get("config") or {}
    llm = summary.get("llm") or {}
    rows = [
        ["생성 시각", payload.get("generatedAt")],
        ["저장 부서", meta.get("department", "")],
        ["저장자", meta.get("owner", "")],
        ["프로젝트명", meta.get("project", "")],
        ["저장 시각", meta.get("savedAtDisplay", "")],
        ["원본 파일", (payload.get("source") or {}).get("fileName", "")],
        ["Primary Topic", config.get("topic_name", "")],
        ["기준일", summary.get("asOf", "")],
        ["입력 문헌 수", summary.get("inputRecordCount")],
        ["패밀리 수", summary.get("familyCount")],
        ["채점 문헌 수", summary.get("scoredCount")],
        ["Gate 통과 수", summary.get("gatePassedCount")],
        ["LLM 분석 건수", summary.get("llmAnalyzedCount")],
        ["LLM 모델", config.get("llm_id", "")],
        ["LLM 제공자", llm.get("provider", "")],
        ["평균 총점", summary.get("scoreAverage")],
        ["최고 총점", summary.get("scoreMax")],
        ["최저 총점", summary.get("scoreMin")],
    ]
    for grade, count in sorted((summary.get("gradeDistribution") or {}).items()):
        rows.append(["등급 %s 건수" % grade, count])
    for route, count in (summary.get("routeDistribution") or {}).items():
        rows.append([route, count])
    for warning in payload.get("warnings") or []:
        rows.append(["경고", warning])
    return [[safe_cell(cell) for cell in row] for row in rows]


def _mapping_rows(payload: Dict[str, Any]) -> List[List[Any]]:
    rows = []
    for field_key, info in (payload.get("mapping") or {}).items():
        spec = FIELD_BY_KEY.get(field_key)
        rows.append([safe_cell(spec.label if spec else field_key), safe_cell(info.get("column")),
                     info.get("method"), info.get("confidence")])
    return sorted(rows, key=lambda r: str(r[0]))


def _detail_rows(payload: Dict[str, Any], limit: int = 300) -> List[List[Any]]:
    rows = []
    for row in (payload.get("rows") or [])[:limit]:
        for area in (row.get("areas") or {}).values():
            for component in area.get("components", []):
                detail = component.get("detail") or {}
                brief = ", ".join("%s=%s" % (k, _brief(v)) for k, v in list(detail.items())[:6])
                rows.append([safe_cell(row.get("docNumber")), component.get("label"),
                             component.get("score"), COMPONENT_MAX.get(component.get("key")),
                             safe_cell(brief[:500]),
                             safe_cell(" / ".join(component.get("notes") or [])[:300])])
    return rows


def _brief(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value[:6])
    if isinstance(value, dict):
        return "{%d항목}" % len(value)
    return str(value)[:80]


def export_bytes(payload: Dict[str, Any], fmt: str = "xlsx") -> bytes:
    return to_csv_bytes(payload) if str(fmt).lower() == "csv" else to_excel_bytes(payload)


def export_filename(payload: Dict[str, Any], fmt: str = "xlsx") -> str:
    from .storage import safe_name
    meta = payload.get("meta") or {}
    config = payload.get("config") or {}
    stem = safe_name(meta.get("project") or config.get("topic_name") or "PrimePatent", 60)
    stamp = (meta.get("savedAt") or payload.get("generatedAt") or "")[:19]
    stamp = stamp.replace(":", "").replace("-", "").replace("T", "_")
    return "PrimePatent_%s_%s.%s" % (stem, stamp or "result", "csv" if fmt == "csv" else "xlsx")
