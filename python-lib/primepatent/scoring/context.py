# -*- coding: utf-8 -*-
"""스코어링 전처리 컨텍스트: 비교집단, 출원인 통계, 인용 문헌 색인."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

from ..config import ScoringConfig
from ..parsing import safe_log1p, to_text, years_between
from ..peers import GlobalIndex, PeerSet

_DOC_KEY_RE = re.compile(r"[^0-9A-Z]")

RECENT_YEARS = 5


def doc_key(value: Any) -> str:
    """문헌번호 비교용 키(국가코드 + 숫자)."""
    text = _DOC_KEY_RE.sub("", to_text(value).upper())
    return text


def digits_key(value: Any) -> str:
    text = re.sub(r"\D", "", to_text(value))
    return text[-11:] if len(text) > 11 else text


class AnalysisContext:
    """전체 모집단에서 1회 계산해 두는 통계.

    ``records``      : 업로드된 전체 문헌. 인용 문헌번호 → 출원인 해석과
                       출원인 포트폴리오 통계에 사용한다.
    ``peer_records`` : 백분위 비교집단을 구성할 문헌(기본값은 records).
                       패밀리 중복 제거를 켠 경우 **채점 단위(대표문헌)** 를 넘겨야 한다.
                       그러지 않으면 6개국에 출원된 패밀리가 분포에 6번 반영되어
                       백분위가 왜곡된다(동일 발명이 비교집단을 지배).
    """

    def __init__(self, records: Sequence[Dict[str, Any]], config: ScoringConfig,
                 as_of: Optional[date] = None,
                 peer_records: Optional[Sequence[Dict[str, Any]]] = None):
        self.config = config
        self.as_of = as_of or date.today()
        self.records = list(records)
        self.peer_records = list(peer_records) if peer_records is not None else self.records
        self.peers = PeerSet(config.peer_min_size, config.peer_year_window)
        self.applicant_family_count: Dict[str, int] = {}
        self.applicant_recent_count: Dict[str, int] = {}
        self.applicant_family_index = GlobalIndex()
        self.applicant_recent_index = GlobalIndex()
        self.doc_index: Dict[str, Dict[str, Any]] = {}
        self.digit_index: Dict[str, Dict[str, Any]] = {}
        self.topic_family_total = 0
        self._build()

    # ------------------------------------------------------------------ topic
    def topic_of(self, record: Dict[str, Any]) -> str:
        label = to_text(record.get("topicLabel"))
        return label or (self.config.topic_name or "Primary Topic")

    @staticmethod
    def year_of(record: Dict[str, Any]) -> Optional[int]:
        return record.get("priorityYear")

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self._build_doc_index()
        self._build_applicant_stats()
        self._build_peers()

    def _build_doc_index(self) -> None:
        for record in self.records:
            for value in (record.get("docNumber"), record.get("publicationNumber"),
                          record.get("registrationNumber"), record.get("applicationNumber")):
                key = doc_key(value)
                if key:
                    self.doc_index.setdefault(key, record)
                digits = digits_key(value)
                if digits and len(digits) >= 6:
                    self.digit_index.setdefault(digits, record)

    def _build_applicant_stats(self) -> None:
        """출원인별 패밀리 수 / 최근 5년 출원 수 (패밀리 중복 제거)."""
        seen_pairs = set()
        seen_recent = set()
        families = set()
        recent_cut = self.as_of.year - RECENT_YEARS
        for record in self.records:
            family = record.get("_familyKey") or record.get("_key")
            families.add(family)
            keys = record.get("applicantKeys") or [record.get("applicantKey") or "unknown"]
            year = record.get("priorityYear")
            for key in keys:
                if not key:
                    continue
                pair = (key, family)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    self.applicant_family_count[key] = self.applicant_family_count.get(key, 0) + 1
                if year is not None and year >= recent_cut and pair not in seen_recent:
                    seen_recent.add(pair)
                    self.applicant_recent_count[key] = self.applicant_recent_count.get(key, 0) + 1
        self.topic_family_total = len(families)
        for key, count in self.applicant_family_count.items():
            self.applicant_family_index.add(count)
            self.applicant_recent_index.add(self.applicant_recent_count.get(key, 0))

    def _build_peers(self) -> None:
        metrics = {
            "logForward": lambda r: safe_log1p(r.get("forwardCitationCountResolved")),
            "logBackward": lambda r: safe_log1p(r.get("backwardCitationCountResolved")),
            "claimCount": lambda r: r.get("claimCount"),
            "independentClaimCount": lambda r: r.get("independentClaimCount"),
            "cpcSubgroups": lambda r: len(r.get("cpcSubgroups") or []) or None,
            "citationSpeed": self.citation_speed,
            "uniqueCitingApplicants": self.unique_citing_applicants,
            "priorityOrdinal": self.priority_ordinal,
            "familyCountryCount": lambda r: (r.get("_family") or {}).get("countryCount"),
        }
        self.peers.build(self.peer_records, metrics, self.topic_of, self.year_of)

    # ------------------------------------------------------------------ metric helpers
    def citation_speed(self, record: Dict[str, Any]) -> Optional[float]:
        """연간 피인용 속도 = 피인용 수 / MAX(1, 공개 후 경과연수)."""
        count = record.get("forwardCitationCountResolved")
        if count is None:
            return None
        start = record.get("publicationDate") or record.get("earliestPriorityDate")
        elapsed = years_between(start, self.as_of)
        if elapsed is None:
            return None
        return float(count) / max(1.0, elapsed)

    def priority_ordinal(self, record: Dict[str, Any]) -> Optional[float]:
        value = record.get("earliestPriorityDate")
        return float(value.toordinal()) if isinstance(value, date) else None

    def resolve_citing_records(self, doc_numbers: Sequence[str]) -> List[Dict[str, Any]]:
        """인용 문헌번호를 업로드 모집단 내 레코드로 해석(가능한 범위)."""
        found: List[Dict[str, Any]] = []
        for number in doc_numbers or []:
            record = self.doc_index.get(doc_key(number))
            if record is None:
                digits = digits_key(number)
                record = self.digit_index.get(digits) if digits and len(digits) >= 6 else None
            if record is not None:
                found.append(record)
        return found

    def unique_citing_applicants(self, record: Dict[str, Any]) -> Optional[float]:
        """고유 비자기 피인용 출원인 수.

        모집단 내에서 해석 가능한 인용 문헌의 출원인을 세고,
        해석 불가한 문헌은 별도 프록시(타인 피인용 문헌 수)로 보완한다.
        """
        cached = record.get("_uniqueCitingApplicants")
        if cached is not None:
            return cached

        citing = list(record.get("otherForwardCitations") or [])
        if not citing:
            citing = [c for c in (record.get("forwardCitations") or [])
                      if c not in set(record.get("selfForwardCitations") or [])]
        own_keys = set(record.get("applicantKeys") or [])
        resolved = self.resolve_citing_records(citing)
        applicants = set()
        for cite in resolved:
            for key in (cite.get("applicantKeys") or []):
                if key and key not in own_keys:
                    applicants.add(key)

        unresolved = max(0, len(citing) - len(resolved))
        method = "resolved"
        value = float(len(applicants))
        if citing and len(resolved) < max(1, len(citing) * 0.3):
            # 해석률이 낮으면 문헌 수 프록시 사용(과소평가 방지)
            method = "proxy"
            value = float(len(citing))
        record["_uniqueCitingApplicants"] = value
        record["_uniqueCitingApplicantsMethod"] = method
        record["_citingUnresolved"] = unresolved
        return value

    # ------------------------------------------------------------------ rank
    def rank(self, metric: str, record: Dict[str, Any], value: Optional[float]):
        return self.peers.rank(metric, self.topic_of(record), self.year_of(record), value)

    def peer_stats(self, metric: str, record: Dict[str, Any]):
        """해당 문헌에 적용된 비교집단의 분포 요약(최소·사분위·중앙·최대)."""
        return self.peers.stats(metric, self.topic_of(record), self.year_of(record))
