# -*- coding: utf-8 -*-
"""출원인 표준화 단위 테스트."""

import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "python-lib"))

from primepatent.applicants import (build_name_map, cluster_applicants,  # noqa: E402
                                    collect_applicants, summarize)
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
        self.assertEqual(groups[0]["standardName"], "SAMSUNG ELECTRONICS")

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
        groups[0]["standardName"] = "삼성전자"
        mapping = build_name_map(groups)
        self.assertEqual(mapping["삼성전자(주)"], "삼성전자")
        self.assertEqual(mapping["삼성전자 주식회사"], "삼성전자")
        # 대표명화 표기도 치환 대상이어야 화면 표시가 표준명으로 바뀐다
        self.assertEqual(mapping["SAMSUNG ELECTRONICS"], "삼성전자")

    def test_blank_standard_name_is_ignored(self):
        self.assertEqual(build_name_map([{"standardName": "", "variants": [{"raw": "A"}]}]), {})


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
