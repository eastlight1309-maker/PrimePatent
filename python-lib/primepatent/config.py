# -*- coding: utf-8 -*-
"""스코어링/LLM 설정값.

모든 배점·가중치는 이 모듈에 모아 두고, 사용자가 화면에서 조정한 값은
``ScoringConfig.from_dict`` 로 덮어쓴다(저장 시 실행 스냅샷으로 함께 보관).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Tuple

# =========================
# 사용 허용할 LLM 목록 (고정)
# =========================
ALLOWED_LLM_CANDIDATES: List[Tuple[str, str]] = [
    ("gpt-5-mini | DW_AOAI_APIM_DES1_LOW", "azureopenai:DW_AOAI_APIM_DES1_LOW:gpt-5-mini"),
    ("gpt-5 | DW_AOAI_APIM_DES1_MID", "azureopenai:DW_AOAI_APIM_DES1_MID:gpt-5"),
    ("gpt-5.4-mini | DW_AOAI_APIM_DES1_LOW", "azureopenai:DW_AOAI_APIM_DES1_LOW:gpt-5.4-mini"),
    ("gpt-5.4 | DW_AOAI_APIM_DES1_MID", "azureopenai:DW_AOAI_APIM_DES1_MID:gpt-5.4"),
]
DEFAULT_LLM_ID = "azureopenai:DW_AOAI_APIM_DES1_LOW:gpt-5-mini"
ALLOWED_LLM_IDS = frozenset(llm_id for _, llm_id in ALLOWED_LLM_CANDIDATES)

# =========================
# 영역별 총배점 (합계 100)
# =========================
AREA_MAX = {
    "rights": 30.0,   # 권리 중요도
    "tech": 30.0,     # 기술 중요도
    "market": 20.0,   # 시장 중요도
    "impact": 20.0,   # 영향력·경쟁성
}
TOTAL_MAX = 100.0

# 세부지표 배점 (스펙 8.1 최종 계산식)
COMPONENT_MAX = {
    # 권리 중요도 30
    "rights.survival": 8.0,
    "rights.claimScope": 8.0,          # 정량 4 + LLM 4
    "rights.globalScope": 7.0,
    "rights.remainingTerm": 4.0,
    "rights.defenseSignal": 3.0,
    # 기술 중요도 30
    "tech.topicFit": 8.0,
    "tech.contribution": 8.0,
    "tech.problemEffect": 6.0,         # 문제 3 + 효과 3
    "tech.generality": 4.0,            # LLM 3 + CPC 1
    "tech.followUp": 4.0,
    # 시장 중요도 20
    "market.entry": 8.0,
    "market.applicantPower": 5.0,
    "market.commercial": 4.0,
    "market.competitorCoverage": 3.0,
    # 영향력·경쟁성 20
    "impact.citation": 8.0,
    "impact.diffusion": 5.0,
    "impact.originality": 4.0,
    "impact.conflict": 3.0,
}

# 세부지표별 산출 방식(정량/LLM) - 정량 70 : LLM 30 집계에 사용
COMPONENT_SOURCE = {
    "rights.survival": "quant",
    "rights.claimScope": "mixed",      # 정량 4 / LLM 4
    "rights.globalScope": "quant",
    "rights.remainingTerm": "quant",
    "rights.defenseSignal": "quant",
    "tech.topicFit": "llm",
    "tech.contribution": "llm",
    "tech.problemEffect": "llm",
    "tech.generality": "mixed",        # LLM 3 / 정량 1
    "tech.followUp": "quant",
    "market.entry": "quant",
    "market.applicantPower": "quant",
    "market.commercial": "quant",
    "market.competitorCoverage": "quant",
    "impact.citation": "quant",
    "impact.diffusion": "quant",
    "impact.originality": "quant",
    "impact.conflict": "quant",
}

# 4.3 글로벌 권리범위 - 국가 가중치 (합계 상한 7점)
DEFAULT_GLOBAL_COUNTRY_WEIGHTS = {
    "US": 1.5, "CN": 1.3, "EP": 1.2, "JP": 1.2, "KR": 1.0, "TW": 1.0,
}
DEFAULT_GLOBAL_OTHER_WEIGHT = 0.3

# 6.1 주요 시장 진입도 - 국가 가중치 (합계 상한 8점)
# 스펙 본문의 소비/공급망 분리 서술을 하나의 표로 합친 값(스펙 내 엑셀 수식 기준).
DEFAULT_MARKET_COUNTRY_WEIGHTS = {
    "US": 2.0, "CN": 1.8, "JP": 1.2, "EP": 1.0, "KR": 1.0, "TW": 1.0,
}

# 4.1 권리 생존성 구간점수
SURVIVAL_SCORES = {
    "granted_alive": 8.0,
    "granted_expiring": 6.0,
    "under_examination": 5.0,
    "filed": 3.0,
    "lapsed": 2.0,
    "rejected": 0.0,
    "invalidated": 0.0,
    "unknown": 2.0,
}

# 4.4 잔존기간 구간점수 (년 단위 하한, 점수)
REMAINING_TERM_BANDS = [(12.0, 4.0), (8.0, 3.0), (4.0, 2.0), (0.0, 1.0)]
PATENT_TERM_YEARS = 20.0


@dataclass
class ScoringConfig:
    """분석 실행 1건에 대한 설정 스냅샷."""

    # 주제 정의
    topic_name: str = "Primary Topic"
    topic_description: str = ""
    topic_keywords: List[str] = field(default_factory=list)

    # Gate
    gate_topic_fit_min: float = 70.0          # Gate 1: Primary Topic 적합도(%)
    apply_gate: bool = True                   # False 면 gate 결과를 표시만 하고 제외하지 않음

    # 기술 적합도 환산 방식: "softened" = MIN(8, MAX(0,(fit-60)/40*8)), "linear" = fit/100*8
    topic_fit_mode: str = "softened"

    # 비교집단(백분위) 설정
    peer_min_size: int = 20                   # 비교집단 최소 표본
    peer_year_window: int = 1                 # 2순위: 우선연도 ±N년

    # 패밀리
    family_id_source: str = "wips"            # "wips" | "epo"
    family_country_source: str = "auto"       # "auto" | "wips" | "epo"
    representative_country_priority: List[str] = field(
        default_factory=lambda: ["US", "EP", "JP", "KR", "CN", "TW", "WO"]
    )
    dedupe_by_family: bool = True

    # 국가 가중치
    global_country_weights: Dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_GLOBAL_COUNTRY_WEIGHTS))
    global_other_weight: float = DEFAULT_GLOBAL_OTHER_WEIGHT
    market_country_weights: Dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_MARKET_COUNTRY_WEIGHTS))

    # 영역 가중치(총점 재배분용. 1.0 = 스펙 기본 배점)
    area_weights: Dict[str, float] = field(
        default_factory=lambda: {"rights": 1.0, "tech": 1.0, "market": 1.0, "impact": 1.0})

    # 시장 상업화 신호에서 데이터 없음 처리
    # False: 결측은 0점 처리하되 missingSignals 로 표기(기본, 점수 부풀림 없음)
    # True : 확보 가능한 신호만으로 만점 환산(coverage 보정)
    rescale_missing_commercial: bool = False

    # LLM
    llm_enabled: bool = True
    llm_id: str = DEFAULT_LLM_ID
    llm_max_workers: int = 4
    llm_max_retries: int = 2
    llm_timeout_sec: int = 120
    llm_text_char_limit: int = 6000
    llm_max_documents: int = 0                # 0 = 제한 없음

    # 기준일(YYYY-MM-DD). 비우면 실행 시각 기준.
    as_of_date: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScoringConfig":
        if not data:
            return cls()
        base = cls()
        known = set(base.to_dict().keys())
        kwargs: Dict[str, Any] = {}
        for key, value in data.items():
            if key not in known or value is None:
                continue
            current = getattr(base, key)
            try:
                if isinstance(current, bool):
                    kwargs[key] = _as_bool(value)
                elif isinstance(current, int) and not isinstance(current, bool):
                    kwargs[key] = int(value)
                elif isinstance(current, float):
                    kwargs[key] = float(value)
                elif isinstance(current, list):
                    kwargs[key] = _as_list(value)
                elif isinstance(current, dict):
                    kwargs[key] = {str(k): float(v) for k, v in dict(value).items()}
                else:
                    kwargs[key] = str(value)
            except (TypeError, ValueError):
                # 잘못된 입력은 기본값 유지 (원인은 호출부에서 검증 메시지로 노출)
                continue
        cfg = cls(**kwargs)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.llm_id not in ALLOWED_LLM_IDS:
            self.llm_id = DEFAULT_LLM_ID
        if self.topic_fit_mode not in ("softened", "linear"):
            self.topic_fit_mode = "softened"
        if self.family_id_source not in ("wips", "epo"):
            self.family_id_source = "wips"
        if self.family_country_source not in ("auto", "wips", "epo"):
            self.family_country_source = "auto"
        self.gate_topic_fit_min = _clamp(self.gate_topic_fit_min, 0.0, 100.0)
        self.peer_min_size = max(2, min(int(self.peer_min_size), 100000))
        self.peer_year_window = max(0, min(int(self.peer_year_window), 10))
        self.llm_max_workers = max(1, min(int(self.llm_max_workers), 16))
        self.llm_max_retries = max(0, min(int(self.llm_max_retries), 5))
        self.llm_timeout_sec = max(10, min(int(self.llm_timeout_sec), 900))
        self.llm_text_char_limit = max(500, min(int(self.llm_text_char_limit), 40000))
        self.llm_max_documents = max(0, int(self.llm_max_documents))
        for key in list(self.area_weights.keys()):
            if key not in AREA_MAX:
                self.area_weights.pop(key)
        for key in AREA_MAX:
            self.area_weights.setdefault(key, 1.0)
            self.area_weights[key] = _clamp(float(self.area_weights[key]), 0.0, 3.0)
        self.global_country_weights = {
            str(k).upper(): _clamp(float(v), 0.0, 5.0)
            for k, v in self.global_country_weights.items() if str(k).strip()}
        self.market_country_weights = {
            str(k).upper(): _clamp(float(v), 0.0, 8.0)
            for k, v in self.market_country_weights.items() if str(k).strip()}
        self.topic_keywords = [str(k).strip() for k in self.topic_keywords if str(k).strip()]

    def copy(self) -> "ScoringConfig":
        return ScoringConfig.from_dict(copy.deepcopy(self.to_dict()))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "y", "yes", "on", "예", "참")


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value)
    for sep in (";", "|", "\n", ","):
        if sep in text:
            return [p.strip() for p in text.split(sep) if p.strip()]
    return [text.strip()] if text.strip() else []


def _clamp(value: float, low: float, high: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, value))
