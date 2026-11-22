"""Flask WSGI backend for the EBDA AI Lesson Studio.

Native-WSGI port of the FastAPI service (app/main.py), reusing the same
engines and pydantic schemas. Designed for PythonAnywhere (no ASGI server
available on free tier).

Security model (single-user, in-memory):
- State-changing endpoints and anything that can spend an AI key require the
  ``X-App-Passcode`` header matching the server-side ``APP_PASSCODE``
  environment variable. The passcode is never embedded in the frontend
  bundle; the teacher enters it in the UI and it is held in browser memory
  only. When ``APP_PASSCODE`` is not configured on the server, all mutating
  endpoints return 503 (disabled), not an open door.
- AI generation additionally requires ``OPENAI_API_KEY`` to be configured
  server-side; otherwise it returns 503 with an honest message. No fake
  data is ever generated.
- Downloads use unguessable capability IDs and stay open (read-only).
- /api/health exposes status/version only, no store counts.

Honest PDF behaviour: PDFs are produced only by a real LibreOffice
conversion. When LibreOffice is unavailable the plan still returns its DOCX
and QA results, but ``pdf_available`` is False, no placeholder PDF is ever
served, and the PDF download endpoint answers 409 with the real reason.
"""
from __future__ import annotations

import hmac
import io
import os
import secrets
import time
import zipfile
from functools import wraps
from typing import Dict, List, Optional

from flask import Flask, jsonify, request, send_file
from pydantic import BaseModel, ValidationError

from app.engines.ai_engine import generate_lesson_plan, regenerate_fields
from app.engines.curriculum_engine import export_lesson_pdf, ingest_curriculum, update_boundaries
from app.engines.render_qa_engine import render_docx_to_pdf_libreoffice, run_four_pillar_qa
from app.engines.rules_engine import RULES_MODE_LABEL_AR, build_rules_lesson_plan
from app.engines.template_engine import extract_template_schema, inject_lesson_plan_xml_safe
from app.models.schemas import (
    CurriculumUnit,
    GenerationContext,
    LessonPlanPayload,
    QAReport,
    TemplateSchema,
)

VERSION = "1.0.0"
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "https://mostafaatteef-eng.github.io")
APP_PASSCODE = os.getenv("APP_PASSCODE", "")

# In-memory session stores (single user, ephemeral on free hosting)
UNITS: Dict[str, Dict] = {}
TEMPLATES: Dict[str, Dict] = {}
PLANS: Dict[str, Dict] = {}
BATCHES: Dict[str, Dict] = {}


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
    default_academic_year: str = "٢٠٢٥-٢٠٢٦"
    default_branch: str = "الذكاء الاصطناعي وتحليل البيانات"
    default_knowledge_code: str = "TPK04"
    default_location: str = "معمل الذكاء الاصطناعي وتحليل البيانات"
    default_duration_minutes: int = 45
    logo_data_url: Optional[str] = None
    logo_filename: Optional[str] = None
    extracted_brand_color: Optional[str] = None


SETTINGS: Dict[str, InstitutionSettings] = {"current": InstitutionSettings()}


class BoundaryUpdateItem(BaseModel):
    lesson_id: str
    title: str
    start_page: int
    end_page: int
    approved: bool = True


class BoundaryUpdateRequest(BaseModel):
    lessons: List[BoundaryUpdateItem]


class BatchGenerateRequest(BaseModel):
    lesson_ids: List[str]
    base_context: Dict


class RegenerateFieldsRequest(BaseModel):
    plan_id: str
    field_keys: List[str]
    instruction: str = ""


class ApproveFieldsRequest(BaseModel):
    approved_fields: List[str]


def _err(status: int, detail: str):
    return jsonify({"detail": detail}), status


# Per-IP passcode failure tracking: 5 failures lock the source for 10 minutes.
_PASSCODE_FAILURES: Dict[str, List] = {}
_PASSCODE_MAX_FAILURES = 5
_PASSCODE_LOCK_SECONDS = 600


def require_passcode(fn):
    """Gate for mutating / AI-spending endpoints.

    Secure by default: with no server-side APP_PASSCODE configured the
    endpoint is disabled (503), never silently open. Wrong passcodes are
    rate-limited per source IP and compared in constant time.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not APP_PASSCODE:
            return _err(503, "This action is disabled until a server-side APP_PASSCODE is configured.")
        # Key on the immediate peer only. X-Forwarded-For is client-controlled
        # unless a trusted proxy boundary strips it, so never key limits on it.
        ip = request.remote_addr or "unknown"
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


def require_ai(fn):
    """AI endpoints run ONLY when paid AI is explicitly authorized.

    A saved key alone is not spend permission: both OPENAI_API_KEY and
    ENABLE_AI_GENERATION=1 must be set server-side.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not (os.getenv("OPENAI_API_KEY") and os.getenv("ENABLE_AI_GENERATION") == "1"):
            return _err(503, "Paid AI is not authorized/configured on this server.")
        return fn(*args, **kwargs)

    return wrapper


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


# Free-host resource bounds: reject oversized uploads and cap retained
# in-memory items and aggregate bytes so a session cannot exhaust the
# 512MB disk / small RAM. Items expire after RETENTION_SECONDS (lazy sweep).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_BATCH_LESSONS = 25
MAX_STORE_ITEMS = 50
MAX_STORE_BYTES = 200 * 1024 * 1024
RETENTION_SECONDS = 6 * 3600

_CURRICULUM_EXTS = (".pdf", ".docx", ".pptx", ".txt")

# Archive/resource validation bounds (pre-parse, guards decompression abuse).
_MAX_ZIP_ENTRIES = 2000
_MAX_ZIP_UNCOMPRESSED = 200 * 1024 * 1024
_MAX_ZIP_RATIO = 100
_MAX_XML_SCAN_BYTES = 8 * 1024 * 1024
_MAX_PDF_PAGES = 300


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
            if i.compress_size > 1024 * 1024 and i.file_size > i.compress_size * _MAX_ZIP_RATIO:
                return "Archive compression ratio is abnormal."
        for i in infos:
            if not i.filename.lower().endswith((".xml", ".rels")):
                continue
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    with zf.open(i) as fh:
                        chunk = fh.read(_MAX_XML_SCAN_BYTES)
            except Exception:
                return "Could not inspect archive contents safely."
            if b"<!DOCTYPE" in chunk or b"<!ENTITY" in chunk:
                return "XML parts with DOCTYPE/ENTITY declarations are not accepted."
    elif name.endswith(".pdf"):
        try:
            import fitz

            with fitz.open(stream=data, filetype="pdf") as doc:
                if doc.page_count > _MAX_PDF_PAGES:
                    return f"PDF exceeds the {_MAX_PDF_PAGES}-page limit."
        except Exception:
            return "Could not parse PDF file."
    return None


def _allowed(filename: str, exts) -> bool:
    return (filename or "").lower().endswith(exts)


def _retained_bytes() -> int:
    """Approximate retained bytes: raw blobs plus serialized parsed objects."""
    total = 0
    for store in (UNITS, TEMPLATES, PLANS, BATCHES):
        for value in store.values():
            for v in value.values():
                if isinstance(v, (bytes, bytearray)):
                    total += len(v)
                elif hasattr(v, "model_dump_json"):
                    total += len(v.model_dump_json())
                elif isinstance(v, dict):
                    total += len(str(v))
    return total


def _sweep_expired() -> None:
    now = time.time()
    for store in (UNITS, TEMPLATES, PLANS, BATCHES):
        for key in [k for k, v in store.items() if now - v.get("ts", now) > RETENTION_SECONDS]:
            del store[key]


def _store_put(store: Dict[str, Dict], key: str, value: Dict, incoming_bytes: int = 0):
    """Insert with count/byte bounds; error response when a cap is hit."""
    if key not in store and len(store) >= MAX_STORE_ITEMS:
        return _err(429, "Session storage limit reached; delete unused items and retry.")
    if _retained_bytes() + incoming_bytes > MAX_STORE_BYTES:
        return _err(429, "Session storage byte limit reached; delete unused items and retry.")
    value["ts"] = time.time()
    store[key] = value
    return None


def _new_capability_id(prefix: str) -> str:
    """Full-strength (128-bit) unguessable capability ID."""
    return f"{prefix}_{secrets.token_hex(16)}"


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

    @app.before_request
    def sweep():
        _sweep_expired()

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
        return jsonify({"status": "ok", "version": VERSION, "service": "ebda-lesson-studio-backend"})

    # ---------------- Settings ----------------
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

    # ---------------- Curriculum ----------------
    @app.post("/api/curriculum/upload")
    @require_passcode
    def upload_curriculum():
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
        # Replace the engine's short id with a full-strength capability id.
        unit.unit_id = _new_capability_id("unit")
        err = _store_put(UNITS, unit.unit_id, {"unit": unit, "bytes": raw}, len(raw))
        if err:
            return err
        return jsonify(unit.model_dump())

    @app.put("/api/curriculum/<unit_id>/boundaries")
    @require_passcode
    def update_curriculum_boundaries(unit_id):
        stored = UNITS.get(unit_id)
        if not stored:
            return _err(404, "Curriculum unit not found.")
        body, err = _parse_body(BoundaryUpdateRequest, request.get_json(silent=True))
        if err:
            return err
        updated = update_boundaries(stored["unit"], [item.model_dump() for item in body.lessons])
        stored["unit"] = updated
        return jsonify(updated.model_dump())

    @app.get("/api/curriculum/<unit_id>/lesson/<lesson_id>/pdf")
    def download_lesson_pdf(unit_id, lesson_id):
        stored = UNITS.get(unit_id)
        if not stored:
            return _err(404, "Curriculum unit not found.")
        unit: CurriculumUnit = stored["unit"]
        lesson = next((l for l in unit.lessons if l.lesson_id == lesson_id), None)
        if not lesson:
            return _err(404, "Lesson not found.")
        pdf_bytes = export_lesson_pdf(unit, lesson, stored["bytes"] if unit.file_format == "pdf" else None)
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"lesson_{lesson.lesson_number}.pdf",
        )

    @app.delete("/api/curriculum/<unit_id>")
    @require_passcode
    def delete_curriculum(unit_id):
        if unit_id not in UNITS:
            return _err(404, "Curriculum unit not found.")
        del UNITS[unit_id]
        return jsonify({"deleted": True, "unit_id": unit_id})

    # ---------------- Templates ----------------
    @app.post("/api/template/upload")
    @require_passcode
    def upload_template():
        docx = request.files.get("docx")
        if docx is None:
            return _err(400, "Missing template DOCX file.")
        if not _allowed(docx.filename or "", (".docx",)):
            return _err(400, "Template file must be DOCX.")
        ref = request.files.get("reference_pdf")
        if ref is not None and not _allowed(ref.filename or "", (".pdf",)):
            return _err(400, "Reference file must be PDF.")
        docx_bytes = docx.read()
        bad = _validate_upload(docx_bytes, docx.filename or "")
        if bad:
            return _err(400, bad)
        ref_bytes = ref.read() if ref is not None else None
        if ref_bytes is not None:
            bad = _validate_upload(ref_bytes, ref.filename or "")
            if bad:
                return _err(400, bad)
        try:
            schema = extract_template_schema(
                docx_bytes,
                docx.filename or "template.docx",
                ref_bytes,
                ref.filename if ref else None,
            )
        except Exception as exc:
            return _err(400, f"Could not parse template file: {exc}")
        schema.template_id = _new_capability_id("tpl")
        err = _store_put(
            TEMPLATES,
            schema.template_id,
            {"schema": schema, "docx_bytes": docx_bytes, "ref_pdf_bytes": ref_bytes},
            len(docx_bytes) + len(ref_bytes or b""),
        )
        if err:
            return err
        return jsonify(schema.model_dump())

    @app.post("/api/template/<template_id>/reference-pdf")
    @require_passcode
    def upload_reference_pdf(template_id):
        stored = TEMPLATES.get(template_id)
        if not stored:
            return _err(404, "Template not found.")
        f = request.files.get("file") or request.files.get("reference_pdf")
        if f is None:
            return _err(400, "Missing reference PDF file.")
        if not _allowed(f.filename or "", (".pdf",)):
            return _err(400, "Reference file must be PDF.")
        ref_bytes = f.read()
        bad = _validate_upload(ref_bytes, f.filename or "")
        if bad:
            return _err(400, bad)
        try:
            import fitz

            with fitz.open(stream=ref_bytes, filetype="pdf") as doc:
                pages = doc.page_count
        except Exception:
            return _err(400, "Could not parse reference PDF file.")
        old_len = len(stored.get("ref_pdf_bytes") or b"")
        if _retained_bytes() - old_len + len(ref_bytes) > MAX_STORE_BYTES:
            return _err(429, "Session storage byte limit reached; delete unused items and retry.")
        stored["ref_pdf_bytes"] = ref_bytes
        stored["ts"] = time.time()
        schema: TemplateSchema = stored["schema"]
        schema.has_reference_pdf = True
        schema.reference_pdf_filename = f.filename
        schema.reference_pdf_pages = pages
        return jsonify(schema.model_dump())

    @app.delete("/api/template/<template_id>/reference-pdf")
    @require_passcode
    def delete_reference_pdf(template_id):
        stored = TEMPLATES.get(template_id)
        if not stored:
            return _err(404, "Template not found.")
        stored["ref_pdf_bytes"] = None
        schema: TemplateSchema = stored["schema"]
        schema.has_reference_pdf = False
        schema.reference_pdf_filename = None
        schema.reference_pdf_pages = None
        return jsonify(schema.model_dump())

    @app.delete("/api/template/<template_id>")
    @require_passcode
    def delete_template(template_id):
        if template_id not in TEMPLATES:
            return _err(404, "Template not found.")
        del TEMPLATES[template_id]
        return jsonify({"deleted": True, "template_id": template_id})

    # ---------------- Generation ----------------
    def _run_generation(ctx: GenerationContext):
        """Returns (record, error_response)."""
        unit_entry = UNITS.get(ctx.unit_id)
        if not unit_entry:
            return None, _err(404, "Curriculum unit not found.")
        unit: CurriculumUnit = unit_entry["unit"]
        lesson = next((l for l in unit.lessons if l.lesson_id == ctx.lesson_id), None)
        if not lesson:
            return None, _err(404, "Lesson not found.")
        tpl_entry = TEMPLATES.get(ctx.template_id)
        if not tpl_entry:
            return None, _err(404, "Template not found.")

        schema: TemplateSchema = tpl_entry["schema"]
        if _retained_bytes() > MAX_STORE_BYTES:
            return None, _err(429, "Session storage byte limit reached; delete unused items and retry.")
        # Paid AI runs ONLY on explicit authorization: a saved key alone is not
        # spend permission. ENABLE_AI_GENERATION=1 must also be set server-side
        # after the user approves AI cost/scope. Default is the honest,
        # clearly-labeled rules fallback grounded in the uploaded source.
        if os.getenv("OPENAI_API_KEY") and os.getenv("ENABLE_AI_GENERATION") == "1":
            payload: LessonPlanPayload = generate_lesson_plan(unit, lesson, schema, ctx)
            generation_mode = "ai"
        else:
            payload = build_rules_lesson_plan(unit, lesson, schema, ctx)
            generation_mode = "rules_fallback"
        out_docx, metrics = inject_lesson_plan_xml_safe(tpl_entry["docx_bytes"], payload)
        out_pdf, lo_used = _render_pdf(out_docx)
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
                reference_pdf_bytes=tpl_entry.get("ref_pdf_bytes"),
            )
            qa_dict = qa.model_dump()
        except Exception as exc:
            qa_status = f"blocked: QA could not run ({exc})"

        plan_id = _new_capability_id("plan")
        record = {
            "plan_id": plan_id,
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
        PLANS[plan_id] = {
            "record": record,
            "payload_obj": payload,
            "docx_bytes": out_docx,
            "pdf_bytes": out_pdf,
        }
        PLANS[plan_id]["ts"] = time.time()
        if len(PLANS) > MAX_STORE_ITEMS or _retained_bytes() > MAX_STORE_BYTES:
            del PLANS[plan_id]
            return None, _err(429, "Session storage limit reached; delete unused plans and retry.")
        return record, None

    @app.post("/api/generate")
    @require_passcode
    def generate_single():
        ctx, err = _parse_body(GenerationContext, request.get_json(silent=True))
        if err:
            return err
        record, rerr = _run_generation(ctx)
        if rerr:
            return rerr
        return jsonify(record)

    @app.post("/api/generate-batch")
    @require_passcode
    def generate_batch():
        req, err = _parse_body(BatchGenerateRequest, request.get_json(silent=True))
        if err:
            return err
        if not req.lesson_ids:
            return _err(400, "Select at least one lesson.")
        if len(req.lesson_ids) > MAX_BATCH_LESSONS:
            return _err(400, f"Batch size is limited to {MAX_BATCH_LESSONS} lessons.")
        records = []
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for lid in req.lesson_ids:
                ctx = GenerationContext(**{**req.base_context, "lesson_id": lid})
                rec, rerr = _run_generation(ctx)
                if rerr:
                    return rerr
                records.append(rec)
                stored = PLANS[rec["plan_id"]]
                zf.writestr(rec["docx_filename"], stored["docx_bytes"])
                if stored["pdf_bytes"]:
                    zf.writestr(rec["pdf_filename"], stored["pdf_bytes"])

        batch_id = _new_capability_id("batch")
        err = _store_put(
            BATCHES,
            batch_id,
            {"filename": f"ATS-MU_Batch_{batch_id}.zip", "zip_bytes": zip_buf.getvalue()},
            zip_buf.tell(),
        )
        if err:
            return err
        return jsonify({"batch_id": batch_id, "plans": records})

    @app.post("/api/regenerate-fields")
    @require_passcode
    @require_ai
    def regenerate_plan_fields():
        req, err = _parse_body(RegenerateFieldsRequest, request.get_json(silent=True))
        if err:
            return err
        stored = PLANS.get(req.plan_id)
        if not stored:
            return _err(404, "Plan not found.")
        approved = set(stored["record"]["approved_fields"])
        unlocked = [k for k in req.field_keys if k not in approved]
        if not unlocked:
            return _err(400, "All selected fields are locked/approved.")

        ctx = GenerationContext(**stored["record"]["context"])
        unit_entry = UNITS[ctx.unit_id]
        lesson = next(l for l in unit_entry["unit"].lessons if l.lesson_id == ctx.lesson_id)
        tpl_entry = TEMPLATES[ctx.template_id]

        updated_payload = regenerate_fields(lesson, stored["payload_obj"], unlocked, req.instruction)
        out_docx, metrics = inject_lesson_plan_xml_safe(tpl_entry["docx_bytes"], updated_payload)
        out_pdf, lo_used = _render_pdf(out_docx)
        try:
            qa = run_four_pillar_qa(
                lesson=lesson,
                schema=tpl_entry["schema"],
                payload=updated_payload,
                injection_metrics=metrics,
                rendered_pdf_bytes=out_pdf or b"",
                libreoffice_used=lo_used,
                reference_pdf_bytes=tpl_entry.get("ref_pdf_bytes"),
            )
            stored["record"]["qa_report"] = qa.model_dump()
            stored["record"]["qa_status"] = "ok"
        except Exception as exc:
            stored["record"]["qa_report"] = None
            stored["record"]["qa_status"] = f"blocked: QA could not run ({exc})"
        old_blob = len(stored["docx_bytes"] or b"") + len(stored["pdf_bytes"] or b"")
        if _retained_bytes() - old_blob + len(out_docx) + len(out_pdf or b"") > MAX_STORE_BYTES:
            return _err(429, "Session storage byte limit reached; delete unused items and retry.")
        stored["payload_obj"] = updated_payload
        stored["docx_bytes"] = out_docx
        stored["pdf_bytes"] = out_pdf
        stored["ts"] = time.time()
        stored["record"]["payload"] = updated_payload.model_dump()
        stored["record"]["pdf_available"] = bool(out_pdf)
        stored["record"]["pdf_status"] = (
            "ok" if out_pdf else "unavailable: LibreOffice conversion failed on this host"
        )
        return jsonify(stored["record"])

    @app.post("/api/plans/<plan_id>/approve-fields")
    @require_passcode
    def approve_plan_fields(plan_id):
        stored = PLANS.get(plan_id)
        if not stored:
            return _err(404, "Plan not found.")
        req, err = _parse_body(ApproveFieldsRequest, request.get_json(silent=True))
        if err:
            return err
        approved = set(stored["record"]["approved_fields"])
        approved.update(req.approved_fields)
        stored["record"]["approved_fields"] = sorted(approved)
        return jsonify(stored["record"])

    # ---------------- Downloads & deletes ----------------
    def _serve_plan(plan_id, fmt):
        stored = PLANS.get(plan_id)
        if not stored:
            return _err(404, "Plan not found.")
        if fmt == "docx":
            return send_file(
                io.BytesIO(stored["docx_bytes"]),
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                as_attachment=True,
                download_name=stored["record"]["docx_filename"],
            )
        if fmt == "pdf":
            if not stored["pdf_bytes"]:
                return _err(409, stored["record"]["pdf_status"])
            return send_file(
                io.BytesIO(stored["pdf_bytes"]),
                mimetype="application/pdf",
                as_attachment=True,
                download_name=stored["record"]["pdf_filename"],
            )
        return _err(400, "Format must be docx or pdf.")

    def _serve_batch(batch_id):
        batch = BATCHES.get(batch_id)
        if not batch:
            return _err(404, "Batch archive not found.")
        return send_file(
            io.BytesIO(batch["zip_bytes"]),
            mimetype="application/zip",
            as_attachment=True,
            download_name=batch["filename"],
        )

    @app.get("/api/download")
    def download_artifact():
        batch_id = request.args.get("batch_id")
        plan_id = request.args.get("plan_id")
        fmt = request.args.get("format", "docx")
        if batch_id:
            return _serve_batch(batch_id)
        if not plan_id:
            return _err(404, "Plan not found.")
        return _serve_plan(plan_id, fmt)

    # Path-style aliases used by the production frontend
    @app.get("/api/download/<plan_id>/<fmt>")
    def download_artifact_path(plan_id, fmt):
        return _serve_plan(plan_id, fmt)

    @app.get("/api/download/batch/<batch_id>")
    def download_batch_path(batch_id):
        return _serve_batch(batch_id)

    @app.delete("/api/plans/<plan_id>")
    @require_passcode
    def delete_plan(plan_id):
        if plan_id not in PLANS:
            return _err(404, "Plan not found.")
        del PLANS[plan_id]
        return jsonify({"deleted": True, "plan_id": plan_id})

    @app.delete("/api/batches/<batch_id>")
    @require_passcode
    def delete_batch(batch_id):
        if batch_id not in BATCHES:
            return _err(404, "Batch archive not found.")
        del BATCHES[batch_id]
        return jsonify({"deleted": True, "batch_id": batch_id})

    return app


application = create_app()
app = application
