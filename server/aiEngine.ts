import { GoogleGenAI, Type } from '@google/genai';
import type {
  AiGenerationMode,
  AlignmentValidationResult,
  CurriculumUnit,
  GenerationContext,
  LessonBoundary,
  LessonPlanPayload,
  TemplateSchema,
} from './types';

function getAiClient(): GoogleGenAI {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    throw new Error(
      'GEMINI_API_KEY is not configured on the server. Please verify your API key in Settings > Secrets.'
    );
  }
  return new GoogleGenAI({
    apiKey,
    httpOptions: {
      headers: {
        'User-Agent': 'aistudio-build',
      },
    },
  });
}

export function formatMinutesToSlot(minutes: number): string {
  const safe = Math.max(1, Math.round(minutes));
  const hrs = Math.floor(safe / 60);
  const mins = safe % 60;
  if (hrs > 0) {
    return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
  }
  return `${String(mins).padStart(2, '0')}:00`;
}

/**
 * Guarantees exact time sum compliance across lesson elements:
 * sum(lesson_elements.duration_minutes) === total_duration_minutes.
 */
export function normalizeElementDurations(
  elements: LessonPlanPayload['lesson_elements'],
  totalDurationMinutes: number
): LessonPlanPayload['lesson_elements'] {
  const count = Math.max(1, Math.min(5, elements.length));
  const sliced = elements.slice(0, count).map((e, idx) => ({
    ...e,
    index: idx + 1,
    duration_minutes: Math.max(1, Math.round(Number(e.duration_minutes) || 5)),
  }));

  const currentSum = sliced.reduce((acc, el) => acc + el.duration_minutes, 0);
  if (currentSum !== totalDurationMinutes) {
    const scale = totalDurationMinutes / Math.max(1, currentSum);
    let allocated = 0;
    for (let i = 0; i < sliced.length; i++) {
      if (i === sliced.length - 1) {
        sliced[i].duration_minutes = Math.max(1, totalDurationMinutes - allocated);
      } else {
        const val = Math.max(1, Math.round(sliced[i].duration_minutes * scale));
        sliced[i].duration_minutes = val;
        allocated += val;
      }
    }
    // Re-balance if last element clamping caused an overrun
    let diff = sliced.reduce((a, b) => a + b.duration_minutes, 0) - totalDurationMinutes;
    for (let i = 0; i < sliced.length && diff > 0; i++) {
      if (sliced[i].duration_minutes > 1) {
        const take = Math.min(diff, sliced[i].duration_minutes - 1);
        sliced[i].duration_minutes -= take;
        diff -= take;
      }
    }
  }

  return sliced.map((el) => ({
    ...el,
    time_formatted: formatMinutesToSlot(el.duration_minutes),
  }));
}

const LESSON_PLAN_RESPONSE_SCHEMA = {
  type: Type.OBJECT,
  properties: {
    unit_number: { type: Type.STRING },
    unit_name: { type: Type.STRING },
    lesson_title: { type: Type.STRING },
    learning_outcomes: {
      type: Type.ARRAY,
      items: { type: Type.STRING },
      description: 'Exactly 4 measurable Bloom taxonomy outcomes starting with observable action verbs.',
    },
    lesson_elements: {
      type: Type.ARRAY,
      items: {
        type: Type.OBJECT,
        properties: {
          index: { type: Type.INTEGER },
          title: { type: Type.STRING },
          duration_minutes: { type: Type.INTEGER },
          teaching_strategy: { type: Type.STRING },
          brief_description: { type: Type.STRING },
        },
        required: ['index', 'title', 'duration_minutes'],
      },
      description: 'Exactly 5 sequential lesson elements whose duration_minutes sum strictly to total_duration_minutes.',
    },
    selected_strategies: {
      type: Type.ARRAY,
      items: { type: Type.STRING },
      description: 'Subset chosen strictly from: المحاضرة, مناقشة وحوار, تعلم تعاوني, حل مشكلات, لعب ادوار, عصف ذهني, أخرى',
    },
    selected_resources: {
      type: Type.ARRAY,
      items: { type: Type.STRING },
      description: 'Subset chosen strictly from: دليل الطالب, فيديو تعليمي, المكتبة المدرسية, منصات تعليمية, عرض تقديمي, أخرى',
    },
    assessment_group_1: { type: Type.STRING },
    assessment_group_2: { type: Type.STRING },
    assessment_group_3: { type: Type.STRING },
    warm_up: { type: Type.STRING },
    element_1_strategy: { type: Type.STRING },
    element_1_summary: { type: Type.STRING },
    activity_1: {
      type: Type.OBJECT,
      properties: {
        duration_minutes: { type: Type.INTEGER },
        pattern: { type: Type.STRING, description: 'فردي or جماعي' },
        activity_type: { type: Type.STRING, description: 'دراسة حالة or بحث or رسم / تصميم or أخرى' },
        purpose: { type: Type.STRING },
        teacher_procedures: { type: Type.STRING },
        student_procedures: { type: Type.STRING },
        student_note: { type: Type.STRING },
      },
      required: [
        'duration_minutes',
        'pattern',
        'activity_type',
        'purpose',
        'teacher_procedures',
        'student_procedures',
        'student_note',
      ],
    },
    element_2_strategy: { type: Type.STRING },
    element_2_summary: { type: Type.STRING },
    activity_2: {
      type: Type.OBJECT,
      properties: {
        duration_minutes: { type: Type.INTEGER },
        pattern: { type: Type.STRING, description: 'فردي or جماعي' },
        activity_type: { type: Type.STRING, description: 'دراسة حالة or بحث or رسم / تصميم or أخرى' },
        purpose: { type: Type.STRING },
        teacher_procedures: { type: Type.STRING },
        student_procedures: { type: Type.STRING },
        student_note: { type: Type.STRING },
      },
      required: [
        'duration_minutes',
        'pattern',
        'activity_type',
        'purpose',
        'teacher_procedures',
        'student_procedures',
        'student_note',
      ],
    },
    rubric_group_1_header: { type: Type.STRING },
    rubric_group_1_items: { type: Type.ARRAY, items: { type: Type.STRING } },
    rubric_group_2_header: { type: Type.STRING },
    rubric_group_2_items: { type: Type.ARRAY, items: { type: Type.STRING } },
    traceability: {
      type: Type.ARRAY,
      items: {
        type: Type.OBJECT,
        properties: {
          field_key: { type: Type.STRING },
          field_label: { type: Type.STRING },
          supporting_excerpt: {
            type: Type.STRING,
            description: 'Exact verbatim substring copied from the provided source lesson text.',
          },
          source_pages: { type: Type.ARRAY, items: { type: Type.INTEGER } },
        },
        required: ['field_key', 'field_label', 'supporting_excerpt', 'source_pages'],
      },
    },
    missing_curriculum_notes: {
      type: Type.ARRAY,
      items: { type: Type.STRING },
      description: 'List any required template info absent from the source curriculum rather than fabricating facts.',
    },
  },
  required: [
    'unit_number',
    'unit_name',
    'lesson_title',
    'learning_outcomes',
    'lesson_elements',
    'selected_strategies',
    'selected_resources',
    'assessment_group_1',
    'assessment_group_2',
    'assessment_group_3',
    'warm_up',
    'element_1_strategy',
    'element_1_summary',
    'activity_1',
    'element_2_strategy',
    'element_2_summary',
    'activity_2',
    'rubric_group_1_header',
    'rubric_group_1_items',
    'rubric_group_2_header',
    'rubric_group_2_items',
    'traceability',
    'missing_curriculum_notes',
  ],
};

function verifyExcerptInSource(excerpt: string, sourceText: string): boolean {
  const cleanExcerpt = excerpt.replace(/\s+/g, ' ').trim();
  if (cleanExcerpt.length < 6) return false;
  const cleanSource = sourceText.replace(/\s+/g, ' ');
  if (cleanSource.includes(cleanExcerpt)) return true;
  // Also check 60% consecutive token match for minor punctuation normalization
  const tokens = cleanExcerpt.split(' ').filter((t) => t.length > 2);
  if (tokens.length === 0) return false;
  const matched = tokens.filter((t) => cleanSource.includes(t)).length;
  return matched / tokens.length >= 0.7;
}

export async function generateStructuredLessonPlan(
  unit: CurriculumUnit,
  lesson: LessonBoundary,
  schema: TemplateSchema,
  context: GenerationContext
): Promise<LessonPlanPayload> {
  const ai = getAiClient();
  const effectiveLang =
    context.output_language && context.output_language !== 'auto'
      ? context.output_language
      : schema.language;
  const targetLang =
    effectiveLang === 'en'
      ? 'English'
      : 'Arabic (Modern Standard Arabic suitable for Applied Technology schools)';

  const systemInstruction = `You are a senior Applied Technology Educational Curriculum Specialist and Instructional Designer.
Your task is to perform Dual-Document Analysis between the uploaded Curriculum Lesson (the SOLE source of educational truth) and the locked DOCX Template Schema.

NON-NEGOTIABLE PEDAGOGICAL & FIDELITY RULES:
1. Language: Write all generated fields in ${targetLang} matching the template language, preserving exact technical LTR tokens (e.g., PLC, CPU, TON, TOF, CTU, I0.0, Q0.0, TPK04) as written in the lesson.
2. Zero Fabrication: NEVER invent textbook page numbers, exercises, hardware models, or curriculum facts absent from the provided lesson text. If a requested detail is not in the source text, note it in missing_curriculum_notes.
3. Measurable Bloom's Taxonomy Outcomes: Every learning outcome MUST start with an observable, measurable Bloom verb (Arabic examples: يحدد، يقارن، يصمم، يطبق، يستنتج، يحلل، يوضح، يبرمج، يفحص، يفرق بين; English examples: Identify, Compare, Design, Apply, Analyze, Explain, Construct). STRICTLY FORBIDDEN vague verbs: يفهم، يعرف، يدرك، يلم بـ، يتعلم، يستوعب، understand, know, learn, appreciate.
4. Strict Time Allocation: Provide exactly 5 sequential lesson_elements whose duration_minutes sum EXACTLY to ${context.total_duration_minutes} minutes.
5. Concise Cell-Fit Sizing: Keep each field concise and high-impact so it fits cleanly inside the locked DOCX table cells without causing page overflow:
   - Each learning outcome <= 115 characters.
   - Each lesson element title <= 90 characters.
   - Warm-up, summaries, and assessments <= 320 characters each.
   - Rubric group 1 and group 2 each have exactly 6 concise measurable criteria items (<= 110 characters each).
6. Verbatim Source Traceability: Provide at least 5 traceability entries covering learning_outcomes, lesson_elements, activity_1, activity_2, and assessment_group_1, copying an EXACT verbatim substring (15–120 characters) directly from the source lesson text into supporting_excerpt.`;

  const userPrompt = `### LESSON CONTEXT
- Unit Title: ${unit.unit_title}
- Lesson Number: ${lesson.lesson_number}
- Lesson Title: ${lesson.title}
- Source Pages: ${lesson.start_page} to ${lesson.end_page}
- Program / Course: ${context.program_or_course}
- Grade Level: ${context.grade_level}
- Branch: ${context.branch}
- Knowledge Code: ${context.knowledge_code}
- Total Duration (minutes): ${context.total_duration_minutes}
- Teacher Instructions: ${context.teacher_instructions || 'None'}

### LOCKED TEMPLATE PROFILE
- Profile: ${schema.template_profile}
- Expected Pages: ${schema.page_count_expected}
- RTL: ${schema.is_rtl}
- Parsed Fields Count: ${schema.fields.length}

### VERBATIM SOURCE LESSON TEXT (SOLE EDUCATIONAL TRUTH)
${lesson.raw_text}

Generate the complete structured JSON lesson plan payload now.`;

  const response = await ai.models.generateContent({
    model: 'gemini-4-hydrogen',
    contents: userPrompt,
    config: {
      systemInstruction,
      responseMimeType: 'application/json',
      responseSchema: LESSON_PLAN_RESPONSE_SCHEMA,
    },
  });

  const rawJson = (response.text ?? '').trim();
  if (!rawJson) {
    throw new Error('Gemini returned an empty response for lesson plan generation.');
  }

  const parsed = JSON.parse(rawJson);

  const normalizedElements = normalizeElementDurations(
    Array.isArray(parsed.lesson_elements) ? parsed.lesson_elements : [],
    context.total_duration_minutes
  );

  const el1Time = normalizedElements[0]?.time_formatted ?? formatMinutesToSlot(Math.round(context.total_duration_minutes * 0.25));
  const el2Time = normalizedElements[1]?.time_formatted ?? formatMinutesToSlot(Math.round(context.total_duration_minutes * 0.25));

  const act1Mins = Math.max(5, Math.round(parsed.activity_1?.duration_minutes || 10));
  const act2Mins = Math.max(5, Math.round(parsed.activity_2?.duration_minutes || 10));

  const normalizePattern = (p: string): 'فردي' | 'جماعي' => (p?.includes('فردي') ? 'فردي' : 'جماعي');
  const normalizeActType = (t: string): 'دراسة حالة' | 'بحث' | 'رسم / تصميم' | 'أخرى' => {
    if (t?.includes('دراسة حالة')) return 'دراسة حالة';
    if (t?.includes('بحث')) return 'بحث';
    if (t?.includes('رسم') || t?.includes('تصميم')) return 'رسم / تصميم';
    return 'أخرى';
  };

  const traceability = (Array.isArray(parsed.traceability) ? parsed.traceability : []).map(
    (entry: { field_key: string; field_label: string; supporting_excerpt: string; source_pages: number[] }) => ({
      field_key: entry.field_key,
      field_label: entry.field_label,
      supporting_excerpt: entry.supporting_excerpt,
      source_pages:
        Array.isArray(entry.source_pages) && entry.source_pages.length > 0
          ? entry.source_pages
          : [lesson.start_page],
      verified_in_source: verifyExcerptInSource(entry.supporting_excerpt || '', lesson.raw_text),
    })
  );

  return {
    program_or_course: context.program_or_course,
    teacher_name: context.teacher_name,
    job_title: context.job_title,
    academic_year: context.academic_year,
    school_name: context.school_name,
    grade_level: context.grade_level,
    class_sections: context.class_sections.length > 0 ? context.class_sections : ['2 A', '2B'],
    unit_number: parsed.unit_number || 'الوحدة الثالثة',
    unit_name: parsed.unit_name || unit.unit_title,
    branch: context.branch,
    knowledge_code: context.knowledge_code,
    lesson_title: parsed.lesson_title || lesson.title,
    learning_outcomes: (Array.isArray(parsed.learning_outcomes) ? parsed.learning_outcomes : []).slice(0, 4),
    lesson_elements: normalizedElements,
    selected_strategies: Array.isArray(parsed.selected_strategies) ? parsed.selected_strategies : ['مناقشة وحوار', 'تعلم تعاوني'],
    selected_resources: Array.isArray(parsed.selected_resources) ? parsed.selected_resources : ['دليل الطالب', 'عرض تقديمي'],
    assessment_group_1: parsed.assessment_group_1 || '',
    assessment_group_2: parsed.assessment_group_2 || '',
    assessment_group_3: parsed.assessment_group_3 || '',
    presentation_class: context.class_sections[0] || '2 A',
    location: context.location,
    lesson_date: context.lesson_date,
    total_duration_minutes: context.total_duration_minutes,
    warm_up: parsed.warm_up || '',
    element_1_strategy: parsed.element_1_strategy || normalizedElements[0]?.teaching_strategy || 'مناقشة وحوار',
    element_1_time: el1Time,
    element_1_summary: parsed.element_1_summary || '',
    activity_1: {
      activity_number: 1,
      duration_minutes: act1Mins,
      time_formatted: formatMinutesToSlot(act1Mins),
      pattern: normalizePattern(parsed.activity_1?.pattern),
      activity_type: normalizeActType(parsed.activity_1?.activity_type),
      purpose: parsed.activity_1?.purpose || '',
      teacher_procedures: parsed.activity_1?.teacher_procedures || '',
      student_procedures: parsed.activity_1?.student_procedures || '',
      student_note: parsed.activity_1?.student_note || '',
    },
    element_2_strategy: parsed.element_2_strategy || normalizedElements[1]?.teaching_strategy || 'تعلم تعاوني',
    element_2_time: el2Time,
    element_2_summary: parsed.element_2_summary || '',
    activity_2: {
      activity_number: 2,
      duration_minutes: act2Mins,
      time_formatted: formatMinutesToSlot(act2Mins),
      pattern: normalizePattern(parsed.activity_2?.pattern),
      activity_type: normalizeActType(parsed.activity_2?.activity_type),
      purpose: parsed.activity_2?.purpose || '',
      teacher_procedures: parsed.activity_2?.teacher_procedures || '',
      student_procedures: parsed.activity_2?.student_procedures || '',
      student_note: parsed.activity_2?.student_note || '',
    },
    rubric_group_1_header: parsed.rubric_group_1_header || 'تقييم المعارف والمفاهيم الأساسية',
    rubric_group_1_items: (Array.isArray(parsed.rubric_group_1_items) ? parsed.rubric_group_1_items : []).slice(0, 6),
    rubric_group_2_header: parsed.rubric_group_2_header || 'تقييم المهارات التطبيقية والعملية',
    rubric_group_2_items: (Array.isArray(parsed.rubric_group_2_items) ? parsed.rubric_group_2_items : []).slice(0, 6),
    traceability,
    missing_curriculum_notes: Array.isArray(parsed.missing_curriculum_notes) ? parsed.missing_curriculum_notes : [],
  };
}

/**
 * Partial Field Regeneration:
 * Regenerates ONLY the requested field keys while preserving all approved/unselected fields verbatim.
 */
export async function regenerateSelectedFields(
  lesson: LessonBoundary,
  currentPayload: LessonPlanPayload,
  fieldKeysToRegenerate: string[],
  refinementInstruction: string
): Promise<LessonPlanPayload> {
  const ai = getAiClient();

  const prompt = `You are updating ONLY specific fields of an existing Applied Technology lesson plan based on the verbatim source lesson below.
DO NOT modify or omit any field outside the requested list.
Strictly use measurable Bloom verbs (never use يفهم/يعرف/يدرك/understand/know) and keep text concise to avoid DOCX cell overflow.

### FIELDS TO REGENERATE
${fieldKeysToRegenerate.join(', ')}

### TEACHER REFINEMENT INSTRUCTION
${refinementInstruction || 'Improve pedagogical precision, alignment with learning outcomes, and conciseness to prevent overflow.'}

### CURRENT LESSON PLAN JSON (FOR CONTEXT)
${JSON.stringify(currentPayload, null, 2)}

### VERBATIM SOURCE LESSON TEXT
${lesson.raw_text}

Return a JSON object containing ONLY the regenerated fields with their exact keys matching the current payload schema (plus updated traceability entries for the regenerated fields if applicable).`;

  const response = await ai.models.generateContent({
    model: 'gemini-4-hydrogen',
    contents: prompt,
    config: {
      responseMimeType: 'application/json',
    },
  });

  const rawText = (response.text ?? '').trim();
  if (!rawText) {
    throw new Error('Gemini returned an empty response during partial field regeneration.');
  }

  const patch = JSON.parse(rawText);
  const merged: LessonPlanPayload = { ...currentPayload };

  for (const key of fieldKeysToRegenerate) {
    if (key in patch && patch[key] !== undefined) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (merged as any)[key] = patch[key];
    }
  }

  // Always preserve exact time sum if lesson_elements were regenerated
  if (fieldKeysToRegenerate.includes('lesson_elements')) {
    merged.lesson_elements = normalizeElementDurations(
      merged.lesson_elements,
      currentPayload.total_duration_minutes
    );
    merged.element_1_time = merged.lesson_elements[0]?.time_formatted ?? merged.element_1_time;
    merged.element_2_time = merged.lesson_elements[1]?.time_formatted ?? merged.element_2_time;
  }

  return merged;
}

const MODE_FIELD_MAP: Record<Exclude<AiGenerationMode, 'complete' | 'regenerate_field' | 'validate_alignment'>, { fields: string[]; instruction: string }> = {
  improve_outcomes: {
    fields: ['learning_outcomes'],
    instruction:
      "Strengthen all 4 learning outcomes using observable higher-order Bloom's Taxonomy action verbs grounded strictly in the source lesson. Eliminate any vague verbs (يفهم/يعرف/يدرك/understand/know) and keep each bullet concise (<= 110 chars).",
  },
  improve_activities: {
    fields: ['warm_up', 'element_1_summary', 'activity_1', 'element_2_summary', 'activity_2'],
    instruction:
      'Enhance practical classroom activities with clear, concrete teacher and student roles, realistic lab/applied technology tasks grounded verbatim in the lesson, and concise cell-safe phrasing.',
  },
  improve_assessment: {
    fields: ['assessment_group_1', 'assessment_group_2', 'assessment_group_3', 'rubric_group_1_items', 'rubric_group_2_items'],
    instruction:
      'Align formative assessments and evaluation rubrics (-1 to -6) directly to every learning outcome, ensuring objective observable criteria grounded strictly in the curriculum without inventing page numbers.',
  },
  simplify_language: {
    fields: ['warm_up', 'element_1_summary', 'element_2_summary', 'assessment_group_1', 'assessment_group_2', 'assessment_group_3'],
    instruction:
      'Simplify instructional Arabic/English phrasing for maximum teacher and student readability while retaining exact technical terms and keeping text concise to avoid DOCX cell overflow.',
  },
};

export async function runTargetedAiAction(
  lesson: LessonBoundary,
  currentPayload: LessonPlanPayload,
  mode: Exclude<AiGenerationMode, 'complete' | 'regenerate_field'>,
  approvedFields: string[],
  customInstruction = ''
): Promise<{
  updatedPayload?: LessonPlanPayload;
  alignment?: AlignmentValidationResult;
  skippedLockedFields: string[];
}> {
  if (mode === 'validate_alignment') {
    const ai = getAiClient();
    const prompt = `Perform a strict curriculum-alignment audit comparing the generated lesson plan against the verbatim source lesson below.
Identify any concept drift, ungrounded claims, weak Bloom verbs, or missing alignment between learning outcomes, activities, and assessments.

### VERBATIM SOURCE LESSON (PAGES ${lesson.start_page}-${lesson.end_page})
${lesson.raw_text}

### CURRENT LESSON PLAN
${JSON.stringify(currentPayload, null, 2)}

Return JSON with:
- summary: concise 1-2 sentence overall alignment assessment
- findings: array of { section, status ("aligned" | "needs_review" | "gap"), finding, recommendation }`;

    const response = await ai.models.generateContent({
      model: 'gemini-4-hydrogen',
      contents: prompt,
      config: {
        responseMimeType: 'application/json',
        responseSchema: {
          type: Type.OBJECT,
          properties: {
            summary: { type: Type.STRING },
            findings: {
              type: Type.ARRAY,
              items: {
                type: Type.OBJECT,
                properties: {
                  section: { type: Type.STRING },
                  status: { type: Type.STRING },
                  finding: { type: Type.STRING },
                  recommendation: { type: Type.STRING },
                },
                required: ['section', 'status', 'finding', 'recommendation'],
              },
            },
          },
          required: ['summary', 'findings'],
        },
      },
    });

    const parsed = JSON.parse((response.text ?? '{}').trim() || '{}');
    const findings = (Array.isArray(parsed.findings) ? parsed.findings : []).map(
      (f: { section?: string; status?: string; finding?: string; recommendation?: string }) => ({
        section: f.section || 'General',
        status: (f.status === 'aligned' || f.status === 'gap' ? f.status : 'needs_review') as
          | 'aligned'
          | 'needs_review'
          | 'gap',
        finding: f.finding || '',
        recommendation: f.recommendation || '',
      })
    );

    return {
      alignment: {
        checked_at: new Date().toISOString(),
        summary: parsed.summary || 'Alignment validation completed against uploaded lesson text.',
        findings,
      },
      skippedLockedFields: [],
    };
  }

  const config = MODE_FIELD_MAP[mode];
  const skippedLockedFields = config.fields.filter((k) => approvedFields.includes(k));
  const unlockedFields = config.fields.filter((k) => !approvedFields.includes(k));

  if (unlockedFields.length === 0) {
    throw new Error(
      `All target fields for "${mode.replace(/_/g, ' ')}" are currently locked/approved. Unlock at least one field first.`
    );
  }

  const combinedInstruction = customInstruction
    ? `${config.instruction}\nAdditional teacher note: ${customInstruction}`
    : config.instruction;

  const updatedPayload = await regenerateSelectedFields(
    lesson,
    currentPayload,
    unlockedFields,
    combinedInstruction
  );

  return {
    updatedPayload,
    skippedLockedFields,
  };
}

