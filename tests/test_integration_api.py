# -*- coding: utf-8 -*-
"""API 통합 테스트: 업로드 → 매핑 → 분석 → 결과 → 저장 → 재조회 → 다운로드."""

import io
import os
import shutil
import sys
import time
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "python-lib"))

import run_local  # noqa: E402
from tests.make_sample import write as write_sample  # noqa: E402

TMP = os.path.join(BASE, "tmp", "itest")


class ApiFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(TMP, exist_ok=True)
        cls.sample = write_sample(os.path.join(TMP, "wips.xlsx"), 90)
        cls.app = run_local.create_app(os.path.join(TMP, "store"))
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def _upload(self):
        with open(self.sample, "rb") as handle:
            data = {"file": (io.BytesIO(handle.read()), "wips.xlsx")}
            response = self.client.post("/api/upload", data=data,
                                        content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200, response.data[:400])
        return response.get_json()["upload"]

    def _run_job(self, upload, config=None, mapping=None):
        body = {"uploadId": upload["uploadId"], "mapping": mapping or upload["mapping"],
                "config": config or {"topic_name": "첨단 반도체 패키징",
                                     "topic_keywords": ["하이브리드 본딩", "TSV", "패키지"],
                                     "peer_min_size": 10, "as_of_date": "2026-08-25"}}
        response = self.client.post("/api/analyze", json=body)
        self.assertEqual(response.status_code, 200, response.data[:400])
        job_id = response.get_json()["job"]["id"]
        for _ in range(200):
            status = self.client.get("/api/jobs/%s" % job_id).get_json()["job"]
            if status["status"] in ("done", "error", "cancelled"):
                return job_id, status
            time.sleep(0.05)
        self.fail("작업이 제한 시간 내에 끝나지 않았습니다.")

    # ------------------------------------------------------------------
    def test_01_upload_and_automap(self):
        upload = self._upload()
        self.assertGreater(upload["meta"]["rowCount"], 50)
        self.assertTrue(upload["mappingReport"]["ok"], upload["mappingReport"])
        self.assertIn("applicationNumber", upload["mapping"])
        self.assertIn("forwardCitationCount", upload["mapping"])
        self.assertEqual(len(upload["preview"]), 15)

    def test_02_mapping_override(self):
        upload = self._upload()
        override = {"title": {"column": "요약"}}
        response = self.client.post("/api/upload/%s/mapping" % upload["uploadId"],
                                    json={"mapping": override})
        payload = response.get_json()
        self.assertEqual(payload["mapping"]["title"]["column"], "요약")
        self.assertEqual(payload["mapping"]["title"]["method"], "manual")
        # 요약 컬럼을 title 이 가져갔으므로 abstract 는 해제되어야 한다
        self.assertNotIn("abstract", payload["mapping"])

    def test_03_analyze_and_result(self):
        upload = self._upload()
        job_id, status = self._run_job(upload)
        self.assertEqual(status["status"], "done", status.get("error"))

        result = self.client.get("/api/jobs/%s/result?limit=10" % job_id).get_json()
        self.assertTrue(result["ok"])
        self.assertGreater(result["total"], 0)
        self.assertEqual(len(result["rows"]), 10)

        first = result["rows"][0]
        self.assertGreaterEqual(first["totalScore"], result["rows"][-1]["totalScore"])
        for key in ("rights", "tech", "market", "impact"):
            self.assertIn(key, first["areaScores"])

        detail = self.client.get("/api/jobs/%s/row/%s" % (job_id, first["key"])).get_json()["row"]
        component_total = sum(
            component["score"]
            for area in detail["areas"].values()
            for component in area["components"])
        self.assertAlmostEqual(component_total, detail["totalScore"], places=1)
        self.assertAlmostEqual(detail["quantScore"] + detail["llmScore"],
                               detail["totalScore"], places=1)
        from primepatent.config import TOTAL_MAX
        self.assertAlmostEqual(detail["quantMax"] + detail["llmMax"], TOTAL_MAX, places=1)

    def test_04_filters_and_paging(self):
        upload = self._upload()
        job_id, _ = self._run_job(upload)
        base = "/api/jobs/%s/result" % job_id
        total = self.client.get(base + "?limit=1").get_json()["total"]

        page1 = self.client.get(base + "?limit=5&offset=0").get_json()["rows"]
        page2 = self.client.get(base + "?limit=5&offset=5").get_json()["rows"]
        self.assertNotEqual([r["key"] for r in page1], [r["key"] for r in page2])

        desc = self.client.get(base + "?limit=5&sort=totalScore&order=desc").get_json()["rows"]
        self.assertGreaterEqual(desc[0]["totalScore"], desc[-1]["totalScore"])

        graded = self.client.get(base + "?limit=500&grade=A").get_json()
        self.assertTrue(all(r["grade"] == "A" for r in graded["rows"]))
        self.assertLessEqual(graded["total"], total)

        searched = self.client.get(base + "?limit=500&q=KR").get_json()
        self.assertTrue(all("KR" in (r["docNumber"] or "") or "KR" in (r["title"] or "")
                            for r in searched["rows"]))

    def test_05_save_reload_download(self):
        upload = self._upload()
        job_id, _ = self._run_job(upload)

        bad = self.client.post("/api/save", json={"jobId": job_id, "department": "",
                                                  "owner": "홍길동", "project": "P"})
        self.assertEqual(bad.status_code, 400)

        saved = self.client.post("/api/save", json={
            "jobId": job_id, "department": "IP전략팀", "owner": "홍길동",
            "project": "2026 첨단패키징 핵심특허", "note": "1차 스크리닝"})
        self.assertEqual(saved.status_code, 200, saved.data[:300])
        meta = saved.get_json()["meta"]
        self.assertTrue(meta["savedAt"])
        self.assertTrue(meta["savedAtDisplay"].endswith("(KST)"))

        runs = self.client.get("/api/runs").get_json()
        self.assertEqual(len(runs["runs"]), 1)
        self.assertIn("IP전략팀", runs["facets"]["departments"])

        filtered = self.client.get("/api/runs?department=없는팀").get_json()
        self.assertEqual(filtered["runs"], [])

        reloaded = self.client.get("/api/runs/%s/result?limit=5" % meta["runId"]).get_json()
        self.assertEqual(reloaded["meta"]["owner"], "홍길동")
        self.assertGreater(reloaded["total"], 0)

        xlsx = self.client.get("/api/runs/%s/download?format=xlsx" % meta["runId"])
        self.assertEqual(xlsx.status_code, 200)
        self.assertEqual(xlsx.data[:2], b"PK")
        self.assertIn("filename*=UTF-8''", xlsx.headers["Content-Disposition"])

        csv_response = self.client.get("/api/runs/%s/download?format=csv" % meta["runId"])
        self.assertEqual(csv_response.status_code, 200)
        self.assertTrue(csv_response.data.startswith(b"\xef\xbb\xbf"))  # 엑셀 호환 BOM

        job_xlsx = self.client.get("/api/jobs/%s/download?format=xlsx" % job_id)
        self.assertEqual(job_xlsx.status_code, 200)

        self.assertEqual(self.client.delete("/api/runs/%s" % meta["runId"]).status_code, 200)
        self.assertEqual(self.client.get("/api/runs").get_json()["runs"], [])

    def test_055_applicant_standardization(self):
        """승인 전에는 원본 표기, 승인 후에는 표준명이 반영되어야 한다."""
        upload = self._upload()
        self.assertFalse(upload["applicant"]["approved"])
        self.assertFalse(upload["applicant"]["loaded"])

        built = self.client.post("/api/upload/%s/applicants" % upload["uploadId"],
                                 json={"mapping": upload["mapping"]})
        self.assertEqual(built.status_code, 200, built.data[:300])
        groups = built.get_json()["groups"]
        self.assertTrue(groups)
        self.assertTrue(any(g["variantCount"] >= 1 for g in groups))

        # 승인 전 분석 → 표준화 미적용
        job_id, _status = self._run_job(upload)
        before = self.client.get("/api/jobs/%s/result?limit=500" % job_id).get_json()
        self.assertTrue(any("승인되지 않아" in w for w in before["warnings"]))

        # 표준명을 바꿔 승인(병합 그룹은 그룹별 승인이 필요하다)
        for group in groups:
            group["standardName"] = "표준_" + group["standardName"]
            group["approved"] = True
        approved = self.client.post("/api/upload/%s/applicants/approve" % upload["uploadId"],
                                    json={"groups": groups})
        self.assertEqual(approved.status_code, 200, approved.data[:300])
        state = approved.get_json()["state"]
        self.assertTrue(state["approved"])
        self.assertTrue(state["approvedAt"])

        job_id2, _ = self._run_job(upload)
        after = self.client.get("/api/jobs/%s/result?limit=500" % job_id2).get_json()
        self.assertTrue(any("표준화를 적용했습니다" in w for w in after["warnings"]))
        self.assertTrue(all(str(row["applicant"]).startswith("표준_") for row in after["rows"]),
                        sorted({row["applicant"] for row in after["rows"]})[:5])

        # 승인 해제
        reset = self.client.post("/api/upload/%s/applicants/reset" % upload["uploadId"]).get_json()
        self.assertFalse(reset["state"]["approved"])

    def test_056_applicant_validation(self):
        upload = self._upload()
        self.client.post("/api/upload/%s/applicants" % upload["uploadId"],
                         json={"mapping": upload["mapping"]})
        empty = self.client.post("/api/upload/%s/applicants/approve" % upload["uploadId"],
                                 json={"groups": []})
        self.assertEqual(empty.status_code, 400)
        blank = self.client.post("/api/upload/%s/applicants/approve" % upload["uploadId"],
                                 json={"groups": [{"groupId": "g0", "standardName": "  ",
                                                   "variants": [{"raw": "A", "count": 1}]}]})
        self.assertEqual(blank.status_code, 400)
        self.assertIn("표준명", blank.get_json()["error"])

        # 출원인 컬럼을 비우면 안내 메시지
        no_applicant = {k: v for k, v in upload["mapping"].items()
                        if k not in ("applicant", "applicantNormalized")}
        no_applicant["applicant"] = "__none__"
        no_applicant["applicantNormalized"] = "__none__"
        response = self.client.post("/api/upload/%s/applicants" % upload["uploadId"],
                                    json={"mapping": no_applicant})
        self.assertEqual(response.status_code, 400)
        self.assertIn("출원인", response.get_json()["error"])

    def test_06_error_paths(self):
        self.assertEqual(self.client.post("/api/upload", data={}).status_code, 400)
        self.assertEqual(self.client.get("/api/jobs/deadbeef").status_code, 404)
        self.assertEqual(self.client.get("/api/runs/does_not_exist/result").status_code, 404)
        self.assertEqual(self.client.post("/api/analyze", json={}).status_code, 400)
        self.assertEqual(self.client.get("/api/nope").status_code, 404)

        data = {"file": (io.BytesIO(b"not an excel"), "bad.txt")}
        response = self.client.post("/api/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)
        self.assertIn("지원하지 않는", response.get_json()["error"])

    def test_07_cancel(self):
        upload = self._upload()
        response = self.client.post("/api/analyze", json={
            "uploadId": upload["uploadId"], "mapping": upload["mapping"],
            "config": {"topic_name": "T", "peer_min_size": 10}})
        job_id = response.get_json()["job"]["id"]
        self.client.post("/api/jobs/%s/cancel" % job_id)
        for _ in range(100):
            status = self.client.get("/api/jobs/%s" % job_id).get_json()["job"]
            if status["status"] in ("done", "cancelled", "error"):
                break
            time.sleep(0.05)
        self.assertIn(status["status"], ("cancelled", "done"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
