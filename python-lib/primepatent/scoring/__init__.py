# -*- coding: utf-8 -*-
"""핵심특허 스코어링 (권리30 + 기술30 + 시장20 + 영향력20 = 100)."""

from .common import Component, AreaResult  # noqa: F401
from .context import AnalysisContext  # noqa: F401
from .engine import score_records, score_one  # noqa: F401
