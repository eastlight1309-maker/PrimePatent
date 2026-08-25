# -*- coding: utf-8 -*-
"""백그라운드 작업 관리자.

웹 UI 가 멈추지 않도록 분석은 워커 스레드에서 실행하고,
프론트엔드는 /api/jobs/<id> 폴링으로 진행률을 표시한다(취소 지원).
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("primepatent.jobs")

PENDING = "pending"
RUNNING = "running"
DONE = "done"
ERROR = "error"
CANCELLED = "cancelled"

DEFAULT_TTL_SEC = 3600 * 6
MAX_JOBS = 50


class Job:
    def __init__(self, job_id: str, kind: str, label: str = ""):
        self.id = job_id
        self.kind = kind
        self.label = label
        self.status = PENDING
        self.phase = ""
        self.message = "대기 중"
        self.progress = 0.0
        self.result: Optional[Any] = None
        self.error: Optional[str] = None
        self.traceback: Optional[str] = None
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.finished_at: Optional[float] = None
        self.cancel_event = threading.Event()
        self._lock = threading.RLock()

    def update(self, phase: str, progress: float, message: str) -> None:
        with self._lock:
            self.phase = phase
            self.progress = max(0.0, min(1.0, float(progress)))
            self.message = message
            self.updated_at = time.time()

    def cancel(self) -> None:
        self.cancel_event.set()
        with self._lock:
            if self.status in (PENDING, RUNNING):
                self.message = "취소 요청됨"
                self.updated_at = time.time()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def to_dict(self, include_result: bool = False) -> Dict[str, Any]:
        with self._lock:
            payload = {
                "id": self.id, "kind": self.kind, "label": self.label,
                "status": self.status, "phase": self.phase,
                "progress": round(self.progress, 4), "message": self.message,
                "error": self.error,
                "createdAt": self.created_at, "updatedAt": self.updated_at,
                "finishedAt": self.finished_at,
                "elapsedSec": round((self.finished_at or time.time()) - self.created_at, 1),
                "cancelRequested": self.cancelled,
            }
            if include_result:
                payload["result"] = self.result
            return payload


class JobManager:
    def __init__(self, ttl_sec: int = DEFAULT_TTL_SEC, max_jobs: int = MAX_JOBS):
        self.ttl_sec = ttl_sec
        self.max_jobs = max_jobs
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.RLock()

    def submit(self, kind: str, target: Callable[[Job], Any], label: str = "") -> Job:
        """target(job) 을 워커 스레드에서 실행한다."""
        self._cleanup()
        job = Job(uuid.uuid4().hex[:12], kind, label)
        with self._lock:
            self._jobs[job.id] = job

        def runner() -> None:
            job.status = RUNNING
            job.message = "실행 중"
            try:
                result = target(job)
                if job.cancelled:
                    job.status = CANCELLED
                    job.message = "취소되었습니다."
                else:
                    job.result = result
                    job.status = DONE
                    job.progress = 1.0
                    job.message = "완료"
            except Exception as exc:  # 작업 실패는 상태로만 보고하고 서버는 유지
                if job.cancelled:
                    job.status = CANCELLED
                    job.message = "취소되었습니다."
                else:
                    job.status = ERROR
                    job.error = "%s: %s" % (type(exc).__name__, exc)
                    job.traceback = traceback.format_exc()
                    job.message = job.error
                    logger.exception("작업 실패(%s/%s)", kind, job.id)
            finally:
                job.finished_at = time.time()
                job.updated_at = job.finished_at

        thread = threading.Thread(target=runner, name="primepatent-%s-%s" % (kind, job.id),
                                  daemon=True)
        thread.start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None:
            return False
        job.cancel()
        return True

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())
        return [j.to_dict() for j in sorted(jobs, key=lambda j: -j.created_at)]

    def _cleanup(self) -> None:
        now = time.time()
        with self._lock:
            expired = [
                job_id for job_id, job in self._jobs.items()
                if job.finished_at and now - job.finished_at > self.ttl_sec
            ]
            for job_id in expired:
                self._jobs.pop(job_id, None)
            if len(self._jobs) > self.max_jobs:
                finished = sorted(
                    (j for j in self._jobs.values() if j.finished_at),
                    key=lambda j: j.finished_at or 0)
                for job in finished[:len(self._jobs) - self.max_jobs]:
                    self._jobs.pop(job.id, None)
