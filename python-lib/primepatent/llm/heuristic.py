# -*- coding: utf-8 -*-
"""LLM 폴백용 규칙 기반 추정기.

주의: 실제 LLM 판단을 대체하지 못한다. 오프라인 개발/테스트와
LLM 장애 시 파이프라인이 멈추지 않도록 하기 위한 보수적 근사치이며,
결과에는 항상 provider="heuristic" 이 표시된다.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List

_SECTION_RE = re.compile(r"^### (.+?)\n(.*?)(?=\n### |\n\[|\Z)", re.S | re.M)
_NUMERIC_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|㎛|um|µm|nm|mm|℃|도|kg|g|Pa|MPa|GPa|W|V|A|Hz|배|이상|이하|미만|초과)")
_MATERIAL_RE = re.compile(
    r"(구리|copper|Cu\b|은|silver|Ag\b|금|gold|Au\b|주석|tin|Sn\b|니켈|nickel|Ni\b|"
    r"실리콘|silicon|Si\b|에폭시|epoxy|폴리이미드|polyimide|몰딩|molding|솔더|solder)", re.I)
_PROCESS_RE = re.compile(r"(단계|공정|순차|이후에|다음에|step|process|sequential)", re.I)
_FUNCTIONAL_RE = re.compile(r"(수단|부재|유닛|모듈|구성되는|하도록|configured to|means for|unit)", re.I)
_CATEGORY_RE = [
    re.compile(r"(장치|디바이스|apparatus|device|패키지|package)", re.I),
    re.compile(r"(방법|method|제조방법|프로세스)", re.I),
    re.compile(r"(시스템|system|모듈|module|반도체 소자)", re.I),
]
_KEY_TERMS_RE = re.compile(r"[A-Za-z가-힣]{2,}")


def _sections(prompt: str) -> Dict[str, str]:
    return {m.group(1).strip(): m.group(2).strip() for m in _SECTION_RE.finditer(prompt)}


def _keywords(prompt: str) -> List[str]:
    match = re.search(r"- 핵심 키워드: (.+)", prompt)
    if not match:
        return []
    return [k.strip().lower() for k in match.group(1).split(",") if k.strip()]


def estimate_from_prompt(prompt: str) -> str:
    sections = _sections(prompt)
    title = sections.get("발명의 명칭", "")
    abstract = sections.get("요약", "")
    claim = sections.get("대표청구항", "") or sections.get("독립청구항", "")
    independent = sections.get("독립청구항", "")
    problem = sections.get("해결과제 요약", "")
    effect = sections.get("효과 요약", "")
    corpus = " ".join([title, abstract, claim, independent, problem, effect])
    corpus_lower = corpus.lower()

    keywords = _keywords(prompt)
    if keywords:
        hits = sum(1 for k in keywords if k and k in corpus_lower)
        fit = 45 + min(50, int(hits / max(1, len(keywords)) * 100 * 0.55))
    else:
        fit = 70 if corpus.strip() else 0

    numeric_count = len(_NUMERIC_RE.findall(claim))
    material = bool(_MATERIAL_RE.search(claim))
    process_order = bool(_PROCESS_RE.search(claim))
    functional_hits = len(_FUNCTIONAL_RE.findall(claim))
    elements = max(1, len(re.split(r"[;\n]|(?<=[가-힣])\s*와\s*|,\s*(?=[가-힣])", claim))) if claim else 0
    categories = sum(1 for pattern in _CATEGORY_RE if pattern.search(independent or claim))

    if not claim.strip():
        breadth = 0
    else:
        breadth = 4
        breadth -= min(2, numeric_count // 2)
        if material:
            breadth -= 0.5
        if process_order:
            breadth -= 0.5
        if elements > 8:
            breadth -= 1
        if functional_hits >= 3:
            breadth += 0.5
        breadth = max(0, min(4, breadth))

    length_signal = min(1.0, len(corpus) / 3000.0)
    contribution = round(min(8.0, 2.0 + length_signal * 3.0 + (breadth / 4.0) * 3.0), 1)
    problem_score = 2 if problem else (1 if abstract else 0)
    effect_score = 2 if (_NUMERIC_RE.search(effect or abstract or "")) else (1 if effect or abstract else 0)
    generality = max(0, min(4, round(breadth * 0.75 + (1 if categories >= 2 else 0), 1)))

    payload = {
        "topicFitPercent": int(max(0, min(100, fit))),
        "claimBreadthScore": round(float(breadth), 1),
        "coreContributionScore": float(contribution),
        "problemImportanceScore": int(problem_score),
        "effectEvidenceScore": int(effect_score),
        "generalityScore": float(generality),
        "claimAnalysis": {
            "essentialElementCount": int(elements),
            "numericLimitationCount": int(numeric_count),
            "materialLimitation": bool(material),
            "processOrderLimitation": bool(process_order),
            "functionalLanguage": "high" if functional_hits >= 3 else ("low" if functional_hits == 0 else "medium"),
            "multiCategoryIndependentClaims": categories >= 2,
            "designAroundRisk": "low" if breadth >= 3.5 else ("high" if breadth <= 1.5 else "medium"),
        },
        "keyFeatures": _KEY_TERMS_RE.findall(title)[:5],
        "rationale": "LLM 미사용(휴리스틱 추정): 청구항 한정 개수·텍스트 길이·키워드 일치도로 산출한 근사치입니다.",
    }
    return json.dumps(payload, ensure_ascii=False)
