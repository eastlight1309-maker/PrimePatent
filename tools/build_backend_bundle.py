# -*- coding: utf-8 -*-
"""DSS [Python backend] 탭에 붙여넣을 수 있는 단일 파일 번들 생성기.

DSS 프로젝트 라이브러리를 편집할 수 없거나, 20여 개 파일을 옮기기 어려운 경우
이 번들 하나만 붙여넣으면 primepatent 패키지 전체가 메모리에서 import 된다.

사용:
    python tools/build_backend_bundle.py            # dist/backend_bundle.py 생성
    python tools/build_backend_bundle.py --check    # 재생성 없이 최신 여부만 확인
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import zlib

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_DIR = os.path.join(BASE, "python-lib")
PACKAGE = "primepatent"
BACKEND = os.path.join(BASE, "webapp", "backend.py")
OUTPUT = os.path.join(BASE, "dist", "backend_bundle.py")

HEADER = '''# -*- coding: utf-8 -*-
# =============================================================================
#  PrimePatent - Dataiku Standard Webapp [Python backend] 단일 파일 번들
#  자동 생성 파일입니다. 직접 수정하지 마십시오.
#  재생성: python tools/build_backend_bundle.py
#  소스 해시: @@DIGEST@@
#  포함 모듈: @@COUNT@@개
#
#  [사용법] 이 파일 전체를 DSS 웹앱 편집기의 [Python backend] 탭에 붙여넣고 저장하십시오.
#           프로젝트 라이브러리(python-lib) 배치가 필요 없습니다.
#           관리 폴더를 쓰려면 아래 PRIMEPATENT_FOLDER_ID 에 폴더 ID 를 입력하십시오.
#  [주의]   코드환경에는 pandas / numpy / openpyxl / Flask 가 설치되어 있어야 합니다.
# =============================================================================

PRIMEPATENT_FOLDER_ID = ""      # 예: "PATENT_STORE" (비우면 서버 로컬 디렉터리 사용)

import base64 as _pp_base64
import importlib.abc as _pp_abc
import importlib.util as _pp_util
import json as _pp_json
import os as _pp_os
import sys as _pp_sys
import zlib as _pp_zlib

_PP_SOURCES = _pp_json.loads(
    _pp_zlib.decompress(_pp_base64.b64decode(_PP_BLOB)).decode("utf-8"))


class _PrimePatentBundleLoader(_pp_abc.MetaPathFinder, _pp_abc.Loader):
    """번들에 들어 있는 모듈을 sys.path 없이 import 할 수 있게 한다."""

    def find_spec(self, fullname, path=None, target=None):
        entry = _PP_SOURCES.get(fullname)
        if entry is None:
            return None
        return _pp_util.spec_from_loader(fullname, self, is_package=entry[0])

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        is_package, source = _PP_SOURCES[module.__name__]
        if is_package:
            module.__path__ = []
        module.__file__ = "<primepatent-bundle:%s>" % module.__name__
        exec(compile(source, module.__file__, "exec"), module.__dict__)


if not any(isinstance(finder, _PrimePatentBundleLoader) for finder in _pp_sys.meta_path):
    _pp_sys.meta_path.insert(0, _PrimePatentBundleLoader())

if PRIMEPATENT_FOLDER_ID:
    _pp_os.environ["PRIMEPATENT_FOLDER_ID"] = PRIMEPATENT_FOLDER_ID

# 번들에 포함된 backend.py 를 그대로 실행한다(로직 중복 없음).
# globals() 로 실행해야 DSS 가 주입한 전역 ``app`` 을 찾을 수 있다.
exec(compile(_PP_SOURCES["__backend__"][1], "<primepatent-bundle:backend>", "exec"),
     globals(), globals())
'''


def collect_sources():
    """{모듈명: [패키지여부, 소스]} + 백엔드 진입점."""
    sources = {}
    package_root = os.path.join(LIB_DIR, PACKAGE)
    if not os.path.isdir(package_root):
        raise SystemExit("패키지를 찾을 수 없습니다: %s" % package_root)

    for dirpath, _dirnames, filenames in os.walk(package_root):
        if "__pycache__" in dirpath:
            continue
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            full = os.path.join(dirpath, filename)
            relative = os.path.relpath(full, LIB_DIR).replace(os.sep, "/")
            parts = relative[:-3].split("/")          # ".py" 제거
            is_package = parts[-1] == "__init__"
            module = ".".join(parts[:-1] if is_package else parts)
            with open(full, encoding="utf-8") as handle:
                sources[module] = [is_package, handle.read()]

    with open(BACKEND, encoding="utf-8") as handle:
        sources["__backend__"] = [False, handle.read()]
    return sources


def render(sources) -> str:
    payload = json.dumps(sources, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:16]
    blob = base64.b64encode(zlib.compress(payload, 9)).decode("ascii")
    chunks = [blob[i:i + 100] for i in range(0, len(blob), 100)]
    literal = "_PP_BLOB = (\n" + "\n".join('    "%s"' % chunk for chunk in chunks) + "\n)\n"
    module_count = len([k for k in sources if k != "__backend__"])
    header = HEADER.replace("@@DIGEST@@", digest).replace("@@COUNT@@", str(module_count))
    # _PP_BLOB 정의를 사용 지점보다 앞에 둔다.
    marker = "PRIMEPATENT_FOLDER_ID = \"\""
    index = header.index(marker)
    return header[:index] + literal + "\n" + header[index:]


def main() -> int:
    parser = argparse.ArgumentParser(description="DSS 백엔드 단일 파일 번들 생성")
    parser.add_argument("--check", action="store_true", help="재생성 없이 최신 여부만 확인")
    parser.add_argument("--output", default=OUTPUT)
    args = parser.parse_args()

    content = render(collect_sources())
    if args.check:
        if not os.path.exists(args.output):
            print("번들이 없습니다: %s" % args.output)
            return 1
        with open(args.output, encoding="utf-8") as handle:
            current = handle.read()
        if current != content:
            print("번들이 소스와 다릅니다. python tools/build_backend_bundle.py 로 재생성하십시오.")
            return 1
        print("번들 최신 상태: %s" % args.output)
        return 0

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(content)
    print("생성 완료: %s (%.1f KB)" % (args.output, os.path.getsize(args.output) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
