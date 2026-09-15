# -*- coding: utf-8 -*-
"""출원인 표준화 단위 테스트."""

import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "python-lib"))

from primepatent.applicants import (build_name_map, cluster_applicants,  # noqa: E402
                                    collect_applicants, core_name, summarize)
from primepatent.parsing import to_entity_list  # noqa: E402
from primepatent.records import build_records  # noqa: E402

MAPPING = {"applicant": {"column": "출원인"},
           "applicantNormalized": {"column": "대표명"},
           "applicantNormalizedCode": {"column": "코드"}}


def rows(*items):
    return [{"출원인": raw, "대표명": hint, "코드": code} for raw, hint, code in items]


class EntityListTest(unittest.TestCase):
    """법인명 안의 콤마에서 이름이 잘리면 안 된다."""

    def test_corporate_suffix_is_not_split(self):
        self.assertEqual(to_entity_list("SAMSUNG ELECTRONICS CO., LTD."),
                         ["SAMSUNG ELECTRONICS CO., LTD."])
        self.assertEqual(to_entity_list("MICRON TECHNOLOGY, INC."),
                         ["MICRON TECHNOLOGY, INC."])

    def test_multiple_entities_are_split(self):
        self.assertEqual(to_entity_list("삼성전자(주); LG전자"), ["삼성전자(주)", "LG전자"])
        self.assertEqual(to_entity_list("A CO., LTD.|B CORP."), ["A CO., LTD.", "B CORP."])
        self.assertEqual(to_entity_list("홍길동,김철수"), ["홍길동", "김철수"])

    def test_blank(self):
        self.assertEqual(to_entity_list(""), [])
        self.assertEqual(to_entity_list(None), [])


class ClusterTest(unittest.TestCase):
    def test_groups_by_normalized_code(self):
        groups = cluster_applicants(collect_applicants(rows(
            ("삼성전자(주)", "SAMSUNG ELECTRONICS", "C1"),
            ("삼성전자 주식회사", "SAMSUNG ELECTRONICS", "C1"),
            ("SAMSUNG ELECTRONICS CO., LTD.", "SAMSUNG ELECTRONICS", "C1")), MAPPING))
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["variantCount"], 3)
        # 표준명은 한글 표기를 먼저 고르고 법인격 표기를 뗀다
        self.assertEqual(groups[0]["standardName"], "삼성전자")
        self.assertEqual(groups[0]["suggestedSource"], "한글 표기")
        # 표기가 2개 이상 묶인 그룹은 승인 전에는 병합하지 않는다
        self.assertFalse(groups[0]["approved"])

    def test_groups_by_normalized_name_across_languages(self):
        """코드가 없어도 대표명화 값이 같으면 한글·영문 표기를 묶어야 한다."""
        mapping = {"applicant": {"column": "출원인"}, "applicantNormalized": {"column": "대표명"}}
        groups = cluster_applicants(collect_applicants(rows(
            ("삼성전자(주)", "SAMSUNG ELECTRONICS", ""),
            ("SAMSUNG ELECTRONICS CO., LTD.", "SAMSUNG ELECTRONICS", "")), mapping))
        self.assertEqual(len(groups), 1)

    def test_similar_names_merge_without_hints(self):
        mapping = {"applicant": {"column": "출원인"}}
        groups = cluster_applicants(collect_applicants(rows(
            ("에스케이하이닉스 주식회사", "", ""), ("에스케이하이닉스(주)", "", "")), mapping))
        self.assertEqual(len(groups), 1)

    def test_different_companies_stay_separate(self):
        """LG전자 와 LG화학 처럼 접두어만 같은 회사는 묶이면 안 된다."""
        mapping = {"applicant": {"column": "출원인"}}
        groups = cluster_applicants(collect_applicants(rows(
            ("LG전자", "", ""), ("LG화학", "", ""), ("LG디스플레이", "", "")), mapping))
        self.assertEqual(len(groups), 3, [g["standardName"] for g in groups])

    def test_counts_and_summary(self):
        groups = cluster_applicants(collect_applicants(rows(
            ("삼성전자(주)", "SAMSUNG", "C1"), ("삼성전자(주)", "SAMSUNG", "C1"),
            ("삼성전자 주식회사", "SAMSUNG", "C1"), ("LG전자", "LG", "C2")), MAPPING))
        stats = summarize(groups)
        self.assertEqual(stats["groupCount"], 2)
        self.assertEqual(stats["variantCount"], 3)
        self.assertEqual(stats["mergedGroupCount"], 1)
        self.assertEqual(stats["documentCount"], 4)
        samsung = [g for g in groups if g["variantCount"] > 1][0]
        self.assertEqual(samsung["count"], 3)          # 2 + 1

    def test_no_applicant_column(self):
        self.assertEqual(collect_applicants(rows(("A", "", "")), {}), [])


class NameMapTest(unittest.TestCase):
    def test_map_includes_variants_and_aliases(self):
        groups = cluster_applicants(collect_applicants(rows(
            ("삼성전자(주)", "SAMSUNG ELECTRONICS", "C1"),
            ("삼성전자 주식회사", "SAMSUNG ELECTRONICS", "C1")), MAPPING))
        self.assertEqual(groups[0]["standardName"], "삼성전자")
        self.assertEqual(build_name_map(groups), {}, "승인 전에는 병합하지 않아야 한다")
        groups[0]["approved"] = True
        mapping = build_name_map(groups)
        self.assertEqual(mapping["삼성전자(주)"], "삼성전자")
        self.assertEqual(mapping["삼성전자 주식회사"], "삼성전자")
        # 대표명화 표기도 치환 대상이어야 화면 표시가 표준명으로 바뀐다
        self.assertEqual(mapping["SAMSUNG ELECTRONICS"], "삼성전자")

    def test_blank_standard_name_is_ignored(self):
        self.assertEqual(build_name_map([{"standardName": "", "variants": [{"raw": "A"}]}]), {})


class CoreNameTest(unittest.TestCase):
    """표준명에서 법인격 표기를 떼고 핵심 명칭만 남긴다."""

    CASES = [
        ("주식회사 이엔에프테크놀로지", "이엔에프테크놀로지"),
        ("(주)엘지화학", "엘지화학"),
        ("엘지화학 주식회사", "엘지화학"),
        ("도레이첨단소재 주식회사", "도레이첨단소재"),
        ("SAMSUNG ELECTRONICS CO., LTD.", "SAMSUNG ELECTRONICS"),
        ("MICRON TECHNOLOGY, INC.", "MICRON TECHNOLOGY"),
        ("Siemens AG", "Siemens"),
        ("ASML Holding N.V.", "ASML Holding"),
        ("The Boeing Company", "Boeing"),
        ("株式会社 東芝", "東芝"),
    ]

    def test_core_names(self):
        for raw, expected in self.CASES:
            self.assertEqual(core_name(raw), expected, raw)

    def test_name_made_only_of_legal_form_is_kept(self):
        self.assertEqual(core_name("주식회사"), "주식회사")
        self.assertEqual(core_name(""), "")


class JointApplicationTest(unittest.TestCase):
    """공동출원 행의 대표명화 값이 파트너에게 옮겨 붙으면 안 된다.

    실제 증상: '주식회사 이엔에프테크놀로지 68건' 과 '주식회사 제이케이머티리얼즈 5건' 이
    한 그룹으로 묶임(공동출원 5건의 대표명화 컬럼에 대표 출원인 1곳만 적혀 있었음).
    """

    MAPPING = {"applicant": {"column": "출원인"},
               "applicantNormalized": {"column": "대표명"}}

    def _rows(self, solo, joint):
        data = [{"출원인": "주식회사 이엔에프테크놀로지", "대표명": "ENF TECHNOLOGY"}] * solo
        data += [{"출원인": "주식회사 이엔에프테크놀로지;주식회사 제이케이머티리얼즈",
                  "대표명": "ENF TECHNOLOGY"}] * joint
        return data

    def test_partner_is_not_merged_into_lead_applicant(self):
        groups = cluster_applicants(collect_applicants(self._rows(63, 5), self.MAPPING))
        names = sorted(g["standardName"] for g in groups)
        self.assertEqual(names, ["이엔에프테크놀로지", "제이케이머티리얼즈"])
        for group in groups:
            self.assertEqual(group["variantCount"], 1, group["standardName"])

    def test_counts_split_solo_and_joint(self):
        groups = {g["standardName"]: g
                  for g in cluster_applicants(collect_applicants(self._rows(63, 5), self.MAPPING))}
        lead = groups["이엔에프테크놀로지"]
        partner = groups["제이케이머티리얼즈"]
        self.assertEqual((lead["count"], lead["soloCount"], lead["jointCount"]), (68, 63, 5))
        self.assertEqual((partner["count"], partner["soloCount"], partner["jointCount"]), (5, 0, 5))

    def test_aligned_hints_are_still_used(self):
        """대표명화 값 개수가 출원인 수와 맞으면 위치로 짝지어 사용한다."""
        rows_ = [{"출원인": "삼성전자(주);LG전자", "대표명": "SAMSUNG ELECTRONICS;LG ELECTRONICS"}]
        rows_ += [{"출원인": "SAMSUNG ELECTRONICS CO., LTD.", "대표명": "SAMSUNG ELECTRONICS"}]
        groups = cluster_applicants(collect_applicants(rows_, self.MAPPING))
        merged = [g for g in groups if g["variantCount"] > 1]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["standardName"], "삼성전자")
        self.assertEqual(sorted(v["raw"] for v in merged[0]["variants"]),
                         ["SAMSUNG ELECTRONICS CO., LTD.", "삼성전자(주)"])

    def test_conflicting_codes_block_similarity_merge(self):
        """WIPS 가 다른 회사로 판정한 것을 문자열 유사도로 뒤집지 않는다."""
        mapping = {"applicant": {"column": "출원인"},
                   "applicantNormalizedCode": {"column": "코드"}}
        data = [{"출원인": "에이비씨테크놀로지 주식회사", "코드": "C1"},
                {"출원인": "에이비씨테크놀로지스 주식회사", "코드": "C2"}]
        groups = cluster_applicants(collect_applicants(data, mapping))
        self.assertEqual(len(groups), 2, [g["standardName"] for g in groups])


class ApplyToRecordsTest(unittest.TestCase):
    RECORD_MAP = {"applicationNumber": {"column": "출원번호"},
                  "applicant": {"column": "출원인"},
                  "applicantNormalized": {"column": "대표명"}}
    ROWS = [{"출원번호": "KR1", "출원인": "삼성전자(주)", "대표명": "SAMSUNG ELECTRONICS"},
            {"출원번호": "KR2", "출원인": "삼성전자 주식회사", "대표명": "SAMSUNG ELECTRONICS"},
            {"출원번호": "KR3", "출원인": "LG전자", "대표명": "LG ELECTRONICS"}]

    def test_without_approval_original_names_are_kept(self):
        records = build_records(self.ROWS, self.RECORD_MAP)
        self.assertEqual(records[0]["applicantPrimary"], "SAMSUNG ELECTRONICS")
        self.assertFalse(records[0].get("_applicantStandardized"))

    def test_with_approval_standard_name_is_applied(self):
        name_map = {"삼성전자(주)": "삼성전자", "삼성전자 주식회사": "삼성전자",
                    "SAMSUNG ELECTRONICS": "삼성전자"}
        records = build_records(self.ROWS, self.RECORD_MAP, name_map)
        self.assertEqual(records[0]["applicantPrimary"], "삼성전자")
        self.assertEqual(records[1]["applicantPrimary"], "삼성전자")
        self.assertEqual(records[0]["applicantKey"], records[1]["applicantKey"])
        self.assertTrue(records[0]["_applicantStandardized"])
        # 대상이 아닌 출원인은 그대로
        self.assertEqual(records[2]["applicantPrimary"], "LG ELECTRONICS")
        self.assertFalse(records[2].get("_applicantStandardized"))

    def test_standardization_merges_applicant_statistics(self):
        """표준화 전에는 흩어져 있던 출원인 통계가 하나로 합쳐져야 한다."""
        from datetime import date

        from primepatent.config import ScoringConfig
        from primepatent.family import build_families
        from primepatent.scoring.context import AnalysisContext

        config = ScoringConfig(peer_min_size=2)
        as_of = date(2026, 8, 25)
        name_map = {"삼성전자(주)": "삼성전자", "삼성전자 주식회사": "삼성전자",
                    "SAMSUNG ELECTRONICS": "삼성전자"}

        before = build_records(self.ROWS, self.RECORD_MAP)
        build_families(before, config, as_of)
        counts_before = AnalysisContext(before, config, as_of).applicant_family_count

        after = build_records(self.ROWS, self.RECORD_MAP, name_map)
        build_families(after, config, as_of)
        counts_after = AnalysisContext(after, config, as_of).applicant_family_count

        samsung_key = after[0]["applicantKey"]
        self.assertEqual(counts_after[samsung_key], 2)          # 2건이 한 출원인으로
        self.assertLessEqual(max(counts_before.values()), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
