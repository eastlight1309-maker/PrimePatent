# -*- coding: utf-8 -*-
"""법적상태 문자열 → 표준 상태코드 분류 (한글/영문 WIPS·DOCDB 표기 모두 처리)."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Optional

from .parsing import to_date, to_text, years_between

GRANTED_ALIVE = "granted_alive"
GRANTED_EXPIRING = "granted_expiring"
UNDER_EXAMINATION = "under_examination"
FILED = "filed"
LAPSED = "lapsed"
REJECTED = "rejected"
INVALIDATED = "invalidated"
UNKNOWN = "unknown"

STATUS_LABEL = {
    GRANTED_ALIVE: "등록·존속",
    GRANTED_EXPIRING: "등록·만료임박",
    UNDER_EXAMINATION: "공개·심사중",
    FILED: "출원(심사 미청구)",
    LAPSED: "등록 후 소멸·포기",
    REJECTED: "거절·취하·포기",
    INVALIDATED: "무효 확정",
    UNKNOWN: "상태 미상",
}

# 대표문헌 선정 우선순위(높을수록 우선)
STATUS_PRIORITY = {
    GRANTED_ALIVE: 100,
    GRANTED_EXPIRING: 90,
    LAPSED: 70,
    UNDER_EXAMINATION: 60,
    FILED: 50,
    UNKNOWN: 30,
    REJECTED: 10,
    INVALIDATED: 5,
}

_GRANT_RE = re.compile(r"(등록|granted|grant|registered|patented|공고)", re.IGNORECASE)
_ALIVE_RE = re.compile(r"(존속|유효|alive|in\s*force|active|납부)", re.IGNORECASE)
_LAPSE_RE = re.compile(r"(소멸|만료|expire|expired|lapse|lapsed|ceased|불납|말소)", re.IGNORECASE)
_ABANDON_RE = re.compile(r"(포기|abandon|abandoned|withdraw|withdrawn|취하)", re.IGNORECASE)
_REJECT_RE = re.compile(r"(거절|refus|reject|dismiss)", re.IGNORECASE)
_INVALID_RE = re.compile(r"(무효|invalid|revoked|revocation)", re.IGNORECASE)
_EXAM_RE = re.compile(r"(심사중|심사청구|공개|pending|examination|published|계속)", re.IGNORECASE)
_FILED_RE = re.compile(r"(출원|filed|application)", re.IGNORECASE)
_DEAD_RE = re.compile(r"^(dead|inactive)$", re.IGNORECASE)

EXPIRING_YEARS = 2.0


def classify(record: Dict[str, Any], as_of: Optional[date] = None) -> str:
    """레코드의 상태코드를 판정한다."""
    as_of = as_of or date.today()
    text = " ".join(filter(None, [
        to_text(record.get("legalStatus")),
        to_text(record.get("docdbLegalStatus")),
    ])).strip()

    rejection = record.get("rejectionDecision")
    registered = bool(to_text(record.get("registrationNumber")) or record.get("registrationDate"))

    if text:
        if _INVALID_RE.search(text) and not _EXAM_RE.search(text):
            return INVALIDATED
        granted = bool(_GRANT_RE.search(text)) or registered
        if granted:
            if _INVALID_RE.search(text):
                return INVALIDATED
            if _LAPSE_RE.search(text) or _ABANDON_RE.search(text) or _DEAD_RE.search(text):
                return LAPSED
            if _ALIVE_RE.search(text) or not _REJECT_RE.search(text):
                return _expiring_or_alive(record, as_of)
        if _REJECT_RE.search(text) or _ABANDON_RE.search(text):
            return REJECTED
        if _DEAD_RE.search(text):
            return LAPSED if registered else REJECTED
        if _EXAM_RE.search(text):
            return UNDER_EXAMINATION
        if _FILED_RE.search(text):
            return FILED if record.get("examinationRequested") is False else UNDER_EXAMINATION

    # 상태 문자열이 없을 때는 서지 정보로 추정
    if registered:
        return _expiring_or_alive(record, as_of)
    if rejection is True:
        return REJECTED
    if record.get("publicationDate"):
        return UNDER_EXAMINATION
    if record.get("applicationDate"):
        return FILED if record.get("examinationRequested") is False else UNDER_EXAMINATION
    return UNKNOWN


def _expiring_or_alive(record: Dict[str, Any], as_of: date) -> str:
    remaining = remaining_term_years(record, as_of)
    if remaining is not None and remaining <= 0:
        return LAPSED
    if remaining is not None and remaining <= EXPIRING_YEARS:
        return GRANTED_EXPIRING
    return GRANTED_ALIVE


def remaining_term_years(record: Dict[str, Any], as_of: Optional[date] = None) -> Optional[float]:
    """잔존기간(년) 추정. 만료일이 있으면 사용하고, 없으면 최초우선일 + 20년."""
    as_of = as_of or date.today()
    expiry = to_date(record.get("expiryDate"))
    if expiry:
        return max(0.0, (expiry - as_of).days / 365.25)
    start = record.get("earliestPriorityDate") or record.get("applicationDate")
    elapsed = years_between(start, as_of)
    if elapsed is None:
        return None
    from .config import PATENT_TERM_YEARS
    return max(0.0, PATENT_TERM_YEARS - elapsed)
