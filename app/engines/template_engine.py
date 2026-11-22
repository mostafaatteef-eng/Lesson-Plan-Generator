from __future__ import annotations

import copy
import io
import re
import uuid
from typing import Dict, List, Optional, Tuple

from lxml import etree

from app.models.schemas import (
    LessonPlanPayload,
    TemplateField,
    TemplateSchema,
    TemplateTableSummary,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def _qn(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _dxa_to_pt(dxa: int) -> float:
    return round(dxa / 20.0, 2)


def _estimate_max_chars(width_dxa: int, field_type: str) -> int:
    inches = max(0.8, width_dxa / 1440.0)
    per_line = int(round(inches * 14))
    if field_type in ("multiline", "bullet_list", "rubric_list"):
        return per_line * 6
    if field_type == "time_slot":
        return 12
    return max(40, per_line * 2)


def _normalize_label(raw: str, counts: Dict[str, int]) -> str:
    clean = re.sub(r"\s+", " ", raw).strip()
    mapping = [
        (r"^برنامج\s*\/\s*مقرر$", "program_or_course"),
        (r"^البرنامج\s*\/\s*المقرر$", "program_or_course_meta"),
        (r"^الاسم$", "teacher_name"),
        (r"^الوظيفة$", "job_title"),
        (r"^العام الدراسي$", "academic_year"),
        (r"^المدرسة$", "school_name"),
        (r"^الصف$", "grade_level"),
        (r"^فصل$", "class_sections"),
        (r"^الوحدة$", "unit_number"),
        (r"^اسم الوحدة$", "unit_name"),
        (r"^الفرع$", "branch"),
        (r"المعرفة|TPK", "knowledge_code"),
        (r"^الدرس$", "lesson_title"),
        (r"^اسم الدرس$", "lesson_title_presentation"),
        (r"نواتج التعلم|learning outcomes", "learning_outcomes"),
        (r"استراتيجيات التدريس|teaching strategies", "selected_strategies"),
        (r"مصادر التعلم|learning resources", "selected_resources"),
        (r"التقييم.*مجموعة.*١", "assessment_group_1"),
        (r"التقييم.*مجموعة.*٢", "assessment_group_2"),
        (r"مجموعة.*٣", "assessment_group_3"),
        (r"^التهيئة$", "warm_up"),
        (r"الغرض النشاط|انشاط", "activity_purpose"),
        (r"عزيزي الطالب", "student_note"),
    ]
    base = ""
    for pattern, key in mapping:
        if re.search(pattern, clean, re.IGNORECASE):
            base = key
            break
    if not base:
        base = re.sub(r"[^\w\u0600-\u06FF]+", "_", clean.lower()).strip("_")[:40] or "field"
    counts[base] = counts.get(base, 0) + 1
    return base if counts[base] == 1 else f"{base}_{counts[base]}"


def extract_template_schema(
    docx_bytes: bytes,
    filename: str,
    reference_pdf_bytes: Optional[bytes] = None,
    reference_pdf_filename: Optional[str] = None,
) -> TemplateSchema:
    from docx import Document

    doc = Document(io.BytesIO(docx_bytes))
    sect = doc.sections[0]
    page_w = round(sect.page_width.pt, 2) if sect.page_width else 595.28
    page_h = round(sect.page_height.pt, 2) if sect.page_height else 841.89
    margins = {
        "top": round(sect.top_margin.pt, 2) if sect.top_margin else 56.7,
        "bottom": round(sect.bottom_margin.pt, 2) if sect.bottom_margin else 56.7,
        "left": round(sect.left_margin.pt, 2) if sect.left_margin else 56.7,
        "right": round(sect.right_margin.pt, 2) if sect.right_margin else 56.7,
    }

    locked_markers: List[str] = []
    for s in doc.sections:
        for container in (s.header, s.footer):
            txt = " ".join(p.text.strip() for p in container.paragraphs if p.text.strip())
            if txt and txt not in locked_markers:
                locked_markers.append(txt)

    body_el = doc.element.body
    bidi_count = len(body_el.findall(f".//{_qn('bidi')}")) + len(body_el.findall(f".//{_qn('bidiVisual')}"))
    full_text = " ".join(t.text or "" for t in body_el.findall(f".//{_qn('t')}"))
    ar_chars = len(re.findall(r"[\u0600-\u06FF]", full_text))
    en_chars = len(re.findall(r"[A-Za-z]", full_text))
    language = "ar" if ar_chars >= en_chars else "en"
    if ar_chars > 20 and en_chars > 20 and 0.25 <= ar_chars / (ar_chars + en_chars) <= 0.75:
        language = "mixed"
    is_rtl = bidi_count > 0 or language == "ar"

    current_page = 1
    table_idx = 0
    tables: List[TemplateTableSummary] = []
    fields: List[TemplateField] = []
    occ: Dict[str, int] = {}

    for child in body_el:
        if child.tag == _qn("p"):
            txt = "".join(t.text or "" for t in child.findall(f".//{_qn('t')}")).strip()
            if re.search(r"ATS-MU|التكنولوجيا التطبيقية|تحضير برنامج", txt) and txt not in locked_markers:
                locked_markers.append(txt)
            for br in child.findall(f".//{_qn('br')}"):
                if br.get(_qn("type")) == "page":
                    current_page += 1
        elif child.tag == _qn("tbl"):
            tbl_pr = child.find(_qn("tblPr"))
            tbl_rtl = (tbl_pr is not None and tbl_pr.find(_qn("bidiVisual")) is not None) or is_rtl
            tbl_grid = child.find(_qn("tblGrid"))
            col_widths = (
                [int(gc.get(_qn("w")) or 2400) for gc in tbl_grid.findall(_qn("gridCol"))]
                if tbl_grid is not None
                else []
            )
            trs = child.findall(_qn("tr"))
            merged_cells = 0
            max_cols = len(col_widths)

            for r_idx, tr in enumerate(trs):
                tcs = tr.findall(_qn("tc"))
                max_cols = max(max_cols, len(tcs))
                for c_idx, tc in enumerate(tcs):
                    tc_pr = tc.find(_qn("tcPr"))
                    tc_w_el = tc_pr.find(_qn("tcW")) if tc_pr is not None else None
                    tc_w = int(tc_w_el.get(_qn("w")) or (col_widths[c_idx] if c_idx < len(col_widths) else 2400))
                    is_merged = bool(
                        tc_pr is not None
                        and (tc_pr.find(_qn("gridSpan")) is not None or tc_pr.find(_qn("vMerge")) is not None)
                    )
                    if is_merged:
                        merged_cells += 1

                    cell_text = "\n".join(
                        "".join(t.text or "" for t in p.findall(f".//{_qn('t')}"))
                        for p in tc.findall(_qn("p"))
                    ).strip()
                    prev_label = (
                        "".join(t.text or "" for t in tcs[c_idx - 1].findall(f".//{_qn('t')}")).strip()
                        if c_idx > 0
                        else ""
                    )

                    if "☐" in cell_text or "☑" in cell_text:
                        opts = [o.strip() for o in re.split(r"[☐☑]", cell_text)[1:] if o.strip()]
                        fields.append(
                            TemplateField(
                                field_id=f"f_t{table_idx}_r{r_idx}_c{c_idx}",
                                label=prev_label or cell_text[:40],
                                normalized_key=_normalize_label(prev_label or cell_text, occ),
                                page_hint=current_page,
                                field_type="checkbox_group",
                                table_index=table_idx,
                                row_index=r_idx,
                                col_index=c_idx,
                                is_rtl=tbl_rtl,
                                max_chars=_estimate_max_chars(tc_w, "checkbox_group"),
                                current_value=cell_text,
                                checkbox_options=opts,
                                is_merged=is_merged,
                                locked_label=prev_label or None,
                            )
                        )
                    elif re.match(r"^\d{2}:\d{2}$", cell_text):
                        fields.append(
                            TemplateField(
                                field_id=f"f_t{table_idx}_r{r_idx}_c{c_idx}",
                                label=f"{prev_label or 'الزمن'} (00:00)",
                                normalized_key=f"time_slot_t{table_idx}_r{r_idx}_c{c_idx}",
                                page_hint=current_page,
                                field_type="time_slot",
                                table_index=table_idx,
                                row_index=r_idx,
                                col_index=c_idx,
                                is_rtl=False,
                                max_chars=10,
                                current_value=cell_text,
                                has_time_placeholder=True,
                                is_merged=is_merged,
                            )
                        )
                    elif "▪" in cell_text:
                        fields.append(
                            TemplateField(
                                field_id=f"f_t{table_idx}_r{r_idx}_c{c_idx}",
                                label=prev_label or "نواتج التعلم",
                                normalized_key=_normalize_label(prev_label or "نواتج التعلم", occ),
                                page_hint=current_page,
                                field_type="bullet_list",
                                table_index=table_idx,
                                row_index=r_idx,
                                col_index=c_idx,
                                is_rtl=tbl_rtl,
                                max_chars=_estimate_max_chars(tc_w, "bullet_list"),
                                current_value=cell_text,
                                is_merged=is_merged,
                                locked_label=prev_label or None,
                            )
                        )
                    elif re.match(r"^-\d+\s*$", cell_text):
                        fields.append(
                            TemplateField(
                                field_id=f"f_t{table_idx}_r{r_idx}_c{c_idx}",
                                label=f"Rubric {cell_text}",
                                normalized_key=f"rubric_t{table_idx}_r{r_idx}",
                                page_hint=current_page,
                                field_type="rubric_list",
                                table_index=table_idx,
                                row_index=r_idx,
                                col_index=c_idx,
                                is_rtl=tbl_rtl,
                                max_chars=_estimate_max_chars(tc_w, "text"),
                                current_value=cell_text,
                                is_merged=is_merged,
                            )
                        )
                    elif (cell_text == "" or re.match(r"^(?:TPK00|2025/2024|٢٠٢٥-٢٠٢٦|2 A|2B)$", cell_text)) and prev_label:
                        ftype = "multiline" if tc_w >= 6000 else "text"
                        fields.append(
                            TemplateField(
                                field_id=f"f_t{table_idx}_r{r_idx}_c{c_idx}",
                                label=prev_label,
                                normalized_key=_normalize_label(prev_label, occ),
                                page_hint=current_page,
                                field_type=ftype,  # type: ignore[arg-type]
                                table_index=table_idx,
                                row_index=r_idx,
                                col_index=c_idx,
                                is_rtl=tbl_rtl,
                                max_chars=_estimate_max_chars(tc_w, ftype),
                                current_value=cell_text,
                                is_merged=is_merged,
                                locked_label=prev_label,
                            )
                        )

            tables.append(
                TemplateTableSummary(
                    table_index=table_idx,
                    page_hint=current_page,
                    rows=len(trs),
                    cols=max_cols,
                    is_rtl=tbl_rtl,
                    merged_cells=merged_cells,
                    column_widths_dxa=col_widths,
                )
            )
            table_idx += 1

    ref_pages: Optional[int] = None
    if reference_pdf_bytes:
        try:
            import fitz

            pdf_doc = fitz.open(stream=reference_pdf_bytes, filetype="pdf")
            ref_pages = len(pdf_doc)
            pdf_doc.close()
        except Exception:
            ref_pages = None

    is_ats_mu = bool(re.search(r"ATS-MU|التكنولوجيا التطبيقية|الغرض النشاط", f"{full_text} {' '.join(locked_markers)}"))
    return TemplateSchema(
        template_id=f"tpl_{uuid.uuid4().hex[:8]}",
        filename=filename,
        language=language,  # type: ignore[arg-type]
        is_rtl=is_rtl,
        page_count_expected=ref_pages or current_page,
        page_width_pt=page_w,
        page_height_pt=page_h,
        margins_pt=margins,
        template_profile="ATS-MU 6-Page Arabic RTL Lesson Plan" if is_ats_mu else "Custom DOCX Template",
        locked_identity_markers=locked_markers,
        tables=tables,
        fields=fields,
        has_reference_pdf=reference_pdf_bytes is not None,
        reference_pdf_filename=reference_pdf_filename,
        reference_pdf_pages=ref_pages,
    )


def apply_checkbox_selections(original_text: str, selected_items: List[str]) -> str:
    norm_sel = [re.sub(r"[أإآ]", "ا", re.sub(r"\s+", " ", s).strip()) for s in selected_items if s.strip()]
    parts = re.split(r"(?=[☐☑])", original_text)
    out: List[str] = []
    for part in parts:
        if not part.startswith(("☐", "☑")):
            out.append(part)
            continue
        label = re.sub(r"[أإآ]", "ا", part[1:].strip())
        checked = any(label == s or s in label or label in s for s in norm_sel)
        out.append(("☑" if checked else "☐") + part[1:])
    return "".join(out)


def _set_paragraph_text_preserve_format(p_el: etree._Element, text: str) -> None:
    """Modify ONLY <w:t> text inside existing runs so w:pPr, w:rPr, w:bidi, fonts, and colors stay untouched."""
    runs = p_el.findall(_qn("r"))
    if not runs:
        r = etree.SubElement(p_el, _qn("r"))
        t = etree.SubElement(r, _qn("t"))
        t.set(f"{{{XML_NS}}}space", "preserve")
        t.text = text
        return

    placed = False
    for r in runs:
        for t in r.findall(_qn("t")):
            if not placed:
                t.set(f"{{{XML_NS}}}space", "preserve")
                t.text = text
                placed = True
            else:
                t.text = ""
    if not placed:
        t = etree.SubElement(runs[0], _qn("t"))
        t.set(f"{{{XML_NS}}}space", "preserve")
        t.text = text


def _set_cell_lines_xml_safe(tc_el: etree._Element, lines: List[str]) -> None:
    """Update paragraphs in-place and clone last paragraph XML (copy.deepcopy) only for extra lines."""
    clean_lines = lines or [" "]
    existing_ps = tc_el.findall(_qn("p"))
    if not existing_ps:
        return
    for idx, line in enumerate(clean_lines):
        if idx < len(existing_ps):
            _set_paragraph_text_preserve_format(existing_ps[idx], line)
        else:
            cloned_p = copy.deepcopy(existing_ps[-1])
            _set_paragraph_text_preserve_format(cloned_p, line)
            tc_el.append(cloned_p)
    for idx in range(len(clean_lines), len(existing_ps)):
        _set_paragraph_text_preserve_format(existing_ps[idx], "")


def inject_lesson_plan_xml_safe(
    template_bytes: bytes,
    payload: LessonPlanPayload,
) -> Tuple[bytes, Dict]:
    """Inject lesson plan content into an existing .docx with zero unauthorized formatting changes."""
    from docx import Document

    doc = Document(io.BytesIO(template_bytes))
    body = doc.element.body

    tables_before = len(body.findall(f".//{_qn('tbl')}"))
    cells_before = len(body.findall(f".//{_qn('tc')}"))
    bidi_before = len(body.findall(f".//{_qn('bidi')}")) + len(body.findall(f".//{_qn('bidiVisual')}"))
    widths_before = [el.get(_qn("w")) for el in body.findall(f".//{_qn('tcW')}")]

    injected_count = 0
    checkboxes_checked = 0
    overflow_fields: List[Dict] = []

    def write_tc(tc_el: etree._Element, lines: List[str], label: str, max_chars: int = 400) -> None:
        nonlocal injected_count
        _set_cell_lines_xml_safe(tc_el, lines)
        injected_count += 1
        joined = " ".join(lines)
        if len(joined) > max_chars:
            overflow_fields.append({"field_label": label, "char_count": len(joined), "max_chars": max_chars})

    rubric_tables = 0
    activity_rows = 0
    element_ctx = 1

    for tbl in body.findall(_qn("tbl")):
        trs = tbl.findall(_qn("tr"))
        first_txt = "".join(t.text or "" for t in trs[0].findall(f".//{_qn('t')}")).strip() if trs else ""
        second_txt = "".join(t.text or "" for t in trs[1].findall(f".//{_qn('t')}")).strip() if len(trs) > 1 else ""

        if re.match(r"^-1\s*$", second_txt) and len(trs) >= 7:
            rubric_tables += 1
            items = payload.rubric_group_1_items if rubric_tables == 1 else payload.rubric_group_2_items
            for k in range(6):
                val = items[k] if k < len(items) else ""
                tc0 = trs[k + 1].findall(_qn("tc"))[0]
                write_tc(tc0, [f"-{k + 1} {val}".strip()], f"{first_txt} -{k + 1}", 220)
            continue

        for r_idx, tr in enumerate(trs):
            tcs = tr.findall(_qn("tc"))
            if r_idx > 0 and len(tcs) == 2:
                prev_row = "".join(t.text or "" for t in trs[r_idx - 1].findall(f".//{_qn('t')}"))
                if "إجراءات النشاط" in prev_row:
                    act = payload.activity_2 if ("٢" in prev_row or activity_rows > 0) else payload.activity_1
                    write_tc(tcs[0], act.teacher_procedures.splitlines(), "إجراءات النشاط (المعلم)", 420)
                    write_tc(tcs[1], act.student_procedures.splitlines(), "إجراءات النشاط (الطالب)", 420)
                    activity_rows += 1
                    continue

            if r_idx > 0 and len(tcs) == 1:
                prev_row = "".join(t.text or "" for t in trs[r_idx - 1].findall(f".//{_qn('t')}")).strip()
                if re.search(r"مجموعة.*٣", prev_row):
                    write_tc(tcs[0], payload.assessment_group_3.splitlines(), "مجموعة ( ٣ )", 900)
                    continue

            for c_idx, tc in enumerate(tcs):
                txt = "".join(t.text or "" for t in tc.findall(f".//{_qn('t')}")).strip()

                elem_m = re.match(r"^([1-5])-\s*$", txt)
                if elem_m:
                    idx = int(elem_m.group(1)) - 1
                    if idx < len(payload.lesson_elements):
                        el = payload.lesson_elements[idx]
                        write_tc(tc, [f"{idx + 1}- {el.title}"], f"عنصر الدرس {idx + 1}", 180)
                        if c_idx + 1 < len(tcs):
                            write_tc(tcs[c_idx + 1], [el.time_formatted], f"زمن العنصر {idx + 1}", 12)
                    continue

                if "☐" in txt or "☑" in txt:
                    prev_lbl = "".join(t.text or "" for t in tcs[c_idx - 1].findall(f".//{_qn('t')}")).strip() if c_idx > 0 else ""
                    row_txt = "".join(t.text or "" for t in tr.findall(f".//{_qn('t')}"))
                    selected: List[str] = []
                    if "استراتيجيات التدريس" in prev_lbl:
                        selected = payload.selected_strategies
                    elif "مصادر التعلم" in prev_lbl:
                        selected = payload.selected_resources
                    elif "فردي" in txt or "جماعي" in txt:
                        selected = [payload.activity_2.pattern if "٢" in row_txt else payload.activity_1.pattern]
                    elif "دراسة حالة" in txt or "بحث" in txt:
                        selected = [payload.activity_2.activity_type if "٢" in row_txt else payload.activity_1.activity_type]
                    if selected:
                        updated = apply_checkbox_selections(txt, selected)
                        checkboxes_checked += updated.count("☑")
                        _set_cell_lines_xml_safe(tc, [updated])
                        injected_count += 1
                    continue

                if re.search(r"أولا.*العنصر", txt):
                    element_ctx = 1
                    if c_idx + 1 < len(tcs):
                        write_tc(tcs[c_idx + 1], [f"استراتيجية التدريس: {payload.element_1_strategy}"], "استراتيجية العنصر الأول", 120)
                    if c_idx + 2 < len(tcs):
                        write_tc(tcs[c_idx + 2], [payload.element_1_time], "زمن العنصر الأول", 12)
                    continue
                if re.search(r"ثانيا.*العنصر", txt):
                    element_ctx = 2
                    if c_idx + 1 < len(tcs):
                        write_tc(tcs[c_idx + 1], [f"استراتيجية التدريس: {payload.element_2_strategy}"], "استراتيجية العنصر الثاني", 120)
                    if c_idx + 2 < len(tcs):
                        write_tc(tcs[c_idx + 2], [payload.element_2_time], "زمن العنصر الثاني", 12)
                    continue

                if c_idx + 1 >= len(tcs):
                    continue
                nxt = tcs[c_idx + 1]
                nxt_txt = "".join(t.text or "" for t in nxt.findall(f".//{_qn('t')}")).strip()

                if re.match(r"^برنامج\s*\/\s*مقرر$|^البرنامج\s*\/\s*المقرر$", txt):
                    write_tc(nxt, [payload.program_or_course], txt, 140)
                elif txt == "الاسم":
                    write_tc(nxt, [payload.teacher_name], txt, 120)
                elif txt == "الوظيفة":
                    write_tc(nxt, [payload.job_title], txt, 120)
                elif txt == "العام الدراسي":
                    write_tc(nxt, [payload.academic_year], txt, 40)
                elif txt == "المدرسة":
                    write_tc(nxt, [payload.school_name], txt, 160)
                elif txt == "الصف":
                    write_tc(nxt, [payload.grade_level], txt, 80)
                elif txt == "فصل":
                    for s_i, sec in enumerate(payload.class_sections):
                        if c_idx + 1 + s_i < len(tcs):
                            write_tc(tcs[c_idx + 1 + s_i], [sec], f"فصل {s_i + 1}", 30)
                elif txt == "الوحدة":
                    write_tc(nxt, [payload.unit_number], txt, 60)
                elif txt == "اسم الوحدة":
                    write_tc(nxt, [payload.unit_name], txt, 160)
                elif txt == "الفرع":
                    write_tc(nxt, [payload.branch], txt, 100)
                elif "المعرفة" in txt or "TPK" in txt:
                    write_tc(nxt, [payload.knowledge_code], txt, 60)
                elif txt in ("الدرس", "اسم الدرس"):
                    write_tc(nxt, [payload.lesson_title], txt, 180)
                elif txt == "نواتج التعلم":
                    bullets = [o if o.startswith("▪") else f"▪ {o}" for o in payload.learning_outcomes[:4]]
                    write_tc(nxt, bullets, txt, 600)
                elif re.search(r"التقييم.*مجموعة.*١", txt):
                    write_tc(nxt, payload.assessment_group_1.splitlines(), txt, 500)
                elif re.search(r"التقييم.*مجموعة.*٢", txt):
                    write_tc(nxt, payload.assessment_group_2.splitlines(), txt, 500)
                elif txt == "الفصل":
                    write_tc(nxt, [payload.presentation_class], txt, 40)
                elif txt == "المكان":
                    write_tc(nxt, [payload.location], txt, 80)
                elif txt == "التاريخ":
                    write_tc(nxt, [payload.lesson_date], txt, 40)
                elif txt == "الزمن" and re.match(r"^\d{2}:\d{2}$", nxt_txt):
                    write_tc(nxt, [f"{payload.total_duration_minutes:02d}:00"], txt, 16)
                elif txt == "التهيئة":
                    write_tc(nxt, payload.warm_up.splitlines(), txt, 450)
                elif "وصف مختصر للعنصر الأول" in txt:
                    write_tc(nxt, payload.element_1_summary.splitlines(), txt, 450)
                elif "وصف مختصر للعنصر الثاني" in txt:
                    write_tc(nxt, payload.element_2_summary.splitlines(), txt, 450)
                elif "الغرض النشاط" in txt:
                    act = payload.activity_2 if ("٢" in txt or element_ctx == 2) else payload.activity_1
                    write_tc(nxt, [act.purpose], txt, 320)
                elif "عزيزي الطالب" in txt:
                    act = payload.activity_2 if ("٢" in txt or element_ctx == 2) else payload.activity_1
                    write_tc(nxt, [act.student_note], txt, 320)

    tables_after = len(body.findall(f".//{_qn('tbl')}"))
    cells_after = len(body.findall(f".//{_qn('tc')}"))
    bidi_after = len(body.findall(f".//{_qn('bidi')}")) + len(body.findall(f".//{_qn('bidiVisual')}"))
    widths_after = [el.get(_qn("w")) for el in body.findall(f".//{_qn('tcW')}")]

    out_buf = io.BytesIO()
    doc.save(out_buf)
    metrics = {
        "injected_count": injected_count,
        "checkboxes_checked": checkboxes_checked,
        "overflow_fields": overflow_fields,
        "tables_before": tables_before,
        "tables_after": tables_after,
        "cells_before": cells_before,
        "cells_after": cells_after,
        "widths_unchanged": widths_before == widths_after,
        "bidi_preserved": bidi_after >= bidi_before,
    }
    return out_buf.getvalue(), metrics
