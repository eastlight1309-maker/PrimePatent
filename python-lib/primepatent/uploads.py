# -*- coding: utf-8 -*-
"""업로드 파일 세션 관리.

업로드 파일은 임시 디렉터리에 보관하고 메모리에는 헤더/미리보기만 유지한다.
(대용량 엑셀을 세션마다 메모리에 들고 있지 않기 위함)
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from .ingest import IngestError, list_sheets, load_table
from .mapping import auto_map, mapping_report
from .storage import StorageError, ensure_writable_dir, safe_name, temp_dir_candidates

logger = logging.getLogger("primepatent.uploads")

DEFAULT_TTL_SEC = 3600 * 4
PREVIEW_ROWS = 15
MAX_UPLOAD_BYTES = 200 * 1024 * 1024      # 200MB
MAX_ROWS = 50000
ALLOWED_EXTENSIONS = (".xlsx", ".xlsm", ".xls", ".csv", ".tsv")


class UploadError(Exception):
    """업로드 처리 실패."""


class UploadSession:
    def __init__(self, upload_id: str, path: str, file_name: str):
        self.id = upload_id
        self.path = path
        self.file_name = file_name
        self.sheet: Optional[str] = None
        self.sheets: List[str] = []
        self.headers: List[str] = []
        self.preview: List[Dict[str, Any]] = []
        self.meta: Dict[str, Any] = {}
        self.mapping: Dict[str, Dict] = {}
        self.report: Dict[str, Any] = {}
        # 출원인 표준화: 승인 전에는 approved=False 이며 분석에 반영되지 않는다.
        self.applicant_groups: List[Dict[str, Any]] = []
        self.applicant_map: Dict[str, str] = {}
        self.applicant_approved = False
        self.applicant_approved_at: Optional[str] = None
        self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uploadId": self.id, "fileName": self.file_name, "sheet": self.sheet,
            "sheets": self.sheets, "headers": self.headers, "preview": self.preview,
            "meta": self.meta, "mapping": self.mapping, "mappingReport": self.report,
            "applicant": self.applicant_state(),
        }

    def applicant_state(self) -> Dict[str, Any]:
        from .applicants import summarize
        state = summarize(self.applicant_groups)
        state.update({
            "approved": self.applicant_approved,
            "approvedAt": self.applicant_approved_at,
            "mappedNameCount": len(self.applicant_map),
            "loaded": bool(self.applicant_groups),
        })
        return state


class UploadStore:
    """업로드 임시 파일 보관소.

    임시 경로는 **계정별로 나뉜 이름**을 쓴다. 고정 이름(/tmp/primepatent_uploads)을
    쓰면 같은 서버의 다른 계정이 먼저 만들어 둔 디렉터리에 걸려
    하위 디렉터리 생성이 [Errno 13] Permission denied 로 실패한다.
    경로를 직접 지정하려면 환경변수 PRIMEPATENT_TMP 를 사용한다.
    """

    def __init__(self, root: Optional[str] = None, ttl_sec: int = DEFAULT_TTL_SEC):
        self._root_hint = root
        self._root: Optional[str] = None
        self.ttl_sec = ttl_sec
        self._sessions: Dict[str, UploadSession] = {}
        self._lock = threading.RLock()

    @property
    def root(self) -> str:
        """쓸 수 있는 임시 디렉터리(첫 사용 시점에 확보한다).

        웹앱 기동 시점에 확보하지 않는 이유: 임시 경로 문제로 백엔드 전체가
        기동하지 못하면 원인 화면조차 뜨지 않기 때문이다.
        """
        if self._root is None:
            self._root = self._resolve_root(self._root_hint)
            logger.info("업로드 임시 디렉터리: %s", self._root)
        return self._root

    @staticmethod
    def _resolve_root(root: Optional[str] = None) -> str:
        candidates: List[Optional[str]] = [root, os.environ.get("PRIMEPATENT_TMP")]
        candidates.extend(temp_dir_candidates("primepatent_uploads"))
        return ensure_writable_dir(candidates, purpose="업로드 임시 디렉터리")

    def describe(self) -> Dict[str, Any]:
        """진단용. 경로 확보에 실패해도 예외를 던지지 않는다(/api/health 에서 호출)."""
        try:
            return {"root": self.root, "error": None}
        except Exception as exc:
            return {"root": None, "error": "%s: %s" % (type(exc).__name__, exc)}

    def _new_upload_dir(self, upload_id: str) -> str:
        """업로드 1건용 디렉터리를 만든다.

        기동 후 디렉터리가 지워지거나(임시파일 청소) 권한이 바뀐 경우를 대비해
        **한 번만** 경로를 다시 확보하고 재시도한다. 그래도 실패하면 원인을 그대로 알린다.
        """
        try:
            directory = os.path.join(self.root, upload_id)
            os.makedirs(directory, mode=0o700, exist_ok=True)
            return directory
        except (OSError, StorageError) as first:
            logger.warning("업로드 디렉터리 생성 실패(%s) → 임시 경로를 다시 확보합니다.", first)
            self._root = None
            try:
                directory = os.path.join(self.root, upload_id)
                os.makedirs(directory, mode=0o700, exist_ok=True)
            except (OSError, StorageError) as exc:
                raise UploadError(
                    "업로드 임시 디렉터리를 만들 수 없습니다: %s\n"
                    "환경변수 PRIMEPATENT_TMP 에 쓰기 가능한 경로를 지정한 뒤 "
                    "웹앱을 다시 시작하십시오." % exc) from exc
            logger.info("업로드 임시 디렉터리를 %s 로 전환했습니다.", self._root)
            return directory

    def save_upload(self, file_storage, sheet: Optional[str] = None) -> UploadSession:
        """Flask FileStorage 를 저장하고 헤더/자동매핑을 계산한다."""
        name = safe_name(getattr(file_storage, "filename", "") or "upload", 120)
        extension = os.path.splitext(name)[1].lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise UploadError("지원하지 않는 파일 형식입니다(%s). xlsx/xls/csv 만 업로드할 수 있습니다."
                              % (extension or "확장자 없음"))

        self.cleanup()
        upload_id = uuid.uuid4().hex[:12]
        directory = self._new_upload_dir(upload_id)
        path = os.path.join(directory, name)
        try:
            file_storage.save(path)
        except Exception as exc:
            shutil.rmtree(directory, ignore_errors=True)
            raise UploadError("파일 저장 실패: %s" % exc) from exc

        size = os.path.getsize(path)
        if size == 0:
            shutil.rmtree(directory, ignore_errors=True)
            raise UploadError("빈 파일입니다.")
        if size > MAX_UPLOAD_BYTES:
            shutil.rmtree(directory, ignore_errors=True)
            raise UploadError("파일이 너무 큽니다(%.1fMB). 최대 %dMB 까지 업로드할 수 있습니다."
                              % (size / 1024 / 1024, MAX_UPLOAD_BYTES // 1024 // 1024))

        session = UploadSession(upload_id, path, name)
        try:
            session.sheets = list_sheets(path)
        except IngestError:
            session.sheets = []
        self.load_sheet(session, sheet)
        with self._lock:
            self._sessions[upload_id] = session
        return session

    def load_sheet(self, session: UploadSession, sheet: Optional[str] = None) -> UploadSession:
        try:
            headers, rows, meta = load_table(session.path, sheet, max_rows=MAX_ROWS)
        except IngestError as exc:
            raise UploadError(str(exc)) from exc
        session.sheet = meta.get("sheet") or sheet
        session.headers = headers
        session.meta = meta
        session.preview = [
            {k: _preview_value(v) for k, v in row.items()} for row in rows[:PREVIEW_ROWS]]
        session.mapping = auto_map(headers)
        session.report = mapping_report(headers, session.mapping)
        # 데이터가 바뀌었으므로 이전 표준화 승인은 무효화한다.
        session.applicant_groups = []
        session.applicant_map = {}
        session.applicant_approved = False
        session.applicant_approved_at = None
        if meta.get("truncated"):
            session.report.setdefault("warnings", []).append(
                "행 수가 %d 건을 초과하여 앞부분만 사용합니다." % MAX_ROWS)
        return session

    def get(self, upload_id: str) -> UploadSession:
        with self._lock:
            session = self._sessions.get(upload_id)
        if session is None:
            raise UploadError("업로드 세션이 만료되었거나 존재하지 않습니다. 파일을 다시 업로드하십시오.")
        if not os.path.exists(session.path):
            raise UploadError("업로드 파일이 삭제되었습니다. 다시 업로드하십시오.")
        return session

    def rows(self, session: UploadSession):
        headers, rows, meta = load_table(session.path, session.sheet, max_rows=MAX_ROWS)
        return headers, rows, meta

    def drop(self, upload_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(upload_id, None)
        if session is not None:
            shutil.rmtree(os.path.dirname(session.path), ignore_errors=True)

    def cleanup(self) -> None:
        now = time.time()
        with self._lock:
            expired = [sid for sid, s in self._sessions.items()
                       if now - s.created_at > self.ttl_sec]
        for upload_id in expired:
            self.drop(upload_id)


def _preview_value(value: Any) -> Any:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= 300 else text[:300] + "…"
