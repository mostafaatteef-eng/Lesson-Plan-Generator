from pathlib import Path
"""Regression checks for EBDA production defaults and source-verification integrity."""
from app.engines.ai_engine import _verify_excerpt
from app.flask_app import InstitutionSettings


def test_school_defaults_match_2026_2027():
    settings = InstitutionSettings()
    assert settings.default_academic_year == "٢٠٢٦-٢٠٢٧"
    assert settings.default_duration_minutes == 50


def test_verbatim_excerpt_accepts_line_wrapping():
    source = "الذكاء الاصطناعي يساعد\nفي تحليل البيانات داخل المؤسسات."
    assert _verify_excerpt("الذكاء الاصطناعي يساعد في تحليل البيانات", source)


def test_partial_word_overlap_is_not_verbatim_evidence():
    source = "الذكاء الاصطناعي يساعد في تحليل البيانات داخل المؤسسات."
    assert not _verify_excerpt("الذكاء الاصطناعي يساعد المؤسسات في تحليل البيانات", source)


def test_missing_and_short_excerpts_are_not_verified():
    assert not _verify_excerpt("غير موجود في المنهج", "المحتوى مختلف تمامًا")
    assert not _verify_excerpt("مادة", "مادة")


def test_frontend_school_defaults_and_progress_are_not_regressed():
    source = (Path(__file__).resolve().parents[1] / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "durationMinutes: 50" in source
    assert "'٢٠٢٦-٢٠٢٧'" in source
    assert "Number(advanced.durationMinutes) || 50" in source
    # A timer must not falsely claim the backend advanced its processing stage.
    assert "setInterval(() =>" not in source or "setActiveStageIndex((prev)" not in source


def test_teacher_class_date_are_always_visible_and_required():
    root = Path(__file__).resolve().parents[1]
    selector = (root / "src" / "components" / "LessonSelector.tsx").read_text(encoding="utf-8")
    app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
    identity_block = selector.split("Required lesson identity")[1].split("Minimal Advanced Settings")[0]
    for field_id in ("ebda-teacher-name", "ebda-class-section", "ebda-lesson-date"):
        assert field_id in identity_block
    assert 'type="date"' in identity_block
    assert "Boolean(advanced.teacherName.trim())" in app
    assert "Boolean(advanced.classSection.trim())" in app
    assert "teacher_name: advanced.teacherName.trim()" in app
    assert "['2 A', '2B']" not in app


def test_session_openings_ignore_contents_running_headers_and_topics():
    from app.engines.curriculum_engine import detect_lesson_boundaries
    from app.models.schemas import PageText
    pages = [
        PageText(page_number=1, text="Unit 2\nSessions\nSession 1: Data Sourcing\nSession 2: Annotation"),
        PageText(page_number=2, text="77\nSession 1\nData Sourcing for AI\nLearning Objectives\nIdentify data sources and compare their quality."),
        PageText(page_number=3, text="1\nSession\nTopic 1: Data Sourcing\nSource details and examples."),
        PageText(page_number=4, text="Learning Objectives\nDefine annotation.\nSession 2\nA Deep Dive into Data Annotation"),
        PageText(page_number=5, text="2\nSession\nTopic 1: Annotation\nAnnotation examples."),
    ]
    _, lessons, _ = detect_lesson_boundaries(pages, "source.pdf")
    assert [(x.start_page, x.end_page) for x in lessons] == [(2, 3), (4, 5)]
    assert "Data Sourcing" in lessons[0].title
    assert "Source details" in lessons[0].raw_text
    assert "Annotation examples" not in lessons[0].raw_text


def test_wrapped_english_fact_is_complete_not_a_fragment():
    from app.engines.rules_engine import _pick_excerpts
    from app.models.schemas import LessonBoundary
    lesson = LessonBoundary(lesson_id='x', lesson_number=1, title='Data Sourcing', start_page=1, end_page=1,
        raw_text='Topic 1: Data Sourcing in AI\nDefinition\nThe process of collecting and aggregating data from various sources to be used in\nAI and machine learning models.\nData Importance:\nData is the lifeblood of AI and machine learning models.', word_count=50, confidence=1)
    points = _pick_excerpts(lesson)
    assert any(x.endswith('AI and machine learning models') for x in points)
    assert not any(x.endswith('used in') for x in points)
    assert not any('Learning Objectives' in x for x in points)


def test_data_sourcing_adaptation_requires_supporting_source():
    from app.engines.rules_engine import _enrich_data_sourcing
    from types import SimpleNamespace
    lesson = SimpleNamespace(title='Data Sourcing for AI', raw_text='Structured Data Unstructured Data Semi-structured Data Publicly Available Datasets Web Scraping BeautifulSoup Scrapy hospital medical images privacy bias', start_page=2, end_page=12)
    activity = lambda: SimpleNamespace()
    payload = SimpleNamespace(activity_1=activity(), activity_2=activity(), lesson_elements=[SimpleNamespace() for _ in range(5)], missing_curriculum_notes=[], traceability=[])
    assert _enrich_data_sourcing(payload, lesson) is payload
    assert len(payload.learning_outcomes) == 4
    assert 'JSON' in payload.learning_outcomes[0]
    assert 'المستشفى' in payload.assessment_group_2
    assert 'ثلاثة' in payload.activity_1.student_procedures
    assert len(payload.traceability) == 6
    assert all(e.verified_in_source for e in payload.traceability)
    unchanged = SimpleNamespace()
    lesson.raw_text = 'Data sourcing is important without detailed supporting content.'
    assert _enrich_data_sourcing(unchanged, lesson) is unchanged
    assert not hasattr(unchanged, 'learning_outcomes')


def test_source_unit_number_is_not_invented():
    from app.engines.rules_engine import _source_unit_number
    assert _source_unit_number('Unit 2') == '2'
    assert _source_unit_number('الوحدة ٣: البيانات') == '٣'
    assert _source_unit_number('Learning Python') == 'غير محدد'


def test_mixed_script_boundaries_have_spaces():
    from app.engines.template_engine import _normalize_mixed_script_spacing
    assert _normalize_mixed_script_spacing('وJSON') == 'و JSON'
    assert _normalize_mixed_script_spacing('JSONوالصور') == 'JSON والصور'


def test_checkbox_uses_portable_visible_states():
    from lxml import etree
    from app.engines.template_engine import _apply_sdt_checkboxes, _W14, _qn
    tr = etree.fromstring('''<w:tr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"><w:sdt><w:sdtPr><w14:checkbox><w14:checked w14:val="0"/><w14:checkedState w14:val="0052" w14:font="Wingdings 2"/><w14:uncheckedState w14:val="2610" w14:font="MS Gothic"/></w14:checkbox></w:sdtPr><w:sdtContent><w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Cairo"/></w:rPr><w:t>☐</w:t></w:r></w:p></w:tc></w:sdtContent></w:sdt><w:tc><w:p><w:r><w:t>تعلم تعاوني</w:t></w:r></w:p></w:tc></w:tr>''')
    assert _apply_sdt_checkboxes(tr, ['تعلم تعاوني']) == 1
    state = tr.find(f'.//{{{_W14}}}checkedState')
    assert state.get(f'{{{_W14}}}val') == '2611'
    assert state.get(f'{{{_W14}}}font') == 'DejaVu Sans'
    assert '☑' in ''.join(tr.itertext())
    assert _apply_sdt_checkboxes(tr, []) == 0
    assert '☐' in ''.join(tr.itertext())


def test_existing_list_does_not_receive_duplicate_square_bullet():
    from lxml import etree
    from app.engines.template_engine import _set_paragraph_text_preserve_format
    p = etree.fromstring('<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:pPr><w:numPr><w:numId w:val="15"/></w:numPr></w:pPr><w:r><w:t>old</w:t></w:r></w:p>')
    _set_paragraph_text_preserve_format(p, '▪ يصنف الطالب البيانات')
    assert ''.join(p.itertext()) == 'يصنف الطالب البيانات'
