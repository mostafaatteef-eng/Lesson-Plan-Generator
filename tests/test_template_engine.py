
def _build_official_like_template():
    """Synthetic template mirroring the official ATS-MU structure:
    narrow empty separator columns between label and value cells, and a
    same-cell 'label : value' identity line."""
    import io
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Twips

    doc = Document()
    tbl = doc.add_table(rows=3, cols=3)
    for row in tbl.rows:
        row.cells[1].width = Twips(283)  # separator
        row.cells[2].width = Twips(7078)  # value
    tbl.rows[0].cells[0].text = "المدرسة"
    tbl.rows[1].cells[0].text = "البرنامج / المقرر"
    tbl.rows[2].cells[0].text = "فصل"
    ident = doc.add_table(rows=1, cols=1)
    cell = ident.rows[0].cells[0]
    para = cell.paragraphs[0]
    r1 = para.add_run("الاسم")
    r2 = para.add_run(" : أ/ معلم سابق ")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _payload(**over):
    from app.models.schemas import LessonPlanPayload, ActivityPlan, LessonElementPlan
    a1 = ActivityPlan(activity_number=1, duration_minutes=15, time_formatted="15", pattern="فردي", activity_type="بحث", purpose="غ", teacher_procedures="م", student_procedures="ط", student_note="ن")
    a2 = ActivityPlan(activity_number=2, duration_minutes=20, time_formatted="20", pattern="جماعي", activity_type="دراسة حالة", purpose="غ٢", teacher_procedures="م٢", student_procedures="ط٢", student_note="ن٢")
    kw = dict(
        lesson_title="درس", program_or_course="الذكاء الاصطناعي", teacher_name="معلم جديد",
        job_title="وظيفة جديدة", academic_year="٢٠٢٥-٢٠٢٦", school_name="مدرسة الاختبار",
        grade_level="الثاني الثانوي", class_sections=["2 A", "2B"], unit_number="١",
        unit_name="وحدة", branch="فرع", knowledge_code="TPK04", learning_outcomes=["ناتج"],
        lesson_elements=[LessonElementPlan(index=1, title="ت", duration_minutes=10, time_formatted="10")],
        selected_strategies=[], selected_resources=[],
        assessment_group_1="ق١", assessment_group_2="ق٢", assessment_group_3="ق٣",
        warm_up="ت", element_1_strategy="س", element_1_time="15", element_1_summary="و١",
        element_2_strategy="س٢", element_2_time="25", element_2_summary="و٢",
        activity_1=a1, activity_2=a2, rubric_group_1_header="م١", rubric_group_1_items=[],
        rubric_group_2_header="م٢", rubric_group_2_items=[])
    kw.update(over)
    return LessonPlanPayload(**kw)


def test_separator_columns_are_skipped_when_writing_values():
    from docx import Document
    import io
    from app.engines.template_engine import inject_lesson_plan_xml_safe
    out, metrics = inject_lesson_plan_xml_safe(_build_official_like_template(), _payload())
    doc = Document(io.BytesIO(out))
    tbl = doc.tables[0]
    assert tbl.rows[0].cells[1].text.strip() == ""  # separator untouched
    assert tbl.rows[0].cells[2].text.strip() == "مدرسة الاختبار"
    assert tbl.rows[1].cells[1].text.strip() == ""
    assert tbl.rows[1].cells[2].text.strip() == "الذكاء الاصطناعي"
    assert tbl.rows[2].cells[2].text.strip() == "2 A"


def test_same_cell_identity_replaced_and_cleared_without_invention():
    from docx import Document
    import io
    from app.engines.template_engine import inject_lesson_plan_xml_safe
    out, _ = inject_lesson_plan_xml_safe(_build_official_like_template(), _payload())
    text = Document(io.BytesIO(out)).tables[1].rows[0].cells[0].text
    assert "معلم جديد" in text and "معلم سابق" not in text
    out2, _ = inject_lesson_plan_xml_safe(_build_official_like_template(), _payload(teacher_name=""))
    text2 = Document(io.BytesIO(out2)).tables[1].rows[0].cells[0].text
    assert "معلم سابق" not in text2  # cleared, never invented
