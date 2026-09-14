# -*- coding: utf-8 -*-
"""테스트용 윈텔립스 RAW DATA 모사 파일 생성기 (실제 특허 데이터가 아님)."""

from __future__ import annotations

import os
import random
import sys

HEADERS = [
    "국가코드", "DB종류", "특허/실용 구분", "문헌종류 코드", "발명의 명칭", "요약", "대표청구항",
    "독립청구항[KR,JP,US,CN,EP,IN]", "청구항 수", "독립항 수[KR,JP,US,CN,EP,IN]",
    "IPURE AI Score",
    "AI 요약[KR,US,JP,CN,EP,PCT,TW]", "해결과제 요약[KR,US,JP,CN,EP,PCT,TW]",
    "해결수단 요약[KR,US,JP,CN,EP,PCT,TW]", "효과 요약[KR,US,JP,CN,EP,PCT,TW]",
    "출원번호", "출원일", "공개번호", "공개일", "등록번호", "등록일",
    "출원인", "출원인 대표명화 영문명", "출원인 국적", "발명자",
    "우선권 번호", "우선권 국가", "우선권 주장일", "최우선출원일",
    "인용 문헌 수(B1)", "인용 문헌번호(B1)", "피인용 문헌 수(F1)", "피인용 문헌번호(F1)",
    "자기 피인용 문헌번호(F1)", "타인 피인용 문헌번호(F1)",
    "TR", "외부TR",
    "WIPS패밀리 ID", "WIPS패밀리 문헌번호(출원기준)", "WIPS패밀리 문헌 수(출원기준)",
    "WIPS패밀리 국가 수(출원기준)", "WIPS패밀리 개별국 문헌 수(출원기준)",
    "상태정보[KR,JP,US,EP,CN,CA,AU]", "현재권리자[KR,JP,US,CN,CA,AU]",
    "Current CPC All", "Current IPC All",
    "분할출원 여부[KR,US,JP,EP,CN,IN,CA,AU]", "심판 전체 횟수[KR,JP,US,EP]",
    "실시권 설정 유무[KR]", "최근 양수인[KR,US,CN]", "존속기간(예상)만료일[KR,JP,US,EP,CN,CA,AU]",
    "상세보기 링크(비로그인)",
]

# 실제 WIPS 데이터처럼 같은 회사가 여러 표기로 등장하도록 구성한다
# (출원인 표준화 단계를 실제로 검증하기 위함)
APPLICANTS = [
    ("삼성전자(주)", "SAMSUNG ELECTRONICS", "KR"),
    ("삼성전자 주식회사", "SAMSUNG ELECTRONICS", "KR"),
    ("SAMSUNG ELECTRONICS CO., LTD.", "SAMSUNG ELECTRONICS", "KR"),
    ("에스케이하이닉스 주식회사", "SK HYNIX", "KR"),
    ("에스케이하이닉스(주)", "SK HYNIX", "KR"),
    ("TAIWAN SEMICONDUCTOR MANUFACTURING CO., LTD.", "TSMC", "TW"),
    ("TAIWAN SEMICONDUCTOR MANUFACTURING COMPANY LIMITED", "TSMC", "TW"),
    ("INTEL CORPORATION", "INTEL", "US"),
    ("INTEL CORP.", "INTEL", "US"),
    ("MICRON TECHNOLOGY, INC.", "MICRON", "US"),
    ("주식회사 에이피솔루션", "AP SOLUTION", "KR"),
]
TOPICS = [
    ("하이브리드 본딩을 이용한 반도체 패키지", "미세 피치 하이브리드 본딩 구조로 접합 신뢰성을 개선한다.",
     "H01L24/05; H01L23/00; H01L25/065"),
    ("TSV 기반 적층 반도체 장치", "실리콘 관통전극의 열경로를 개선한 적층 구조를 제공한다.",
     "H01L25/18; H01L23/48"),
    ("팬아웃 웨이퍼 레벨 패키지의 휨 저감 구조", "몰딩 응력을 분산시켜 휨과 박리를 저감한다.",
     "H01L23/31; H01L21/56"),
    ("반도체 패키지용 방열 구조체", "히트스프레더 접촉 면적을 늘려 열저항을 낮춘다.",
     "H01L23/367"),
    ("디스플레이 패널 구동 회로", "표시 패널의 구동 전압을 낮춘다.", "G09G3/36"),  # 주제 밖 문헌
]
STATUSES = ["등록(존속)", "등록(존속)", "공개", "심사중", "거절", "소멸", "등록(존속)"]
COUNTRY_SETS = [
    ["KR", "US", "JP", "CN", "EP", "TW"], ["KR", "US"], ["US", "CN"],
    ["KR", "US", "CN", "EP"], ["JP"], ["KR"], ["US", "EP", "JP", "TW"],
]


def claim_text(topic_index: int, breadth: int) -> str:
    base = ("기판; 상기 기판 상에 배치된 제1 반도체 칩; 및 상기 제1 반도체 칩 상에 "
            "하이브리드 본딩으로 접합된 제2 반도체 칩을 포함하는 반도체 패키지.")
    if breadth == 0:
        return base
    narrow = (" 여기서 상기 하이브리드 본딩의 피치는 3㎛ 이하이고, 상기 본딩 금속은 구리이며, "
              "상기 접합 온도는 200℃ 이상 400℃ 이하이고, 상기 절연층의 두께는 50nm 내지 200nm 인, ")
    return base[:-len("반도체 패키지.")] + narrow * breadth + "반도체 패키지."


def build_rows(count: int = 90, seed: int = 20260825):
    random.seed(seed)
    rows = []
    doc_numbers = []
    family_serial = 0
    while len(rows) < count:
        family_serial += 1
        topic_index = random.randrange(len(TOPICS))
        title, abstract, cpc = TOPICS[topic_index]
        applicant, applicant_en, nationality = random.choice(APPLICANTS)
        year = random.choice([2012, 2015, 2017, 2018, 2019, 2019, 2020, 2021, 2022, 2023, 2024])
        countries = random.choice(COUNTRY_SETS)
        family_id = "WF%06d" % family_serial
        members = ["%s10%d%06d" % (c, year, family_serial) for c in countries]
        priority = "%04d-%02d-%02d" % (year, random.randint(1, 12), random.randint(1, 28))
        base_citations = max(0, int(random.expovariate(1 / 6.0)) * (2026 - year) // 4)

        for country in countries:
            if len(rows) >= count:
                break
            doc = "%s10%d%06d" % (country, year, family_serial)
            doc_numbers.append(doc)
            status = random.choice(STATUSES)
            granted = status.startswith("등록") or status == "소멸"
            forward = max(0, base_citations + random.randint(-2, 3))
            citing = random.sample(doc_numbers, min(len(doc_numbers), forward)) if forward else []
            total_tr = round(forward * random.uniform(0.6, 1.8), 2)
            external_tr = round(total_tr * random.uniform(0.2, 0.9), 2)
            self_citing = [c for c in citing if c[2:] .startswith("10%d" % year)][:1]
            other_citing = [c for c in citing if c not in self_citing]
            breadth = random.randint(0, 2)
            rows.append({
                "국가코드": country, "DB종류": "특허", "특허/실용 구분": "특허", "문헌종류 코드": "A1",
                "발명의 명칭": "%s (%s)" % (title, country),
                "요약": abstract,
                "대표청구항": claim_text(topic_index, breadth),
                "독립청구항[KR,JP,US,CN,EP,IN]": claim_text(topic_index, breadth) +
                    " 제10항: 상기 반도체 패키지의 제조 방법.",
                "청구항 수": random.randint(6, 30),
                "독립항 수[KR,JP,US,CN,EP,IN]": random.randint(1, 4),
                "IPURE AI Score": random.choice([95, 88, 82, 76, 71, 68, 55, 42]),
                "AI 요약[KR,US,JP,CN,EP,PCT,TW]": abstract,
                "해결과제 요약[KR,US,JP,CN,EP,PCT,TW]":
                    "미세 피치 접합 시 발생하는 정렬 오차와 보이드로 수율이 저하되는 문제",
                "해결수단 요약[KR,US,JP,CN,EP,PCT,TW]": abstract,
                "효과 요약[KR,US,JP,CN,EP,PCT,TW]":
                    "접합 불량률을 30%% 저감하고 열저항을 15%% 개선한다." if breadth else
                    "접합 신뢰성이 향상된다.",
                "출원번호": doc, "출원일": priority,
                "공개번호": doc.replace("10", "20", 1), "공개일": "%d-%02d-01" % (year + 1, 9),
                "등록번호": doc.replace("10", "30", 1) if granted else "",
                "등록일": "%d-%02d-01" % (year + 3, 3) if granted else "",
                "출원인": applicant, "출원인 대표명화 영문명": applicant_en,
                "출원인 국적": nationality, "발명자": "홍길동;김철수",
                "우선권 번호": members[0], "우선권 국가": countries[0], "우선권 주장일": priority,
                "최우선출원일": priority,
                "인용 문헌 수(B1)": random.randint(0, 25),
                "인용 문헌번호(B1)": ";".join(random.sample(doc_numbers, min(len(doc_numbers), 4))),
                "피인용 문헌 수(F1)": forward,
                "피인용 문헌번호(F1)": ";".join(citing),
                "자기 피인용 문헌번호(F1)": ";".join(self_citing),
                "타인 피인용 문헌번호(F1)": ";".join(other_citing),
                # TR = WIPS 가 제공하는 연령보정 피인용 지표, 외부TR = 그중 타사 인용분
                "TR": total_tr,
                "외부TR": external_tr,
                "WIPS패밀리 ID": family_id,
                "WIPS패밀리 문헌번호(출원기준)": ";".join(members),
                "WIPS패밀리 문헌 수(출원기준)": len(members),
                "WIPS패밀리 국가 수(출원기준)": len(set(countries)),
                "WIPS패밀리 개별국 문헌 수(출원기준)":
                    "|".join("%s:%d" % (c, random.randint(1, 3)) for c in countries),
                "상태정보[KR,JP,US,EP,CN,CA,AU]": status,
                "현재권리자[KR,JP,US,CN,CA,AU]": applicant if granted else "",
                "Current CPC All": cpc,
                "Current IPC All": cpc.split(";")[0],
                "분할출원 여부[KR,US,JP,EP,CN,IN,CA,AU]": random.choice(["Y", "N", "N", ""]),
                "심판 전체 횟수[KR,JP,US,EP]": random.choice([0, 0, 0, 1, 2]),
                "실시권 설정 유무[KR]": random.choice(["유", "무", "무", ""]),
                "최근 양수인[KR,US,CN]": random.choice(["", "", "ACME LICENSING LLC"]),
                "존속기간(예상)만료일[KR,JP,US,EP,CN,CA,AU]": "%d-%s" % (year + 20, priority[5:]),
                "상세보기 링크(비로그인)": "https://www.wipsON.com/search/detail/%s" % doc,
            })
    return rows


def write(path: str, count: int = 90) -> str:
    import pandas as pd
    rows = build_rows(count)
    frame = pd.DataFrame(rows, columns=HEADERS)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if path.lower().endswith(".csv"):
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    else:
        frame.to_excel(path, index=False)
    return path


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "tmp/wips_sample.xlsx"
    number = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    print(write(target, number))
