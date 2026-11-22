import React, { useEffect, useState } from 'react';
import { ArrowRight, Lock } from 'lucide-react';
import { UploadCard, type UploadedFileSummary } from './components/UploadCard';
import { LessonSelector, type AdvancedOptions } from './components/LessonSelector';
import { GenerationProgress } from './components/GenerationProgress';
import { ResultsPanel } from './components/ResultsPanel';
import type {
  CurriculumUnit,
  GeneratedPlanRecord,
  GenerationContext,
  InstitutionSettings,
  TemplateSchema,
} from './types';

// Backend origin: build-time VITE_API_BASE_URL wins; otherwise default to the
// deployed PythonAnywhere backend. No secrets here - the passcode is entered
// by the user at runtime and sent only as a request header over HTTPS.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'https://mostafaatteef.pythonanywhere.com').replace(/\/$/, '');
const apiUrl = (path: string) => `${API_BASE_URL}${path}`;

export default function App() {
  // Institutional defaults & optional official uploaded EBDA logo
  const [settings, setSettings] = useState<InstitutionSettings | null>(null);

  // Section B — Upload state (3 independent cards)
  const [unit, setUnit] = useState<CurriculumUnit | null>(null);
  const [curriculumError, setCurriculumError] = useState<string | null>(null);
  const [uploadingCurriculum, setUploadingCurriculum] = useState(false);

  const [template, setTemplate] = useState<TemplateSchema | null>(null);
  const [templateSizeBytes, setTemplateSizeBytes] = useState<number>(0);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [uploadingTemplate, setUploadingTemplate] = useState(false);

  const [stagedRefPdf, setStagedRefPdf] = useState<File | null>(null);
  const [refPdfSizeBytes, setRefPdfSizeBytes] = useState<number>(0);
  const [refPdfError, setRefPdfError] = useState<string | null>(null);
  const [uploadingRefPdf, setUploadingRefPdf] = useState(false);

  // Section C — Lesson selection, inline boundary editing & advanced options
  const [selectedLessonIds, setSelectedLessonIds] = useState<string[]>([]);
  const [savingBoundary, setSavingBoundary] = useState(false);
  const [advanced, setAdvanced] = useState<AdvancedOptions>({
    gradeLevel: 'الصف الثاني الثانوي التكنولوجي',
    subject: 'الذكاء الاصطناعي وتحليل البيانات',
    durationMinutes: 45,
    outputLanguage: 'auto',
  });

  // Generation progress state
  const [isGenerating, setIsGenerating] = useState(false);
  const [activeStageIndex, setActiveStageIndex] = useState(2);
  const [generationError, setGenerationError] = useState<string | null>(null);

  // Section D — Results & Download
  const [generatedPlans, setGeneratedPlans] = useState<GeneratedPlanRecord[]>([]);
  const [batchDownload, setBatchDownload] = useState<{ batchId: string; filename: string } | null>(
    null
  );

  // App passcode: kept only in memory for this session, never persisted,
  // never part of the build. Sent as X-App-Passcode on mutating requests.
  const [passcode, setPasscode] = useState('');

  const authHeaders = (extra?: Record<string, string>): Record<string, string> => {
    const headers: Record<string, string> = { ...(extra || {}) };
    if (passcode) headers['X-App-Passcode'] = passcode;
    return headers;
  };

  // Honest server error surfacing. A 401 means the passcode was rejected:
  // clear it so the next attempt forces a fresh entry.
  const explainHttpError = (status: number, data: unknown, fallback: string): string => {
    const body = data as { error?: string; detail?: string } | null;
    const serverMessage = body?.error || body?.detail || '';
    if (status === 401) {
      setPasscode('');
      return 'Passcode missing or incorrect. Re-enter it above and try again.';
    }
    return serverMessage || fallback;
  };

  // Load EBDA institutional settings on mount (includes official logo if configured)
  useEffect(() => {
    let active = true;
    fetch(apiUrl('/api/settings'))
      .then((res) => (res.ok ? res.json() : null))
      .then((data: InstitutionSettings | null) => {
        if (!active || !data) return;
        setSettings(data);
        setAdvanced((prev) => ({
          ...prev,
          gradeLevel: data.default_grade_level || prev.gradeLevel,
          subject: data.specialization_ar || prev.subject,
          durationMinutes: data.default_duration_minutes || prev.durationMinutes,
        }));
      })
      .catch(() => {
        // Defaults remain active if settings endpoint is temporarily unreachable
      });
    return () => {
      active = false;
    };
  }, []);

  // 1. Curriculum Upload / Replace / Remove
  const handleCurriculumSelect = async (file: File) => {
    setCurriculumError(null);
    setUploadingCurriculum(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch(apiUrl('/api/curriculum/upload'), {
        method: 'POST',
        headers: authHeaders(),
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(
          explainHttpError(res.status, data, 'Could not extract text from the uploaded curriculum.')
        );
      }
      const parsedUnit = data as CurriculumUnit;
      setUnit(parsedUnit);
      setSelectedLessonIds(parsedUnit.lessons.length > 0 ? [parsedUnit.lessons[0].lesson_id] : []);
      setGeneratedPlans([]);
      setBatchDownload(null);
      setGenerationError(null);
    } catch (err) {
      setCurriculumError(err instanceof Error ? err.message : 'Curriculum upload failed.');
    } finally {
      setUploadingCurriculum(false);
    }
  };

  const handleCurriculumRemove = async () => {
    const existingId = unit?.unit_id;
    setUnit(null);
    setSelectedLessonIds([]);
    setCurriculumError(null);
    setGeneratedPlans([]);
    setBatchDownload(null);
    setGenerationError(null);
    if (existingId) {
      fetch(apiUrl(`/api/curriculum/${existingId}`), {
        method: 'DELETE',
        headers: authHeaders(),
      }).catch(() => {});
    }
  };

  // 2. Word Template Upload / Replace / Remove
  const handleTemplateSelect = async (file: File) => {
    setTemplateError(null);
    setUploadingTemplate(true);
    try {
      const fd = new FormData();
      fd.append('docx', file);
      if (stagedRefPdf) {
        fd.append('reference_pdf', stagedRefPdf);
      }
      const res = await fetch(apiUrl('/api/template/upload'), {
        method: 'POST',
        headers: authHeaders(),
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(
          explainHttpError(res.status, data, 'Could not parse the uploaded Word template.')
        );
      }
      const parsedTemplate = data as TemplateSchema;
      setTemplate(parsedTemplate);
      setTemplateSizeBytes(file.size);
      if (stagedRefPdf) {
        setRefPdfSizeBytes(stagedRefPdf.size);
        setStagedRefPdf(null);
      }
      setGeneratedPlans([]);
      setBatchDownload(null);
      setGenerationError(null);
    } catch (err) {
      setTemplateError(err instanceof Error ? err.message : 'Template upload failed.');
    } finally {
      setUploadingTemplate(false);
    }
  };

  const handleTemplateRemove = async () => {
    const existingId = template?.template_id;
    setTemplate(null);
    setTemplateSizeBytes(0);
    setTemplateError(null);
    setGeneratedPlans([]);
    setBatchDownload(null);
    setGenerationError(null);
    if (existingId) {
      fetch(apiUrl(`/api/template/${existingId}`), {
        method: 'DELETE',
        headers: authHeaders(),
      }).catch(() => {});
    }
  };

  // 3. Optional Reference PDF Upload / Replace / Remove (works before or after DOCX upload)
  const handleRefPdfSelect = async (file: File) => {
    setRefPdfError(null);
    if (!template) {
      setStagedRefPdf(file);
      setRefPdfSizeBytes(file.size);
      return;
    }

    setUploadingRefPdf(true);
    try {
      const fd = new FormData();
      fd.append('reference_pdf', file);
      const res = await fetch(apiUrl(`/api/template/${template.template_id}/reference-pdf`), {
        method: 'POST',
        headers: authHeaders(),
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(explainHttpError(res.status, data, 'Could not attach Reference PDF.'));
      }
      setTemplate(data as TemplateSchema);
      setRefPdfSizeBytes(file.size);
      setStagedRefPdf(null);
    } catch (err) {
      setRefPdfError(err instanceof Error ? err.message : 'Reference PDF upload failed.');
    } finally {
      setUploadingRefPdf(false);
    }
  };

  const handleRefPdfRemove = async () => {
    setRefPdfError(null);
    setStagedRefPdf(null);
    setRefPdfSizeBytes(0);
    if (template?.has_reference_pdf) {
      try {
        const res = await fetch(apiUrl(`/api/template/${template.template_id}/reference-pdf`), {
          method: 'DELETE',
          headers: authHeaders(),
        });
        if (res.ok) {
          const updated = (await res.json()) as TemplateSchema;
          setTemplate(updated);
        }
      } catch {
        // Local reference state already cleared
      }
    }
  };

  // Inline Lesson Boundary Correction
  const handleSaveBoundaryEdit = async (
    lessonId: string,
    patch: { title: string; start_page: number; end_page: number }
  ) => {
    if (!unit) return;
    setSavingBoundary(true);
    try {
      const nextLessons = unit.lessons.map((l) => ({
        lesson_id: l.lesson_id,
        title: l.lesson_id === lessonId ? patch.title : l.title,
        start_page: l.lesson_id === lessonId ? patch.start_page : l.start_page,
        end_page: l.lesson_id === lessonId ? patch.end_page : l.end_page,
        approved: l.lesson_id === lessonId ? true : l.approved,
      }));
      const res = await fetch(apiUrl(`/api/curriculum/${unit.unit_id}/boundaries`), {
        method: 'PUT',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ lessons: nextLessons }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(explainHttpError(res.status, data, 'Failed to update lesson range.'));
      }
      setUnit(data as CurriculumUnit);
    } catch (err) {
      setCurriculumError(err instanceof Error ? err.message : 'Could not save lesson boundary.');
    } finally {
      setSavingBoundary(false);
    }
  };

  // Lesson Selection Controls
  const handleToggleLesson = (lessonId: string) => {
    setSelectedLessonIds((prev) =>
      prev.includes(lessonId) ? prev.filter((id) => id !== lessonId) : [...prev, lessonId]
    );
  };

  const handleSelectAll = () => {
    if (!unit || unit.lessons.length === 0) return;
    if (selectedLessonIds.length === unit.lessons.length) {
      setSelectedLessonIds([unit.lessons[0].lesson_id]);
    } else {
      setSelectedLessonIds(unit.lessons.map((l) => l.lesson_id));
    }
  };

  // Generate Single or Multi-Lesson Plans
  const handleGenerate = async () => {
    if (!unit || !template || selectedLessonIds.length === 0 || isGenerating) return;

    setIsGenerating(true);
    setGenerationError(null);
    setGeneratedPlans([]);
    setBatchDownload(null);
    // Stages 0 ("Reading curriculum") & 1 ("Identifying lessons") are already verified from upload
    setActiveStageIndex(2);

    const stageTimer = window.setInterval(() => {
      setActiveStageIndex((prev) => (prev < 5 ? prev + 1 : prev));
    }, 2400);

    const baseContext: Omit<GenerationContext, 'lesson_id'> = {
      unit_id: unit.unit_id,
      template_id: template.template_id,
      school_name: settings?.school_name_ar || 'مدرسة ابدأ الوطنية للعلوم التقنية — بدر',
      teacher_name: settings?.default_teacher_name || 'معلم التكنولوجيا التطبيقية',
      job_title: settings?.default_job_title || 'معلم أول الذكاء الاصطناعي وتحليل البيانات',
      program_or_course: advanced.subject.trim() || 'الذكاء الاصطناعي وتحليل البيانات',
      grade_level: advanced.gradeLevel.trim() || 'الصف الثاني الثانوي التكنولوجي',
      academic_year: settings?.default_academic_year || '٢٠٢٥-٢٠٢٦',
      branch: settings?.default_branch || advanced.subject.trim() || 'الذكاء الاصطناعي وتحليل البيانات',
      knowledge_code: settings?.default_knowledge_code || 'TPK04',
      class_sections: ['2 A', '2B'],
      location: settings?.default_location || 'معمل الذكاء الاصطناعي وتحليل البيانات',
      lesson_date: new Date().toISOString().slice(0, 10),
      total_duration_minutes: Math.max(15, Number(advanced.durationMinutes) || 45),
      output_language: advanced.outputLanguage,
      teacher_instructions: '',
    };

    try {
      if (selectedLessonIds.length > 1) {
        const res = await fetch(apiUrl('/api/generate-batch'), {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            lesson_ids: selectedLessonIds,
            base_context: baseContext,
          }),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(
            explainHttpError(res.status, data, 'Batch lesson plan generation failed.')
          );
        }
        setGeneratedPlans(Array.isArray(data.plans) ? data.plans : []);
        setBatchDownload(
          data.batch_id ? { batchId: data.batch_id, filename: data.zip_filename } : null
        );
      } else {
        const res = await fetch(apiUrl('/api/generate'), {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            ...baseContext,
            lesson_id: selectedLessonIds[0],
          }),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(explainHttpError(res.status, data, 'Lesson plan generation failed.'));
        }
        setGeneratedPlans([data as GeneratedPlanRecord]);
        setBatchDownload(null);
      }
    } catch (err) {
      setGenerationError(
        err instanceof Error ? err.message : 'An unexpected error occurred during generation.'
      );
    } finally {
      window.clearInterval(stageTimer);
      setIsGenerating(false);
    }
  };

  // Upload card file summaries
  const curriculumSummary: UploadedFileSummary | null = unit
    ? {
        name: unit.filename,
        sizeBytes: unit.file_size_bytes,
        metaLine: `${unit.lessons.length} ${unit.lessons.length === 1 ? 'lesson' : 'lessons'} · ${unit.total_pages}p`,
      }
    : null;

  const templateSummary: UploadedFileSummary | null = template
    ? {
        name: template.filename,
        sizeBytes: templateSizeBytes,
        metaLine: `${template.page_count_expected}p · ${template.is_rtl ? 'RTL' : 'LTR'}`,
      }
    : null;

  const refPdfSummary: UploadedFileSummary | null = template?.has_reference_pdf
    ? {
        name: template.reference_pdf_filename || 'Reference.pdf',
        sizeBytes: refPdfSizeBytes,
        metaLine: template.reference_pdf_pages ? `${template.reference_pdf_pages}p baseline` : 'Attached',
      }
    : stagedRefPdf
      ? {
          name: stagedRefPdf.name,
          sizeBytes: stagedRefPdf.size,
          metaLine: 'Ready to compare',
        }
      : null;

  const canGenerate =
    Boolean(unit) &&
    Boolean(template) &&
    selectedLessonIds.length > 0 &&
    !uploadingCurriculum &&
    !uploadingTemplate &&
    !uploadingRefPdf &&
    !isGenerating;

  const readinessHint = !unit && !template
    ? 'Upload a curriculum file and a Word template to continue.'
    : !unit
      ? 'Upload a curriculum file to detect lessons.'
      : !template
        ? 'Upload a Word (.docx) lesson plan template to enable generation.'
        : selectedLessonIds.length === 0
          ? 'Select at least one lesson to generate.'
          : null;

  return (
    <div className="min-h-screen bg-[#FAF9F5] text-[#141716]">
      <div className="max-w-[900px] mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8">
        {/* SECTION A — Minimal Header */}
        <header className="pb-6 border-b border-[#E6E1D3] flex items-center justify-between gap-4">
          <div className="space-y-1 min-w-0">
            <h1 className="text-[22px] sm:text-[26px] font-bold tracking-[-0.02em] text-[#141716] leading-tight">
              EBDA AI Lesson Studio
            </h1>
            <p className="text-[14px] text-[#525B58]">
              Smart Lesson Planning, Made Simple.
            </p>
          </div>

          {settings?.logo_data_url && (
            <img
              src={settings.logo_data_url}
              alt={`${settings.institution_en} official logo`}
              className="h-10 sm:h-11 max-w-[140px] w-auto object-contain shrink-0"
            />
          )}
        </header>

        {/* Access passcode — required by the backend for uploads and generation.
            Session-memory only; sent as a header directly to the backend. */}
        <section
          aria-label="App passcode"
          className="rounded-[14px] border border-[#E6E1D3] bg-white px-4 py-3.5 flex flex-col sm:flex-row sm:items-center gap-3"
        >
          <div className="flex items-center gap-2 shrink-0">
            <Lock className="w-4 h-4 text-[#137A74]" />
            <label
              htmlFor="app-passcode"
              className="text-[13px] font-medium text-[#141716] whitespace-nowrap"
            >
              App passcode
            </label>
          </div>
          <input
            id="app-passcode"
            type="password"
            value={passcode}
            onChange={(e) => setPasscode(e.target.value)}
            placeholder="Required for uploads and generation"
            autoComplete="off"
            className="flex-1 min-h-[38px] rounded-[9px] border border-[#CBC0A3] bg-white px-3 py-1.5 text-[13px] text-[#141716] focus:outline-none focus:border-[#1CA29A]"
          />
          {passcode && (
            <button
              type="button"
              onClick={() => setPasscode('')}
              className="shrink-0 min-h-[38px] px-3 rounded-[9px] border border-[#E6E1D3] bg-white text-[12px] font-medium text-[#525B58] hover:border-[#CBC0A3] transition-colors"
            >
              Clear
            </button>
          )}
          <p className="text-[11.5px] text-[#525B58] sm:max-w-[220px]">
            Kept only for this session and sent directly to the backend over HTTPS. Never stored.
          </p>
        </section>

        <main className="space-y-8">
          {/* SECTION B — File Upload Workspace */}
          <section aria-label="Document uploads" className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-stretch">
              <UploadCard
                id="upload-curriculum"
                title="Curriculum / Lesson File"
                requirementLabel="Required"
                accept=".pdf,.docx,.pptx,.txt"
                allowedExtensions={['pdf', 'docx', 'pptx', 'txt']}
                formatHint="PDF, DOCX, PPTX, TXT"
                helperText="Educational material used as the sole lesson source."
                icon="curriculum"
                file={curriculumSummary}
                uploading={uploadingCurriculum}
                error={curriculumError}
                onSelectFile={handleCurriculumSelect}
                onRemoveFile={handleCurriculumRemove}
                onValidationError={setCurriculumError}
              />

              <UploadCard
                id="upload-template"
                title="Lesson Plan Template"
                requirementLabel="Required"
                accept=".docx"
                allowedExtensions={['docx']}
                formatHint="DOCX only"
                helperText="Editable Word template whose layout will be preserved."
                icon="template"
                file={templateSummary}
                uploading={uploadingTemplate}
                error={templateError}
                onSelectFile={handleTemplateSelect}
                onRemoveFile={handleTemplateRemove}
                onValidationError={setTemplateError}
              />

              <UploadCard
                id="upload-reference-pdf"
                title="Reference PDF"
                requirementLabel="Optional"
                accept=".pdf"
                allowedExtensions={['pdf']}
                formatHint="PDF"
                helperText="Approved layout baseline to verify page count and fit."
                icon="reference"
                file={refPdfSummary}
                uploading={uploadingRefPdf}
                error={refPdfError}
                onSelectFile={handleRefPdfSelect}
                onRemoveFile={handleRefPdfRemove}
                onValidationError={setRefPdfError}
              />
            </div>
          </section>

          {/* SECTION C — Lesson Selection & Generation */}
          <section aria-label="Lesson selection and generation" className="space-y-5">
            {unit && unit.lessons.length > 0 && (
              <LessonSelector
                unit={unit}
                selectedLessonIds={selectedLessonIds}
                onToggleLesson={handleToggleLesson}
                onSelectAll={handleSelectAll}
                onSaveBoundaryEdit={handleSaveBoundaryEdit}
                savingBoundary={savingBoundary}
                advanced={advanced}
                onChangeAdvanced={setAdvanced}
                disabled={isGenerating}
              />
            )}

            {/* Primary Generate Action OR Honest 6-Stage Progress */}
            {isGenerating || generationError ? (
              <GenerationProgress
                activeStageIndex={activeStageIndex}
                selectedCount={selectedLessonIds.length}
                error={generationError}
                onRetry={handleGenerate}
              />
            ) : (
              <div className="space-y-2.5">
                <button
                  type="button"
                  disabled={!canGenerate}
                  onClick={handleGenerate}
                  className="w-full min-h-[50px] px-6 py-3.5 rounded-[14px] bg-[#137A74] hover:bg-[#0F6661] active:bg-[#0C5551] disabled:bg-[#CBC0A3]/55 disabled:text-[#525B58] disabled:cursor-not-allowed text-white text-[15px] font-semibold transition-colors flex items-center justify-center gap-2 cursor-pointer"
                >
                  <span>
                    {selectedLessonIds.length > 1
                      ? `Generate ${selectedLessonIds.length} Lesson Plans`
                      : 'Generate Lesson Plan'}
                  </span>
                  <ArrowRight className="w-4 h-4 shrink-0" />
                </button>

                {readinessHint && (
                  <p className="text-center text-[12.5px] text-[#525B58]">
                    {readinessHint}
                  </p>
                )}
              </div>
            )}
          </section>

          {/* SECTION D — Results & Download */}
          {generatedPlans.length > 0 && (
            <ResultsPanel plans={generatedPlans} batchDownload={batchDownload} />
          )}
        </main>
      </div>
    </div>
  );
}
