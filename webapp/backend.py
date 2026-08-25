# -*- coding: utf-8 -*-
"""Dataiku Standard Webapp 백엔드.

DSS 웹앱 편집기의 [Python backend] 탭에 이 파일 내용을 붙여넣거나,
프로젝트 라이브러리(python-lib)에 primepatent 패키지를 배치한 뒤 그대로 사용한다.
DSS 가 전역으로 제공하는 Flask 객체 ``app`` 에 라우트를 등록한다.

저장소(관리 폴더) 지정 방법 (우선순위)
 1) 아래 FOLDER_ID 상수에 관리 폴더 ID 직접 입력
 2) 환경변수 PRIMEPATENT_FOLDER_ID
 3) 둘 다 없으면 DSS 서버 로컬 디렉터리(.primepatent_store)
"""

import logging
import os
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("primepatent.backend")

# 프로젝트 라이브러리를 사용할 수 없는 경우를 대비한 경로 보강
for _candidate in (
    os.environ.get("PRIMEPATENT_LIB"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python-lib"),
):
    if _candidate and os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.insert(0, os.path.abspath(_candidate))

from primepatent.webapp_routes import AppState, register_routes  # noqa: E402

FOLDER_ID = ""          # 예: "PATENT_STORE" (관리 폴더 ID)

state = AppState(folder_id=FOLDER_ID or None)
register_routes(app, state)  # noqa: F821  # app: DSS 웹앱 백엔드가 주입하는 Flask 객체

logger.info("PrimePatent backend ready (storage=%s)", state.store.backend.kind)
