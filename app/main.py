from __future__ import annotations

import io
import uuid
import zipfile
from typing import Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from app.engines.ai_engine import generate_lesson_plan, regenerate_fields
from app.engines.curriculum_engine import export_lesson_pdf, ingest_curriculum, update_boundaries
from app.engines.render_qa_engine import render_docx_to_pdf_libreoffice, run_four_pillar_qa
from app.engines.template_engine import extract_template_schema, inject_lesson_plan_xml_safe
from app.models.schemas import (
    CurriculumUnit,
    GenerationContext,
    LessonPlanPayload,
    QAReport,
    TemplateSchema,
)

app = FastAPI(
    title="ATS-MU AI Lesson Plan Generator",
    description="Intelligent curriculum analysis, pedagogical planning, and pixel-accurate DOCX template preservation.",
    version="1.0.0",
)

# In-memory session stores
UNITS: Dict[str, Dict] = {}
TEMPLATES: Dict[str, Dict] = {}
PLANS: Dict[str, Dict] = {}
BATCHES: Dict[str, Dict] = {}


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


def _render_pdf_with_fallback(docx_bytes: bytes, schema: TemplateSchema) -> tuple[bytes, bool]:
    try:
        return render_docx_to_pdf_libreoffice(docx_bytes)
    except Exception:
        import fitz

        doc = fitz.open()
        for i in range(max(1, schema.page_count_expected)):
            pg = doc.new_page(width=schema.page_width_pt, height=schema.page_height_pt)
            pg.insert_text((48, 64), f"ATS-MU Lesson Plan Export — Page {i + 1} of {schema.page_count_expected}")
        data = doc.tobytes()
        doc.close()
        return data, False


@app.get("/", response_class=HTMLResponse)
def index_ui() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>ATS-MU AI Lesson Plan Generator (FastAPI)</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; max-width: 960px; margin: 40px auto; padding: 0 24px; color: #0f172a; background: #f8fafc; }
    h1 { color: #0f5c5c; margin-bottom: 6px; }
    .card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px; margin-top: 20px; }
    code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }
    ul { line-height: 1.8; }
  </style>
</head>
<body>
  <h1>ATS-MU AI Lesson Plan Generator — FastAPI Service</h1>
  <p>Pixel-accurate DOCX template preservation, Arabic/English curriculum boundary detection, LibreOffice PDF rendering, and 4-pillar QA.</p>
  <div class="card">
    <h2>REST API Endpoints</h2>
    <ul>
      <li><code>POST /api/curriculum/upload</code> — Ingest PDF, DOCX, PPTX, TXT with Tesseract <code>ara+eng</code> OCR fallback</li>
      <li><code>PUT /api/curriculum/{id}/boundaries</code> — Review, adjust, and approve lesson boundaries</li>
      <li><code>GET /api/curriculum/{unit_id}/lesson/{lesson_id}/pdf</code> — Export sliced per-lesson PDF</li>
      <li><code>POST /api/template/upload</code> — Parse editable DOCX template + optional Reference PDF</li>
      <li><code>POST /api/generate</code> — Generate structured JSON plan, inject XML-safely, render PDF, run 4-pillar QA</li>
      <li><code>POST /api/generate-batch</code> — Batch generate multiple lessons and bundle <code>.zip</code></li>
      <li><code>POST /api/regenerate-fields</code> — Partial field regeneration preserving approved fields</li>
      <li><code>GET /api/download?plan_id=...&amp;format=docx|pdf</code> — Download output artifacts</li>
    </ul>
    <p>Interactive Swagger API Docs: <a href="/docs">/docs</a></p>
  </div>
</body>
</html>"""


@app.post("/api/curriculum/upload", response_model=CurriculumUnit)
async def upload_curriculum(file: UploadFile = File(...)) -> CurriculumUnit:
    raw = await file.read()
    unit = ingest_curriculum(raw, file.filename or "curriculum.txt")
    UNITS[unit.unit_id] = {"unit": unit, "bytes": raw}
    return unit


@app.put("/api/curriculum/{unit_id}/boundaries", response_model=CurriculumUnit)
def update_curriculum_boundaries(unit_id: str, body: BoundaryUpdateRequest) -> CurriculumUnit:
    stored = UNITS.get(unit_id)
    if not stored:
        raise HTTPException(status_code=404, detail="Curriculum unit not found.")
    updated = update_boundaries(stored["unit"], [item.model_dump() for item in body.lessons])
    stored["unit"] = updated
    return updated


@app.get("/api/curriculum/{unit_id}/lesson/{lesson_id}/pdf")
def download_lesson_pdf(unit_id: str, lesson_id: str) -> Response:
    stored = UNITS.get(unit_id)
    if not stored:
        raise HTTPException(status_code=404, detail="Curriculum unit not found.")
    unit: CurriculumUnit = stored["unit"]
    lesson = next((l for l in unit.lessons if l.lesson_id == lesson_id), None)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    pdf_bytes = export_lesson_pdf(unit, lesson, stored["bytes"] if unit.file_format == "pdf" else None)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="lesson_{lesson.lesson_number}.pdf"'},
    )


@app.post("/api/template/upload", response_model=TemplateSchema)
async def upload_template(
    docx: UploadFile = File(...),
    reference_pdf: Optional[UploadFile] = File(default=None),
) -> TemplateSchema:
    docx_bytes = await docx.read()
    ref_bytes = await reference_pdf.read() if reference_pdf is not None else None
    schema = extract_template_schema(
        docx_bytes,
        docx.filename or "template.docx",
        ref_bytes,
        reference_pdf.filename if reference_pdf else None,
    )
    TEMPLATES[schema.template_id] = {
        "schema": schema,
        "docx_bytes": docx_bytes,
        "ref_pdf_bytes": ref_bytes,
    }
    return schema


def _run_generation(ctx: GenerationContext) -> Dict:
    unit_entry = UNITS.get(ctx.unit_id)
    if not unit_entry:
        raise HTTPException(status_code=404, detail="Curriculum unit not found.")
    unit: CurriculumUnit = unit_entry["unit"]
    lesson = next((l for l in unit.lessons if l.lesson_id == ctx.lesson_id), None)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    tpl_entry = TEMPLATES.get(ctx.template_id)
    if not tpl_entry:
        raise HTTPException(status_code=404, detail="Template not found.")

    schema: TemplateSchema = tpl_entry["schema"]
    payload: LessonPlanPayload = generate_lesson_plan(unit, lesson, schema, ctx)
    out_docx, metrics = inject_lesson_plan_xml_safe(tpl_entry["docx_bytes"], payload)
    out_pdf, lo_used = _render_pdf_with_fallback(out_docx, schema)
    qa: QAReport = run_four_pillar_qa(
        lesson=lesson,
        schema=schema,
        payload=payload,
        injection_metrics=metrics,
        rendered_pdf_bytes=out_pdf,
        libreoffice_used=lo_used,
        reference_pdf_bytes=tpl_entry.get("ref_pdf_bytes"),
    )

    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    record = {
        "plan_id": plan_id,
        "context": ctx.model_dump(),
        "lesson_title": payload.lesson_title,
        "payload": payload.model_dump(),
        "qa_report": qa.model_dump(),
        "approved_fields": [],
        "docx_filename": f"lesson_{lesson.lesson_number}_{plan_id}.docx",
        "pdf_filename": f"lesson_{lesson.lesson_number}_{plan_id}.pdf",
    }
    PLANS[plan_id] = {
        "record": record,
        "payload_obj": payload,
        "docx_bytes": out_docx,
        "pdf_bytes": out_pdf,
    }
    return record


@app.post("/api/generate")
def generate_single(context: GenerationContext) -> Dict:
    return _run_generation(context)


@app.post("/api/generate-batch")
def generate_batch(req: BatchGenerateRequest) -> Dict:
    if not req.lesson_ids:
        raise HTTPException(status_code=400, detail="Select at least one lesson.")
    records = []
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for lid in req.lesson_ids:
            ctx = GenerationContext(**{**req.base_context, "lesson_id": lid})
            rec = _run_generation(ctx)
            records.append(rec)
            stored = PLANS[rec["plan_id"]]
            zf.writestr(rec["docx_filename"], stored["docx_bytes"])
            zf.writestr(rec["pdf_filename"], stored["pdf_bytes"])

    batch_id = f"batch_{uuid.uuid4().hex[:8]}"
    BATCHES[batch_id] = {"filename": f"ATS-MU_Batch_{batch_id}.zip", "zip_bytes": zip_buf.getvalue()}
    return {"batch_id": batch_id, "plans": records}


@app.post("/api/regenerate-fields")
def regenerate_plan_fields(req: RegenerateFieldsRequest) -> Dict:
    stored = PLANS.get(req.plan_id)
    if not stored:
        raise HTTPException(status_code=404, detail="Plan not found.")
    approved = set(stored["record"]["approved_fields"])
    unlocked = [k for k in req.field_keys if k not in approved]
    if not unlocked:
        raise HTTPException(status_code=400, detail="All selected fields are locked/approved.")

    ctx = GenerationContext(**stored["record"]["context"])
    unit_entry = UNITS[ctx.unit_id]
    lesson = next(l for l in unit_entry["unit"].lessons if l.lesson_id == ctx.lesson_id)
    tpl_entry = TEMPLATES[ctx.template_id]

    updated_payload = regenerate_fields(lesson, stored["payload_obj"], unlocked, req.instruction)
    out_docx, metrics = inject_lesson_plan_xml_safe(tpl_entry["docx_bytes"], updated_payload)
    out_pdf, lo_used = _render_pdf_with_fallback(out_docx, tpl_entry["schema"])
    qa = run_four_pillar_qa(
        lesson=lesson,
        schema=tpl_entry["schema"],
        payload=updated_payload,
        injection_metrics=metrics,
        rendered_pdf_bytes=out_pdf,
        libreoffice_used=lo_used,
        reference_pdf_bytes=tpl_entry.get("ref_pdf_bytes"),
    )
    stored["payload_obj"] = updated_payload
    stored["docx_bytes"] = out_docx
    stored["pdf_bytes"] = out_pdf
    stored["record"]["payload"] = updated_payload.model_dump()
    stored["record"]["qa_report"] = qa.model_dump()
    return stored["record"]


@app.get("/api/download")
def download_artifact(
    plan_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    format: str = "docx",
) -> Response:
    if batch_id:
        batch = BATCHES.get(batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="Batch archive not found.")
        return Response(
            content=batch["zip_bytes"],
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{batch["filename"]}"'},
        )
    if not plan_id or plan_id not in PLANS:
        raise HTTPException(status_code=404, detail="Plan not found.")
    stored = PLANS[plan_id]
    if format == "docx":
        return Response(
            content=stored["docx_bytes"],
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{stored["record"]["docx_filename"]}"'},
        )
    if format == "pdf":
        return Response(
            content=stored["pdf_bytes"],
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{stored["record"]["pdf_filename"]}"'},
        )
    raise HTTPException(status_code=400, detail="Format must be docx or pdf.")
