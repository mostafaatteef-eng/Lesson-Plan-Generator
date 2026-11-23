from __future__ import annotations

import json
import os
from typing import List

from app.models.schemas import (
    CurriculumUnit,
    GenerationContext,
    LessonBoundary,
    LessonElementPlan,
    LessonPlanPayload,
    TemplateSchema,
)


def format_minutes(minutes: int) -> str:
    safe = max(1, int(round(minutes)))
    hrs, mins = divmod(safe, 60)
    return f"{hrs:02d}:{mins:02d}" if hrs > 0 else f"{mins:02d}:00"


def normalize_element_durations(elements: List[LessonElementPlan], total_minutes: int) -> List[LessonElementPlan]:
    if not elements:
        return []
    items = [e.model_copy(deep=True) for e in elements[:5]]
    current_sum = sum(max(1, e.duration_minutes) for e in items)
    if current_sum != total_minutes:
        scale = total_minutes / max(1, current_sum)
        allocated = 0
        for idx, item in enumerate(items):
            if idx == len(items) - 1:
                item.duration_minutes = max(1, total_minutes - allocated)
            else:
                val = max(1, int(round(item.duration_minutes * scale)))
                item.duration_minutes = val
                allocated += val
        diff = sum(e.duration_minutes for e in items) - total_minutes
        for item in items:
            if diff <= 0:
                break
            if item.duration_minutes > 1:
                take = min(diff, item.duration_minutes - 1)
                item.duration_minutes -= take
                diff -= take
    for idx, item in enumerate(items):
        item.index = idx + 1
        item.time_formatted = format_minutes(item.duration_minutes)
    return items


def _verify_excerpt(excerpt: str, source_text: str) -> bool:
    """Only mark an excerpt verified when it appears verbatim in the source.

    Whitespace is normalized to account for line wrapping in PDF extraction.
    Word overlap is deliberately not sufficient for a verbatim citation.
    """
    clean_excerpt = " ".join(excerpt.split()).strip()
    clean_source = " ".join(source_text.split())
    return len(clean_excerpt) >= 6 and clean_excerpt in clean_source


def generate_lesson_plan(
    unit: CurriculumUnit,
    lesson: LessonBoundary,
    schema: TemplateSchema,
    context: GenerationContext,
) -> LessonPlanPayload:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is required for Python AI engine.")

    client = OpenAI(api_key=api_key)
    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    lang_label = "English" if schema.language == "en" else "Arabic (Modern Standard Arabic)"

    system_prompt = (
        f"You are an expert Applied Technology Curriculum Specialist and Instructional Designer. "
        f"Generate a structured JSON LessonPlanPayload in {lang_label} grounded strictly in the provided source lesson text.\n"
        f"Rules:\n"
        f"1. Use observable Bloom taxonomy action verbs. NEVER use vague verbs (يفهم، يعرف، يدرك، understand, know).\n"
        f"2. Provide exactly 5 lesson_elements whose duration_minutes sum EXACTLY to {context.total_duration_minutes}.\n"
        f"3. Never invent textbook exercises or curriculum facts; list gaps in missing_curriculum_notes.\n"
        f"4. Attach verbatim supporting_excerpt strings copied directly from the source lesson with source_pages.\n"
        f"5. Avoid generic activities. Each activity must quote or clearly reference a specific concept, fact, code example or exercise found in SOURCE LESSON TEXT.\n"
        f"6. Provide specific teacher_procedures, student_procedures, measurable assessment items, and misconceptions supported by the source; do not invent examples that contradict or extend the source.\n"
        f"7. Keep all fields concise enough for a compact four-page form; avoid lengthy paragraphs and repetitive padding.\n"
        f"8. Preserve literal programming syntax and English technical terms accurately, with natural Arabic spacing; do not add unusual spaces inside words or code.\n"
        f"9. Match learning outcomes to specific activities and assessment questions. If information is absent, state the gap and do not fabricate it."
    )

    user_prompt = (
        f"Unit: {unit.unit_title}\n"
        f"Lesson {lesson.lesson_number}: {lesson.title} (Pages {lesson.start_page}-{lesson.end_page})\n"
        f"Template Profile: {schema.template_profile} ({schema.page_count_expected} pages, RTL={schema.is_rtl})\n"
        f"Context JSON: {context.model_dump_json()}\n\n"
        f"SOURCE LESSON TEXT:\n{lesson.raw_text}"
    )

    completion = client.beta.chat.completions.parse(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format=LessonPlanPayload,
    )
    payload = completion.choices[0].message.parsed
    if payload is None:
        raise RuntimeError("AI provider returned no structured LessonPlanPayload.")

    payload.lesson_elements = normalize_element_durations(payload.lesson_elements, context.total_duration_minutes)
    payload.total_duration_minutes = context.total_duration_minutes
    for trace in payload.traceability:
        trace.verified_in_source = _verify_excerpt(trace.supporting_excerpt, lesson.raw_text)
    return payload


def regenerate_fields(
    lesson: LessonBoundary,
    current_payload: LessonPlanPayload,
    field_keys: List[str],
    instruction: str = "",
) -> LessonPlanPayload:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is required.")

    client = OpenAI(api_key=api_key)
    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    prompt = (
        f"Regenerate ONLY these fields: {', '.join(field_keys)}.\n"
        f"Keep all other fields unchanged. Use measurable Bloom verbs and keep text concise for DOCX cell fit.\n"
        f"Instruction: {instruction or 'Improve alignment and conciseness.'}\n"
        f"Current Payload:\n{current_payload.model_dump_json(indent=2)}\n\n"
        f"Source Lesson:\n{lesson.raw_text}\n"
        f"Return a JSON object containing only the regenerated keys."
    )

    resp = client.chat.completions.create(
        model=model_name,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    patch = json.loads(resp.choices[0].message.content or "{}")
    data = current_payload.model_dump()
    for key in field_keys:
        if key in patch:
            data[key] = patch[key]
    updated = LessonPlanPayload.model_validate(data)
    if "lesson_elements" in field_keys:
        updated.lesson_elements = normalize_element_durations(updated.lesson_elements, updated.total_duration_minutes)
    return updated
