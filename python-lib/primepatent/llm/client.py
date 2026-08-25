# -*- coding: utf-8 -*-
"""LLM 호출 클라이언트.

- 운영(Dataiku DSS): LLM Mesh (``project.get_llm(llm_id).new_completion()``)
- 로컬/오프라인: 휴리스틱 폴백. 결과에 provider="heuristic" 을 남겨
  화면과 결과 파일에서 'LLM 미사용 추정치' 임을 명확히 표시한다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from ..config import ALLOWED_LLM_IDS, DEFAULT_LLM_ID

logger = logging.getLogger("primepatent.llm")


class LLMError(Exception):
    """LLM 호출 실패."""


@dataclass
class LLMResult:
    text: str
    provider: str
    llm_id: str
    elapsed_ms: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.text) and self.error is None


class BaseLLMClient:
    provider = "base"

    def __init__(self, llm_id: str, timeout_sec: int = 120, max_retries: int = 2):
        self.llm_id = llm_id
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        raise NotImplementedError


class DataikuLLMClient(BaseLLMClient):
    """Dataiku LLM Mesh 클라이언트."""

    provider = "dataiku"

    def __init__(self, llm_id: str, timeout_sec: int = 120, max_retries: int = 2):
        super().__init__(llm_id, timeout_sec, max_retries)
        self._llm = None
        self._lock_init()

    def _lock_init(self) -> None:
        import dataiku  # noqa: WPS433  (Dataiku 환경에서만 존재)
        client = dataiku.api_client()
        project = client.get_default_project()
        self._llm = project.get_llm(self.llm_id)

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        last_error: Optional[str] = None
        for attempt in range(self.max_retries + 1):
            started = time.time()
            try:
                completion = self._llm.new_completion()
                if system_prompt:
                    completion.with_message(system_prompt, role="system")
                completion.with_message(user_prompt, role="user")
                response = completion.execute()
                elapsed = int((time.time() - started) * 1000)
                success = getattr(response, "success", True)
                text = getattr(response, "text", None) or ""
                if success and text:
                    return LLMResult(text=text, provider=self.provider,
                                     llm_id=self.llm_id, elapsed_ms=elapsed)
                last_error = getattr(response, "errorMessage", None) or "빈 응답"
            except Exception as exc:  # 네트워크/쿼터/모델 오류
                last_error = "%s: %s" % (type(exc).__name__, exc)
                logger.warning("LLM 호출 실패(%d/%d): %s", attempt + 1,
                               self.max_retries + 1, last_error)
            if attempt < self.max_retries:
                time.sleep(min(8.0, 1.5 * (2 ** attempt)))
        return LLMResult(text="", provider=self.provider, llm_id=self.llm_id,
                         error=last_error or "알 수 없는 오류")


class HeuristicLLMClient(BaseLLMClient):
    """LLM 을 사용할 수 없는 환경의 폴백. 규칙 기반 추정치를 JSON 으로 반환."""

    provider = "heuristic"

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        from .heuristic import estimate_from_prompt
        started = time.time()
        text = estimate_from_prompt(user_prompt)
        return LLMResult(text=text, provider=self.provider, llm_id=self.llm_id,
                         elapsed_ms=int((time.time() - started) * 1000))


def dataiku_available() -> Tuple[bool, str]:
    """(사용 가능 여부, 사유). 로컬 실행 환경에서는 False 를 반환한다."""
    try:
        import dataiku  # noqa: WPS433
    except ImportError:
        return False, "dataiku 패키지를 찾을 수 없습니다(로컬 실행 환경)."
    try:
        dataiku.api_client().get_default_project()
    except Exception as exc:
        return False, "Dataiku API 연결 실패: %s: %s" % (type(exc).__name__, exc)
    return True, "Dataiku LLM Mesh 사용 가능"


def get_client(llm_id: str = DEFAULT_LLM_ID, timeout_sec: int = 120,
               max_retries: int = 2, allow_fallback: bool = True) -> BaseLLMClient:
    """허용 목록 검증 후 클라이언트를 생성한다."""
    if llm_id not in ALLOWED_LLM_IDS:
        raise LLMError("허용되지 않은 LLM 입니다: %s" % llm_id)
    available, reason = dataiku_available()
    if available:
        try:
            return DataikuLLMClient(llm_id, timeout_sec, max_retries)
        except Exception as exc:
            reason = "LLM(%s) 연결 실패: %s" % (llm_id, exc)
            if not allow_fallback:
                raise LLMError(reason) from exc
    if not allow_fallback:
        raise LLMError(reason)
    logger.warning("LLM 폴백(휴리스틱) 사용: %s", reason)
    return HeuristicLLMClient(llm_id, timeout_sec, max_retries)


def probe_client(llm_id: str = DEFAULT_LLM_ID) -> Dict[str, Any]:
    """화면 표시용 LLM 연결 상태 점검."""
    if llm_id not in ALLOWED_LLM_IDS:
        return {"ok": False, "provider": "none", "message": "허용되지 않은 LLM 입니다."}
    available, reason = dataiku_available()
    if not available:
        return {"ok": False, "provider": "heuristic", "message": reason}
    try:
        client = DataikuLLMClient(llm_id, timeout_sec=30, max_retries=0)
        result = client.complete("", "OK 라고만 답하십시오.")
        if result.ok:
            return {"ok": True, "provider": "dataiku",
                    "message": "정상 (%d ms)" % result.elapsed_ms}
        return {"ok": False, "provider": "dataiku", "message": result.error or "빈 응답"}
    except Exception as exc:
        return {"ok": False, "provider": "dataiku", "message": "%s: %s" % (type(exc).__name__, exc)}
