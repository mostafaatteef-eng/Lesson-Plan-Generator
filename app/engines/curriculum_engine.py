from __future__ import annotations

import io
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.models.schemas import CurriculumUnit, LessonBoundary, PageText

LESSON_HEADER_PATTERNS = [
    re.compile(
        r"^(?:الدرس)\s+(?:الأول|الاول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر|\d+|[١-٩٠]+)\s*[:\-–—]?\s*(.*)$"
    ),
    re.compile(r"^(?:Lesson|Topic|Session|Module)\s+(\d+|[IVX]+)\s*[:\-–—]?\s*(.*)$", re.IGNORECASE),
    re.compile(r"^(?:الموضوع|المحور)\s+(?:الأول|الثاني|الثالث|الرابع|\d+)\s*[:\-–—]?\s*(.*)$"),
]

UNIT_HEADER_PATTERNS = [
    re.compile(r"^(?:الوحدة)\s+(?:الأولى|الاولى|الثانية|الثالثة|الرابعة|الخامسة|السادسة|\d+|[١-٩٠]+)\s*[:\-–—]?\s*(.*)$"),
    re.compile(r"^(?:Unit|Chapter)\s+(\d+|[IVX]+)\s*[:\-–—]?\s*(.*)$", re.IGNORECASE),
]


def detect_language(text: str) -> str:
    ar = len(re.findall(r"[\u0600-\u06FF]", text))
    en = len(re.findall(r"[A-Za-z]", text))
    if ar > 20 and en > 20:
        ratio = ar / (ar + en)
        if ratio > 0.75:
            return "ar"
        if ratio < 0.25:
            return "en"
        return "mixed"
    return "ar" if ar >= en else "en"


def extract_key_concepts(text: str) -> List[str]:
    concepts: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if len(line) <= 4:
            continue
        match = re.match(r"^(?:\d+[.)\-]|[-•▪*])\s*([^:–—\n]{4,70})", line)
        if match:
            concepts.append(match.group(1).strip())
        elif ":" in line and len(line) < 95:
            prefix = line.split(":", 1)[0].strip()
            if 4 <= len(prefix) <= 60:
                concepts.append(prefix)
        if len(concepts) >= 6:
            break
    return list(dict.fromkeys(concepts))[:6]


def _extract_pdf_pages(file_bytes: bytes) -> Tuple[List[PageText], bool, List[str]]:
    import fitz  # PyMuPDF

    warnings: List[str] = []
    ocr_used = False
    pages: List[PageText] = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    for idx, page in enumerate(doc):
        text = page.get_text("text").strip()
        if len(text) < 20:
            # Attempt Tesseract OCR (ara+eng) fallback for scanned PDFs
            try:
                import pytesseract
                from PIL import Image

                pix = page.get_pixmap(dpi=220)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                ocr_text = pytesseract.image_to_string(img, lang="ara+eng").strip()
                if ocr_text:
                    text = ocr_text
                    ocr_used = True
            except Exception as exc:
                warnings.append(f"OCR fallback unavailable on page {idx + 1}: {exc}")
        pages.append(PageText(page_number=idx + 1, text=text))
    doc.close()
    return pages, ocr_used, warnings


def _extract_docx_pages(file_bytes: bytes) -> List[PageText]:
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    buckets: List[List[str]] = [[]]
    for p in doc.paragraphs:
        if p.text.strip():
            buckets[-1].append(p.text.strip())
        xml_str = p._p.xml
        if 'w:type="page"' in xml_str:
            buckets.append([])
    for tbl in doc.tables:
        for row in tbl.rows:
            row_txt = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
            if row_txt:
                buckets[-1].append(row_txt)
    non_empty = [b for b in buckets if b] or [[""]]
    return [PageText(page_number=i + 1, text="\n".join(lines)) for i, lines in enumerate(non_empty)]


def _extract_pptx_pages(file_bytes: bytes) -> List[PageText]:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(file_bytes))
    pages: List[PageText] = []
    for idx, slide in enumerate(prs.slides):
        lines: List[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                for para in shape.text_frame.paragraphs:
                    if para.text.strip():
                        lines.append(para.text.strip())
        pages.append(PageText(page_number=idx + 1, text="\n".join(lines)))
    return pages or [PageText(page_number=1, text="")]


def _split_txt_pages(text: str) -> List[PageText]:
    if re.search(r"---\s*PAGE\s+\d+\s*---", text, re.IGNORECASE):
        chunks = [c.strip() for c in re.split(r"---\s*PAGE\s+\d+\s*---", text, flags=re.IGNORECASE)]
        preamble = chunks[0]
        body = [c for c in chunks[1:] if c]
        pages = []
        for idx, chunk in enumerate(body):
            full = f"{preamble}\n{chunk}" if idx == 0 and preamble else chunk
            pages.append(PageText(page_number=idx + 1, text=full))
        return pages or [PageText(page_number=1, text=text)]

    paragraphs = re.split(r"\n{2,}", text)
    pages: List[PageText] = []
    buf = ""
    for para in paragraphs:
        if len(buf) + len(para) > 2000 and buf:
            pages.append(PageText(page_number=len(pages) + 1, text=buf.strip()))
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf.strip():
        pages.append(PageText(page_number=len(pages) + 1, text=buf.strip()))
    return pages or [PageText(page_number=1, text=text)]


def detect_lesson_boundaries(pages: List[PageText], fallback_title: str) -> Tuple[str, List[LessonBoundary], List[str]]:
    warnings: List[str] = []
    unit_title = Path(fallback_title).stem

    for pg in pages[:2]:
        for line in pg.text.splitlines():
            clean = line.strip()
            if any(pat.match(clean) for pat in UNIT_HEADER_PATTERNS):
                unit_title = clean
                break

    # Designed session books put an overview list before the actual session
    # openings and repeat Session in running headers. Prefer opening pages
    # carrying Learning Objectives, not the table of contents or Topic rows.
    session_starts = []
    for pg in pages:
        lines = [line.strip() for line in pg.text.splitlines() if line.strip()]
        if "Learning Objectives" not in lines:
            continue
        for pos, line in enumerate(lines):
            match = re.fullmatch(r"Session\s+(\d+)", line, re.I)
            if match:
                title_lines = []
                for value in lines[pos + 1:pos + 4]:
                    if value == "Learning Objectives" or value.isdigit():
                        break
                    title_lines.append(value)
                title = line + (": " + " ".join(title_lines) if title_lines else "")
                session_starts.append((pg.page_number, int(match.group(1)), title))
                break
    if len(session_starts) >= 2 and len({x[1] for x in session_starts}) == len(session_starts):
        sessions = []
        for idx, (start, number, title) in enumerate(session_starts):
            end = session_starts[idx + 1][0] - 1 if idx + 1 < len(session_starts) else pages[-1].page_number
            raw = "\n\n".join(pg.text for pg in pages if start <= pg.page_number <= end)
            sessions.append(LessonBoundary(
                lesson_id=f"lsn_{uuid.uuid4().hex[:8]}", lesson_number=number,
                title=title, start_page=start, end_page=end, raw_text=raw,
                word_count=len(raw.split()), confidence=0.96,
                key_concepts=extract_key_concepts(raw),
            ))
        return unit_title, sessions, warnings

    flat_lines: List[Tuple[int, str, bool]] = []
    for pg in pages:
        for raw_line in pg.text.splitlines():
            clean = raw_line.strip()
            is_lesson_header = bool(clean and len(clean) <= 160 and any(p.match(clean) for p in LESSON_HEADER_PATTERNS))
            flat_lines.append((pg.page_number, raw_line, is_lesson_header))

    hit_indices = [i for i, (_, _, is_hit) in enumerate(flat_lines) if is_hit]
    if not hit_indices:
        all_text = "\n\n".join(p.text for p in pages).strip()
        warnings.append("No explicit lesson boundary headers found; flagged for human boundary review.")
        return (
            unit_title,
            [
                LessonBoundary(
                    lesson_id=f"lsn_{uuid.uuid4().hex[:8]}",
                    lesson_number=1,
                    title=unit_title,
                    start_page=1,
                    end_page=max(1, len(pages)),
                    raw_text=all_text,
                    word_count=len(all_text.split()),
                    confidence=0.55,
                    is_ambiguous=True,
                    ambiguity_reason="لم تُرصد عناوين دروس واضحة؛ جُمعت الوحدة كاملة كدرس واحد. راجع حدود الدروس قبل التوليد.",
                    approved=False,
                    key_concepts=extract_key_concepts(all_text),
                )
            ],
            warnings,
        )

    lessons: List[LessonBoundary] = []
    for idx, start_pos in enumerate(hit_indices):
        end_pos = hit_indices[idx + 1] if idx + 1 < len(hit_indices) else len(flat_lines)
        chunk = flat_lines[start_pos:end_pos]
        raw_text = "\n".join(line for _, line, _ in chunk).strip()
        start_page = chunk[0][0]
        end_page = chunk[-1][0]
        title = chunk[0][1].strip()
        word_count = len(raw_text.split())
        is_short = word_count < 30
        lessons.append(
            LessonBoundary(
                lesson_id=f"lsn_{uuid.uuid4().hex[:8]}",
                lesson_number=idx + 1,
                title=title,
                start_page=start_page,
                end_page=end_page,
                raw_text=raw_text,
                word_count=word_count,
                confidence=0.68 if is_short else 0.94,
                is_ambiguous=is_short,
                ambiguity_reason="مقطع الدرس قصير (أقل من ٣٠ كلمة)؛ أكّد صفحتي البداية والنهاية." if is_short else None,
                approved=not is_short,
                key_concepts=extract_key_concepts(raw_text),
            )
        )

    return unit_title, lessons, warnings


def ingest_curriculum(file_bytes: bytes, filename: str) -> CurriculumUnit:
    ext = Path(filename).suffix.lower().lstrip(".") or "txt"
    ocr_used = False
    warnings: List[str] = []

    if ext == "pdf":
        pages, ocr_used, warnings = _extract_pdf_pages(file_bytes)
        fmt = "pdf"
    elif ext == "docx":
        pages = _extract_docx_pages(file_bytes)
        fmt = "docx"
    elif ext == "pptx":
        pages = _extract_pptx_pages(file_bytes)
        fmt = "pptx"
    else:
        pages = _split_txt_pages(file_bytes.decode("utf-8", errors="replace"))
        fmt = "txt"

    full_text = "\n".join(p.text for p in pages)
    unit_title, lessons, boundary_warnings = detect_lesson_boundaries(pages, filename)
    # Slide decks commonly put LESSON n inside grade metadata, not as a
    # stand-alone header. Accept a single explicit cover marker only when no
    # later slide introduces another lesson; otherwise preserve human review.
    if fmt == "pptx" and lessons and lessons[0].is_ambiguous:
        cover = [line.strip() for line in pages[0].text.splitlines() if line.strip()]
        marker = re.search(r"\bLESSON\s+(\d+)\b", pages[0].text, re.I)
        later_markers = any(re.search(r"\bLESSON\s+\d+\b", pg.text, re.I) for pg in pages[1:])
        titles = [line for line in cover if not re.search(r"\b(?:grade|lesson|ms[.]?|mr[.]?)\b", line, re.I)]
        if marker and not later_markers and len(titles) >= 2 and sum(len(pg.text.split()) for pg in pages) >= 80:
            unit_title = titles[0]
            lesson_title = " - ".join(titles[:2])
            raw = "\n\n".join(pg.text for pg in pages)
            lessons = [LessonBoundary(lesson_id=f"lsn_{uuid.uuid4().hex[:8]}", lesson_number=int(marker.group(1)), title=lesson_title, start_page=1, end_page=len(pages), raw_text=raw, word_count=len(raw.split()), confidence=0.94, approved=True, key_concepts=extract_key_concepts(raw))]
            boundary_warnings = []
    return CurriculumUnit(
        unit_id=f"unit_{uuid.uuid4().hex[:8]}",
        filename=filename,
        file_format=fmt,  # type: ignore[arg-type]
        language=detect_language(full_text),  # type: ignore[arg-type]
        unit_title=unit_title,
        total_pages=len(pages),
        ocr_used=ocr_used,
        pages=pages,
        lessons=lessons,
        warnings=warnings + boundary_warnings,
    )


def update_boundaries(unit: CurriculumUnit, updates: List[Dict]) -> CurriculumUnit:
    new_lessons: List[LessonBoundary] = []
    existing_by_id = {l.lesson_id: l for l in unit.lessons}
    for idx, item in enumerate(updates):
        lid = item.get("lesson_id") or f"lsn_{uuid.uuid4().hex[:8]}"
        start_p = max(1, min(unit.total_pages, int(item["start_page"])))
        end_p = max(start_p, min(unit.total_pages, int(item["end_page"])))
        prev = existing_by_id.get(lid)
        if prev and prev.start_page == start_p and prev.end_page == end_p:
            raw_text = prev.raw_text
        else:
            raw_text = "\n\n".join(p.text for p in unit.pages if start_p <= p.page_number <= end_p).strip()
        approved = bool(item.get("approved", True))
        new_lessons.append(
            LessonBoundary(
                lesson_id=lid,
                lesson_number=idx + 1,
                title=str(item.get("title") or f"Lesson {idx + 1}").strip(),
                start_page=start_p,
                end_page=end_p,
                raw_text=raw_text,
                word_count=len(raw_text.split()),
                confidence=1.0 if approved else 0.85,
                is_ambiguous=False if approved else (prev.is_ambiguous if prev else False),
                ambiguity_reason=None if approved else (prev.ambiguity_reason if prev else None),
                approved=approved,
                key_concepts=extract_key_concepts(raw_text),
            )
        )
    unit.lessons = new_lessons
    return unit


def export_lesson_pdf(unit: CurriculumUnit, lesson: LessonBoundary, original_pdf_bytes: Optional[bytes] = None) -> bytes:
    import fitz  # PyMuPDF

    if unit.file_format == "pdf" and original_pdf_bytes:
        src = fitz.open(stream=original_pdf_bytes, filetype="pdf")
        out = fitz.open()
        start_idx = max(0, lesson.start_page - 1)
        end_idx = min(len(src) - 1, lesson.end_page - 1)
        out.insert_pdf(src, from_page=start_idx, to_page=end_idx)
        data = out.tobytes()
        src.close()
        out.close()
        return data

    out = fitz.open()
    page = out.new_page(width=595.28, height=841.89)
    header = f"Lesson {lesson.lesson_number}: {lesson.title} (Pages {lesson.start_page}-{lesson.end_page})"
    page.insert_textbox(fitz.Rect(40, 40, 555, 800), f"{header}\n\n{lesson.raw_text}", fontsize=11)
    data = out.tobytes()
    out.close()
    return data
