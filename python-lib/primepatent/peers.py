# -*- coding: utf-8 -*-
"""비교집단(Primary Topic × 최초 우선연도) 구성과 백분위 계산.

스펙 3.2 / 3.3
 - 비교집단 1순위: Topic + 우선연도
 - 2순위: Topic + 우선연도 ±N년
 - 3순위: Topic 전체
 - 오른쪽 꼬리분포 지표는 LN(1+x) 변환 후 PERCENTRANK
"""

from __future__ import annotations

import bisect
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """선형보간 분위수(엑셀 PERCENTILE.INC 와 동일한 정의)."""
    n = len(sorted_values)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_values[0])
    position = (n - 1) * q
    lower = int(math.floor(position))
    upper = min(lower + 1, n - 1)
    weight = position - lower
    return float(sorted_values[lower]) * (1 - weight) + float(sorted_values[upper]) * weight


def _round(value: float) -> float:
    number = round(float(value), 3)
    return int(number) if number == int(number) else number


def percent_rank_inc(sorted_values: Sequence[float], value: float) -> float:
    """엑셀 PERCENTRANK.INC 동등 구현 = (자신보다 작은 값의 수) / (n-1).

    표본이 1개 이하이면 비교 불가로 보고 중립값 0.5 를 반환한다.
    """
    n = len(sorted_values)
    if n <= 1:
        return 0.5
    below = bisect.bisect_left(sorted_values, value)
    return max(0.0, min(1.0, below / float(n - 1)))


class PeerIndex:
    """지표 하나에 대한 비교집단별 정렬값 색인."""

    def __init__(self, min_size: int = 20, year_window: int = 1):
        self.min_size = max(2, int(min_size))
        self.year_window = max(0, int(year_window))
        self._by_topic_year: Dict[Tuple[str, Optional[int]], List[float]] = {}
        self._by_topic: Dict[str, List[float]] = {}
        self._all: List[float] = []
        self._sorted = False

    def add(self, topic: str, year: Optional[int], value: Optional[float]) -> None:
        if value is None:
            return
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        if math.isnan(number):
            return
        self._by_topic_year.setdefault((topic, year), []).append(number)
        self._by_topic.setdefault(topic, []).append(number)
        self._all.append(number)
        self._sorted = False

    def finalize(self) -> None:
        if self._sorted:
            return
        for values in self._by_topic_year.values():
            values.sort()
        for values in self._by_topic.values():
            values.sort()
        self._all.sort()
        self._sorted = True

    def _window_values(self, topic: str, year: Optional[int]) -> List[float]:
        if year is None:
            return []
        merged: List[float] = []
        for offset in range(-self.year_window, self.year_window + 1):
            merged.extend(self._by_topic_year.get((topic, year + offset), []))
        merged.sort()
        return merged

    def select(self, topic: str, year: Optional[int]) -> Tuple[List[float], str]:
        """백분위 계산에 사용할 비교집단 값과 라벨을 고른다(4단계 폴백)."""
        self.finalize()
        exact = self._by_topic_year.get((topic, year), [])
        if len(exact) >= self.min_size:
            return exact, "topic+year"

        window = self._window_values(topic, year)
        if len(window) >= self.min_size:
            return window, "topic+year±%d" % self.year_window

        topic_values = self._by_topic.get(topic, [])
        if len(topic_values) >= self.min_size:
            return topic_values, "topic"

        if len(self._all) >= 2:
            return self._all, "all"

        return self._all, "insufficient"

    def rank(self, topic: str, year: Optional[int], value: Optional[float]) -> Tuple[float, str, int]:
        """(백분위, 사용된 비교집단, 표본수). 값이 없으면 (0.0, 'none', 0)."""
        self.finalize()
        if value is None:
            return 0.0, "none", 0
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0, "none", 0
        if math.isnan(number):
            return 0.0, "none", 0

        values, label = self.select(topic, year)
        if label == "insufficient":
            # 표본이 절대적으로 부족 → 중립값
            return 0.5, "insufficient", len(values)
        return percent_rank_inc(values, number), label, len(values)

    def stats(self, topic: str, year: Optional[int]) -> Optional[Dict[str, Any]]:
        """비교집단의 분포 요약.

        백분위만 보면 '이 값이 집단에서 실제로 어느 수준인지' 알 수 없으므로
        최소·사분위·중앙·최대를 함께 제공한다.
        """
        values, label = self.select(topic, year)
        if not values:
            return None
        return {
            "peerGroup": label,
            "n": len(values),
            "min": _round(values[0]),
            "p25": _round(_quantile(values, 0.25)),
            "median": _round(_quantile(values, 0.5)),
            "p75": _round(_quantile(values, 0.75)),
            "max": _round(values[-1]),
            "mean": _round(sum(values) / len(values)),
        }


class PeerSet:
    """여러 지표(metric)에 대한 PeerIndex 묶음."""

    def __init__(self, min_size: int = 20, year_window: int = 1):
        self.min_size = min_size
        self.year_window = year_window
        self.indexes: Dict[str, PeerIndex] = {}

    def index(self, metric: str) -> PeerIndex:
        if metric not in self.indexes:
            self.indexes[metric] = PeerIndex(self.min_size, self.year_window)
        return self.indexes[metric]

    def add(self, metric: str, topic: str, year: Optional[int], value: Optional[float]) -> None:
        self.index(metric).add(topic, year, value)

    def rank(self, metric: str, topic: str, year: Optional[int],
             value: Optional[float]) -> Tuple[float, str, int]:
        return self.index(metric).rank(topic, year, value)

    def stats(self, metric: str, topic: str, year: Optional[int]) -> Optional[Dict[str, Any]]:
        return self.index(metric).stats(topic, year)

    def build(self, records: Sequence[Dict], metrics: Dict[str, Callable[[Dict], Optional[float]]],
              topic_of: Callable[[Dict], str], year_of: Callable[[Dict], Optional[int]]) -> "PeerSet":
        for record in records:
            topic = topic_of(record)
            year = year_of(record)
            for metric, getter in metrics.items():
                self.add(metric, topic, year, getter(record))
        for index in self.indexes.values():
            index.finalize()
        return self


class GlobalIndex:
    """비교집단 구분 없이 전체 모집단에서 백분위를 구하는 색인(출원인 규모 등)."""

    def __init__(self):
        self._values: List[float] = []
        self._sorted = False

    def add(self, value: Optional[float]) -> None:
        if value is None:
            return
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        if not math.isnan(number):
            self._values.append(number)
            self._sorted = False

    def finalize(self) -> None:
        if not self._sorted:
            self._values.sort()
            self._sorted = True

    def rank(self, value: Optional[float]) -> float:
        self.finalize()
        if value is None or not self._values:
            return 0.0
        return percent_rank_inc(self._values, float(value))

    @property
    def size(self) -> int:
        return len(self._values)
