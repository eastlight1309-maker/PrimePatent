# -*- coding: utf-8 -*-
"""경로/한글 인코딩/빈 데이터/중복 실행/저장소 예외 처리 테스트."""

import os
import shutil
import sys
import threading
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "python-lib"))

from primepatent.columns import normalize_header  # noqa: E402
from primepatent.config import ScoringConfig  # noqa: E402
from primepatent.ingest import IngestError, load_table  # noqa: E402
from primepatent.mapping import auto_map, mapping_report, resolve_mapping  # noqa: E402
from primepatent.parsing import to_bool, to_date, to_int, to_list  # noqa: E402
from primepatent.pipeline import run_analysis  # noqa: E402
from primepatent.storage import LocalBackend, ResultStore, StorageError  # noqa: E402

TMP = os.path.join(BASE, "tmp", "edge")


class ParsingTest(unittest.TestCase):
    def test_date_formats(self):
        for value in ("2019-03-04", "2019.03.04", "20190304", "2019/03/04"):
            self.assertEqual(to_date(value).isoformat(), "2019-03-04", value)
        self.assertEqual(to_date("2019-03").isoformat(), "2019-03-01")
        self.assertIsNone(to_date(""))
        self.assertIsNone(to_date("날짜없음"))
        self.assertEqual(to_date("2019-02-30").isoformat(), "2019-02-01")  # 잘못된 일자 보정

    def test_multi_value_split(self):
        self.assertEqual(to_list("A;B|C\nD"), ["A", "B", "C", "D"])
        self.assertEqual(to_list("삼성전자(주), LG전자"), ["삼성전자(주)", "LG전자"])
        self.assertEqual(to_list("KR10-2019-0001,234"), ["KR10-2019-0001,234"])  # 숫자 콤마 유지
        self.assertEqual(to_list(""), [])
        self.assertEqual(to_list(None), [])

    def test_bool_tokens(self):
        self.assertTrue(to_bool("Y"))
        self.assertFalse(to_bool("무"))
        self.assertTrue(to_bool("무효심판(2)"))       # 부정어 부분문자열 오판 방지
        self.assertIsNone(to_bool(""))
        self.assertIsNone(to_bool(None))

    def test_int_with_unit(self):
        self.assertEqual(to_int("12건"), 12)
        self.assertIsNone(to_int("-"))

    def test_header_normalization_strips_country_brackets(self):
        self.assertEqual(normalize_header("독립청구항[KR,JP,US,CN,EP,IN]"), "독립청구항")
        self.assertEqual(normalize_header(" 청 구 항 수 "), "청구항수")


class IngestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(TMP, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_cp949_csv(self):
        path = os.path.join(TMP, "한글_cp949.csv")
        with open(path, "w", encoding="cp949", newline="") as handle:
            handle.write("출원번호,발명의 명칭,청구항 수\n")
            handle.write("KR1020190001234,반도체 패키지 및 제조 방법,20\n")
        headers, rows, meta = load_table(path)
        self.assertEqual(meta["encoding"], "cp949")
        self.assertEqual(headers[1], "발명의 명칭")
        self.assertEqual(rows[0]["발명의 명칭"], "반도체 패키지 및 제조 방법")

    def test_utf8_bom_csv(self):
        path = os.path.join(TMP, "utf8.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            handle.write("출원번호,발명의 명칭\nKR1,반도체\n")
        headers, rows, _meta = load_table(path)
        self.assertEqual(headers[0], "출원번호")

    def test_empty_and_missing_file(self):
        empty = os.path.join(TMP, "empty.csv")
        open(empty, "w").close()
        with self.assertRaises(IngestError):
            load_table(empty)
        with self.assertRaises(IngestError):
            load_table(os.path.join(TMP, "없는파일.xlsx"))

    def test_header_only_file(self):
        path = os.path.join(TMP, "headeronly.csv")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("출원번호,발명의 명칭\n")
        with self.assertRaises(IngestError):
            load_table(path)

    def test_unsupported_extension(self):
        path = os.path.join(TMP, "doc.pdf")
        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.4")
        with self.assertRaises(IngestError):
            load_table(path)


class MappingTest(unittest.TestCase):
    HEADERS = ["출원번호", "발명의 명칭", "요약", "청구항 수",
               "독립항 수[KR,JP,US,CN,EP,IN]", "피인용 문헌 수(F1)", "인용 문헌 수(B1)",
               "상태정보[KR,JP,US,EP,CN,CA,AU]", "알 수 없는 컬럼"]

    def test_auto_map_distinguishes_similar_headers(self):
        mapping = auto_map(self.HEADERS)
        self.assertEqual(mapping["forwardCitationCount"]["column"], "피인용 문헌 수(F1)")
        self.assertEqual(mapping["backwardCitationCount"]["column"], "인용 문헌 수(B1)")
        self.assertEqual(mapping["independentClaimCount"]["column"],
                         "독립항 수[KR,JP,US,CN,EP,IN]")

    def test_unknown_column_reported(self):
        mapping = auto_map(self.HEADERS)
        report = mapping_report(self.HEADERS, mapping)
        self.assertIn("알 수 없는 컬럼", report["unmappedColumns"])
        self.assertTrue(report["ok"])

    def test_missing_required_blocks_run(self):
        headers = ["발명의 명칭", "요약"]
        report = mapping_report(headers, auto_map(headers))
        self.assertFalse(report["ok"])
        self.assertIn("출원번호", report["missingRequiredLabels"])

    def test_user_override_releases_conflicting_field(self):
        mapping = resolve_mapping(self.HEADERS, {"abstract": {"column": "발명의 명칭"}})
        self.assertEqual(mapping["abstract"]["column"], "발명의 명칭")
        self.assertNotIn("title", mapping)

    def test_explicit_none_clears_field(self):
        mapping = resolve_mapping(self.HEADERS, {"abstract": "__none__"})
        self.assertNotIn("abstract", mapping)


class PipelineEdgeTest(unittest.TestCase):
    def test_minimal_columns_still_scores(self):
        headers = ["출원번호", "발명의 명칭"]
        rows = [{"출원번호": "KR102019000%d" % i, "발명의 명칭": "반도체 패키지 %d" % i}
                for i in range(5)]
        payload = run_analysis(headers, rows, None,
                               ScoringConfig(topic_name="T", llm_enabled=False, peer_min_size=2))
        self.assertEqual(payload["summary"]["scoredCount"], 5)
        self.assertTrue(any("미매핑" in w for w in payload["warnings"]))
        for row in payload["rows"]:
            self.assertGreaterEqual(row["totalScore"], 0.0)
            self.assertLessEqual(row["totalScore"], 100.0)

    def test_empty_rows_raise(self):
        with self.assertRaises(ValueError):
            run_analysis(["출원번호"], [], None, ScoringConfig(llm_enabled=False))

    def test_missing_required_column_raises(self):
        with self.assertRaises(ValueError) as ctx:
            run_analysis(["발명의 명칭"], [{"발명의 명칭": "X"}], None,
                         ScoringConfig(llm_enabled=False))
        self.assertIn("필수", str(ctx.exception))

    def test_blank_cells_do_not_crash(self):
        headers = ["출원번호", "발명의 명칭", "청구항 수", "출원일", "피인용 문헌 수(F1)",
                   "상태정보", "WIPS패밀리 문헌번호(출원기준)"]
        rows = [
            {"출원번호": "KR1", "발명의 명칭": "", "청구항 수": "", "출원일": "",
             "피인용 문헌 수(F1)": "", "상태정보": "", "WIPS패밀리 문헌번호(출원기준)": ""},
            {"출원번호": "KR2", "발명의 명칭": None, "청구항 수": None, "출원일": None,
             "피인용 문헌 수(F1)": None, "상태정보": None, "WIPS패밀리 문헌번호(출원기준)": None},
        ]
        payload = run_analysis(headers, rows, None,
                               ScoringConfig(topic_name="T", llm_enabled=False, peer_min_size=2))
        self.assertEqual(payload["summary"]["scoredCount"], 2)


class StorageEdgeTest(unittest.TestCase):
    def setUp(self):
        self.root = os.path.join(TMP, "store")
        shutil.rmtree(self.root, ignore_errors=True)
        self.store = ResultStore(LocalBackend(self.root))
        self.payload = {"schemaVersion": 1, "summary": {"scoredCount": 1},
                        "config": {}, "rows": [{"key": "A"}]}

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_required_metadata(self):
        for args in (("", "이름", "P"), ("부서", "", "P"), ("부서", "이름", "")):
            with self.assertRaises(StorageError):
                self.store.save(self.payload, *args)

    def test_path_traversal_blocked(self):
        for bad in ("../etc", "a/b", "..", "run id"):
            with self.assertRaises(StorageError):
                self.store.load(bad)

    def test_korean_names_roundtrip(self):
        meta = self.store.save(self.payload, "반도체연구소 IP팀", "김철수", "2026 핵심특허 발굴")
        loaded = self.store.load(meta["runId"])
        self.assertEqual(loaded["meta"]["department"], "반도체연구소 IP팀")
        self.assertEqual(loaded["meta"]["project"], "2026 핵심특허 발굴")

    def test_concurrent_saves_all_indexed(self):
        errors = []

        def worker(index):
            try:
                self.store.save(self.payload, "부서", "사용자%d" % index, "프로젝트%d" % index)
            except Exception as exc:      # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.store.list_runs()), 8)

    def test_corrupt_index_is_rebuilt(self):
        meta = self.store.save(self.payload, "부서", "이름", "프로젝트")
        self.store.backend.write("index.json", b"{ broken json")
        runs = self.store.list_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["runId"], meta["runId"])

    def test_missing_run_raises(self):
        with self.assertRaises(StorageError):
            self.store.load("20260101_000000_abcdef")


if __name__ == "__main__":
    unittest.main(verbosity=2)
