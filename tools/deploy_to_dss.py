# -*- coding: utf-8 -*-
"""python-lib/primepatent 패키지를 DSS 프로젝트 라이브러리에 업로드한다.

DSS 화면에서 파일을 하나씩 만들지 않고 API 로 한 번에 배치하기 위한 도구.
기본은 dry-run 이며, 실제 업로드는 --apply 를 붙여야 수행한다.

    export DSS_URL=https://dss.example.com
    export DSS_API_KEY=<개인 API 키>
    python tools/deploy_to_dss.py --project PRIMEPATENT            # 미리보기
    python tools/deploy_to_dss.py --project PRIMEPATENT --apply    # 실제 업로드

주의: 이 스크립트는 실제 DSS 인스턴스 대상으로 검증되지 않았습니다(개발 환경에 DSS 없음).
      먼저 dry-run 으로 대상 파일 목록을 확인한 뒤 --apply 하십시오.
      업로드가 여의치 않으면 dist/backend_bundle.py 를 붙여넣는 방법을 사용하십시오.
"""

from __future__ import annotations

import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_DIR = os.path.join(BASE, "python-lib")
PACKAGE = "primepatent"


def collect_files():
    """(라이브러리 내 상대경로, 로컬 절대경로) 목록."""
    root = os.path.join(LIB_DIR, PACKAGE)
    if not os.path.isdir(root):
        raise SystemExit("패키지를 찾을 수 없습니다: %s" % root)
    files = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            full = os.path.join(dirpath, filename)
            relative = os.path.relpath(full, LIB_DIR).replace(os.sep, "/")
            files.append(("python/" + relative, full))
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description="DSS 프로젝트 라이브러리에 primepatent 업로드")
    parser.add_argument("--project", required=True, help="DSS 프로젝트 키 (예: PRIMEPATENT)")
    parser.add_argument("--url", default=os.environ.get("DSS_URL"))
    parser.add_argument("--api-key", default=os.environ.get("DSS_API_KEY"))
    parser.add_argument("--apply", action="store_true", help="실제 업로드 수행")
    args = parser.parse_args()

    files = collect_files()
    total = sum(os.path.getsize(path) for _, path in files)
    print("업로드 대상: %d개 파일 (%.1f KB) → 프로젝트 %s 의 라이브러리"
          % (len(files), total / 1024.0, args.project))
    for relative, _path in files:
        print("  %s" % relative)

    if not args.apply:
        print("\n[dry-run] 실제 업로드하려면 --apply 를 추가하십시오.")
        return 0

    if not args.url or not args.api_key:
        print("\nDSS_URL 과 DSS_API_KEY (또는 --url/--api-key)가 필요합니다.", file=sys.stderr)
        return 2

    try:
        import dataikuapi
    except ImportError:
        print("\ndataikuapi 패키지가 필요합니다: pip install dataiku-api-client", file=sys.stderr)
        return 2

    client = dataikuapi.DSSClient(args.url, args.api_key)
    project = client.get_project(args.project)
    library = project.get_library()

    for relative, path in files:
        with open(path, "rb") as handle:
            content = handle.read()
        library.add_file(relative, content)
        print("업로드: %s" % relative)

    print("\n완료. DSS 웹앱을 재시작한 뒤 /api/health 로 상태를 확인하십시오.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
