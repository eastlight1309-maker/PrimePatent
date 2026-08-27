# -*- coding: utf-8 -*-
"""LLM 배치 분석기: 병렬 호출 + 캐시 + 취소 + 응답 검증."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Sequence

from .client import BaseLLMClient, LLMResult
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("primepatent.llm.analyzer")

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)

# LLM 이 산출하는 점수의 허용 범위 (config.COMPONENT_MAX 의 LLM 배점과 일치)
SCORE_BOUNDS = {
    "claimBreadthScore": (0.0, 3.0),
    "coreCentralityScore": (0.0, 5.0),
    "claimExpansionScore": (0.0, 5.0),
    "claimTypeDiversityScore": (0.0, 3.0),
}
RATIONALE_KEYS = ("centralityRationale", "expansionRationale", "diversityRationale", "rationale")


class LLMCache:
    """LLM 분석 결과 캐시.

    여러 분석 작업이 하나의 캐시를 공유하므로 **캐시 자체가 락을 갖는다.**
    (분석기마다 별도 락을 두면 같은 dict 를 서로 다른 락으로 보호하게 되어
     read-modify-write 가 겹치고 동일 문헌을 중복 호출할 수 있다)
    크기 상한을 두어 장시간 구동 시 메모리가 무한히 늘지 않게 한다.
    """

    def __init__(self, max_entries: int = 20000):
        self.max_entries = max(100, int(max_entries))
        self._data: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            value = self._data.get(key)
            if value is not None:
                self._data.move_to_end(key)          # 최근 사용 항목을 뒤로
                return dict(value)
        return None

    def put(self, key: str, value: Dict[str, Any]) -> None:
        with self._lock:
            self._data[key] = dict(value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)       # 가장 오래된 항목 제거

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


def analysis_defaults(status: str = "skipped", message: str = "") -> Dict[str, Any]:
    """LLM 분석을 수행하지 않은 문헌의 기본값(모든 LLM 점수 0)."""
    payload = {key: 0.0 for key in SCORE_BOUNDS}
    payload.update({
        "claimAnalysis": {},
        "keyFeatures": [],
        "status": status,          # ok | skipped | error
        "provider": "",
        "llmId": "",
        "message": message,
    })
    for key in RATIONALE_KEYS:
        payload[key] = message
    return payload


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """모델 응답에서 JSON 객체를 안전하게 추출한다."""
    if not text:
        return None
    candidate = text.strip()
    fence = _JSON_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    start = candidate.find("{")
    if start < 0:
        return None
    depth, in_string, escape = 0, False, False
    for index in range(start, len(candidate)):
        char = candidate[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(candidate[start:index + 1])
                    return parsed if isinstance(parsed, dict) else None
                except ValueError:
                    return None
    return None


def _clamp_number(value: Any, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    if number != number:  # NaN
        return low
    return max(low, min(high, number))


def validate_analysis(payload: Dict[str, Any]) -> Dict[str, Any]:
    """모델 응답을 점수 범위에 맞춰 검증·보정한다."""
    result = analysis_defaults(status="ok")
    for key, (low, high) in SCORE_BOUNDS.items():
        result[key] = round(_clamp_number(payload.get(key), low, high), 2)

    raw_claim = payload.get("claimAnalysis")
    claim: Dict[str, Any] = {}
    if isinstance(raw_claim, dict):
        elements = raw_claim.get("coreElementsInIndependentClaims")
        claim = {
            "coreElementsInIndependentClaims":
                [str(e)[:120] for e in elements][:12] if isinstance(elements, (list, tuple)) else [],
            "linkageClaimed": bool(raw_claim.get("linkageClaimed")),
            "independentClaimsWithCore":
                int(_clamp_number(raw_claim.get("independentClaimsWithCore"), 0, 200)),
            "relatedClaimCount": int(_clamp_number(raw_claim.get("relatedClaimCount"), 0, 500)),
            "totalClaimCount": int(_clamp_number(raw_claim.get("totalClaimCount"), 0, 500)),
            "relatedClaimRatio": round(_clamp_number(raw_claim.get("relatedClaimRatio"), 0, 1), 3),
            "expansionDependentCount":
                int(_clamp_number(raw_claim.get("expansionDependentCount"), 0, 500)),
            "claimTypes": [str(t)[:40] for t in (raw_claim.get("claimTypes") or [])][:10]
                if isinstance(raw_claim.get("claimTypes"), (list, tuple)) else [],
            "independentClaimCount":
                int(_clamp_number(raw_claim.get("independentClaimCount"), 0, 200)),
            "numericLimitationCount":
                int(_clamp_number(raw_claim.get("numericLimitationCount"), 0, 200)),
            "designAroundRisk": str(raw_claim.get("designAroundRisk") or "").lower()[:10],
        }
        # 비율이 비어 있으면 개수로 보정한다(둘 다 있으면 모델 값을 신뢰).
        if not claim["relatedClaimRatio"] and claim["totalClaimCount"]:
            claim["relatedClaimRatio"] = round(
                claim["relatedClaimCount"] / float(claim["totalClaimCount"]), 3)
    result["claimAnalysis"] = claim

    features = payload.get("keyFeatures")
    if isinstance(features, (list, tuple)):
        result["keyFeatures"] = [str(f)[:120] for f in features][:8]
    for key in RATIONALE_KEYS:
        result[key] = str(payload.get(key) or "")[:1200]
    return result


def document_fingerprint(document: Dict[str, Any], topic_signature: str, llm_id: str) -> str:
    payload = json.dumps({
        "doc": {k: document.get(k) for k in sorted(document.keys())},
        "topic": topic_signature,
        "llm": llm_id,
        "prompt": PROMPT_VERSION,
    }, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LLMAnalyzer:
    """문헌 목록에 대한 LLM 분석 실행기."""

    def __init__(self, client: BaseLLMClient, topic_name: str = "", topic_description: str = "",
                 topic_keywords: Optional[Sequence[str]] = None, char_limit: int = 6000,
                 max_workers: int = 4, cache: Optional[LLMCache] = None,
                 core_technology: str = ""):
        self.client = client
        self.topic_name = topic_name
        self.topic_description = topic_description
        self.topic_keywords = list(topic_keywords or [])
        self.char_limit = char_limit
        self.core_technology = core_technology
        self.max_workers = max(1, int(max_workers))
        self.cache = cache if cache is not None else LLMCache()
        self.stats = {"total": 0, "ok": 0, "error": 0, "cached": 0}

    @property
    def topic_signature(self) -> str:
        return "|".join([self.topic_name, self.topic_description,
                         ",".join(self.topic_keywords), self.core_technology])

    def analyze_one(self, document: Dict[str, Any]) -> Dict[str, Any]:
        fingerprint = document_fingerprint(document, self.topic_signature, self.client.llm_id)
        cached = self.cache.get(fingerprint)
        if cached is not None:
            cached["cached"] = True
            return cached

        prompt = build_user_prompt(document, self.topic_name, self.topic_description,
                                   self.topic_keywords, self.char_limit, self.core_technology)
        result: LLMResult = self.client.complete(SYSTEM_PROMPT, prompt)
        if not result.ok:
            analysis = analysis_defaults(
                status="error", message="LLM 호출 실패: %s" % (result.error or "unknown"))
            analysis["provider"] = result.provider
            analysis["llmId"] = result.llm_id
            return analysis

        payload = extract_json(result.text)
        if payload is None:
            analysis = analysis_defaults(
                status="error", message="LLM 응답을 JSON 으로 해석하지 못했습니다.")
            analysis["provider"] = result.provider
            analysis["llmId"] = result.llm_id
            analysis["rawSnippet"] = result.text[:300]
            return analysis

        analysis = validate_analysis(payload)
        analysis["provider"] = result.provider
        analysis["llmId"] = result.llm_id
        analysis["elapsedMs"] = result.elapsed_ms
        self.cache.put(fingerprint, analysis)
        return analysis

    def analyze_many(self, documents: List[Dict[str, Any]],
                     progress: Optional[Callable[[int, int], None]] = None,
                     cancel_event: Optional[threading.Event] = None) -> Dict[str, Dict[str, Any]]:
        """{documentKey: analysis}. cancel_event 가 set 되면 남은 작업을 중단한다."""
        results: Dict[str, Dict[str, Any]] = {}
        total = len(documents)
        self.stats = {"total": total, "ok": 0, "error": 0, "cached": 0}
        if total == 0:
            return results

        done = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {}
            for document in documents:
                if cancel_event is not None and cancel_event.is_set():
                    break
                futures[pool.submit(self.analyze_one, document)] = document.get("_key")
            for future in as_completed(futures):
                key = futures[future]
                try:
                    analysis = future.result()
                except Exception as exc:  # 개별 문헌 실패가 전체를 막지 않도록
                    logger.exception("LLM 분석 실패: %s", key)
                    analysis = analysis_defaults(
                        status="error", message="분석 예외: %s: %s" % (type(exc).__name__, exc))
                results[key] = analysis
                if analysis.get("status") == "ok":
                    self.stats["ok"] += 1
                    if analysis.get("cached"):
                        self.stats["cached"] += 1
                else:
                    self.stats["error"] += 1
                done += 1
                if progress is not None:
                    progress(done, total)
                if cancel_event is not None and cancel_event.is_set():
                    for pending in futures:
                        pending.cancel()
        return results
