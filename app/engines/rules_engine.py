"""Deterministic, source-grounded rules-based lesson plan fallback.

Used only when no OPENAI_API_KEY is configured. This is NOT AI generation:
content is assembled from fixed pedagogical templates plus verbatim excerpts
from the uploaded lesson source. Every plan produced here must be labeled as
rules-based output in the API record and in the document-facing notes.
"""
from __future__ import annotations

import re
from typing import List

from app.engines.ai_engine import _verify_excerpt, format_minutes, normalize_element_durations
from app.models.schemas import (
    ActivityPlan,
    CurriculumUnit,
    GenerationContext,
    LessonBoundary,
    LessonElementPlan,
    LessonPlanPayload,
    TemplateSchema,
    TraceabilityEntry,
)

RULES_MODE_LABEL_AR = (
    "ملاحظة: تم إنشاء هذه الخطة بالوضع القواعدي المحدود (بدون ذكاء اصطناعي) — "
    "محتوى ثابت مبني على نص الدرس المرفوع، وتحتاج مراجعة المعلم قبل الاعتماد."
)

_PHASES = [
    ("التهيئة والتمهيد", 0.10, "مناقشة وحوار"),
    ("عرض المفاهيم الأساسية", 0.30, "المحاضرة التفاعلية"),
    ("التطبيق والتدريب", 0.30, "تعلم تعاوني"),
    ("التقويم التكويني", 0.20, "تقويم الأداء"),
    ("الختام والتكليف", 0.10, "مناقشة وحوار"),
]


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"[.!؟?\n؛]+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 12]


def _pick_excerpts(lesson: LessonBoundary, limit: int = 4) -> List[str]:
    excerpts: List[str] = []
    for concept in lesson.key_concepts:
        c = concept.strip()
        if len(c) >= 6 and _verify_excerpt(c, lesson.raw_text):
            excerpts.append(c)
        if len(excerpts) >= limit:
            break
    if len(excerpts) < limit:
        for sent in _split_sentences(lesson.raw_text):
            if sent not in excerpts:
                excerpts.append(sent[:180])
            if len(excerpts) >= limit:
                break
    return excerpts


def build_rules_lesson_plan(
    unit: CurriculumUnit,
    lesson: LessonBoundary,
    schema: TemplateSchema,
    context: GenerationContext,
) -> LessonPlanPayload:
    excerpts = _pick_excerpts(lesson)
    # Prefer substantive source-grounded phrases; fall back to source sentences
    # when key_concepts are too short to be meaningful (e.g. bare headings).
    concepts = [c.strip() for c in lesson.key_concepts if len(c.strip()) >= 12][:4]
    if len(concepts) < 3:
        for sent in _split_sentences(lesson.raw_text):
            if sent not in concepts:
                concepts.append(sent[:90])
            if len(concepts) >= 4:
                break
    concepts = concepts[:4] or [lesson.title]
    verbs = ["يحدد", "يشرح", "يطبق", "يستنتج"]
    learning_outcomes = [
        f"{verbs[i % len(verbs)]} الطالب {c[:90]}" for i, c in enumerate(concepts[:4])
    ] or [f"يشرح الطالب محتوى درس {lesson.title}"]

    total = max(15, context.total_duration_minutes)
    elements = normalize_element_durations(
        [
            LessonElementPlan(
                index=i + 1,
                title=name,
                duration_minutes=max(1, round(total * frac)),
                time_formatted=format_minutes(max(1, round(total * frac))),
                teaching_strategy=strategy,
                brief_description=(
                    f"{name} حول: {concepts[min(i, len(concepts) - 1)][:80]}"
                ),
            )
            for i, (name, frac, strategy) in enumerate(_PHASES)
        ],
        total,
    )

    strategies = [s for _, _, s in _PHASES]
    seen = set()
    selected_strategies = [s for s in strategies if not (s in seen or seen.add(s))]
    selected_resources = ["الكتاب المدرسي / المنهج المرفوع", "السبورة التفاعلية", "أوراق عمل"]

    def _activity(num: int, minutes: int, purpose: str, note: str) -> ActivityPlan:
        return ActivityPlan(
            activity_number=num,
            duration_minutes=minutes,
            time_formatted=format_minutes(minutes),
            pattern="جماعي" if num == 1 else "فردي",
            activity_type="دراسة حالة" if num == 1 else "بحث",
            purpose=purpose,
            teacher_procedures=f"يعرض المعلم نشاطًا حول {lesson.title[:60]} ويوجه المجموعات ويتابع الأداء.",
            student_procedures="يعمل الطلاب في مجموعات على النشاط، ثم يعرضون النتائج ويناقشونها.",
            student_note=note,
        )

    act_minutes = max(5, round(total * 0.2))
    e1, e2 = elements[1], elements[2]

    payload = LessonPlanPayload(
        program_or_course=context.program_or_course,
        teacher_name=context.teacher_name,
        job_title=context.job_title,
        academic_year=context.academic_year,
        school_name=context.school_name,
        grade_level=context.grade_level,
        class_sections=context.class_sections,
        unit_number="1",
        unit_name=unit.unit_title,
        branch=context.branch,
        knowledge_code=context.knowledge_code,
        lesson_title=lesson.title,
        learning_outcomes=learning_outcomes,
        lesson_elements=elements,
        selected_strategies=selected_strategies,
        selected_resources=selected_resources,
        assessment_group_1=f"ملاحظة أداء الطلاب أثناء نشاط {lesson.title[:50]}",
        assessment_group_2="الاستجابة للأسئلة الشفوية أثناء العرض",
        assessment_group_3="تسليم ورقة العمل الختامية",
        presentation_class=context.class_sections[0] if context.class_sections else "",
        location=context.location,
        lesson_date=context.lesson_date,
        total_duration_minutes=total,
        warm_up=f"سؤال تمهيدي حول: {concepts[0][:80]}",
        element_1_strategy=e1.teaching_strategy or "",
        element_1_time=e1.time_formatted,
        element_1_summary=e1.brief_description or e1.title,
        activity_1=_activity(1, act_minutes, f"تطبيق مفاهيم {lesson.title[:60]}", "التزم بالوقت المحدد."),
        element_2_strategy=e2.teaching_strategy or "",
        element_2_time=e2.time_formatted,
        element_2_summary=e2.brief_description or e2.title,
        activity_2=_activity(2, act_minutes, f"تعميق فهم {concepts[min(1, len(concepts) - 1)][:60]}", "راجع المصدر."),
        rubric_group_1_header="المعرفة والفهم",
        rubric_group_1_items=[
            f"يذكر {concepts[0][:60]} بدقة",
            "يربط المفاهيم الجديدة بسابقتها",
        ],
        rubric_group_2_header="المهارات والتطبيق",
        rubric_group_2_items=[
            "يطبق خطوات النشاط بشكل صحيح",
            "يتعاون مع المجموعة ويعرض النتائج",
        ],
        traceability=[
            TraceabilityEntry(
                field_key="learning_outcomes",
                field_label="نواتج التعلم",
                supporting_excerpt=ex,
                source_pages=list(range(lesson.start_page, lesson.end_page + 1)),
                verified_in_source=_verify_excerpt(ex, lesson.raw_text),
            )
            for ex in excerpts[:3]
        ],
        missing_curriculum_notes=[RULES_MODE_LABEL_AR],
    )
    return payload
