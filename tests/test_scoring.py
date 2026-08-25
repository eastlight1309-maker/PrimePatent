# -*- coding: utf-8 -*-
"""스코어링 규칙 단위 테스트 (스펙 4~8장)."""

import os
import sys
import unittest
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "python-lib"))

from primepatent import status as status_mod  # noqa: E402
from primepatent.config import COMPONENT_MAX, ScoringConfig  # noqa: E402
from primepatent.family import build_families  # noqa: E402
from primepatent.llm.analyzer import analysis_defaults, extract_json, validate_analysis  # noqa: E402
from primepatent.peers import percent_rank_inc  # noqa: E402
from primepatent.records import build_record  # noqa: E402
from primepatent.scoring.context import AnalysisContext  # noqa: E402
from primepatent.scoring.engine import score_one, score_records  # noqa: E402
from primepatent.scoring.tech import topic_fit_score  # noqa: E402

AS_OF = date(2026, 8, 25)


def make_record(**overrides):
    """표준 레코드 1건(모든 컬럼이 매핑된 상태)을 만든다."""
    row = {
        "출원번호": "KR1020190001234", "국가코드": "KR",
        "발명의 명칭": "반도체 패키지", "요약": "요약문",
        "대표청구항": "기판; 제1 칩; 제2 칩을 포함하는 반도체 패키지.",
        "독립청구항": "제1항 반도체 패키지. 제10항 제조 방법.",
        "청구항 수": 20, "독립항 수": 3,
        "출원일": "2019-01-10", "최우선출원일": "2019-01-10",
        "공개일": "2020-07-01", "등록번호": "KR102000000", "등록일": "2021-03-01",
        "상태정보": "등록(존속)", "출원인": "삼성전자(주)", "출원인 대표명화 영문명": "SAMSUNG",
        "WIPS패밀리 ID": "F1",
        "WIPS패밀리 문헌번호(출원기준)": "KR1020190001234;US16999888;JP2019123;EP19123;CN2019123;TW108123",
        "피인용 문헌 수(F1)": 10, "피인용 문헌번호(F1)": "US1;US2;KR3",
        "타인 피인용 문헌번호(F1)": "US1;US2", "자기 피인용 문헌번호(F1)": "KR3",
        "인용 문헌 수(B1)": 8, "Current CPC All": "H01L23/00; H01L24/05; H01L25/065",
        "분할출원 여부": "Y", "심판 전체 횟수": 1, "실시권 설정 유무": "유",
    }
    row.update({k: v for k, v in overrides.items()})
    if "출원번호" in overrides and "등록번호" not in overrides and row.get("등록번호"):
        row["등록번호"] = "REG" + str(overrides["출원번호"])
    mapping = {
        "applicationNumber": {"column": "출원번호"}, "country": {"column": "국가코드"},
        "title": {"column": "발명의 명칭"}, "abstract": {"column": "요약"},
        "mainClaim": {"column": "대표청구항"}, "independentClaims": {"column": "독립청구항"},
        "claimCount": {"column": "청구항 수"}, "independentClaimCount": {"column": "독립항 수"},
        "applicationDate": {"column": "출원일"}, "earliestPriorityDate": {"column": "최우선출원일"},
        "publicationDate": {"column": "공개일"}, "registrationNumber": {"column": "등록번호"},
        "registrationDate": {"column": "등록일"}, "legalStatus": {"column": "상태정보"},
        "applicant": {"column": "출원인"}, "applicantNormalized": {"column": "출원인 대표명화 영문명"},
        "familyId": {"column": "WIPS패밀리 ID"},
        "familyMembers": {"column": "WIPS패밀리 문헌번호(출원기준)"},
        "forwardCitationCount": {"column": "피인용 문헌 수(F1)"},
        "forwardCitations": {"column": "피인용 문헌번호(F1)"},
        "otherForwardCitations": {"column": "타인 피인용 문헌번호(F1)"},
        "selfForwardCitations": {"column": "자기 피인용 문헌번호(F1)"},
        "backwardCitationCount": {"column": "인용 문헌 수(B1)"},
        "cpcAll": {"column": "Current CPC All"},
        "divisionalFlag": {"column": "분할출원 여부"}, "trialCount": {"column": "심판 전체 횟수"},
        "licenseFlag": {"column": "실시권 설정 유무"},
    }
    return build_record(row, mapping, 0)


def prepare(records, config=None):
    config = config or ScoringConfig(peer_min_size=2)
    build_families(records, config, AS_OF)
    return AnalysisContext(records, config, AS_OF), config


def component_of(result, key):
    area = key.split(".")[0]
    for component in result["areas"][area]["components"]:
        if component["key"] == key:
            return component
    raise AssertionError("세부지표 없음: %s" % key)


class PercentileTest(unittest.TestCase):
    def test_excel_percentrank_inc(self):
        values = [0.0, 1.0, 2.0, 3.0, 4.0]
        self.assertEqual(percent_rank_inc(values, 0.0), 0.0)
        self.assertEqual(percent_rank_inc(values, 2.0), 0.5)
        self.assertEqual(percent_rank_inc(values, 4.0), 1.0)

    def test_small_sample_is_neutral(self):
        self.assertEqual(percent_rank_inc([5.0], 5.0), 0.5)


class SurvivalTest(unittest.TestCase):
    def test_status_scores(self):
        cases = [("등록(존속)", 8.0), ("심사중", 5.0), ("공개", 5.0),
                 ("거절", 0.0), ("취하", 0.0), ("무효", 0.0), ("소멸", 2.0)]
        for legal_status, expected in cases:
            record = make_record(**{"상태정보": legal_status})
            if legal_status != "등록(존속)":
                # 미등록 상태를 모사하기 위해 등록 서지 제거 (소멸은 등록 후 소멸)
                if legal_status != "소멸":
                    record["registrationNumber"] = ""
                    record["registrationDate"] = None
                record["_statusCode"] = None
            ctx, _ = prepare([record])
            result = score_one(record, None, ctx)
            self.assertEqual(component_of(result, "rights.survival")["score"], expected,
                             "%s → %s" % (legal_status, result["statusLabel"]))

    def test_expiring_patent_scores_lower(self):
        record = make_record(**{"최우선출원일": "2007-01-10", "출원일": "2007-01-10"})
        ctx, _ = prepare([record])
        result = score_one(record, None, ctx)
        # 2007 + 20년 = 2027 → 잔존 1년 미만 → 만료임박
        self.assertEqual(record["_statusCode"], status_mod.GRANTED_EXPIRING)
        self.assertEqual(component_of(result, "rights.survival")["score"], 6.0)
        self.assertEqual(component_of(result, "rights.remainingTerm")["score"], 1.0)


class RightsTest(unittest.TestCase):
    def test_global_scope_weighted_sum_capped(self):
        record = make_record()
        ctx, _ = prepare([record])
        result = score_one(record, None, ctx)
        component = component_of(result, "rights.globalScope")
        # KR,US,JP,EP,CN,TW = 1.0+1.5+1.2+1.2+1.3+1.0 = 7.2 → 상한 7
        self.assertEqual(component["detail"]["countryCount"], 6)
        self.assertAlmostEqual(component["detail"]["weightSum"], 7.2, places=2)
        self.assertEqual(component["score"], 7.0)

    def test_global_scope_single_country(self):
        record = make_record(**{"WIPS패밀리 문헌번호(출원기준)": "KR1020190001234"})
        ctx, _ = prepare([record])
        component = component_of(score_one(record, None, ctx), "rights.globalScope")
        self.assertEqual(component["score"], 1.0)

    def test_remaining_term_bands(self):
        # 기준일 2026-08-25, 잔존 = 20년 - 경과년수
        for priority, expected in [("2019-01-10", 4.0),   # 잔존 12.4년
                                   ("2016-01-10", 3.0),   # 잔존 9.4년
                                   ("2014-01-10", 2.0),   # 잔존 7.4년
                                   ("2010-01-10", 1.0),   # 잔존 3.4년
                                   ("2000-01-10", 0.0)]:  # 만료
            record = make_record(**{"최우선출원일": priority, "출원일": priority})
            ctx, _ = prepare([record])
            component = component_of(score_one(record, None, ctx), "rights.remainingTerm")
            self.assertEqual(component["score"], expected, priority)

    def test_claim_scope_splits_quant_and_llm(self):
        record = make_record()
        ctx, _ = prepare([record])
        analysis = analysis_defaults(status="ok")
        analysis["claimBreadthScore"] = 4.0
        component = component_of(score_one(record, analysis, ctx), "rights.claimScope")
        self.assertEqual(component["llmScore"], 4.0)
        self.assertIsNotNone(component["quantScore"])
        self.assertLessEqual(component["score"], COMPONENT_MAX["rights.claimScope"])

    def test_defense_signal_counts_events(self):
        record = make_record()
        ctx, _ = prepare([record])
        component = component_of(score_one(record, None, ctx), "rights.defenseSignal")
        self.assertEqual(component["score"], 3.0)      # 분할 + 심판 + 실시권

    def test_missing_signals_are_reported_not_scored(self):
        record = make_record()
        record["divisionalFlag"] = None
        record["trialCount"] = None
        record["licenseFlag"] = None
        ctx, _ = prepare([record])
        component = component_of(score_one(record, None, ctx), "rights.defenseSignal")
        self.assertEqual(component["score"], 0.0)
        self.assertEqual(len(component["detail"]["missingSignals"]), 3)
        self.assertTrue(component["notes"])


class TechTest(unittest.TestCase):
    def test_topic_fit_modes(self):
        self.assertAlmostEqual(topic_fit_score(100, "softened"), 8.0)
        self.assertAlmostEqual(topic_fit_score(70, "softened"), 2.0)
        self.assertAlmostEqual(topic_fit_score(60, "softened"), 0.0)
        self.assertAlmostEqual(topic_fit_score(50, "softened"), 0.0)
        self.assertAlmostEqual(topic_fit_score(75, "linear"), 6.0)

    def test_gate_threshold(self):
        record = make_record()
        ctx, _ = prepare([record])
        for fit, expected in [(90, True), (70, True), (69.9, False)]:
            analysis = analysis_defaults(status="ok")
            analysis["topicFitPercent"] = fit
            result = score_one(record, analysis, ctx)
            self.assertEqual(result["gate"]["passed"], expected, fit)

    def test_generality_caps_at_four(self):
        record = make_record()
        ctx, _ = prepare([record, make_record(**{"Current CPC All": "H01L1/1"})])
        analysis = analysis_defaults(status="ok")
        analysis["generalityScore"] = 4.0
        component = component_of(score_one(record, analysis, ctx), "tech.generality")
        self.assertLessEqual(component["score"], 4.0)
        self.assertLessEqual(component["llmScore"], 3.0)
        self.assertLessEqual(component["quantScore"], 1.0)

    def test_llm_missing_gives_zero_llm_score(self):
        record = make_record()
        ctx, _ = prepare([record])
        result = score_one(record, None, ctx)
        self.assertEqual(result["llmScore"], 0.0)
        self.assertGreater(result["quantScore"], 0.0)
        self.assertFalse(result["gate"]["passed"])


class MarketImpactTest(unittest.TestCase):
    def test_market_entry_capped_at_eight(self):
        record = make_record()
        ctx, _ = prepare([record])
        component = component_of(score_one(record, None, ctx), "market.entry")
        self.assertEqual(component["score"], 8.0)

    def test_citation_percentile_orders_records(self):
        low = make_record(**{"출원번호": "KR1", "WIPS패밀리 ID": "FA", "피인용 문헌 수(F1)": 0,
                             "피인용 문헌번호(F1)": "", "타인 피인용 문헌번호(F1)": ""})
        mid = make_record(**{"출원번호": "KR2", "WIPS패밀리 ID": "FB", "피인용 문헌 수(F1)": 5})
        high = make_record(**{"출원번호": "KR3", "WIPS패밀리 ID": "FC", "피인용 문헌 수(F1)": 90})
        records = [low, mid, high]
        ctx, _config = prepare(records)
        scores = [component_of(score_one(r, None, ctx), "impact.citation")["score"]
                  for r in records]
        self.assertLess(scores[0], scores[1])
        self.assertLess(scores[1], scores[2])
        self.assertEqual(scores[0], 0.0)   # 피인용 0건은 백분위 0

    def test_non_self_diffusion_ratio(self):
        record = make_record()          # 피인용 10건 중 타인 2건
        ctx, _ = prepare([record])
        component = component_of(score_one(record, None, ctx), "impact.diffusion")
        self.assertAlmostEqual(component["detail"]["nonSelfRatio"], 0.2, places=3)

    def test_originality_favors_earlier_priority(self):
        early = make_record(**{"출원번호": "KR-E", "WIPS패밀리 ID": "FE", "최우선출원일": "2012-01-01"})
        late = make_record(**{"출원번호": "KR-L", "WIPS패밀리 ID": "FL", "최우선출원일": "2024-01-01"})
        ctx, _ = prepare([early, late])
        early_score = component_of(score_one(early, None, ctx), "impact.originality")
        late_score = component_of(score_one(late, None, ctx), "impact.originality")
        self.assertGreater(early_score["detail"]["earlinessScore"],
                           late_score["detail"]["earlinessScore"])


class TotalsTest(unittest.TestCase):
    def test_component_and_area_maxima(self):
        record = make_record()
        ctx, _ = prepare([record])
        result = score_one(record, analysis_defaults(status="ok"), ctx)
        for area in result["areas"].values():
            for component in area["components"]:
                self.assertLessEqual(component["score"], component["max"] + 1e-9,
                                     component["key"])
        self.assertAlmostEqual(result["totalMax"], 100.0, places=6)
        self.assertAlmostEqual(result["quantMax"] + result["llmMax"], 100.0, places=6)
        self.assertLessEqual(result["totalScore"], 100.0)

    def test_quant_llm_split_is_70_30(self):
        record = make_record()
        ctx, _ = prepare([record])
        result = score_one(record, analysis_defaults(status="ok"), ctx)
        self.assertAlmostEqual(result["quantMax"], 71.0, places=6)
        self.assertAlmostEqual(result["llmMax"], 29.0, places=6)

    def test_result_is_json_serializable_with_iso_dates(self):
        import json
        import re as _re
        record = make_record()
        ctx, _ = prepare([record])
        result = score_one(record, analysis_defaults(status="ok"), ctx)
        blob = json.dumps(result)          # default= 없이 직렬화 가능해야 함
        self.assertTrue(_re.match(r"^\d{4}-\d{2}-\d{2}$", result["priorityDate"]),
                        result["priorityDate"])
        self.assertNotIn("GMT", blob)

    def test_area_weights_change_totals(self):
        record = make_record()
        config = ScoringConfig(peer_min_size=2)
        config.area_weights = {"rights": 2.0, "tech": 1.0, "market": 1.0, "impact": 1.0}
        build_families([record], config, AS_OF)
        ctx = AnalysisContext([record], config, AS_OF)
        result = score_one(record, None, ctx)
        self.assertAlmostEqual(result["totalMax"], 130.0, places=6)
        self.assertAlmostEqual(result["areas"]["rights"]["weightedMax"], 60.0, places=6)

    def test_ranking_is_descending(self):
        records = [make_record(**{"출원번호": "KR%d" % i, "WIPS패밀리 ID": "F%d" % i,
                                  "피인용 문헌 수(F1)": i * 3, "청구항 수": 5 + i})
                   for i in range(1, 8)]
        config = ScoringConfig(peer_min_size=3)
        build_families(records, config, AS_OF)
        scored = score_records(records, {}, config, AS_OF)
        totals = [row["totalScore"] for row in scored["rows"]]
        self.assertEqual(totals, sorted(totals, reverse=True))
        self.assertEqual([row["rank"] for row in scored["rows"]], list(range(1, 8)))


class FamilyTest(unittest.TestCase):
    def test_representative_prefers_granted_alive(self):
        pending = make_record(**{"출원번호": "KR1", "국가코드": "KR", "상태정보": "공개",
                                 "등록번호": "", "등록일": ""})
        granted = make_record(**{"출원번호": "US2", "국가코드": "US", "상태정보": "등록(존속)"})
        rejected = make_record(**{"출원번호": "JP3", "국가코드": "JP", "상태정보": "거절",
                                  "등록번호": "", "등록일": ""})
        records = [pending, granted, rejected]
        families = build_families(records, ScoringConfig(), AS_OF)
        family = list(families.values())[0]
        self.assertEqual(family["memberCount"], 3)
        self.assertEqual(family["representativeKey"], granted["_key"])

    def test_dedupe_scores_one_row_per_family(self):
        records = [make_record(**{"출원번호": "KR1", "국가코드": "KR"}),
                   make_record(**{"출원번호": "US2", "국가코드": "US"})]
        config = ScoringConfig(peer_min_size=2)
        build_families(records, config, AS_OF)
        from primepatent.family import representative_records
        self.assertEqual(len(representative_records(records, {}, True)), 1)
        self.assertEqual(len(representative_records(records, {}, False)), 2)


class DuplicateKeyTest(unittest.TestCase):
    def test_duplicate_doc_numbers_get_unique_keys(self):
        from primepatent.records import build_records
        mapping = {"applicationNumber": {"column": "출원번호"}, "title": {"column": "명칭"}}
        rows = [{"출원번호": "KR1020190001234", "명칭": "A"},
                {"출원번호": "KR1020190001234", "명칭": "B"},
                {"출원번호": "KR1020190009999", "명칭": "C"}]
        records = build_records(rows, mapping)
        keys = [r["_key"] for r in records]
        self.assertEqual(len(set(keys)), 3, keys)
        self.assertEqual(records[1]["_duplicateKey"], "KR1020190001234")


class LLMPayloadTest(unittest.TestCase):
    def test_extract_json_variants(self):
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('설명\n{"a": {"b": 2}} 끝'), {"a": {"b": 2}})
        self.assertIsNone(extract_json("JSON 이 없습니다"))

    def test_validate_clamps_out_of_range(self):
        result = validate_analysis({
            "topicFitPercent": 250, "claimBreadthScore": 9,
            "coreContributionScore": -3, "generalityScore": "3",
            "claimAnalysis": {"essentialElementCount": "5", "materialLimitation": 1},
            "keyFeatures": ["a"] * 20})
        self.assertEqual(result["topicFitPercent"], 100.0)
        self.assertEqual(result["claimBreadthScore"], 4.0)
        self.assertEqual(result["coreContributionScore"], 0.0)
        self.assertEqual(result["generalityScore"], 3.0)
        self.assertEqual(result["claimAnalysis"]["essentialElementCount"], 5)
        self.assertTrue(result["claimAnalysis"]["materialLimitation"])
        self.assertEqual(len(result["keyFeatures"]), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
