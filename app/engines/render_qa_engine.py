from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.models.schemas import (
    HumanApprovalGate,
    LessonBoundary,
    LessonPlanPayload,
    QACheck,
    QAPillarResult,
    QAReport,
    TemplateSchema,
    VisualDiffPage,
)

VAGUE_VERBS_AR = ["يفهم", "تفهم", "يعرف", "تعرف", "يدرك", "تدرك", "يلم ب", "يستوعب", "يتعلم"]
VAGUE_VERBS_EN = ["understand", "understands", "know", "knows", "learn", "learns", "appreciate"]


def detect_vague_verbs(outcomes: List[str]) -> List[str]:
    found: List[str] = []
    for raw in outcomes:
        clean = re.sub(r"^[▪•\-\d.\s]+", "", raw).strip()
        for v in VAGUE_VERBS_AR:
            if v in clean:
                found.append(f"{v} ({clean[:40]})")
        for v in VAGUE_VERBS_EN:
            if re.search(rf"\b{re.escape(v)}\b", clean, re.IGNORECASE):
                found.append(f"{v} ({clean[:40]})")
    return found


def render_docx_to_pdf_libreoffice(docx_bytes: bytes) -> Tuple[bytes, bool]:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise FileNotFoundError("LibreOffice (soffice) binary not found on PATH.")

    with tempfile.TemporaryDirectory(prefix="atsmu_lo_") as tmp:
        tmp_path = Path(tmp)
        in_docx = tmp_path / "lesson_plan.docx"
        in_docx.write_bytes(docx_bytes)
        proc = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(in_docx)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        out_pdf = tmp_path / "lesson_plan.pdf"
        if proc.returncode != 0 or not out_pdf.exists():
            raise RuntimeError(f"LibreOffice conversion failed: {proc.stderr or proc.stdout}")
        return out_pdf.read_bytes(), True


def _global_ssim_percent(generated, reference) -> float:
    """Global-window structural similarity, measured on matching grayscale pages.

    This is global SSIM (one window), not a sliding-window or perceptual metric.
    It is only calculated when a reference image of the same shape exists.
    """
    import numpy as np

    if generated.shape != reference.shape:
        return 0.0
    a = generated.astype(np.float64)
    b = reference.astype(np.float64)
    mean_a, mean_b = float(a.mean()), float(b.mean())
    var_a, var_b = float(a.var()), float(b.var())
    covariance = float(((a - mean_a) * (b - mean_b)).mean())
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    score = ((2 * mean_a * mean_b + c1) * (2 * covariance + c2)) / (
        (mean_a ** 2 + mean_b ** 2 + c1) * (var_a + var_b + c2)
    )
    return round(100.0 * max(0.0, min(1.0, score)), 2)


def compute_visual_diff(
    generated_pdf_bytes: bytes,
    reference_pdf_bytes: Optional[bytes],
    expected_pages: int,
    overflow_fields: List[Dict],
) -> Tuple[List[VisualDiffPage], int, int]:
    import fitz
    import numpy as np

    gen_doc = fitz.open(stream=generated_pdf_bytes, filetype="pdf")
    ref_doc = fitz.open(stream=reference_pdf_bytes, filetype="pdf") if reference_pdf_bytes else None

    gen_count = len(gen_doc)
    ref_count = len(ref_doc) if ref_doc is not None else expected_pages
    max_pages = max(gen_count, ref_count)
    results: List[VisualDiffPage] = []

    for i in range(max_pages):
        pnum = i + 1
        gen_pg = gen_doc[i] if i < gen_count else None
        ref_pg = ref_doc[i] if (ref_doc is not None and i < ref_count) else None

        gen_w, gen_h = (round(gen_pg.rect.width, 2), round(gen_pg.rect.height, 2)) if gen_pg else (0.0, 0.0)
        ref_w, ref_h = (round(ref_pg.rect.width, 2), round(ref_pg.rect.height, 2)) if ref_pg else (595.28, 841.89)

        extra_page = i >= ref_count and gen_pg is not None
        missing_page = i < ref_count and gen_pg is None
        dim_match = (not extra_page and not missing_page) and abs(gen_w - ref_w) <= 2.0 and abs(gen_h - ref_h) <= 2.0

        pixel_diff_pct = 0.0
        structural_similarity_pct = 0.0
        notes: List[str] = []

        if extra_page:
            pixel_diff_pct = 100.0
            notes.append("Extra overflow page detected beyond approved template page count.")
        elif missing_page:
            pixel_diff_pct = 100.0
            notes.append("Expected reference page is missing from rendered PDF.")
        elif gen_pg is not None and ref_pg is not None:
            g_pix = gen_pg.get_pixmap(dpi=96, colorspace=fitz.csGRAY)
            r_pix = ref_pg.get_pixmap(dpi=96, colorspace=fitz.csGRAY)
            g_arr = np.frombuffer(g_pix.samples, dtype=np.uint8).reshape(g_pix.height, g_pix.width)
            r_arr = np.frombuffer(r_pix.samples, dtype=np.uint8).reshape(r_pix.height, r_pix.width)
            min_h = min(g_arr.shape[0], r_arr.shape[0])
            min_w = min(g_arr.shape[1], r_arr.shape[1])
            diff = np.abs(g_arr[:min_h, :min_w].astype(np.int16) - r_arr[:min_h, :min_w].astype(np.int16))
            pixel_diff_pct = round(float(np.mean(diff > 18) * 100.0), 2)
            structural_similarity_pct = _global_ssim_percent(g_arr, r_arr)
            notes.append(
                f"Pixel difference: {pixel_diff_pct}%; global SSIM: "
                f"{structural_similarity_pct}% against reference."
            )
        else:
            pixel_diff_pct = 0.0
            notes.append("No Reference PDF uploaded; image comparison unavailable (metrics set to zero, not measured).")

        has_overflow = extra_page or (len(overflow_fields) > 0 and pnum in (3, 5))
        status = "fail" if (extra_page or missing_page or not dim_match) else ("warning" if has_overflow else "pass")
        results.append(
            VisualDiffPage(
                page_number=pnum,
                reference_width_pt=ref_w,
                reference_height_pt=ref_h,
                generated_width_pt=gen_w,
                generated_height_pt=gen_h,
                dimension_match=dim_match,
                pixel_diff_pct=pixel_diff_pct,
                structural_similarity_pct=structural_similarity_pct,
                overflow_detected=has_overflow,
                status=status,  # type: ignore[arg-type]
                notes=notes,
            )
        )

    gen_doc.close()
    if ref_doc is not None:
        ref_doc.close()
    return results, ref_count, gen_count


def run_four_pillar_qa(
    lesson: LessonBoundary,
    schema: TemplateSchema,
    payload: LessonPlanPayload,
    injection_metrics: Dict,
    rendered_pdf_bytes: bytes,
    libreoffice_used: bool,
    reference_pdf_bytes: Optional[bytes] = None,
) -> QAReport:
    visual_diff, expected_pages, rendered_pages = compute_visual_diff(
        rendered_pdf_bytes,
        reference_pdf_bytes,
        schema.page_count_expected,
        injection_metrics.get("overflow_fields", []),
    )

    time_sum = sum(el.duration_minutes for el in payload.lesson_elements)
    time_valid = time_sum == payload.total_duration_minutes
    vague_verbs = detect_vague_verbs(payload.learning_outcomes)
    overflow_list = [o["field_label"] for o in injection_metrics.get("overflow_fields", [])]

    verified_traces = sum(1 for t in payload.traceability if t.verified_in_source)
    total_traces = len(payload.traceability)

    p1 = _build_pillar(
        "curriculum_fidelity",
        "Curriculum Fidelity",
        [
            QACheck(
                name="Required Fields Populated",
                passed=bool(payload.lesson_title and payload.learning_outcomes and payload.lesson_elements),
                severity="info" if payload.lesson_title else "error",
                detail="All mandatory lesson fields populated from source curriculum.",
            ),
            QACheck(
                name="Source Traceability Grounding",
                passed=total_traces >= 3 and verified_traces >= max(1, int(total_traces * 0.6)),
                severity="info" if verified_traces >= max(1, int(total_traces * 0.6)) else "warning",
                detail=f"{verified_traces}/{total_traces} verbatim excerpts matched source pages {lesson.start_page}-{lesson.end_page}.",
            ),
        ],
    )

    p2 = _build_pillar(
        "pedagogical_quality",
        "Pedagogical Quality",
        [
            QACheck(
                name="Measurable Bloom Taxonomy Verbs",
                passed=len(vague_verbs) == 0,
                severity="info" if not vague_verbs else "error",
                detail="No vague verbs found." if not vague_verbs else f"Vague verbs detected: {', '.join(vague_verbs)}",
            ),
            QACheck(
                name="Strict Time Allocation Sum",
                passed=time_valid,
                severity="info" if time_valid else "error",
                detail=f"Element time sum = {time_sum} min vs target {payload.total_duration_minutes} min.",
            ),
        ],
    )

    geom_ok = (
        injection_metrics.get("tables_before") == injection_metrics.get("tables_after")
        and injection_metrics.get("cells_before") == injection_metrics.get("cells_after")
        and bool(injection_metrics.get("widths_unchanged"))
    )
    # Page-count policy: exact match expected; ONE extra page is tolerated as a
    # warning (approved product policy for fully filled fixed-layout forms;
    # geometry and content stay untouched). Fewer pages than expected still
    # means lost content and stays blocking.
    pages_exact = rendered_pages == expected_pages
    pages_ok = expected_pages <= rendered_pages <= expected_pages + 1
    p3 = _build_pillar(
        "template_fidelity",
        "Template Fidelity",
        [
            QACheck(
                name="Table Geometry & w:tcW Widths",
                passed=geom_ok,
                severity="info" if geom_ok else "error",
                detail=f"Tables/cells unchanged and w:tcW preserved={injection_metrics.get('widths_unchanged')}.",
            ),
            QACheck(
                name="RTL w:bidi & Page Count Guard",
                passed=bool(injection_metrics.get("bidi_preserved")) and pages_ok and len(overflow_list) == 0,
                severity="error" if not pages_ok else ("warning" if (overflow_list or not pages_exact) else "info"),
                detail=f"Pages {rendered_pages}/{expected_pages} (tolerance +1), overflow cells={len(overflow_list)}.",
            ),
        ],
    )

    p4 = _build_pillar(
        "document_integrity",
        "Document Integrity",
        [
            QACheck(
                name="Non-Empty Rendered PDF",
                passed=len(rendered_pdf_bytes) > 500 and rendered_pages > 0,
                severity="info" if len(rendered_pdf_bytes) > 500 else "error",
                detail=f"PDF size {len(rendered_pdf_bytes)} bytes across {rendered_pages} pages.",
            )
        ],
    )

    pillars = [p1, p2, p3, p4]
    gates: List[HumanApprovalGate] = []
    if lesson.is_ambiguous and not lesson.approved:
        gates.append(
            HumanApprovalGate(
                gate_id="gate_boundary",
                category="ambiguous_boundary",
                severity="blocking",
                message=lesson.ambiguity_reason or "حدود الدرس غير واضحة وتحتاج اعتماد المعلم قبل التوليد.",
            )
        )
    if not pages_ok:
        gates.append(
            HumanApprovalGate(
                gate_id="gate_page_count",
                category="layout_deviation",
                severity="blocking",
                message=f"عدد صفحات الناتج ({rendered_pages}) يتجاوز قالب الاعتماد ({expected_pages}) بأكثر من صفحة أو يقل عنها.",
            )
        )
    if vague_verbs:
        gates.append(
            HumanApprovalGate(
                gate_id="gate_vague_verbs",
                category="pedagogical_flag",
                severity="blocking",
                message=f"رُصدت أفعال غير قابلة للقياس في نواتج التعلم: {', '.join(vague_verbs)}.",
                field_key="learning_outcomes",
            )
        )
    for idx, field_name in enumerate(overflow_list):
        gates.append(
            HumanApprovalGate(
                gate_id=f"gate_overflow_{idx}",
                category="cell_overflow",
                severity="warning",
                message=f"Cell '{field_name}' exceeded estimated capacity.",
                field_key=field_name,
            )
        )

    score = int(round(sum(p.score for p in pillars) / len(pillars)))
    status = "fail" if any(p.status == "fail" for p in pillars) else ("warning" if gates else "pass")
    return QAReport(
        overall_status=status,  # type: ignore[arg-type]
        overall_score=score,
        time_sum_minutes=time_sum,
        target_duration_minutes=payload.total_duration_minutes,
        time_sum_valid=time_valid,
        vague_verbs_found=vague_verbs,
        overflow_fields=overflow_list,
        page_count_expected=expected_pages,
        page_count_rendered=rendered_pages,
        libreoffice_used=libreoffice_used,
        pillars=pillars,
        visual_diff=visual_diff,
        approval_gates=gates,
    )


def _build_pillar(pillar_id: str, title: str, checks: List[QACheck]) -> QAPillarResult:
    passed = sum(1 for c in checks if c.passed)
    has_err = any((not c.passed) and c.severity == "error" for c in checks)
    has_warn = any((not c.passed) and c.severity == "warning" for c in checks)
    return QAPillarResult(
        pillar=pillar_id,  # type: ignore[arg-type]
        title=title,
        status="fail" if has_err else ("warning" if has_warn else "pass"),
        score=int(round((passed / max(1, len(checks))) * 100)),
        checks=checks,
    )
