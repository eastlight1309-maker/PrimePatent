# -*- coding: utf-8 -*-
"""업로드 파일(엑셀/CSV) 적재.

- WIPS 다운로드 파일은 상단에 검색식/안내 행이 붙는 경우가 있어 헤더 행을 탐지한다.
- CSV 는 utf-8-sig → cp949 → euc-kr → utf-8(errors=replace) 순으로 시도한다(한글 인코딩).
"""

from __future__ import annotations

import io
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .columns import ALIAS_LOOSE, ALIAS_STRICT, loose_header, normalize_header

EXCEL_EXTENSIONS = (".xlsx", ".xlsm", ".xls")
CSV_EXTENSIONS = (".csv", ".tsv", ".txt")
HEADER_SCAN_ROWS = 12
CSV_ENCODINGS = ("utf-8-sig", "cp949", "euc-kr", "utf-8")


class IngestError(Exception):
    """업로드 파일을 읽을 수 없을 때."""


def _import_pandas():
    try:
        import pandas as pd  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise IngestError(
            "pandas 가 설치되어 있지 않습니다. Dataiku 코드환경에 pandas/openpyxl 을 추가하십시오."
        ) from exc
    return pd


def _header_score(values: Sequence[Any]) -> int:
    """해당 행이 헤더일 가능성 점수 = 알려진 WIPS 항목명과 일치하는 셀 수."""
    score = 0
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text.lower() == "nan":
            continue
        if normalize_header(text) in ALIAS_STRICT or loose_header(text) in ALIAS_LOOSE:
            score += 1
    return score


def detect_header_row(frame) -> int:
    """헤더로 보이는 행 index(0-base)를 반환. 못 찾으면 0."""
    best_index, best_score = 0, -1
    limit = min(HEADER_SCAN_ROWS, len(frame))
    for index in range(limit):
        row = list(frame.iloc[index].values)
        score = _header_score(row)
        filled = sum(1 for v in row if v is not None and str(v).strip() not in ("", "nan"))
        # 동점이면 채워진 셀이 많은 위쪽 행을 선호
        total = score * 10 + min(filled, 50)
        if score > 0 and total > best_score:
            best_index, best_score = index, total
    return best_index if best_score > 0 else 0


def _dedupe_headers(headers: Sequence[Any]) -> List[str]:
    out: List[str] = []
    seen: Dict[str, int] = {}
    for index, value in enumerate(headers):
        text = "" if value is None else str(value).strip()
        if text.lower() == "nan":
            text = ""
        if not text:
            text = "컬럼_%d" % (index + 1)
        if text in seen:
            seen[text] += 1
            text = "%s_%d" % (text, seen[text])
        else:
            seen[text] = 0
        out.append(text)
    return out


def list_sheets(path: str) -> List[str]:
    if not path.lower().endswith(EXCEL_EXTENSIONS):
        return []
    pd = _import_pandas()
    try:
        with pd.ExcelFile(path) as book:
            return list(book.sheet_names)
    except Exception as exc:
        raise IngestError("엑셀 파일을 열 수 없습니다: %s" % exc) from exc


def load_table(path: str, sheet: Optional[str] = None,
               max_rows: Optional[int] = None) -> Tuple[List[str], List[Dict[str, Any]], Dict[str, Any]]:
    """파일 → (헤더목록, 행 dict 리스트, 메타)."""
    pd = _import_pandas()
    if not os.path.exists(path):
        raise IngestError("파일을 찾을 수 없습니다: %s" % path)
    lower = path.lower()

    if lower.endswith(EXCEL_EXTENSIONS):
        raw, meta = _read_excel(pd, path, sheet)
    elif lower.endswith(CSV_EXTENSIONS):
        raw, meta = _read_csv(pd, path)
    else:
        raise IngestError("지원하지 않는 파일 형식입니다(.xlsx/.xls/.csv 만 지원).")

    if raw is None or len(raw) == 0:
        raise IngestError("데이터가 비어 있습니다.")

    header_row = detect_header_row(raw)
    headers = _dedupe_headers(list(raw.iloc[header_row].values))
    body = raw.iloc[header_row + 1:]

    rows: List[Dict[str, Any]] = []
    truncated = False
    for position in range(len(body)):
        if max_rows and len(rows) >= max_rows:
            truncated = True
            break
        values = list(body.iloc[position].values)
        if all(v is None or str(v).strip() in ("", "nan", "NaT") for v in values):
            continue
        rows.append({headers[i]: (values[i] if i < len(values) else None)
                     for i in range(len(headers))})

    if not rows:
        raise IngestError("헤더 이후 데이터 행이 없습니다. 헤더 행 인식 결과를 확인하십시오.")

    meta.update({
        "headerRow": header_row,
        "rowCount": len(rows),
        "columnCount": len(headers),
        "truncated": truncated,
        "fileName": os.path.basename(path),
        "fileSize": os.path.getsize(path),
    })
    return headers, rows, meta


def _read_excel(pd, path: str, sheet: Optional[str]):
    try:
        with pd.ExcelFile(path) as book:
            names = list(book.sheet_names)
            target = sheet if sheet in names else names[0]
            frame = book.parse(target, header=None, dtype=object)
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError(
            "엑셀 파일을 읽지 못했습니다(%s). openpyxl 설치 여부와 파일 손상 여부를 확인하십시오." % exc
        ) from exc
    return _clean_frame(frame), {"sheet": target, "sheets": names, "format": "excel"}


def _read_csv(pd, path: str):
    delimiter = "\t" if path.lower().endswith(".tsv") else None
    last_error: Optional[Exception] = None
    for encoding in CSV_ENCODINGS:
        try:
            with io.open(path, "r", encoding=encoding, errors="strict") as handle:
                frame = pd.read_csv(handle, header=None, dtype=object, sep=delimiter,
                                    engine="python", skip_blank_lines=False)
            return _clean_frame(frame), {"encoding": encoding, "format": "csv"}
        except (UnicodeDecodeError, UnicodeError) as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            continue
    raise IngestError("CSV 를 읽지 못했습니다(인코딩 확인 필요): %s" % last_error)


def _clean_frame(frame):
    """NaN → None 으로 통일(문자열 'nan' 방지)."""
    try:
        return frame.where(frame.notna(), None)
    except Exception:
        return frame
