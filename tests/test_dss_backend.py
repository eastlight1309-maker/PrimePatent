# -*- coding: utf-8 -*-
"""DSS Standard Webapp 기동 회귀 테스트.

DSS 는 [Python backend] 탭의 코드를 문자열로 exec 하므로
 - ``__file__`` 이 정의되지 않고
 - 전역 ``app`` 은 DSS 가 주입한다.
이 환경을 그대로 재현해 백엔드가 기동하는지 검증한다.
"""

import os
import shutil
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "python-lib"))

from flask import Flask  # noqa: E402

from primepatent.webapp_routes import (SEND_FILE_KWARG, AppState,  # noqa: E402
                                       _send_file_kwarg, register_routes)

BACKEND_SOURCE = os.path.join(BASE, "webapp", "backend.py")
TMP = os.path.join(BASE, "tmp", "dss")


def exec_backend(app, extra_env=None, with_lib=True):
    """DSS 와 동일하게 backend.py 를 exec 한다(__file__ 없음)."""
    with open(BACKEND_SOURCE, encoding="utf-8") as handle:
        source = handle.read()
    saved_env = dict(os.environ)
    saved_path = list(sys.path)
    try:
        if extra_env:
            os.environ.update(extra_env)
        if not with_lib:
            lib = os.path.join(BASE, "python-lib")
            sys.path[:] = [p for p in sys.path if os.path.abspath(p) != os.path.abspath(lib)]
            removed = {name: module for name, module in list(sys.modules.items())
                       if name == "primepatent" or name.startswith("primepatent.")}
            for name in removed:
                sys.modules.pop(name)
        namespace = {"app": app, "__name__": "__main__"}     # __file__ 없음
        exec(compile(source, "<dss-webapp-backend>", "exec"), namespace)
        return namespace
    finally:
        if not with_lib:
            sys.modules.update(removed)
        sys.path[:] = saved_path
        os.environ.clear()
        os.environ.update(saved_env)


class DssBackendStartupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(TMP, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_backend_starts_without_dunder_file(self):
        """회귀: __file__ 미정의 환경에서 NameError 로 죽지 않아야 한다."""
        app = Flask("dss_test")
        namespace = exec_backend(app, {"PRIMEPATENT_STORE": os.path.join(TMP, "store")})
        self.assertIsNotNone(namespace.get("state"), "백엔드가 정상 기동하지 못했습니다.")
        self.assertIsNone(namespace.get("_IMPORT_ERROR"))

        client = app.test_client()
        health = client.get("/api/health").get_json()
        self.assertTrue(health["ok"])
        self.assertEqual(health["degraded"], [])
        self.assertIsNone(health["storageError"])

    def test_registered_routes_available(self):
        app = Flask("dss_routes")
        exec_backend(app, {"PRIMEPATENT_STORE": os.path.join(TMP, "store2")})
        rules = {str(rule) for rule in app.url_map.iter_rules()}
        for expected in ("/api/health", "/api/upload", "/api/analyze", "/api/save",
                         "/api/runs", "/api/fields"):
            self.assertIn(expected, rules)

    def test_diagnostic_mode_when_library_missing(self):
        """라이브러리를 못 찾으면 조용히 죽지 말고 원인을 503 으로 알려야 한다."""
        app = Flask("dss_broken")
        namespace = exec_backend(app, {"PRIMEPATENT_LIB": ""}, with_lib=False)
        self.assertIsNone(namespace.get("state"))
        self.assertIsNotNone(namespace.get("_IMPORT_ERROR"))

        response = app.test_client().get("/api/health")
        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("python-lib", payload["error"])
        self.assertIn("ModuleNotFoundError", payload["detail"])

    def test_library_path_env_is_honored(self):
        app = Flask("dss_libpath")
        namespace = exec_backend(app, {"PRIMEPATENT_LIB": os.path.join(BASE, "python-lib"),
                                       "PRIMEPATENT_STORE": os.path.join(TMP, "store3")},
                                 with_lib=False)
        self.assertIsNotNone(namespace.get("state"))


class HealthDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask("health")
        self.state = AppState(local_root=os.path.join(TMP, "health_store"))
        register_routes(self.app, self.state)
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(os.path.join(TMP, "health_store"), ignore_errors=True)

    def test_environment_report(self):
        health = self.client.get("/api/health").get_json()
        environment = health["environment"]
        self.assertTrue(environment["python"])
        self.assertTrue(environment["flask"])
        self.assertIn(environment["sendFileKwarg"], ("download_name", "attachment_filename"))
        self.assertIsNotNone(environment["packages"]["pandas"])
        self.assertTrue(health["storageLocation"])

    def test_storage_failure_is_reported_not_fatal(self):
        """저장소가 죽어도 분석 기능은 살아 있어야 하고, 원인은 그대로 보여야 한다."""
        self.state.store = None
        self.state.storage_error = "PermissionError: 권한 없음"

        health = self.client.get("/api/health").get_json()
        self.assertEqual(health["storage"], "unavailable")
        self.assertIn("PermissionError", health["storageError"])
        self.assertTrue(any("저장소" in item for item in health["degraded"]))

        # 분석에 필요한 라우트는 계속 동작
        self.assertEqual(self.client.get("/api/fields").status_code, 200)

        # 저장소 의존 라우트는 원인을 담아 503
        for response in (self.client.get("/api/runs"),
                         self.client.post("/api/save", json={"jobId": "x", "department": "a",
                                                             "owner": "b", "project": "c"}),
                         self.client.delete("/api/runs/20260101_000000_aaaaaa"),
                         self.client.get("/api/runs/20260101_000000_aaaaaa/download"),
                         self.client.get("/api/runs/20260101_000000_aaaaaa/result")):
            self.assertEqual(response.status_code, 503)
            self.assertIn("PermissionError", response.get_json()["error"])

    def test_missing_run_still_404_when_storage_ok(self):
        response = self.client.get("/api/runs/20260101_000000_aaaaaa/result")
        self.assertEqual(response.status_code, 404)


class FlaskCompatTest(unittest.TestCase):
    def test_send_file_kwarg_detection(self):
        self.assertIn(SEND_FILE_KWARG, ("download_name", "attachment_filename"))
        self.assertEqual(_send_file_kwarg(), SEND_FILE_KWARG)

    def test_send_file_kwarg_for_legacy_flask(self):
        """Flask 1.x 시그니처(attachment_filename)를 올바로 인식하는지 확인."""
        import primepatent.webapp_routes as routes

        def legacy_send_file(path_or_file, mimetype=None, as_attachment=False,
                             attachment_filename=None):    # Flask 1.x 시그니처
            raise AssertionError("호출되지 않아야 함")

        original = routes.send_file
        try:
            routes.send_file = legacy_send_file
            self.assertEqual(routes._send_file_kwarg(), "attachment_filename")
        finally:
            routes.send_file = original
        self.assertEqual(routes._send_file_kwarg(), SEND_FILE_KWARG)

    def test_download_uses_rfc5987_header(self):
        response = None
        app = Flask("dl")
        state = AppState(local_root=os.path.join(TMP, "dl_store"))
        register_routes(app, state)
        payload = {"schemaVersion": 1, "summary": {}, "config": {}, "rows": [],
                   "meta": {"project": "한글 프로젝트"}}
        meta = state.store.save(payload, "부서", "이름", "한글 프로젝트")
        try:
            response = app.test_client().get("/api/runs/%s/download?format=csv" % meta["runId"])
            self.assertEqual(response.status_code, 200)
            disposition = response.headers["Content-Disposition"]
            self.assertIn("filename*=UTF-8''", disposition)
            self.assertTrue(disposition.split(";")[1].strip().startswith('filename="result.'))
        finally:
            shutil.rmtree(os.path.join(TMP, "dl_store"), ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
