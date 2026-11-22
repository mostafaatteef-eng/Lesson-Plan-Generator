from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class PageText(BaseModel):
    page_number: int
    text: str


class LessonBoundary(BaseModel):
    lesson_id: str
    lesson_number: int
    title: str
    start_page: int
    end_page: int
    raw_text: str
    word_count: int
    confidence: float = Field(ge=0.0, le=1.0)
    is_ambiguous: bool = False
    ambiguity_reason: Optional[str] = None
    approved: bool = True
    key_concepts: List[str] = Field(default_factory=list)


class CurriculumUnit(BaseModel):
    unit_id: str
    filename: str
    file_format: Literal["pdf", "docx", "pptx", "txt"]
    language: Literal["ar", "en", "mixed"]
    unit_title: str
    total_pages: int
    ocr_used: bool = False
    uploaded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pages: List[PageText] = Field(default_factory=list)
    lessons: List[LessonBoundary] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class TemplateField(BaseModel):
    field_id: str
    label: str
    normalized_key: str
    page_hint: int
    field_type: Literal[
        "text",
        "multiline",
        "time_slot",
        "checkbox_group",
        "bullet_list",
        "rubric_list",
        "activity_block",
    ]
    table_index: int
    row_index: int
    col_index: int
    is_rtl: bool = True
    max_chars: int = 200
    current_value: str = ""
    checkbox_options: List[str] = Field(default_factory=list)
    has_time_placeholder: bool = False
    is_merged: bool = False
    locked_label: Optional[str] = None


class TemplateTableSummary(BaseModel):
    table_index: int
    page_hint: int
    rows: int
    cols: int
    is_rtl: bool
    merged_cells: int
    column_widths_dxa: List[int] = Field(default_factory=list)


class TemplateSchema(BaseModel):
    template_id: str
    filename: str
    uploaded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_locked: bool = False
    language: Literal["ar", "en", "mixed"] = "ar"
    is_rtl: bool = True
    page_count_expected: int = 6
    page_width_pt: float = 595.28
    page_height_pt: float = 841.89
    margins_pt: Dict[str, float] = Field(
        default_factory=lambda: {"top": 56.7, "bottom": 56.7, "left": 56.7, "right": 56.7}
    )
    template_profile: str = "ATS-MU 6-Page Arabic RTL Lesson Plan"
    locked_identity_markers: List[str] = Field(default_factory=list)
    tables: List[TemplateTableSummary] = Field(default_factory=list)
    fields: List[TemplateField] = Field(default_factory=list)
    has_reference_pdf: bool = False
    reference_pdf_filename: Optional[str] = None
    reference_pdf_pages: Optional[int] = None


class TraceabilityEntry(BaseModel):
    field_key: str
    field_label: str
    supporting_excerpt: str
    source_pages: List[int]
    verified_in_source: bool = False


class LessonElementPlan(BaseModel):
    index: int
    title: str
    duration_minutes: int
    time_formatted: str
    teaching_strategy: Optional[str] = None
    brief_description: Optional[str] = None


class ActivityPlan(BaseModel):
    activity_number: int
    duration_minutes: int
    time_formatted: str
    pattern: Literal["فردي", "جماعي"] = "جماعي"
    activity_type: Literal["دراسة حالة", "بحث", "رسم / تصميم", "أخرى"] = "دراسة حالة"
    purpose: str
    teacher_procedures: str
    student_procedures: str
    student_note: str


class LessonPlanPayload(BaseModel):
    program_or_course: str
    teacher_name: str
    job_title: str
    academic_year: str
    school_name: str
    grade_level: str
    class_sections: List[str] = Field(default_factory=lambda: ["2 A", "2B"])
    unit_number: str
    unit_name: str
    branch: str
    knowledge_code: str = "TPK00"
    lesson_title: str
    learning_outcomes: List[str]
    lesson_elements: List[LessonElementPlan]
    selected_strategies: List[str]
    selected_resources: List[str]
    assessment_group_1: str
    assessment_group_2: str
    assessment_group_3: str
    presentation_class: str = "2 A"
    location: str = ""
    lesson_date: str = ""
    total_duration_minutes: int = 45
    warm_up: str
    element_1_strategy: str
    element_1_time: str
    element_1_summary: str
    activity_1: ActivityPlan
    element_2_strategy: str
    element_2_time: str
    element_2_summary: str
    activity_2: ActivityPlan
    rubric_group_1_header: str
    rubric_group_1_items: List[str]
    rubric_group_2_header: str
    rubric_group_2_items: List[str]
    traceability: List[TraceabilityEntry] = Field(default_factory=list)
    missing_curriculum_notes: List[str] = Field(default_factory=list)


class VisualDiffPage(BaseModel):
    page_number: int
    reference_width_pt: float
    reference_height_pt: float
    generated_width_pt: float
    generated_height_pt: float
    dimension_match: bool
    pixel_diff_pct: float
    structural_similarity_pct: float
    overflow_detected: bool = False
    status: Literal["pass", "warning", "fail"]
    notes: List[str] = Field(default_factory=list)


class QACheck(BaseModel):
    name: str
    passed: bool
    severity: Literal["info", "warning", "error"]
    detail: str


class QAPillarResult(BaseModel):
    pillar: Literal[
        "curriculum_fidelity",
        "pedagogical_quality",
        "template_fidelity",
        "document_integrity",
    ]
    title: str
    status: Literal["pass", "warning", "fail"]
    score: int
    checks: List[QACheck]


class HumanApprovalGate(BaseModel):
    gate_id: str
    category: Literal[
        "ambiguous_boundary",
        "missing_curriculum_info",
        "cell_overflow",
        "layout_deviation",
        "pedagogical_flag",
    ]
    severity: Literal["warning", "blocking"]
    message: str
    field_key: Optional[str] = None
    resolved: bool = False


class QAReport(BaseModel):
    overall_status: Literal["pass", "warning", "fail"]
    overall_score: int
    time_sum_minutes: int
    target_duration_minutes: int
    time_sum_valid: bool
    vague_verbs_found: List[str] = Field(default_factory=list)
    overflow_fields: List[str] = Field(default_factory=list)
    page_count_expected: int
    page_count_rendered: int
    libreoffice_used: bool = False
    pillars: List[QAPillarResult]
    visual_diff: List[VisualDiffPage]
    approval_gates: List[HumanApprovalGate] = Field(default_factory=list)


class GenerationContext(BaseModel):
    unit_id: str
    lesson_id: str
    template_id: str
    school_name: str
    teacher_name: str
    job_title: str
    program_or_course: str
    grade_level: str
    academic_year: str
    branch: str
    knowledge_code: str = "TPK00"
    class_sections: List[str] = Field(default_factory=lambda: ["2 A", "2B"])
    location: str = ""
    lesson_date: str = ""
    total_duration_minutes: int = 45
    teacher_instructions: str = ""
