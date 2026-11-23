from __future__ import annotations

import io
import json
from unittest.mock import patch

import fitz
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.engines.ai_engine import normalize_element_durations
from app.engines.curriculum_engine import export_lesson_pdf, ingest_curriculum
from app.engines.render_qa_engine import compute_visual_diff, detect_vague_verbs
from app.engines.template_engine import (
    apply_checkbox_selections,
    extract_template_schema,
    inject_lesson_plan_xml_safe,
)
from app import flask_app as fa
from app.models.schemas import (
    ActivityPlan,
    LessonElementPlan,
    LessonPlanPayload,
    TraceabilityEntry,
)


def _make_sample_rtl_docx() -> bytes:
    doc = Document()
    tbl = doc.add_table(rows=6, cols=2)
    tbl_pr = tbl._tbl.tblPr
    tbl_pr.append(OxmlElement("w:bidiVisual"))

    pairs = [
        ("الدرس", " "),
        ("نواتج التعلم", "▪ "),
        ("1-", "00:00"),
        ("استراتيجيات التدريس", "☐ المحاضرة   ☐ مناقشة وحوار   ☐ تعلم تعاوني   ☐ لعب ادوار"),
        ("الغرض النشاط", " "),
        ("التهيئة", " "),
    ]
    for r_idx, (left, right) in enumerate(pairs):
        row = tbl.rows[r_idx]
        for c_idx, txt in enumerate((left, right)):
            cell = row.cells[c_idx]
            p = cell.paragraphs[0]
            p._p.get_or_add_pPr().append(OxmlElement("w:bidi"))
            p.text = txt
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = OxmlElement("w:tcW")
            tc_w.set(qn("w:w"), "4500")
            tc_w.set(qn("w:type"), "dxa")
            tc_pr.append(tc_w)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_sample_payload(total_minutes: int = 45) -> LessonPlanPayload:
    return LessonPlanPayload(
        program_or_course="أنظمة التحكم المنطقي المبرمج PLC",
        teacher_name="م. أحمد محمود",
        job_title="معلم أول أتمتة",
        academic_year="٢٠٢٥-٢٠٢٦",
        school_name="مدرسة التكنولوجيا التطبيقية",
        grade_level="الصف الثاني",
        class_sections=["2 A", "2B"],
        unit_number="الوحدة الثالثة",
        unit_name="أنظمة التحكم المنطقي المبرمج",
        branch="الأتمتة الصناعية",
        knowledge_code="TPK04",
        lesson_title="مكونات وحدة التحكم المنطقي المبرمج وبنيتها",
        learning_outcomes=[
            "يحدد المكونات الخمسة الرئيسية لوحدة التحكم المنطقي المبرمج PLC.",
            "يقارن بين وظائف وحدات الإدخال الرقمية ووحدات الإخراج.",
            "يشرح مراحل دورة المسح Scan Cycle بالترتيب الصحيح.",
            "يرسم مخططاً صندوقياً لمسار الإشارة داخل الـ PLC.",
        ],
        lesson_elements=[
            LessonElementPlan(index=1, title="مقدمة عن الـ PLC", duration_minutes=8, time_formatted="08:00"),
            LessonElementPlan(index=2, title="وحدة المعالجة والذاكرة", duration_minutes=10, time_formatted="10:00"),
            LessonElementPlan(index=3, title="وحدات الإدخال والإخراج", duration_minutes=12, time_formatted="12:00"),
            LessonElementPlan(index=4, title="تطبيق عملي على S7-1200", duration_minutes=10, time_formatted="10:00"),
            LessonElementPlan(index=5, title="التقويم الختامي", duration_minutes=5, time_formatted="05:00"),
        ],
        selected_strategies=["مناقشة وحوار", "تعلم تعاوني"],
        selected_resources=["دليل الطالب", "عرض تقديمي"],
        assessment_group_1="قارن بين وحدة الإدخال ووحدة الإخراج.",
        assessment_group_2="رتب مراحل دورة المسح.",
        assessment_group_3="حدد وظيفة العازل الضوئي Optocoupler.",
        presentation_class="2 A",
        location="معمل PLC",
        lesson_date="2026-03-10",
        total_duration_minutes=total_minutes,
        warm_up="عرض صورة لخط إنتاج آلي وطرح سؤال حول كيفية تنسيق الحساسات والمحركات.",
        element_1_strategy="مناقشة وحوار",
        element_1_time="08:00",
        element_1_summary="شرح البنية الأساسية لوحدة PLC وبيئة عملها الصناعية.",
        activity_1=ActivityPlan(
            activity_number=1,
            duration_minutes=10,
            time_formatted="10:00",
            pattern="جماعي",
            activity_type="دراسة حالة",
            purpose="تحديد أطراف الإدخال والإخراج على لوحة S7-1200.",
            teacher_procedures="يوزع المعلم اللوحات التدريبية ويوجه المجموعات.",
            student_procedures="يفحص الطلاب أطراف I0.0-I0.7 ومؤشرات RUN/STOP.",
            student_note="تأكد من فصل التيار قبل فحص الأسلاك.",
        ),
        element_2_strategy="تعلم تعاوني",
        element_2_time="10:00",
        element_2_summary="تحليل دورة المسح Scan Cycle ومكونات الذاكرة.",
        activity_2=ActivityPlan(
            activity_number=2,
            duration_minutes=10,
            time_formatted="10:00",
            pattern="فردي",
            activity_type="رسم / تصميم",
            purpose="رسم المخطط الصندوقي لدورة المسح.",
            teacher_procedures="يعرض المعلم مثالاً إرشادياً ويقيم الرسومات.",
            student_procedures="يرسم الطالب مسار الإشارة من المدخل إلى المخرج.",
            student_note="اذكر أسماء الوحدات بدقة على الرسم.",
        ),
        rubric_group_1_header="معايير المعرفة",
        rubric_group_1_items=["دقة تحديد CPU", "دقة تحديد الذاكرة", "تمييز المداخل", "تمييز المخارج", "ترتيب Scan Cycle", "سلامة المصطلحات"],
        rubric_group_2_header="معايير التطبيق",
        rubric_group_2_items=["فحص S7-1200", "تحديد I0.0", "تحديد Q0.0", "رسم المخطط", "الالتزام بالسلامة", "العمل الجماعي"],
        traceability=[
            TraceabilityEntry(
                field_key="learning_outcomes",
                field_label="نواتج التعلم",
                supporting_excerpt="تتكون منظومة الـ PLC الأساسية من خمس وحدات رئيسية",
                source_pages=[1],
                verified_in_source=True,
            )
        ],
        missing_curriculum_notes=[],
    )


def test_1_multilingual_boundary_extraction_and_lesson_pdf():
    text = (
        "الوحدة الأولى: التحكم الصناعي\n"
        "--- PAGE 1 ---\n"
        "الدرس الأول: مكونات وحدة التحكم المنطقي المبرمج\n"
        "تتكون منظومة الـ PLC الأساسية من خمس وحدات رئيسية متكاملة تشمل المعالج والذاكرة والمداخل والمخارج والتغذية.\n"
        "--- PAGE 2 ---\n"
        "Lesson 2: Ladder Diagram Programming Basics\n"
        "Ladder Diagram follows IEC 61131-3 with normally open contacts, normally closed contacts, and output coils.\n"
    )
    unit = ingest_curriculum(text.encode("utf-8"), "bilingual_unit.txt")
    assert len(unit.lessons) == 2
    assert unit.lessons[0].start_page == 1
    assert unit.lessons[1].start_page == 2
    pdf_bytes = export_lesson_pdf(unit, unit.lessons[0])
    assert pdf_bytes.startswith(b"%PDF")


def test_2_docx_schema_extraction_and_xml_preservation():
    docx_bytes = _make_sample_rtl_docx()
    schema = extract_template_schema(docx_bytes, "ats_mu_test.docx")
    assert schema.is_rtl is True
    assert len(schema.tables) == 1

    payload = _make_sample_payload()
    injected_bytes, metrics = inject_lesson_plan_xml_safe(docx_bytes, payload)
    assert metrics["tables_before"] == metrics["tables_after"] == 1
    assert metrics["widths_unchanged"] is True
    assert metrics["bidi_preserved"] is True

    out_doc = Document(io.BytesIO(injected_bytes))
    full_xml = out_doc.element.body.xml
    assert "w:bidi" in full_xml
    assert "☑ مناقشة وحوار" in full_xml
    assert "☑ تعلم تعاوني" in full_xml
    assert "☐ المحاضرة" in full_xml
    # Original quirked label must remain untouched
    assert "الغرض النشاط" in full_xml


def test_3_time_sum_and_measurable_verb_qa():
    payload = _make_sample_payload(total_minutes=45)
    # Perturb durations and verify normalization restores exact target sum
    payload.lesson_elements[0].duration_minutes = 20
    normalized = normalize_element_durations(payload.lesson_elements, 45)
    assert sum(e.duration_minutes for e in normalized) == 45

    assert detect_vague_verbs(payload.learning_outcomes) == []
    bad_outcomes = ["يفهم الطالب مبدأ عمل PLC", "Students understand Ohm's law"]
    vague = detect_vague_verbs(bad_outcomes)
    assert len(vague) == 2


def test_4_visual_diff_extra_page_and_overflow_detection():
    ref = fitz.open()
    ref.new_page(width=595, height=842)
    ref_bytes = ref.tobytes()
    ref.close()

    gen = fitz.open()
    gen.new_page(width=595, height=842)
    gen.new_page(width=595, height=842)  # Extra overflow page
    gen_bytes = gen.tobytes()
    gen.close()

    diff_pages, expected_count, rendered_count = compute_visual_diff(gen_bytes, ref_bytes, 1, [])
    assert expected_count == 1
    assert rendered_count == 2
    assert diff_pages[1].overflow_detected is True
    assert diff_pages[1].status == "fail"


def test_5_end_to_end_api_upload_generate_export():
    """Migrated from the retired FastAPI app (app/main.py) to the Flask
    request-scoped API: parse -> generate -> artifacts in the response.
    Engine-level coverage of the old pipeline lives in tests 1-4 above."""
    import base64

    fa.APP_PASSCODE = "pipeline-test-pass"
    fa._PASSCODE_FAILURES.clear()
    client = fa.application.test_client()
    headers = {"X-App-Passcode": "pipeline-test-pass"}
    curr_text = (
        "الوحدة الثالثة: PLC\n"
        "--- PAGE 1 ---\n"
        "الدرس الأول: مكونات وحدة التحكم المنطقي المبرمج\n"
        "تتكون منظومة الـ PLC الأساسية من خمس وحدات رئيسية متكاملة تشمل وحدة المعالجة المركزية والذاكرة ووحدات الإدخال والإخراج. "
        "يحدد الطالب وظيفة وحدة المعالجة المركزية في تنفيذ التعليمات. "
        "يصنف الطالب وحدات الإدخال والإخراج حسب اتجاه الإشارة. "
        "يشرح الطالب دور الذاكرة في حفظ البيانات والتعليمات. "
        "يعرض الدرس بنية كل وحدة ووظيفتها داخل المنظومة ويشرح الطلاب دور الإشارات في نقل البيانات بين الوحدات المختلفة.\n"
    )
    up_curr = client.post(
        "/api/curriculum/parse",
        data={"file": (io.BytesIO(curr_text.encode("utf-8")), "unit3.txt")},
        content_type="multipart/form-data",
        headers=headers,
    )
    assert up_curr.status_code == 200
    unit = up_curr.get_json()

    tpl_bytes = _make_sample_rtl_docx()
    gen_body = {
        "context": {
            "school_name": "مدرسة التكنولوجيا التطبيقية",
            "teacher_name": "م. أحمد محمود",
            "job_title": "معلم أول",
            "program_or_course": "PLC",
            "grade_level": "الصف الثاني",
            "academic_year": "٢٠٢٥-٢٠٢٦",
            "branch": "الأتمتة",
            "knowledge_code": "TPK04",
            "class_sections": ["2 A", "2B"],
            "location": "معمل PLC",
            "lesson_date": "2026-03-10",
            "total_duration_minutes": 45,
            "teacher_instructions": "",
        },
        "unit": {k: v for k, v in unit.items() if k not in ("lessons", "pages")},
        "lessons": [unit["lessons"][0]],
    }
    gen_resp = client.post(
        "/api/generate",
        data={
            "template": (io.BytesIO(tpl_bytes), "ats_mu.docx"),
            "request": json.dumps(gen_body),
        },
        content_type="multipart/form-data",
        headers=headers,
    )
    assert gen_resp.status_code == 200
    plan = gen_resp.get_json()["plan"]
    assert plan["qa_report"]["time_sum_valid"] is True

    # Request-scoped delivery: the DOCX arrives in the response itself.
    docx_bytes = base64.b64decode(plan["docx_b64"])
    assert docx_bytes[:2] == b"PK"


def test_6_clip_drops_dangling_exemplar_without_modifier():
    """A cut that leaves one bare word after مثل must drop the exemplar clause
    instead of shipping a misleading modifier-less noun."""
    from app.engines.rules_engine import _clip

    src = "أمثلة واقعية لتقنيات الذكاء الاصطناعي مثل المساعدات الصوتية وأنظمة التوصية والمركبات ذاتية القيادة"
    out = _clip(src, 55)
    assert not out.endswith("المساعدات"), out
    assert " مثل " not in f" {out} ", out
    assert out == "أمثلة واقعية لتقنيات الذكاء الاصطناعي"

    # A surviving two-word exemplar keeps its modifier and stays.
    src2 = "أمثلة واقعية للتقنية مثل المساعدات الصوتية وأنظمة التوصية الذكية جدا"
    out2 = _clip(src2, 48)
    assert out2.endswith("الصوتية"), out2
