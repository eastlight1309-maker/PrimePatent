# -*- coding: utf-8 -*-
"""결과 저장소.

- Dataiku 환경: 관리 폴더(Managed Folder)를 저장소로 사용
- 로컬 환경: 파일시스템 디렉터리(.primepatent_store)

저장 단위(run)
    runs/<run_id>/meta.json     저장 메타(부서/이름/프로젝트명/저장시간 등)
    runs/<run_id>/result.json   분석 결과 payload 전체
    index.json                  목록 조회용 인덱스(메타만 보관)

동시성: 프로세스 내 RLock 으로 인덱스 갱신을 직렬화하고, 인덱스가 깨진 경우
run 디렉터리를 스캔해 복구한다(원격 폴더에서 원자적 rename 을 쓸 수 없기 때문).
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("primepatent.storage")

INDEX_PATH = "index.json"
RUNS_DIR = "runs"
KST = timezone(timedelta(hours=9))
_SAFE_RE = re.compile(r"[^0-9A-Za-z가-힣._\- ]+")
_ID_RE = re.compile(r"^[0-9A-Za-z_\-]+$")


class StorageError(Exception):
    """저장소 접근 실패."""


def now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def safe_name(value: Any, limit: int = 80) -> str:
    text = _SAFE_RE.sub("_", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" ._-")
    return text[:limit] or "untitled"


# ---------------------------------------------------------------- backends
class BaseBackend:
    kind = "base"

    def read(self, path: str) -> Optional[bytes]:
        raise NotImplementedError

    def write(self, path: str, data: bytes) -> None:
        raise NotImplementedError

    def delete_prefix(self, prefix: str) -> None:
        raise NotImplementedError

    def list_paths(self, prefix: str = "") -> List[str]:
        raise NotImplementedError

    def exists(self, path: str) -> bool:
        return self.read(path) is not None

    def local_path(self, path: str) -> Optional[str]:
        return None


class LocalBackend(BaseBackend):
    kind = "local"

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _full(self, path: str) -> str:
        clean = path.replace("\\", "/").lstrip("/")
        full = os.path.abspath(os.path.join(self.root, clean))
        if not (full == self.root or full.startswith(self.root + os.sep)):
            raise StorageError("허용되지 않은 경로입니다: %s" % path)
        return full

    def read(self, path: str) -> Optional[bytes]:
        full = self._full(path)
        if not os.path.exists(full):
            return None
        with open(full, "rb") as handle:
            return handle.read()

    def write(self, path: str, data: bytes) -> None:
        full = self._full(path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        temp = full + ".tmp"
        with open(temp, "wb") as handle:
            handle.write(data)
        os.replace(temp, full)

    def delete_prefix(self, prefix: str) -> None:
        full = self._full(prefix)
        if os.path.isdir(full):
            shutil.rmtree(full, ignore_errors=True)
        elif os.path.exists(full):
            os.remove(full)

    def list_paths(self, prefix: str = "") -> List[str]:
        base = self._full(prefix) if prefix else self.root
        if not os.path.isdir(base):
            return []
        found: List[str] = []
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                if name.endswith(".tmp"):
                    continue
                full = os.path.join(dirpath, name)
                found.append(os.path.relpath(full, self.root).replace(os.sep, "/"))
        return sorted(found)

    def local_path(self, path: str) -> Optional[str]:
        full = self._full(path)
        return full if os.path.exists(full) else None


class DataikuFolderBackend(BaseBackend):
    """Dataiku 관리 폴더 백엔드."""

    kind = "dataiku"

    def __init__(self, folder_id: str, project_key: Optional[str] = None):
        import dataiku  # noqa: WPS433
        self.folder = dataiku.Folder(folder_id, project_key=project_key) if project_key \
            else dataiku.Folder(folder_id)
        self.folder_id = folder_id

    @staticmethod
    def _norm(path: str) -> str:
        return "/" + path.replace("\\", "/").lstrip("/")

    def read(self, path: str) -> Optional[bytes]:
        target = self._norm(path)
        try:
            with self.folder.get_download_stream(target) as stream:
                return stream.read()
        except Exception:
            return None

    def write(self, path: str, data: bytes) -> None:
        try:
            self.folder.upload_stream(self._norm(path), io.BytesIO(data))
        except Exception as exc:
            raise StorageError("저장소 쓰기 실패(%s): %s" % (path, exc)) from exc

    def delete_prefix(self, prefix: str) -> None:
        target = self._norm(prefix).rstrip("/")
        for path in self.list_paths():
            normalized = self._norm(path)
            if normalized == target or normalized.startswith(target + "/"):
                try:
                    self.folder.delete_path(normalized)
                except Exception as exc:
                    logger.warning("저장소 삭제 실패(%s): %s", normalized, exc)

    def list_paths(self, prefix: str = "") -> List[str]:
        try:
            paths = self.folder.list_paths_in_partition()
        except Exception as exc:
            raise StorageError("저장소 목록 조회 실패: %s" % exc) from exc
        cleaned = [p.lstrip("/") for p in paths]
        if prefix:
            clean_prefix = prefix.lstrip("/")
            cleaned = [p for p in cleaned if p.startswith(clean_prefix)]
        return sorted(cleaned)


def make_backend(folder_id: Optional[str] = None, local_root: Optional[str] = None) -> BaseBackend:
    """환경에 맞는 백엔드를 만든다."""
    folder_id = folder_id or os.environ.get("PRIMEPATENT_FOLDER_ID")
    if folder_id:
        try:
            return DataikuFolderBackend(folder_id)
        except ImportError:
            logger.warning("dataiku 패키지가 없어 로컬 저장소를 사용합니다.")
        except Exception as exc:
            logger.warning("관리 폴더(%s) 연결 실패 → 로컬 저장소 사용: %s", folder_id, exc)
    root = local_root or os.environ.get("PRIMEPATENT_STORE") or \
        os.path.join(os.getcwd(), ".primepatent_store")
    return LocalBackend(root)


# ---------------------------------------------------------------- store
class ResultStore:
    """분석 결과 저장/조회."""

    def __init__(self, backend: Optional[BaseBackend] = None):
        self.backend = backend or make_backend()
        self._lock = threading.RLock()

    # --------------------------------------------------------- index
    def _load_index(self) -> List[Dict[str, Any]]:
        raw = self.backend.read(INDEX_PATH)
        if not raw:
            return []
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            logger.warning("인덱스 파손(%s) → run 디렉터리에서 재구성합니다.", exc)
            return self.rebuild_index()
        return data.get("runs", []) if isinstance(data, dict) else []

    def _save_index(self, runs: List[Dict[str, Any]]) -> None:
        payload = {"schemaVersion": 1, "updatedAt": now_iso(), "runs": runs}
        self.backend.write(INDEX_PATH,
                           json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8"))

    def rebuild_index(self) -> List[Dict[str, Any]]:
        """run 디렉터리를 스캔해 인덱스를 재구성한다."""
        runs: List[Dict[str, Any]] = []
        for path in self.backend.list_paths(RUNS_DIR):
            if not path.endswith("/meta.json"):
                continue
            raw = self.backend.read(path)
            if not raw:
                continue
            try:
                runs.append(json.loads(raw.decode("utf-8")))
            except (ValueError, UnicodeDecodeError):
                logger.warning("메타 파일 파손: %s", path)
        runs.sort(key=lambda m: m.get("savedAt", ""), reverse=True)
        with self._lock:
            self._save_index(runs)
        return runs

    # --------------------------------------------------------- CRUD
    def list_runs(self, department: str = "", owner: str = "", project: str = "",
                  keyword: str = "", limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            runs = self._load_index()
        def match(meta: Dict[str, Any]) -> bool:
            if department and department != meta.get("department"):
                return False
            if owner and owner != meta.get("owner"):
                return False
            if project and project != meta.get("project"):
                return False
            if keyword:
                blob = " ".join(str(meta.get(k, "")) for k in
                                ("project", "owner", "department", "title", "note", "sourceFile"))
                if keyword.lower() not in blob.lower():
                    return False
            return True
        return [m for m in runs if match(m)][:limit]

    def save(self, payload: Dict[str, Any], department: str, owner: str, project: str,
             title: str = "", note: str = "", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """분석 결과 1건 저장. 저장 시간은 서버에서 자동 기록한다."""
        if not str(department).strip():
            raise StorageError("부서를 입력하십시오.")
        if not str(owner).strip():
            raise StorageError("이름을 입력하십시오.")
        if not str(project).strip():
            raise StorageError("프로젝트명을 입력하십시오.")

        saved_at = datetime.now(KST)
        run_id = "%s_%s" % (saved_at.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:6])
        summary = payload.get("summary") or {}
        config = payload.get("config") or {}
        meta = {
            "runId": run_id,
            "department": str(department).strip(),
            "owner": str(owner).strip(),
            "project": str(project).strip(),
            "title": safe_name(title or project, 120),
            "note": str(note or "")[:1000],
            "savedAt": saved_at.isoformat(timespec="seconds"),
            "savedAtDisplay": saved_at.strftime("%Y-%m-%d %H:%M:%S (KST)"),
            "sourceFile": (payload.get("source") or {}).get("fileName", ""),
            "topicName": config.get("topic_name", ""),
            "llmId": config.get("llm_id", ""),
            "llmProvider": (summary.get("llm") or {}).get("provider", ""),
            "recordCount": summary.get("inputRecordCount"),
            "scoredCount": summary.get("scoredCount"),
            "gatePassedCount": summary.get("gatePassedCount"),
            "scoreAverage": summary.get("scoreAverage"),
            "scoreMax": summary.get("scoreMax"),
            "schemaVersion": payload.get("schemaVersion", 1),
        }
        if extra:
            meta.update({k: v for k, v in extra.items() if k not in meta})

        body = dict(payload)
        body["meta"] = meta
        prefix = "%s/%s" % (RUNS_DIR, run_id)
        self.backend.write("%s/result.json" % prefix,
                           json.dumps(body, ensure_ascii=False, default=str).encode("utf-8"))
        self.backend.write("%s/meta.json" % prefix,
                           json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8"))
        with self._lock:
            runs = self._load_index()
            runs = [m for m in runs if m.get("runId") != run_id]
            runs.insert(0, meta)
            self._save_index(runs)
        return meta

    def load(self, run_id: str) -> Dict[str, Any]:
        self._validate_id(run_id)
        raw = self.backend.read("%s/%s/result.json" % (RUNS_DIR, run_id))
        if raw is None:
            raise StorageError("저장된 결과를 찾을 수 없습니다: %s" % run_id)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise StorageError("저장 파일이 손상되었습니다: %s" % run_id) from exc

    def load_meta(self, run_id: str) -> Dict[str, Any]:
        self._validate_id(run_id)
        raw = self.backend.read("%s/%s/meta.json" % (RUNS_DIR, run_id))
        if raw is None:
            raise StorageError("저장된 결과를 찾을 수 없습니다: %s" % run_id)
        return json.loads(raw.decode("utf-8"))

    def delete(self, run_id: str) -> None:
        self._validate_id(run_id)
        self.backend.delete_prefix("%s/%s" % (RUNS_DIR, run_id))
        with self._lock:
            runs = [m for m in self._load_index() if m.get("runId") != run_id]
            self._save_index(runs)

    def put_artifact(self, run_id: str, name: str, data: bytes) -> str:
        """엑셀 등 파생 산출물 저장."""
        self._validate_id(run_id)
        path = "%s/%s/artifacts/%s" % (RUNS_DIR, run_id, safe_name(name, 120))
        self.backend.write(path, data)
        return path

    def get_artifact(self, run_id: str, name: str) -> Optional[bytes]:
        self._validate_id(run_id)
        return self.backend.read("%s/%s/artifacts/%s" % (RUNS_DIR, run_id, safe_name(name, 120)))

    def facets(self) -> Dict[str, List[str]]:
        runs = self.list_runs(limit=10000)
        return {
            "departments": sorted({m.get("department", "") for m in runs if m.get("department")}),
            "owners": sorted({m.get("owner", "") for m in runs if m.get("owner")}),
            "projects": sorted({m.get("project", "") for m in runs if m.get("project")}),
        }

    @staticmethod
    def _validate_id(run_id: str) -> None:
        if not run_id or not _ID_RE.match(str(run_id)):
            raise StorageError("잘못된 실행 ID 입니다: %s" % run_id)
