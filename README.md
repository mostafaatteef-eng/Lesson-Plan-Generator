# EBDA AI Lesson Studio

**Smart Lesson Planning, Made Simple.**

Ultra-minimal single-page lesson plan generator for **EBDA National Schools of Applied Technology** (`مدارس ابدأ الوطنية للعلوم التقنية`).

Upload educational documents → Select lessons → Generate → Download editable Word (`.docx`), PDF (`.pdf`), or Batch ZIP (`.zip`).

---

## Single-Page Interface

1. **Minimal Header:** Displays **EBDA AI Lesson Studio** and subtitle *Smart Lesson Planning, Made Simple.* (plus official EBDA logo if configured via `/api/settings`). No sidebar, no navigation tabs, no dashboard clutter.
2. **File Upload Workspace:** Three compact drag-and-drop upload cards with validation, file name/size, replace, and remove controls:
   - **Curriculum / Lesson File** (Required — `PDF`, `DOCX`, `PPTX`, `TXT`)
   - **Lesson Plan Word Template** (Required — `DOCX` only)
   - **Reference PDF** (Optional — `PDF`)
3. **Lesson Selection & Generation:** Automatically detects lessons, supports single or multi-lesson selection, provides inline boundary adjustment for uncertain ranges, hides **Grade / Subject / Lesson duration / Output language** inside a collapsed-by-default **Advanced settings** disclosure, and replaces the **Generate Lesson Plan** button with a 6-stage progress indicator while running.
4. **Results & Download:** Displays **Your Lesson Plan Is Ready** with lesson title, count, quality validation status (`Passed` / `Needs Review` / `Failed`), honest document-formatting warnings, **Download Word (.docx)**, **Download PDF (.pdf)**, and **Download All (.zip)** for multi-lesson batches.

---

## Preserved Backend & Document Fidelity Guarantees

- **Curriculum Truth:** Verbatim text extraction, Arabic/English boundary detection, and source-page traceability without fabricated content.
- **OOXML-Safe Word Generation:** Modifies text strictly inside existing `<w:t>` runs, preserving tables, column widths (`w:tcW`), merged cells, `w:bidi`/`w:bidiVisual` RTL directionality, headers, footers, checkboxes (`☐` → `☑`), `00:00` time slots, and original institutional labels.
- **PDF Conversion & Reference Validation:** Converts generated DOCX via LibreOffice headless when installed (with honest fallback reporting when `soffice` is absent), compares page count and dimensions against the optional Reference PDF, and keeps `.docx` downloadable even if PDF conversion fails.
- **Automated Quality Assurance:** Runs 4-pillar validation (Curriculum Fidelity, Pedagogical Quality, Template Fidelity, Document Integrity), strict lesson timing normalization, and measurable Bloom's Taxonomy verb checks internally on every generated plan.

---

## Run Locally

```bash
npm install
npm run dev
```

Configure `GEMINI_API_KEY` in `.env` (or AI Studio **Settings → Secrets**).

### Run Automated Tests

```bash
node --import tsx --test tests/pipeline.test.ts
```

### Python + FastAPI Deliverable

All Python/FastAPI engines and tests remain preserved under `app/` and `tests/test_pipeline.py` (see `requirements.txt`).
