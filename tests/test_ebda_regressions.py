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


def test_questionnaire_adaptation_requires_all_source_evidence():
    from app.engines.rules_engine import _enrich_questionnaire
    from types import SimpleNamespace
    lesson = SimpleNamespace(raw_text='questionnaire target population open-ended closed-ended rating scale biased validity reliability Cronbach Google Forms QuestionPro canteen small group',start_page=1,end_page=14)
    payload = SimpleNamespace(activity_1=SimpleNamespace(),activity_2=SimpleNamespace(),lesson_elements=[SimpleNamespace() for _ in range(5)],missing_curriculum_notes=[],traceability=[])
    assert _enrich_questionnaire(payload,lesson) is payload
    assert len(payload.learning_outcomes)==4
    assert 'المقصف' in payload.learning_outcomes[2]
    assert 'Google Forms / QuestionPro' in payload.element_2_summary
    assert 'الثبات' in payload.learning_outcomes[3]
    assert 'أربعة' in payload.activity_2.purpose
    assert 'مقترحة' in payload.activity_1.student_note
    assert 'للمراجعة' in payload.warm_up
    assert len(payload.traceability)==8
    assert all(item.verified_in_source for item in payload.traceability)
    assert 'تمثيل العينة' in payload.missing_curriculum_notes[-1]
    for missing in ['validity','cronbach','rating scale','canteen']:
        partial=SimpleNamespace(raw_text=lesson.raw_text.lower().replace(missing,''))
        blank=SimpleNamespace()
        assert _enrich_questionnaire(blank,partial) is blank
        assert not hasattr(blank,'learning_outcomes')


def test_pptx_explicit_cover_metadata_is_single_lesson_not_ambiguous():
    import io
    from pptx import Presentation
    from app.engines.curriculum_engine import ingest_curriculum
    prs=Presentation()
    for index in range(3):
        slide=prs.slides.add_slide(prs.slide_layouts[6])
        box=slide.shapes.add_textbox(0,0,1000000,1000000)
        box.text_frame.text=('DATA ANALYSIS\nQuestionnaire Design\nGoogle Forms\nGRADE 1 & 2 · LESSON 3\nMS. Example' if index==0 else 'Questionnaire content ' * 50)
    buf=io.BytesIO();prs.save(buf)
    unit=ingest_curriculum(buf.getvalue(),'source.pptx')
    assert unit.unit_title=='DATA ANALYSIS'
    assert len(unit.lessons)==1
    lesson=unit.lessons[0]
    assert lesson.title=='Lesson 3: DATA ANALYSIS - Questionnaire Design'
    assert lesson.lesson_number==3
    assert (lesson.start_page,lesson.end_page)==(1,3)
    assert lesson.approved and not lesson.is_ambiguous
    prs.slides[2].shapes[0].text_frame.text='LESSON 4\nA second lesson '
    buf=io.BytesIO();prs.save(buf)
    multi=ingest_curriculum(buf.getvalue(),'source.pptx')
    assert multi.lessons[0].title!='DATA ANALYSIS - Questionnaire Design'


def test_official_lesson_badge_never_hardcodes_first_lesson():
    source=(Path(__file__).resolve().parents[1]/'app'/'engines'/'template_engine.py').read_text()
    assert 'number = match_number.group(1) if match_number else "غير محدد"' in source
    assert 'f"الدرس ({number})"' in source
    assert '["الدرس (١)"]' not in source


def test_generic_lesson_headers_ignore_contents_and_do_not_overlap():
    from app.engines.curriculum_engine import detect_lesson_boundaries
    from app.models.schemas import PageText
    pages = [PageText(page_number=1,text="Contents\nLesson 1: Measurement 2\nLesson 2: Units 4\nLesson 3: Motion 6"),
        PageText(page_number=2,text="Lesson 1\nMeasurement\n" + "Measurement has three elements and tools used for each quantity. " * 6),
        PageText(page_number=3,text="More explanatory content for measurement."),
        PageText(page_number=4,text="School running header\nLesson 2\nUnits\n" + "Units express the physical quantity using agreed standard definitions. " * 6)]
    _, lessons, _ = detect_lesson_boundaries(pages,"guide.pdf")
    assert [(x.start_page,x.end_page) for x in lessons] == [(2,3),(4,4)]
    assert lessons[0].title == "Lesson 1: Measurement"
    assert "School running header" not in lessons[0].raw_text


def test_mixed_script_run_directions_are_explicit_and_text_is_preserved():
    from lxml import etree
    from app.engines.template_engine import _set_paragraph_text_preserve_format, _qn
    p=etree.fromstring('<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:pPr><w:bidi/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Cairo"/></w:rPr><w:t>old</w:t></w:r></w:p>')
    value="أدوات المصدر: Google Forms / QuestionPro. ثم يراجع المعلم."
    _set_paragraph_text_preserve_format(p,value)
    assert ''.join(p.itertext()).replace('\u200e','') == value
    latin=[r for r in p.findall(_qn('r')) if 'Google' in ''.join(r.itertext())][0]
    assert latin.find(f"{_qn('rPr')}/{_qn('rtl')}").get(_qn('val')) == '0'
    assert p.find(f"{_qn('pPr')}/{_qn('bidi')}") is not None


def test_context_accepts_output_language_without_silently_ignoring_it():
    from app.models.schemas import GenerationContext
    assert 'output_language' in GenerationContext.model_fields
    assert GenerationContext.model_fields['output_language'].default == 'auto'


def test_subject_metadata_does_not_inherit_specialty_or_invent_a_room():
    from app.flask_app import InstitutionSettings, resolve_subject_metadata
    from app.models.schemas import GenerationContext
    settings = InstitutionSettings()
    ctx = GenerationContext(unit_id='u', lesson_id='l', template_id='t', school_name='School',
        teacher_name='Teacher', job_title=settings.default_job_title,
        program_or_course='Physics', grade_level='1', academic_year='2026-2027',
        branch=settings.default_branch, location=settings.default_location)
    for subject in ['Physics', 'الفيزياء', 'English for AI']:
        result = resolve_subject_metadata(ctx.model_copy(update={'program_or_course': subject}), settings)
        assert result.branch == subject
        assert result.job_title == f'معلم {subject}'
        assert result.location == 'يحدده المعلم'
        assert result.teacher_name == ctx.teacher_name
        assert ctx.branch == settings.default_branch
    assert resolve_subject_metadata(ctx.model_copy(update={'program_or_course': settings.specialization_ar}), settings) == ctx.model_copy(update={'program_or_course': settings.specialization_ar})
    custom = ctx.model_copy(update={'branch':'Mechanics','job_title':'Physics teacher','location':'Room 12'})
    assert resolve_subject_metadata(custom, settings) == custom


def test_unit_fallback_never_uses_uploaded_filename():
    from app.engines.curriculum_engine import detect_lesson_boundaries
    from app.models.schemas import PageText
    page = PageText(page_number=1, text='Lesson 2: Basic units\n' + 'These physical quantities are fundamental. ' * 15)
    for filename in ['file-4ef406d2-4.pdf', 'private-teacher-name.pdf', 'Course.docx']:
        title, lessons, warnings = detect_lesson_boundaries([page], filename)
        assert title == 'غير محددة في المصدر'
        assert filename.split('.')[0] not in title
        assert lessons[0].title == 'Lesson 2: Basic units'
    actual = PageText(page_number=1, text='Unit 2: Measurement\n' + page.text)
    title, _, _ = detect_lesson_boundaries([actual], 'private-file.pdf')
    assert title == 'Unit 2: Measurement'


def test_outcomes_name_actual_lesson_targets_and_have_individual_evidence():
    from types import SimpleNamespace
    from app.engines.rules_engine import _grounded_outcomes
    physics = SimpleNamespace(title='Measurements', start_page=4, end_page=6, key_concepts=[], raw_text=(
        'Measurement is the process of comparing an unknown quantity with a unit. '
        'The fundamental unit of length is defined to be one meter. '
        'The fundamental unit of mass is defined as one kilogram. '
        'The fundamental unit of time is defined to be one second.'))
    computing = SimpleNamespace(title='AI', start_page=8, end_page=10, key_concepts=[], raw_text=(
        'An algorithm is a set of instructions for performing a specific task. '
        'A data set is a collection of data points used for analysis. '
        'Automation refers to the process of operating without human intervention.'))
    a, evidence = _grounded_outcomes(physics)
    b, other = _grounded_outcomes(computing)
    assert len(a) == 4 and len(b) == 3
    assert 'Measurement' in a[0] and 'algorithm' in b[0]
    assert not set(a) & set(b)
    for outcomes, entries, source in [(a, evidence, physics.raw_text), (b, other, computing.raw_text)]:
        assert len(outcomes) == len(entries)
        assert all(e.verified_in_source and e.supporting_excerpt in source for e in entries)
        assert all(e.field_key == f'learning_outcomes.{i}' for i,e in enumerate(entries))
        assert not any('المقتطف' in o or 'مفهوم AI' in o for o in outcomes)


def test_outcomes_do_not_pad_a_title_or_misread_questions_and_pronouns():
    from types import SimpleNamespace
    from app.engines.rules_engine import _grounded_outcomes
    lesson = SimpleNamespace(title='Physics',start_page=1,end_page=1,key_concepts=[],raw_text=(
        'What is meant by measurement? There are many things in daily life. '
        'Describing the temperature of a person as being high is scientifically inaccurate. '
        'You must explain your results to others and discuss your ideas.'))
    assert _grounded_outcomes(lesson) == ([], [])


def test_outcomes_refuse_generic_padding_even_with_enough_excerpt_text():
    from app.engines.rules_engine import build_rules_lesson_plan, InsufficientCurriculumEvidence
    from app.models.schemas import CurriculumUnit, LessonBoundary, GenerationContext, TemplateSchema
    lesson = LessonBoundary(lesson_id='l',lesson_number=1,confidence=1,title='Unsupported topic',start_page=1,end_page=1,
        raw_text='Students should read the paragraph carefully and share a summary of their views. A discussion about this subject can include many opinions and different perspectives.',word_count=30)
    unit = CurriculumUnit(unit_id='u',filename='source.txt',file_format='txt',language='en',unit_title='Unit',total_pages=1,pages=[],lessons=[lesson])
    schema = TemplateSchema(template_id='t',filename='t.docx')
    context = GenerationContext(unit_id='u',lesson_id='l',template_id='t',school_name='School',teacher_name='Test',job_title='Teacher',program_or_course='Subject',grade_level='1',academic_year='2026',branch='Subject')
    import pytest
    with pytest.raises(InsufficientCurriculumEvidence):
        build_rules_lesson_plan(unit,lesson,schema,context)


def test_wider_outcomes_support_mixed_case_parentheses_and_unit_table():
    from types import SimpleNamespace
    from app.engines.rules_engine import _grounded_outcomes
    lesson = SimpleNamespace(title='Basic and derived units', start_page=7,end_page=8,key_concepts=[],raw_text=(
        'First: Fundamental (basic) Physical Quantity is the physical quantity that cannot be defined in terms of other quantities.\n'
        'Second: Derived Physical Quantity is the physical quantity that can be defined in terms of fundamental quantities.\n'
        'Basic physical quantity\nFundamental unit\nUnit symbol\n1- Mass (m)\nkilogram\nkg\n2- Length (l)\nmeter\nm\n'))
    outcomes,evidence = _grounded_outcomes(lesson)
    assert len(outcomes)==4
    assert 'Fundamental (basic)' in outcomes[0] and 'Derived Physical' in outcomes[1]
    assert 'kilogram (kg)' in outcomes[2] and 'meter (m)' in outcomes[3]
    assert all(e.verified_in_source for e in evidence)
    assert all(' '.join(e.supporting_excerpt.split()) in ' '.join(lesson.raw_text.split()) for e in evidence)


def test_wider_outcomes_support_next_line_colon_definition_and_components():
    from types import SimpleNamespace
    from app.engines.rules_engine import _grounded_outcomes
    lesson = SimpleNamespace(title='Motion',start_page=1,end_page=2,key_concepts=[],raw_text=(
        'The scalar quantity:\n“Is the physical quantity that can be fully defined by its magnitude only”.\n'
        'The vector quantity:\n“Is a physical quantity defined by magnitude and direction”.\n'
        'Calipers are comprised of two jaws, one attached to a fixed scale and the other to a sliding scale.\n'))
    outcomes,evidence = _grounded_outcomes(lesson)
    assert len(outcomes)==3
    assert any('scalar quantity' in o for o in outcomes)
    assert any('vector quantity' in o for o in outcomes)
    assert any('مكونات Calipers' in o for o in outcomes)
    assert all(e.verified_in_source for e in evidence)


def test_wider_outcomes_never_join_an_unrelated_heading_to_a_target():
    from types import SimpleNamespace
    from app.engines.rules_engine import _grounded_outcomes
    lesson = SimpleNamespace(title='Instructions',start_page=1,end_page=1,key_concepts=[],raw_text=(
        'Take a break\nWhat is the difference between these things?\n'
        'There are a large number of possible answers in this exercise.\n'
        'Measuring length using the micrometer\nA micrometer is an instrument used for measuring small lengths.\n'))
    outcomes,_ = _grounded_outcomes(lesson)
    assert outcomes == ['يشرح الطالب تعريف A micrometer الوارد في الدرس.']


def test_practice_names_each_verified_concept_and_maps_every_field():
    from types import SimpleNamespace
    from app.engines.rules_engine import _grounded_practice, _grounded_outcomes, InsufficientCurriculumEvidence
    import pytest
    sources = [
        'Measurement is the process of comparing a quantity with its unit.\nThe fundamental unit of length is defined to be one meter.\nThe fundamental unit of mass is defined as one kilogram.',
        'An algorithm is a set of instructions for a computer to perform a task.\nA data set is a collection of data points used for analysis.\nNatural language processing is a branch of AI that enables computers to understand language.',
    ]
    plans = []
    for source in sources:
        lesson = SimpleNamespace(raw_text=source,start_page=2,end_page=3,key_concepts=[],title='Lesson')
        outcomes, evidence = _grounded_outcomes(lesson)
        payload = SimpleNamespace(learning_outcomes=outcomes,traceability=evidence,
            activity_1=SimpleNamespace(),activity_2=SimpleNamespace(),
            lesson_elements=[SimpleNamespace() for _ in range(5)],missing_curriculum_notes=[])
        p = _grounded_practice(payload,lesson)
        fields = {'warm_up','assessment_group_1','assessment_group_2','assessment_group_3','element_1_summary','element_2_summary'}
        fields |= {f'activity_{n}.{f}' for n in [1,2] for f in ['purpose','teacher_procedures','student_procedures','student_note']}
        fields |= {f'lesson_elements.{i}.brief_description' for i in range(5)}
        assert fields <= {e.field_key for e in p.traceability}
        assert all(e.verified_in_source for e in p.traceability)
        assert all(' '.join(e.supporting_excerpt.split()) in ' '.join(source.split()) for e in p.traceability)
        assert 'مقتطف' not in p.assessment_group_1 + p.assessment_group_2
        assert 'بطاقة مقترحة' in p.activity_1.purpose
        plans.append(p)
    assert 'Measurement' in plans[0].assessment_group_1
    assert 'algorithm' in plans[1].assessment_group_1
    assert 'Measurement' not in plans[1].activity_1.teacher_procedures
    # Evidence that does not occur in this lesson cannot authorize a task.
    lesson.raw_text = 'Unrelated lesson without supported statements.'
    with pytest.raises(InsufficientCurriculumEvidence):
        _grounded_practice(plans[1],lesson)


def test_practice_uses_literal_table_targets_and_component_questions():
    from types import SimpleNamespace
    from app.engines.rules_engine import _grounded_practice, _grounded_outcomes
    source = ('First: Fundamental (basic) Physical Quantity is the physical quantity that cannot be defined in terms of other quantities.\n'
              'Calipers are comprised of two jaws attached to fixed and sliding scales.\n'
              '1- Mass (m)\nkilogram\nkg\n2- Length (l)\nmeter\nm\n')
    lesson = SimpleNamespace(raw_text=source,start_page=1,end_page=1,key_concepts=[],title='Lesson')
    outcomes,evidence = _grounded_outcomes(lesson)
    p = SimpleNamespace(learning_outcomes=outcomes,traceability=evidence,activity_1=SimpleNamespace(),activity_2=SimpleNamespace(),lesson_elements=[SimpleNamespace() for _ in range(5)],missing_curriculum_notes=[])
    p = _grounded_practice(p,lesson)
    assert 'مكونات Calipers' in p.assessment_group_1
    assert 'وحدة قياس Mass' in p.assessment_group_2
    assert 'وحدة قياس Length' in p.assessment_group_2
    assert any(e.field_key=='assessment_group_2' and 'kilogram' in e.supporting_excerpt for e in p.traceability)


def test_revision_section_is_not_absorbed_into_last_lesson():
    from app.engines.curriculum_engine import detect_lesson_boundaries
    from app.models.schemas import PageText
    pages = [PageText(page_number=1,text='Lesson 5\nEffective Online Collaboration\n'+'A supported lesson sentence. '*20),
             PageText(page_number=2,text='More lesson content. '*20),
             PageText(page_number=3,text='37\nRevision\nUnit 1\nDifferent revision material.')]
    _, lessons, _ = detect_lesson_boundaries(pages,'book.pdf')
    assert lessons[-1].end_page == 2
    assert 'Different revision' not in lessons[-1].raw_text


def test_pattern_cards_require_every_evidence_span():
    from app.engines.rules_engine import source_cards
    from types import SimpleNamespace
    lesson = SimpleNamespace(title='Lesson 5: Accuracy and Error',raw_text=(
        'The error in the use of any instrument is normally taken to be half of the smallest division on the scale of the instrument. '
        'The Absolute Error (delta): is the difference between the actual value (Xo) and the measured value (X). '
        'The Relative Error (r): is the ratio between the absolute error (delta) to the real value (Xo). '
        'As the relative error decreases, the measurement accuracy is considered higher.'))
    cards = source_cards(lesson)
    assert len(cards)==4
    assert all(_verify_excerpt(s,lesson.raw_text) for c in cards for s in c[4])
    lesson.raw_text = lesson.raw_text.replace('half of the smallest division','a vague quantity')
    assert len(source_cards(lesson))==3
    lesson.raw_text = 'Accuracy and Error, definitions and examples not present.'
    assert not source_cards(lesson)


def test_new_cards_are_bounded_to_matching_lesson_title():
    from app.engines.rules_engine import source_cards
    from types import SimpleNamespace
    lesson=SimpleNamespace(title='Unrelated lesson',raw_text='Progress reports are documents that track the status and development of a project.')
    assert source_cards(lesson)==[]


def test_match_and_sequence_mechanics_use_only_verified_items():
    from types import SimpleNamespace
    from app.engines.rules_engine import (_definition_pairs, _ordered_steps,
        _grounded_outcomes, _grounded_practice)
    source = ('Speed is the distance moved by an object per unit time.\n'
              'Velocity is the displacement of an object per unit time.\n'
              'Acceleration is the change of the object velocity per unit time.\n'
              '1. Collect the measurements from the instruments carefully.\n'
              '2. Record each reading in the results table immediately.\n'
              '3. Compare the readings with the expected values together.\n')
    lesson = SimpleNamespace(raw_text=source, start_page=1, end_page=1, key_concepts=[], title='Lesson')
    pairs = _definition_pairs(lesson)
    assert [t for t, _, _ in pairs] == ['Speed', 'Velocity', 'Acceleration']
    steps = _ordered_steps(lesson)
    assert len(steps) == 3
    norm = ' '.join(source.split())
    for term, definition, span in pairs:
        assert ' '.join(definition.split()) in norm
        assert ' '.join(span.split()) in norm
    outcomes, evidence = _grounded_outcomes(lesson)
    payload = SimpleNamespace(learning_outcomes=outcomes, traceability=list(evidence),
        activity_1=SimpleNamespace(), activity_2=SimpleNamespace(),
        lesson_elements=[SimpleNamespace() for _ in range(5)], missing_curriculum_notes=[])
    p = _grounded_practice(payload, lesson)
    # The cooperative element takes the first mechanic; the individual one the next.
    assert '(توصيل)' in p.activity_2.purpose
    assert '(ترتيب)' in p.activity_1.purpose
    # Every presented item is verbatim source text.
    for term, definition, _ in pairs:
        assert term in p.activity_2.student_procedures
        assert definition in p.activity_2.student_procedures
    for step in steps:
        assert step in p.activity_1.student_procedures
    assert all(e.verified_in_source for e in p.traceability)
    assert all(' '.join(e.supporting_excerpt.split()) in norm for e in p.traceability)
    # Items stay inside the printable budget.
    assert len(p.activity_1.student_procedures) <= 320
    assert len(p.activity_2.student_procedures) <= 320


def test_classify_and_scenario_mechanics_are_source_gated():
    from types import SimpleNamespace
    from app.engines.rules_engine import (_category_groups, _scenario_span,
        _grounded_outcomes, _grounded_practice)
    cat_source = ('Copper is a good conductor. Rubber is an insulator. Wood is an insulator.\n'
                  'A conductor is a material that allows charge to pass through it easily.\n'
                  'An insulator is a material that resists the flow of charge through it.\n'
                  'The school workshop uses both groups in wiring projects safely every day.\n')
    lesson = SimpleNamespace(raw_text=cat_source, start_page=1, end_page=1, key_concepts=[], title='Lesson')
    groups = _category_groups(lesson)
    assert groups is not None
    cats = {c: [t for t, _ in items] for c, items in groups}
    assert cats.get('insulator') == ['Rubber', 'Wood']
    assert any('Copper' in v for v in cats.values())
    outcomes, evidence = _grounded_outcomes(lesson)
    payload = SimpleNamespace(learning_outcomes=outcomes, traceability=list(evidence),
        activity_1=SimpleNamespace(), activity_2=SimpleNamespace(),
        lesson_elements=[SimpleNamespace() for _ in range(5)], missing_curriculum_notes=[])
    p = _grounded_practice(payload, lesson)
    norm = ' '.join(cat_source.split())
    assert any('(تصنيف)' in a.purpose or '(توصيل)' in a.purpose
               for a in (p.activity_1, p.activity_2))
    assert all(e.verified_in_source for e in p.traceability)
    assert all(' '.join(e.supporting_excerpt.split()) in norm for e in p.traceability)

    scen_source = ('Structured logging helps operators trace requests across services reliably.\n'
                   'A trace identifier is a unique value attached to every request in the system.\n'
                   'A log pipeline is a chain that collects, parses and stores log records.\n'
                   'A retry policy is a rule that repeats failed requests with increasing delays.\n'
                   'For example, a small clinic application stores every trace identifier in its log '
                   'pipeline so that the administrator can investigate a failed payment quickly.\n')
    s_lesson = SimpleNamespace(raw_text=scen_source, start_page=1, end_page=1, key_concepts=[], title='Lesson')
    found = _scenario_span(s_lesson, ['A trace identifier', 'A log pipeline', 'A retry policy'])
    assert found is not None
    block, located = found
    assert ' '.join(block.split()) in ' '.join(scen_source.split())
    assert located == ['A trace identifier', 'A log pipeline']
    # No example marker -> no scenario activity.
    assert _scenario_span(lesson, ['Copper', 'Rubber']) is None


def test_mechanics_never_fabricate_and_cards_remain_the_fallback():
    from types import SimpleNamespace
    from app.engines.rules_engine import (_definition_pairs, _ordered_steps,
        _category_groups, _scenario_span, _grounded_outcomes, _grounded_practice)
    bare = SimpleNamespace(raw_text='An unsupported remark about daily classroom routines. ' * 8,
                           start_page=1, end_page=1, key_concepts=[], title='Lesson')
    assert _definition_pairs(bare) == []
    assert _ordered_steps(bare) == []
    assert _category_groups(bare) is None
    assert _scenario_span(bare, ['x', 'y']) is None
    # Unit-table lines are not mistaken for ordered steps.
    table = SimpleNamespace(raw_text='1- Mass (m)\nkilogram\nkg\n2- Length (l)\nmeter\nm\n3- Time (t)\nsecond\ns\n',
                            start_page=1, end_page=1, key_concepts=[], title='Lesson')
    assert _ordered_steps(table) == []
    # A lesson without mechanic material keeps the question-card activities.
    card_source = ('Measurement is the process of comparing a quantity with its unit.\n'
                   'The fundamental unit of length is defined to be one meter.\n'
                   'The fundamental unit of mass is defined as one kilogram.\n')
    c_lesson = SimpleNamespace(raw_text=card_source, start_page=1, end_page=1, key_concepts=[], title='Lesson')
    outcomes, evidence = _grounded_outcomes(c_lesson)
    payload = SimpleNamespace(learning_outcomes=outcomes, traceability=list(evidence),
        activity_1=SimpleNamespace(), activity_2=SimpleNamespace(),
        lesson_elements=[SimpleNamespace() for _ in range(5)], missing_curriculum_notes=[])
    p = _grounded_practice(payload, c_lesson)
    # Three definitions activate the match mechanic on the cooperative element;
    # the individual element keeps the question card.
    assert '(توصيل)' in p.activity_2.purpose
    assert 'بطاقة مقترحة' in p.activity_1.purpose
    assert any('التوصيل' in note for note in p.missing_curriculum_notes)


def test_page_fit_retry_uses_card_only_layout():
    from types import SimpleNamespace
    from app.engines.rules_engine import _grounded_outcomes, _grounded_practice
    source = ('Measurement is the process of comparing a quantity with its unit.\n'
              'The fundamental unit of length is defined to be one meter.\n'
              'The fundamental unit of mass is defined as one kilogram.\n')
    lesson = SimpleNamespace(raw_text=source, start_page=1, end_page=1, key_concepts=[], title='Lesson')
    def make_payload():
        outcomes, evidence = _grounded_outcomes(lesson)
        return SimpleNamespace(learning_outcomes=outcomes, traceability=list(evidence),
            activity_1=SimpleNamespace(), activity_2=SimpleNamespace(),
            lesson_elements=[SimpleNamespace() for _ in range(5)], missing_curriculum_notes=[])
    rich = _grounded_practice(make_payload(), lesson)
    assert '(توصيل)' in rich.activity_2.purpose
    compact = _grounded_practice(make_payload(), lesson, allow_mechanics=False)
    # The page-fit fallback keeps both elements on the baseline question cards.
    assert 'بطاقة مقترحة' in compact.activity_1.purpose
    assert 'بطاقة مقترحة' in compact.activity_2.purpose
    assert not any('التوصيل' in note for note in compact.missing_curriculum_notes)
    assert any('تكييف مقترح' in note for note in compact.missing_curriculum_notes)
