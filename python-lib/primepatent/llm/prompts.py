# -*- coding: utf-8 -*-
"""LLM 프롬프트 (스펙 4.2 / 5.1~5.4 평가 루브릭)."""

from __future__ import annotations

from typing import Any, Dict, List

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = (
    "당신은 반도체·전자 분야 특허를 평가하는 20년 경력의 한국 변리사이자 기술분석 전문가입니다. "
    "주어진 특허 서지·청구항·요약만을 근거로 평가하며, 문서에 없는 사실을 지어내지 않습니다. "
    "반드시 지정된 JSON 스키마 하나만 출력하고, 그 외 설명·마크다운·코드펜스는 출력하지 않습니다."
)

RUBRIC = """
[평가 루브릭]

1) topicFitPercent (0~100) - Primary Topic 적합도
   - 청구항이 주제 기술을 직접 구현/한정하면 85~100
   - 주제와 밀접하나 일부만 관련되면 70~84
   - 인접 기술이거나 주제는 배경으로만 언급되면 40~69
   - 주제와 실질적 관련이 없으면 0~39

2) claimBreadthScore (0~4) - 대표/독립청구항의 권리범위 넓이
   4: 필수 구성이 적고 넓은 상위개념으로 기재
   3: 핵심기술을 충분히 포괄하나 일부 한정 존재
   2: 수치범위/재료/공정조건 등 다수 한정
   1: 실시예 수준의 좁은 권리 또는 회피 용이
   0: 실질적인 보호범위 부족(청구항 정보 없음 포함)

3) coreContributionScore (0~8) - 핵심 기술기여도
   7~8: 기존 구조의 근본적 변경 또는 새로운 아키텍처
   5~6: 핵심 공정·구조·재료의 유의미한 개선
   3~4: 특정 요소 또는 조건의 최적화
   1~2: 주변부 개선 또는 일반적 적용
   0: 주제와 실질적 관련 없음

4) problemImportanceScore (0~3) - 해결과제의 중요성
   3: 성능·수율·신뢰성을 제한하는 핵심 병목
   2: 주요 공정 또는 구조 문제
   1: 형상·제조 편의성 등 국부 개선
   0: 명확한 과제 없음

5) effectEvidenceScore (0~3) - 효과의 검증성
   3: 정량 데이터와 비교예로 효과 입증
   2: 실시예 또는 복수 근거로 효과 설명
   1: 정성적 효과만 기재
   0: 효과 불명확

6) generalityScore (0~4) - 기술 범용성
   4: 복수 제품·공정·패키지에 적용 가능
   3: 동일 플랫폼 내 다수 제품에 적용 가능
   2: 특정 패키지 또는 공정에 제한
   1: 특정 실시형태·특정 재료에 강하게 제한
   0: 적용 범위 불명확

claimAnalysis 는 청구범위 판단 근거로서 다음을 채웁니다.
   essentialElementCount: 독립항 1개의 필수 구성요소 수(정수)
   numericLimitationCount: 수치범위 한정 개수(정수)
   materialLimitation: 특정 재료명 한정 여부(true/false)
   processOrderLimitation: 특정 공정순서 한정 여부(true/false)
   functionalLanguage: 기능적 표현 사용 정도("high"/"medium"/"low")
   multiCategoryIndependentClaims: 장치·방법·시스템 등 복수 카테고리 독립항 존재 여부(true/false)
   designAroundRisk: 경쟁사가 대체수단으로 회피할 가능성("high"/"medium"/"low")
"""

OUTPUT_SCHEMA = """
{
  "topicFitPercent": 0,
  "claimBreadthScore": 0,
  "coreContributionScore": 0,
  "problemImportanceScore": 0,
  "effectEvidenceScore": 0,
  "generalityScore": 0,
  "claimAnalysis": {
    "essentialElementCount": 0,
    "numericLimitationCount": 0,
    "materialLimitation": false,
    "processOrderLimitation": false,
    "functionalLanguage": "medium",
    "multiCategoryIndependentClaims": false,
    "designAroundRisk": "medium"
  },
  "keyFeatures": ["핵심 특징 1", "핵심 특징 2"],
  "rationale": "평가 근거를 2~3문장의 한국어로"
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
                      topic_keywords: List[str], char_limit: int = 6000) -> str:
    """특허 1건에 대한 사용자 프롬프트."""
    claim_limit = max(800, int(char_limit * 0.45))
    text_limit = max(400, int(char_limit * 0.2))

    parts = [
        "다음 특허를 아래 루브릭에 따라 평가하십시오.\n",
        "## 평가 주제 (Primary Topic)",
        "- 주제명: %s" % (topic_name or "(미지정)"),
    ]
    if topic_description:
        parts.append("- 주제 설명: %s" % topic_description[:1000])
    if topic_keywords:
        parts.append("- 핵심 키워드: %s" % ", ".join(topic_keywords[:30]))

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
        "주의: 청구항 텍스트가 비어 있으면 claimBreadthScore 는 0, "
        "관련 판단은 요약 기반의 보수적인 값으로 부여하고 rationale 에 그 사실을 명시하십시오."
    )
    return "\n".join(part for part in parts if part)
