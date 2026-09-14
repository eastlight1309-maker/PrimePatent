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
from primepatent.scoring.tech import ipure_percent  # noqa: E402

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
        "IPURE AI Score": 85,
        "TR": 40, "외부TR": 12,
        "WIPS패밀리 개별국 문헌 수(출원기준)": "KR:2|US:2|JP:1|EP:1|CN:1|TW:1",
        "WIPS패밀리 문헌 수(출원기준)": 8,
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
        "ipureAiScore": {"column": "IPURE AI Score"},
        "totalTr": {"column": "TR"}, "externalTr": {"column": "외부TR"},
        "familyCountryDocCounts": {"column": "WIPS패밀리 개별국 문헌 수(출원기준)"},
        "familyDocCount": {"column": "WIPS패밀리 문헌 수(출원기준)"},
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
        cases = [("등록(존속)", 10.0), ("심사중", 6.0), ("공개", 6.0),
                 ("거절", 0.0), ("취하", 0.0), ("무효", 0.0), ("소멸", 2.0)]
        for legal_status, expected in cases:
            record = make_record(**{"상태정보": legal_status})
            if legal_status != "등록(존속)":
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
        # 2007 + 20년 = 2027 → 잔존 2년 이하 → 만료임박 8점
        self.assertEqual(record["_statusCode"], status_mod.GRANTED_EXPIRING)
        self.assertEqual(component_of(result, "rights.survival")["score"], 8.0)
        self.assertEqual(component_of(result, "rights.remainingTerm")["score"], 1.0)

    def test_remaining_term_bands(self):
        # 기준일 2026-08-25, 잔존 = 20년 - 경과년수
        for priority, expected in [("2019-01-10", 5.0),   # 잔존 12.4년
                                   ("2016-01-10", 4.0),   # 잔존 9.4년
                                   ("2014-01-10", 3.0),   # 잔존 7.4년
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
        analysis["claimBreadthScore"] = 3.0
        component = component_of(score_one(record, analysis, ctx), "rights.claimScope")
        self.assertEqual(component["llmScore"], 3.0)
        self.assertEqual(component["llmMax"], 3.0)
        self.assertEqual(component["quantMax"], 2.0)
        self.assertLessEqual(component["score"], COMPONENT_MAX["rights.claimScope"])

    def test_defense_signal_counts_events(self):
        record = make_record()
        ctx, _ = prepare([record])
        component = component_of(score_one(record, None, ctx), "rights.defenseSignal")
        self.assertEqual(component["score"], 7.0)      # 분할 2 + 분쟁 5

    def test_missing_signals_are_reported_not_scored(self):
        record = make_record()
        record["divisionalFlag"] = None
        record["trialCount"] = None
        record["litigationCount"] = None
        record["trialType"] = []
        ctx, _ = prepare([record])
        component = component_of(score_one(record, None, ctx), "rights.defenseSignal")
        self.assertEqual(component["score"], 0.0)
        self.assertEqual(len(component["detail"]["missingSignals"]), 2)
        self.assertTrue(component["notes"])

    def test_topic_fit_uses_ipure_score(self):
        """Primary Topic 적합도는 IPURE AI Score 백분율 × 8 이다."""
        for raw, expected in [(100, 8.0), (85, 6.8), (50, 4.0), (0, 0.0)]:
            record = make_record(**{"IPURE AI Score": raw})
            ctx, _ = prepare([record])
            component = component_of(score_one(record, None, ctx), "tech.topicFit")
            self.assertAlmostEqual(component["score"], expected, places=3, msg=str(raw))
            self.assertEqual(component["source"], "quant")

    def test_topic_fit_missing_score_is_reported(self):
        record = make_record()
        record["ipureAiScore"] = None
        ctx, _ = prepare([record])
        component = component_of(score_one(record, None, ctx), "tech.topicFit")
        self.assertEqual(component["score"], 0.0)
        self.assertTrue(component["notes"])

    def test_ipure_percent_scale(self):
        self.assertAlmostEqual(ipure_percent({"ipureAiScore": 85}, 100.0), 85.0)
        self.assertAlmostEqual(ipure_percent({"ipureAiScore": 0.85}, 1.0), 85.0)
        self.assertIsNone(ipure_percent({}, 100.0))

    def test_gate_threshold(self):
        record = make_record()
        for fit, expected in [(90, True), (70, True), (69, False)]:
            record["ipureAiScore"] = fit
            ctx, _ = prepare([record])
            result = score_one(record, analysis_defaults(status="ok"), ctx)
            self.assertEqual(result["gate"]["passed"], expected, fit)
            self.assertEqual(result["gate"]["source"], "IPURE AI Score")

    def test_new_tech_components_come_from_llm(self):
        record = make_record()
        ctx, _ = prepare([record])
        analysis = analysis_defaults(status="ok")
        analysis.update({"coreCentralityScore": 5.0, "claimExpansionScore": 5.0,
                         "claimTypeDiversityScore": 3.0})
        result = score_one(record, analysis, ctx)
        self.assertEqual(component_of(result, "tech.coreCentrality")["score"], 5.0)
        self.assertEqual(component_of(result, "tech.claimExpansion")["score"], 5.0)
        self.assertEqual(component_of(result, "tech.claimTypeDiversity")["score"], 3.0)
        for key in ("tech.coreCentrality", "tech.claimExpansion", "tech.claimTypeDiversity"):
            self.assertEqual(component_of(result, key)["source"], "llm")

    def test_llm_missing_gives_zero_llm_score(self):
        record = make_record()
        ctx, _ = prepare([record])
        result = score_one(record, None, ctx)
        self.assertEqual(result["llmScore"], 0.0)
        self.assertGreater(result["quantScore"], 0.0)
        # Topic 적합도는 IPURE 기반이므로 LLM 없이도 점수가 나온다
        self.assertGreater(component_of(result, "tech.topicFit")["score"], 0.0)

    def test_market_entry_consumer_and_supply(self):
        record = make_record()
        ctx, _ = prepare([record])
        component = component_of(score_one(record, None, ctx), "market.entry")
        # KR,US,JP,EP,CN,TW 전부 진입 → 소비 10 + 공급망 5 = 15 (상한)
        self.assertEqual(component["score"], 15.0)
        self.assertEqual(component["detail"]["consumerScore"], 10.0)
        self.assertEqual(component["detail"]["supplyScore"], 5.0)

    def test_market_entry_partial(self):
        record = make_record(**{"WIPS패밀리 개별국 문헌 수(출원기준)": "US:1",
                                "WIPS패밀리 문헌번호(출원기준)": "US16999888",
                                "국가코드": "US"})
        ctx, _ = prepare([record])
        component = component_of(score_one(record, None, ctx), "market.entry")
        self.assertEqual(component["detail"]["countries"], ["US"])
        self.assertAlmostEqual(component["detail"]["consumerScore"], 4.2, places=3)
        self.assertAlmostEqual(component["detail"]["supplyScore"], 0.4, places=3)

    def test_family_size_bands(self):
        for count, expected in [(9, 2.0), (6, 1.5), (4, 1.0), (3, 0.5), (1, 0.0)]:
            record = make_record(**{"WIPS패밀리 문헌 수(출원기준)": count})
            ctx, _ = prepare([record])
            component = component_of(score_one(record, None, ctx), "market.familySize")
            self.assertEqual(component["score"], expected, count)

    def test_citation_uses_tr_max_ratio(self):
        """연령보정 피인용 영향력 = (TR / 모집단 TR 최대값) x 13."""
        records = [make_record(**{"출원번호": "KR%d" % i, "WIPS패밀리 ID": "F%d" % i, "TR": tr})
                   for i, tr in enumerate([0, 25, 100])]
        ctx, _config = prepare(records)
        scores = [component_of(score_one(r, None, ctx), "impact.citation")["score"]
                  for r in records]
        self.assertEqual(scores[0], 0.0)                     # TR 0 -> 0점
        self.assertAlmostEqual(scores[1], 25.0 / 100.0 * 13.0, places=6)
        self.assertEqual(scores[2], 13.0)                    # 최대값 보유 건은 만점

    def test_competitor_coverage_uses_external_tr_max_ratio(self):
        """경쟁사 커버리지 = (외부TR / 모집단 외부TR 최대값) x 7."""
        records = [make_record(**{"출원번호": "KR%d" % i, "WIPS패밀리 ID": "F%d" % i, "외부TR": value})
                   for i, value in enumerate([2, 8, 40])]
        ctx, _config = prepare(records)
        scores = [component_of(score_one(r, None, ctx), "impact.competitorCoverage")["score"]
                  for r in records]
        self.assertAlmostEqual(scores[0], 2.0 / 40.0 * 7.0, places=6)
        self.assertAlmostEqual(scores[1], 8.0 / 40.0 * 7.0, places=6)
        self.assertEqual(scores[2], 7.0)

    def test_max_ratio_detail_is_auditable(self):
        records = [make_record(**{"출원번호": "KR%d" % i, "WIPS패밀리 ID": "F%d" % i, "TR": tr})
                   for i, tr in enumerate([10, 50])]
        ctx, _ = prepare(records)
        detail = component_of(score_one(records[0], None, ctx), "impact.citation")["detail"]
        self.assertEqual(detail["value"], 10.0)
        self.assertEqual(detail["populationMax"], 50.0)
        self.assertAlmostEqual(detail["ratio"], 0.2, places=6)
        self.assertEqual(detail["populationN"], 2)
        self.assertIn("13", detail["formula"])

    def test_missing_tr_scores_zero_with_reason(self):
        """값이 없으면 숨기지 말고 0점 + 사유를 남긴다."""
        blank = make_record(**{"출원번호": "KR1", "WIPS패밀리 ID": "FA", "TR": "", "외부TR": ""})
        other = make_record(**{"출원번호": "KR2", "WIPS패밀리 ID": "FB", "TR": 30, "외부TR": 9})
        ctx, _ = prepare([blank, other])
        result = score_one(blank, None, ctx)
        for key, label in [("impact.citation", "TR"), ("impact.competitorCoverage", "외부TR")]:
            component = component_of(result, key)
            self.assertEqual(component["score"], 0.0, key)
            self.assertIsNone(component["detail"]["value"], key)
            self.assertTrue(component["notes"], key)
            self.assertIn(label, component["notes"][0])

    def test_zero_population_max_scores_zero_without_crash(self):
        """모집단 전체가 0/결측이어도 0 나눗셈 없이 0점으로 처리한다."""
        records = [make_record(**{"출원번호": "KR%d" % i, "WIPS패밀리 ID": "F%d" % i,
                                  "TR": 0, "외부TR": 0})
                   for i in range(2)]
        ctx, _ = prepare(records)
        for record in records:
            result = score_one(record, None, ctx)
            for key in ("impact.citation", "impact.competitorCoverage"):
                component = component_of(result, key)
                self.assertEqual(component["score"], 0.0)
                self.assertEqual(component["detail"]["populationMax"], 0.0)
                self.assertIsNone(component["detail"]["ratio"])
                self.assertTrue(component["notes"])

    def test_leadership_favors_earlier_priority(self):
        early = make_record(**{"출원번호": "KR-E", "WIPS패밀리 ID": "FE", "최우선출원일": "2012-01-01"})
        late = make_record(**{"출원번호": "KR-L", "WIPS패밀리 ID": "FL", "최우선출원일": "2024-01-01"})
        ctx, _ = prepare([early, late])
        early_score = component_of(score_one(early, None, ctx), "impact.leadership")["score"]
        late_score = component_of(score_one(late, None, ctx), "impact.leadership")["score"]
        self.assertGreater(early_score, late_score)
        self.assertEqual(early_score, 5.0)      # 가장 이른 출원 → 만점
        self.assertEqual(late_score, 0.0)

    def test_component_and_area_maxima(self):
        record = make_record()
        ctx, _ = prepare([record])
        result = score_one(record, analysis_defaults(status="ok"), ctx)
        for area in result["areas"].values():
            for component in area["components"]:
                self.assertLessEqual(component["score"], component["max"] + 1e-9,
                                     component["key"])
        from primepatent.config import TOTAL_MAX
        self.assertAlmostEqual(result["totalMax"], TOTAL_MAX, places=6)
        self.assertAlmostEqual(result["quantMax"] + result["llmMax"], TOTAL_MAX, places=6)
        self.assertLessEqual(result["totalScore"], TOTAL_MAX)

    def test_every_component_reports_quant_and_llm_maxima(self):
        """세부지표마다 정량/LLM 배점 상한이 노출되고 합이 배점과 같아야 한다."""
        from primepatent.config import mixed_max
        record = make_record()
        ctx, _ = prepare([record])
        result = score_one(record, analysis_defaults(status="ok"), ctx)
        for area in result["areas"].values():
            for component in area["components"]:
                expected = mixed_max(component["key"])
                self.assertAlmostEqual(component["quantMax"], expected[0], places=6,
                                       msg=component["key"])
                self.assertAlmostEqual(component["llmMax"], expected[1], places=6,
                                       msg=component["key"])
                self.assertAlmostEqual(component["quantMax"] + component["llmMax"],
                                       component["max"], places=6, msg=component["key"])

    def test_claim_scope_exposes_llm_raw_score(self):
        """LLM 이 매긴 권리범위 넓이(0~3)가 상세에 그대로 남아야 한다."""
        record = make_record()
        ctx, _ = prepare([record])
        analysis = analysis_defaults(status="ok")
        analysis["claimBreadthScore"] = 2.0
        component = component_of(score_one(record, analysis, ctx), "rights.claimScope")
        self.assertEqual(component["detail"]["claimBreadthScore"], 2.0)
        self.assertEqual(component["llmScore"], 2.0)
        self.assertEqual(component["llmMax"], 3.0)
        self.assertEqual(component["quantMax"], 2.0)
        self.assertAlmostEqual(component["score"],
                               component["quantScore"] + component["llmScore"], places=6)

    def test_quant_llm_split(self):
        record = make_record()
        ctx, _ = prepare([record])
        result = score_one(record, analysis_defaults(status="ok"), ctx)
        self.assertAlmostEqual(result["quantMax"], 84.0, places=6)
        self.assertAlmostEqual(result["llmMax"], 16.0, places=6)

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
        from primepatent.config import AREA_MAX, TOTAL_MAX
        self.assertAlmostEqual(result["totalMax"], TOTAL_MAX + AREA_MAX["rights"], places=6)
        self.assertAlmostEqual(result["areas"]["rights"]["weightedMax"],
                               AREA_MAX["rights"] * 2, places=6)

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


class PeerStatsTest(unittest.TestCase):
    """비교집단 분포 요약(백분위 해석용)."""

    def _index(self):
        from primepatent.peers import PeerIndex
        index = PeerIndex(min_size=5, year_window=1)
        for value in [3, 6, 8, 10, 12, 15, 18, 20, 25, 40]:
            index.add("T", 2020, value)
        return index

    def test_quantiles_match_excel_percentile_inc(self):
        from primepatent.peers import _quantile
        values = [3, 6, 8, 10, 12, 15, 18, 20, 25, 40]
        # 엑셀 =PERCENTILE.INC({...}, q) 와 동일해야 한다
        self.assertAlmostEqual(_quantile(values, 0.0), 3)
        self.assertAlmostEqual(_quantile(values, 0.25), 8.5)
        self.assertAlmostEqual(_quantile(values, 0.5), 13.5)
        self.assertAlmostEqual(_quantile(values, 0.75), 19.5)
        self.assertAlmostEqual(_quantile(values, 1.0), 40)

    def test_stats_describe_the_group_actually_used(self):
        index = self._index()
        _rank, group, size = index.rank("T", 2020, 12)
        stats = index.stats("T", 2020)
        self.assertEqual(stats["peerGroup"], group)
        self.assertEqual(stats["n"], size)
        self.assertEqual(stats["min"], 3)
        self.assertEqual(stats["max"], 40)
        self.assertEqual(stats["median"], 13.5)

    def test_stats_follow_fallback(self):
        from primepatent.peers import PeerIndex
        index = PeerIndex(min_size=5, year_window=1)
        for value in [1, 2]:
            index.add("T", 2019, value)
        for value in [10, 20, 30, 40]:
            index.add("T", 2020, value)
        # 2019 단독은 2건 → ±1년(6건) 으로 확장되어야 한다
        stats = index.stats("T", 2019)
        self.assertEqual(stats["peerGroup"], "topic+year±1")
        self.assertEqual(stats["n"], 6)
        self.assertEqual(stats["max"], 40)

    def test_empty_index_returns_none(self):
        from primepatent.peers import PeerIndex
        self.assertIsNone(PeerIndex().stats("T", 2020))

    def test_claim_scope_detail_exposes_distribution(self):
        records = [make_record(**{"출원번호": "KR%02d" % i, "WIPS패밀리 ID": "F%02d" % i,
                                  "청구항 수": count, "독립항 수": 1 + i % 3})
                   for i, count in enumerate([5, 9, 13, 21, 30])]
        ctx, _ = prepare(records, ScoringConfig(peer_min_size=3))
        result = score_one(records[2], None, ctx)
        detail = component_of(result, "rights.claimScope")["detail"]
        stats = detail["claimPeerStats"]
        self.assertEqual(stats["n"], 5)
        self.assertEqual(stats["min"], 5)
        self.assertEqual(stats["max"], 30)
        self.assertEqual(stats["median"], 13)
        self.assertEqual(detail["claimPeerN"], stats["n"])
        self.assertIn("independentPeerStats", detail)

    def test_leadership_distribution_is_reported_in_years(self):
        """우선일 분포는 ordinal 이 아니라 연도로 보여야 한다."""
        # 최초우선일은 출원일보다 늦을 수 없으므로 출원일도 함께 맞춘다.
        records = [make_record(**{"출원번호": "KR%02d" % i, "WIPS패밀리 ID": "F%02d" % i,
                                  "출원일": "%d-03-01" % year,
                                  "최우선출원일": "%d-03-01" % year})
                   for i, year in enumerate([2010, 2013, 2015, 2017, 2019])]
        ctx, _ = prepare(records, ScoringConfig(peer_min_size=3))
        detail = component_of(score_one(records[2], None, ctx), "impact.leadership")["detail"]
        stats = detail["peerStats"]
        self.assertEqual(stats["min"], 2010)
        self.assertEqual(stats["max"], 2019)
        self.assertIn("우선연도", stats["unit"])


class OutputIdentityTest(unittest.TestCase):
    """결과 목록의 식별자는 출원정보여야 하고, 등록여부가 함께 표시되어야 한다."""

    def test_application_info_is_exposed(self):
        record = make_record()
        ctx, _ = prepare([record])
        result = score_one(record, None, ctx)
        self.assertEqual(result["applicationNumber"], "KR1020190001234")
        self.assertEqual(result["applicationDateText"], "2019-01-10")
        # 문헌번호도 추적용으로 남아 있어야 한다(인용 매칭 키)
        self.assertTrue(result["docNumber"])

    def test_registration_label(self):
        registered = make_record()
        ctx, _ = prepare([registered])
        result = score_one(registered, None, ctx)
        self.assertTrue(result["registered"])
        self.assertEqual(result["registrationLabel"], "등록")
        self.assertEqual(result["registrationNumber"], "KR102000000")

        pending = make_record(**{"출원번호": "KR-P", "상태정보": "공개"})
        pending["registrationNumber"] = ""
        pending["registrationDate"] = None
        ctx2, _ = prepare([pending])
        result2 = score_one(pending, None, ctx2)
        self.assertFalse(result2["registered"])
        self.assertEqual(result2["registrationLabel"], "미등록")

    def test_lapsed_patent_is_still_registered(self):
        """등록 후 소멸도 '등록' 으로 표기하고, 현재 상태는 상태 컬럼에서 구분한다."""
        record = make_record(**{"상태정보": "소멸"})
        ctx, _ = prepare([record])
        result = score_one(record, None, ctx)
        self.assertTrue(result["registered"])
        self.assertEqual(result["statusLabel"], "등록 후 소멸·포기")

    def test_export_uses_application_number(self):
        from primepatent.export import result_columns
        columns = result_columns()
        self.assertEqual(columns[1], "출원번호")
        self.assertIn("출원일", columns)
        self.assertIn("등록여부", columns)
        self.assertIn("등록번호", columns)
        self.assertIn("문헌번호", columns)      # 추적용으로 유지


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
            "claimBreadthScore": 9, "coreCentralityScore": "4",
            "claimExpansionScore": -3, "claimTypeDiversityScore": 2.5,
            "claimAnalysis": {"relatedClaimCount": 4, "totalClaimCount": 5,
                              "claimTypes": ["장치", "제조방법"], "linkageClaimed": 1},
            "keyFeatures": ["a"] * 20})
        self.assertEqual(result["claimBreadthScore"], 3.0)      # 상한 3
        self.assertEqual(result["coreCentralityScore"], 4.0)
        self.assertEqual(result["claimExpansionScore"], 0.0)    # 음수 → 0
        self.assertEqual(result["claimTypeDiversityScore"], 2.5)
        self.assertEqual(result["claimAnalysis"]["relatedClaimRatio"], 0.8)
        self.assertTrue(result["claimAnalysis"]["linkageClaimed"])
        self.assertEqual(len(result["keyFeatures"]), 8)

