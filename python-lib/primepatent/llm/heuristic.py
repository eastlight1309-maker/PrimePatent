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
    """규칙 기반 근사치. 실제 LLM 판단을 대체하지 못한다."""
    sections = _sections(prompt)
    title = sections.get("발명의 명칭", "")
    abstract = sections.get("요약", "")
    claim = sections.get("대표청구항", "") or sections.get("독립청구항", "")
    independent = sections.get("독립청구항", "")

    core_terms = _core_terms(prompt)
    numeric_count = len(_NUMERIC_RE.findall(claim))
    material = bool(_MATERIAL_RE.search(claim))
    process_order = bool(_PROCESS_RE.search(claim))
    functional_hits = len(_FUNCTIONAL_RE.findall(claim))
    claim_types = _claim_types(independent or claim)
    independent_count = max(1, len(re.findall(r"제\s*\d+\s*항", independent))) if independent else 0

    # --- 1) 권리범위 넓이 0~3 ---
    if not claim.strip():
        breadth = 0.0
    else:
        breadth = 3.0
        breadth -= min(1.5, numeric_count * 0.5)
        if material:
            breadth -= 0.5
        if process_order:
            breadth -= 0.5
        if functional_hits >= 3:
            breadth += 0.5
        breadth = max(0.0, min(3.0, breadth))

    # --- 2) 핵심기술 중심성 0~5 ---
    hits_in_claim = sum(1 for term in core_terms if term in claim.lower())
    hits_in_abstract = sum(1 for term in core_terms if term in abstract.lower())
    if not claim.strip():
        centrality = 0.0
    elif not core_terms:
        centrality = 2.0
    elif hits_in_claim >= 2:
        centrality = 4.0 if independent_count >= 2 else 3.0
    elif hits_in_claim == 1:
        centrality = 3.0
    elif hits_in_abstract:
        centrality = 1.0
    else:
        centrality = 0.0

    # --- 3) 청구항 확장도 0~5 ---
    total_claims = _int_from(sections.get("청구항 수 / 독립항 수", ""), 0)
    related = hits_in_claim + (1 if hits_in_abstract else 0)
    ratio = (related / total_claims) if total_claims else 0.0
    if not claim.strip() or not core_terms:
        expansion = 0.0
    elif ratio >= 0.45 or related >= 4:
        expansion = 4.0
    elif ratio >= 0.30 or related >= 3:
        expansion = 3.0
    elif ratio >= 0.20 or related >= 2:
        expansion = 2.0
    elif related >= 1:
        expansion = 1.0
    else:
        expansion = 0.5

    # --- 4) 독립청구항 유형 다양성 0~3 ---
    if not claim.strip():
        diversity = 0.0
    elif len(claim_types) >= 3:
        diversity = 3.0
    elif len(claim_types) == 2:
        diversity = 2.5
    elif independent_count >= 2:
        diversity = 2.0
    elif independent_count == 1:
        diversity = 1.5 if total_claims > 1 else 1.0
    else:
        diversity = 1.0

    payload = {
        "claimBreadthScore": round(float(breadth), 1),
        "coreCentralityScore": float(centrality),
        "claimExpansionScore": float(expansion),
        "claimTypeDiversityScore": float(diversity),
        "claimAnalysis": {
            "coreElementsInIndependentClaims": [t for t in core_terms if t in claim.lower()][:6],
            "linkageClaimed": hits_in_claim >= 2,
            "independentClaimsWithCore": min(independent_count, hits_in_claim),
            "relatedClaimCount": related,
            "totalClaimCount": total_claims,
            "relatedClaimRatio": round(ratio, 3),
            "expansionDependentCount": max(0, related - 1),
            "claimTypes": claim_types,
            "independentClaimCount": independent_count,
            "numericLimitationCount": int(numeric_count),
            "designAroundRisk": "low" if breadth >= 2.5 else ("high" if breadth <= 1 else "medium"),
        },
        "keyFeatures": _KEY_TERMS_RE.findall(title)[:5],
        "centralityRationale": "LLM 미사용(휴리스틱): 핵심기술 키워드의 청구항 등장 횟수로 근사했습니다.",
        "expansionRationale": "LLM 미사용(휴리스틱): 키워드 일치 청구항 수와 전체 청구항 수의 비율로 근사했습니다.",
        "diversityRationale": "LLM 미사용(휴리스틱): 독립청구항 문장에서 유형 표현을 탐지해 근사했습니다.",
        "rationale": "LLM 미사용(휴리스틱 추정): 청구항 한정 개수·키워드 일치도로 산출한 근사치입니다. "
                     "실제 평가로 사용하지 마십시오.",
    }
    return json.dumps(payload, ensure_ascii=False)


def _core_terms(prompt: str) -> List[str]:
    """핵심기술 설명 + 키워드에서 판정용 용어를 뽑는다."""
    terms: List[str] = []
    match = re.search(r"## 핵심기술 설명 \(모든 판정의 기준\)\n(.+?)(?=\n##|\n\[)", prompt, re.S)
    if match and "입력되지 않았습니다" not in match.group(1):
        terms += [t.lower() for t in _KEY_TERMS_RE.findall(match.group(1)) if len(t) >= 2]
    keyword_match = re.search(r"- 핵심 키워드: (.+)", prompt)
    if keyword_match:
        terms += [k.strip().lower() for k in keyword_match.group(1).split(",") if k.strip()]
    out, seen = [], set()
    for term in terms:
        if term not in seen:
            seen.add(term)
            out.append(term)
    return out[:20]


_TYPE_PATTERNS = [
    ("장치/패키지", re.compile(r"(패키지|장치|디바이스|소자|기판|apparatus|device|package)", re.I)),
    ("제조방법", re.compile(r"(제조\s*방법|제조방법|manufactur\w*\s*method|fabricat\w*)", re.I)),
    ("시스템/전자장치", re.compile(r"(시스템|전자\s*장치|electronic\s*device|system)", re.I)),
    ("중간제품/부품", re.compile(r"(인터포저|리드프레임|기판\s*구조체|interposer|substrate\s*structure)", re.I)),
    ("공정방법", re.compile(r"(본딩\s*방법|접합\s*방법|공정\s*방법|bonding\s*method|process\s*method)", re.I)),
    ("검사방법", re.compile(r"(검사\s*방법|측정\s*방법|inspection\s*method|test\s*method)", re.I)),
]


def _claim_types(text: str) -> List[str]:
    found = []
    for label, pattern in _TYPE_PATTERNS:
        if pattern.search(text or ""):
            found.append(label)
    return found


def _int_from(text: str, default: int = 0) -> int:
    match = re.search(r"\d+", text or "")
    return int(match.group(0)) if match else default
