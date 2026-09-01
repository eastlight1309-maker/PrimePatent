# -*- coding: utf-8 -*-
"""WIPS 셀 값 파서 (날짜/숫자/리스트/불리언/국가코드/법적상태)."""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, List, Optional

_LIST_SPLIT_RE = re.compile(r"[;|\n\r]+|(?<!\d),(?!\d)|,\s+|\t+")
_DATE_CLEAN_RE = re.compile(r"[^0-9]")
_COUNTRY_PREFIX_RE = re.compile(r"^([A-Z]{2})")
_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

# 문서번호 앞 2자리 국가코드로 인정할 값 (WO/EP 포함)
_KNOWN_COUNTRIES = {
    "KR", "US", "JP", "CN", "EP", "WO", "TW", "DE", "GB", "FR", "IN", "CA",
    "AU", "RU", "BR", "MX", "SG", "MY", "TH", "VN", "ID", "PH", "IL", "NL",
    "IT", "ES", "SE", "CH", "AT", "BE", "DK", "FI", "NO", "PL", "TR", "ZA",
    "HK", "MO", "NZ", "PT", "IE", "CZ", "HU", "RO", "GR", "AR", "CL", "SA",
    "AE", "EA", "AP", "OA", "UA", "BY", "KZ",
}

TRUE_TOKENS = {"y", "yes", "true", "1", "t", "o", "유", "있음", "있다", "존재",
               "예", "yes.", "有", "적용", "청구", "설정", "완료"}
FALSE_TOKENS = {"n", "no", "false", "0", "f", "x", "무", "없음", "없다", "미청구",
               "아니오", "無", "미적용", "미설정", "-", "미해당"}


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    text = str(value).strip()
    return text == "" or text.lower() in ("nan", "none", "null", "-", "n/a", "na")


def to_text(value: Any, limit: Optional[int] = None) -> str:
    if is_blank(value):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = text.replace("\r\n", "\n")
    if limit and len(text) > limit:
        text = text[:limit]
    return text


def to_list(value: Any) -> List[str]:
    """구분자(;, |, 개행, 콤마)로 분리된 다중값 셀을 리스트로."""
    if is_blank(value):
        return []
    if isinstance(value, (list, tuple, set)):
        items = [to_text(v) for v in value]
    else:
        text = to_text(value)
        items = _LIST_SPLIT_RE.split(text)
    out: List[str] = []
    seen = set()
    for item in items:
        item = (item or "").strip().strip("'\"")
        if not item or item in ("-",):
            continue
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# 콤마 뒤에 오면 법인명의 일부로 보아 분리하지 않을 접미사
_CORP_SUFFIX_TOKENS = (
    "ltd", "ltd.", "co", "co.", "inc", "inc.", "llc", "llp", "corp", "corp.",
    "limited", "incorporated", "corporation", "company", "gmbh", "ag", "sa", "s.a.",
    "nv", "n.v.", "bv", "b.v.", "plc", "kk", "k.k.", "pte", "pte.", "pty", "srl",
    "s.r.l.", "spa", "s.p.a.", "oy", "ab", "as", "a/s", "kg", "mbh", "sas", "sarl",
    "주식회사", "유한회사", "(주)", "(유)",
)


def to_entity_list(value: Any) -> List[str]:
    """출원인·발명자처럼 **이름**이 들어오는 다중값 셀 파서.

    ``to_list`` 는 ", " 에서도 분리하므로 "SAMSUNG ELECTRONICS CO., LTD." 가
    두 개의 출원인으로 쪼개진다. 여기서는 세미콜론/파이프/개행/탭으로만 나누고,
    콤마는 뒤 토막이 법인격 표기가 아닐 때만 분리한다.
    """
    if is_blank(value):
        return []
    if isinstance(value, (list, tuple, set)):
        raw_parts = [to_text(v) for v in value]
    else:
        raw_parts = re.split(r"[;|\n\r\t]+", to_text(value))

    out: List[str] = []
    seen = set()
    for part in raw_parts:
        for name in _split_names_on_comma(part):
            name = name.strip().strip("'\"")
            if not name or name == "-":
                continue
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _split_names_on_comma(text: str) -> List[str]:
    """콤마 분리하되 법인격 접미사 앞의 콤마는 유지한다."""
    segments = [seg.strip() for seg in text.split(",")]
    if len(segments) <= 1:
        return [text.strip()] if text.strip() else []
    names: List[str] = []
    for segment in segments:
        if not segment:
            continue
        head = segment.split()[0].lower().rstrip(".,") if segment.split() else ""
        is_suffix = (segment.lower() in _CORP_SUFFIX_TOKENS
                     or head in {t.rstrip(".") for t in _CORP_SUFFIX_TOKENS})
        if is_suffix and names:
            names[-1] = names[-1] + ", " + segment
        else:
            names.append(segment)
    return names


def to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    number = to_float(value, None)
    if number is None:
        return default
    try:
        return int(round(number))
    except (ValueError, OverflowError):
        return default


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if is_blank(value):
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER_RE.search(str(value).replace(",", ""))
    if not match:
        return default
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return default


def to_date(value: Any) -> Optional[date]:
    """WIPS 날짜(YYYY-MM-DD, YYYY.MM.DD, YYYYMMDD, datetime, 엑셀 serial) 파싱."""
    if is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # 엑셀 serial date (1900 시스템). 20000101 형태의 숫자와 구분.
        number = float(value)
        if 10000 <= number <= 100000:
            try:
                from datetime import timedelta
                return (datetime(1899, 12, 30) + timedelta(days=int(number))).date()
            except (ValueError, OverflowError):
                return None
    digits = _DATE_CLEAN_RE.sub("", str(value))
    if len(digits) >= 8:
        digits = digits[:8]
        try:
            return date(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            try:  # 일자가 00 인 경우가 있음
                return date(int(digits[0:4]), max(1, int(digits[4:6])), 1)
            except ValueError:
                return None
    if len(digits) == 6:
        try:
            return date(int(digits[0:4]), int(digits[4:6]), 1)
        except ValueError:
            return None
    if len(digits) == 4:
        try:
            return date(int(digits), 1, 1)
        except ValueError:
            return None
    return None


_NEGATIVE_RE = re.compile(r"^(무|없음|없다|해당없음|미청구|미설정|미적용|미해당|none|없)$")
_POSITIVE_RE = re.compile(r"(있음|있다|유$|^유|yes|설정됨|존재)")


def to_bool(value: Any) -> Optional[bool]:
    """Y/N, 유/무 등을 불리언으로. 판단 불가하면 None(=데이터 없음).

    주의: "무효심판(2)" 처럼 부정어(무)를 부분문자열로 포함하지만 실제로는
    이벤트가 존재하는 값이 있으므로, 완전일치 → 정규식 → 숫자 → 내용유무 순으로 본다.
    """
    if is_blank(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = to_text(value).strip().lower()
    if not text:
        return None
    if text in TRUE_TOKENS:
        return True
    if text in FALSE_TOKENS:
        return False
    if _NEGATIVE_RE.match(text):
        return False
    if _POSITIVE_RE.search(text):
        return True
    number = to_float(text, None)
    if number is not None and not re.search(r"[a-z가-힣]", text.replace("건", "")):
        return number > 0
    if number is not None:
        # "무효심판(2)", "거절결정불복심판 1회" 등 - 건수가 있으면 존재로 본다
        return number > 0
    # 그 밖의 텍스트(예: 분할, 계속출원)는 값이 존재하므로 True
    return True


def country_of(doc_number: Any) -> Optional[str]:
    """문헌번호/출원번호 앞 2자리에서 국가코드 추출."""
    text = to_text(doc_number).upper().replace(" ", "")
    if not text:
        return None
    match = _COUNTRY_PREFIX_RE.match(text)
    if match and match.group(1) in _KNOWN_COUNTRIES:
        return match.group(1)
    return None


def countries_of(values: Any) -> List[str]:
    out: List[str] = []
    for item in (values if isinstance(values, (list, tuple)) else to_list(values)):
        code = country_of(item)
        if code and code not in out:
            out.append(code)
    return out


# 국가코드는 반드시 '독립된 두 글자 토큰' 이어야 한다.
# 경계를 강제하지 않으면 EPO→EP, Europe→RO, SEPTEMBER→SE/PT/BE 처럼
# 단어 안의 두 글자가 국가로 오인되어 시장 진입도가 부풀려진다.
_COUNTRY_COUNT_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{2})(?![A-Z])\s*[:(\[=-]?\s*(\d+)?")


def country_doc_counts(value: Any) -> Dict[str, int]:
    """'KR:2|US:3|JP:1' / 'KR(2), US(3)' 형태의 개별국 문헌 수를 {국가: 건수} 로.

    건수 표기가 없으면 1건으로 본다(주요 시장 진입도는 유무만 보므로 무방).
    """
    result: Dict[str, int] = {}
    text = to_text(value).upper()
    if not text:
        return result
    for match in _COUNTRY_COUNT_RE.finditer(text):
        code = match.group(1)
        if code not in _KNOWN_COUNTRIES:
            continue
        count = int(match.group(2)) if match.group(2) else 1
        result[code] = result.get(code, 0) + max(1, count)
    return result


def normalize_country(value: Any) -> Optional[str]:
    text = to_text(value).upper().strip()
    if not text:
        return None
    text = re.sub(r"[^A-Z]", "", text)[:2]
    return text if len(text) == 2 else None


def year_of(value: Optional[date]) -> Optional[int]:
    return value.year if isinstance(value, date) else None


def years_between(start: Optional[date], end: Optional[date]) -> Optional[float]:
    if not isinstance(start, date) or not isinstance(end, date):
        return None
    return (end - start).days / 365.25


def safe_log1p(value: Optional[float]) -> float:
    try:
        return math.log1p(max(0.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return low
    if math.isnan(value):
        return low
    return max(low, min(high, value))
