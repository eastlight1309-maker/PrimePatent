# -*- coding: utf-8 -*-
"""앱 설명(도움말) 화면에 사용할 스코어링 안내 데이터.

배점·가중치·산출방식은 **실제 스코어링 코드가 쓰는 상수에서 그대로 가져온다.**
(문서를 따로 관리하면 코드와 어긋나므로, 여기서는 설명 문구만 보관한다)
"""

from __future__ import annotations

from typing import Any, Dict, List

from .columns import FIELDS
from .config import (COMPONENT_MAX, COMPONENT_SOURCE, DEFAULT_GLOBAL_COUNTRY_WEIGHTS,
                     DEFAULT_GLOBAL_OTHER_WEIGHT, DEFAULT_MARKET_COUNTRY_WEIGHTS,
                     REMAINING_TERM_BANDS, SURVIVAL_SCORES, ScoringConfig, mixed_max)
from .scoring.engine import GRADE_BANDS
from .status import STATUS_LABEL

SOURCE_LABEL = {"quant": "정량", "llm": "LLM", "mixed": "정량+LLM"}

AREA_INFO = [
    ("rights", "권리 중요도", "권리의 범위, 존속 가능성, 국가 확장성을 본다."),
    ("tech", "기술 중요도", "주제 적합성, 기술 핵심성, 해결과제·효과를 본다."),
    ("market", "시장 중요도", "주요 시장 진입, 경쟁사 관심, 상업화 가능성을 본다."),
    ("impact", "영향력·경쟁성", "후속 특허에 미친 영향과 경쟁 강도를 본다."),
]

# 세부지표별 설명 (배점은 COMPONENT_MAX 에서 자동으로 채워진다)
COMPONENT_INFO: Dict[str, Dict[str, Any]] = {
    "rights.survival": {
        "label": "권리 생존성",
        "how": "법적상태를 6단계로 분류해 구간점수를 준다. 상태 문자열이 없으면 등록번호·등록일·"
               "공개일 등 서지정보로 추정한다.",
        "formula": "상태 분류 → 구간점수",
        "table": [(STATUS_LABEL["granted_alive"], "8"),
                  (STATUS_LABEL["granted_expiring"] + " (잔존 2년 이하)", "6"),
                  (STATUS_LABEL["under_examination"], "5"),
                  (STATUS_LABEL["filed"], "3"),
                  (STATUS_LABEL["lapsed"], "2"),
                  (STATUS_LABEL["unknown"], "2"),
                  (STATUS_LABEL["rejected"] + " / " + STATUS_LABEL["invalidated"], "0")],
        "fields": ["상태정보", "DOCDB 법적상태", "등록번호", "등록일", "존속기간(예상)만료일"],
    },
    "rights.claimScope": {
        "label": "청구범위 강도",
        "how": "청구항 개수는 많다고 강한 권리가 아니므로 정량 4점으로 제한하고, 나머지 4점은 "
               "LLM 이 대표·독립청구항을 읽고 권리범위의 넓이를 판단한다.",
        "formula": "정량 4 = 2×독립항수 백분위 + 2×청구항수 백분위\nLLM 4 = 권리범위 넓이(0~4)",
        "table": [("핵심 구성이 적고 넓은 상위개념", "LLM 4"),
                  ("핵심기술을 포괄하나 일부 한정", "LLM 3"),
                  ("수치·재료·공정조건 등 다수 한정", "LLM 2"),
                  ("실시예 수준의 좁은 권리·회피 용이", "LLM 1"),
                  ("실질적 보호범위 부족(청구항 없음 포함)", "LLM 0")],
        "fields": ["청구항 수", "독립항 수", "대표청구항", "독립청구항"],
    },
    "rights.globalScope": {
        "label": "글로벌 권리범위",
        "how": "패밀리의 **고유 국가**에 가중치를 부여해 합산한다. 미국 continuation 이나 일본 "
               "분할출원이 많아도 국가 커버리지가 넓어지는 것은 아니므로 건수가 아닌 국가 수를 쓴다.",
        "formula": "Σ 국가가중치 (상한 7)",
        "weights": DEFAULT_GLOBAL_COUNTRY_WEIGHTS,
        "weightsOther": DEFAULT_GLOBAL_OTHER_WEIGHT,
        "fields": ["WIPS패밀리 문헌번호(출원기준)", "국가코드", "지정국 코드"],
    },
    "rights.remainingTerm": {
        "label": "잔존기간",
        "how": "만료일 컬럼이 있으면 그 값을, 없으면 최초우선일 + 20년으로 근사한다. 국가별 제도·"
               "연장·포기·무효를 반영하지 않은 선별용 값이다.",
        "formula": "잔존년수 = 만료일 − 기준일 (없으면 20년 − 경과년수)",
        "table": [("12년 이상", "4"), ("8년 이상 12년 미만", "3"), ("4년 이상 8년 미만", "2"),
                  ("0년 초과 4년 미만", "1"), ("만료", "0")],
        "fields": ["존속기간(예상)만료일", "최우선출원일", "출원일"],
    },
    "rights.defenseSignal": {
        "label": "권리유지·방어 신호",
        "how": "분쟁이 있다는 사실이 권리 유효성을 뜻하지는 않는다. 다만 비용을 들여 방어하거나 "
               "공격할 경제적 유인이 있었다는 **보조 신호**로 쓴다. 패밀리 단위로 집계한다.",
        "formula": "분할·연속출원 1 + 심판·소송 1 + 양도 또는 실시권 1",
        "fields": ["분할출원 여부", "원출원번호", "심판 전체 횟수", "소송 전체 횟수",
                   "실시권 설정 유무", "권리변동 유무", "최근 양수인"],
    },
    "tech.topicFit": {
        "label": "Primary Topic 적합도",
        "how": "LLM 이 명칭·요약·청구항을 읽고 분석 주제와의 적합도를 0~100%로 판정한다. "
               "Gate 와 점수에 같은 값을 그대로 쓰면 자기상관이 생기므로, 점수는 완화식을 기본으로 한다.",
        "formula": "완화식: MIN(8, MAX(0, (적합도−60)/40 × 8))\n선형식: 적합도/100 × 8",
        "table": [("적합도 100%", "8.0"), ("90%", "6.0"), ("80%", "4.0"),
                  ("70% (Gate 하한)", "2.0"), ("60% 이하", "0.0")],
        "fields": ["발명의 명칭", "요약", "대표청구항", "독립청구항"],
    },
    "tech.contribution": {
        "label": "핵심 기술기여도",
        "how": "LLM 이 청구항 기준으로 기술적 기여의 크기를 판단한다.",
        "formula": "LLM 루브릭 0~8",
        "table": [("기존 구조의 근본적 변경·새로운 아키텍처", "7~8"),
                  ("핵심 공정·구조·재료의 유의미한 개선", "5~6"),
                  ("특정 요소·조건의 최적화", "3~4"),
                  ("주변부 개선·일반적 적용", "1~2"),
                  ("주제와 실질적 관련 없음", "0")],
        "fields": ["대표청구항", "독립청구항", "요약", "해결수단 요약"],
    },
    "tech.problemEffect": {
        "label": "문제·효과 중요성",
        "how": "해결하려는 과제가 얼마나 핵심 병목인지(3점)와, 효과가 얼마나 검증 가능하게 "
               "기재되었는지(3점)를 나눠 본다.",
        "formula": "문제 중요성(0~3) + 효과 검증성(0~3)",
        "table": [("성능·수율·신뢰성을 제한하는 핵심 병목", "문제 3"),
                  ("주요 공정·구조 문제", "문제 2"),
                  ("형상·제조 편의성 등 국부 개선", "문제 1"),
                  ("정량 데이터와 비교예로 효과 입증", "효과 3"),
                  ("실시예·복수 근거로 효과 설명", "효과 2"),
                  ("정성적 효과만 기재", "효과 1")],
        "fields": ["해결과제 요약", "효과 요약", "요약", "AI 요약"],
    },
    "tech.generality": {
        "label": "기술 범용성",
        "how": "여러 제품·공정에 적용 가능한지를 LLM 이 판단하고, CPC 서브그룹 다양성을 보조지표로 "
               "1점까지만 더한다. CPC 가 많다는 이유만으로 범용성이 높다고 볼 수 없기 때문이다.",
        "formula": "MIN(4, LLM 범용성(0~4)×0.75 + CPC 서브그룹수 백분위×1)",
        "fields": ["독립청구항", "Current CPC All"],
    },
    "tech.followUp": {
        "label": "후속개량·분할 신호",
        "how": "후속 개량이 이어졌는지를 본다. 장치·방법·시스템 등 복수 카테고리 독립항이 있으면 "
               "권리 설계가 촘촘하다는 신호로 본다.",
        "formula": "분할·계속출원 2 + 패밀리 내 후속출원 1 + 복수 청구항 카테고리 1",
        "fields": ["분할출원 여부", "WIPS패밀리 문헌 수(출원기준)", "독립청구항"],
    },
    "market.entry": {
        "label": "주요 시장 진입도",
        "how": "패밀리 **전체** 기준으로 주요 소비시장·제조 공급망 국가 진입 여부를 가중 합산한다. "
               "가중치는 프로젝트 목적에 따라 설정 화면에서 조정한다.",
        "formula": "Σ 시장가중치 (상한 8)",
        "weights": DEFAULT_MARKET_COUNTRY_WEIGHTS,
        "fields": ["WIPS패밀리 문헌번호(출원기준)", "국가코드"],
    },
    "market.applicantPower": {
        "label": "출원인 시장 영향력",
        "how": "외부 매출 데이터 없이 업로드된 모집단 안에서의 출원 점유로 대신한다. 대기업이 항상 "
               "중요한 특허를 보유한다는 뜻은 아니므로 100점 중 5점을 넘기지 않는다.",
        "formula": "주제 내 출원인 패밀리수 백분위×3 + 최근 5년 출원 백분위×2",
        "fields": ["출원인", "출원인 대표명화 영문명", "최우선출원일"],
    },
    "market.commercial": {
        "label": "상업화·거래 신호",
        "how": "실시권·양도는 상업적 가치의 직접 신호다. 다만 **데이터가 없는 것과 거래가 없는 것은 "
               "다르므로**, 컬럼이 없으면 0점 처리하되 '데이터 없음'으로 구분 표기한다.",
        "formula": "실시권 2 + 양도 이력 1 + 2개국 이상 등록 1",
        "fields": ["실시권 설정 유무", "실시권자 수", "권리변동 유무", "최근 양수인", "등록번호"],
    },
    "market.competitorCoverage": {
        "label": "경쟁사 커버리지",
        "how": "같은 회사가 자기인용을 반복한 특허보다, 여러 경쟁사가 후속 특허에서 인용한 특허를 "
               "높게 본다. 피인용 문헌의 출원인은 업로드된 모집단 안에서 해석하며, 해석률이 "
               "30% 미만이면 '타인 피인용 문헌 수'를 대용지표로 쓰고 그 사실을 표기한다.",
        "formula": "고유 비자기 피인용 출원인 수 백분위 × 3",
        "fields": ["타인 피인용 문헌번호(F1)", "피인용 문헌번호(F1)", "출원인"],
    },
    "impact.citation": {
        "label": "연령보정 피인용 영향력",
        "how": "피인용 20회는 2010년 출원과 2024년 출원에서 의미가 전혀 다르다. 그래서 절대값이 "
               "아니라 **동일 주제·동일 우선연도 집단 안에서의 백분위**를 쓴다. 비교집단 표본이 "
               "부족하면 연간 피인용 속도로 대체한다.",
        "formula": "PERCENTRANK( LN(1+피인용수) ) × 8",
        "fields": ["피인용 문헌 수(F1)", "최우선출원일", "공개일"],
    },
    "impact.diffusion": {
        "label": "비자기·다출원인 확산성",
        "how": "자기인용 비중이 높은 특허보다 여러 경쟁사로 확산된 특허를 산업 영향력이 크다고 본다.",
        "formula": "비자기 피인용 비율×2 + 고유 피인용 출원인수 백분위×3",
        "fields": ["타인 피인용 문헌번호(F1)", "자기 피인용 문헌번호(F1)", "피인용 문헌 수(F1)"],
    },
    "impact.originality": {
        "label": "기술 원천성",
        "how": "주제 내에서 얼마나 이른 시점의 출원인지, 이후 경쟁사로 얼마나 확산되었는지를 본다. "
               "후방인용은 적을수록 원천적인 것이 아니라(선행기술 검토 부족일 수 있음) 적정 구간"
               "(백분위 0.2~0.8)에서 만점을 준다.",
        "formula": "(1−우선일 백분위)×1.5 + 확산성 1.5 + 후방인용 구조 1",
        "fields": ["최우선출원일", "인용 문헌 수(B1)", "타인 피인용 문헌번호(F1)"],
    },
    "impact.conflict": {
        "label": "권리충돌·경쟁 신호",
        "how": "무효·이의·심판은 그 특허가 실제로 방해가 되었다는 신호다. 단, 무효로 확정된 특허는 "
               "권리 생존성에서 0점으로 크게 감점된다.",
        "formula": "심판·분쟁 1.5 + 제3자 인용·이의 0.5 + 양도·실시권 1.0",
        "fields": ["심판 전체 횟수", "심판 종류", "소송 전체 횟수", "심사관인용 문헌번호(FE)",
                   "실시권 설정 유무", "권리변동 유무"],
    },
}

RULES = [
    {
        "title": "① 패밀리 대표문헌 1건만 채점",
        "why": "같은 발명이 KR·US·JP·EP·CN·WO 에 각각 공개된 것을 6건으로 세면 특정 출원인의 "
               "점수가 과대평가된다.",
        "how": "패밀리별로 대표문헌 1건을 골라 채점한다. 우선순위는 "
               "등록·존속 > 등록·소멸 > 공개·심사중 > 거절·취하 이고, 동순위면 "
               "국가 우선순위 → 청구항 수 → 피인용 수 → 이른 우선일 순으로 정한다.",
        "note": "권리 점수는 대표문헌 개별 국가 기준, 시장·글로벌 점수는 패밀리 전체 기준으로 계산한다.",
    },
    {
        "title": "② 동일 주제·출원연도 안에서 비교(백분위)",
        "why": "특허 연령에 따른 편향을 없애기 위해서다.",
        "how": "비교집단은 '주제 + 최초 우선연도' 가 1순위, 표본이 부족하면 '주제 + 우선연도 ±N년', "
               "그다음 '주제 전체', 마지막으로 모집단 전체로 넓힌다. 사용된 비교집단과 표본 수는 "
               "결과 상세 화면에 그대로 표시된다.",
        "note": "백분위는 엑셀 PERCENTRANK.INC 와 동일하게 (자신보다 작은 값의 수)/(n−1) 로 계산한다. "
                "결과 상세 화면에는 비교집단의 분포(최소·25%·중앙·75%·최대·평균)와 표본 수를 함께 "
                "표시하므로, 백분위가 실제로 어느 수준인지 바로 확인할 수 있다.",
    },
    {
        "title": "③ 로그 변환 후 백분위",
        "why": "피인용·인용·패밀리 수는 일부 특허에 값이 몰리는 오른쪽 꼬리분포이기 때문이다.",
        "how": "LN(1 + 원값) 으로 변환한 뒤 비교집단 백분위를 구한다.",
    },
    {
        "title": "④ Gate 1 — 주제 적합도",
        "why": "주제와 무관한 특허가 상위에 올라오는 것을 막기 위해서다.",
        "how": "LLM 적합도가 기준(기본 70%) 미만이면 '제외(Gate 미통과)' 로 표시된다. "
               "기준값은 설정 화면에서 조정할 수 있다.",
    },
    {
        "title": "⑤ 데이터가 없는 항목",
        "why": "'데이터가 없다' 와 '값이 0이다' 는 다르다.",
        "how": "실시권·양도처럼 컬럼 자체가 없으면 0점으로 두되 결과에 '데이터 없음' 으로 구분 "
               "표기한다. 확보된 항목만으로 만점 환산하려면 설정에서 옵션을 켠다.",
    },
    {
        "title": "⑥ LLM 분석에 실패한 문헌",
        "why": "점수를 임의로 보정하면 근거 없는 값이 섞인다.",
        "how": "LLM 점수 0점으로 두고 사유를 결과의 주의사항에 남긴다. LLM 을 끄면 정량 구간만 "
               "계산되며, 그 사실이 경고로 표시된다.",
    },
]

ROUTES = [
    ("Route 1 (전문가 검토)", "Gate 통과 + 상위 10% 또는 80점 이상"),
    ("Route 2 (신흥 원천특허 검토)", "최근 5년 이내 우선일 + 연간 피인용 속도 상위 20%"),
    ("Route 3 (모니터링)", "그 밖의 Gate 통과 문헌"),
    ("제외(Gate 미통과)", "주제 적합도가 기준 미만"),
]

STEPS = [
    ("1. 업로드", "윈텔립스(WIPS ON)에서 내려받은 엑셀·CSV 를 올린다. 상단에 검색식 안내 행이 "
                  "있어도 헤더 행을 자동으로 찾는다."),
    ("2. 컬럼 매핑", "엑셀 컬럼을 표준 필드에 자동 매핑한다. 화면에 보이는 매핑 상태가 그대로 "
                     "실행되므로, 필요한 항목만 수정하면 된다."),
    ("3. 분석 설정", "분석 주제(Primary Topic)와 키워드, 사용할 LLM, Gate 기준, 비교집단, "
                     "국가 가중치를 정한다. 주제와 키워드가 LLM 판정의 기준이 된다."),
    ("4. 실행", "백그라운드로 실행되며 진행률이 표시되고 도중에 취소할 수 있다."),
    ("5. 결과", "총점 순으로 정렬된 목록에서 행을 클릭하면 18개 세부지표의 점수와 산출 근거를 "
                "모두 볼 수 있다. 엑셀·CSV 로 내려받을 수 있다."),
    ("6. 저장소", "부서·이름·프로젝트명을 입력해 저장하면(저장 시각 자동 기록) 나중에 다시 "
                  "불러오거나 내려받을 수 있다."),
]


def build_guide(config: ScoringConfig = None) -> Dict[str, Any]:
    """설명 화면용 데이터. 배점·가중치는 실제 상수에서 가져온다."""
    config = config or ScoringConfig()
    areas: List[Dict[str, Any]] = []
    quant_total = llm_total = 0.0

    for area_key, area_label, area_summary in AREA_INFO:
        components = []
        for component_key, maximum in COMPONENT_MAX.items():
            if not component_key.startswith(area_key + "."):
                continue
            info = COMPONENT_INFO[component_key]
            source = COMPONENT_SOURCE[component_key]
            if source == "quant":
                quant_part, llm_part = maximum, 0.0
            elif source == "llm":
                quant_part, llm_part = 0.0, maximum
            else:
                quant_part, llm_part = mixed_max(component_key)
            quant_total += quant_part
            llm_total += llm_part

            components.append({
                "key": component_key,
                "label": info["label"],
                "max": maximum,
                "source": source,
                "sourceLabel": SOURCE_LABEL[source],
                "quantMax": quant_part,
                "llmMax": llm_part,
                "how": info["how"],
                "formula": info.get("formula", ""),
                "table": [{"label": row[0], "score": row[1]} for row in info.get("table", [])],
                # dict 로 내보내면 JSON 키 정렬 때문에 의도한 순서(US→CN→…)가 깨진다.
                "weights": ([{"country": country, "weight": weight}
                             for country, weight in info["weights"].items()]
                            if info.get("weights") else None),
                "weightsOther": info.get("weightsOther"),
                "fields": info.get("fields", []),
            })

        areas.append({
            "key": area_key, "label": area_label, "summary": area_summary,
            "max": sum(c["max"] for c in components), "components": components,
        })

    return {
        "totalMax": sum(area["max"] for area in areas),
        "quantMax": round(quant_total, 2),
        "llmMax": round(llm_total, 2),
        "areas": areas,
        "rules": RULES,
        "grades": [{"grade": grade, "min": threshold} for threshold, grade in GRADE_BANDS],
        "routes": [{"route": route, "condition": condition} for route, condition in ROUTES],
        "steps": [{"step": step, "detail": detail} for step, detail in STEPS],
        "survivalScores": SURVIVAL_SCORES,
        "remainingTermBands": REMAINING_TERM_BANDS,
        "fieldGroups": _field_groups(),
    }


def _field_groups() -> List[Dict[str, Any]]:
    """표준 필드 카탈로그를 그룹별로 정리."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for spec in FIELDS:
        groups.setdefault(spec.group, []).append({
            "key": spec.key, "label": spec.label,
            "required": spec.required, "important": spec.important,
            "note": spec.note,
        })
    return [{"group": group, "fields": fields} for group, fields in groups.items()]
