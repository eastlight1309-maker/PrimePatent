# -*- coding: utf-8 -*-
"""단일 파일 번들(dist/backend_bundle.py) 회귀 테스트.

DSS 14.7.x 는 백엔드 코드를 ``exec(code, globals(), globals())`` 로 실행하며
프로젝트 라이브러리가 없으면 primepatent 를 import 할 수 없다.
번들은 그 상태에서도 동작해야 한다.
"""

import io
import os
import shutil
import subprocess
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(BASE, "dist", "backend_bundle.py")
TMP = os.path.join(BASE, "tmp", "bundle")

RUNNER = r'''
# primepatent 를 sys.path 어디에서도 찾을 수 없는 DSS 환경을 재현한다.
import json, os, sys
sys.path[:] = [p for p in sys.path
               if os.path.abspath(p) != os.path.abspath(%(lib)r)]
for name in [n for n in list(sys.modules) if n == "primepatent" or n.startswith("primepatent.")]:
    sys.modules.pop(name)
try:
    import primepatent
    print(json.dumps({"error": "사전 조건 실패: primepatent 가 여전히 import 됩니다."}))
    raise SystemExit(1)
except ImportError:
    pass

os.environ["PRIMEPATENT_STORE"] = %(store)r
from flask import Flask
app = Flask("dss_bundle")

with open(%(bundle)r, encoding="utf-8") as handle:
    code = handle.read()
# DSS 와 동일: 모듈 전역에서 exec
exec(compile(code, "<string>", "exec"), globals(), globals())

client = app.test_client()
health = client.get("/api/health").get_json()
rules = sorted(str(r) for r in app.url_map.iter_rules())
print(json.dumps({
    "ok": health.get("ok"),
    "storage": health.get("storage"),
    "degraded": health.get("degraded"),
    "modules": len([m for m in sys.modules if m.startswith("primepatent")]),
    "hasUpload": "/api/upload" in rules,
    "fields": len(client.get("/api/fields").get_json()["fields"]),
}, ensure_ascii=False))
'''


E2E_RUNNER = r'''
# 번들 백엔드로 업로드 → 분석 → 결과 → 저장까지 실제로 수행한다.
import io, json, os, sys, time
sys.path[:] = [p for p in sys.path
               if os.path.abspath(p) != os.path.abspath("@@LIB@@")]
for name in [n for n in list(sys.modules) if n == "primepatent" or n.startswith("primepatent.")]:
    sys.modules.pop(name)

os.environ["PRIMEPATENT_STORE"] = "@@STORE@@"
from flask import Flask
app = Flask("dss_bundle_e2e")
with open("@@BUNDLE@@", encoding="utf-8") as handle:
    exec(compile(handle.read(), "<string>", "exec"), globals(), globals())

client = app.test_client()

header = ("국가코드,발명의 명칭,요약,대표청구항,청구항 수,독립항 수,출원번호,출원일,"
          "최우선출원일,출원인,상태정보,WIPS패밀리 ID,WIPS패밀리 문헌번호(출원기준),"
          "피인용 문헌 수(F1),인용 문헌 수(B1),Current CPC All\n")
rows = []
for i in range(12):
    rows.append("KR,반도체 패키지 %d,하이브리드 본딩 구조,기판; 칩; 본딩부를 포함하는 패키지.,"
                "%d,2,KR10201900%04d,2019-03-04,2019-03-04,삼성전자(주),등록(존속),"
                "F%d,KR10201900%04d;US1699%04d,%d,%d,H01L23/00; H01L24/05\n"
                % (i, 10 + i, i, i, i, i, i * 3, 5 + i))
csv_bytes = (header + "".join(rows)).encode("utf-8-sig")

response = client.post("/api/upload",
                       data={"file": (io.BytesIO(csv_bytes), "wips.csv")},
                       content_type="multipart/form-data")
upload = response.get_json()["upload"]

started = client.post("/api/analyze", json={
    "uploadId": upload["uploadId"], "mapping": upload["mapping"],
    "config": {"topic_name": "첨단 패키징", "llm_enabled": False, "peer_min_size": 3,
               "as_of_date": "2026-08-25"}}).get_json()
job_id = started["job"]["id"]
for _ in range(200):
    job = client.get("/api/jobs/%s" % job_id).get_json()["job"]
    if job["status"] in ("done", "error", "cancelled"):
        break
    time.sleep(0.05)

result = client.get("/api/jobs/%s/result?limit=5" % job_id).get_json()
saved = client.post("/api/save", json={"jobId": job_id, "department": "IP전략팀",
                                       "owner": "홍길동", "project": "번들 검증"}).get_json()
run_id = saved["meta"]["runId"]
download = client.get("/api/runs/%s/download?format=xlsx" % run_id)
reloaded = client.get("/api/runs/%s/result?limit=3" % run_id).get_json()

print(json.dumps({
    "jobStatus": job["status"],
    "jobError": job.get("error"),
    "uploadRows": upload["meta"]["rowCount"],
    "total": result.get("total"),
    "topScore": result["rows"][0]["totalScore"] if result.get("rows") else None,
    "savedAt": saved["meta"]["savedAtDisplay"],
    "downloadStatus": download.status_code,
    "isXlsx": download.data[:2] == b"PK",
    "reloadedTotal": reloaded.get("total"),
}, ensure_ascii=False))
'''


class BundleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(TMP, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_bundle_is_up_to_date(self):
        """소스를 고친 뒤 번들 재생성을 잊지 않도록 강제한다."""
        result = subprocess.run(
            [sys.executable, os.path.join(BASE, "tools", "build_backend_bundle.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         "번들이 소스와 다릅니다. python tools/build_backend_bundle.py 실행 필요.\n"
                         + result.stdout + result.stderr)

    def test_bundle_starts_without_project_library(self):
        script = os.path.join(TMP, "runner.py")
        with io.open(script, "w", encoding="utf-8") as handle:
            handle.write(RUNNER % {"lib": os.path.join(BASE, "python-lib"),
                                   "bundle": BUNDLE,
                                   "store": os.path.join(TMP, "store")})
        result = subprocess.run([sys.executable, script], capture_output=True, text=True,
                                cwd=TMP)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        import json
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["degraded"], [])
        self.assertEqual(payload["storage"], "local")
        self.assertTrue(payload["hasUpload"])
        self.assertGreater(payload["modules"], 20)
        self.assertGreater(payload["fields"], 50)


    def test_bundle_runs_full_analysis(self):
        """번들만으로 업로드→분석→저장→다운로드→재조회가 동작해야 한다."""
        script = os.path.join(TMP, "e2e.py")
        with io.open(script, "w", encoding="utf-8") as handle:
            handle.write(E2E_RUNNER
                         .replace("@@LIB@@", os.path.join(BASE, "python-lib").replace("\\", "/"))
                         .replace("@@BUNDLE@@", BUNDLE.replace("\\", "/"))
                         .replace("@@STORE@@", os.path.join(TMP, "store_e2e").replace("\\", "/")))
        result = subprocess.run([sys.executable, script], capture_output=True, text=True,
                                cwd=TMP)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        import json
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(payload["jobStatus"], "done", payload.get("jobError"))
        self.assertEqual(payload["uploadRows"], 12)
        self.assertEqual(payload["total"], 12)
        self.assertGreater(payload["topScore"], 0)
        self.assertTrue(payload["savedAt"].endswith("(KST)"))
        self.assertEqual(payload["downloadStatus"], 200)
        self.assertTrue(payload["isXlsx"])
        self.assertEqual(payload["reloadedTotal"], 12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
