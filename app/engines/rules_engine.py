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


def _clip(text: str, limit: int) -> str:
    """Bound text length without cutting a word in half.

    Hard slicing (``text[:n]``) mangles Arabic words mid-glyph; trim at the
    last whitespace boundary inside the budget instead, and drop a dangling
    trailing conjunction so the phrase still reads complete.
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    boundary = head.rfind(" ")
    if boundary >= limit // 2:
        head = head[:boundary]
    head = head.rstrip(" .،,؛:：-")
    # Drop a dangling one-letter conjunction (و) left at the cut point.
    if head.endswith(" و"):
        head = head[:-2].rstrip()
    # A trailing و-word is a list item cut mid-phrase (more text follows,
    # since we only reach here when the source exceeded the budget); drop it
    # so the phrase does not end on an incomplete enumeration.
    last = head.rsplit(" ", 1)[-1]
    if last.startswith("و") and len(last) > 1:
        head = head[: head.rfind(" ")].rstrip(" .،,؛:：-")
    # An exemplar opener left with a single bare word at the cut point is a
    # clipped exemplar that lost its modifier ("مثل المساعدات" cut from "مثل
    # المساعدات الصوتية"); drop the whole exemplar clause so the phrase ends
    # on a complete meaning rather than a misleading bare noun.
    idx = max(head.rfind(" مثل "), head.rfind(" مثال "))
    if idx != -1 and len(head[idx:].split()) - 1 < 2:
        head = head[:idx].rstrip(" .،,؛:：-")
    return head


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
                excerpts.append(_clip(sent, 140))
            if len(excerpts) >= limit:
                break
    return excerpts




_LESSON_NUM_PREFIX = re.compile(r"^الدرس\s+\S+\s*[:：]\s*")

# Clause boundaries where a longer source sentence can be cut without leaving
# an incomplete predicate (relative clauses, purpose clauses, coordinated verbs).
_NP_BOUNDARIES = [
    " يهتم ", " تهتم ", " يهدف ", " تهدف ", " ويشرح ", " وتشرح ", " ويستعرض ",
    " ويناقش ", " ويطبق ", " ويحدد ", " ويستنتج ", " ويعرض ", " ويوضح ",
    " ويصنف ", " ويحلل ", " ويتعرف ", " ويستعرض ", " الذي ", " التي ",
    " الذين ", " بحيث ", " حيث ", " كما ", " إذ ", " مما ", " وبناء",
]

# Words that cannot END a phrase: prepositions, conjunctions, relatives, copulas
# and open-ended adjectives. A phrase ending in one is a fragment.
_TRAILING_OPENERS = {
    "في", "على", "إلى", "عن", "من", "مع", "بين", "حول", "مثل", "خلال", "عبر",
    "ضمن", "نحو", "لدى", "الذي", "التي", "الذين", "هو", "هي", "كان", "كانت",
    "ثم", "أو", "و", "لا", "لم", "لن", "قد", "كل", "بعض", "غير", "أي", "بعد",
    "قبل", "عند", "حتى", "منذ", "دون", "لكن", "قادرة", "قادر", "أن", "إن",
}

_LEAD_VERBS = {
    "يستعرض", "تستعرض", "يناقش", "تناقش", "يتناول", "تتناول", "يشرح", "تشرح",
    "يوضح", "توضح", "يتعرف", "تتعرف", "يصنف", "تصنف", "يطبق", "تطبق",
    "يعرض", "تعرض", "يقدم", "تقدم", "يوظف", "توظف", "يستخدم", "تستخدم",
    "يتعلم", "تتعلم", "يدرس", "تدرس",
}
_LEAD_SUBJECTS = {"الدرس", "الطلاب", "الطالب", "المعلم", "المتعلم", "الحصة"}


def _core_title(title: str) -> str:
    """Lesson title without the 'الدرس الأول:' numbering prefix."""
    core = _LESSON_NUM_PREFIX.sub("", title).strip()
    return core or title


def _strip_trailing_openers(text: str) -> str:
    tokens = text.split()
    while len(tokens) > 3 and tokens[-1] in _TRAILING_OPENERS:
        tokens.pop()
    return " ".join(tokens)


def _noun_phrase(sentence: str, budget: int) -> str:
    """Extract a COMPLETE noun phrase from a source sentence, or return "".

    Never returns a clipped clause fragment: leading verb+subject are dropped,
    the cut happens at a clause boundary, and trailing opener words that demand
    a complement are removed. Copula sentences (X هو Y) are not NP sources.
    """
    s = sentence.strip()
    tokens = s.split()
    if tokens and tokens[0] in _LEAD_VERBS:
        tokens = tokens[1:]
        if tokens and tokens[0].strip("،,") in _LEAD_SUBJECTS:
            tokens = tokens[1:]
        s = " ".join(tokens)
    head = s.split()
    if any(t in ("هو", "هي", "ليس", "ليست") for t in head[:3]):
        return ""
    for marker in _NP_BOUNDARIES:
        idx = s.find(marker)
        if idx > 0:
            s = s[:idx]
    s = _strip_trailing_openers(_clip(s, budget))
    tokens = s.split()
    if tokens and tokens[0].strip("،,") in _LEAD_SUBJECTS:
        s = " ".join(tokens[1:])
    return s if len(s) >= 12 else ""


# Lead verbs that name no observable performance; never used for outcomes.
_VAGUE_LEAD = {
    "يفهم", "تفهم", "يعرف", "تعرف", "يدرك", "تدرك", "يلم", "تلم",
    "يستوعب", "تستوعب", "يتعلم", "تتعلم",
}


def _outcome_from_sentence(sentence: str, budget: int) -> str:
    """Build 'verb الطالب object' from the source sentence's own measurable
    verb. Returns "" when the sentence has no usable verb+subject head, so a
    full source sentence is never mechanically wrapped behind a stock verb.
    """
    tokens = sentence.strip().split()
    if len(tokens) < 4:
        return ""
    verb = tokens[0]
    # Any present-tense Arabic verb head (ي/ت prefix, 3+ letters) qualifies;
    # exclusions remove vague verbs and copulas. A fixed allowlist alone was
    # brittle: source verbs outside it were silently dropped or, worse, glued
    # behind a stock verb with their own subject still attached.
    if not re.match(r"^[يت][أ-ي]{3,}$", verb):
        return ""
    if verb in _VAGUE_LEAD or verb in ("يكون", "تكون", "يصبح", "تصبح", "يبدو", "تبدو"):
        return ""
    subj = tokens[1].strip("،,")
    if subj not in _LEAD_SUBJECTS or subj == "المعلم":
        return ""
    # Feminine ت-prefix verbs (تستعرض الدرس) become ي- with الطالب.
    if verb.startswith("ت"):
        verb = "ي" + verb[1:]
    obj = " ".join(tokens[2:])
    for marker in _NP_BOUNDARIES:
        idx = obj.find(marker)
        if idx > 0:
            obj = obj[:idx]
    obj = _strip_trailing_openers(_clip(obj, budget))
    # Drop a trailing Latin-script gloss (e.g. "دورة المسح Scan Cycle") when the
    # Arabic object stays complete without it; the gloss often orphans onto its
    # own line and adds no meaning beyond the Arabic term it explains. Guarded:
    # only 2+ Latin words preceded by Arabic, so "الفرق بين RAM و ROM" keeps ROM.
    m = re.search(r"^(?P<ar>.*[\u0621-\u064a])\s+(?:[A-Za-z][A-Za-z0-9-]*\s+)+[A-Za-z][A-Za-z0-9-]*\.?$", obj)
    if m and len(m.group("ar")) >= 12:
        obj = m.group("ar").rstrip()
    if len(obj) < 12:
        return ""
    return f"{verb} الطالب {obj}"


def _outcome_phrases(lesson: LessonBoundary, limit: int = 4, budget: int = 55) -> List[str]:
    """Complete pedagogical outcomes grounded in the source's own verbs."""
    core = _core_title(lesson.title)
    seen: set = set()
    phrases: List[str] = []
    candidates = [c.strip() for c in lesson.key_concepts if len(c.strip()) >= 12]
    candidates += _split_sentences(lesson.raw_text)
    for cand in candidates:
        ph = _outcome_from_sentence(cand, budget)
        if ph and ph not in seen:
            seen.add(ph)
            phrases.append(ph)
        if len(phrases) >= limit:
            break
    # Pad with distinct, complete core-title objectives when the source is thin.
    pads = [
        f"يشرح الطالب مفهوم {core}",
        f"يستعرض الطالب تطبيقات {core}",
        f"يناقش الطالب أهمية {core}",
        f"يطبق الطالب خطوات تطبيق {core}",
    ]
    for pad in pads:
        if len(phrases) >= max(2, limit - 1):
            break
        if pad not in seen:
            seen.add(pad)
            phrases.append(pad)
    return phrases[:limit]


def build_rules_lesson_plan(
    unit: CurriculumUnit,
    lesson: LessonBoundary,
    schema: TemplateSchema,
    context: GenerationContext,
) -> LessonPlanPayload:
    excerpts = _pick_excerpts(lesson)
    core = _core_title(lesson.title)
    learning_outcomes = _outcome_phrases(lesson) or [f"يشرح الطالب {core}"]
    # Specific source evidence must be visible in the activities and assessments.
    # Do not claim pedagogical depth that the uploaded material cannot support.
    source_points = [_clip(f"{core}: {e}", 115) for e in excerpts if e.strip()]
    if not source_points:
        source_points = [core]
    first_point = source_points[0]
    second_point = source_points[min(1, len(source_points) - 1)]
    third_point = source_points[min(2, len(source_points) - 1)]

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
                    f"{name}: {source_points[min(i, len(source_points) - 1)]}"
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

    def _activity(num: int, minutes: int, purpose: str, note: str, strategy: str) -> ActivityPlan:
        # The activity's grouping follows its element's strategy: cooperative
        # learning is a group activity; a lecture-phase activity is individual.
        cooperative = strategy == "تعلم تعاوني"
        return ActivityPlan(
            activity_number=num,
            duration_minutes=minutes,
            time_formatted=format_minutes(minutes),
            pattern="جماعي" if cooperative else "فردي",
            activity_type="دراسة حالة" if num == 1 else "بحث",
            purpose=purpose,
            teacher_procedures=(
                f"يعرض المعلم مقتطف المنهج: «{first_point if num == 1 else second_point}» ثم يطلب تفسير الفكرة بدليل من النص، ويصحح الإجابات."
            ),
            student_procedures=(
                (f"تحدد كل مجموعة فكرة من «{first_point if num == 1 else second_point}» وتشرحها بمثال من المادة، ثم تعرض دليلها."
                 if cooperative
                 else f"يستخرج الطالب معلومة من «{first_point if num == 1 else second_point}» ويشرحها ويذكر شاهدها من الدرس.")
            ),
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
        assessment_group_1=f"سؤال: ما الفكرة الأساسية في المقتطف «{first_point}»؟ ادعم إجابتك من النص.",
        assessment_group_2=f"طبّق أو فسّر المعلومة التالية بمثال من الدرس: «{second_point}».",
        assessment_group_3=f"قارن ما تعلمته بالمعلومة الواردة: «{third_point}»؛ بيّن وجه الارتباط.",
        presentation_class="، ".join(context.class_sections) if context.class_sections else "",
        location=context.location,
        lesson_date=context.lesson_date,
        total_duration_minutes=total,
        warm_up=f"اقرأ العبارة من الدرس: «{first_point}». ما المقصود بها؟ وما الدليل في النص؟",
        element_1_strategy=e1.teaching_strategy or "",
        element_1_time=e1.time_formatted,
        element_1_summary=e1.brief_description or e1.title,
        activity_1=_activity(1, act_minutes, f"تحليل النص: {first_point}", "استشهد بالمادة المرفوعة ولا تفترض معلومات غير مذكورة.", e1.teaching_strategy or ""),
        element_2_strategy=e2.teaching_strategy or "",
        element_2_time=e2.time_formatted,
        element_2_summary=e2.brief_description or e2.title,
        activity_2=_activity(2, act_minutes, f"تفسير وتطبيق: {second_point}", "اربط الإجابة بالمثال الوارد في المصدر.", e2.teaching_strategy or ""),
        rubric_group_1_header="المعرفة والفهم",
        rubric_group_1_items=[
            f"يستخرج فكرة صحيحة من: {first_point}",
            f"يفسر علاقة المعلومة بالمحتوى: {second_point}",
        ],
        rubric_group_2_header="المهارات والتطبيق",
        rubric_group_2_items=[
            f"يقدّم مثالاً مستنداً إلى: {second_point}",
            "يوضح موضع الدليل في النص ويعرض النتيجة",
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
