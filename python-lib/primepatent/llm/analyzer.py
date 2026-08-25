# -*- coding: utf-8 -*-
"""LLM 배치 분석기: 병렬 호출 + 캐시 + 취소 + 응답 검증."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Sequence

from .client import BaseLLMClient, LLMResult
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("primepatent.llm.analyzer")

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)

SCORE_BOUNDS = {
    "topicFitPercent": (0.0, 100.0),
    "claimBreadthScore": (0.0, 4.0),
    "coreContributionScore": (0.0, 8.0),
    "problemImportanceScore": (0.0, 3.0),
    "effectEvidenceScore": (0.0, 3.0),
    "generalityScore": (0.0, 4.0),
}


def analysis_defaults(status: str = "skipped", message: str = "") -> Dict[str, Any]:
    """LLM 분석을 수행하지 않은 문헌의 기본값(모든 LLM 점수 0)."""
    return {
        "topicFitPercent": 0.0,
        "claimBreadthScore": 0.0,
        "coreContributionScore": 0.0,
        "problemImportanceScore": 0.0,
        "effectEvidenceScore": 0.0,
        "generalityScore": 0.0,
        "claimAnalysis": {},
        "keyFeatures": [],
        "rationale": message,
        "status": status,          # ok | skipped | error
        "provider": "",
        "llmId": "",
        "message": message,
    }


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
        claim = {
            "essentialElementCount": int(_clamp_number(raw_claim.get("essentialElementCount"), 0, 200)),
            "numericLimitationCount": int(_clamp_number(raw_claim.get("numericLimitationCount"), 0, 200)),
            "materialLimitation": bool(raw_claim.get("materialLimitation")),
            "processOrderLimitation": bool(raw_claim.get("processOrderLimitation")),
            "functionalLanguage": str(raw_claim.get("functionalLanguage") or "").lower()[:10],
            "multiCategoryIndependentClaims": bool(raw_claim.get("multiCategoryIndependentClaims")),
            "designAroundRisk": str(raw_claim.get("designAroundRisk") or "").lower()[:10],
        }
    result["claimAnalysis"] = claim

    features = payload.get("keyFeatures")
    if isinstance(features, (list, tuple)):
        result["keyFeatures"] = [str(f)[:120] for f in features][:8]
    result["rationale"] = str(payload.get("rationale") or "")[:1200]
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
                 max_workers: int = 4, cache: Optional[Dict[str, Dict]] = None):
        self.client = client
        self.topic_name = topic_name
        self.topic_description = topic_description
        self.topic_keywords = list(topic_keywords or [])
        self.char_limit = char_limit
        self.max_workers = max(1, int(max_workers))
        self.cache = cache if cache is not None else {}
        self._cache_lock = threading.Lock()
        self.stats = {"total": 0, "ok": 0, "error": 0, "cached": 0}

    @property
    def topic_signature(self) -> str:
        return "|".join([self.topic_name, self.topic_description, ",".join(self.topic_keywords)])

    def analyze_one(self, document: Dict[str, Any]) -> Dict[str, Any]:
        fingerprint = document_fingerprint(document, self.topic_signature, self.client.llm_id)
        with self._cache_lock:
            cached = self.cache.get(fingerprint)
        if cached is not None:
            cached = dict(cached)
            cached["cached"] = True
            return cached

        prompt = build_user_prompt(document, self.topic_name, self.topic_description,
                                   self.topic_keywords, self.char_limit)
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
        with self._cache_lock:
            self.cache[fingerprint] = dict(analysis)
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
