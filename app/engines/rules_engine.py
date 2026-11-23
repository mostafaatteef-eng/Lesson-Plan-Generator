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

class InsufficientCurriculumEvidence(ValueError):
    """The source does not contain enough explanatory content for a real plan."""


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
    """Prefer substantive source statements, not section headings or titles."""
    title_tokens = set(re.findall(r"[A-Za-z\u0621-\u064A]{3,}", lesson.title.lower()))

    def usable(sentence: str) -> bool:
        value = sentence.strip()
        # Avoid antecedent-free pronouns and publishing/running headers.
        if re.match(r"^(?:we|they|it|these|those|this|what we)\b", value, re.I):
            return False
        if re.match(r"^(?:read|choose|complete|match|discuss|write|listen|to:|subject:|com\b|org\b|dear\b)", value, re.I):
            return False
        if re.match(r"^[a-z]", value) or "@" in value:
            return False
        if re.search(r"Administration and Operation|Science Development Office|Page \d+ of|ALL RIGHTS RESERVED", value, re.I):
            return False
        words = re.findall(r"[A-Za-z\u0621-\u064A]{2,}", value)
        if len(words) < 7 or len(value) < 35:
            return False
        if re.match(r"^(?:unit|chapter|topic|lesson|الوحدة|الدرس)\s*[^:：]*[:：]", value, re.I):
            value = re.split(r"[:：]", value, maxsplit=1)[-1].strip()
            if len(value.split()) < 7:
                return False
        if title_tokens and len(set(w.lower() for w in words) - title_tokens) < 4:
            return False
        return True

    excerpts: List[str] = []
    # Session opening objectives and viewing instructions are not lesson facts.
    text = lesson.raw_text
    topic = re.search(r"Topic\s+1\s*[:：]", text, re.I)
    if topic:
        text = text[topic.end():]
    text = re.sub(r"(?<=\w)-\s*\n(?=\w)", "", text)
    text = re.sub(r"(?m)^.*(?:Definition|Data Importance:|Data Sourcing in AI)\s*$", "", text)
    text = re.sub(r"(?m)^\s*[•▪]\s*", "", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    for sent in _split_sentences(text):
        if usable(sent) and len(sent.strip()) <= (220 if re.search(r"[\u0621-\u064a]", sent) else 140):
            excerpt = sent.strip().lstrip("•▪ ")
            if excerpt and excerpt not in excerpts:
                excerpts.append(excerpt)
        if len(excerpts) >= limit:
            break
    if len(excerpts) < limit:
        for concept in lesson.key_concepts:
            concept = concept.strip()
            if usable(concept) and _verify_excerpt(concept, lesson.raw_text) and concept not in excerpts:
                excerpts.append(_clip(concept, 150))
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
    return phrases[:limit]


def source_cards(lesson):
    text = re.sub(r"\s+", " ", lesson.raw_text)
    cards = []

    def add(gates, target, outcome, question, criterion):
        spans = []
        for gate in gates:
            match = re.search(gate, text, re.I)
            if not match:
                return
            spans.append(match.group(0))
        # One card can need separated statements; preserve each span as its own
        # evidence record rather than joining unrelated sentences into a quote.
        cards.append((target, outcome, question, criterion, spans))

    if 'accuracy and error' in lesson.title.lower():
        add([r'The error in the use of any instrument is normally taken to be half of the smallest division on the scale of the instrument\.'],
            'Instrumental error', 'يحدد الطالب الخطأ الآلي من أصغر تدريج كما يوضحه الدرس.',
            'كيف يرتبط الخطأ الآلي بأصغر تدريج للأداة؟', 'يذكر نصف أصغر تدريج وفق النص')
        add([r'The Absolute Error.*?is the difference between the actual value.*?and the measured value.*?\(X\)'],
            'Absolute error', 'يشرح الطالب معنى الخطأ المطلق في القياس.',
            'ما المقصود بالخطأ المطلق؟', 'يفرق بين القيمة الفعلية والمقاسة وفق تعريف المصدر')
        add([r'The Relative Error.*?is the ratio between the absolute error.*?to the real value.*?\(Xo\)'],
            'Relative error', 'يشرح الطالب نسبة الخطأ النسبي إلى القيمة الحقيقية.',
            'ما المقصود بالخطأ النسبي؟ ما الكميتان في النسبة؟', 'يحدد نسبة الخطأ المطلق إلى القيمة الحقيقية')
        add([r'As the relative error decreases, the measurement accuracy is considered higher\.'],
            'Measurement accuracy', 'يربط الطالب انخفاض الخطأ النسبي بارتفاع دقة القياس.',
            'ماذا يحدث لدقة القياس عندما يقل الخطأ النسبي؟', 'يربط انخفاض الخطأ النسبي بارتفاع الدقة')

    if 'speed and velocity' in lesson.title.lower():
        add([r'Speed: is the distance moved by the object per unit time\. It is a scalar quantity\.'],
            'Speed', 'يشرح الطالب تعريف السرعة القياسية من المسافة والزمن.',
            'ما تعريف السرعة القياسية؟ هل هي كمية قياسية أم متجهة؟', 'يذكر المسافة لكل وحدة زمن وكونها قياسية')
        add([r'Velocity: is the displacement of the object per unit time\. It is a vector quantity'],
            'Velocity', 'يشرح الطالب تعريف السرعة المتجهة من الإزاحة والزمن.',
            'ما تعريف السرعة المتجهة؟ هل هي كمية قياسية أم متجهة؟', 'يذكر الإزاحة لكل وحدة زمن وكونها متجهة')
        add([r'Uniform velocity: the object velocity when it is displaced through equal displacements in equal times\.'],
            'Uniform velocity', 'يميز الطالب السرعة المتجهة المنتظمة من تساوي الإزاحات في أزمنة متساوية.',
            'متى تكون السرعة المتجهة منتظمة وفق الإزاحة والزمن؟', 'يذكر إزاحات متساوية في أزمنة متساوية')
        add([r'Non-uniform \(variable\) velocity: the object velocity when it is displaced through unequal displacements in equal times\.'],
            'Non-uniform velocity', 'يميز الطالب السرعة المتجهة غير المنتظمة من تغير الإزاحات في أزمنة متساوية.',
            'متى تكون السرعة المتجهة غير منتظمة وفق الدرس؟', 'يذكر إزاحات غير متساوية في أزمنة متساوية')

    if 'acceleration' in lesson.title.lower():
        add([r'Acceleration: [“"]?Is the change of the object velocity per unit time'],
            'Acceleration', 'يشرح الطالب تعريف العجلة بوصفها تغير السرعة المتجهة لكل وحدة زمن.',
            'ما تعريف العجلة بالنسبة للسرعة المتجهة والزمن؟', 'يذكر تغير السرعة المتجهة لكل وحدة زمن')
        add([r'change the speed or change the direction or change both\.'],
            'Changing velocity', 'يحدد الطالب صور تغير السرعة المتجهة المسببة للعجلة.',
            'كيف تحدث العجلة بتغير مقدار السرعة أو اتجاهها؟', 'يذكر تغير المقدار أو الاتجاه أو كليهما')
        add([r'positive acceleration \(increasing velocity\), negative acceleration or deceleration \(decreasing velocity\) or zero acceleration \(uniform velocity\)'],
            'Acceleration types', 'يميز الطالب العجلة الموجبة والسالبة والصفرية في إطار اتجاه الحركة المحدد بالدرس.',
            'باتخاذ اتجاه السرعة موجبا، متى تكون العجلة موجبة أو سالبة أو صفرية؟', 'يربط زيادة السرعة بالموجبة ونقصها بالسالبة وثباتها بالصفرية في الإطار المحدد')
        add([r'The slope of straight line expresses the value of acceleration'],
            'Velocity-time graph', 'يحدد الطالب دلالة ميل منحنى السرعة المتجهة والزمن في الحركة الموضحة.',
            'ماذا يمثل ميل الخط المستقيم في منحنى السرعة المتجهة والزمن؟', 'يحدد العجلة بوصفها ميل المنحنى')

    if 'equation of motions' in lesson.title.lower():
        # Free fall is a distinct lesson despite sharing the printed title.
        if 'Free fall' in text:
            add([r'fall of objects under the effect of their weights, only neglecting the effect of air resistance\. This motion is called free fall\.'],
                'Free fall', 'يشرح الطالب السقوط الحر مع إهمال مقاومة الهواء.',
                'ما المقصود بالسقوط الحر؟ ما الفرض المتعلق بمقاومة الهواء؟', 'يذكر تأثير الوزن فقط وإهمال مقاومة الهواء')
            add([r'at the absence of air resistance, all objects fall to the ground at the same acceleration\.'],
                'Equal fall acceleration', 'يحدد الطالب شرط تساوي عجلة سقوط الأجسام.',
                'ما شرط سقوط الأجسام بالعجلة نفسها في الدرس؟', 'يذكر غياب مقاومة الهواء')
            add([r'When an object falls freely \(from a high place\), the initial velocity = zero'],
                'Released object', 'يحدد الطالب السرعة الابتدائية للجسم المتروك للسقوط في حالة الدرس.',
                'ما السرعة الابتدائية للجسم المتروك ليسقط من السكون؟', 'يحدد السرعة الابتدائية بصفر في حالة الترك من السكون')
            add([r'When an object is thrown upwards until it reaches its maximum height, the final velocity = zero'],
                'Maximum height', 'يحدد الطالب السرعة اللحظية عند أقصى ارتفاع في القذف الرأسي.',
                'ما سرعة الجسم المقذوف رأسيا لأعلى عند أقصى ارتفاع؟', 'يحدد السرعة اللحظية بصفر عند أقصى ارتفاع')
        else:
            add([r'motion in a straight line with constant acceleration'],
                'Uniform acceleration condition', 'يحدد الطالب شرط استخدام معادلات الحركة المعروضة.',
                'ما شرط الحركة والتسارع في معادلات هذا الدرس؟', 'يذكر حركة في خط مستقيم بعجلة ثابتة')
            add([r'From the opposite graph, the slope of straight line represents the acceleration\.'],
                'Velocity-time slope', 'يحدد الطالب دلالة ميل منحنى السرعة والزمن للحركة المعروضة.',
                'ماذا يمثل ميل الخط المستقيم في منحنى السرعة والزمن؟', 'يحدد العجلة')
            add([r'While the area under the curve represents the displacement'],
                'Velocity-time area', 'يحدد الطالب دلالة المساحة تحت منحنى السرعة والزمن.',
                'ماذا تمثل المساحة تحت منحنى السرعة والزمن؟', 'يحدد الإزاحة')
            add([r'when the time taken by the object increases, the displacement covered by the object increases'],
                'Displacement and time', 'يصف الطالب ارتباط الزمن بالإزاحة في الحالة الواردة بالدرس.',
                'كيف تتغير الإزاحة بزيادة زمن الحركة في الحالة الموضحة؟', 'يذكر زيادة الإزاحة في الحالة الموضحة دون تعميم خارجها')

    if 'types of ai in the workplace' in lesson.title.lower():
        add([r'A Recruitment Management System \(RMS\) allows organizations to manage job post-?\s*ings, applications, or interviewing schedules\.'],
            'Recruitment Management System', 'يحدد الطالب وظائف نظام إدارة التوظيف في النص الإنجليزي.',
            'من النص الإنجليزي، اذكر ثلاث مهام يديرها RMS.', 'يسمي إعلانات الوظائف والطلبات ومواعيد المقابلات')
        add([r'emails, automated texts, or an FAQ section of the company’s website create a better communication experience for the candidates\.'],
            'Candidate communication', 'يستخرج الطالب وسائل التواصل مع المرشحين من نص التوظيف.',
            'استخرج وسائل التواصل مع المرشحين الواردة بالنص الإنجليزي.', 'يذكر البريد والرسائل الآلية وقسم الأسئلة الشائعة')
        add([r'The benefits include connecting with applicants best suited for the role, an efficient screening process without bias, and decreasing overall time to hire\.'],
            'Recruitment benefits', 'يلخص الطالب فوائد أتمتة التوظيف المذكورة في النص.',
            'لخص بالإنجليزية فوائد أتمتة التوظيف التي يذكرها النص.', 'يحافظ على معنى ملاءمة المرشح والفرز دون تحيز وتقليل زمن التوظيف بوصفها ادعاءات النص')
        add([r'candidate sourcing, resume review, or onboarding tasks can be optimized through automation\.'],
            'Automated tasks', 'يستخرج الطالب أمثلة لمهام التوظيف القابلة للأتمتة من النص.',
            'اذكر أمثلة مهام التوظيف التي يعرض النص أتمتتها.', 'يذكر البحث عن المرشحين ومراجعة السير والتهيئة الوظيفية')

    if 'tracking ai projects' in lesson.title.lower():
        add([r'Progress reports are documents that track the status and development of a project\.'],
            'Progress report', 'يشرح الطالب غرض تقرير تقدم المشروع بالاستناد إلى النص.',
            'ما غرض تقرير تقدم المشروع؟ أجب من النص الإنجليزي.', 'يذكر متابعة حالة المشروع وتطوره')
        add([r'Tools Used: GitHub for version control, Slack for team communication, Trello for task management, Google Drive for report storage\.'],
            'Project tools', 'يربط الطالب أدوات المشروع بوظائفها في التقرير.',
            'اربط GitHub وSlack وTrello وGoogle Drive بوظيفة كل منها في التقرير.', 'يطابق التحكم بالإصدارات والتواصل وإدارة المهام وحفظ التقارير بالترتيب')
        add([r'Faced challenges integrating Slack and Trello APIs seamlessly\. Resolution: Collaborated with tool support teams and updated integration scripts\.'],
            'Challenge and resolution', 'يستخرج الطالب تحدي تكامل الأدوات وحله من التقرير.',
            'ما تحدي تكامل الأدوات؟ كيف يذكر التقرير التعامل معه؟', 'يحدد تكامل Slack/Trello والتعاون مع الدعم وتحديث السكربتات')
        add([r'They help keep everyone informed about what has been done, what is currently happening, and what needs to be done next\.'],
            'Report time frames', 'يميز الطالب المنجز والحالي والخطوات التالية في تقرير التقدم.',
            'ما الفترات الثلاث للمعلومات التي يغطيها تقرير التقدم؟', 'يميز ما أنجز وما يجري وما ينبغي عمله لاحقا')

    if 'promoting innovations' in lesson.title.lower():
        add([r'Subject: Business Dashboard Offer'],
            'Email subject', 'يحدد الطالب موضوع الرسالة الترويجية من نموذج الدرس.',
            'ما عنوان موضوع الرسالة الإنجليزية النموذجية؟', 'يحدد Business Dashboard Offer')
        add([r'I am writing to introduce you to our latest innovation: our brand-new AI Ibdaa Dashboard\.'],
            'Reason for writing', 'يحدد الطالب غرض كتابة الرسالة الترويجية من النص.',
            'ما غرض كتابة الرسالة الإنجليزية النموذجية؟', 'يذكر تقديم AI Ibdaa Dashboard بوصفه منتج الرسالة')
        add([r'1\. Data Visualization:.*?2\. Predictive Analytics:.*?3\. Customization Options:.*?4\. Real-time Updates:'],
            'Advertised features', 'يستخرج الطالب خصائص اللوحة الأربع كما تعرضها الرسالة.',
            'سم بالإنجليزية الخصائص الأربع التي تعلنها الرسالة.', 'يسمي التصور البياني والتحليلات التنبؤية والتخصيص والتحديثات الفورية كخصائص معلنة بالنص')
        add([r'we would like to offer you a personalized demo where we can walk you through its features'],
            'Call to action', 'يحدد الطالب الدعوة إلى الإجراء في نموذج الرسالة.',
            'ما الإجراء الذي تدعو الرسالة المتلقي إليه؟', 'يحدد عرضا توضيحيا مخصصا للمنتج')

    if 'effective online collaboration' in lesson.title.lower():
        add([r'Test your technology.*?Make eye contact with your camera.*?Eliminate noise.*?Use proper lighting.*?Mute your microphone'],
            'Meeting protocol', 'يستخرج الطالب إرشادات الاجتماع عن بعد من قائمة الدرس.',
            'اختر ثلاثة إرشادات من قائمة الاجتماع عن بعد، واكتبها بالإنجليزية دون تخمين ترتيب الفيديو.', 'تطابق الإرشادات قائمة النص ولا يدعي ترتيب الاستماع غير المتاح')
        add([r'The meeting date and time.*?The participants and their roles.*?The meeting platform you are going to use and why you will be using it.*?The tools you are going to use for taking notes and collaboration.*?The meeting agenda.*?The meeting protocol'],
            'Meeting briefing', 'ينظم الطالب عناصر إحاطة الاجتماع كما حددها نشاط الدرس.',
            'سم عناصر إحاطة الاجتماع: الموعد والمشاركون والمنصة والأدوات وجدول الأعمال والبروتوكول.', 'يتضمن العناصر الستة دون اختلاق موعد أو أسماء مشاركين')
        add([r'Information is presented in a logical sequence\.'],
            'Presentation organization', 'يحدد الطالب معيار تنظيم العرض في سلم تقويم الدرس.',
            'ما معيار تنظيم المعلومات في سلم تقويم العرض؟', 'يذكر تسلسلا منطقيا للمعلومات')
        add([r'The speaker uses a clear, audible voice\.'],
            'Presentation delivery', 'يحدد الطالب معيار وضوح الصوت في عرض الإحاطة.',
            'ما معيار الصوت في سلم تقويم العرض بالدرس؟', 'يذكر صوتا واضحا مسموعا')
    return cards


def _grounded_outcomes(lesson: LessonBoundary) -> tuple[List[str], List[TraceabilityEntry]]:
    """Extract observable targets, never pad using a title or generic text task.

    This deliberately bounded fallback supports explicit learner performances,
    definitions and enumerations. It does not guess a domain's teaching goals.
    Each target has its own literal source evidence. Unsupported text is refused.
    """
    text = re.sub(r"\s+", " ", lesson.raw_text)
    candidates = []
    for sentence in re.split(r"[.!؟?\n؛]+|\s+و(?=ي[أ-ي]+\s+(?:الطالب|الطلاب))", lesson.raw_text):
        outcome = _outcome_from_sentence(sentence, 100)
        if outcome and re.match(r"^(?:يشرح|يحدد|يعدد|يصنف|يقارن|يكتب|يطبق|يحلل|يحسب|يرتب|يصمم|يميز|يختار|يعرّف) الطالب", outcome):
            candidates.append((outcome, sentence))
    # A capitalized noun phrase immediately before an explicit definition.
    # Preserve the source language of technical terms rather than fake translation.
    pattern = re.compile(
        r"\b((?:[Aa]n? |[Tt]he )?[A-Z]?[a-z]+(?: [a-z][a-z-]*){0,7}) "
        r"(is|are|refers to|means|has|have) ([^.!?]{15,320})(?:[.!?]|$)"
    )
    for match in pattern.finditer(text):
        target, relation, description = match.groups()
        # The pattern can start inside a running sentence. Require an actual
        # capitalized subject, then reject pronouns/instructions and fragments.
        if not target[0].isupper() or len(target) > 70:
            continue
        if re.match(r"^(?:In|If|What|How|Why|Describing|It|Its|This|That|These|Those|There|You|We|They|Here|To|For|By|Our)\b", target):
            continue
        if re.search(r"lesson|chapter|rights|office|page|book|impact", target, re.I):
            continue
        enumeration = relation in ('has', 'have')
        if enumeration and not re.search(r"elements|types|steps|stages|components", description, re.I):
            continue
        if not enumeration and not re.match(r"(?:a |an |the |two |defined|called|another |[0-9])", description):
            continue
        if relation == 'are' and not re.search(r"branches|types|defined|called|collection", description, re.I):
            continue
        verb = ('يعدد الطالب عناصر' if enumeration else
                'يصنف الطالب الفرعين' if relation == 'are' and 'branches' in description else
                'يشرح الطالب تعريف')
        outcome = f"{verb} {target} الوارد في الدرس."
        candidates.append((outcome, match.group(0).strip()))
    for match in re.finditer(r"(?:^|[.\n])\s*([أ-ي][أ-ي \u064b-\u0652]{2,65}?)\s+(هو|هي|تشمل|يتكون من|تتكون من)\s+([^.!؟\n]{15,220})", lesson.raw_text):
        target, relation, description = match.groups()
        verb = 'يعدد' if relation in ('تشمل', 'يتكون من', 'تتكون من') else 'يعرّف'
        candidates.append((f"{verb} الطالب {target.strip()} كما ورد في الدرس.", match.group(0).strip(' .\n')))
    for match in re.finditer(r"(?:^|[.\n]|\sو)(يشرح|يحدد|يعدد|يصنف|يقارن|يكتب|يطبق|يحلل|يحسب|يرتب|يصمم|يميز|يختار)\s+(?:الطالب|الطلاب)\s+([^.!؟\n]{12,180})", lesson.raw_text):
        candidates.append((f"{match.group(1)} الطالب {match.group(2).strip()}", match.group(0).strip(' .\nو')))
    # Broader source shapes: numbered definitions, mixed-case terms, a
    # label followed by a definition on the next line, and explicit categories.
    # Work from line starts so preceding headings cannot become part of a term.
    expanded = []
    lines = lesson.raw_text.splitlines()
    subject = r"(?:[A-Za-z][A-Za-z()& /-]*?)"
    for index, raw in enumerate(lines):
        line = raw.strip().lstrip('•▪ ')
        line = re.sub(r"^(?:(?:First|Second|Third)\s*:\s*|[0-9]+[) .-]+)", "", line, flags=re.I)
        window = line
        # Join only after the relation starts on this line, or after a short
        # colon-terminated label followed immediately by an explicit definition.
        relation_on_line = re.search(r"\b(?:is|are|means|refers to|can be classified into)\b", line, re.I)
        label_then_definition = line.endswith(':') and len(line.split()) <= 7 and index+1 < len(lines) and re.match(r'^[“\"]?(?:Is|is|Are|are)\b', lines[index+1].strip())
        if not relation_on_line and not label_then_definition:
            continue
        window = re.sub(r"\s+", " ", ' '.join([line] + lines[index+1:index+5])).strip()
        # Keep target and the full predicate as literal evidence, never a
        # translation or a guessed formula. Colon and quote layouts are common.
        definition = re.match(
            r"(" + subject + r")(?:\s*:\s*|\s+)(?:[“\"]?)(?:it\s+)?"
            r"(is|are|refers to|means|can be classified into|is measured in|are measured in|is composed of|are comprised of)\s+"
            r"([^.!?]{12,280})(?:[.!?]|$)", window, re.I)
        if not definition:
            continue
        target, relation, description = definition.groups()
        target = target.strip(' :')
        if len(target) > 65 or len(target.split()) > 8:
            continue
        if target.lower() in ('quantity', 'table', 'example', 'examples', 'this', 'it', 'there', 'they', 'we', 'you', 'what', 'which', 'these quantities'):
            continue
        if re.match(r"^(?:if|what|why|how|there|you|we|they|it|this|that|these|those|for example|such|some|then|take|go|head|the following|the previous)\b",target,re.I):
            continue
        if re.search(r"lesson|office|page|rights|introduction|structure|procedure|exercise|figure|table|number of|following|previous|\b(?:what|which|when|where|how|then)\b",target,re.I):
            continue
        # Reject non-defining statements and imperatives. Definitions begin
        # with a noun phrase, not a bare adjective or open task instruction.
        if relation.lower() in ('is','are') and not re.match(r"(?:a |an |the |defined|called|comprised|composed|measured)",description,re.I):
            continue
        if 'classified' in relation.lower():
            outcome=f"يصنف الطالب {target} إلى الفئات المذكورة في الدرس."
        elif 'measured' in relation.lower() or description.lower().startswith('measured'):
            outcome=f"يحدد الطالب وحدة قياس {target} المذكورة في الدرس."
        elif any(w in relation.lower()+' '+description.lower() for w in ['composed of','comprised of']):
            outcome=f"يعدد الطالب مكونات {target} الواردة في الدرس."
        else:
            outcome=f"يشرح الطالب تعريف {target} الوارد في الدرس."
        expanded.append((outcome, definition.group(0).strip()))
    # Three-line source table rows: quantity, unit name, unit symbol.
    # No unit values are supplied by the program.
    table_rows = []
    for index, raw in enumerate(lines[:-2]):
        row = re.fullmatch(r"\s*\d+[)-]\s*([A-Za-z][A-Za-z &-]{1,40})(?:\s*\([^)]*\))?\s*", raw)
        if not row:
            continue
        unit_name, symbol = lines[index+1].strip(), lines[index+2].strip()
        if not re.fullmatch(r"[A-Za-z]{2,18}",unit_name) or not re.fullmatch(r"[A-Za-z]{1,4}",symbol):
            continue
        excerpt = '\n'.join(lines[index:index+3]).strip()
        table_rows.append((f"يحدد الطالب وحدة قياس {row.group(1).strip()} ورمزها من جدول الدرس: {unit_name} ({symbol}).",excerpt))
    # Avoid antecedent-free fragments and accidental joins in both grammars.
    def valid_target(item):
        outcome = item[0]
        target = re.sub(r"^.*?(?:تعريف |مكونات |وحدة قياس |عناصر |الفرعين )", "",outcome)
        if re.match(r"^(?:Quantity\b|Such\b|Then\b|[a-z]\)|meter/|Motion in which\b|Tail\b)",target,re.I):
            return False
        return True
    candidates = [item for item in candidates + expanded if valid_target(item)] + table_rows
    outcomes, evidence, seen = [], [], set()
    for outcome, excerpt in candidates:
        key = re.sub(r'\b(?:the|an?)\s+|\s*\([^)]*\)', '', outcome.casefold()).rstrip('.')
        if key in seen or not _verify_excerpt(excerpt, lesson.raw_text):
            continue
        seen.add(key)
        outcomes.append(outcome)
        evidence.append(TraceabilityEntry(
            field_key=f"learning_outcomes.{len(outcomes)-1}",
            field_label=f"دليل ناتج التعلم {len(outcomes)}",
            supporting_excerpt=excerpt,
            source_pages=list(range(lesson.start_page, lesson.end_page + 1)),
            verified_in_source=True,
        ))
        if len(outcomes) == 4:
            break
    if len(outcomes) < 3:
        supported = source_cards(lesson)
        if len(supported) >= 3:
            outcomes, evidence = [], []
            for target, outcome, question, criterion, spans in supported[:4]:
                if not all(_verify_excerpt(span, lesson.raw_text) for span in spans):
                    continue
                field = f"learning_outcomes.{len(outcomes)}"
                outcomes.append(outcome)
                for span in spans:
                    evidence.append(TraceabilityEntry(field_key=field,
                        field_label="دليل ناتج التعلم", supporting_excerpt=span,
                        source_pages=list(range(lesson.start_page, lesson.end_page + 1)),
                        verified_in_source=True))
    return outcomes, evidence


def _grounded_practice(payload: LessonPlanPayload, lesson: LessonBoundary) -> LessonPlanPayload:
    """Build named tasks from the same verified targets as the outcomes.

    The task mechanics are a proposed teaching adaptation. Their subject matter
    and answer criteria come only from each target's own source evidence.
    """
    cards = []
    entries = {e.field_key: e for e in payload.traceability}
    patterned = {card[1]: card for card in source_cards(lesson)}
    for i, outcome in enumerate(payload.learning_outcomes):
        evidence = entries.get(f"learning_outcomes.{i}")
        if not evidence or not _verify_excerpt(evidence.supporting_excerpt, lesson.raw_text):
            continue
        if outcome in patterned:
            target, _, question, criterion, spans = patterned[outcome]
            cards.append((target, question, criterion, evidence))
            continue
        target = None
        patterns = [
            ('definition', r"^يشرح الطالب تعريف (.+?) الوارد في الدرس"),
            ('definition', r"^يعرّف الطالب (.+?) كما ورد في الدرس"),
            ('components', r"^يعدد الطالب مكونات (.+?) الواردة في الدرس"),
            ('components', r"^يعدد الطالب عناصر (.+?) الوارد في الدرس"),
            ('classification', r"^يصنف الطالب (.+?) إلى الفئات المذكورة في الدرس"),
            ('branches', r"^يصنف الطالب الفرعين (.+?) الوارد في الدرس"),
            ('unit', r"^يحدد الطالب وحدة قياس (.+?) (?:ورمزها من جدول|المذكورة في) الدرس"),
        ]
        for kind, pattern in patterns:
            match = re.search(pattern, outcome)
            if match:
                target = match.group(1).strip()
                break
        if target:
            if kind == 'definition':
                question = f"ما تعريف {target}؟"
                criterion = f"تعريف {target} يحافظ على معنى تعريف المصدر"
            elif kind == 'components':
                question = f"عدد مكونات {target} المذكورة في الدرس."
                criterion = f"قائمة مكونات {target} تطابق المصدر دون إضافة"
            elif kind == 'branches':
                question = f"سم الفرعين المذكورين: {target}، وحدد المجال الذي ينتميان إليه."
                criterion = f"تسمية {target} وربطهما بالمجال المذكور في المصدر"
            elif kind == 'classification':
                question = f"ما تصنيف {target} الوارد في الدرس؟ سم الفئات."
                criterion = f"فئات {target} وتسمياتها صحيحة وفق المصدر"
            else:
                question = f"ما وحدة قياس {target} ورمزها المذكوران في الدرس؟"
                criterion = f"وحدة {target} ورمزها مطابقان للمصدر"
        else:
            # Explicit Arabic source objectives remain actual tasks, rather than
            # being reduced to an instruction to summarize an unnamed excerpt.
            action = re.match(r"^(يشرح|يحدد|يعدد|يصنف|يقارن|يكتب|يطبق|يحلل|يحسب|يرتب|يصمم|يميز|يختار) الطالب (.+)", outcome)
            if not action:
                continue
            imperatives = dict(zip(
                ['يشرح','يحدد','يعدد','يصنف','يقارن','يكتب','يطبق','يحلل','يحسب','يرتب','يصمم','يميز','يختار'],
                ['اشرح','حدد','عدد','صنف','قارن','اكتب','طبق','حلل','احسب','رتب','صمم','ميز','اختر']))
            target = action.group(2).rstrip(' .')
            question = f"{imperatives[action.group(1)]} {target}."
            criterion = f"إنجاز المهمة: {target} وفق دليل الدرس"
        cards.append((target, question, criterion, evidence))
    if len(cards) < 3:
        raise InsufficientCurriculumEvidence(
            "تعذر بناء أنشطة وتقويم لثلاثة أهداف محددة لها دليل من الدرس؛ لن تستبدل بمهام عامة.")
    groups = [cards[:2], cards[2:]]
    def questions(group):
        return ' '.join(f"{i+1}) {card[1]}" for i, card in enumerate(group))
    def evidence_for(field, group):
        for card in group:
            source = card[3]
            sources = [e for e in list(payload.traceability)
                       if e.field_key == source.field_key] or [source]
            for entry in sources:
                payload.traceability.append(TraceabilityEntry(
                    field_key=field, field_label="دليل المهمة ومعيار الإجابة",
                    supporting_excerpt=entry.supporting_excerpt,
                    source_pages=entry.source_pages, verified_in_source=True))
    for num, group in enumerate(groups, 1):
        activity = getattr(payload, f"activity_{num}")
        targets = ' / '.join(card[0] for card in group)
        activity.activity_type = "أخرى"
        activity.purpose = f"بطاقة مقترحة: {targets}."
        activity.teacher_procedures = f"يطرح: {questions(group)} يصحح الإجابات من مواضعها في الدرس."
        actor = "الطالب" if num == 1 else "أفراد المجموعة"
        activity.student_procedures = f"يجيب {actor} عن الأسئلة المحددة، مع موضع الدليل، ثم يصحح الإجابة بعد المراجعة."
        activity.student_note = "الناتج: بطاقة إجابة للأسئلة المحددة أعلاه. النجاح: إجابة صحيحة لكل سؤال مع موضع الدليل."
        setattr(payload, f"element_{num}_summary", f"مفاهيم الدرس المستهدفة: {targets}. المطلوب: التعريف أو القائمة أو الوحدة كما يحدد سؤال النشاط أدناه.")
        for subfield in ['purpose','teacher_procedures','student_procedures','student_note']:
            evidence_for(f"activity_{num}.{subfield}", group)
        evidence_for(f"element_{num}_summary", group)
        evidence_for(f"assessment_group_{num}", group)
        setattr(payload, f"assessment_group_{num}", questions(group))
        setattr(payload, f"rubric_group_{num}_items", [card[2] for card in group])
        for i, card in enumerate(group):
            evidence_for(f"rubric_group_{num}_items.{i}", [card])
    payload.assessment_group_3 = "بطاقة خروج دون الرجوع للنص: " + cards[-1][1]
    evidence_for('assessment_group_3', [cards[-1]])
    payload.warm_up = "تكييف تدريسي مقترح من مفاهيم الدرس. سؤال تمهيدي: " + cards[0][1]
    evidence_for('warm_up', [cards[0]])
    summaries = [payload.warm_up, payload.element_1_summary, payload.element_2_summary,
                 payload.assessment_group_1, payload.assessment_group_3]
    for i, (element, summary) in enumerate(zip(payload.lesson_elements, summaries)):
        element.brief_description = summary
        evidence_for(f"lesson_elements.{i}.brief_description", [cards[0]] if i == 0 else groups[0] if i in (1,3) else groups[1] if i == 2 else [cards[-1]])
    payload.missing_curriculum_notes.append(
        "تكييف مقترح: توزيع الأهداف على بطاقتي إجابة والمراجعة الفردية والجماعية من إعداد المحرك؛ المفاهيم ومعايير الإجابة من الدرس، وليست تجربة عملية أو شرحا مولدا بالذكاء الاصطناعي.")
    return payload


def _trace_specialized_practice(payload: LessonPlanPayload, lesson: LessonBoundary) -> None:
    questionnaire = any('QuestionPro' in e.supporting_excerpt for e in payload.traceability)
    groups = (
        [['open-ended', 'closed-ended', 'rating scale', 'biased', 'canteen'],
         ['target population', 'small group', 'Google Forms', 'QuestionPro', 'validity', 'reliability', 'Cronbach']]
        if questionnaire else
        [['Structured Data', 'Unstructured Data', 'Semi-structured Data'],
         ['hospital', 'privacy', 'bias', 'BeautifulSoup', 'Scrapy']]
    )
    text = re.sub(r"\s+", " ", lesson.raw_text)
    def add(field, terms):
        for term in terms:
            match = re.search(re.escape(term), text, re.I)
            if not match:
                continue
            # Context on both sides, kept as a literal, verified source span.
            start = max(text.rfind('. ', 0, match.start()) + 2, match.start()-100, 0)
            end = text.find('. ', match.end())
            end = min(end+1 if end >= 0 else len(text), match.end()+260)
            excerpt = text[start:end].strip()
            payload.traceability.append(TraceabilityEntry(field_key=field,
                field_label="دليل التكييف المتخصص", supporting_excerpt=excerpt,
                source_pages=list(range(lesson.start_page,lesson.end_page+1)),
                verified_in_source=_verify_excerpt(excerpt,lesson.raw_text)))
    for num, terms in enumerate(groups,1):
        for subfield in ['purpose','teacher_procedures','student_procedures','student_note']:
            add(f"activity_{num}.{subfield}",terms)
        for field in [f"element_{num}_summary",f"assessment_group_{num}"]:
            add(field,terms)
        for i in range(len(getattr(payload,f"rubric_group_{num}_items"))):
            add(f"rubric_group_{num}_items.{i}",terms)
    add('assessment_group_3',groups[1])
    add('warm_up',groups[0])
    for i in range(5):
        add(f"lesson_elements.{i}.brief_description",groups[0] if i in (0,1,3) else groups[1])


def _source_unit_number(title: str) -> str:
    match = re.search(r"(?:unit|الوحدة)\s*[:：]?\s*([0-9٠-٩]+)", title, re.I)
    return match.group(1) if match else "غير محدد"


def build_rules_lesson_plan(
    unit: CurriculumUnit,
    lesson: LessonBoundary,
    schema: TemplateSchema,
    context: GenerationContext,
) -> LessonPlanPayload:
    excerpts = _pick_excerpts(lesson)
    core = _core_title(lesson.title)
    learning_outcomes, outcome_evidence = _grounded_outcomes(lesson)
    # Specific source evidence must be visible in the activities and assessments.
    # Do not claim pedagogical depth that the uploaded material cannot support.
    source_points = [e for e in excerpts if e.strip()]
    if len(source_points) < 2:
        raise InsufficientCurriculumEvidence(
            "المحتوى المستخرج من الدرس لا يتضمن معلومات كافية لإنتاج أنشطة وتقييمات دقيقة. "
            "راجع صفحات الدرس أو ارفع نسخة تحتوي على النص التفصيلي؛ لن تُنتج خطة عامة بعنوان الدرس فقط."
        )
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
                f"يعرض مقتطف المصدر في العنصر {num} ويطلب تفسيره وتحديد الدليل فيه، ثم يصحح التفسير بمقارنته بالنص."
            ),
            student_procedures=(
                ("تكتب المجموعة تفسيرًا للمقتطف الثاني، وتحدد عبارته الداعمة وتعرض النتيجة."
                 if cooperative
                 else "يكتب الطالب تفسيرًا للمقتطف الأول ويحدد عبارته الداعمة، ثم يراجعه مع المعلم.")
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
        unit_number=_source_unit_number(unit.unit_title),
        unit_name=unit.unit_title,
        branch=context.branch,
        knowledge_code=context.knowledge_code,
        lesson_title=lesson.title,
        learning_outcomes=learning_outcomes,
        lesson_elements=elements,
        selected_strategies=selected_strategies,
        selected_resources=selected_resources,
        assessment_group_1="ما الفكرة الأساسية للمقتطف الأول؟ اكتب تفسيرًا صحيحًا ودليلًا من المصدر.",
        assessment_group_2="فسر المقتطف الثاني وقارن بينه وبين الأول. اذكر من المصدر وجه ارتباط أو اختلاف، أو وضح إن لم تجد علاقة مباشرة.",
        assessment_group_3="راجع التفسيرين: حدد عبارة مطابقة للمصدر وعبارة تحتاج إلى تعديل، مع بيان السبب.",
        presentation_class="، ".join(context.class_sections) if context.class_sections else "",
        location=context.location,
        lesson_date=context.lesson_date,
        total_duration_minutes=total,
        warm_up="ما موضوع الدرس؟ اقرأ عنوانه وحدد سؤالًا تتوقع أن يجيب عنه النص. بعد القراءة راجع توقعك.",
        element_1_strategy=e1.teaching_strategy or "",
        element_1_time=e1.time_formatted,
        element_1_summary=f"مقتطف المصدر الأول: {first_point}",
        activity_1=_activity(1, act_minutes, "تفسير المقتطف الأول مع شاهد نصي.", "استشهد بالمادة المرفوعة ولا تفترض معلومات غير مذكورة.", e1.teaching_strategy or ""),
        element_2_strategy=e2.teaching_strategy or "",
        element_2_time=e2.time_formatted,
        element_2_summary=f"مقتطف المصدر الثاني: {second_point}",
        activity_2=_activity(2, act_minutes, "تفسير المقتطف الثاني ومراجعة الدليل في مجموعة.", "اربط الإجابة بالمثال الوارد في المصدر.", e2.teaching_strategy or ""),
        rubric_group_1_header="المعرفة والفهم",
        rubric_group_1_items=[
            "تفسير المقتطف الأول يحافظ على المعنى",
            "دليل نصي صحيح يدعم التفسير",
        ],
        rubric_group_2_header="المهارات والتطبيق",
        rubric_group_2_items=[
            "تفسير المقتطف الثاني مرتبط بالنص دون إضافة غير موثقة",
            "يوضح موضع الدليل في النص ويعرض النتيجة",
        ],
        traceability=outcome_evidence,
        missing_curriculum_notes=[RULES_MODE_LABEL_AR],
    )
    # Specialized, source-gated adaptations keep their established content.
    payload = _enrich_questionnaire(_enrich_data_sourcing(payload, lesson), lesson)
    if not any("تكييف مقترح" in note for note in payload.missing_curriculum_notes):
        payload = _grounded_practice(payload, lesson)
    else:
        _trace_specialized_practice(payload, lesson)
    if len(payload.learning_outcomes) < 3:
        raise InsufficientCurriculumEvidence(
            "لا يكفي النص لصياغة ثلاثة نواتج تعلم محددة مرتبطة بالدرس في الوضع القواعدي. "
            "ارفع محتوى يوضح المفاهيم أو المهارات المطلوبة؛ لن تضاف نواتج عامة لاستكمال العدد."
        )
    # Visible in the printable plan, not just response metadata or web UI.
    payload.warm_up = "مسودة بالقواعد؛ مقترحات لاعتماد المعلم. " + payload.warm_up
    if not any("تكييف مقترح" in n for n in payload.missing_curriculum_notes):
        payload.missing_curriculum_notes.append("تكييف مقترح من محتوى الدرس، يراجعه المعلم قبل الاعتماد.")
    return payload


def _enrich_data_sourcing(payload: LessonPlanPayload, lesson: LessonBoundary) -> LessonPlanPayload:
    """A bounded curriculum pattern, activated only when its supporting text exists.

    The hospital scenario and tools are from the uploaded source. The 50-minute
    selection and worksheet are teacher-review adaptations, not source quotes.
    No network collection or paid service is performed by this plan.
    """
    normalized = re.sub(r"\s+", " ", lesson.raw_text).lower()
    required = ["structured data", "unstructured data", "semi-structured data",
                "publicly available datasets", "web scraping", "beautifulsoup", "scrapy",
                "hospital", "medical images", "privacy", "bias"]
    if "data sourcing" not in lesson.title.lower() or not all(term in normalized for term in required):
        return payload
    payload.learning_outcomes = [
        "يصنف الطالب الجداول والصور و JSON إلى بيانات منظمة وغير منظمة وشبه منظمة.",
        "يقارن الطالب بين البيانات الداخلية والمجموعات المفتوحة واستخلاص الويب وفق التكلفة والجودة.",
        "يقترح الطالب إجراءين لحماية خصوصية صور المرضى وتحسين جودة بياناتها، مستندا إلى المنهج.",
        "يحدد الطالب وظيفة أدوات جمع بيانات الويب، ويذكر ضرورة الإذن والتنظيف: BeautifulSoup/Scrapy.",
    ]
    payload.warm_up = "توليد بالقواعد للمراجعة. تكييف تدريسي مقترح لـ50دقيقة من صفحات الدرس، لا نقل حرفي لكل أنشطته. من سؤال المنهج: أيهما بيانات غير منظمة، جدول رواتب أم منشورات وتعليقات؟ علل التصنيف."
    payload.element_1_summary = "تصنيف البيانات: جداول منظمة، صور ونصوص غير منظمة، وJSON شبه منظم؛ مقارنة البيانات الداخلية والمفتوحة واستخلاص الويب."
    payload.element_2_summary = "حالة المستشفى من المنهج: جودة صور الأشعة ودقة الوسوم، خصوصية المرضى، وإتاحة عدد كاف من الصور."
    payload.activity_1.purpose = "إنتاج جدول يصنف ثلاثة أمثلة ويقارن ثلاثة مصادر للبيانات."
    payload.activity_1.teacher_procedures = "يعرض أمثلة الجداول والصور و JSON. يطلب تصنيفها ثم يقارن مصادر البيانات الداخلية والمفتوحة واستخلاص الويب من المنهج."
    payload.activity_1.student_procedures = "يصنف الطالب الأمثلة الثلاثة؛ يسجل ميزة وقيدا لكل مصدر؛ يسلم جدول المقارنة للتصحيح."
    payload.activity_1.student_note = "ورقة عمل مقترحة: مثال / نوع البيانات / السبب. معيار النجاح: ثلاثة تصنيفات صحيحة مع سبب لكل تصنيف."
    payload.activity_2.purpose = "إنتاج خطة جمع بيانات مختصرة لحالة المستشفى الواردة في المنهج."
    payload.activity_2.teacher_procedures = "يقسم الطلاب مجموعات ويعرض حالة صور الأشعة. يطلب تحديد مشكلة جودة ومشكلة خصوصية، ثم يراجع الحلول بمقارنة أدلتها من النص."
    payload.activity_2.student_procedures = "تحدد المجموعة مصدر الصور وشرط الجودة وإجراء حماية؛ تعرض قرارها مع شاهد من المنهج، وتراجع اقتراح مجموعة أخرى."
    payload.activity_2.student_note = "ناتج مقترح: بطاقة قرار من ثلاثة بنود. التقييم: ملاءمة المصدر، دقة الوسوم، وحماية هوية المريض."
    payload.assessment_group_1 = "صنف: جدول رواتب، تعليقات منصة اجتماعية، وملف JSON. اذكر سببا لكل إجابة."
    payload.assessment_group_2 = "لماذا لا تكفي صور أشعة كثيرة منخفضة الجودة؟ اقترح إجراء جودة وإجراء خصوصية لحالة المستشفى."
    payload.assessment_group_3 = "قارن مصدر بيانات مفتوحا باستخلاص الويب: ميزة وقيد لكل منهما. ما وظيفة أداتي استخلاص الويب BeautifulSoup/Scrapy؟"
    payload.rubric_group_1_items = ["ثلاثة تصنيفات صحيحة مع تعليلها", "ميزة وقيد صحيحان لكل مصدر مقارنة"]
    payload.rubric_group_2_items = ["إجراء جودة وإجراء خصوصية مناسبان لحالة المستشفى", "القرار مدعوم بشاهد محدد من المنهج"]
    summaries = [payload.warm_up, payload.element_1_summary, payload.element_2_summary,
                 payload.assessment_group_1, "بطاقة خروج: اختر مصدر بيانات وعلل اختيارك بميزة وقيد من النص."]
    for element, summary in zip(payload.lesson_elements, summaries):
        element.brief_description = summary
    evidence_terms = ["Structured Data", "Unstructured Data", "Semi-structured Data", "BeautifulSoup", "Scrapy", "hospital"]
    payload.traceability.extend(
        TraceabilityEntry(field_key="activity_2" if term == "hospital" else "learning_outcomes",
                          field_label="دليل تكييف درس مصادر البيانات", supporting_excerpt=term,
                          source_pages=list(range(lesson.start_page, lesson.end_page + 1)),
                          verified_in_source=_verify_excerpt(term, lesson.raw_text))
        for term in evidence_terms
    )
    payload.missing_curriculum_notes.append(
        "تكييف مقترح للحصة: اختيرت مهارات التصنيف والمقارنة وحالة المستشفى لتناسب50دقيقة؛ ليس تغطية كاملة لكل أنشطة الدرس الأصلي. لا يتضمن جمعا حيا للبيانات أو استخدام خدمات مدفوعة."
    )
    return payload


def _enrich_questionnaire(payload: LessonPlanPayload, lesson: LessonBoundary) -> LessonPlanPayload:
    """A source-gated questionnaire adaptation, not a general generation claim."""
    normalized = re.sub(r"\s+", " ", lesson.raw_text).lower()
    required = ["questionnaire", "target population", "open-ended", "closed-ended",
                "rating scale", "biased", "validity", "reliability", "cronbach",
                "google forms", "questionpro", "canteen", "small group"]
    if not all(term in normalized for term in required):
        return payload
    payload.learning_outcomes = [
        "يرتب الطالب خطوات تصميم الاستبيان من تحديد الهدف إلى المراجعة والتجريب.",
        "يصنف الطالب الأسئلة إلى مفتوحة ومغلقة واختيار متعدد وتقدير، مع تعليل التصنيف.",
        "يعيد الطالب صياغة سؤال المقصف المتحيز الوارد في المصدر بصياغة محايدة.",
        "يميز الطالب الصدق من الثبات ويحدد وظيفة معامل ألفا كرونباخ في فحص الثبات.",
    ]
    payload.warm_up = "توليد بالقواعد للمراجعة. تكييف مقترح لـ50 دقيقة. من المصدر: لماذا يتحيز سؤال أليس المقصف ممتازا؟ قارن بسؤال ما مدى رضاك عن المقصف؟"
    payload.element_1_summary = "الاستبيان لجمع بيانات البحث: تحديد الهدف والفئة، اختيار أنواع الأسئلة، تنظيمها ثم مراجعتها وتجريبها. الصدق يقيس المقصود والثبات اتساق النتائج."
    payload.element_2_summary = "تصميم استبيان قصير محايد: وضوح اللغة، عدم التكرار، تحديد الوحدات، السرية وتجريب مجموعة صغيرة. أدوات المصدر: Google Forms / QuestionPro"
    payload.activity_1.purpose = "تصنيف أربعة أسئلة وتحسين سؤال المقصف المتحيز."
    payload.activity_1.teacher_procedures = "يعرض أنواع أسئلة المصدر ومثال المقصف. يقدم أربعة أسئلة مقترحة: رأي مفتوح، نعم أو لا، اختيار متعدد، ومقياس رضا من واحد إلى خمسة."
    payload.activity_1.student_procedures = "يصنف الطالب الأسئلة الأربعة ويبرر كل تصنيف؛ يعيد صياغة سؤال المقصف بحياد ويقارن إجابتين مع زميله."
    payload.activity_1.student_note = "ورقة مقترحة: السؤال / نوعه / مبرر التصنيف. النجاح: أربعة تصنيفات صحيحة وسؤال محايد واضح."
    payload.activity_2.purpose = "إنتاج مسودة استبيان من أربعة أسئلة لهدف وفئة محددين."
    payload.activity_2.teacher_procedures = "يقسم الطلاب مجموعات. يطلب هدفا وفئة مستهدفة وأربعة أسئلة؛ يراجع الوضوح والحياد والسرية. يوضح خطوات إنشاء نموذج رقمي دون نشره أو جمع بيانات شخصية."
    payload.activity_2.student_procedures = "تصمم المجموعة المسودة مع مقدمة وختام. تختار أداة من المصدر وتبررها؛ تتبادل مراجعتها مع مجموعة أخرى وتقترح تجربة صغيرة وتعديلا بعد المراجعة."
    payload.activity_2.student_note = "ناتج مقترح: مسودة وبطاقة مراجعة للوضوح والحياد والترتيب والسرية. لا حساب مدفوع ولا نشر أو جمع فعلي للبيانات."
    payload.assessment_group_1 = "رتب: اختيار الأسئلة، تحديد الهدف، التجريب، تحديد الفئة، تنظيم الأسئلة. هل مقياس التقدير مفتوح أم مغلق؟ علل."
    payload.assessment_group_2 = "حسن سؤال أليس المقصف ممتازا؟ ما الفرق بين الصدق والثبات؟ ما وظيفة ألفا كرونباخ المذكور مع SPSS؟"
    payload.assessment_group_3 = "راجع مسودة استبيان: حدد سؤالا غامضا أو متحيزا واقترح تعديله وخطة لتجربته على مجموعة صغيرة."
    payload.rubric_group_1_items = ["ترتيب الخطوات الخمس وتصنيف مقياس التقدير بدقة", "تمييز الصدق والثبات وذكر ألفا كرونباخ لفحص الثبات"]
    payload.rubric_group_2_items = ["مسودة محايدة واضحة مرتبطة بهدف وفئة محددين", "مراجعة السرية وخطة تجريب وتعديل موثقة"]
    summaries = [payload.warm_up, payload.element_1_summary, payload.element_2_summary,
                 payload.assessment_group_1, "بطاقة خروج: اذكر تعديلا يجعل سؤال الاستبيان أوضح وأقل تحيزا."]
    for element, summary in zip(payload.lesson_elements, summaries):
        element.brief_description = summary
    for term in ["target population", "rating scale", "biased", "validity", "reliability", "Cronbach", "Google Forms", "QuestionPro"]:
        payload.traceability.append(TraceabilityEntry(field_key="learning_outcomes", field_label="دليل تكييف تصميم الاستبيان", supporting_excerpt=term, source_pages=list(range(lesson.start_page, lesson.end_page + 1)), verified_in_source=_verify_excerpt(term, lesson.raw_text)))
    payload.missing_curriculum_notes.append("تكييف مقترح لخمسين دقيقة: الأسئلة الأربعة وورقة العمل مقترحتان؛ أمثلة المقصف والمفاهيم والأدوات من المصدر. لا تشمل الحصة حساب ألفا كرونباخ أو نشر استبيان حي. تعريف الصدق المستخدم هو قياس الأداة لما صممت لقياسه، لا مساواته بتمثيل العينة للمجتمع.")
    return payload
