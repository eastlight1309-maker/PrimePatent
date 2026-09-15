# -*- coding: utf-8 -*-
"""Flask 라우트 정의.

Dataiku Standard Webapp 의 backend.py 와 로컬 standalone 실행이
동일한 라우트를 공유한다.
"""

from __future__ import annotations

import inspect
import io
import json
import logging
import platform
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from flask import jsonify, request, send_file

from .applicants import build_name_map, cluster_applicants, collect_applicants
from .columns import field_catalog
from .config import (ALLOWED_LLM_CANDIDATES, ALLOWED_LLM_IDS, AREA_MAX, AREA_ORDER,
                     COMPONENT_MAX, DEFAULT_LLM_ID, TOTAL_MAX, ScoringConfig)
from .export import export_bytes, export_filename
from .guide import build_guide
from .jobs import DONE, JobManager
from .llm.analyzer import LLMCache
from .llm.client import probe_client
from .mapping import resolve_mapping
from .pipeline import PipelineCancelled, run_analysis
from .storage import ResultStore, StorageError, make_backend
from .uploads import UploadError, UploadStore

logger = logging.getLogger("primepatent.webapp")

MAX_ROWS_PER_PAGE = 500
SLIM_KEYS = (
    "key", "rank", "applicationNumber", "applicationDateText", "docNumber",
    "publicationNumber", "registrationNumber", "registered", "registrationLabel",
    "country", "title", "applicant",
    "currentAssignee", "statusLabel", "statusCode", "priorityDate", "priorityYear",
    "applicationDate", "registrationDate", "totalScore", "totalMax", "quantScore",
    "llmScore", "grade", "areaScores", "reviewRoute", "familyCountries",
    "familyMemberCount", "forwardCitations", "backwardCitations", "claimCount",
    "independentClaimCount", "cpcMain", "detailLink", "percentile", "isRepresentative",
)


class AppState:
    """웹앱 전역 상태(업로드/작업/저장소).

    저장소 초기화가 실패해도 백엔드 전체가 죽지 않도록 오류를 보관하고,
    ``/api/health`` 와 저장 관련 API 에서 **원인을 그대로** 알려 준다.
    (오류를 숨기는 것이 아니라, 나머지 기능은 살린 채 원인을 화면에 노출한다.)
    """

    def __init__(self, folder_id: Optional[str] = None, local_root: Optional[str] = None):
        self.jobs = JobManager()
        # 임시 디렉터리는 첫 업로드 때 확보한다(UploadStore.root).
        # 기동 시점에 확보하면 임시 경로 문제로 백엔드 전체가 뜨지 못한다.
        self.uploads = UploadStore()
        self.llm_cache = LLMCache()
        self.folder_id = folder_id
        self.local_root = local_root
        self.store: Optional[ResultStore] = None
        self.storage_error: Optional[str] = None
        self.init_storage()

    def init_storage(self) -> Optional[ResultStore]:
        try:
            self.store = ResultStore(make_backend(self.folder_id, self.local_root))
            self.storage_error = None
        except Exception as exc:
            self.store = None
            self.storage_error = "%s: %s" % (type(exc).__name__, exc)
            logger.error("저장소 초기화 실패: %s", self.storage_error)
        return self.store

    def describe(self) -> str:
        if self.store is None:
            return "storage=ERROR(%s)" % self.storage_error
        return "storage=%s at %s" % (self.store.backend.kind,
                                     self.store.backend.describe().get("location"))


def _error(message: str, code: int = 400):
    return jsonify({"ok": False, "error": message}), code


def _store_or_error(state: "AppState"):
    """(store, error_response) - 저장소를 쓸 수 없으면 원인을 담은 응답을 돌려준다."""
    if state.store is not None:
        return state.store, None
    return None, _error(
        "결과 저장소를 사용할 수 없습니다: %s\n"
        "관리 폴더 ID(FOLDER_ID) 또는 저장 디렉터리 권한을 확인한 뒤 웹앱을 다시 시작하십시오."
        % (state.storage_error or "원인 미상"), 503)


def _json_body() -> Dict[str, Any]:
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        return body
    if request.form:
        raw = request.form.get("payload")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except ValueError:
                pass
        return {k: v for k, v in request.form.items()}
    return {}


def _slim_row(row: Dict[str, Any]) -> Dict[str, Any]:
    slim = {key: row.get(key) for key in SLIM_KEYS}
    slim["gate"] = row.get("gate")
    slim["llmStatus"] = (row.get("llm") or {}).get("status")
    slim["llmProvider"] = (row.get("llm") or {}).get("provider")
    slim["hasNotes"] = bool(row.get("notes"))
    return slim


def _paginate(rows: List[Dict[str, Any]], args) -> Tuple[List[Dict[str, Any]], int]:
    keyword = (args.get("q") or "").strip().lower()
    grade = (args.get("grade") or "").strip()
    route = (args.get("route") or "").strip()
    gate = (args.get("gate") or "").strip()
    country = (args.get("country") or "").strip().upper()

    filtered = rows
    if keyword:
        def hit(row: Dict[str, Any]) -> bool:
            blob = " ".join(str(row.get(k) or "") for k in
                            ("applicationNumber", "docNumber", "publicationNumber",
                             "registrationNumber", "title", "applicant",
                             "currentAssignee", "cpcMain"))
            return keyword in blob.lower()
        filtered = [r for r in filtered if hit(r)]
    if grade:
        filtered = [r for r in filtered if r.get("grade") == grade]
    if route:
        filtered = [r for r in filtered if r.get("reviewRoute") == route]
    if country:
        filtered = [r for r in filtered if (r.get("country") or "").upper() == country]
    if gate == "pass":
        filtered = [r for r in filtered if (r.get("gate") or {}).get("passed")]
    elif gate == "fail":
        filtered = [r for r in filtered if not (r.get("gate") or {}).get("passed")]

    sort_key = (args.get("sort") or "rank").strip()
    descending = (args.get("order") or "").lower() == "desc"
    if sort_key and sort_key != "rank":
        def sort_value(row: Dict[str, Any]):
            value = row.get(sort_key)
            if isinstance(value, dict):
                value = value.get("topicFitPercent")
            if value is None:
                return (1, 0, "")
            if isinstance(value, (int, float)):
                return (0, -value if descending else value, "")
            return (0, 0, str(value).lower() if not descending else _invert(str(value).lower()))
        filtered = sorted(filtered, key=sort_value)
    elif descending:
        filtered = list(reversed(filtered))

    try:
        offset = max(0, int(args.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = int(args.get("limit", 100))
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(MAX_ROWS_PER_PAGE, limit))
    return filtered[offset:offset + limit], len(filtered)


def _invert(text: str) -> str:
    return "".join(chr(0x10FFFF - ord(c)) if ord(c) < 0x10FFFF else c for c in text)


def _send_file_kwarg() -> str:
    """Flask 버전별 파일명 인자명.

    Flask 2.0 부터 ``download_name``, 그 이전(DSS 내장 환경에 흔한 1.x)은
    ``attachment_filename`` 이다. 예외로 감추지 않고 시그니처로 판별한다.
    """
    try:
        parameters = inspect.signature(send_file).parameters
    except (TypeError, ValueError):     # 서명 조회 불가(래핑된 구현) → 최신 인자 가정
        return "download_name"
    if "download_name" in parameters:
        return "download_name"
    if "attachment_filename" in parameters:
        return "attachment_filename"
    return "download_name"


SEND_FILE_KWARG = _send_file_kwarg()


def _download_response(data: bytes, filename: str):
    """다운로드 응답. 한글 파일명은 RFC 5987 헤더로 직접 지정한다."""
    stream = io.BytesIO(data)
    stream.seek(0)
    extension = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    # send_file 에는 ASCII 안전 이름만 넘기고(구버전 Flask 의 비ASCII 처리 차이 회피),
    # 실제 한글 파일명은 아래에서 Content-Disposition 으로 덮어쓴다.
    kwargs = {"mimetype": "application/octet-stream", "as_attachment": True,
              SEND_FILE_KWARG: "result.%s" % extension}
    response = send_file(stream, **kwargs)
    response.headers["Content-Disposition"] = \
        "attachment; filename=\"result.%s\"; filename*=UTF-8''%s" % (extension, quote(filename))
    return response


def _package_version(name: str) -> Optional[str]:
    """설치 여부/버전 조회. 없으면 None (구동 진단용).

    Flask 3.1+ 에서 ``flask.__version__`` 이 폐기되었으므로
    importlib.metadata 를 먼저 사용한다.
    """
    try:
        __import__(name)
    except Exception:
        return None
    try:
        from importlib import metadata
        return metadata.version(name)
    except Exception:
        pass
    module = sys.modules.get(name)
    version = getattr(module, "__version__", None) if module else None
    return str(version) if version else "설치됨"


def _environment_report() -> Dict[str, Any]:
    return {
        "python": platform.python_version(),
        "flask": _package_version("flask"),
        "sendFileKwarg": SEND_FILE_KWARG,
        "packages": {name: _package_version(name)
                     for name in ("pandas", "numpy", "openpyxl", "dataiku")},
        "executable": sys.executable,
    }


def register_routes(app, state: Optional[AppState] = None) -> AppState:
    """Flask app 에 API 라우트를 등록한다."""
    state = state or AppState()
    app.config.setdefault("JSON_AS_ASCII", False)
    try:
        app.json.ensure_ascii = False        # Flask >= 2.2
    except Exception:
        pass

    # ------------------------------------------------------------- 기본 정보
    @app.route("/api/health", methods=["GET"])
    def api_health():
        """구동 진단용. 실패 원인(패키지 누락/저장소 오류)을 그대로 노출한다."""
        environment = _environment_report()
        degraded: List[str] = []
        if state.storage_error:
            degraded.append("저장소 사용 불가: %s" % state.storage_error)
        upload_info = state.uploads.describe()
        if upload_info.get("error"):
            degraded.append("업로드 임시 디렉터리 사용 불가: %s" % upload_info["error"])
        for package in ("pandas", "openpyxl"):
            if not environment["packages"].get(package):
                degraded.append("%s 패키지가 없어 엑셀 읽기/쓰기가 동작하지 않습니다." % package)
        return jsonify({
            "ok": True,
            "app": "PrimePatent",
            "storage": state.store.backend.kind if state.store else "unavailable",
            "storageLocation": (state.store.backend.describe().get("location")
                                if state.store else None),
            "storageNote": (state.store.backend.describe().get("note") if state.store else None),
            "storageError": state.storage_error,
            "uploadRoot": upload_info.get("root"),
            "uploadError": upload_info.get("error"),
            "environment": environment,
            "degraded": degraded,
            "llmCandidates": [{"label": label, "id": llm_id}
                              for label, llm_id in ALLOWED_LLM_CANDIDATES],
            "defaultLlmId": DEFAULT_LLM_ID,
            # JSON 키 정렬 때문에 순서가 깨지므로 순서는 배열로 따로 내려준다
            "areaMax": AREA_MAX,
            "areaOrder": AREA_ORDER,
            "totalMax": TOTAL_MAX,
            "componentMax": COMPONENT_MAX,
            "defaultConfig": ScoringConfig().to_dict(),
        })

    @app.route("/api/fields", methods=["GET"])
    def api_fields():
        return jsonify({"ok": True, "fields": field_catalog()})

    @app.route("/api/guide", methods=["GET"])
    def api_guide():
        """설명 화면 데이터. 배점·가중치는 실제 스코어링 상수에서 생성된다."""
        return jsonify({"ok": True, "guide": build_guide()})

    @app.route("/api/llm/probe", methods=["GET"])
    def api_llm_probe():
        llm_id = request.args.get("llmId") or DEFAULT_LLM_ID
        if llm_id not in ALLOWED_LLM_IDS:
            return _error("허용되지 않은 LLM 입니다.")
        return jsonify({"ok": True, "probe": probe_client(llm_id)})

    # ------------------------------------------------------------- 업로드/매핑
    @app.route("/api/upload", methods=["POST"])
    def api_upload():
        file_storage = request.files.get("file")
        if file_storage is None or not getattr(file_storage, "filename", ""):
            return _error("업로드할 파일을 선택하십시오.")
        try:
            session = state.uploads.save_upload(file_storage, request.form.get("sheet") or None)
        except UploadError as exc:
            return _error(str(exc))
        except Exception as exc:
            logger.exception("업로드 실패")
            return _error("업로드 처리 중 오류가 발생했습니다: %s" % exc, 500)
        return jsonify({"ok": True, "upload": session.to_dict()})

    @app.route("/api/upload/<upload_id>/sheet", methods=["POST"])
    def api_upload_sheet(upload_id):
        body = _json_body()
        try:
            session = state.uploads.get(upload_id)
            state.uploads.load_sheet(session, body.get("sheet"))
        except UploadError as exc:
            return _error(str(exc))
        return jsonify({"ok": True, "upload": session.to_dict()})

    @app.route("/api/upload/<upload_id>/mapping", methods=["POST"])
    def api_upload_mapping(upload_id):
        """사용자 수정 매핑을 검증하고 매핑 현황을 되돌려준다."""
        body = _json_body()
        try:
            session = state.uploads.get(upload_id)
        except UploadError as exc:
            return _error(str(exc))
        from .mapping import mapping_report
        mapping = resolve_mapping(session.headers, body.get("mapping"))
        report = mapping_report(session.headers, mapping)
        return jsonify({"ok": True, "mapping": mapping, "mappingReport": report})

    # ------------------------------------------------------------- 출원인 표준화
    @app.route("/api/upload/<upload_id>/applicants", methods=["POST"])
    def api_applicants(upload_id):
        """업로드 데이터에서 출원인 표기를 모아 표준화 후보 그룹을 만든다."""
        body = _json_body()
        try:
            session = state.uploads.get(upload_id)
        except UploadError as exc:
            return _error(str(exc))
        mapping = resolve_mapping(session.headers, body.get("mapping"))
        if "applicant" not in mapping and "applicantNormalized" not in mapping:
            return _error("출원인 컬럼이 매핑되지 않아 표준화를 진행할 수 없습니다. "
                          "컬럼 매핑에서 '출원인' 을 지정하십시오.")
        try:
            _headers, rows, _meta = state.uploads.rows(session)
        except Exception as exc:
            logger.exception("출원인 수집 실패")
            return _error("업로드 파일을 다시 읽지 못했습니다: %s" % exc, 500)

        entries = collect_applicants(rows, mapping)
        session.applicant_groups = cluster_applicants(entries)
        session.applicant_approved = False
        session.applicant_approved_at = None
        session.applicant_map = {}
        return jsonify({"ok": True, "groups": session.applicant_groups,
                        "state": session.applicant_state()})

    @app.route("/api/upload/<upload_id>/applicants/approve", methods=["POST"])
    def api_applicants_approve(upload_id):
        """사용자가 확정한 표준명을 승인 처리한다. 승인 후에만 분석에 반영된다."""
        body = _json_body()
        try:
            session = state.uploads.get(upload_id)
        except UploadError as exc:
            return _error(str(exc))

        groups = body.get("groups")
        if not isinstance(groups, list) or not groups:
            return _error("승인할 출원인 그룹이 없습니다. 먼저 표준화 후보를 생성하십시오.")
        blank = [g.get("groupId") for g in groups
                 if not str(g.get("standardName") or "").strip()]
        if blank:
            return _error("표준명이 비어 있는 그룹이 있습니다: %s" % ", ".join(map(str, blank[:5])))

        session.applicant_groups = groups
        session.applicant_map = build_name_map(groups)
        session.applicant_approved = True
        from .storage import now_iso
        session.applicant_approved_at = now_iso()

        # 승인하지 않은 병합 그룹은 병합하지 않는다. 조용히 넘기지 않고 사실대로 알린다.
        pending = [g for g in groups
                   if len(g.get("variants") or []) > 1 and not g.get("approved", True)]
        warning = ""
        if pending:
            warning = ("승인하지 않은 그룹 %d개는 병합하지 않고 원본 표기를 그대로 사용합니다: %s"
                       % (len(pending),
                          ", ".join(str(g.get("standardName") or g.get("groupId"))
                                    for g in pending[:5])
                          + (" 외" if len(pending) > 5 else "")))
        logger.info("출원인 표준화 승인: %s (%d개 표기, 미승인 그룹 %d개)",
                    upload_id, len(session.applicant_map), len(pending))
        return jsonify({"ok": True, "state": session.applicant_state(), "warning": warning})

    @app.route("/api/upload/<upload_id>/applicants/reset", methods=["POST"])
    def api_applicants_reset(upload_id):
        try:
            session = state.uploads.get(upload_id)
        except UploadError as exc:
            return _error(str(exc))
        session.applicant_approved = False
        session.applicant_approved_at = None
        session.applicant_map = {}
        return jsonify({"ok": True, "state": session.applicant_state()})

    @app.route("/api/upload/<upload_id>", methods=["DELETE"])
    def api_upload_delete(upload_id):
        state.uploads.drop(upload_id)
        return jsonify({"ok": True})

    # ------------------------------------------------------------- 분석 실행
    @app.route("/api/analyze", methods=["POST"])
    def api_analyze():
        body = _json_body()
        upload_id = body.get("uploadId")
        if not upload_id:
            return _error("uploadId 가 필요합니다.")
        try:
            session = state.uploads.get(upload_id)
        except UploadError as exc:
            return _error(str(exc))

        try:
            config = ScoringConfig.from_dict(body.get("config") or {})
        except Exception as exc:
            return _error("설정 값이 올바르지 않습니다: %s" % exc)
        user_mapping = body.get("mapping")

        # 승인된 경우에만 출원인 표준화를 반영한다(승인 전에는 원본 표기 사용).
        applicant_map = dict(session.applicant_map) if session.applicant_approved else None

        def target(job):
            headers, rows, meta = state.uploads.rows(session)
            meta["uploadId"] = upload_id
            meta["applicantApprovedAt"] = session.applicant_approved_at
            try:
                return run_analysis(
                    headers, rows, user_mapping, config, meta,
                    progress=lambda phase, ratio, message: job.update(phase, ratio, message),
                    cancel_event=job.cancel_event, llm_cache=state.llm_cache,
                    applicant_map=applicant_map)
            except PipelineCancelled:
                job.cancel()
                raise

        job = state.jobs.submit("analyze", target, session.file_name)
        return jsonify({"ok": True, "job": job.to_dict()})

    @app.route("/api/jobs", methods=["GET"])
    def api_jobs():
        return jsonify({"ok": True, "jobs": state.jobs.list_jobs()})

    @app.route("/api/jobs/<job_id>", methods=["GET"])
    def api_job(job_id):
        job = state.jobs.get(job_id)
        if job is None:
            return _error("작업을 찾을 수 없습니다(만료되었을 수 있습니다).", 404)
        return jsonify({"ok": True, "job": job.to_dict()})

    @app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
    def api_job_cancel(job_id):
        if not state.jobs.cancel(job_id):
            return _error("작업을 찾을 수 없습니다.", 404)
        return jsonify({"ok": True})

    # ------------------------------------------------------------- 결과 조회
    def _payload_from_job(job_id: str) -> Dict[str, Any]:
        job = state.jobs.get(job_id)
        if job is None:
            raise LookupError("작업을 찾을 수 없습니다(만료되었을 수 있습니다).")
        if job.status == DONE and job.result_dropped:
            raise LookupError(
                "이 분석 결과는 메모리에서 해제되었습니다(최근 %d건만 유지). "
                "저장소에 저장해 둔 결과를 불러오거나 분석을 다시 실행하십시오."
                % state.jobs.result_retention)
        if job.status != DONE or not isinstance(job.result, dict):
            raise LookupError("아직 완료되지 않은 작업입니다(상태: %s)." % job.status)
        return job.result

    def _payload(source: str, ident: str) -> Dict[str, Any]:
        if source == "job":
            return _payload_from_job(ident)
        if state.store is None:
            raise StorageError("결과 저장소를 사용할 수 없습니다: %s"
                               % (state.storage_error or "원인 미상"))
        return state.store.load(ident)

    def _result_response(payload: Dict[str, Any]):
        rows, total = _paginate(payload.get("rows") or [], request.args)
        return jsonify({
            "ok": True,
            "meta": payload.get("meta"),
            "summary": payload.get("summary"),
            "config": payload.get("config"),
            "mapping": payload.get("mapping"),
            "mappingReport": payload.get("mappingReport"),
            "warnings": payload.get("warnings") or [],
            "generatedAt": payload.get("generatedAt"),
            "source": payload.get("source"),
            "total": total,
            "rows": [_slim_row(r) for r in rows],
        })

    @app.route("/api/jobs/<job_id>/result", methods=["GET"])
    def api_job_result(job_id):
        try:
            return _result_response(_payload_from_job(job_id))
        except LookupError as exc:
            return _error(str(exc), 404)

    @app.route("/api/jobs/<job_id>/row/<path:row_key>", methods=["GET"])
    def api_job_row(job_id, row_key):
        try:
            payload = _payload_from_job(job_id)
        except LookupError as exc:
            return _error(str(exc), 404)
        return _row_response(payload, row_key)

    def _row_response(payload: Dict[str, Any], row_key: str):
        for row in payload.get("rows") or []:
            if str(row.get("key")) == str(row_key):
                return jsonify({"ok": True, "row": row})
        return _error("해당 문헌을 찾을 수 없습니다.", 404)

    # ------------------------------------------------------------- 저장소
    @app.route("/api/save", methods=["POST"])
    def api_save():
        store, unavailable = _store_or_error(state)
        if unavailable:
            return unavailable
        body = _json_body()
        job_id = body.get("jobId")
        run_id = body.get("runId")
        try:
            payload = _payload("job", job_id) if job_id else _payload("run", run_id)
        except (LookupError, StorageError) as exc:
            return _error(str(exc), 404)
        if not job_id and not run_id:
            return _error("저장할 결과(jobId 또는 runId)가 필요합니다.")

        try:
            meta = store.save(
                payload,
                department=body.get("department", ""),
                owner=body.get("owner", ""),
                project=body.get("project", ""),
                title=body.get("title", ""),
                note=body.get("note", ""))
        except StorageError as exc:
            return _error(str(exc))
        except Exception as exc:
            logger.exception("저장 실패")
            return _error("저장 중 오류가 발생했습니다: %s" % exc, 500)

        # 엑셀 산출물도 함께 보관(다운로드 재생성 비용 절감)
        try:
            payload_with_meta = dict(payload)
            payload_with_meta["meta"] = meta
            store.put_artifact(meta["runId"], "result.xlsx",
                               export_bytes(payload_with_meta, "xlsx"))
        except Exception as exc:
            logger.warning("엑셀 산출물 저장 실패(다운로드 시 재생성됨): %s", exc)
        return jsonify({"ok": True, "meta": meta})

    @app.route("/api/runs", methods=["GET"])
    def api_runs():
        store, unavailable = _store_or_error(state)
        if unavailable:
            return unavailable
        try:
            runs = store.list_runs(
                department=request.args.get("department", ""),
                owner=request.args.get("owner", ""),
                project=request.args.get("project", ""),
                keyword=request.args.get("q", ""))
        except StorageError as exc:
            return _error(str(exc), 500)
        return jsonify({"ok": True, "runs": runs, "facets": store.facets(),
                        "storage": store.backend.kind})

    @app.route("/api/runs/<run_id>/result", methods=["GET"])
    def api_run_result(run_id):
        _store, unavailable = _store_or_error(state)
        if unavailable:
            return unavailable
        try:
            return _result_response(_payload("run", run_id))
        except StorageError as exc:
            return _error(str(exc), 404)

    @app.route("/api/runs/<run_id>/row/<path:row_key>", methods=["GET"])
    def api_run_row(run_id, row_key):
        _store, unavailable = _store_or_error(state)
        if unavailable:
            return unavailable
        try:
            payload = _payload("run", run_id)
        except StorageError as exc:
            return _error(str(exc), 404)
        return _row_response(payload, row_key)

    @app.route("/api/runs/<run_id>", methods=["DELETE"])
    def api_run_delete(run_id):
        store, unavailable = _store_or_error(state)
        if unavailable:
            return unavailable
        try:
            store.delete(run_id)
        except StorageError as exc:
            return _error(str(exc), 404)
        return jsonify({"ok": True})

    # ------------------------------------------------------------- 다운로드
    @app.route("/api/jobs/<job_id>/download", methods=["GET"])
    def api_job_download(job_id):
        fmt = (request.args.get("format") or "xlsx").lower()
        try:
            payload = _payload_from_job(job_id)
        except LookupError as exc:
            return _error(str(exc), 404)
        return _download_response(export_bytes(payload, fmt), export_filename(payload, fmt))

    @app.route("/api/runs/<run_id>/download", methods=["GET"])
    def api_run_download(run_id):
        store, unavailable = _store_or_error(state)
        if unavailable:
            return unavailable
        fmt = (request.args.get("format") or "xlsx").lower()
        try:
            payload = _payload("run", run_id)
        except StorageError as exc:
            return _error(str(exc), 404)
        if fmt == "xlsx":
            cached = store.get_artifact(run_id, "result.xlsx")
            if cached:
                return _download_response(cached, export_filename(payload, fmt))
        return _download_response(export_bytes(payload, fmt), export_filename(payload, fmt))

    @app.errorhandler(404)
    def _not_found(exc):
        if request.path.startswith("/api/"):
            return _error("존재하지 않는 API 경로입니다: %s" % request.path, 404)
        # API 외 경로는 DSS/Flask 기본 처리에 맡긴다.
        # (예외 객체를 그대로 반환하면 구버전 Flask 에서 500 이 된다)
        return getattr(exc, "description", "Not Found"), 404

    @app.errorhandler(500)
    def _server_error(exc):
        logger.exception("서버 오류")
        return _error("서버 오류: %s" % exc, 500)

    return state
