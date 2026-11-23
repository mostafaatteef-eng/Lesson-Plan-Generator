"""Flask WSGI backend for the EBDA AI Lesson Studio.

Native-WSGI port of the FastAPI service (app/main.py), reusing the same
engines and pydantic schemas. Designed for PythonAnywhere (no ASGI server
available on free tier).

Privacy model (request-scoped, no retained lesson data):
- The server keeps NO lesson data between requests. There are no curriculum,
  template, plan or batch stores. The browser holds the uploaded files and
  the parsed unit; every generation request carries what it needs and the
  response carries every artifact back (base64 DOCX/PDF/ZIP). When the
  response leaves, the server is done: inputs, parsed objects and outputs
  are request-local and garbage-collected, including on error and on
  disconnect (nothing was ever stored).
- The only disk writes in the flow are LibreOffice conversion scratch
  files inside an auto-deleted TemporaryDirectory (see render_qa_engine);
  orphans left by a hard process kill are swept at startup.
- Institution settings (school branding, not lesson data) stay in process
  memory only and are never written to disk.

Security model (open classroom access, owner decision 2026-11-23):
- The tool is open: teachers use it without any sign-in or passcode. When
  the server-side ``APP_PASSCODE`` environment variable IS set, mutating
  endpoints require the matching ``X-App-Passcode`` header instead (opt-in
  lock, e.g. for a private deployment); when it is empty, access is open
  by explicit product decision, never by misconfiguration.
- AI generation additionally requires ``OPENAI_API_KEY`` plus
  ``ENABLE_AI_GENERATION=1`` server-side; otherwise the clearly-labeled
  rules fallback is used. No fake data is ever generated.
- Built-in official template: when ``EBDA_DEFAULT_TEMPLATE_PATH`` (and
  optionally ``EBDA_DEFAULT_REFERENCE_PDF_PATH``) point at server-private
  files, they are used whenever a request carries no template upload, so
  teachers only upload a curriculum file. These assets live OUTSIDE the
  public repo; personal document metadata (creator/lastModifiedBy) is
  scrubbed from every generated artifact.
- /api/health exposes status/version and built-in-default availability only.

Honest PDF behaviour: PDFs are produced only by a real LibreOffice
conversion. When LibreOffice is unavailable QA cannot verify the render, so
the lesson is reported as a structured block with no artifacts at all; no
placeholder PDF or unverified DOCX is ever produced.
"""
from __future__ import annotations

import base64
import hmac
import io
import json
import os
import secrets
import time
from datetime import datetime, timezone
import zipfile
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request
from pydantic import BaseModel, ValidationError

from app.engines.ai_engine import generate_lesson_plan
from app.engines.curriculum_engine import ingest_curriculum, update_boundaries
from app.engines.render_qa_engine import render_docx_to_pdf_libreoffice, run_four_pillar_qa
from app.engines.rules_engine import RULES_MODE_LABEL_AR, InsufficientCurriculumEvidence, build_rules_lesson_plan
from app.engines.template_engine import extract_template_schema, inject_lesson_plan_xml_safe
from app.models.schemas import (
    CurriculumUnit,
    GenerationContext,
    LessonBoundary,
    LessonPlanPayload,
    QAReport,
    TemplateSchema,
)

VERSION = "2.1.0"
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "https://mostafaatteef-eng.github.io")
APP_PASSCODE = os.getenv("APP_PASSCODE", "")

# Built-in official template assets (server-private paths, outside the repo).
# Automatically use institution-approved files in a private home directory.
# Environment variables can still override the paths for managed deployments.
_PRIVATE_ASSETS_DIR = Path.home() / "ebda_private_assets"
DEFAULT_TEMPLATE_PATH = os.getenv(
    "EBDA_DEFAULT_TEMPLATE_PATH",
    str(_PRIVATE_ASSETS_DIR / "EBDA_Compact_Template_2026-2027.docx"),
)
DEFAULT_REFERENCE_PDF_PATH = os.getenv(
    "EBDA_DEFAULT_REFERENCE_PDF_PATH",
    str(_PRIVATE_ASSETS_DIR / "EBDA_Compact_Reference_2026-2027.pdf"),
)

# Institution branding only — never lesson data. Process memory, never disk.
SETTINGS: Dict[str, "InstitutionSettings"] = {}


class InstitutionSettings(BaseModel):
    institution_en: str = "EBDA National Schools of Applied Technology"
    institution_ar: str = "مدارس ابدأ الوطنية للعلوم التقنية"
    school_name_en: str = "EBDA National School of Applied Technology – Badr"
    school_name_ar: str = "مدرسة ابدأ الوطنية للعلوم التقنية — بدر"
    specialization_en: str = "Artificial Intelligence & Data Analysis"
    specialization_ar: str = "الذكاء الاصطناعي وتحليل البيانات"
    default_teacher_name: str = ""
    default_job_title: str = "معلم أول الذكاء الاصطناعي وتحليل البيانات"
    default_grade_level: str = "الصف الثاني الثانوي التكنولوجي"
    default_academic_year: str = "٢٠٢٦-٢٠٢٧"
    default_branch: str = "الذكاء الاصطناعي وتحليل البيانات"
    default_knowledge_code: str = "TPK04"
    default_location: str = "معمل الذكاء الاصطناعي وتحليل البيانات"
    default_duration_minutes: int = 50
    logo_data_url: Optional[str] = None
    logo_filename: Optional[str] = None
    extracted_brand_color: Optional[str] = None


SETTINGS["current"] = InstitutionSettings()


class BoundaryUpdateItem(BaseModel):
    lesson_id: str
    title: str
    start_page: int
    end_page: int
    approved: bool = True


class RebindRequest(BaseModel):
    unit: Dict[str, Any]
    lessons: List[BoundaryUpdateItem]


class ScopedGenerateBody(BaseModel):
    context: Dict[str, Any]
    unit: Dict[str, Any]
    lessons: List[Dict[str, Any]]


def _err(status: int, detail: str):
    return jsonify({"detail": detail}), status


def _client_ip() -> str:
    """Best available client key for fairness limiting.

    On PythonAnywhere the load balancer sets X-Real-IP to the real client
    address it received the request from (remote_addr is always the LB).
    X-Forwarded-For is client-controlled and never used. Outside PA a
    direct client's X-Real-IP is self-supplied, which is acceptable for a
    fairness cooldown (not a security boundary).
    """
    return request.headers.get("X-Real-IP") or request.remote_addr or "unknown"


# Per-IP passcode failure tracking: 5 failures lock the source for 10 minutes.
_PASSCODE_FAILURES: Dict[str, List] = {}
_PASSCODE_MAX_FAILURES = 5
# Bound the per-IP failure map: an attacker rotating source IPs must not grow
# worker memory without limit. Expired entries are pruned first; as a last
# resort the map resets (rate limiting only — the passcode is still required).
_PASSCODE_FAILURES_MAX_KEYS = 5000
_PASSCODE_LOCK_SECONDS = 600

def require_passcode(fn):
    """Gate for mutating / AI-spending endpoints.

    Open by explicit product decision: with no server-side APP_PASSCODE the
    endpoint runs without any credential. When APP_PASSCODE is set the
    X-App-Passcode header is required; wrong passcodes are rate-limited per
    source IP and compared in constant time.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not APP_PASSCODE:
            return fn(*args, **kwargs)
        ip = _client_ip()
        if ip not in _PASSCODE_FAILURES and len(_PASSCODE_FAILURES) >= _PASSCODE_FAILURES_MAX_KEYS:
            now = time.time()
            expired = [k for k, v in _PASSCODE_FAILURES.items() if v[1] <= now and v[0] == 0]
            for k in expired:
                del _PASSCODE_FAILURES[k]
            if len(_PASSCODE_FAILURES) >= _PASSCODE_FAILURES_MAX_KEYS:
                _PASSCODE_FAILURES.clear()
        state = _PASSCODE_FAILURES.setdefault(ip, [0, 0.0])
        if state[1] > time.time():
            return _err(429, "Too many failed attempts. Try again later.")
        supplied = request.headers.get("X-App-Passcode", "")
        if not hmac.compare_digest(supplied.encode(), APP_PASSCODE.encode()):
            state[0] += 1
            if state[0] >= _PASSCODE_MAX_FAILURES:
                state[0] = 0
                state[1] = time.time() + _PASSCODE_LOCK_SECONDS
            return _err(401, "Missing or invalid app passcode.")
        state[0] = 0
        return fn(*args, **kwargs)

    return wrapper


def _default_asset(path: str) -> Optional[bytes]:
    """Read a server-private built-in asset (official template/reference)."""
    if path and os.path.isfile(path):
        with open(path, "rb") as fh:
            return fh.read()
    return None


def _parse_body(model, data) -> "tuple[Optional[BaseModel], Optional[tuple]]":
    try:
        return model(**(data or {})), None
    except ValidationError as exc:
        return None, _err(422, exc.errors()[0].get("msg", "Invalid request body"))


def _render_pdf(docx_bytes: bytes) -> "tuple[Optional[bytes], bool]":
    """Real LibreOffice conversion only. No placeholder fallback."""
    try:
        pdf_bytes, ok = render_docx_to_pdf_libreoffice(docx_bytes)
        if ok and pdf_bytes:
            return pdf_bytes, True
    except Exception:
        pass
    return None, False


# Request/body bounds for the free host (512MB disk / small RAM).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_BATCH_LESSONS = 25
# Bound the total decoded artifact bytes returned in one response (plan docx/pdf
# payloads plus the batch zip they are mirrored into). Base64 inflates this by
# 4/3 on the wire; 8 MB decoded keeps the worst-case response near ~21 MB,
# which a free-tier host worker can buffer safely. Lessons beyond the cap fail
# honestly instead of growing worker memory without bound.
MAX_RESPONSE_ARTIFACT_BYTES = 8 * 1024 * 1024
# Per-request wall-clock budget for generation. Measured per-lesson cost is
# dominated by one LibreOffice render (~2-6s); 240s leaves headroom under the
# hosting worker timeout for parsing and response assembly.
GENERATE_TIME_BUDGET_SECONDS = int(os.getenv("GENERATE_TIME_BUDGET_SECONDS", "240"))

_CURRICULUM_EXTS = (".pdf", ".docx", ".pptx", ".txt")

# Archive/resource validation bounds (pre-parse, guards decompression abuse).
_MAX_ZIP_ENTRIES = 2000
_MAX_ZIP_UNCOMPRESSED = 200 * 1024 * 1024
_MAX_ZIP_RATIO = 100
_MAX_XML_SCAN_BYTES = 8 * 1024 * 1024
_MAX_PDF_PAGES = 300
_MAX_PDF_PAGE_AREA_PT2 = 9_000_000  # ~3000x3000pt; bounds pixmap render memory
_XML_MARKERS = (
    [b"<!DOCTYPE", b"<!ENTITY"]
    + [m.encode("utf-16-le") for m in ("<!DOCTYPE", "<!ENTITY")]
    + [m.encode("utf-16-be") for m in ("<!DOCTYPE", "<!ENTITY")]
)


def _validate_upload(data: bytes, filename: str):
    """Pre-parse resource checks. Returns an error string or None.

    DOCX/PPTX are ZIP containers, so the extension allowlist alone cannot
    stop decompression bombs: verify entry count, aggregate uncompressed
    size and per-entry ratio before any parser sees the file, and reject
    XML parts with DOCTYPE/ENTITY declarations (XXE surface). PDFs get a
    page-count bound on top of the byte cap.
    """
    name = (filename or "").lower()
    if name.endswith((".docx", ".pptx")):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                infos = zf.infolist()
        except zipfile.BadZipFile:
            return "File is not a valid DOCX/PPTX archive."
        if len(infos) > _MAX_ZIP_ENTRIES:
            return "Archive has too many entries."
        if sum(i.file_size for i in infos) > _MAX_ZIP_UNCOMPRESSED:
            return "Archive expands beyond the allowed size."
        for i in infos:
            if i.file_size > max(1, i.compress_size) * _MAX_ZIP_RATIO:
                return "Archive compression ratio is abnormal."
        for i in infos:
            if not i.filename.lower().endswith((".xml", ".rels")):
                continue
            if i.file_size > _MAX_XML_SCAN_BYTES:
                return "An XML part exceeds the inspectable size limit."
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    with zf.open(i) as fh:
                        chunk = fh.read(_MAX_XML_SCAN_BYTES)
            except Exception:
                return "Could not inspect archive contents safely."
            for marker in _XML_MARKERS:
                if marker in chunk:
                    return "XML parts with DOCTYPE/ENTITY declarations are not accepted."
    elif name.endswith(".pdf"):
        try:
            import fitz

            with fitz.open(stream=data, filetype="pdf") as doc:
                if doc.page_count > _MAX_PDF_PAGES:
                    return f"PDF exceeds the {_MAX_PDF_PAGES}-page limit."
                for page in doc:
                    r = page.rect
                    if r.width * r.height > _MAX_PDF_PAGE_AREA_PT2:
                        return "PDF page geometry exceeds the renderable limit."
        except Exception:
            return "Could not parse PDF file."
    return None


def _allowed(filename: str, exts) -> bool:
    return (filename or "").lower().endswith(exts)


def _cleanup_lo_scratch() -> None:
    """Remove LibreOffice conversion scratch dirs orphaned by a hard kill.

    TemporaryDirectory deletes its own files on success, error and timeout;
    only a SIGKILL/OOM of the worker itself can orphan one, and the worker is
    gone in that case — so startup cleanup bounds the orphan's lifetime to
    the process restart.
    """
    import glob
    import shutil as _shutil
    import tempfile as _tempfile

    for path in glob.glob(os.path.join(_tempfile.gettempdir(), "atsmu_lo_*")):
        _shutil.rmtree(path, ignore_errors=True)


def _new_id(prefix: str) -> str:
    """Full-strength (128-bit) random ID used as a client-side key."""
    return f"{prefix}_{secrets.token_hex(16)}"


def _b64(data: Optional[bytes]) -> Optional[str]:
    return base64.b64encode(data).decode("ascii") if data else None


def _run_generation_scoped(
    ctx: GenerationContext,
    unit: CurriculumUnit,
    lesson: LessonBoundary,
    schema: TemplateSchema,
    template_docx: bytes,
    ref_pdf_bytes: Optional[bytes],
):
    """Generate one lesson plan entirely within this request.

    Returns (plan_dict, failure_dict). On success plan_dict carries the
    record plus base64 artifacts. On QA-block or failure, failure_dict
    carries the full diagnostics and NO artifact bytes.
    """
    # Paid AI runs ONLY on explicit authorization: a saved key alone is not
    # spend permission. ENABLE_AI_GENERATION=1 must also be set server-side
    # after the user approves AI cost/scope. Default is the honest,
    # clearly-labeled rules fallback grounded in the uploaded source.
    if ctx.output_language == "en":
        return None, {"lesson_id": lesson.lesson_id, "lesson_title": lesson.title,
            "detail": "English lesson-plan output is not supported by the current Arabic template. Interface language does not translate the plan. Choose Arabic or match-template for an Arabic draft with original source excerpts. No translation or AI service was activated."}
    if os.getenv("OPENAI_API_KEY") and os.getenv("ENABLE_AI_GENERATION") == "1":
        payload: LessonPlanPayload = generate_lesson_plan(unit, lesson, schema, ctx)
        generation_mode = "ai"
    else:
        payload = build_rules_lesson_plan(unit, lesson, schema, ctx)
        generation_mode = "rules_fallback"
    out_docx, metrics = inject_lesson_plan_xml_safe(template_docx, payload)
    if metrics.get("injected_count", 0) == 0:
        # Honest refusal: an unrecognized template must never come back as a
        # valid-looking but actually empty "generated" plan.
        return None, {
            "lesson_id": lesson.lesson_id,
            "lesson_title": lesson.title,
            "detail": "القالب غير معروف: لم تطابق أي خانات قابلة للتعبئة، فلم تُنتج خطة. ارفع قالب التحضير الرسمي ATS-MU.",
        }
    out_pdf, lo_used = _render_pdf(out_docx)
    if out_pdf is None:
        # QA's visual pillars need the rendered PDF. Without it no honest
        # verification happened, so this is a structured block, not a plan.
        return None, {
            "lesson_id": lesson.lesson_id,
            "lesson_title": lesson.title,
            "detail": "تعذّر إنتاج PDF للمعاينة وفحص الجودة على هذا الخادم، فلم تُنتج الخطة. حاول مجددًا لاحقًا.",
            "qa_blocked": True,
        }
    qa_status = "ok"
    qa_dict = None
    try:
        qa: QAReport = run_four_pillar_qa(
            lesson=lesson,
            schema=schema,
            payload=payload,
            injection_metrics=metrics,
            rendered_pdf_bytes=out_pdf or b"",
            libreoffice_used=lo_used,
            reference_pdf_bytes=ref_pdf_bytes,
        )
        qa_dict = qa.model_dump()
    except Exception as exc:
        # Fail closed: QA could not run, so nothing is verifiable. Return a
        # structured block with no artifact bytes — never a plan with
        # qa_report=None (the frontend cannot render that safely).
        return None, {
            "lesson_id": lesson.lesson_id,
            "lesson_title": lesson.title,
            "detail": f"تعذّر إجراء فحص الجودة، فلم تُنتج الخطة. حاول مجددًا. ({exc})",
            "qa_blocked": True,
        }

    # Honest enforcement: a generation whose QA found blocking gates is not a
    # valid plan. It produces no artifact bytes and is reported as a failure
    # with the full diagnostics.
    if qa_dict is not None:
        blocking = [g for g in qa_dict.get("approval_gates", []) if g.get("severity") == "blocking"]
        if qa_dict.get("overall_status") == "fail" or blocking:
            reasons = "؛ ".join(g.get("message", "") for g in blocking if g.get("message"))
            detail = "الخطة لم تجتز فحوصات الجودة ولم تُنتج."
            if reasons:
                detail = f"{detail} الأسباب: {reasons}"
            return None, {
                "lesson_id": lesson.lesson_id,
                "lesson_title": lesson.title,
                "detail": detail,
                "qa_blocked": True,
                "qa_report": qa_dict,
                "blocking_gates": blocking,
            }

    plan_id = _new_id("plan")
    record = {
        "plan_id": plan_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generation_mode": generation_mode,
        "generation_label": None if generation_mode == "ai" else RULES_MODE_LABEL_AR,
        "context": ctx.model_dump(),
        "lesson_title": payload.lesson_title,
        "payload": payload.model_dump(),
        "qa_report": qa_dict,
        "qa_status": qa_status,
        "pdf_available": bool(out_pdf),
        "pdf_status": "ok" if out_pdf else "unavailable: LibreOffice conversion failed on this host",
        "approved_fields": [],
        "docx_filename": f"lesson_{lesson.lesson_number}_{plan_id}.docx",
        "pdf_filename": f"lesson_{lesson.lesson_number}_{plan_id}.pdf" if out_pdf else None,
    }
    return {
        **record,
        "docx_b64": _b64(out_docx),
        "pdf_b64": _b64(out_pdf),
        "_docx_bytes": out_docx,  # internal: used for the batch zip, stripped before jsonify
        "_pdf_bytes": out_pdf,
    }, None


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

    @app.after_request
    def add_cors(resp):
        origin = request.headers.get("Origin", "")
        if origin == FRONTEND_ORIGIN:
            resp.headers["Access-Control-Allow-Origin"] = FRONTEND_ORIGIN
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-App-Passcode"
        return resp

    @app.route("/api/<path:_any>", methods=["OPTIONS"])
    def cors_preflight(_any):
        return ("", 204)

    @app.get("/")
    def index():
        return (
            "<!doctype html><html lang=\"ar\"><head><meta charset=\"utf-8\"/>"
            "<title>EBDA AI Lesson Studio — Backend</title></head><body>"
            "<h1>EBDA AI Lesson Studio — Flask Backend</h1>"
            "<p>Backend API is running. See <code>/api/health</code>.</p>"
            "</body></html>"
        )

    @app.get("/api/health")
    def health():
        return jsonify({
            "status": "ok",
            "version": VERSION,
            "service": "ebda-lesson-studio-backend",
            # Configuration only: never expose the API key, provider response or costs.
            "generation": {
                "mode": "ai" if bool(os.getenv("OPENAI_API_KEY")) and os.getenv("ENABLE_AI_GENERATION") == "1" else "rules_fallback",
                "ai_enabled": bool(os.getenv("OPENAI_API_KEY")) and os.getenv("ENABLE_AI_GENERATION") == "1",
            },
            "defaults": {
                "template": _default_asset(DEFAULT_TEMPLATE_PATH) is not None,
                "reference_pdf": _default_asset(DEFAULT_REFERENCE_PDF_PATH) is not None,
            },
        })

    # ---------------- Settings (branding only, never lesson data) ----------------
    @app.get("/api/settings")
    def get_settings():
        return jsonify(SETTINGS["current"].model_dump())

    @app.put("/api/settings")
    @require_passcode
    def update_settings():
        body, err = _parse_body(InstitutionSettings, request.get_json(silent=True))
        if err:
            return err
        if body.logo_data_url is not None:
            if not body.logo_data_url.startswith("data:image/"):
                return _err(400, "Logo must be a valid uploaded image data URL.")
            if len(body.logo_data_url) > 4 * 1024 * 1024:
                return _err(400, "Logo image exceeds 4 MB limit.")
        body.default_duration_minutes = max(15, min(180, body.default_duration_minutes))
        SETTINGS["current"] = body
        return jsonify(body.model_dump())

    # ---------------- Curriculum (request-scoped) ----------------
    @app.post("/api/curriculum/parse")
    @require_passcode
    def parse_curriculum():
        """Parse an uploaded curriculum file and return the full unit JSON.

        Nothing is stored: the browser keeps the parsed unit and sends the
        relevant parts back with any later request."""
        f = request.files.get("file")
        if f is None:
            return _err(400, "Missing curriculum file.")
        if not _allowed(f.filename or "", _CURRICULUM_EXTS):
            return _err(400, "Curriculum file must be PDF, DOCX, PPTX or TXT.")
        raw = f.read()
        bad = _validate_upload(raw, f.filename or "")
        if bad:
            return _err(400, bad)
        try:
            unit = ingest_curriculum(raw, f.filename or "curriculum.txt")
        except Exception as exc:
            return _err(400, f"Could not parse curriculum file: {exc}")
        unit.unit_id = _new_id("unit")
        return jsonify(unit.model_dump())

    @app.post("/api/curriculum/rebind")
    @require_passcode
    def rebind_curriculum():
        """Pure boundary edit: full unit in, updated unit out. No storage."""
        body, err = _parse_body(RebindRequest, request.get_json(silent=True))
        if err:
            return err
        try:
            unit = CurriculumUnit(**body.unit)
        except ValidationError as exc:
            return _err(422, f"Invalid unit payload: {exc.errors()[0].get('msg', 'invalid')}")
        updated = update_boundaries(unit, [item.model_dump() for item in body.lessons])
        return jsonify(updated.model_dump())

    # ---------------- Template (request-scoped) ----------------
    @app.post("/api/template/parse")
    @require_passcode
    def parse_template():
        """Parse a template DOCX (+ optional reference PDF) into its schema.

        Nothing is stored: the browser keeps the original files and attaches
        them to the generation request."""
        docx = request.files.get("docx")
        default_docx = None if docx is not None else _default_asset(DEFAULT_TEMPLATE_PATH)
        if docx is None and default_docx is None:
            return _err(400, "Missing template DOCX file.")
        if docx is not None and not _allowed(docx.filename or "", (".docx",)):
            return _err(400, "Template file must be DOCX.")
        ref = request.files.get("reference_pdf")
        if ref is not None and not _allowed(ref.filename or "", (".pdf",)):
            return _err(400, "Reference file must be PDF.")
        docx_bytes = docx.read() if docx is not None else default_docx
        bad = _validate_upload(docx_bytes, docx.filename if docx is not None else "builtin-template.docx")
        if bad:
            return _err(400, bad)
        ref_bytes = ref.read() if ref is not None else _default_asset(DEFAULT_REFERENCE_PDF_PATH)
        if ref_bytes is not None:
            bad = _validate_upload(ref_bytes, (ref.filename if ref is not None else "ebda-reference.pdf") or "")
            if bad:
                return _err(400, bad)
        ref_name = ref.filename if ref is not None else ("ebda-reference.pdf" if ref_bytes is not None else None)
        try:
            schema = extract_template_schema(
                docx_bytes,
                (docx.filename or "template.docx") if docx is not None else "ebda-official-template.docx",
                ref_bytes,
                ref_name,
            )
        except Exception as exc:
            return _err(400, f"Could not parse template file: {exc}")
        schema.template_id = _new_id("tpl")
        return jsonify(schema.model_dump())

    # ---------------- Generation (fully request-scoped) ----------------
    @app.post("/api/generate")
    @require_passcode
    def generate():
        """Generate lesson plans within one request and return all artifacts.

        Multipart fields:
          template      DOCX file (required) — the browser-held template.
          reference_pdf PDF file (optional) — QA visual reference.
          request       JSON string: {context, unit, lessons[]} where lessons
                        are the full LessonBoundary objects (with raw_text)
                        selected in the UI.

        Response: single lesson -> {"plan": {...}} or 422 with diagnostics;
        multiple -> {"plans": [...], "failures": [...], "zip_b64": ...}.
        Nothing is stored server-side; when this response leaves, the server
        holds nothing from the request.
        """
        tpl_file = request.files.get("template")
        default_template = None if tpl_file is not None else _default_asset(DEFAULT_TEMPLATE_PATH)
        if tpl_file is None and default_template is None:
            return _err(400, "Missing template DOCX file.")
        if tpl_file is not None and not _allowed(tpl_file.filename or "", (".docx",)):
            return _err(400, "Template file must be DOCX.")
        template_bytes = tpl_file.read() if tpl_file is not None else default_template
        bad = _validate_upload(template_bytes, tpl_file.filename if tpl_file is not None else "builtin-template.docx")
        if bad:
            return _err(400, bad)
        ref_file = request.files.get("reference_pdf")
        ref_bytes = None
        if ref_file is not None:
            if not _allowed(ref_file.filename or "", (".pdf",)):
                return _err(400, "Reference file must be PDF.")
            ref_bytes = ref_file.read()
            bad = _validate_upload(ref_bytes, ref_file.filename or "")
            if bad:
                return _err(400, bad)
        elif tpl_file is None:
            ref_bytes = _default_asset(DEFAULT_REFERENCE_PDF_PATH)

        raw_body = request.form.get("request")
        if not raw_body:
            return _err(400, "Missing generation request JSON.")
        try:
            parsed = json.loads(raw_body)
        except (ValueError, TypeError):
            return _err(400, "Generation request is not valid JSON.")
        body, err = _parse_body(ScopedGenerateBody, parsed)
        if err:
            return err
        # Validate actual caller input before schema defaults can invent identity.
        identity_errors = []
        if not str(body.context.get("teacher_name") or "").strip():
            identity_errors.append("أدخل اسم المعلم.")
        sections = body.context.get("class_sections")
        if not isinstance(sections, list) or not sections or any(
            not isinstance(section, str) or not section.strip() for section in sections
        ):
            identity_errors.append("حدد الفصل أو الفصول المطلوبة.")
        lesson_date = body.context.get("lesson_date")
        try:
            if not isinstance(lesson_date, str) or len(lesson_date) != 10:
                raise ValueError("date required")
            datetime.strptime(lesson_date, "%Y-%m-%d")
        except ValueError:
            identity_errors.append("اختر تاريخ حصة صحيحًا.")
        if identity_errors:
            return _err(422, " ".join(identity_errors))
        if not body.lessons:
            return _err(400, "Select at least one lesson.")
        if len(body.lessons) > MAX_BATCH_LESSONS:
            return _err(400, f"Batch size is limited to {MAX_BATCH_LESSONS} lessons.")

        try:
            schema = extract_template_schema(
                template_bytes,
                (tpl_file.filename or "template.docx") if tpl_file is not None else "ebda-official-template.docx",
                ref_bytes,
                ref_file.filename if ref_file else None,
            )
        except Exception as exc:
            return _err(400, f"Could not parse template file: {exc}")
        schema.template_id = _new_id("tpl")

        lessons: List[LessonBoundary] = []
        for item in body.lessons:
            try:
                lessons.append(LessonBoundary(**item))
            except ValidationError as exc:
                return _err(422, f"Invalid lesson payload: {exc.errors()[0].get('msg', 'invalid')}")

        try:
            unit = CurriculumUnit(**{**body.unit, "lessons": lessons, "pages": []})
        except ValidationError as exc:
            return _err(422, f"Invalid unit payload: {exc.errors()[0].get('msg', 'invalid')}")

        plans: List[Dict] = []
        failures: List[Dict] = []
        response_bytes_used = 0
        cap_reached = False
        # Serial LibreOffice runs are the dominant cost (~seconds per lesson).
        # Free hosts kill long requests, so stop starting new lessons once the
        # budget is spent and report the rest as honest failures instead of
        # dying mid-batch with nothing returned.
        generate_started = time.monotonic()
        for lesson in lessons:
            if cap_reached or time.monotonic() - generate_started > GENERATE_TIME_BUDGET_SECONDS:
                failures.append({
                    "lesson_id": lesson.lesson_id,
                    "lesson_title": lesson.title,
                    "detail": (
                        "تجاوزت المخرجات حد حجم الاستجابة لهذه الدفعة؛ "
                        "ولّد هذا الدرس ضمن دفعة أصغر."
                    ) if cap_reached else (
                        "انتهت المهلة الزمنية للطلب قبل توليد هذا الدرس؛ "
                        "أعد المحاولة بعدد دروس أقل."
                    ),
                })
                continue
            ctx_data = {
                **body.context,
                "unit_id": unit.unit_id,
                "template_id": schema.template_id,
                "lesson_id": lesson.lesson_id,
            }
            ctx, cerr = _parse_body(GenerationContext, ctx_data)
            if cerr:
                return cerr
            try:
                plan, failure = _run_generation_scoped(
                    ctx, unit, lesson, schema, template_bytes, ref_bytes
                )
            except InsufficientCurriculumEvidence as exc:
                plan, failure = None, {
                    "lesson_id": lesson.lesson_id,
                    "lesson_title": lesson.title,
                    "detail": str(exc),
                    "qa_blocked": True,
                    "blocking_gates": [{
                        "gate_id": "gate_source_depth",
                        "category": "curriculum_fidelity",
                        "severity": "blocking",
                        "message": str(exc),
                    }],
                    "qa_report": {
                        "overall_status": "fail",
                        "approval_gates": [{
                            "gate_id": "gate_source_depth",
                            "category": "curriculum_fidelity",
                            "severity": "blocking",
                            "message": str(exc),
                        }],
                    },
                }
            except Exception as exc:
                plan, failure = None, {
                    "lesson_id": lesson.lesson_id,
                    "lesson_title": lesson.title,
                    "detail": "تعذّر توليد هذا الدرس. إذا كان وضع AI مفعّلًا، تحقق من اتصال الخدمة وإعداداتها ثم أعد المحاولة. لم تُنتج ملفات غير متحققة.",
                }
            if failure:
                failures.append(failure)
            else:
                artifact_bytes = len(plan.get("_docx_bytes") or b"") + len(plan.get("_pdf_bytes") or b"")
                if response_bytes_used + artifact_bytes > MAX_RESPONSE_ARTIFACT_BYTES:
                    cap_reached = True
                    failures.append({
                        "lesson_id": lesson.lesson_id,
                        "lesson_title": lesson.title,
                        "detail": (
                            "تجاوزت خطة هذا الدرس حد حجم الاستجابة؛ "
                            "ولّده ضمن دفعة أصغر."
                        ),
                    })
                    continue
                response_bytes_used += artifact_bytes
                plans.append(plan)

        if len(lessons) == 1 and failures:
            f0 = failures[0]
            status = 422
            body_out = {"detail": f0.get("detail", "Generation failed.")}
            for key in ("qa_blocked", "qa_report", "blocking_gates"):
                if key in f0:
                    body_out[key] = f0[key]
            return jsonify(body_out), status

        zip_b64 = None
        if len(plans) > 1:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for plan in plans:
                    zf.writestr(plan["docx_filename"], plan["_docx_bytes"])
                    if plan["_pdf_bytes"]:
                        zf.writestr(plan["pdf_filename"], plan["_pdf_bytes"])
            zip_b64 = _b64(zip_buf.getvalue())

        for plan in plans:
            plan.pop("_docx_bytes", None)
            plan.pop("_pdf_bytes", None)

        if not plans:
            return jsonify({"detail": "تعذّر إنشاء أي درس. راجع الأسباب لكل درس ثم حاول مجددًا.", "failures": failures}), 422

        if len(lessons) == 1:
            return jsonify({"plan": plans[0]})
        return jsonify({
            "plans": plans,
            "failures": failures,
            "zip_b64": zip_b64,
            "zip_filename": "ATS-MU_Lesson_Plans.zip" if zip_b64 else None,
        })

    _cleanup_lo_scratch()
    return app


application = create_app()
app = application
