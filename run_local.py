# -*- coding: utf-8 -*-
"""로컬 standalone 실행 진입점.

Dataiku 없이 동일한 화면/기능을 브라우저에서 확인하기 위한 개발용 서버.
    python run_local.py --port 8088
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(BASE_DIR, "python-lib")
WEBAPP_DIR = os.path.join(BASE_DIR, "webapp")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

from flask import Flask, Response  # noqa: E402

from primepatent.webapp_routes import AppState, register_routes  # noqa: E402

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PrimePatent - 핵심특허 스코어링</title>
<style>html,body{margin:0;padding:0;height:100%%;background:#f5f6f8;}</style>
<style>%(css)s</style>
</head>
<body>
%(body)s
<script>%(js)s</script>
</body>
</html>"""


def read(name: str) -> str:
    with open(os.path.join(WEBAPP_DIR, name), "r", encoding="utf-8") as handle:
        return handle.read()


def create_app(store_root: str = None, folder_id: str = None) -> Flask:
    app = Flask(__name__)
    state = AppState(folder_id=folder_id, local_root=store_root)
    register_routes(app, state)

    @app.route("/favicon.ico", methods=["GET"])
    def favicon():
        return Response(status=204)

    @app.route("/", methods=["GET"])
    def index():
        # 개발 편의를 위해 요청 시마다 정적 파일을 다시 읽는다.
        page = PAGE_TEMPLATE % {"css": read("style.css"), "body": read("body.html"),
                                "js": read("script.js")}
        return Response(page, mimetype="text/html; charset=utf-8")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="PrimePatent 로컬 실행")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--store", default=os.path.join(BASE_DIR, ".primepatent_store"),
                        help="로컬 저장소 디렉터리")
    parser.add_argument("--folder-id", default=os.environ.get("PRIMEPATENT_FOLDER_ID"),
                        help="Dataiku 관리 폴더 ID(있으면 사용)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app(args.store, args.folder_id)
    print("PrimePatent → http://%s:%d" % (args.host, args.port))
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
