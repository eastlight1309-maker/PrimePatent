# -*- coding: utf-8 -*-
"""스코어링 공통 자료구조."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config import COMPONENT_MAX, COMPONENT_SOURCE


@dataclass
class Component:
    """세부지표 1개의 채점 결과."""

    key: str
    label: str
    score: float
    max: float
    source: str = "quant"                  # quant | llm | mixed
    quant_score: Optional[float] = None    # mixed 인 경우 정량 부분
    llm_score: Optional[float] = None      # mixed 인 경우 LLM 부분
    detail: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key, "label": self.label,
            "score": round(float(self.score), 3), "max": float(self.max),
            "source": self.source,
            "quantScore": None if self.quant_score is None else round(float(self.quant_score), 3),
            "llmScore": None if self.llm_score is None else round(float(self.llm_score), 3),
            "detail": self.detail, "notes": self.notes,
        }


@dataclass
class AreaResult:
    """평가영역(권리/기술/시장/영향력) 결과."""

    key: str
    label: str
    components: List[Component]

    @property
    def score(self) -> float:
        return sum(c.score for c in self.components)

    @property
    def max(self) -> float:
        return sum(c.max for c in self.components)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key, "label": self.label,
            "score": round(self.score, 3), "max": round(self.max, 3),
            "components": [c.to_dict() for c in self.components],
        }


def make_component(key: str, label: str, score: float, detail: Optional[Dict] = None,
                   notes: Optional[List[str]] = None, quant_score: Optional[float] = None,
                   llm_score: Optional[float] = None) -> Component:
    """COMPONENT_MAX 에 정의된 배점으로 상한을 강제한다."""
    maximum = COMPONENT_MAX[key]
    bounded = max(0.0, min(float(maximum), float(score or 0.0)))
    return Component(
        key=key, label=label, score=bounded, max=maximum,
        source=COMPONENT_SOURCE.get(key, "quant"),
        quant_score=quant_score, llm_score=llm_score,
        detail=detail or {}, notes=notes or [],
    )


def band_score(value: Optional[float], bands: List, default: float = 0.0) -> float:
    """[(하한, 점수), ...] 구간표에서 점수를 찾는다(내림차순 하한 가정)."""
    if value is None:
        return default
    for threshold, score in bands:
        if value >= threshold:
            return float(score)
    return default
