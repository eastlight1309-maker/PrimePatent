# -*- coding: utf-8 -*-
"""LLM 프롬프트 (스펙 4.2 / 5.1~5.4 평가 루브릭)."""

from __future__ import annotations

from typing import Any, Dict, List

PROMPT_VERSION = "v2"

SYSTEM_PROMPT = (
    "당신은 반도체·전자 분야 특허의 청구범위를 분석하는 20년 경력의 한국 변리사입니다. "
    "주어진 특허의 청구항과 요약만을 근거로 판정하며, 문서에 없는 사실을 지어내지 않습니다. "
    "발명이 '혁신적인지' 를 평가하지 않습니다. 오직 사용자가 제시한 핵심기술이 "
    "청구항에 어떻게 반영되어 있는지만 판정합니다. "
    "반드시 지정된 JSON 스키마 하나만 출력하고, 그 외 설명·마크다운·코드펜스는 출력하지 않습니다."
)

RUBRIC = """
[평가 루브릭] - 모든 판정의 기준은 위에 제시된 '핵심기술 설명' 이다.

1) claimBreadthScore (0~3) - 대표/독립청구항의 권리범위 넓이
   3   : 핵심 구성이 적고 넓은 상위개념으로 기재
   2.5 : 핵심기술을 충분히 포괄하나 일부 한정 존재
   2   : 수치·재료·공정조건 등 다수 한정
   1   : 실시예 수준의 좁은 권리 또는 회피 용이
   0   : 실질적인 보호범위 부족(청구항 정보 없음 포함)

2) coreCentralityScore (0~5) - 독립청구항 내 핵심기술 중심성
   핵심 구성요소가 독립청구항의 '필수 구성' 으로 청구되고 있는지, 그리고
   핵심 구성요소 사이의 '연결관계' 가 청구되어 있는지만 판정한다.
   5 : 핵심 구성요소와 연결관계가 대표청구항 및 2개 이상의 독립청구항에 반복적으로 포함
   4 : 핵심 구성요소와 연결관계가 대표청구항 또는 주요 독립청구항에 필수 구성으로 포함
   3 : 핵심 구성요소는 독립청구항에 있으나 연결관계·해결수단이 부분적으로만 한정됨
   2 : 핵심 구성요소가 종속항 중심이며 독립항에서는 상위개념으로만 표현됨
   1 : 요약에는 관련 기술이 있으나 청구항에서 필수 구성인지 불명확
   0 : 핵심 구성요소가 청구항에 없거나 적용 가능한 대상 중 하나로만 언급됨

3) claimExpansionScore (0~5) - 핵심기술의 청구항 확장도
   먼저 두 값을 센다.
     - 관련 청구항 비율 = 핵심기술 관련 청구항 수 / 전체 청구항 수
     - 확장 종속항 수  = 핵심 구성의 구조·공정·소재·파라미터를 추가 한정하는 종속항 수
   전체 청구항이 적은 특허가 불리하지 않도록 **비율 기준과 개수 기준 중 높은 점수**를 준다.
   5   : 관련 비율 60% 이상 **이고** 확장 종속항 5개 이상
   4   : 관련 비율 45% 이상 **또는** 확장 종속항 4개 이상
   3   : 관련 비율 30% 이상 **또는** 확장 종속항 3개 이상
   2   : 관련 비율 20% 이상 **또는** 확장 종속항 2개 이상
   1   : 핵심기술이 독립항과 1개의 종속항에만 존재
   0.5 : 핵심기술이 일부 청구항에 제한적으로 존재
   0   : 청구항에서 핵심기술을 확인할 수 없음

4) claimTypeDiversityScore (0~3) - 독립청구항 유형 다양성
   하나의 기술개념을 여러 관점에서 보호하는지 본다.
   유형 예시: 장치/패키지, 제조방법, 시스템/전자장치, 중간제품/핵심부품, 공정방법, 검사방법
   3   : 3개 이상의 서로 다른 청구항 유형에서 동일 핵심기술을 보호
   2.5 : 장치·패키지 및 제조방법의 2개 유형에서 보호
   2   : 동일 유형의 복수 독립청구항에서 서로 다른 구현을 보호
   1.5 : 1개의 독립청구항 유형과 다수 종속항으로 보호
   1   : 단일 독립청구항에만 제한
   0   : 관련 독립청구항을 확인할 수 없음

claimAnalysis 에는 위 판정의 근거가 된 실제 관찰값을 채운다.
   coreElementsInIndependentClaims: 독립항에 나타난 핵심 구성요소 목록(문자열 배열)
   linkageClaimed: 구성요소 사이 연결관계가 청구되어 있는지(true/false)
   independentClaimsWithCore: 핵심기술을 포함한 독립항 수(정수)
   relatedClaimCount: 핵심기술 관련 청구항 수(정수)
   totalClaimCount: 전체 청구항 수(정수)
   relatedClaimRatio: 관련 청구항 비율(0~1 소수)
   expansionDependentCount: 핵심기술 확장 종속항 수(정수)
   claimTypes: 확인된 독립청구항 유형 목록(예: ["장치","제조방법"])
   independentClaimCount: 독립항 수(정수)
   numericLimitationCount: 수치범위 한정 개수(정수)
   designAroundRisk: 경쟁사 회피 가능성("high"/"medium"/"low")
"""

OUTPUT_SCHEMA = """
{
  "claimBreadthScore": 0,
  "coreCentralityScore": 0,
  "claimExpansionScore": 0,
  "claimTypeDiversityScore": 0,
  "claimAnalysis": {
    "coreElementsInIndependentClaims": ["구성요소1", "구성요소2"],
    "linkageClaimed": false,
    "independentClaimsWithCore": 0,
    "relatedClaimCount": 0,
    "totalClaimCount": 0,
    "relatedClaimRatio": 0,
    "expansionDependentCount": 0,
    "claimTypes": ["장치"],
    "independentClaimCount": 0,
    "numericLimitationCount": 0,
    "designAroundRisk": "medium"
  },
  "centralityRationale": "중심성 판정 근거 1~2문장(한국어)",
  "expansionRationale": "확장도 판정 근거 1~2문장(한국어)",
  "diversityRationale": "유형 다양성 판정 근거 1~2문장(한국어)",
  "keyFeatures": ["핵심 특징 1", "핵심 특징 2"],
  "rationale": "종합 판단 근거를 2~3문장의 한국어로"
}
"""


def _section(title: str, body: Any, limit: int) -> str:
    text = "" if body is None else str(body).strip()
    if not text:
        return ""
    if len(text) > limit:
        text = text[:limit] + " …(이하 생략)"
    return "### %s\n%s\n" % (title, text)


def build_user_prompt(document: Dict[str, Any], topic_name: str, topic_description: str,
                      topic_keywords: List[str], char_limit: int = 6000,
                      core_technology: str = "") -> str:
    """특허 1건에 대한 사용자 프롬프트."""
    claim_limit = max(800, int(char_limit * 0.45))
    text_limit = max(400, int(char_limit * 0.2))

    parts = [
        "다음 특허의 청구항을 아래 루브릭에 따라 판정하십시오.\n",
        "## 평가 주제 (Primary Topic)",
        "- 주제명: %s" % (topic_name or "(미지정)"),
    ]
    if topic_description:
        parts.append("- 주제 설명: %s" % topic_description[:1000])
    if topic_keywords:
        parts.append("- 핵심 키워드: %s" % ", ".join(topic_keywords[:30]))

    parts.append("\n## 핵심기술 설명 (모든 판정의 기준)")
    if core_technology:
        parts.append(core_technology[:2000])
    else:
        parts.append("(핵심기술 설명이 입력되지 않았습니다. 위 주제명·키워드를 핵심기술로 간주하되, "
                     "판정 근거에 그 사실을 명시하십시오.)")

    parts.append("\n## 특허 정보")
    parts.append(_section("문헌번호/국가", "%s / %s" % (document.get("docNumber", ""),
                                                   document.get("country", "")), 200))
    parts.append(_section("발명의 명칭", document.get("title"), 500))
    parts.append(_section("요약", document.get("abstract"), text_limit))
    parts.append(_section("해결과제 요약", document.get("problemSummary"), text_limit))
    parts.append(_section("해결수단 요약", document.get("solutionSummary"), text_limit))
    parts.append(_section("효과 요약", document.get("effectSummary"), text_limit))
    parts.append(_section("대표청구항", document.get("mainClaim"), claim_limit))
    parts.append(_section("독립청구항", document.get("independentClaims"), claim_limit))
    parts.append(_section("청구항 수 / 독립항 수",
                          "%s / %s" % (document.get("claimCount", "-"),
                                       document.get("independentClaimCount", "-")), 100))
    parts.append(_section("CPC", ", ".join(document.get("cpc") or [])[:400], 400))

    parts.append(RUBRIC)
    parts.append("\n[출력 형식] 아래 JSON 스키마와 동일한 키 구조로 값만 채워 JSON 하나만 출력하십시오.")
    parts.append(OUTPUT_SCHEMA)
    parts.append(
        "주의: 청구항 텍스트가 비어 있으면 claimBreadthScore·coreCentralityScore·"
        "claimExpansionScore·claimTypeDiversityScore 를 모두 0 으로 두고 "
        "rationale 에 그 사실을 명시하십시오. 추측으로 점수를 부여하지 마십시오."
    )
    return "\n".join(part for part in parts if part)
