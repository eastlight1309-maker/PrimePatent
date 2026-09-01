# -*- coding: utf-8 -*-
"""앱 설명(도움말) 화면에 사용할 스코어링 안내 데이터.

배점·가중치·산출방식은 **실제 스코어링 코드가 쓰는 상수에서 그대로 가져온다.**
(문서를 따로 관리하면 코드와 어긋나므로, 여기서는 설명 문구만 보관한다)
"""

from __future__ import annotations

from typing import Any, Dict, List

from .columns import FIELDS
from .config import (AREA_LABEL, AREA_ORDER, COMPONENT_MAX, COMPONENT_SOURCE,
                     REMAINING_TERM_BANDS, SURVIVAL_SCORES, ScoringConfig, mixed_max)
from .scoring.engine import GRADE_BANDS

SOURCE_LABEL = {"quant": "정량", "llm": "LLM", "mixed": "정량+LLM"}

AREA_SUMMARY = {
    "rights": "권리의 생존 가능성, 청구범위의 강도, 방어 이력을 본다.",
    "tech": "주제 적합도와, 입력한 핵심기술이 청구항에 어떻게 반영되었는지를 본다.",
    "market": "주요 시장 진입, 출원인 영향력, 상업화 신호, 패밀리 규모를 본다.",
    "impact": "경쟁사 확산, 연령보정 피인용, 기술 선도성을 본다.",
}
AREA_INFO = [(key, AREA_LABEL[key], AREA_SUMMARY[key]) for key in AREA_ORDER]

# 세부지표별 설명 (배점은 COMPONENT_MAX 에서 자동으로 채워진다)
COMPONENT_INFO: Dict[str, Dict[str, Any]] = {
    "rights.survival": {
        "label": "권리 생존성",
        "how": "법적상태를 6단계로 분류해 구간점수를 준다. 상태 문자열이 없으면 등록번호·등록일·"
               "공개일 등 서지정보로 추정한다. 만료 임박은 **잔존 2년 이하**를 기준으로 한다.",
        "formula": "상태 분류 → 구간점수",
        "table": [("등록·존속", "10"),
                  ("등록·존속기간 만료 임박 (잔존 2년 이하)", "8"),
                  ("공개·심사 중", "6"),
                  ("출원 중·심사 미청구", "4"),
                  ("등록 후 소멸·포기", "2"),
                  ("상태 미상", "2"),
                  ("거절 확정·취하·포기 / 무효 확정", "0")],
        "fields": ["상태정보", "DOCDB 법적상태", "등록번호", "등록일", "존속기간(예상)만료일"],
    },
    "rights.claimScope": {
        "label": "청구범위 강도",
        "how": "청구항 개수는 많다고 강한 권리가 아니므로 정량 2점으로 제한하고, 나머지 3점은 "
               "LLM 이 **입력한 핵심기술 설명을 기준으로** 대표·독립청구항의 권리범위 넓이를 판단한다.",
        "formula": "정량 2 = 독립항 수 백분위 × 1 + 전체 청구항 수 백분위 × 1\nLLM 3 = 권리범위 넓이(0~3)",
        "table": [("핵심 구성이 적고 넓은 상위개념으로 기재", "LLM 3"),
                  ("핵심기술을 충분히 포괄하나 일부 한정 존재", "LLM 2.5"),
                  ("수치·재료·공정조건 등 다수 한정", "LLM 2"),
                  ("실시예 수준의 좁은 권리 또는 회피 용이", "LLM 1"),
                  ("실질적인 보호범위 부족", "LLM 0")],
        "fields": ["청구항 수", "독립항 수", "대표청구항", "독립청구항"],
    },
    "rights.remainingTerm": {
        "label": "잔존기간",
        "how": "만료일 컬럼이 있으면 그 값을, 없으면 최초우선일 + 20년으로 근사한다. 국가별 제도·"
               "연장·포기·무효를 반영하지 않은 선별용 값이며 제도 상한(20년)으로 제한한다.",
        "formula": "잔존년수 = 만료일 − 기준일 (없으면 20년 − 경과년수)",
        "table": [("12년 이상", "5"), ("8년 이상 12년 미만", "4"), ("4년 이상 8년 미만", "3"),
                  ("0년 초과 4년 미만", "1"), ("만료", "0")],
        "fields": ["존속기간(예상)만료일", "최우선출원일", "출원일"],
    },
    "rights.defenseSignal": {
        "label": "권리유지·방어 신호",
        "how": "분쟁이 있다는 사실이 권리 유효성을 뜻하지는 않는다. 다만 비용을 들여 방어하거나 "
               "공격할 경제적 유인이 있었다는 **보조 신호**로 쓴다. 패밀리 단위로 집계한다.",
        "formula": "분할·연속출원 존재 2점 + 심판·무효·이의 등 권리분쟁 존재 5점",
        "fields": ["분할출원 여부", "원출원번호", "심판 전체 횟수", "심판 종류", "소송 전체 횟수"],
    },
    "tech.topicFit": {
        "label": "Primary Topic 적합도",
        "how": "**IPURE AI Score 적용**. 엑셀의 'IPURE AI Score' 컬럼값을 백분율로 환산해 배점을 곱한다. "
               "LLM 판정이 아니라 업로드 데이터의 값을 그대로 쓰며, Gate 1 판정도 이 값으로 한다.",
        "formula": "점수 = IPURE AI Score ÷ 만점 × 8",
        "table": [("IPURE 100%", "8.0"), ("90%", "7.2"), ("80%", "6.4"),
                  ("70% (Gate 기본 하한)", "5.6"), ("50%", "4.0")],
        "fields": ["IPURE AI Score"],
    },
    "tech.coreCentrality": {
        "label": "독립청구항 내 핵심기술 중심성",
        "how": "입력한 핵심 구성요소가 독립청구항에서 **필수 구성으로 청구되고 있는지**를 본다. "
               "LLM 은 '혁신적인가' 를 판단하지 않고 ① 핵심기술이 독립청구항의 필수 구성인가 "
               "② 핵심 구성요소 사이의 연결관계가 청구되어 있는가 만 판정한다.",
        "formula": "LLM 루브릭 0~5",
        "table": [("핵심 구성요소와 연결관계가 대표청구항 및 2개 이상 독립항에 반복 포함", "5"),
                  ("핵심 구성요소와 연결관계가 대표청구항 또는 주요 독립항에 필수 구성으로 포함", "4"),
                  ("핵심 구성요소는 독립항에 있으나 연결관계·해결수단이 부분적으로만 한정", "3"),
                  ("핵심 구성요소가 종속항 중심이며 독립항에서는 상위개념으로만 표현", "2"),
                  ("요약에는 관련 기술이 있으나 청구항에서 필수 구성인지 불명확", "1"),
                  ("청구항에 없거나 적용 가능한 대상 중 하나로만 언급", "0")],
        "fields": ["대표청구항", "독립청구항", "요약", "핵심기술 설명(설정 입력)"],
    },
    "tech.claimExpansion": {
        "label": "핵심기술의 청구항 확장도",
        "how": "핵심기술이 청구항 전반에 얼마나 퍼져 있는지를 본다. 전체 청구항 수가 적은 특허가 "
               "불리해지지 않도록 **비율 기준과 절대 개수 기준 중 높은 점수**를 적용한다. "
               "(예: 전체 5개 중 4개가 관련이면 비율 80%로 높은 점수)",
        "formula": "관련 청구항 비율 = 관련 청구항 수 ÷ 전체 청구항 수\n"
                   "확장 종속항 수 = 핵심 구성의 구조·공정·소재·파라미터를 추가 한정하는 종속항 수",
        "table": [("비율 60% 이상 **이고** 확장 종속항 5개 이상", "5"),
                  ("비율 45% 이상 **또는** 확장 종속항 4개 이상", "4"),
                  ("비율 30% 이상 **또는** 확장 종속항 3개 이상", "3"),
                  ("비율 20% 이상 **또는** 확장 종속항 2개 이상", "2"),
                  ("독립항과 1개의 종속항에만 존재", "1"),
                  ("일부 청구항에 제한적으로 존재", "0.5"),
                  ("청구항에서 핵심기술을 확인할 수 없음", "0")],
        "fields": ["전체 청구항", "대표청구항", "독립청구항", "청구항 수", "핵심기술 설명(설정 입력)"],
    },
    "tech.claimTypeDiversity": {
        "label": "독립청구항 유형 다양성",
        "how": "하나의 기술개념을 장치·방법·시스템·중간제품 등 **여러 관점에서 보호**하고 있는지 본다. "
               "예: 「반도체 패키지는…」 장치 / 「제조방법은…」 제조방법 / 「전자장치는…」 시스템 / "
               "「인터포저는…」 중간제품 / 「본딩 방법은…」 공정방법 / 「검사 방법은…」 검사방법",
        "formula": "LLM 루브릭 0~3",
        "table": [("3개 이상의 서로 다른 청구항 유형에서 동일 핵심기술 보호", "3"),
                  ("장치·패키지 및 제조방법의 2개 유형에서 보호", "2.5"),
                  ("동일 유형의 복수 독립항에서 서로 다른 구현 보호", "2"),
                  ("1개의 독립항 유형과 다수 종속항으로 보호", "1.5"),
                  ("단일 독립청구항에만 제한", "1"),
                  ("관련 독립청구항을 확인할 수 없음", "0")],
        "fields": ["독립청구항", "전체 청구항", "발명의 명칭"],
    },
    "market.entry": {
        "label": "주요 시장 진입도",
        "how": "패밀리에 **해당 국가 출원이 존재하는지(유무)** 만 보고 가중치를 합산한다. "
               "소비·권리시장 10점과 제조·공급망시장 5점을 나누어 계산한다. "
               "'WIPS패밀리 개별국 문헌 수(출원기준)' 컬럼을 1순위 근거로 사용한다.",
        "formula": "소비·권리시장 Σ(상한 10) + 제조·공급망시장 Σ(상한 5)",
        "table": [("소비·권리시장 US / CN / EP / JP / KR", "4.2 / 2.2 / 2.1 / 1.1 / 0.4"),
                  ("제조·공급망시장 CN / JP / KR / TW / US", "1.5 / 1.5 / 0.8 / 0.8 / 0.4")],
        "fields": ["WIPS패밀리 개별국 문헌 수(출원기준)", "WIPS패밀리 문헌번호(출원기준)", "국가코드"],
    },
    "market.applicantPower": {
        "label": "출원인 시장 영향력",
        "how": "외부 매출 데이터 없이 업로드된 모집단 안에서의 출원 점유로 대신한다. "
               "출원인 점유율 = 해당 출원인의 패밀리 수 ÷ 해당 주제 전체 패밀리 수.",
        "formula": "주제 내 출원인 패밀리수 백분위 × 2 + 최근 5년 점유 백분위 × 2",
        "fields": ["출원인", "출원인 대표명화 영문명", "최우선출원일"],
    },
    "market.commercial": {
        "label": "상업화·거래 신호",
        "how": "실시권·양도는 상업적 가치의 직접 신호다. **데이터가 없는 것과 거래가 없는 것은 다르므로**, "
               "컬럼이 없으면 0점 처리하되 '데이터 없음' 으로 구분 표기한다.",
        "formula": "실시권 설정 존재 3점 + 타사 양도·양수 이력 존재 3점",
        "fields": ["실시권 설정 유무", "실시권자 수", "최근 양도유형", "최근 양도인", "최근 양도일",
                   "최근 양수인", "권리변동 유무"],
    },
    "market.familySize": {
        "label": "패밀리 건수",
        "how": "해당 특허의 패밀리 문헌이 얼마나 많은지 본다(국가 수가 아니라 문헌 건수).",
        "formula": "WIPS패밀리 문헌 수(출원기준) → 구간점수",
        "table": [("8건 이상", "2"), ("6건 이상", "1.5"), ("4건 이상", "1"),
                  ("3건 이상", "0.5"), ("1건", "0")],
        "fields": ["WIPS패밀리 문헌 수(출원기준)"],
    },
    "impact.competitorCoverage": {
        "label": "경쟁사 커버리지",
        "how": "같은 회사가 자기인용을 반복한 특허보다, 여러 경쟁사가 후속 특허에서 인용한 특허를 "
               "높게 본다. '타인 피인용 문헌번호' 를 근거로 하되 업로드 모집단 안에서 각 인용문헌의 "
               "출원인을 해석해 **고유 출원인 수**를 센다. 해석률이 낮으면 문헌 수를 대용지표로 쓴다.",
        "formula": "고유 비자기 피인용 출원인 수 백분위 × 5",
        "fields": ["타인 피인용 문헌번호(F1)", "피인용 문헌번호(F1)", "출원인"],
    },
    "impact.citation": {
        "label": "연령보정 피인용 영향력",
        "how": "피인용 20회는 2010년 출원과 2024년 출원에서 의미가 전혀 다르다. 그래서 절대값이 "
               "아니라 **동일 주제·동일 우선연도 집단 안에서의 백분위**를 쓴다. 비교집단 표본이 "
               "부족하면 연간 피인용 속도(전방인용 ÷ 공개 후 경과연수)로 대체한다.",
        "formula": "PERCENTRANK.INC( LN(1+전방인용수) ) × 15",
        "fields": ["피인용 문헌 수(F1)", "최우선출원일", "공개일"],
    },
    "impact.leadership": {
        "label": "기술 선도성",
        "how": "동일 주제 안에서 얼마나 이른 시점의 출원인지만 본다. 빠를수록 높은 점수를 받는다. "
               "(업로드 데이터는 전부 동일 주제로 간주한다)",
        "formula": "(1 − PERCENTRANK.INC(동일주제 최초우선일, 해당 특허 최초우선일)) × 5",
        "fields": ["최우선출원일"],
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
        "note": "권리 점수는 대표문헌 개별 국가 기준, 시장 진입도는 패밀리 전체 기준으로 계산한다.",
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
        "title": "⑥ 출원인 표준화는 승인이 필요하다",
        "why": "같은 회사가 여러 표기로 흩어져 있으면 출원인 기준 통계(시장 영향력, 경쟁사 "
               "커버리지, 자기인용 판정)가 모두 어긋난다.",
        "how": "업로드 직후 표기를 자동으로 묶어 후보를 보여 주고, 사용자가 표준명을 확정해 "
               "승인하면 그때부터 분석에 반영한다. 승인 전에는 원본 표기를 그대로 사용한다.",
        "note": "WIPS 대표명화 코드/영문명이 같으면 한글·영문 표기도 같은 그룹으로 묶는다. "
                "잘못 묶인 표기는 × 버튼으로 분리할 수 있다.",
    },
    {
        "title": "⑦ LLM 분석에 실패한 문헌",
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
    ("2. 출원인 표준화", "같은 회사의 여러 표기(삼성전자(주) / 삼성전자 주식회사 / SAMSUNG "
                        "ELECTRONICS CO., LTD.)를 하나로 묶어 표준명을 확정한다. "
                        "**승인한 이후에만** 분석에 반영되며, 승인 전에는 원본 표기를 그대로 쓴다."),
    ("3. 컬럼 매핑", "엑셀 컬럼을 표준 필드에 자동 매핑한다. 화면에 보이는 매핑 상태가 그대로 "
                     "실행되므로, 필요한 항목만 수정하면 된다."),
    ("4. 분석 설정", "분석 주제(Primary Topic)와 키워드, 사용할 LLM, Gate 기준, 비교집단, "
                     "국가 가중치를 정한다. 주제와 키워드가 LLM 판정의 기준이 된다."),
    ("5. 실행", "백그라운드로 실행되며 진행률이 표시되고 도중에 취소할 수 있다."),
    ("6. 결과", "총점 순으로 정렬된 목록에서 행을 클릭하면 세부지표의 점수와 산출 근거를 모두 "
                "볼 수 있다. 목록의 식별자는 **출원번호·출원일**이며 등록여부를 함께 표시한다. "
                "(문헌번호는 등록 여부에 따라 등록번호/공개번호가 섞이므로 목록 표기에 쓰지 않고 "
                "엑셀 내보내기에만 추적용으로 남긴다). 엑셀·CSV 로 내려받을 수 있다."),
    ("7. 저장소", "부서·이름·프로젝트명을 입력해 저장하면(저장 시각 자동 기록) 나중에 다시 "
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
                # dict 로 내보내면 JSON 키 정렬 때문에 의도한 순서가 깨지므로 배열로 낸다.
                "weights": _entry_weights(component_key, config),
                "weightsOther": None,
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


def _entry_weights(component_key: str, config: ScoringConfig):
    """주요 시장 진입도의 국가 가중치(소비/공급망 구분)."""
    if component_key != "market.entry":
        return None
    rows = [{"country": "[소비] " + country, "weight": weight}
            for country, weight in config.market_consumer_weights.items()]
    rows += [{"country": "[공급망] " + country, "weight": weight}
             for country, weight in config.market_supply_weights.items()]
    return rows


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
