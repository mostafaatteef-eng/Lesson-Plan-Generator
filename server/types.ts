export interface LessonBoundary {
  lesson_id: string;
  lesson_number: number;
  title: string;
  start_page: number;
  end_page: number;
  raw_text: string;
  word_count: number;
  confidence: number;
  is_ambiguous: boolean;
  ambiguity_reason?: string;
  approved: boolean;
  user_modified?: boolean;
  key_concepts: string[];
}

export interface CurriculumUnit {
  unit_id: string;
  filename: string;
  file_format: 'pdf' | 'docx' | 'pptx' | 'txt';
  file_size_bytes: number;
  extraction_quality: 'high' | 'medium' | 'needs_review';
  language: 'ar' | 'en' | 'mixed';
  unit_title: string;
  total_pages: number;
  ocr_used: boolean;
  uploaded_at: string;
  pages: Array<{ page_number: number; text: string }>;
  lessons: LessonBoundary[];
  warnings: string[];
}

export interface TemplateField {
  field_id: string;
  label: string;
  normalized_key: string;
  page_hint: number;
  field_type:
    | 'text'
    | 'multiline'
    | 'time_slot'
    | 'checkbox_group'
    | 'bullet_list'
    | 'rubric_list'
    | 'activity_block';
  table_index: number;
  row_index: number;
  col_index: number;
  is_rtl: boolean;
  max_chars: number;
  current_value: string;
  checkbox_options?: string[];
  has_time_placeholder?: boolean;
  is_merged?: boolean;
  locked_label?: string;
}

export interface TemplateTableSummary {
  table_index: number;
  page_hint: number;
  rows: number;
  cols: number;
  is_rtl: boolean;
  merged_cells: number;
  column_widths_dxa: number[];
}

export interface TemplateSchema {
  template_id: string;
  filename: string;
  uploaded_at: string;
  is_locked: boolean;
  language: 'ar' | 'en' | 'mixed';
  is_rtl: boolean;
  page_count_expected: number;
  page_width_pt: number;
  page_height_pt: number;
  margins_pt: {
    top: number;
    bottom: number;
    left: number;
    right: number;
  };
  template_profile: string;
  locked_identity_markers: string[];
  tables: TemplateTableSummary[];
  fields: TemplateField[];
  has_reference_pdf: boolean;
  reference_pdf_filename?: string;
  reference_pdf_pages?: number;
  reference_pdf_dimensions?: Array<{ page: number; width_pt: number; height_pt: number }>;
}

export interface TraceabilityEntry {
  field_key: string;
  field_label: string;
  supporting_excerpt: string;
  source_pages: number[];
  verified_in_source: boolean;
}

export interface LessonElementPlan {
  index: number;
  title: string;
  duration_minutes: number;
  time_formatted: string;
  teaching_strategy?: string;
  brief_description?: string;
}

export interface ActivityPlan {
  activity_number: number;
  duration_minutes: number;
  time_formatted: string;
  pattern: 'فردي' | 'جماعي';
  activity_type: 'دراسة حالة' | 'بحث' | 'رسم / تصميم' | 'أخرى';
  purpose: string;
  teacher_procedures: string;
  student_procedures: string;
  student_note: string;
}

export interface LessonPlanPayload {
  // Page 1 Cover
  program_or_course: string;
  teacher_name: string;
  job_title: string;
  academic_year: string;
  // Page 2 Metadata
  school_name: string;
  grade_level: string;
  class_sections: string[];
  // Page 3 Unit & Outcomes
  unit_number: string;
  unit_name: string;
  branch: string;
  knowledge_code: string;
  lesson_title: string;
  learning_outcomes: string[];
  lesson_elements: LessonElementPlan[];
  selected_strategies: string[];
  selected_resources: string[];
  assessment_group_1: string;
  assessment_group_2: string;
  // Page 4 Assessment Continuation
  assessment_group_3: string;
  // Page 5 Lesson Presentation
  presentation_class: string;
  location: string;
  lesson_date: string;
  total_duration_minutes: number;
  warm_up: string;
  element_1_strategy: string;
  element_1_time: string;
  element_1_summary: string;
  activity_1: ActivityPlan;
  element_2_strategy: string;
  element_2_time: string;
  element_2_summary: string;
  activity_2: ActivityPlan;
  // Page 6 Evaluation Rubrics
  rubric_group_1_header: string;
  rubric_group_1_items: string[];
  rubric_group_2_header: string;
  rubric_group_2_items: string[];
  // Grounding & Traceability
  traceability: TraceabilityEntry[];
  missing_curriculum_notes: string[];
}

export interface VisualDiffPage {
  page_number: number;
  reference_width_pt: number;
  reference_height_pt: number;
  generated_width_pt: number;
  generated_height_pt: number;
  dimension_match: boolean;
  structural_similarity_pct: number;
  layout_delta_pct: number;
  overflow_detected: boolean;
  status: 'pass' | 'warning' | 'fail';
  notes: string[];
}

export interface QAPillarResult {
  pillar:
    | 'curriculum_fidelity'
    | 'pedagogical_quality'
    | 'template_fidelity'
    | 'document_integrity';
  title: string;
  status: 'pass' | 'warning' | 'fail';
  score: number;
  checks: Array<{
    name: string;
    passed: boolean;
    severity: 'info' | 'warning' | 'error';
    detail: string;
  }>;
}

export interface HumanApprovalGate {
  gate_id: string;
  category:
    | 'ambiguous_boundary'
    | 'missing_curriculum_info'
    | 'cell_overflow'
    | 'layout_deviation'
    | 'pedagogical_flag';
  severity: 'warning' | 'blocking';
  message: string;
  field_key?: string;
  resolved: boolean;
}

export interface QAReport {
  overall_status: 'pass' | 'warning' | 'fail';
  overall_score: number;
  time_sum_minutes: number;
  target_duration_minutes: number;
  time_sum_valid: boolean;
  vague_verbs_found: string[];
  overflow_fields: string[];
  page_count_expected: number;
  page_count_rendered: number;
  libreoffice_used: boolean;
  pillars: QAPillarResult[];
  visual_diff: VisualDiffPage[];
  approval_gates: HumanApprovalGate[];
}

export type AiGenerationMode =
  | 'complete'
  | 'regenerate_field'
  | 'improve_outcomes'
  | 'improve_activities'
  | 'improve_assessment'
  | 'simplify_language'
  | 'validate_alignment';

export interface AlignmentFinding {
  section: string;
  status: 'aligned' | 'needs_review' | 'gap';
  finding: string;
  recommendation: string;
}

export interface AlignmentValidationResult {
  checked_at: string;
  summary: string;
  findings: AlignmentFinding[];
}

export interface InstitutionSettings {
  institution_en: string;
  institution_ar: string;
  school_name_en: string;
  school_name_ar: string;
  specialization_en: string;
  specialization_ar: string;
  default_teacher_name: string;
  default_job_title: string;
  default_grade_level: string;
  default_academic_year: string;
  default_branch: string;
  default_knowledge_code: string;
  default_location: string;
  default_duration_minutes: number;
  logo_data_url: string | null;
  logo_filename: string | null;
  extracted_brand_color: string | null;
}

export interface GenerationContext {
  unit_id: string;
  lesson_id: string;
  template_id: string;
  school_name: string;
  teacher_name: string;
  job_title: string;
  program_or_course: string;
  grade_level: string;
  academic_year: string;
  branch: string;
  knowledge_code: string;
  class_sections: string[];
  location: string;
  lesson_date: string;
  total_duration_minutes: number;
  output_language?: 'auto' | 'ar' | 'en';
  teacher_instructions: string;
}

export interface GeneratedPlanRecord {
  plan_id: string;
  created_at: string;
  updated_at?: string;
  context: GenerationContext;
  lesson_title: string;
  payload: LessonPlanPayload;
  qa_report: QAReport;
  approved_fields: string[];
  last_alignment_check?: AlignmentValidationResult | null;
  docx_filename: string;
  pdf_filename: string;
  pdf_available?: boolean;
  pdf_error?: string | null;
}
