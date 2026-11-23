import React, { useEffect, useState } from 'react';
import { ArrowRight, Languages } from 'lucide-react';
import { UploadCard, type UploadedFileSummary } from './components/UploadCard';
import { LessonSelector, type AdvancedOptions } from './components/LessonSelector';
import { GenerationProgress } from './components/GenerationProgress';
import { ResultsPanel } from './components/ResultsPanel';
import type { PlanArtifacts, ZipArtifact } from './components/ResultsPanel';
import type {
  CurriculumUnit,
  GenerationFailure,
  GeneratedPlanRecord,
  GenerationContext,
  InstitutionSettings,
  TemplateSchema,
} from './types';
import { STRINGS, type Lang } from './i18n';
import { readSavedTemplate, saveTemplate, forgetTemplate } from './lib/templateCache';

// Backend origin: build-time VITE_API_BASE_URL wins; otherwise default to the
// deployed PythonAnywhere backend. The tool is open access: no credentials
// are requested from the teacher or embedded in the bundle.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'https://mostafaatteef.pythonanywhere.com').replace(/\/$/, '');
const apiUrl = (path: string) => `${API_BASE_URL}${path}`;
const FRONTEND_RELEASE = '2026.11.23.4';

export default function App() {
  // Institutional defaults & optional official uploaded EBDA logo
  const [settings, setSettings] = useState<InstitutionSettings | null>(null);
  const [backendState, setBackendState] = useState<'checking' | 'online' | 'offline'>('checking');
  const [backendVersion, setBackendVersion] = useState<string | null>(null);
  const [generationMode, setGenerationMode] = useState<'ai' | 'rules_fallback' | null>(null);

  // Section B — Upload state (3 independent cards)
  const [unit, setUnit] = useState<CurriculumUnit | null>(null);
  const [curriculumFileSize, setCurriculumFileSize] = useState<number | null>(null);
  const [curriculumError, setCurriculumError] = useState<string | null>(null);
  const [uploadingCurriculum, setUploadingCurriculum] = useState(false);

  const [template, setTemplate] = useState<TemplateSchema | null>(null);
  const [showTemplateSettings, setShowTemplateSettings] = useState(false);
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
    teacherName: '',
    classSection: '',
    lessonDate: '',
    gradeLevel: 'الصف الثاني الثانوي التكنولوجي',
    subject: 'الذكاء الاصطناعي وتحليل البيانات',
    durationMinutes: 50,
    outputLanguage: 'auto',
  });

  // Generation progress state
  const [isGenerating, setIsGenerating] = useState(false);
  const [activeStageIndex, setActiveStageIndex] = useState(2);
  const [generationError, setGenerationError] = useState<string | null>(null);

  // Section D — Results & Download
  const [generatedPlans, setGeneratedPlans] = useState<GeneratedPlanRecord[]>([]);
  const [planArtifacts, setPlanArtifacts] = useState<Record<string, PlanArtifacts>>({});
  const [generationFailures, setGenerationFailures] = useState<GenerationFailure[]>([]);
  const [batchDownload, setBatchDownload] = useState<ZipArtifact | null>(null);
  // Browser-held uploads: the server is request-scoped and stores nothing, so
  // the template DOCX File (and optional reference PDF File) live here and are
  // attached to each generation request.
  const [templateFile, setTemplateFile] = useState<File | null>(null);

  // Built-in official template availability, reported by the backend.
  // When present, teachers upload only a curriculum file.
  const [serverDefaults, setServerDefaults] = useState<{ template: boolean; reference_pdf: boolean }>({
    template: false,
    reference_pdf: false,
  });

  // Interface language: Arabic-first (teachers are the primary audience),
  // English toggle in the header. Document content direction stays dir="auto".
  const [lang, setLang] = useState<Lang>('ar');
  const t = STRINGS[lang];

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  }, [lang]);

  const authHeaders = (extra?: Record<string, string>): Record<string, string> => {
    return { ...(extra || {}) };
  };

  // Network failures surface as a clear translated message, not a raw TypeError.
  const netMessage = (err: unknown, fallback: string): string => {
    if (err instanceof TypeError) return t.errNetwork;
    return err instanceof Error ? err.message : fallback;
  };

  // Honest server error surfacing: surface the server's own message.
  const explainHttpError = (status: number, data: unknown, fallback: string): string => {
    const body = data as {
      error?: string;
      detail?: string;
      failures?: Array<{ lesson_title?: string; detail?: string }>;
    } | null;
    // A proxy/host 413 is usually an HTML page, not JSON: give a real message.
    if (status === 413) {
      return STRINGS[lang].errPayloadTooLarge;
    }
    const serverMessage = body?.error || body?.detail || '';
    if (serverMessage === 'No lesson could be generated.') {
      return STRINGS[lang].noLessonsGenerated;
    }
    if (serverMessage) {
      // Surface the per-lesson blocking reasons instead of discarding them.
      const failureLines = (body?.failures || [])
        .map((f) => [f.lesson_title, f.detail].filter(Boolean).join(': '))
        .filter(Boolean);
      return failureLines.length ? `${serverMessage}\n${failureLines.join('\n')}` : serverMessage;
    }
    return fallback;
  };

  // Load EBDA institutional settings on mount (includes official logo if configured)
  useEffect(() => {
    let active = true;

    // Restore previously approved files on this device before selecting server defaults.
    // Never store curriculum content; only a teacher-selected DOCX template and reference PDF.
    void (async () => {
      const [savedDocx, savedReference] = await Promise.all([
        readSavedTemplate('template').catch(() => null),
        readSavedTemplate('reference').catch(() => null),
      ]);
      if (!active) return;
      if (savedReference) {
        setStagedRefPdf(savedReference);
        setRefPdfSizeBytes(savedReference.size);
      }
      try {
        const res = await fetch(apiUrl('/api/health'));
        const health = res.ok ? await res.json().catch(() => null) : null;
        if (!active) return;
        if (!health || health.status !== 'ok') {
          setBackendState('offline');
          return;
        }
        setBackendState('online');
        setBackendVersion(typeof health.version === 'string' ? health.version : null);
        setGenerationMode(health.generation?.mode === 'ai' ? 'ai' : 'rules_fallback');
        setServerDefaults({
          template: Boolean(health.defaults?.template),
          reference_pdf: Boolean(health.defaults?.reference_pdf),
        });
        if (!savedDocx && !health.defaults?.template) return;
        const fd = new FormData();
        if (savedDocx) fd.append('docx', savedDocx);
        if (savedReference) fd.append('reference_pdf', savedReference);
        const parsedRes = await fetch(apiUrl('/api/template/parse'), {
          method: 'POST', headers: authHeaders(), body: fd,
        });
        const parsed = parsedRes.ok
          ? ((await parsedRes.json().catch(() => null)) as TemplateSchema | null)
          : null;
        if (active && parsed) {
          setTemplate(parsed);
          if (savedDocx) {
            setTemplateFile(savedDocx);
            setTemplateSizeBytes(savedDocx.size);
          }
        } else if (active && savedDocx) {
          setTemplateError(lang === 'ar'
            ? 'تعذرت استعادة النموذج المحفوظ. يمكنك اختياره مرة أخرى.'
            : 'Could not restore the saved template. Select it again.');
        }
      } catch {
        if (active) setBackendState('offline');
      }
    })();

    fetch(apiUrl('/api/settings'))
      .then((res) => (res.ok ? res.json() : null))
      .then((data: InstitutionSettings | null) => {
        if (!active || !data) return;
        setSettings(data);
        setAdvanced((prev) => ({
          ...prev,
          teacherName: data.default_teacher_name || prev.teacherName,
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
      const res = await fetch(apiUrl('/api/curriculum/parse'), {
        method: 'POST',
        headers: authHeaders(),
        body: fd,
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        throw new Error(explainHttpError(res.status, data, t.errCurriculumUpload));
      }
      if (data == null) {
        throw new Error(t.errUnexpected);
      }
      const parsedUnit = data as CurriculumUnit;
      setUnit(parsedUnit);
      setCurriculumFileSize(file.size);
      setSelectedLessonIds(parsedUnit.lessons.length > 0 ? [parsedUnit.lessons[0].lesson_id] : []);
      setGeneratedPlans([]);
      setBatchDownload(null);
      setGenerationError(null);
    } catch (err) {
      setCurriculumError(netMessage(err, t.errCurriculumUpload));
    } finally {
      setUploadingCurriculum(false);
    }
  };

  const handleCurriculumRemove = async () => {
    // Server is request-scoped: removal is purely local state cleanup.
    if (!unit) return;
    setUnit(null);
    setCurriculumFileSize(null);
    setSelectedLessonIds([]);
    setGeneratedPlans([]);
    setGenerationFailures([]);
    clearArtifacts();
    setGenerationError(null);
    setCurriculumError(null);
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
      const res = await fetch(apiUrl('/api/template/parse'), {
        method: 'POST',
        headers: authHeaders(),
        body: fd,
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        throw new Error(explainHttpError(res.status, data, t.errTemplateUpload));
      }
      if (data == null) {
        throw new Error(t.errUnexpected);
      }
      const parsedTemplate = data as TemplateSchema;
      setTemplate(parsedTemplate);
      setTemplateFile(file);
      setTemplateSizeBytes(file.size);
      // One successful upload is enough on this browser; persist across sessions.
      void saveTemplate('template', file).catch(() => {});
      if (stagedRefPdf) {
        setRefPdfSizeBytes(stagedRefPdf.size);
      }
      setGeneratedPlans([]);
      setGenerationFailures([]);
      clearArtifacts();
      setGenerationError(null);
    } catch (err) {
      setTemplateError(netMessage(err, t.errTemplateUpload));
    } finally {
      setUploadingTemplate(false);
    }
  };

  const handleTemplateRemove = async () => {
    // Server is request-scoped: removal is purely local state cleanup.
    if (!template) return;
    const hadCustomFile = templateFile !== null;
    setTemplate(null);
    setTemplateFile(null);
    setTemplateSizeBytes(0);
    void forgetTemplate('template').catch(() => {});
    void forgetTemplate('reference').catch(() => {});
    setStagedRefPdf(null);
    setRefPdfSizeBytes(0);
    setGeneratedPlans([]);
    setGenerationFailures([]);
    clearArtifacts();
    setGenerationError(null);
    setTemplateError(null);
    // Removing a custom template restores the built-in official one.
    if (hadCustomFile && serverDefaults.template) {
      try {
        const res = await fetch(apiUrl('/api/template/parse'), {
          method: 'POST',
          headers: authHeaders(),
          body: new FormData(),
        });
        const parsed = res.ok ? ((await res.json().catch(() => null)) as TemplateSchema | null) : null;
        if (parsed) setTemplate(parsed);
      } catch {
        // Built-in restore failed; teacher can upload a template manually.
      }
    }
  };

  // 3. Optional Reference PDF Upload / Replace / Remove (works before or after DOCX upload)
  const handleRefPdfSelect = async (file: File) => {
    setRefPdfError(null);
    if (!template) {
      setStagedRefPdf(file);
      setRefPdfSizeBytes(file.size);
      void saveTemplate('reference', file).catch(() => {});
      return;
    }

    setUploadingRefPdf(true);
    try {
      const fd = new FormData();
      if (templateFile) {
        fd.append('docx', templateFile);
      }
      fd.append('reference_pdf', file);
      const res = await fetch(apiUrl('/api/template/parse'), {
        method: 'POST',
        headers: authHeaders(),
        body: fd,
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        throw new Error(explainHttpError(res.status, data, t.errRefPdfUpload));
      }
      if (data == null) {
        throw new Error(t.errUnexpected);
      }
      setTemplate(data as TemplateSchema);
      setRefPdfSizeBytes(file.size);
      setStagedRefPdf(file);
      void saveTemplate('reference', file).catch(() => {});
    } catch (err) {
      setRefPdfError(netMessage(err, t.errRefPdfUpload));
    } finally {
      setUploadingRefPdf(false);
    }
  };

  const handleRefPdfRemove = async () => {
    setRefPdfError(null);
    void forgetTemplate('reference').catch(() => {});
    if (!template?.has_reference_pdf || (!templateFile && !serverDefaults.template)) {
      setStagedRefPdf(null);
      setRefPdfSizeBytes(0);
      return;
    }
    // Re-parse the held (or built-in) template without the reference PDF.
    try {
      const fd = new FormData();
      if (templateFile) {
        fd.append('docx', templateFile);
      }
      const res = await fetch(apiUrl('/api/template/parse'), {
        method: 'POST',
        headers: authHeaders(),
        body: fd,
      });
      if (res.ok) {
        const rebased = (await res.json().catch(() => null)) as TemplateSchema | null;
        if (rebased) setTemplate(rebased);
      }
    } catch (err) {
      setRefPdfError(netMessage(err, t.errRefPdfRemove));
    }
    setStagedRefPdf(null);
    setRefPdfSizeBytes(0);
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
      const res = await fetch(apiUrl('/api/curriculum/rebind'), {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ unit, lessons: nextLessons }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        throw new Error(explainHttpError(res.status, data, t.errBoundary));
      }
      if (data == null) {
        throw new Error(t.errUnexpected);
      }
      setUnit(data as CurriculumUnit);
    } catch (err) {
      setCurriculumError(netMessage(err, t.errBoundary));
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

  // Artifact helpers: generation responses carry base64 artifacts; they are
  // decoded once into object URLs held in this tab's memory. Revoking happens
  // on replace/new upload; tab close discards everything.
  const b64ToUrl = (b64: string, mime: string): string => {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return URL.createObjectURL(new Blob([bytes], { type: mime }));
  };

  const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

  const clearArtifacts = () => {
    for (const a of Object.values(planArtifacts)) {
      URL.revokeObjectURL(a.docxUrl);
      if (a.pdfUrl) URL.revokeObjectURL(a.pdfUrl);
    }
    if (batchDownload) URL.revokeObjectURL(batchDownload.url);
    setPlanArtifacts({});
    setBatchDownload(null);
  };

  const recordPlan = (plan: GeneratedPlanRecord): PlanArtifacts => {
    const artifacts: PlanArtifacts = {
      docxUrl: plan.docx_b64 ? b64ToUrl(plan.docx_b64, DOCX_MIME) : '',
      docxName: plan.docx_filename,
      pdfUrl: plan.pdf_b64 ? b64ToUrl(plan.pdf_b64, 'application/pdf') : null,
      pdfName: plan.pdf_filename || null,
    };
    delete plan.docx_b64;
    delete plan.pdf_b64;
    return artifacts;
  };

  // Generate Single or Multi-Lesson Plans
  const handleGenerate = async () => {
    if (
      !unit ||
      !template ||
      (!templateFile && !serverDefaults.template) ||
      selectedLessonIds.length === 0 ||
      isGenerating
    )
      return;

    setIsGenerating(true);
    setGenerationError(null);
    setGeneratedPlans([]);
    setGenerationFailures([]);
    clearArtifacts();
    // Stages 0 ("Reading curriculum") & 1 ("Identifying lessons") are already verified from upload
    setActiveStageIndex(2);

    // Keep active generation stage fixed unless real server progress arrives.

    const baseContext: Omit<GenerationContext, 'lesson_id'> = {
      unit_id: unit.unit_id,
      template_id: template.template_id,
      school_name: settings?.school_name_ar || 'مدرسة ابدأ الوطنية للعلوم التقنية — بدر',
      teacher_name:
        advanced.teacherName.trim() ||
        settings?.default_teacher_name ||
        'معلم التكنولوجيا التطبيقية',
      job_title: settings?.default_job_title || 'معلم أول الذكاء الاصطناعي وتحليل البيانات',
      program_or_course: advanced.subject.trim() || 'الذكاء الاصطناعي وتحليل البيانات',
      grade_level: advanced.gradeLevel.trim() || 'الصف الثاني الثانوي التكنولوجي',
      academic_year: settings?.default_academic_year || '٢٠٢٦-٢٠٢٧',
      branch: settings?.default_branch || advanced.subject.trim() || 'الذكاء الاصطناعي وتحليل البيانات',
      knowledge_code: settings?.default_knowledge_code || 'TPK04',
      class_sections: advanced.classSection.trim()
        ? advanced.classSection.split(/[،,]/).map((s) => s.trim()).filter(Boolean)
        : ['2 A', '2B'],
      location: settings?.default_location || 'معمل الذكاء الاصطناعي وتحليل البيانات',
      lesson_date: advanced.lessonDate || new Date().toISOString().slice(0, 10),
      total_duration_minutes: Math.max(15, Number(advanced.durationMinutes) || 50),
      output_language: advanced.outputLanguage,
      teacher_instructions: '',
    };

    // Request-scoped generation: the browser-held template file and the
    // selected lessons (with their parsed text) travel WITH this request;
    // every artifact comes back IN the response. The server stores nothing.
    const selectedLessons = unit.lessons.filter((l) => selectedLessonIds.includes(l.lesson_id));
    const slimUnit: Record<string, unknown> = { ...unit };
    delete slimUnit.lessons;
    delete slimUnit.pages;
    try {
      const fd = new FormData();
      if (templateFile) {
        fd.append('template', templateFile);
      }
      if (stagedRefPdf) {
        fd.append('reference_pdf', stagedRefPdf);
      }
      fd.append(
        'request',
        JSON.stringify({ context: baseContext, unit: slimUnit, lessons: selectedLessons })
      );
      const res = await fetch(apiUrl('/api/generate'), {
        method: 'POST',
        headers: authHeaders(),
        body: fd,
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        throw new Error(
          explainHttpError(
            res.status,
            data,
            selectedLessonIds.length > 1 ? t.errGenerateBatch : t.errGenerate
          )
        );
      }
      if (data == null) {
        throw new Error(t.errUnexpected);
      }
      const plans: GeneratedPlanRecord[] = data.plan
        ? [data.plan as GeneratedPlanRecord]
        : Array.isArray(data.plans)
          ? (data.plans as GeneratedPlanRecord[])
          : [];
      const artifacts: Record<string, PlanArtifacts> = {};
      for (const plan of plans) {
        artifacts[plan.plan_id] = recordPlan(plan);
      }
      setGeneratedPlans(plans);
      setPlanArtifacts(artifacts);
      setGenerationFailures(Array.isArray(data.failures) ? (data.failures as GenerationFailure[]) : []);
      setBatchDownload(
        data.zip_b64
          ? {
              url: b64ToUrl(data.zip_b64, 'application/zip'),
              filename: data.zip_filename || 'ATS-MU_Lesson_Plans.zip',
            }
          : null
      );
    } catch (err) {
      setGenerationError(netMessage(err, t.errUnexpected));
    } finally {
      setIsGenerating(false);
    }
  };

  // Upload card file summaries
  const curriculumSummary: UploadedFileSummary | null = unit
    ? {
        name: unit.filename,
        sizeBytes: curriculumFileSize,
        metaLine: `${t.metaLessons(unit.lessons.length)} · ${t.metaPages(unit.total_pages)}`,
      }
    : null;

  const templateSummary: UploadedFileSummary | null = template
    ? {
        name: templateFile ? template.filename : t.builtinTemplateName,
        sizeBytes: templateFile ? templateSizeBytes : null,
        metaLine: `${t.metaPages(template.page_count_expected)} · ${template.is_rtl ? t.rtlLabel : t.ltrLabel}`,
      }
    : null;

  const refPdfSummary: UploadedFileSummary | null = template?.has_reference_pdf
    ? {
        name: template.reference_pdf_filename || 'Reference.pdf',
        sizeBytes: refPdfSizeBytes,
        metaLine: template.reference_pdf_pages ? t.metaBaseline(template.reference_pdf_pages) : t.metaAttached,
      }
    : stagedRefPdf
      ? {
          name: stagedRefPdf.name,
          sizeBytes: stagedRefPdf.size,
          metaLine: t.metaReadyToCompare,
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
    ? t.readinessBoth
    : !unit
      ? t.readinessCurriculum
      : !template
        ? t.readinessTemplate
        : selectedLessonIds.length === 0
          ? t.readinessLessons
          : null;

  return (
    <div className={`min-h-screen bg-[#F8FAF9] text-[#17252C] ${lang === 'ar' ? 'font-arabic' : ''}`}>
      <div className="max-w-[900px] mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8">
        {/* SECTION A — Minimal Header */}
        <header className="pb-6 border-b border-[#E3EAE7] grid grid-cols-[1fr_auto_1fr] items-center gap-4">
          <div className="flex items-center gap-3 shrink-0 justify-self-start">
            <button
              type="button"
              onClick={() => setLang(lang === 'ar' ? 'en' : 'ar')}
              className="inline-flex items-center gap-1.5 min-h-[36px] px-3 py-1.5 text-[12.5px] font-medium rounded-[9px] border border-[#E3EAE7] bg-white text-[#17252C] hover:border-[#168B83] hover:text-[#116962] transition-colors whitespace-nowrap"
              aria-label="Switch interface language"
            >
              <Languages className="w-3.5 h-3.5 text-[#116962]" />
              {t.langToggle}
            </button>

          {settings?.logo_data_url && (
            <img
              src={settings.logo_data_url}
              alt={`${settings.institution_en} official logo`}
              className="h-10 sm:h-11 max-w-[140px] w-auto object-contain shrink-0"
            />
          )}
          </div>

          <div className="space-y-1 min-w-0 text-center">
            <h1 className="text-[22px] sm:text-[26px] font-bold tracking-[-0.02em] text-[#17252C] leading-tight">
              EBDA AI Lesson Studio
            </h1>
            <p className="text-[14px] text-[#596A72]">
              {t.tagline}
            </p>
          </div>

          <div className="justify-self-end text-end space-y-1" role="status" aria-live="polite">
            <span className="block text-[11px] text-[#596A72]">UI v{FRONTEND_RELEASE}</span>
            <span className={`block text-[11px] font-medium ${backendState === 'online' ? 'text-emerald-700' : backendState === 'offline' ? 'text-rose-700' : 'text-[#596A72]'}`}>
              {lang === 'ar'
                ? backendState === 'online' ? 'الخادم متصل' : backendState === 'offline' ? 'الخادم غير متاح' : 'جارٍ فحص الخادم'
                : backendState === 'online' ? 'API connected' : backendState === 'offline' ? 'API unavailable' : 'Checking API'}
              {backendState === 'online' && backendVersion ? ` · v${backendVersion}` : ''}
            </span>
          </div>
        </header>

        <main className="space-y-8">
          {/* SECTION B — File Upload Workspace */}
          <section aria-label="Document uploads" className="space-y-3">
            <p className="text-[12px] text-[#53716B]" role="note">
              {lang === 'ar'
                ? 'نموذج Word ومرجع PDF الرسميان متاحان تلقائيًا عند اتصال الخادم. ارفع المنهج واختر الدرس.'
                : 'The official Word and PDF templates load from the server when available. Upload a curriculum and choose a lesson.'}
            </p>
            {backendState === 'online' && (
              <p role="status" className="text-[12px] text-[#53716B]">
                {generationMode === 'ai'
                  ? (lang === 'ar' ? 'الذكاء الاصطناعي مفعل على الخادم' : 'AI generation is enabled')
                  : (lang === 'ar' ? 'وضع التوليد بالقواعد: المحتوى يحتاج مراجعة المعلم' : 'Rules-based mode: teacher review is required')}
              </p>
            )
            {template && (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-[#EAF4F0] px-4 py-3">
                <span className="text-[13px] font-medium text-[#116962]">
                  {lang === 'ar'
                    ? '✓ نموذج التحضير جاهز — ارفع المنهج فقط'
                    : '✓ Lesson plan template ready — upload the curriculum only'}
                </span>
                <button type="button" onClick={() => setShowTemplateSettings((v) => !v)}
                  className="text-[12px] font-semibold text-[#116962] underline underline-offset-2">
                  {lang === 'ar'
                    ? showTemplateSettings ? 'إخفاء إعدادات النموذج' : 'تغيير النموذج أو المرجع'
                    : showTemplateSettings ? 'Hide template settings' : 'Change template or reference'}
                </button>
              </div>
            )}
            <div className={`grid grid-cols-1 ${!template || showTemplateSettings ? 'md:grid-cols-3' : ''} gap-4 items-stretch`}>
              <UploadCard
                id="upload-curriculum"
                title={t.curriculumTitle}
                required
                requirementLabel={t.required}
                accept=".pdf,.docx,.pptx,.txt"
                allowedExtensions={['pdf', 'docx', 'pptx', 'txt']}
                formatHint="PDF, DOCX, PPTX, TXT"
                helperText={t.curriculumHelper}
                icon="curriculum"
                file={curriculumSummary}
                uploading={uploadingCurriculum}
                error={curriculumError}
                onSelectFile={handleCurriculumSelect}
                onRemoveFile={handleCurriculumRemove}
                onValidationError={setCurriculumError}
                t={t}
              />

              {(!template || showTemplateSettings) && (<>
              <UploadCard
                id="upload-template"
                title={t.templateTitle}
                required={!serverDefaults.template}
                requirementLabel={serverDefaults.template ? t.optional : t.required}
                accept=".docx"
                allowedExtensions={['docx']}
                formatHint="DOCX only"
                helperText={serverDefaults.template ? t.builtinTemplateReady : t.templateHelper}
                icon="template"
                file={templateSummary}
                uploading={uploadingTemplate}
                error={templateError}
                onSelectFile={handleTemplateSelect}
                onRemoveFile={handleTemplateRemove}
                onValidationError={setTemplateError}
                t={t}
              />

              <UploadCard
                id="upload-reference-pdf"
                title={t.refPdfTitle}
                required={false}
                requirementLabel={t.optional}
                accept=".pdf"
                allowedExtensions={['pdf']}
                formatHint="PDF"
                helperText={t.refPdfHelper}
                icon="reference"
                file={refPdfSummary}
                uploading={uploadingRefPdf}
                error={refPdfError}
                onSelectFile={handleRefPdfSelect}
                onRemoveFile={handleRefPdfRemove}
                onValidationError={setRefPdfError}
                t={t}
              />
              </>)}
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
                t={t}
              />
            )}

            {/* Primary Generate Action OR Honest 6-Stage Progress */}
            {isGenerating || generationError ? (
              <GenerationProgress
                activeStageIndex={activeStageIndex}
                selectedCount={selectedLessonIds.length}
                error={generationError}
                onRetry={handleGenerate}
                t={t}
              />
            ) : (
              <div className="space-y-2.5">
                <button
                  type="button"
                  disabled={!canGenerate}
                  onClick={handleGenerate}
                  className="w-full min-h-[50px] px-6 py-3.5 rounded-[14px] bg-[#116962] hover:bg-[#0A544F] active:bg-[#0A544F] disabled:bg-[#CBC0A3]/55 disabled:text-[#596A72] disabled:cursor-not-allowed text-white text-[15px] font-semibold transition-colors flex items-center justify-center gap-2 cursor-pointer"
                >
                  <span>
                    {selectedLessonIds.length > 1
                      ? t.generateMulti(selectedLessonIds.length)
                      : t.generateSingle}
                  </span>
                  <ArrowRight className="w-4 h-4 shrink-0 rtl:-scale-x-100" />
                </button>

                {readinessHint && (
                  <p className="text-center text-[12.5px] text-[#596A72]">
                    {readinessHint}
                  </p>
                )}
              </div>
            )}
          </section>

          {/* SECTION D — Results & Download */}
          {generatedPlans.length > 0 && (
            <ResultsPanel
              plans={generatedPlans}
              artifacts={planArtifacts}
              batchDownload={batchDownload}
              failures={generationFailures}
              t={t}
            />
          )}
        </main>
      </div>
    </div>
  );
}
