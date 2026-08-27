# -*- coding: utf-8 -*-
"""윈텔립스(WIPS) RAW DATA 컬럼 정의 및 표준 필드 매핑 사전.

WIPS 다운로드 항목명은 다운로드 옵션/버전/국가에 따라 조금씩 달라지므로
표준 필드(key) 하나에 여러 별칭(alias)을 등록해 두고 자동 매핑에 사용한다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional

# 값 종류
TEXT = "text"
INT = "int"
FLOAT = "float"
DATE = "date"
LIST = "list"
ENTITY_LIST = "entity_list"   # 법인/개인 이름 목록(콤마 분리 주의)
BOOL = "bool"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str                     # 화면 표시용 한글명
    kind: str = TEXT
    aliases: tuple = ()            # WIPS 항목명 별칭
    group: str = "기타"
    required: bool = False         # 없으면 분석 불가
    important: bool = False        # 없으면 일부 점수가 0/결측 처리
    note: str = ""


def _f(key, label, kind=TEXT, aliases=(), group="기타", required=False,
       important=False, note="") -> FieldSpec:
    return FieldSpec(key=key, label=label, kind=kind, aliases=tuple(aliases),
                     group=group, required=required, important=important, note=note)


FIELDS: List[FieldSpec] = [
    # ---------- 식별 ----------
    _f("docNumber", "문헌번호", TEXT,
       ["문헌번호", "문헌 번호", "공개번호", "등록번호", "출원번호"], "식별",
       note="패밀리/인용 연결 키. 미매핑 시 등록번호→공개번호→출원번호 순으로 자동 생성"),
    _f("applicationNumber", "출원번호", TEXT, ["출원번호"], "식별", required=True),
    _f("country", "국가코드", TEXT, ["국가코드", "출원국가", "국가"], "식별", important=True),
    _f("dbKind", "DB종류", TEXT, ["DB종류"], "식별"),
    _f("patentUtility", "특허/실용 구분", TEXT, ["특허/실용 구분", "특허실용구분"], "식별"),
    _f("kindCode", "문헌종류 코드", TEXT, ["문헌종류 코드", "문헌종류코드"], "식별"),

    # ---------- 일자 ----------
    _f("applicationDate", "출원일", DATE, ["출원일"], "일자", important=True),
    _f("publicationNumber", "공개번호", TEXT, ["공개번호"], "일자"),
    _f("publicationDate", "공개일", DATE, ["공개일"], "일자", important=True),
    _f("announcementNumber", "공고번호", TEXT, ["공고번호"], "일자"),
    _f("announcementDate", "공고일", DATE, ["공고일"], "일자"),
    _f("registrationNumber", "등록번호", TEXT, ["등록번호"], "일자"),
    _f("registrationDate", "등록일", DATE, ["등록일"], "일자"),
    _f("issueDate", "발행일", DATE, ["발행일"], "일자"),
    _f("earliestPriorityDate", "최우선출원일(최초우선일)", DATE,
       ["최우선출원일", "최초우선일", "우선권 주장일", "우선일"], "일자", important=True,
       note="연령보정·잔존기간·원천성 계산의 기준일"),
    _f("earliestPriorityNumber", "최우선출원번호", TEXT, ["최우선출원번호"], "일자"),
    _f("earliestPriorityCountry", "최우선출원국가", TEXT, ["최우선출원국가"], "일자"),
    _f("priorityNumber", "우선권 번호", LIST, ["우선권 번호"], "일자"),
    _f("priorityCountry", "우선권 국가", LIST, ["우선권 국가"], "일자"),
    _f("priorityDate", "우선권 주장일", LIST, ["우선권 주장일"], "일자"),

    # ---------- 텍스트 ----------
    _f("title", "발명의 명칭", TEXT, ["발명의 명칭"], "텍스트", important=True),
    _f("titleTranslated", "발명의 명칭-번역문", TEXT, ["발명의 명칭-번역문"], "텍스트"),
    _f("abstract", "요약", TEXT, ["요약"], "텍스트", important=True),
    _f("abstractTranslated", "요약-번역문", TEXT, ["요약-번역문"], "텍스트"),
    _f("mainClaim", "대표청구항", TEXT, ["대표청구항"], "텍스트", important=True),
    _f("mainClaimTranslated", "대표청구항-번역문", TEXT, ["대표청구항-번역문"], "텍스트"),
    _f("independentClaims", "독립청구항", TEXT, ["독립청구항"], "텍스트", important=True),
    _f("independentClaimsTranslated", "독립청구항-번역문", TEXT, ["독립청구항-번역문"], "텍스트"),
    _f("allClaims", "전체 청구항", TEXT, ["전체 청구항", "전체청구항"], "텍스트"),
    _f("aiSummary", "AI 요약", TEXT, ["AI 요약", "WIPS AI"], "텍스트"),
    _f("ipureAiScore", "IPURE AI Score", FLOAT,
       ["IPURE AI Score", "IPURE AI스코어", "IPURE Score", "IPURE AI 점수", "IPURE"],
       "텍스트", important=True,
       note="Primary Topic 적합도 산출에 사용(백분율 환산 × 8점)"),
    _f("techFieldSummary", "기술분야 요약", TEXT, ["기술분야 요약"], "텍스트"),
    _f("problemSummary", "해결과제 요약", TEXT, ["해결과제 요약"], "텍스트"),
    _f("solutionSummary", "해결수단 요약", TEXT, ["해결수단 요약"], "텍스트"),
    _f("featureSummary", "특징 요약", TEXT, ["특징 요약"], "텍스트"),
    _f("effectSummary", "효과 요약", TEXT, ["효과 요약"], "텍스트"),

    # ---------- 청구항 수 ----------
    _f("claimCount", "청구항 수", INT, ["청구항 수", "청구항수"], "청구항", important=True),
    _f("independentClaimCount", "독립항 수", INT, ["독립항 수", "독립항수"], "청구항", important=True),

    # ---------- 분류 ----------
    _f("cpcAll", "Current CPC All", LIST,
       ["Current CPC All", "CPC All", "Original CPC All", "CPC"], "분류", important=True),
    _f("cpcMain", "Current CPC Main", TEXT,
       ["Current CPC Main", "CPC Main", "Original CPC Main"], "분류"),
    _f("ipcAll", "Current IPC All", LIST,
       ["Current IPC All", "IPC All", "Original IPC All", "IPC"], "분류"),
    _f("ipcMain", "Current IPC Main", TEXT,
       ["Current IPC Main", "IPC Main", "Original IPC Main"], "분류"),

    # ---------- 인명 ----------
    _f("applicant", "출원인", ENTITY_LIST, ["출원인"], "인명", important=True),
    _f("applicantNormalized", "출원인 대표명화 영문명", TEXT,
       ["출원인 대표명화 영문명", "출원인 대표명화 국문명", "출원인 대표명"], "인명", important=True),
    _f("applicantNormalizedCode", "출원인 대표명화 코드", TEXT, ["출원인 대표명화 코드"], "인명"),
    _f("applicantCountry", "출원인 국적", LIST, ["출원인 국적", "출원인 국가"], "인명"),
    _f("applicantCount", "출원인 수", INT, ["출원인 수"], "인명"),
    _f("inventor", "발명자", ENTITY_LIST, ["발명자"], "인명"),
    _f("inventorCount", "발명자 수", INT, ["발명자 수"], "인명"),
    _f("currentAssignee", "현재권리자", ENTITY_LIST, ["현재권리자"], "인명"),
    _f("currentAssigneeNormalized", "현재권리자 대표명화 영문명", TEXT,
       ["현재권리자 대표명화 영문명", "현재권리자 대표명화 국문명", "현재권리자 대표명화 코드"], "인명"),

    # ---------- 패밀리 ----------
    _f("familyId", "WIPS패밀리 ID", TEXT, ["WIPS패밀리 ID"], "패밀리", important=True),
    _f("familyMembers", "WIPS패밀리 문헌번호(출원기준)", LIST,
       ["WIPS패밀리 문헌번호(출원기준)"], "패밀리", important=True,
       note="패밀리 국가 커버리지 산출에 사용"),
    _f("familyDocCount", "WIPS패밀리 문헌 수(출원기준)", INT,
       ["WIPS패밀리 문헌 수(출원기준)"], "패밀리", important=True,
       note="패밀리 건수 점수 산출"),
    _f("familyCountryDocCounts", "WIPS패밀리 개별국 문헌 수(출원기준)", TEXT,
       ["WIPS패밀리 개별국 문헌 수(출원기준)", "EPO패밀리 개별국 문헌 수(출원기준)"],
       "패밀리", important=True,
       note="주요 시장 진입도 산출(국가별 출원 유무). 예: KR:2|US:3|JP:1"),
    _f("familyCountryCount", "WIPS패밀리 국가 수(출원기준)", INT,
       ["WIPS패밀리 국가 수(출원기준)"], "패밀리"),
    _f("familyBasicDoc", "WIPS패밀리 Basic Patent 문헌번호", TEXT,
       ["WIPS패밀리 Basic Patent 문헌번호"], "패밀리"),
    _f("epoFamilyId", "EPO(INPADOC)패밀리 ID", TEXT, ["EPO패밀리 ID"], "패밀리"),
    _f("epoFamilyMembers", "EPO패밀리 문헌번호(출원기준)", LIST,
       ["EPO패밀리 문헌번호(출원기준)"], "패밀리"),
    _f("epoFamilyDocCount", "EPO패밀리 문헌 수(출원기준)", INT,
       ["EPO패밀리 문헌 수(출원기준)"], "패밀리"),
    _f("epoFamilyCountryCount", "EPO패밀리 국가 수(출원기준)", INT,
       ["EPO패밀리 국가 수(출원기준)"], "패밀리"),
    _f("designatedStates", "지정국 코드", LIST, ["지정국 코드", "EPC지정국"], "패밀리"),

    # ---------- 인용 ----------
    _f("backwardCitationCount", "인용 문헌 수(B1)", INT, ["인용 문헌 수(B1)"], "인용"),
    _f("backwardCitations", "인용 문헌번호(B1)", LIST, ["인용 문헌번호(B1)"], "인용"),
    _f("selfBackwardCitations", "자기인용 문헌번호(B1)", LIST, ["자기인용 문헌번호(B1)"], "인용"),
    _f("otherBackwardCitations", "타인인용 문헌번호(B1)", LIST, ["타인인용 문헌번호(B1)"], "인용"),
    _f("nplCount", "비 특허 참고문헌 수(B1)", INT, ["비 특허 참고문헌 수(B1)"], "인용"),
    _f("forwardCitationCount", "피인용 문헌 수(F1)", INT, ["피인용 문헌 수(F1)"], "인용", important=True),
    _f("forwardCitations", "피인용 문헌번호(F1)", LIST, ["피인용 문헌번호(F1)"], "인용"),
    _f("selfForwardCitations", "자기 피인용 문헌번호(F1)", LIST, ["자기 피인용 문헌번호(F1)"], "인용"),
    _f("otherForwardCitations", "타인 피인용 문헌번호(F1)", LIST, ["타인 피인용 문헌번호(F1)"], "인용",
       important=True, note="비자기 확산성/경쟁사 커버리지 산출"),
    _f("examinerForwardCitations", "심사관인용 문헌번호(FE)", LIST,
       ["심사관인용 문헌번호(FE)"], "인용"),
    _f("examinerBackwardCitations", "심사관인용 문헌번호(BE)", LIST,
       ["심사관인용 문헌번호(BE)"], "인용"),

    # ---------- 행정/권리 ----------
    _f("legalStatus", "상태정보(법적상태)", TEXT, ["상태정보", "법적상태", "DOCDB 법적상태"],
       "권리", important=True),
    _f("docdbLegalStatus", "DOCDB 법적상태", TEXT, ["DOCDB 법적상태"], "권리"),
    _f("expiryDate", "존속기간(예상)만료일", DATE, ["존속기간(예상)만료일"], "권리"),
    _f("examinationRequested", "심사청구 여부", BOOL, ["심사청구 여부"], "권리"),
    _f("rejectionDecision", "거절결정 여부", BOOL, ["거절결정 여부"], "권리"),
    _f("reexamRequested", "재심사청구 여부", BOOL, ["재심사청구 여부"], "권리"),
    _f("divisionalFlag", "분할출원 여부", BOOL, ["분할출원 여부"], "권리", important=True),
    _f("parentApplicationNumber", "원출원번호", TEXT, ["원출원번호"], "권리"),
    _f("parentApplicationDate", "원출원일", DATE, ["원출원일"], "권리"),
    _f("trialCount", "심판 전체 횟수", INT, ["심판 전체 횟수"], "권리", important=True),
    _f("trialType", "심판 종류", LIST, ["심판 종류"], "권리"),
    _f("litigationCount", "소송 전체 횟수", INT, ["소송 전체 횟수"], "권리"),
    _f("licenseFlag", "실시권 설정 유무", BOOL, ["실시권 설정 유무", "실시권여부"], "권리", important=True),
    _f("licenseeCount", "실시권자 수", INT, ["실시권자 수"], "권리"),
    _f("recentAssignee", "최근 양수인", TEXT, ["최근 양수인"], "권리"),
    _f("recentAssignor", "최근 양도인", TEXT, ["최근 양도인"], "권리"),
    _f("recentAssignDate", "최근 양도일", DATE, ["최근 양도일"], "권리"),
    _f("recentAssignType", "최근 양도유형", TEXT, ["최근 양도유형"], "권리"),
    _f("rightsChangeFlag", "권리변동 유무", BOOL, ["권리변동 유무"], "권리"),
    _f("entityStatus", "Entity Status", TEXT, ["Entity Status"], "권리"),
    _f("standardPatent", "표준특허", TEXT, ["표준특허"], "권리"),
    _f("standardOrg", "표준화기구", TEXT, ["표준화기구"], "권리"),

    # ---------- 링크/기타 ----------
    _f("pdfLink", "원문(PDF)링크", TEXT, ["원문(PDF)링크"], "링크"),
    _f("detailLink", "상세보기 링크", TEXT,
       ["상세보기 링크(비로그인)", "상세보기 링크(로그인)"], "링크"),
    _f("userTag", "사용자태그", TEXT, ["사용자태그"], "링크"),
    _f("topicLabel", "주제(Topic) 라벨", TEXT,
       ["주제", "Topic", "Primary Topic", "기술분류", "사용자태그"], "링크",
       note="비교집단 분리를 위한 선택 항목. 없으면 프로젝트 주제 1개로 처리"),
]

FIELD_BY_KEY: Dict[str, FieldSpec] = {f.key: f for f in FIELDS}
REQUIRED_KEYS = [f.key for f in FIELDS if f.required]
IMPORTANT_KEYS = [f.key for f in FIELDS if f.important]

_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_PAREN_RE = re.compile(r"\([^)]*\)")
_NON_WORD_RE = re.compile(r"[^0-9a-z가-힣]+")


def normalize_header(header: Optional[str]) -> str:
    """컬럼명 정규화: 전각→반각, [국가목록] 제거, 공백 제거, 소문자화."""
    if header is None:
        return ""
    text = unicodedata.normalize("NFKC", str(header))
    text = text.replace("​", "").replace("﻿", "")
    text = _BRACKET_RE.sub("", text)
    text = re.sub(r"\s+", "", text)
    return text.strip().lower()


def loose_header(header: Optional[str]) -> str:
    """느슨한 정규화: 괄호 및 특수문자까지 제거(유사도 비교용)."""
    text = normalize_header(header)
    text = _PAREN_RE.sub("", text)
    return _NON_WORD_RE.sub("", text)


def build_alias_index():
    """{정규화 별칭: [(field_key, alias_priority)]} 인덱스."""
    strict: Dict[str, List] = {}
    loose: Dict[str, List] = {}
    for spec in FIELDS:
        aliases = list(spec.aliases) or [spec.label]
        for priority, alias in enumerate(aliases):
            strict.setdefault(normalize_header(alias), []).append((spec.key, priority))
            loose.setdefault(loose_header(alias), []).append((spec.key, priority))
    return strict, loose


ALIAS_STRICT, ALIAS_LOOSE = build_alias_index()


def field_catalog() -> List[Dict]:
    """프론트엔드에 내려줄 필드 카탈로그."""
    return [
        {
            "key": f.key, "label": f.label, "kind": f.kind, "group": f.group,
            "required": f.required, "important": f.important, "note": f.note,
            "aliases": list(f.aliases),
        }
        for f in FIELDS
    ]
