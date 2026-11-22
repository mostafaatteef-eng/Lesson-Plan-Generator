import crypto from 'crypto';
import express from 'express';
import multer from 'multer';
import JSZip from 'jszip';
import { PDFDocument } from 'pdf-lib';
import {
  exportLessonPdf,
  ingestCurriculumFile,
  updateUnitBoundaries,
} from './curriculumEngine';
import {
  injectLessonPlanIntoDocx,
  parseTemplateDocx,
} from './templateEngine';
import {
  generateStructuredLessonPlan,
  normalizeElementDurations,
  regenerateSelectedFields,
  runTargetedAiAction,
} from './aiEngine';
import { renderDocxToPdf, runFourPillarQA } from './renderQaEngine';
import {
  buildSampleAtsMuTemplateDocx,
  buildSampleReferencePdf,
  getSampleCurriculumText,
} from './sampleGenerator';
import type {
  AiGenerationMode,
  CurriculumUnit,
  GeneratedPlanRecord,
  GenerationContext,
  InstitutionSettings,
  LessonPlanPayload,
  TemplateSchema,
} from './types';

interface StoredUnit {
  unit: CurriculumUnit;
  originalBuffer: Buffer;
}

interface StoredTemplate {
  schema: TemplateSchema;
  docxBuffer: Buffer;
  refPdfBuffer?: Buffer;
}

interface StoredPlan {
  record: GeneratedPlanRecord;
  docxBuffer: Buffer;
  pdfBuffer: Buffer;
}

function getDefaultSettings(): InstitutionSettings {
  return {
    institution_en: 'EBDA National Schools of Applied Technology',
    institution_ar: 'مدارس ابدأ الوطنية للعلوم التقنية',
    school_name_en: 'EBDA National School of Applied Technology – Badr',
    school_name_ar: 'مدرسة ابدأ الوطنية للعلوم التقنية — بدر',
    specialization_en: 'Artificial Intelligence & Data Analysis',
    specialization_ar: 'الذكاء الاصطناعي وتحليل البيانات',
    default_teacher_name: '',
    default_job_title: 'معلم أول الذكاء الاصطناعي وتحليل البيانات',
    default_grade_level: 'الصف الثاني الثانوي التكنولوجي',
    default_academic_year: '٢٠٢٥-٢٠٢٦',
    default_branch: 'الذكاء الاصطناعي وتحليل البيانات',
    default_knowledge_code: 'TPK04',
    default_location: 'معمل الذكاء الاصطناعي وتحليل البيانات',
    default_duration_minutes: 45,
    logo_data_url: null,
    logo_filename: null,
    extracted_brand_color: null,
  };
}

export function createApiRouter() {
  const router = express.Router();
  const upload = multer({
    storage: multer.memoryStorage(),
    limits: { fileSize: 35 * 1024 * 1024 },
  });

  const units = new Map<string, StoredUnit>();
  const templates = new Map<string, StoredTemplate>();
  const plans = new Map<string, StoredPlan>();
  const batches = new Map<string, { filename: string; zipBuffer: Buffer; planIds: string[] }>();
  let settings: InstitutionSettings = getDefaultSettings();

  router.get('/state', (_req, res) => {
    res.json({
      units: Array.from(units.values()).map((u) => u.unit),
      templates: Array.from(templates.values()).map((t) => t.schema),
      plans: Array.from(plans.values())
        .map((p) => p.record)
        .sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
      settings,
    });
  });

  router.get('/settings', (_req, res) => {
    res.json(settings);
  });

  router.put('/settings', (req, res) => {
    const incoming = req.body as Partial<InstitutionSettings>;
    if (incoming.logo_data_url && typeof incoming.logo_data_url === 'string') {
      if (!incoming.logo_data_url.startsWith('data:image/')) {
        return res.status(400).json({ error: 'Logo must be a valid uploaded image data URL.' });
      }
      if (incoming.logo_data_url.length > 4 * 1024 * 1024) {
        return res.status(400).json({ error: 'Logo image exceeds 4 MB limit.' });
      }
    }
    settings = {
      ...settings,
      ...incoming,
      default_duration_minutes: Math.max(
        15,
        Math.min(180, Number(incoming.default_duration_minutes ?? settings.default_duration_minutes) || 45)
      ),
    };
    return res.json(settings);
  });

  // Optional starter verification pack (keeps real workflow clean while letting reviewers test end-to-end immediately)
  router.post('/sample/load', async (_req, res) => {
    try {
      const sampleText = getSampleCurriculumText();
      const { unit, originalBuffer } = await ingestCurriculumFile(
        Buffer.from(sampleText, 'utf8'),
        'EBDA_Sample_Unit3_Curriculum.txt'
      );
      units.set(unit.unit_id, { unit, originalBuffer });

      const sampleDocx = await buildSampleAtsMuTemplateDocx();
      const sampleRefPdf = await buildSampleReferencePdf();
      const schema = await parseTemplateDocx(
        sampleDocx,
        'ATS-MU_6Page_Arabic_Template.docx',
        sampleRefPdf,
        'ATS-MU_6Page_Reference.pdf'
      );
      schema.is_locked = true;
      templates.set(schema.template_id, {
        schema,
        docxBuffer: sampleDocx,
        refPdfBuffer: sampleRefPdf,
      });

      res.json({ unit, template: schema });
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : 'Failed to load sample assets' });
    }
  });

  // Step 1: Upload Curriculum Unit (PDF, DOCX, PPTX, TXT)
  router.post('/curriculum/upload', upload.single('file'), async (req, res) => {
    try {
      if (!req.file) {
        return res.status(400).json({ error: 'No curriculum file provided.' });
      }
      const originalName = Buffer.from(req.file.originalname, 'latin1').toString('utf8');
      const { unit, originalBuffer } = await ingestCurriculumFile(req.file.buffer, originalName);
      units.set(unit.unit_id, { unit, originalBuffer });
      return res.json(unit);
    } catch (err) {
      return res.status(500).json({ error: err instanceof Error ? err.message : 'Failed to parse curriculum file.' });
    }
  });

  router.delete('/curriculum/:id', (req, res) => {
    if (!units.has(req.params.id)) {
      return res.status(404).json({ error: 'Curriculum unit not found.' });
    }
    units.delete(req.params.id);
    return res.json({ deleted: req.params.id });
  });

  // Step 2: Review & Correct Lesson Boundaries
  router.put('/curriculum/:id/boundaries', (req, res) => {
    const stored = units.get(req.params.id);
    if (!stored) {
      return res.status(404).json({ error: 'Curriculum unit not found.' });
    }
    const { lessons } = req.body as {
      lessons: Array<{
        lesson_id: string;
        title: string;
        start_page: number;
        end_page: number;
        approved: boolean;
      }>;
    };
    if (!Array.isArray(lessons) || lessons.length === 0) {
      return res.status(400).json({ error: 'At least one lesson boundary is required.' });
    }
    stored.unit = updateUnitBoundaries(stored.unit, lessons);
    return res.json(stored.unit);
  });

  // Export Individual Lesson PDF
  router.get('/curriculum/:unitId/lesson/:lessonId/pdf', async (req, res) => {
    const stored = units.get(req.params.unitId);
    if (!stored) return res.status(404).json({ error: 'Curriculum unit not found.' });
    const lesson = stored.unit.lessons.find((l) => l.lesson_id === req.params.lessonId);
    if (!lesson) return res.status(404).json({ error: 'Lesson not found in unit.' });

    try {
      const pdfBuf = await exportLessonPdf(stored.unit, lesson, stored.originalBuffer);
      res.setHeader('Content-Type', 'application/pdf');
      res.setHeader('Content-Disposition', `attachment; filename="lesson_${lesson.lesson_number}.pdf"`);
      return res.send(pdfBuf);
    } catch (err) {
      return res.status(500).json({ error: err instanceof Error ? err.message : 'Failed to export lesson PDF.' });
    }
  });

  // Step 3: Upload & Parse Editable DOCX Template + Optional Reference PDF
  router.post(
    '/template/upload',
    upload.fields([
      { name: 'docx', maxCount: 1 },
      { name: 'reference_pdf', maxCount: 1 },
    ]),
    async (req, res) => {
      try {
        const files = req.files as Record<string, Express.Multer.File[]> | undefined;
        const docxFile = files?.docx?.[0];
        const refPdfFile = files?.reference_pdf?.[0];
        if (!docxFile) {
          return res.status(400).json({ error: 'An editable .docx template file is required.' });
        }
        const docxName = Buffer.from(docxFile.originalname, 'latin1').toString('utf8');
        const refName = refPdfFile
          ? Buffer.from(refPdfFile.originalname, 'latin1').toString('utf8')
          : undefined;

        const schema = await parseTemplateDocx(docxFile.buffer, docxName, refPdfFile?.buffer, refName);
        templates.set(schema.template_id, {
          schema,
          docxBuffer: docxFile.buffer,
          refPdfBuffer: refPdfFile?.buffer,
        });
        return res.json(schema);
      } catch (err) {
        return res.status(500).json({ error: err instanceof Error ? err.message : 'Failed to parse DOCX template.' });
      }
    }
  );

  router.delete('/template/:id', (req, res) => {
    if (!templates.has(req.params.id)) {
      return res.status(404).json({ error: 'Template not found.' });
    }
    templates.delete(req.params.id);
    return res.json({ deleted: req.params.id });
  });

  router.post('/template/:id/lock', (req, res) => {
    const stored = templates.get(req.params.id);
    if (!stored) return res.status(404).json({ error: 'Template not found.' });
    stored.schema.is_locked = Boolean(req.body?.is_locked ?? true);
    return res.json(stored.schema);
  });

  router.get('/template/:id/reference-pdf', (req, res) => {
    const stored = templates.get(req.params.id);
    if (!stored || !stored.refPdfBuffer) {
      return res.status(404).json({ error: 'Reference PDF not available for this template.' });
    }
    res.setHeader('Content-Type', 'application/pdf');
    res.setHeader('Content-Disposition', 'inline; filename="reference.pdf"');
    return res.send(stored.refPdfBuffer);
  });

  router.post('/template/:id/reference-pdf', upload.single('reference_pdf'), async (req, res) => {
    const stored = templates.get(req.params.id);
    if (!stored) return res.status(404).json({ error: 'Template not found.' });
    if (!req.file) return res.status(400).json({ error: 'A PDF file is required.' });
    try {
      const refPdf = await PDFDocument.load(req.file.buffer);
      const dims = refPdf.getPages().map((p, idx) => {
        const { width, height } = p.getSize();
        return {
          page: idx + 1,
          width_pt: Math.round(width * 100) / 100,
          height_pt: Math.round(height * 100) / 100,
        };
      });
      const refName = Buffer.from(req.file.originalname, 'latin1').toString('utf8');
      stored.refPdfBuffer = req.file.buffer;
      stored.schema = {
        ...stored.schema,
        has_reference_pdf: true,
        reference_pdf_filename: refName,
        reference_pdf_pages: refPdf.getPageCount(),
        reference_pdf_dimensions: dims,
      };
      return res.json(stored.schema);
    } catch (err) {
      return res.status(400).json({
        error: err instanceof Error ? `Invalid Reference PDF: ${err.message}` : 'Invalid Reference PDF file.',
      });
    }
  });

  router.delete('/template/:id/reference-pdf', (req, res) => {
    const stored = templates.get(req.params.id);
    if (!stored) return res.status(404).json({ error: 'Template not found.' });
    stored.refPdfBuffer = undefined;
    stored.schema = {
      ...stored.schema,
      has_reference_pdf: false,
      reference_pdf_filename: undefined,
      reference_pdf_pages: undefined,
      reference_pdf_dimensions: undefined,
    };
    return res.json(stored.schema);
  });

  router.get('/template/:id/docx', (req, res) => {
    const stored = templates.get(req.params.id);
    if (!stored) return res.status(404).json({ error: 'Template not found.' });
    res.setHeader(
      'Content-Type',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    );
    res.setHeader('Content-Disposition', `attachment; filename="${stored.schema.filename}"`);
    return res.send(stored.docxBuffer);
  });

  async function rebuildPlanArtifacts(
    existing: StoredPlan,
    updatedPayload: LessonPlanPayload
  ): Promise<StoredPlan> {
    const storedUnit = units.get(existing.record.context.unit_id);
    const lesson = storedUnit?.unit.lessons.find((l) => l.lesson_id === existing.record.context.lesson_id);
    const storedTemplate = templates.get(existing.record.context.template_id);
    if (!lesson || !storedTemplate) {
      throw new Error('Original source lesson or template is no longer loaded.');
    }

    const injection = await injectLessonPlanIntoDocx(
      storedTemplate.docxBuffer,
      storedTemplate.schema,
      updatedPayload
    );
    const rendered = await renderDocxToPdf(injection.docxBuffer, storedTemplate.schema, updatedPayload);
    const qaReport = await runFourPillarQA({
      lesson,
      schema: storedTemplate.schema,
      payload: updatedPayload,
      injection,
      renderedPdfBuffer: rendered.pdfBuffer,
      libreofficeUsed: rendered.libreofficeUsed,
      referencePdfBuffer: storedTemplate.refPdfBuffer,
    });

    existing.record = {
      ...existing.record,
      updated_at: new Date().toISOString(),
      lesson_title: updatedPayload.lesson_title,
      payload: updatedPayload,
      qa_report: qaReport,
    };
    existing.docxBuffer = injection.docxBuffer;
    existing.pdfBuffer = rendered.pdfBuffer;
    return existing;
  }

  async function executeSingleGeneration(context: GenerationContext): Promise<StoredPlan> {
    const storedUnit = units.get(context.unit_id);
    if (!storedUnit) throw new Error('Selected curriculum unit not found.');
    const lesson = storedUnit.unit.lessons.find((l) => l.lesson_id === context.lesson_id);
    if (!lesson) throw new Error('Selected lesson not found in curriculum unit.');
    const storedTemplate = templates.get(context.template_id);
    if (!storedTemplate) throw new Error('Selected template not found.');

    const payload = await generateStructuredLessonPlan(
      storedUnit.unit,
      lesson,
      storedTemplate.schema,
      context
    );

    const injection = await injectLessonPlanIntoDocx(
      storedTemplate.docxBuffer,
      storedTemplate.schema,
      payload
    );

    let pdfBuffer: Buffer = Buffer.alloc(0);
    let libreofficeUsed = false;
    let pdfAvailable = true;
    let pdfError: string | null = null;

    try {
      const rendered = await renderDocxToPdf(injection.docxBuffer, storedTemplate.schema, payload);
      pdfBuffer = rendered.pdfBuffer;
      libreofficeUsed = rendered.libreofficeUsed;
    } catch (err) {
      pdfAvailable = false;
      pdfError = err instanceof Error ? err.message : 'PDF conversion failed.';
    }

    const qaReport = await runFourPillarQA({
      lesson,
      schema: storedTemplate.schema,
      payload,
      injection,
      renderedPdfBuffer: pdfBuffer,
      libreofficeUsed,
      referencePdfBuffer: storedTemplate.refPdfBuffer,
    });

    const planId = `plan_${crypto.randomBytes(4).toString('hex')}`;
    const safeSlug = `EBDA_lesson_${lesson.lesson_number}_${planId}`;
    const record: GeneratedPlanRecord = {
      plan_id: planId,
      created_at: new Date().toISOString(),
      context,
      lesson_title: payload.lesson_title,
      payload,
      qa_report: qaReport,
      approved_fields: [],
      last_alignment_check: null,
      docx_filename: `${safeSlug}.docx`,
      pdf_filename: `${safeSlug}.pdf`,
      pdf_available: pdfAvailable,
      pdf_error: pdfError,
    };

    const storedPlan: StoredPlan = {
      record,
      docxBuffer: injection.docxBuffer,
      pdfBuffer,
    };
    plans.set(planId, storedPlan);
    return storedPlan;
  }

  // Generate Single Lesson Plan
  router.post('/generate', async (req, res) => {
    try {
      const context = req.body as GenerationContext;
      const storedPlan = await executeSingleGeneration(context);
      return res.json(storedPlan.record);
    } catch (err) {
      return res.status(500).json({
        error: err instanceof Error ? err.message : 'Lesson plan generation failed.',
      });
    }
  });

  // Batch Generation for Multiple/All Lessons -> ZIP export
  router.post('/generate-batch', async (req, res) => {
    try {
      const { lesson_ids, base_context } = req.body as {
        lesson_ids: string[];
        base_context: Omit<GenerationContext, 'lesson_id'>;
      };
      if (!Array.isArray(lesson_ids) || lesson_ids.length === 0) {
        return res.status(400).json({ error: 'Please select at least one lesson for batch generation.' });
      }

      const generatedRecords: GeneratedPlanRecord[] = [];
      const zip = new JSZip();

      for (const lessonId of lesson_ids) {
        const storedPlan = await executeSingleGeneration({
          ...base_context,
          lesson_id: lessonId,
        });
        generatedRecords.push(storedPlan.record);
        zip.file(storedPlan.record.docx_filename, storedPlan.docxBuffer);
        zip.file(storedPlan.record.pdf_filename, storedPlan.pdfBuffer);
        zip.file(
          `${storedPlan.record.plan_id}_qa_report.json`,
          JSON.stringify(storedPlan.record.qa_report, null, 2)
        );
      }

      const batchId = `batch_${crypto.randomBytes(4).toString('hex')}`;
      const zipBuffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
      const filename = `EBDA_LessonPlans_${batchId}.zip`;
      batches.set(batchId, {
        filename,
        zipBuffer,
        planIds: generatedRecords.map((r) => r.plan_id),
      });

      return res.json({
        batch_id: batchId,
        zip_filename: filename,
        plans: generatedRecords,
      });
    } catch (err) {
      return res.status(500).json({
        error: err instanceof Error ? err.message : 'Batch generation failed.',
      });
    }
  });

  // Direct Field-Level Editing (respects approved/locked fields, re-injects OOXML & re-runs QA)
  router.patch('/plans/:planId/fields', async (req, res) => {
    try {
      const existing = plans.get(req.params.planId);
      if (!existing) return res.status(404).json({ error: 'Generated plan not found.' });
      const { updates, normalize_timing } = req.body as {
        updates: Partial<LessonPlanPayload>;
        normalize_timing?: boolean;
      };
      if (!updates || typeof updates !== 'object') {
        return res.status(400).json({ error: 'Field updates object is required.' });
      }

      const lockedViolations = Object.keys(updates).filter((k) =>
        existing.record.approved_fields.includes(k)
      );
      if (lockedViolations.length > 0) {
        return res.status(409).json({
          error: `Cannot edit locked/approved field(s): ${lockedViolations.join(', ')}. Unlock them first.`,
        });
      }

      const nextPayload: LessonPlanPayload = {
        ...existing.record.payload,
        ...updates,
      };
      if (normalize_timing && Array.isArray(nextPayload.lesson_elements)) {
        nextPayload.lesson_elements = normalizeElementDurations(
          nextPayload.lesson_elements,
          nextPayload.total_duration_minutes
        );
      }

      await rebuildPlanArtifacts(existing, nextPayload);
      return res.json(existing.record);
    } catch (err) {
      return res.status(500).json({
        error: err instanceof Error ? err.message : 'Failed to update lesson plan fields.',
      });
    }
  });

  // Targeted AI Modes (Improve Outcomes, Improve Activities, Improve Assessment, Simplify Language, Validate Alignment)
  router.post('/plans/:planId/ai-action', async (req, res) => {
    try {
      const existing = plans.get(req.params.planId);
      if (!existing) return res.status(404).json({ error: 'Generated plan not found.' });

      const { mode, instruction } = req.body as {
        mode: Exclude<AiGenerationMode, 'complete' | 'regenerate_field'>;
        instruction?: string;
      };

      const storedUnit = units.get(existing.record.context.unit_id);
      const lesson = storedUnit?.unit.lessons.find((l) => l.lesson_id === existing.record.context.lesson_id);
      if (!lesson) return res.status(404).json({ error: 'Original source lesson is no longer loaded.' });

      const result = await runTargetedAiAction(
        lesson,
        existing.record.payload,
        mode,
        existing.record.approved_fields,
        instruction || ''
      );

      if (result.alignment) {
        existing.record.last_alignment_check = result.alignment;
        return res.json({
          plan: existing.record,
          alignment: result.alignment,
          skipped_locked_fields: [],
        });
      }

      if (result.updatedPayload) {
        await rebuildPlanArtifacts(existing, result.updatedPayload);
      }

      return res.json({
        plan: existing.record,
        skipped_locked_fields: result.skippedLockedFields,
      });
    } catch (err) {
      return res.status(500).json({
        error: err instanceof Error ? err.message : 'AI refinement action failed.',
      });
    }
  });

  // Partial Field Regeneration (preserves approved fields)
  router.post('/regenerate-fields', async (req, res) => {
    try {
      const { plan_id, field_keys, instruction } = req.body as {
        plan_id: string;
        field_keys: string[];
        instruction?: string;
      };
      const existing = plans.get(plan_id);
      if (!existing) return res.status(404).json({ error: 'Generated plan not found.' });
      if (!Array.isArray(field_keys) || field_keys.length === 0) {
        return res.status(400).json({ error: 'Select at least one field to regenerate.' });
      }

      const unlockedKeys = field_keys.filter((k) => !existing.record.approved_fields.includes(k));
      if (unlockedKeys.length === 0) {
        return res.status(400).json({
          error: 'All selected fields are currently locked/approved. Unlock them first before regenerating.',
        });
      }

      const storedUnit = units.get(existing.record.context.unit_id);
      const lesson = storedUnit?.unit.lessons.find((l) => l.lesson_id === existing.record.context.lesson_id);
      if (!lesson) {
        return res.status(404).json({ error: 'Original source lesson is no longer loaded.' });
      }

      const updatedPayload = await regenerateSelectedFields(
        lesson,
        existing.record.payload,
        unlockedKeys,
        instruction || ''
      );

      await rebuildPlanArtifacts(existing, updatedPayload);
      return res.json(existing.record);
    } catch (err) {
      return res.status(500).json({
        error: err instanceof Error ? err.message : 'Partial regeneration failed.',
      });
    }
  });

  router.post('/plans/:planId/approve-fields', (req, res) => {
    const existing = plans.get(req.params.planId);
    if (!existing) return res.status(404).json({ error: 'Plan not found.' });
    const { approved_fields, resolve_gate_id } = req.body as {
      approved_fields?: string[];
      resolve_gate_id?: string;
    };
    if (Array.isArray(approved_fields)) {
      existing.record.approved_fields = approved_fields;
    }
    if (resolve_gate_id) {
      existing.record.qa_report.approval_gates = existing.record.qa_report.approval_gates.map((g) =>
        g.gate_id === resolve_gate_id ? { ...g, resolved: true } : g
      );
    }
    return res.json(existing.record);
  });

  // Download endpoints (.docx, .pdf, batch .zip)
  router.get('/download/batch/:batchId', (req, res) => {
    const batch = batches.get(req.params.batchId);
    if (!batch) return res.status(404).json({ error: 'Batch archive not found.' });
    res.setHeader('Content-Type', 'application/zip');
    res.setHeader('Content-Disposition', `attachment; filename="${batch.filename}"`);
    return res.send(batch.zipBuffer);
  });

  router.get('/download/:planId/:format', (req, res) => {
    const existing = plans.get(req.params.planId);
    if (!existing) return res.status(404).json({ error: 'Plan not found.' });
    const fmt = req.params.format.toLowerCase();

    if (fmt === 'docx') {
      res.setHeader(
        'Content-Type',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      );
      res.setHeader('Content-Disposition', `attachment; filename="${existing.record.docx_filename}"`);
      return res.send(existing.docxBuffer);
    }
    if (fmt === 'pdf') {
      if (existing.record.pdf_available === false || existing.pdfBuffer.length === 0) {
        return res.status(503).json({
          error: existing.record.pdf_error || 'PDF conversion failed; please download the editable Word (.docx) file.',
        });
      }
      res.setHeader('Content-Type', 'application/pdf');
      res.setHeader(
        'Content-Disposition',
        `${req.query.inline === '1' ? 'inline' : 'attachment'}; filename="${existing.record.pdf_filename}"`
      );
      return res.send(existing.pdfBuffer);
    }
    return res.status(400).json({ error: 'Unsupported format. Use docx or pdf.' });
  });

  return router;
}

export function createExpressApp() {
  const app = express();
  app.use(express.json({ limit: '15mb' }));
  app.use('/api', createApiRouter());
  return app;
}
