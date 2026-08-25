# -*- coding: utf-8 -*-
"""Dataiku Standard Webapp 백엔드.

DSS 웹앱 편집기의 [Python backend] 탭에 이 파일 내용을 그대로 붙여넣는다.
DSS 는 이 코드를 **문자열로 exec** 하므로 다음 두 가지를 전제할 수 없다.
  - ``__file__`` 이 정의되어 있다  (정의되지 않는다 → NameError 로 백엔드 기동 실패)
  - 모듈 import 가 항상 성공한다   (실패하면 모든 API 가 죽어 화면이 비어 보인다)
따라서 경로 보강은 ``__file__`` 없이 수행하고, 라이브러리 import 나 저장소 초기화가
실패하면 원인을 그대로 알려 주는 진단용 라우트를 대신 등록한다(오류를 숨기지 않는다).

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


def _library_candidates():
    """primepatent 패키지를 찾을 후보 경로.

    DSS 에서는 프로젝트 라이브러리(python-lib)가 자동으로 sys.path 에 포함되므로
    보통 추가 경로가 필요 없다. 아래는 그렇지 않은 배치를 위한 보조 경로이며,
    ``__file__`` 이 없을 수 있으므로 globals() 에서 안전하게 조회한다.
    """
    candidates = [os.environ.get("PRIMEPATENT_LIB")]
    here = globals().get("__file__")
    if here:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(here)), "..", "python-lib"))
    for name in ("DIP_HOME", "DKU_CURRENT_PROJECT_KEY"):
        base = os.environ.get(name)
        if name == "DIP_HOME" and base:
            candidates.append(os.path.join(base, "lib", "python"))
    return [c for c in candidates if c]


for _candidate in _library_candidates():
    _path = os.path.abspath(_candidate)
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

_IMPORT_ERROR = None
try:
    from primepatent.webapp_routes import AppState, register_routes
except Exception:                       # ImportError 외 의존 패키지 오류도 그대로 노출
    _IMPORT_ERROR = traceback.format_exc()
    logger.error("primepatent 라이브러리를 불러오지 못했습니다.\n%s", _IMPORT_ERROR)


def _register_diagnostic_routes(flask_app, detail):
    """백엔드가 정상 기동하지 못했을 때, 원인을 화면에서 확인할 수 있게 한다."""
    from flask import jsonify

    message = ("PrimePatent 라이브러리를 불러오지 못했습니다. "
               "DSS 프로젝트 라이브러리(python-lib)에 primepatent 패키지가 있는지, "
               "코드환경에 pandas/openpyxl/Flask 가 설치되어 있는지 확인하십시오.")

    def _fail():
        return jsonify({"ok": False, "error": message, "detail": detail}), 503

    for rule in ("/api/health", "/api/fields", "/api/runs", "/api/upload", "/api/analyze"):
        flask_app.add_url_rule(rule, "pp_diag_%s" % rule.strip("/").replace("/", "_"),
                               _fail, methods=["GET", "POST"])
    logger.error("PrimePatent 백엔드가 진단 모드로 기동했습니다.")


state = None
if _IMPORT_ERROR:
    _register_diagnostic_routes(app, _IMPORT_ERROR)  # noqa: F821  # app: DSS 주입 Flask 객체
else:
    state = AppState(folder_id=FOLDER_ID or None)
    register_routes(app, state)  # noqa: F821
    logger.info("PrimePatent backend ready (%s)", state.describe())
