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

    # The docx's own page count (explicit breaks / app metadata) can be stale:
    # the official ATS-MU file claims 4 pages but renders 5. When no reference
    # PDF was supplied and LibreOffice is available, ground the expected page
    # count in a fresh render of the EMPTY template instead.
    rendered_template_pages: Optional[int] = None
    if ref_pages is None:
        try:
            from app.engines.render_qa_engine import render_docx_to_pdf_libreoffice

            lo_pdf, ok = render_docx_to_pdf_libreoffice(docx_bytes)
            if ok and lo_pdf:
                import fitz

                pdf_doc = fitz.open(stream=lo_pdf, filetype="pdf")
                rendered_template_pages = len(pdf_doc)
                pdf_doc.close()
        except Exception:
            rendered_template_pages = None

    is_ats_mu = bool(re.search(r"ATS-MU|التكنولوجيا التطبيقية|الغرض النشاط", f"{full_text} {' '.join(locked_markers)}"))
    return TemplateSchema(
        template_id=f"tpl_{uuid.uuid4().hex[:8]}",
        filename=filename,
        language=language,  # type: ignore[arg-type]
        is_rtl=is_rtl,
        page_count_expected=ref_pages or rendered_template_pages or current_page,
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


_RTL_TEXT = re.compile(r"[\u0621-\u064A\u0660-\u0669\u06F0-\u06F9]")


def _ensure_run_rtl(r: etree._Element) -> None:
    """Mark a run as complex-script RTL so Arabic-Indic digits and slashes in
    values like '٣/١' keep their logical order at render time (without w:rtl
    LibreOffice applies LTR embedding and the class identity flips to '١/٣')."""
    rpr = r.find(_qn("rPr"))
    if rpr is None:
        rpr = etree.Element(_qn("rPr"))
        r.insert(0, rpr)
    if rpr.find(_qn("rtl")) is None:
        rtl = etree.SubElement(rpr, _qn("rtl"))
        rtl.set(_qn("val"), "1")


def _set_paragraph_text_preserve_format(p_el: etree._Element, text: str) -> None:
    """Modify ONLY <w:t> text inside existing runs so w:pPr, w:rPr, w:bidi, fonts, and colors stay untouched."""
    needs_rtl = bool(_RTL_TEXT.search(text or ""))
    runs = p_el.findall(_qn("r"))
    if not runs:
        r = etree.SubElement(p_el, _qn("r"))
        if needs_rtl:
            _ensure_run_rtl(r)
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
                if needs_rtl:
                    _ensure_run_rtl(r)
                placed = True
            else:
                t.text = ""
    if not placed:
        if needs_rtl:
            _ensure_run_rtl(runs[0])
        t = etree.SubElement(runs[0], _qn("t"))
        t.set(f"{{{XML_NS}}}space", "preserve")
        t.text = text


def _set_element_names_keep_icon(tc_el: etree._Element, names: List[str]) -> None:
    """Fill the official عناصر الدرس vMerge cell: keep the single icon
    paragraph untouched, then one compact name line per element. Name
    paragraphs are clones of the icon paragraph with the drawing removed and
    tight 9pt formatting, so the block stays within the five time rows."""
    ps = tc_el.findall(_qn("p"))
    if not ps:
        return
    icon_p = ps[0]
    # The icon paragraph carries no text; clear any stray runs' text only.
    for t in icon_p.findall(f".//{_qn('t')}"):
        t.text = ""
    # Scale the single icon down (50%) so icon + five compact name lines stay
    # within the five time rows; at original size the block outgrows them and
    # the last time cell stretches.
    for ext in icon_p.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent"):
        ext.set("cx", str(int(int(ext.get("cx", "612000")) * 0.50)))
        ext.set("cy", str(int(int(ext.get("cy", "612000")) * 0.50)))
    # Remove any pre-existing non-icon paragraphs.
    for extra in ps[1:]:
        tc_el.remove(extra)
    for name in names or [" "]:
        p = copy.deepcopy(icon_p)
        for dr in p.findall(f".//{_qn('drawing')}"):
            dr.getparent().remove(dr)
        for pic in p.findall(f".//{_qn('pict')}"):
            pic.getparent().remove(pic)
        ppr = p.find(_qn("pPr"))
        if ppr is None:
            ppr = etree.SubElement(p, _qn("pPr"))
            p.insert(0, ppr)
        for sp in ppr.findall(_qn("spacing")):
            ppr.remove(sp)
        sp = etree.SubElement(ppr, _qn("spacing"))
        sp.set(_qn("before"), "0")
        sp.set(_qn("after"), "0")
        sp.set(_qn("line"), "240")
        sp.set(_qn("lineRule"), "auto")
        _set_paragraph_text_preserve_format(p, name)
        # Compact font: override run sizes to 9pt (sz 18 half-points).
        for rpr in p.findall(f".//{_qn('rPr')}"):
            for sz in rpr.findall(_qn("sz")):
                rpr.remove(sz)
            sz = etree.SubElement(rpr, _qn("sz"))
            sz.set(_qn("val"), "18")
            for szcs in rpr.findall(_qn("szCs")):
                rpr.remove(szcs)
            szcs = etree.SubElement(rpr, _qn("szCs"))
            szcs.set(_qn("val"), "18")
        tc_el.append(p)


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




def _rewrite_same_cell_value(tc, label, value):
    """Rewrite a same-cell 'label : value' pair (official cover identity lines).

    The official template puts e.g. run0='الاسم' and run1=' : أ/ ... ' in one
    cell, so the label-cell/next-cell targeting never sees them. Replace only
    the value run, preserving its formatting. An empty value clears the stale
    text instead of inventing or retaining another person's identity.
    Returns True when a value run was rewritten.
    """
    for para in tc.findall(_qn("p")):
        runs = para.findall(_qn("r"))
        for k in range(len(runs) - 1):
            t0 = runs[k].find(_qn("t"))
            t1 = runs[k + 1].find(_qn("t"))
            if t0 is None or t1 is None:
                continue
            if (t0.text or "").strip() != label:
                continue
            after = (t1.text or "").lstrip()
            if after.startswith((":", "：")) and after.strip(" :："):
                # Colon and value in one run: ' : أ/ ... '
                t1.text = f" : {value} " if value else " : "
                t1.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                return True
            if after.strip() in (":", "：") and k + 2 < len(runs):
                # Colon-only run, value in the next run; trailing fragments
                # of the same identity line must not survive either.
                t2 = runs[k + 2].find(_qn("t"))
                if t2 is None:
                    continue
                t2.text = f" {value} " if value else " "
                t2.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                for extra in runs[k + 3:]:
                    te = extra.find(_qn("t"))
                    if te is not None and (te.text or "").strip():
                        te.text = ""
                return True
    return False


def _set_para_lines(p, lines):
    """Replace a paragraph's visible text with lines, preserving the first
    run's formatting; one run per line separated by breaks."""
    runs = p.findall(_qn("r"))
    if not runs:
        return
    first = runs[0]
    for child in list(first):
        if child.tag in (_qn("t"), _qn("br"), _qn("cr")):
            first.remove(child)
    for i, ln in enumerate(lines):
        if i:
            first.append(first.makeelement(_qn("br"), {}))
        t = first.makeelement(_qn("t"), {})
        t.text = ln
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        first.append(t)
    for r in runs[1:]:
        for t in r.findall(_qn("t")):
            t.text = ""


def _norm_opt(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def _option_selected(label, selected):
    lbl = _norm_opt(label)
    if not lbl:
        return False
    base = lbl.split("/")[0].strip()
    for s in selected:
        sn = _norm_opt(s)
        if not sn:
            continue
        if lbl == sn or base == sn or sn in lbl or lbl in sn:
            return True
    return False


_W14 = "http://schemas.microsoft.com/office/word/2010/wordml"


def _apply_sdt_checkboxes(tr, selected):
    """Check/uncheck w14 content-control checkboxes in a row.

    The official template wraps checkbox cells in row-level SDTs, invisible to
    tr.findall(tc). Each checkbox SDT follows its option label cell in document
    order. Stale checks are cleared, matching options are checked.
    Returns the number of boxes checked.
    """
    checked_n = 0
    children = list(tr)
    for i, child in enumerate(children):
        if child.tag == _qn("sdt"):
            cb = child.find(f".//{{{_W14}}}checkbox")
            if cb is None:
                continue
            # The checkbox SDT PRECEDES its option label cell in document order.
            label = ""
            for nxt_ch in children[i + 1:]:
                if nxt_ch.tag == _qn("tc"):
                    label = "".join(t.text or "" for t in nxt_ch.findall(f".//{_qn('t')}")).strip()
                    if label:
                        break
            want = _option_selected(label, selected)
            chk = cb.find(f"{{{_W14}}}checked")
            if chk is None:
                chk = cb.makeelement(f"{{{_W14}}}checked", {})
                cb.insert(0, chk)
            chk.set(f"{{{_W14}}}val", "1" if want else "0")
            for t in child.findall(f".//{_qn('t')}"):
                if t.text and ("☐" in t.text or "☑" in t.text):
                    t.text = t.text.replace("☑", "☐") if not want else t.text.replace("☐", "☑")
            if want:
                checked_n += 1
    return checked_n

def _content_tc_after(tcs, c_idx, min_w=600):
    """Return the first cell after c_idx wide enough to hold content.

    Official templates interleave narrow empty separator columns (~283 twips)
    between label and value cells; writing into one collapses the value into
    a single-character-wide vertical strip. Cells without a usable width are
    treated as content cells (previous behavior).
    """
    for j in range(c_idx + 1, len(tcs)):
        tc = tcs[j]
        tcPr = tc.find(_qn("tcPr"))
        w = None
        if tcPr is not None:
            tcW = tcPr.find(_qn("tcW"))
            if tcW is not None:
                try:
                    w = int(tcW.get(_qn("w")) or 0)
                except (TypeError, ValueError):
                    w = None
        if w is None or w >= min_w:
            return tc
    return None



def _core_lesson_name(title: str) -> str:
    """Lesson name without the 'الدرس الأول:' numbering prefix."""
    core = re.sub(r"^الدرس\s+\S+\s*[:：]\s*", "", title).strip()
    return core or title


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

    for tbl in body.findall(f".//{_qn('tbl')}"):
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

        # Official-template rubric: item cells carry auto-numbering (numPr) and
        # no literal "-1" text. Rows under a مجموعة/التقييم header get the group
        # items; the list label renders the number, so write the bare item.
        numpr_rows = [
            (ri, tr)
            for ri, tr in enumerate(trs)
            if any(tc.findall(f".//{_qn('numPr')}") for tc in tr.findall(_qn("tc")))
        ]
        if (
            len(numpr_rows) >= 3
            and ("مجموعة" in first_txt or "مجموعة" in second_txt or first_txt == "التقييم")
        ):
            rubric_tables += 1
            items = payload.rubric_group_1_items if rubric_tables == 1 else payload.rubric_group_2_items
            for k, (ri, tr) in enumerate(numpr_rows[:6]):
                val = items[k] if k < len(items) else ""
                if not val:
                    continue
                for tc in tr.findall(_qn("tc")):
                    if tc.findall(f".//{_qn('numPr')}"):
                        write_tc(tc, [val], f"rubric -{k + 1}", 220)
                        break

        section_idx = 0
        table_txt = "".join(t.text or "" for t in tbl.findall(f".//{_qn('t')}"))
        strat_table = "استراتيجات التدريس" in table_txt or "استراتيجيات التدريس" in table_txt
        res_table = "مصادر التعلم" in table_txt
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
                if not elem_m and txt == "عناصر الدرس":
                    # Official-template element table: header row carries the
                    # first "00:00" time cell, names live in the vMerge block of
                    # the next row. Only fire on that shape — the marker-style
                    # template's "عناصر الدرس" header has a plain "الزمن" cell.
                    def _time_cell(tcs_):
                        if not tcs_:
                            return None
                        last_txt = "".join(t.text or "" for t in tcs_[-1].findall(f".//{_qn('t')}")).strip()
                        return tcs_[-1] if re.match(r"^\d{2}:\d{2}$", last_txt) else None
                    elements = payload.lesson_elements[:5]
                    tcs_r = tr.findall(_qn("tc"))
                    first_time = _time_cell(tcs_r)
                    if elements and first_time is not None:
                        write_tc(first_time, [elements[0].time_formatted], "زمن العنصر 1", 12)
                        for k in range(1, len(elements)):
                            if r_idx + k < len(trs):
                                tc_k = _time_cell(trs[r_idx + k].findall(_qn("tc")))
                                if tc_k is not None:
                                    write_tc(tc_k, [elements[k].time_formatted], f"زمن العنصر {k + 1}", 12)
                        if r_idx + 1 < len(trs):
                            row_tcs = trs[r_idx + 1].findall(_qn("tc"))
                            if row_tcs:
                                # One element name per line in the vMerge names
                                # block. The original merged icon stays SINGLE:
                                # paragraph 0 keeps its drawing and takes no
                                # text; name lines are clones with the drawing
                                # stripped, set compact (10pt, no spacing) so
                                # icon + five lines stay inside the five time
                                # rows and the last time cell does not stretch.
                                names_cell = row_tcs[0]
                                _set_element_names_keep_icon(names_cell, [f"({e.time_formatted}) {e.title}" for e in elements])
                                injected_count += 1
                        continue

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

                if re.match(r"^الاسم\s*[:：]", txt):
                    if _rewrite_same_cell_value(tc, "الاسم", payload.teacher_name):
                        injected_count += 1
                    continue
                if re.match(r"^الوظيفة\s*[:：]", txt):
                    if _rewrite_same_cell_value(tc, "الوظيفة", payload.job_title):
                        injected_count += 1
                    continue

                if re.match(r"^الوحدة\s*\(", txt):
                    nn = _content_tc_after(tcs, c_idx)
                    if nn is not None:
                        write_tc(nn, [payload.unit_name], "الوحدة", 160)
                    continue
                if re.match(r"^اسم\s+الدرس", txt):
                    mname = re.match(r"^(اسم\s+الدرس)\s*", txt)
                    prefix = mname.group(1) if mname else "اسم الدرس"
                    _set_cell_lines_xml_safe(tc, [f"{prefix} {_core_lesson_name(payload.lesson_title)}"])
                    injected_count += 1
                    continue
                if re.match(r"^الدرس\s*\(", txt):
                    # Original layout: the colored label keeps its
                    # 'الدرس ( ن <name> )' shape — only the placeholder name is
                    # replaced; the wide value cell carries the total time.
                    mhead = re.match(r"^(الدرس\s*\(\s*\S+)(?:\s+.*?)?(\s*\))$", txt)
                    core_name = _core_lesson_name(payload.lesson_title)
                    if mhead:
                        _set_cell_lines_xml_safe(tc, [f"{mhead.group(1)} {core_name}{mhead.group(2)}"])
                    else:
                        _set_cell_lines_xml_safe(tc, [core_name])
                    injected_count += 1
                    # The wide value cell next to the label intentionally stays
                    # blank in the original official template.
                    continue
                if re.match(r"^الفرع\s*[:：]\s*$", txt):
                    _set_cell_lines_xml_safe(tc, [f"الفرع : {payload.branch}"])
                    injected_count += 1
                    continue
                if re.match(r"^مجموعة\s*\(\s*١\s*\)\s*$", txt):
                    nn = _content_tc_after(tcs, c_idx)
                    if nn is not None:
                        write_tc(nn, payload.assessment_group_1.splitlines(), "مجموعة ١", 500)
                    continue
                if re.match(r"^مجموعة\s*\(\s*٢\s*\)\s*$", txt):
                    nn = _content_tc_after(tcs, c_idx)
                    if nn is not None:
                        write_tc(nn, payload.assessment_group_2.splitlines(), "مجموعة ٢", 500)
                    continue
                if re.match(r"^مجموعة\s*\(\s*٣\s*\)\s*$", txt):
                    nn = _content_tc_after(tcs, c_idx)
                    if nn is not None:
                        write_tc(nn, payload.assessment_group_3.splitlines(), "مجموعة ٣", 500)
                    continue
                if txt == "استراتيجية التدريس":
                    strat = payload.element_2_strategy if element_ctx == 2 else payload.element_1_strategy
                    etime = payload.element_2_time if element_ctx == 2 else payload.element_1_time
                    _set_cell_lines_xml_safe(tc, [f"استراتيجية التدريس: {strat}"])
                    injected_count += 1
                    for cand in tcs:
                        ctxt = "".join(t.text or "" for t in cand.findall(f".//{_qn('t')}")).strip()
                        if re.match(r"^\d{2}:\d{2}$", ctxt):
                            write_tc(cand, [f"{int(etime):02d}:00" if str(etime).isdigit() else str(etime)], "زمن العنصر", 16)
                            break
                    continue
                if "إجراءات النشاط" in txt:
                    act = payload.activity_2 if element_ctx == 2 else payload.activity_1
                    nn = _content_tc_after(tcs, c_idx)
                    if nn is not None:
                        write_tc(nn, act.teacher_procedures.splitlines(), "إجراءات النشاط (المعلم)", 420)
                    if nn is not None:
                        nn_idx = list(tcs).index(nn)
                        if nn_idx + 1 < len(tcs):
                            # Official layout: teacher/student areas sit side by
                            # side in the label's own row (gridSpan columns).
                            write_tc(tcs[nn_idx + 1], act.student_procedures.splitlines(), "إجراءات النشاط (الطالب)", 420)
                        elif r_idx + 1 < len(trs):
                            row_tcs = trs[r_idx + 1].findall(_qn("tc"))
                            if nn_idx < len(row_tcs):
                                write_tc(row_tcs[nn_idx], act.student_procedures.splitlines(), "إجراءات النشاط (الطالب)", 420)
                    continue
                if "عزيزي الطالب" in txt and re.search(r"\.{3,}", txt):
                    act = payload.activity_2 if element_ctx == 2 else payload.activity_1
                    new_txt = re.sub(r"\.{3,}", "\n" + act.student_note, txt, count=1)
                    _set_cell_lines_xml_safe(tc, new_txt.splitlines())
                    injected_count += 1
                    continue

                nxt = _content_tc_after(tcs, c_idx)
                if nxt is None:
                    continue
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
                    # Official cover class grid: four slots in document order
                    # (row1 right-pair value, row1 left-pair value, row3
                    # right-pair value, row3 left-pair value). The original
                    # filled example puts the primary section in the row1
                    # RIGHT-pair value (2A) and the second in row3 RIGHT-pair
                    # (2B); left pairs are overflow. Fill in that order.
                    slot_src = [0, 2, 1, 3]
                    src_idx = slot_src[section_idx] if section_idx < len(slot_src) else section_idx
                    sec_tc = _content_tc_after(tcs, c_idx)
                    if sec_tc is not None:
                        if src_idx < len(payload.class_sections):
                            write_tc(sec_tc, [payload.class_sections[src_idx]], f"فصل {src_idx + 1}", 30)
                        else:
                            # Extra template slots must not keep another class's
                            # stale section label: clear them.
                            _set_cell_lines_xml_safe(sec_tc, [""])
                    section_idx += 1
                elif txt == "الوحدة":
                    write_tc(nxt, [payload.unit_number], txt, 60)
                elif txt == "اسم الوحدة":
                    write_tc(nxt, [payload.unit_name], txt, 160)
                elif txt == "الفرع":
                    write_tc(nxt, [payload.branch], txt, 100)
                elif re.match(r"^TPK\d*$", txt):
                    _set_cell_lines_xml_safe(tc, [payload.knowledge_code])
                    injected_count += 1
                elif "المعرفة" in txt or "TPK" in txt:
                    nxt_txt_k = "".join(t.text or "" for t in nxt.findall(f".//{_qn('t')}")).strip()
                    if not nxt_txt_k:
                        write_tc(nxt, [payload.knowledge_code], txt, 60)
                elif txt in ("الدرس", "اسم الدرس"):
                    write_tc(nxt, [payload.lesson_title], txt, 180)
                elif txt == "نواتج التعلم":
                    # Official layout: the header row's value cell carries the
                    # fixed intro 'ينبغى بنهاية الدرس...' — keep it. Each of the
                    # four following rows holds ONE outcome in its value cell
                    # (their first cells are empty vMerge continuations).
                    # Marker templates keep the old all-bullets-in-one-cell path.
                    next_first_txt = ""
                    if r_idx + 1 < len(trs):
                        next_tcs0 = trs[r_idx + 1].findall(_qn("tc"))
                        if next_tcs0:
                            next_first_txt = "".join(t.text or "" for t in next_tcs0[0].findall(f".//{_qn('t')}")).strip()
                    if nxt_txt and not next_first_txt:
                        n_out = min(4, len(payload.learning_outcomes))
                        for k in range(4):
                            if r_idx + 1 + k >= len(trs):
                                break
                            row_tcs = trs[r_idx + 1 + k].findall(_qn("tc"))
                            target = _content_tc_after(row_tcs, 0)
                            if target is None:
                                continue
                            if k < n_out:
                                oc = payload.learning_outcomes[k]
                                write_tc(target, [oc if oc.startswith("▪") else f"▪ {oc}"], f"ناتج التعلم {k + 1}", 300)
                            else:
                                _set_cell_lines_xml_safe(target, [""])
                                # Unused outcome rows stay (structure is
                                # fidelity-checked) but collapse to a hairline
                                # so they do not push later tables onto a
                                # mostly-empty spill page.
                                tr_extra = trs[r_idx + 1 + k]
                                trpr = tr_extra.find(_qn("trPr"))
                                if trpr is None:
                                    trpr = etree.SubElement(tr_extra, _qn("trPr"))
                                    tr_extra.insert(0, trpr)
                                trh = trpr.find(_qn("trHeight"))
                                if trh is None:
                                    trh = etree.SubElement(trpr, _qn("trHeight"))
                                trh.set(_qn("val"), "40")
                                trh.set(_qn("hRule"), "exact")
                    else:
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
                elif txt == "الزمن":
                    row_txt_z = "".join(t.text or "" for t in tr.findall(f".//{_qn('t')}"))
                    # Fire for the lesson-duration row (عرض الدرس, beside التاريخ)
                    # and the activity-duration rows — never for the عناصر الدرس
                    # table header, whose plain "الزمن" cell is handled there.
                    in_scope = (
                        re.match(r"^\d{2}:\d{2}$", nxt_txt)
                        or "التاريخ" in row_txt_z
                        or "نشاط" in row_txt_z
                    )
                    if in_scope and (re.match(r"^\d{2}:\d{2}$", nxt_txt) or not nxt_txt.strip()):
                        # Keep the time cell short (a long parenthetical here
                        # grew the row and split it across pages); the nesting
                        # note lives in the wide الغرض النشاط cell instead.
                        if "نشاط ( ٢" in row_txt_z or "نشاط (٢" in row_txt_z:
                            mins = payload.activity_2.duration_minutes
                        elif "نشاط ( ١" in row_txt_z or "نشاط (١" in row_txt_z:
                            mins = payload.activity_1.duration_minutes
                        else:
                            mins = payload.total_duration_minutes
                        write_tc(nxt, [f"{mins:02d}:00"], txt, 16)
                elif txt == "التهيئة":
                    write_tc(nxt, payload.warm_up.splitlines(), txt, 450)
                elif "وصف مختصر للعنصر الأول" in txt:
                    write_tc(nxt, payload.element_1_summary.splitlines(), txt, 450)
                elif "وصف مختصر للعنصر الثاني" in txt:
                    write_tc(nxt, payload.element_2_summary.splitlines(), txt, 450)
                elif "الغرض النشاط" in txt:
                    act = payload.activity_2 if ("٢" in txt or element_ctx == 2) else payload.activity_1
                    # Activity minutes are NESTED inside their element's time
                    # (9 of the element's 14), never added on top: the overview
                    # sums to the 45-minute session and the body must not read
                    # as 54. This wide cell carries the note so the narrow
                    # الزمن cell stays a bare "09:00" and the row never splits.
                    write_tc(nxt, [act.purpose, f"زمن النشاط ({act.duration_minutes:02d}:00) ضمن زمن العنصر"], txt, 320)
                elif "عزيزي الطالب" in txt:
                    act = payload.activity_2 if ("٢" in txt or element_ctx == 2) else payload.activity_1
                    write_tc(nxt, [act.student_note], txt, 320)

            # Row-level w14 checkbox SDTs (official template): النمط/النوع rows
            # select the activity's pattern/type; strategy/resource tables check
            # the payload's selected items. Stale checks are cleared.
            row_txt_full = "".join(t.text or "" for t in tr.findall(f".//{_qn('t')}"))
            if "النمط" in row_txt_full and ("فردي" in row_txt_full or "جماعي" in row_txt_full):
                act = payload.activity_2 if ("٢" in row_txt_full or element_ctx == 2) else payload.activity_1
                checkboxes_checked += _apply_sdt_checkboxes(tr, [act.pattern])
            elif "النوع" in row_txt_full and ("دراسة حالة" in row_txt_full or "بحث" in row_txt_full):
                act = payload.activity_2 if ("٢" in row_txt_full or element_ctx == 2) else payload.activity_1
                checkboxes_checked += _apply_sdt_checkboxes(tr, [act.activity_type])
            elif strat_table:
                checkboxes_checked += _apply_sdt_checkboxes(tr, payload.selected_strategies)
            elif res_table:
                checkboxes_checked += _apply_sdt_checkboxes(tr, payload.selected_resources)

    # Body-level instructional placeholders outside tables (official template
    # keeps the element summaries as body paragraphs).
    for bp in body.findall(_qn("p")):
        btxt = "".join(t.text or "" for t in bp.findall(f".//{_qn('t')}")).strip()
        if "وصف مختصر للعنصر الاول" in btxt or "وصف مختصر للعنصر الأول" in btxt:
            _set_para_lines(bp, payload.element_1_summary.splitlines())
            injected_count += 1
        elif "وصف مختصر للعنصر الثاني" in btxt:
            _set_para_lines(bp, payload.element_2_summary.splitlines())
            injected_count += 1

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
