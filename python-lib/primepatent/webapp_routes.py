# -*- coding: utf-8 -*-
"""Flask 라우트 정의.

Dataiku Standard Webapp 의 backend.py 와 로컬 standalone 실행이
동일한 라우트를 공유한다.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from flask import jsonify, request, send_file

from .columns import field_catalog
from .config import (ALLOWED_LLM_CANDIDATES, ALLOWED_LLM_IDS, AREA_MAX,
                     COMPONENT_MAX, DEFAULT_LLM_ID, ScoringConfig)
from .export import export_bytes, export_filename
from .jobs import DONE, JobManager
from .llm.client import probe_client
from .mapping import resolve_mapping
from .pipeline import PipelineCancelled, run_analysis
from .storage import ResultStore, StorageError, make_backend
from .uploads import UploadError, UploadStore

logger = logging.getLogger("primepatent.webapp")

MAX_ROWS_PER_PAGE = 500
SLIM_KEYS = (
    "key", "rank", "docNumber", "applicationNumber", "country", "title", "applicant",
    "currentAssignee", "statusLabel", "statusCode", "priorityDate", "priorityYear",
    "applicationDate", "registrationDate", "totalScore", "totalMax", "quantScore",
    "llmScore", "grade", "areaScores", "reviewRoute", "familyCountries",
    "familyMemberCount", "forwardCitations", "backwardCitations", "claimCount",
    "independentClaimCount", "cpcMain", "detailLink", "percentile", "isRepresentative",
)


class AppState:
    """웹앱 전역 상태(업로드/작업/저장소)."""

    def __init__(self, folder_id: Optional[str] = None, local_root: Optional[str] = None):
        self.jobs = JobManager()
        self.uploads = UploadStore()
        self.store = ResultStore(make_backend(folder_id, local_root))
        self.llm_cache: Dict[str, Dict] = {}


def _error(message: str, code: int = 400):
    return jsonify({"ok": False, "error": message}), code


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
                            ("docNumber", "title", "applicant", "currentAssignee",
                             "applicationNumber", "cpcMain"))
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


def _download_response(data: bytes, filename: str):
    import io
    stream = io.BytesIO(data)
    stream.seek(0)
    response = send_file(stream, mimetype="application/octet-stream", as_attachment=True,
                         download_name=filename)
    # 한글 파일명 (RFC 5987)
    response.headers["Content-Disposition"] = \
        "attachment; filename=\"result.%s\"; filename*=UTF-8''%s" % (
            filename.rsplit(".", 1)[-1], quote(filename))
    return response


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
        return jsonify({
            "ok": True,
            "app": "PrimePatent",
            "storage": state.store.backend.kind,
            "llmCandidates": [{"label": label, "id": llm_id}
                              for label, llm_id in ALLOWED_LLM_CANDIDATES],
            "defaultLlmId": DEFAULT_LLM_ID,
            "areaMax": AREA_MAX,
            "componentMax": COMPONENT_MAX,
            "defaultConfig": ScoringConfig().to_dict(),
        })

    @app.route("/api/fields", methods=["GET"])
    def api_fields():
        return jsonify({"ok": True, "fields": field_catalog()})

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

        def target(job):
            headers, rows, meta = state.uploads.rows(session)
            meta["uploadId"] = upload_id
            try:
                return run_analysis(
                    headers, rows, user_mapping, config, meta,
                    progress=lambda phase, ratio, message: job.update(phase, ratio, message),
                    cancel_event=job.cancel_event, llm_cache=state.llm_cache)
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
        if job.status != DONE or not isinstance(job.result, dict):
            raise LookupError("아직 완료되지 않은 작업입니다(상태: %s)." % job.status)
        return job.result

    def _payload(source: str, ident: str) -> Dict[str, Any]:
        if source == "job":
            return _payload_from_job(ident)
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
            meta = state.store.save(
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
            state.store.put_artifact(meta["runId"], "result.xlsx",
                                     export_bytes(payload_with_meta, "xlsx"))
        except Exception as exc:
            logger.warning("엑셀 산출물 저장 실패(다운로드 시 재생성됨): %s", exc)
        return jsonify({"ok": True, "meta": meta})

    @app.route("/api/runs", methods=["GET"])
    def api_runs():
        try:
            runs = state.store.list_runs(
                department=request.args.get("department", ""),
                owner=request.args.get("owner", ""),
                project=request.args.get("project", ""),
                keyword=request.args.get("q", ""))
        except StorageError as exc:
            return _error(str(exc), 500)
        return jsonify({"ok": True, "runs": runs, "facets": state.store.facets(),
                        "storage": state.store.backend.kind})

    @app.route("/api/runs/<run_id>/result", methods=["GET"])
    def api_run_result(run_id):
        try:
            return _result_response(state.store.load(run_id))
        except StorageError as exc:
            return _error(str(exc), 404)

    @app.route("/api/runs/<run_id>/row/<path:row_key>", methods=["GET"])
    def api_run_row(run_id, row_key):
        try:
            payload = state.store.load(run_id)
        except StorageError as exc:
            return _error(str(exc), 404)
        return _row_response(payload, row_key)

    @app.route("/api/runs/<run_id>", methods=["DELETE"])
    def api_run_delete(run_id):
        try:
            state.store.delete(run_id)
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
        fmt = (request.args.get("format") or "xlsx").lower()
        try:
            payload = state.store.load(run_id)
        except StorageError as exc:
            return _error(str(exc), 404)
        if fmt == "xlsx":
            cached = state.store.get_artifact(run_id, "result.xlsx")
            if cached:
                return _download_response(cached, export_filename(payload, fmt))
        return _download_response(export_bytes(payload, fmt), export_filename(payload, fmt))

    @app.errorhandler(404)
    def _not_found(_exc):
        if request.path.startswith("/api/"):
            return _error("존재하지 않는 API 경로입니다: %s" % request.path, 404)
        return _exc, 404

    @app.errorhandler(500)
    def _server_error(exc):
        logger.exception("서버 오류")
        return _error("서버 오류: %s" % exc, 500)

    return state
