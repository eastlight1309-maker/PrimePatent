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
# 세부지표 배점
# =========================
# 영역 합계(AREA_MAX)와 총점(TOTAL_MAX)은 아래 표에서 자동 계산된다.
# 지표를 추가/삭제해도 합계가 어긋나지 않게 하기 위함이다.
COMPONENT_MAX = {
    # 권리 중요도 27
    "rights.survival": 10.0,           # 권리 생존성
    "rights.claimScope": 5.0,          # 청구범위 강도 (정량 2 + LLM 3)
    "rights.remainingTerm": 5.0,       # 잔존기간
    "rights.defenseSignal": 7.0,       # 권리유지·방어 신호
    # 기술 중요도 21
    "tech.topicFit": 8.0,              # Primary Topic 적합도 (IPURE AI Score)
    "tech.coreCentrality": 5.0,        # 독립청구항 내 핵심기술 중심성
    "tech.claimExpansion": 5.0,        # 핵심기술의 청구항 확장도
    "tech.claimTypeDiversity": 3.0,    # 독립청구항 유형 다양성
    # 시장 중요도 27
    "market.entry": 15.0,              # 주요 시장 진입도 (소비 10 + 공급망 5)
    "market.applicantPower": 4.0,      # 출원인 시장 영향력
    "market.commercial": 6.0,          # 상업화·거래 신호
    "market.familySize": 2.0,          # 패밀리 건수
    # 영향력·경쟁성 25
    "impact.competitorCoverage": 7.0,  # 경쟁사 커버리지 (외부TR 최대값 대비 비율)
    "impact.citation": 13.0,           # 연령보정 피인용 영향력 (TR 최대값 대비 비율)
    "impact.leadership": 5.0,          # 기술 선도성
}

AREA_ORDER = ["rights", "tech", "market", "impact"]
AREA_LABEL = {
    "rights": "권리 중요도",
    "tech": "기술 중요도",
    "market": "시장 중요도",
    "impact": "영향력·경쟁성",
}
AREA_MAX = {
    area: round(sum(score for key, score in COMPONENT_MAX.items()
                    if key.split(".")[0] == area), 6)
    for area in AREA_ORDER
}
TOTAL_MAX = round(sum(AREA_MAX.values()), 6)


# 세부지표별 산출 방식(정량/LLM)
COMPONENT_SOURCE = {
    "rights.survival": "quant",
    "rights.claimScope": "mixed",           # 정량 2 / LLM 3
    "rights.remainingTerm": "quant",
    "rights.defenseSignal": "quant",
    "tech.topicFit": "quant",               # IPURE AI Score 컬럼값 사용
    "tech.coreCentrality": "llm",
    "tech.claimExpansion": "llm",
    "tech.claimTypeDiversity": "llm",
    "market.entry": "quant",
    "market.applicantPower": "quant",
    "market.commercial": "quant",
    "market.familySize": "quant",
    "impact.competitorCoverage": "quant",
    "impact.citation": "quant",
    "impact.leadership": "quant",
}


# mixed(정량+LLM) 세부지표의 배점 분해 (정량 상한, LLM 상한)
COMPONENT_MIXED_SPLIT = {
    "rights.claimScope": (2.0, 3.0),     # 정량: 청구항/독립항 백분위, LLM: 권리범위 넓이
}


def mixed_max(component_key):
    """세부지표의 (정량 상한, LLM 상한)."""
    maximum = COMPONENT_MAX[component_key]
    source = COMPONENT_SOURCE.get(component_key, "quant")
    if source == "quant":
        return maximum, 0.0
    if source == "llm":
        return 0.0, maximum
    return COMPONENT_MIXED_SPLIT.get(component_key, (maximum / 2.0, maximum / 2.0))


# 주요 시장 진입도 (소비·권리시장 10점 + 제조·공급망시장 5점 = 15점)
# 패밀리에 해당 국가 출원이 "존재하는가" 만 보고 가중치를 합산한다.
DEFAULT_MARKET_CONSUMER_WEIGHTS = {"US": 4.2, "CN": 2.2, "EP": 2.1, "JP": 1.1, "KR": 0.4}
DEFAULT_MARKET_SUPPLY_WEIGHTS = {"CN": 1.5, "JP": 1.5, "KR": 0.8, "TW": 0.8, "US": 0.4}
MARKET_CONSUMER_MAX = 10.0
MARKET_SUPPLY_MAX = 5.0

# 패밀리 건수 구간점수 (하한, 점수)
FAMILY_SIZE_BANDS = [(8.0, 2.0), (6.0, 1.5), (4.0, 1.0), (3.0, 0.5), (0.0, 0.0)]

# 4.1 권리 생존성 구간점수
SURVIVAL_SCORES = {
    "granted_alive": 10.0,        # 등록·존속
    "granted_expiring": 8.0,      # 등록·존속기간 만료 임박(잔존 2년 이하)
    "under_examination": 6.0,     # 공개·심사 중
    "filed": 4.0,                 # 출원 중·심사 미청구
    "lapsed": 2.0,                # 등록 후 소멸·포기
    "rejected": 0.0,              # 거절 확정·취하·포기
    "invalidated": 0.0,
    "unknown": 2.0,
}

# 4.4 잔존기간 구간점수 (년 단위 하한, 점수)
REMAINING_TERM_BANDS = [(12.0, 5.0), (8.0, 4.0), (4.0, 3.0), (0.0, 1.0)]
PATENT_TERM_YEARS = 20.0


@dataclass
class ScoringConfig:
    """분석 실행 1건에 대한 설정 스냅샷."""

    # 주제 정의
    topic_name: str = "Primary Topic"
    topic_description: str = ""
    topic_keywords: List[str] = field(default_factory=list)
    # 핵심기술 설명 - 청구범위 강도/중심성/확장도/유형 다양성 판정의 기준이 된다.
    core_technology: str = ""

    # IPURE AI Score 만점(백분율 환산 기준). 0~1 스케일이면 1 로 지정.
    ipure_score_max: float = 100.0

    # Gate
    gate_topic_fit_min: float = 70.0          # Gate 1: Primary Topic 적합도(%)
    apply_gate: bool = True                   # False 면 gate 결과를 표시만 하고 제외하지 않음

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

    # 국가 가중치 (주요 시장 진입도)
    market_consumer_weights: Dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_MARKET_CONSUMER_WEIGHTS))
    market_supply_weights: Dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_MARKET_SUPPLY_WEIGHTS))

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
        self.market_consumer_weights = {
            str(k).upper(): _clamp(float(v), 0.0, 15.0)
            for k, v in self.market_consumer_weights.items() if str(k).strip()}
        self.market_supply_weights = {
            str(k).upper(): _clamp(float(v), 0.0, 15.0)
            for k, v in self.market_supply_weights.items() if str(k).strip()}
        self.ipure_score_max = max(0.0001, float(self.ipure_score_max or 100.0))
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
