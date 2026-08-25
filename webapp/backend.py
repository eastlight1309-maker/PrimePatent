# -*- coding: utf-8 -*-
"""Dataiku Standard Webapp 백엔드.

DSS 웹앱 편집기의 [Python backend] 탭에 이 파일 내용을 그대로 붙여넣는다.
DSS 는 이 코드를 ``exec(code, globals(), globals())`` 로 **DSS 자신의 모듈 전역에서**
실행한다(dataiku/webapps/backend.py). 따라서
  - ``__file__`` 은 없거나, 있어도 **DSS 자신의 경로**를 가리킨다.
    → 이 값으로 프로젝트 경로를 유추하면 안 된다.
  - 프로젝트 라이브러리가 sys.path 에 없으면 import 가 실패한다.
    → 이때 조용히 죽지 말고 **어디를 찾아봤는지**까지 알려 주어야 한다.

primepatent 패키지를 찾는 순서
  1) 이미 sys.path 에 있음 (DSS 프로젝트 라이브러리 정상 배치 시)
  2) 환경변수 PRIMEPATENT_LIB
  3) $DIP_HOME/config/projects/<PROJECT_KEY>/lib/python   (프로젝트 라이브러리 실제 경로)
  4) $DIP_HOME/lib/python                                  (인스턴스 공용 라이브러리)
위 어디에도 없으면 dist/backend_bundle.py (단일 파일 번들) 사용을 권한다.

저장소(관리 폴더) 지정 방법 (우선순위)
 1) 아래 FOLDER_ID 상수에 관리 폴더 ID 직접 입력
 2) 환경변수 PRIMEPATENT_FOLDER_ID
 3) 둘 다 없으면 DSS 서버 로컬 디렉터리(.primepatent_store)
"""

import logging
import os
import sys
import traceback

FOLDER_ID = ""          # 예: "PATENT_STORE" (관리 폴더 ID). 비우면 로컬 디렉터리 사용

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("primepatent.backend")


def _project_key():
    """현재 프로젝트 키. 환경변수 → dataiku API 순으로 조회한다."""
    key = os.environ.get("DKU_CURRENT_PROJECT_KEY")
    if key:
        return key
    try:
        import dataiku
        return dataiku.default_project_key()
    except Exception:
        return None


def _library_candidates():
    """primepatent 패키지를 찾을 후보 경로 목록.

    ``__file__`` 은 DSS 자신의 경로를 가리키므로 사용하지 않는다.
    """
    candidates = [os.environ.get("PRIMEPATENT_LIB")]
    dip_home = os.environ.get("DIP_HOME")
    if dip_home:
        key = _project_key()
        if key:
            candidates.append(os.path.join(dip_home, "config", "projects", key, "lib", "python"))
        candidates.append(os.path.join(dip_home, "lib", "python"))
    return [c for c in candidates if c]


_SEARCHED = []
for _candidate in _library_candidates():
    _path = os.path.abspath(_candidate)
    _found = os.path.isdir(os.path.join(_path, "primepatent"))
    _SEARCHED.append("%s (%s)" % (_path, "패키지 있음" if _found else
                                  ("디렉터리 없음" if not os.path.isdir(_path) else "primepatent 없음")))
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

_IMPORT_ERROR = None
try:
    from primepatent.webapp_routes import AppState, register_routes
except Exception:                       # ImportError 외 의존 패키지 오류도 그대로 노출
    _IMPORT_ERROR = traceback.format_exc()
    logger.error("primepatent 라이브러리를 불러오지 못했습니다.\n%s", _IMPORT_ERROR)


def _diagnosis(detail):
    """실패 원인과 '어디를 찾아봤는지' 를 함께 담은 진단 정보."""
    return {
        "ok": False,
        "error": ("PrimePatent 라이브러리(primepatent)를 불러오지 못했습니다. "
                  "DSS 프로젝트 라이브러리의 python/ 폴더에 primepatent 패키지를 배치하거나, "
                  "dist/backend_bundle.py (단일 파일 번들)를 [Python backend] 탭에 붙여넣으십시오."),
        "detail": detail,
        "searchedPaths": _SEARCHED,
        "projectKey": _project_key(),
        "dipHome": os.environ.get("DIP_HOME"),
        "pythonExecutable": sys.executable,
        "sysPathHead": sys.path[:12],
    }


def _register_diagnostic_routes(flask_app, detail):
    """백엔드가 정상 기동하지 못했을 때, 원인을 화면·API 에서 확인할 수 있게 한다."""
    from flask import jsonify

    payload = _diagnosis(detail)

    def _fail():
        return jsonify(payload), 503

    for rule in ("/api/health", "/api/fields", "/api/runs", "/api/upload", "/api/analyze"):
        flask_app.add_url_rule(rule, "pp_diag_%s" % rule.strip("/").replace("/", "_"),
                               _fail, methods=["GET", "POST"])
    logger.error("PrimePatent 백엔드가 진단 모드로 기동했습니다. 탐색한 경로: %s",
                 " | ".join(_SEARCHED) or "(없음)")


state = None
if _IMPORT_ERROR:
    _register_diagnostic_routes(app, _IMPORT_ERROR)  # noqa: F821  # app: DSS 주입 Flask 객체
else:
    state = AppState(folder_id=FOLDER_ID or None)
    register_routes(app, state)  # noqa: F821
    logger.info("PrimePatent backend ready (%s)", state.describe())
