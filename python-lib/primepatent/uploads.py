# -*- coding: utf-8 -*-
"""업로드 파일 세션 관리.

업로드 파일은 임시 디렉터리에 보관하고 메모리에는 헤더/미리보기만 유지한다.
(대용량 엑셀을 세션마다 메모리에 들고 있지 않기 위함)
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from .ingest import IngestError, list_sheets, load_table
from .mapping import auto_map, mapping_report
from .storage import safe_name

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
        self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uploadId": self.id, "fileName": self.file_name, "sheet": self.sheet,
            "sheets": self.sheets, "headers": self.headers, "preview": self.preview,
            "meta": self.meta, "mapping": self.mapping, "mappingReport": self.report,
        }


class UploadStore:
    def __init__(self, root: Optional[str] = None, ttl_sec: int = DEFAULT_TTL_SEC):
        self.root = root or os.path.join(tempfile.gettempdir(), "primepatent_uploads")
        os.makedirs(self.root, exist_ok=True)
        self.ttl_sec = ttl_sec
        self._sessions: Dict[str, UploadSession] = {}
        self._lock = threading.RLock()

    def save_upload(self, file_storage, sheet: Optional[str] = None) -> UploadSession:
        """Flask FileStorage 를 저장하고 헤더/자동매핑을 계산한다."""
        name = safe_name(getattr(file_storage, "filename", "") or "upload", 120)
        extension = os.path.splitext(name)[1].lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise UploadError("지원하지 않는 파일 형식입니다(%s). xlsx/xls/csv 만 업로드할 수 있습니다."
                              % (extension or "확장자 없음"))

        self.cleanup()
        upload_id = uuid.uuid4().hex[:12]
        directory = os.path.join(self.root, upload_id)
        os.makedirs(directory, exist_ok=True)
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
