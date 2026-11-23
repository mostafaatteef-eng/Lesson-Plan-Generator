import assert from 'node:assert/strict';
import test from 'node:test';
import JSZip from 'jszip';
import { PDFDocument } from 'pdf-lib';
import {
  exportLessonPdf,
  ingestCurriculumFile,
  updateUnitBoundaries,
} from '../server/curriculumEngine';
import {
  applyCheckboxSelections,
  injectLessonPlanIntoDocx,
  parseTemplateDocx,
} from '../server/templateEngine';
import { normalizeElementDurations } from '../server/aiEngine';
import {
  compareAgainstReferencePdf,
  detectVagueVerbs,
  renderDocxToPdf,
  runFourPillarQA,
} from '../server/renderQaEngine';
import {
  buildSampleAtsMuTemplateDocx,
  buildSampleReferencePdf,
  getSampleCurriculumText,
} from '../server/sampleGenerator';
import { createExpressApp } from '../server/app';
import type { LessonPlanPayload } from '../server/types';

function makeDeterministicPayload(totalMinutes = 45): LessonPlanPayload {
  return {
    program_or_course: 'أنظمة التحكم المنطقي المبرمج (PLC)',
    teacher_name: 'م. أحمد محمود عبد الرحمن',
    job_title: 'معلم أول أتمتة وتحكم صناعي',
    academic_year: '٢٠٢٥-٢٠٢٦',
    school_name: 'مدرسة التكنولوجيا التطبيقية المتقدمة',
    grade_level: 'الصف الثاني الثانوي التكنولوجي',
    class_sections: ['2 A', '2B'],
    unit_number: 'الوحدة الثالثة',
    unit_name: 'أنظمة التحكم المنطقي المبرمج (PLC)',
    branch: 'الأتمتة الصناعية والتحكم الآلي',
    knowledge_code: 'TPK04',
    lesson_title: 'مكونات وحدة التحكم المنطقي المبرمج (PLC) وبنيتها الوظيفية',
    learning_outcomes: [
      'يحدد المكونات الخمسة الرئيسية لوحدة التحكم المنطقي المبرمج PLC.',
      'يقارن بين وظيفة وحدة الإدخال الرقمية ووحدة الإخراج في نظام PLC.',
      'يشرح مراحل دورة المسح (Scan Cycle) بالترتيب الصحيح.',
      'يرسم مخططاً صندوقياً يوضح مسار الإشارة خلال دورة المسح.',
    ],
    lesson_elements: [
      { index: 1, title: 'مفهوم وحدة PLC وبيئة عملها الصناعية', duration_minutes: 8, time_formatted: '08:00' },
      { index: 2, title: 'وحدة المعالجة المركزية CPU والذاكرة', duration_minutes: 10, time_formatted: '10:00' },
      { index: 3, title: 'وحدات الإدخال والإخراج والعوازل الضوئية', duration_minutes: 12, time_formatted: '12:00' },
      { index: 4, title: 'تطبيق عملي على لوحة Siemens S7-1200', duration_minutes: 10, time_formatted: '10:00' },
      { index: 5, title: 'التقويم الختامي ومراجعة المفاهيم', duration_minutes: 5, time_formatted: '05:00' },
    ],
    selected_strategies: ['مناقشة وحوار', 'تعلم تعاوني', 'حل مشكلات'],
    selected_resources: ['دليل الطالب', 'عرض تقديمي'],
    assessment_group_1: 'قارن بين وظيفة وحدة الإدخال الرقمية ووحدة الإخراج في نظام PLC.',
    assessment_group_2: 'اشرح مراحل دورة المسح (Scan Cycle) بالترتيب الصحيح.',
    assessment_group_3: 'وضح أهمية العازل الضوئي (Optocoupler) في حماية وحدة المعالجة المركزية.',
    presentation_class: '2 A',
    location: 'معمل الـ PLC',
    lesson_date: '2026-03-10',
    total_duration_minutes: totalMinutes,
    warm_up: 'عرض نموذج لخط إنتاج آلي وطرح سؤال حول كيفية ربط الحساسات بالمحركات الصناعية.',
    element_1_strategy: 'مناقشة وحوار',
    element_1_time: '08:00',
    element_1_summary: 'عرض مكونات الـ PLC الخمسة الرئيسية ووظيفة وحدة التغذية 24V DC.',
    activity_1: {
      activity_number: 1,
      duration_minutes: 10,
      time_formatted: '10:00',
      pattern: 'جماعي',
      activity_type: 'دراسة حالة',
      purpose: 'فحص لوحة Siemens S7-1200 وتحديد أطراف الإدخال والإخراج.',
      teacher_procedures: 'يوزع المعلم اللوحات التدريبية ويتابع التزام المجموعات بقواعد السلامة.',
      student_procedures: 'يحدد الطلاب أطراف I0.0 - I0.7 وأطراف Q0.0 - Q0.5 ومؤشرات RUN/STOP.',
      student_note: 'تحقق من مؤشر الطاقة 24V DC قبل تسجيل الملاحظات.',
    },
    element_2_strategy: 'تعلم تعاوني',
    element_2_time: '10:00',
    element_2_summary: 'تحليل دورة المسح Scan Cycle ووظيفة العوازل الضوئية Optocouplers.',
    activity_2: {
      activity_number: 2,
      duration_minutes: 10,
      time_formatted: '10:00',
      pattern: 'فردي',
      activity_type: 'رسم / تصميم',
      purpose: 'رسم مخطط صندوقي يوضح مسار الإشارة خلال دورة المسح.',
      teacher_procedures: 'يراجع المعلم المخططات ويقدم تغذية راجعة فورية.',
      student_procedures: 'يرسم الطالب مسار الإشارة من المدخل عبر CPU إلى المخرج.',
      student_note: 'اكتب أسماء الوحدات بدقة باللغتين العربية والإنجليزية.',
    },
    rubric_group_1_header: 'معايير المعارف النظرية',
    rubric_group_1_items: [
      'يحدد وظيفة CPU بدقة',
      'يميز بين ذاكرة ROM و RAM',
      'يوضح دور العازل الضوئي',
      'يرتب مراحل دورة المسح',
      'يذكر جهد التغذية 24V DC',
      'يستخدم المصطلحات الفنية بدقة',
    ],
    rubric_group_2_header: 'معايير الأداء العملي',
    rubric_group_2_items: [
      'يحدد أطراف I0.0 - I0.7',
      'يحدد أطراف Q0.0 - Q0.5',
      'يميز مؤشرات RUN/STOP/ERROR',
      'يرسم المخطط الصندوقي بوضوح',
      'يلتزم بإجراءات السلامة بالمعمل',
      'يتعاون بفعالية داخل المجموعة',
    ],
    traceability: [
      {
        field_key: 'learning_outcomes',
        field_label: 'نواتج التعلم',
        supporting_excerpt: 'تتكون منظومة الـ PLC الأساسية من خمس وحدات رئيسية متكاملة',
        source_pages: [1],
        verified_in_source: true,
      },
      {
        field_key: 'activity_1',
        field_label: 'نشاط ( ١ )',
        supporting_excerpt: 'يفحص الطلاب لوحة تدريبية لوحدة Siemens S7-1200 ويحددون مواقع أطراف الإدخال',
        source_pages: [1],
        verified_in_source: true,
      },
      {
        field_key: 'assessment_group_1',
        field_label: 'التقييم — مجموعة ( ١ )',
        supporting_excerpt: 'قارن بين وظيفة وحدة الإدخال الرقمية ووحدة الإخراج في نظام PLC',
        source_pages: [1],
        verified_in_source: true,
      },
    ],
    missing_curriculum_notes: [],
  };
}

test('1. Multi-lesson Arabic/English boundary extraction, boundary correction & per-lesson PDF export', async () => {
  const bilingualUnit =
    getSampleCurriculumText() +
    '\n--- PAGE 4 ---\nLesson 4: Industrial Safety Interlocks\nEmergency stop buttons must be wired as normally closed (NC) contacts so a broken wire fails safely.\n';

  const { unit } = await ingestCurriculumFile(Buffer.from(bilingualUnit, 'utf8'), 'bilingual_plc.txt');
  assert.equal(unit.lessons.length, 4);
  assert.equal(unit.lessons[0].start_page, 1);
  assert.equal(unit.lessons[3].start_page, 4);

  const revised = updateUnitBoundaries(unit, [
    {
      lesson_id: unit.lessons[0].lesson_id,
      title: unit.lessons[0].title,
      start_page: 1,
      end_page: 1,
      approved: true,
    },
  ]);
  assert.equal(revised.lessons.length, 1);
  assert.equal(revised.lessons[0].approved, true);

  const lessonPdf = await exportLessonPdf(unit, unit.lessons[0]);
  assert.equal(lessonPdf.subarray(0, 5).toString('ascii'), '%PDF-');
  const loaded = await PDFDocument.load(lessonPdf);
  assert.equal(loaded.getPageCount(), 1);
});

test('2. DOCX 6-page ATS-MU schema extraction & XML-preserving injection (w:bidi, w:tcW, ☐ -> ☑, quirked labels)', async () => {
  const templateDocx = await buildSampleAtsMuTemplateDocx();
  const refPdf = await buildSampleReferencePdf();
  const schema = await parseTemplateDocx(
    templateDocx,
    'ATS-MU_6Page_Arabic_Template.docx',
    refPdf,
    'ATS-MU_Reference.pdf'
  );

  assert.equal(schema.is_rtl, true);
  assert.equal(schema.page_count_expected, 6);
  assert.ok(schema.tables.length >= 6);
  assert.ok(schema.fields.some((f) => f.field_type === 'checkbox_group'));
  assert.ok(schema.fields.some((f) => f.field_type === 'time_slot'));

  const payload = makeDeterministicPayload(45);
  const injection = await injectLessonPlanIntoDocx(templateDocx, schema, payload);

  assert.equal(injection.xmlChecks.tablesBefore, injection.xmlChecks.tablesAfter);
  assert.equal(injection.xmlChecks.cellsBefore, injection.xmlChecks.cellsAfter);
  assert.equal(injection.xmlChecks.widthsUnchanged, true);
  assert.equal(injection.xmlChecks.bidiPreserved, true);
  assert.ok(injection.checkboxesChecked >= 5);

  const outZip = await JSZip.loadAsync(injection.docxBuffer);
  const outXml = await outZip.file('word/document.xml')!.async('string');
  assert.ok(outXml.includes('w:bidi'));
  assert.ok(outXml.includes('☑ مناقشة وحوار'));
  assert.ok(outXml.includes('☑ تعلم تعاوني'));
  assert.ok(outXml.includes('☐ المحاضرة'));
  // Original template label quirk MUST remain unaltered
  assert.ok(outXml.includes('الغرض النشاط'));
  // Footer copyright MUST remain unaltered
  const footerXml = await outZip.file('word/footer1.xml')!.async('string');
  assert.ok(footerXml.includes('© All Copy rights reserved to ATS-MU'));

  const toggled = applyCheckboxSelections('☐ المحاضرة ☐ لعب ادوار ☐ عصف ذهني', ['لعب أدوار']);
  assert.ok(toggled.includes('☑ لعب ادوار'));
});

test('3. Strict time-sum validation & measurable Bloom verb QA checks', async () => {
  const payload = makeDeterministicPayload(45);
  payload.lesson_elements[0].duration_minutes = 25; // deliberately break sum
  const normalized = normalizeElementDurations(payload.lesson_elements, 45);
  const sum = normalized.reduce((acc, el) => acc + el.duration_minutes, 0);
  assert.equal(sum, 45);

  assert.deepEqual(detectVagueVerbs(payload.learning_outcomes), []);
  const bad = detectVagueVerbs(['يفهم الطالب مكونات الـ PLC', 'Students understand PLC memory']);
  assert.equal(bad.length, 2);
});

test('4. Visual diff extra-page overflow detection & 4-pillar QA report', async () => {
  const templateDocx = await buildSampleAtsMuTemplateDocx();
  const refPdf = await buildSampleReferencePdf();
  const schema = await parseTemplateDocx(templateDocx, 'ATS-MU.docx', refPdf, 'Ref.pdf');

  // Create a 7-page PDF (1 extra overflow page beyond the 6-page reference)
  const overflowPdf = await PDFDocument.create();
  for (let i = 0; i < 7; i++) {
    overflowPdf.addPage([595.28, 841.89]);
  }
  const overflowBuf = Buffer.from(await overflowPdf.save());

  const diff = await compareAgainstReferencePdf(overflowBuf, schema, [], refPdf);
  assert.equal(diff.pageCountExpected, 6);
  assert.equal(diff.pageCountRendered, 7);
  assert.equal(diff.visualDiff[6].overflow_detected, true);
  assert.equal(diff.visualDiff[6].status, 'fail');

  // Now run full 4-pillar QA on a clean 6-page render
  const { unit } = await ingestCurriculumFile(Buffer.from(getSampleCurriculumText(), 'utf8'), 'unit3.txt');
  const payload = makeDeterministicPayload(45);
  const injection = await injectLessonPlanIntoDocx(templateDocx, schema, payload);
  const rendered = await renderDocxToPdf(injection.docxBuffer, schema, payload);
  const qa = await runFourPillarQA({
    lesson: unit.lessons[0],
    schema,
    payload,
    injection,
    renderedPdfBuffer: rendered.pdfBuffer,
    libreofficeUsed: rendered.libreofficeUsed,
    referencePdfBuffer: refPdf,
  });
  assert.equal(qa.time_sum_valid, true);
  assert.equal(qa.page_count_rendered, 6);
  assert.equal(qa.page_count_expected, 6);
  assert.equal(qa.overall_status, 'pass');
});

test('5. End-to-end Express API sample load, upload, boundary update & lesson PDF export flow', async () => {
  const app = createExpressApp();
  const server = app.listen(0);
  const addr = server.address();
  const port = typeof addr === 'object' && addr ? addr.port : 0;
  const baseUrl = `http://127.0.0.1:${port}`;

  try {
    const sampleRes = await fetch(`${baseUrl}/api/sample/load`, { method: 'POST' });
    assert.equal(sampleRes.status, 200);
    const sampleData = await sampleRes.json();
    assert.equal(sampleData.unit.lessons.length, 3);
    assert.equal(sampleData.template.page_count_expected, 6);
    assert.equal(sampleData.template.is_rtl, true);

    const lessonId = sampleData.unit.lessons[0].lesson_id;
    const unitId = sampleData.unit.unit_id;

    const boundRes = await fetch(`${baseUrl}/api/curriculum/${unitId}/boundaries`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        lessons: sampleData.unit.lessons.map((l: { lesson_id: string; title: string; start_page: number; end_page: number }) => ({
          lesson_id: l.lesson_id,
          title: l.title,
          start_page: l.start_page,
          end_page: l.end_page,
          approved: true,
        })),
      }),
    });
    assert.equal(boundRes.status, 200);

    const pdfRes = await fetch(`${baseUrl}/api/curriculum/${unitId}/lesson/${lessonId}/pdf`);
    assert.equal(pdfRes.status, 200);
    const pdfBuf = Buffer.from(await pdfRes.arrayBuffer());
    assert.equal(pdfBuf.subarray(0, 5).toString('ascii'), '%PDF-');

    const refRes = await fetch(`${baseUrl}/api/template/${sampleData.template.template_id}/reference-pdf`);
    assert.equal(refRes.status, 200);
    const refBuf = Buffer.from(await refRes.arrayBuffer());
    assert.equal(refBuf.subarray(0, 5).toString('ascii'), '%PDF-');
  } finally {
    server.close();
  }
});

test('6. EBDA Settings defaults, logo validation, extraction metadata & DELETE curriculum/template routes', async () => {
  const app = createExpressApp();
  const server = app.listen(0);
  const addr = server.address();
  const port = typeof addr === 'object' && addr ? addr.port : 0;
  const baseUrl = `http://127.0.0.1:${port}`;

  try {
    // 1. Default EBDA Badr settings
    const settingsRes = await fetch(`${baseUrl}/api/settings`);
    assert.equal(settingsRes.status, 200);
    const settings = await settingsRes.json();
    assert.equal(settings.institution_en, 'EBDA National Schools of Applied Technology');
    assert.equal(settings.school_name_en, 'EBDA National School of Applied Technology – Badr');
    assert.equal(settings.specialization_en, 'Artificial Intelligence & Data Analysis');

    // 2. Reject non-image logo payload
    const badLogoRes = await fetch(`${baseUrl}/api/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ logo_data_url: 'javascript:alert(1)' }),
    });
    assert.equal(badLogoRes.status, 400);

    // 3. Accept valid official PNG logo data URL & custom teacher default
    const tinyPng = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';
    const goodLogoRes = await fetch(`${baseUrl}/api/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        logo_data_url: tinyPng,
        logo_filename: 'ebda_official_logo.png',
        default_teacher_name: 'م. سارة أحمد',
      }),
    });
    assert.equal(goodLogoRes.status, 200);
    const updatedSettings = await goodLogoRes.json();
    assert.equal(updatedSettings.logo_filename, 'ebda_official_logo.png');
    assert.equal(updatedSettings.default_teacher_name, 'م. سارة أحمد');

    // 4. Verify extraction_quality, file_size_bytes & user_modified metadata
    const sampleRes = await fetch(`${baseUrl}/api/sample/load`, { method: 'POST' });
    assert.equal(sampleRes.status, 200);
    const sampleData = await sampleRes.json();
    assert.ok(sampleData.unit.file_size_bytes > 0);
    assert.ok(['high', 'medium', 'needs_review'].includes(sampleData.unit.extraction_quality));

    const boundRes = await fetch(`${baseUrl}/api/curriculum/${sampleData.unit.unit_id}/boundaries`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        lessons: sampleData.unit.lessons.map(
          (l: { lesson_id: string; title: string; start_page: number; end_page: number }, idx: number) => ({
            lesson_id: l.lesson_id,
            title: idx === 0 ? `${l.title} (معدل)` : l.title,
            start_page: l.start_page,
            end_page: l.end_page,
            approved: true,
          })
        ),
      }),
    });
    assert.equal(boundRes.status, 200);
    const revisedUnit = await boundRes.json();
    assert.equal(revisedUnit.lessons[0].user_modified, true);
    assert.equal(revisedUnit.lessons[1].user_modified, false);

    // 5. Verify PATCH nonexistent plan returns 404
    const patch404 = await fetch(`${baseUrl}/api/plans/plan_missing/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ updates: { warm_up: 'test' } }),
    });
    assert.equal(patch404.status, 404);

    // 6. Verify DELETE curriculum & template routes
    const delUnit = await fetch(`${baseUrl}/api/curriculum/${sampleData.unit.unit_id}`, {
      method: 'DELETE',
    });
    assert.equal(delUnit.status, 200);
    const delUnitAgain = await fetch(`${baseUrl}/api/curriculum/${sampleData.unit.unit_id}`, {
      method: 'DELETE',
    });
    assert.equal(delUnitAgain.status, 404);

    const delTpl = await fetch(`${baseUrl}/api/template/${sampleData.template.template_id}`, {
      method: 'DELETE',
    });
    assert.equal(delTpl.status, 200);
    const delTplAgain = await fetch(`${baseUrl}/api/template/${sampleData.template.template_id}`, {
      method: 'DELETE',
    });
    assert.equal(delTplAgain.status, 404);
  } finally {
    server.close();
  }
});

test('7. Independent multipart upload, Reference PDF attach/replace/delete & invalid PDF rejection', async () => {
  const app = createExpressApp();
  const server = app.listen(0);
  const addr = server.address();
  const port = typeof addr === 'object' && addr ? addr.port : 0;
  const baseUrl = `http://127.0.0.1:${port}`;

  try {
    // 1. Multipart upload curriculum file
    const currForm = new FormData();
    currForm.append(
      'file',
      new Blob([getSampleCurriculumText()], { type: 'text/plain' }),
      'unit3_plc.txt'
    );
    const currRes = await fetch(`${baseUrl}/api/curriculum/upload`, {
      method: 'POST',
      body: currForm,
    });
    assert.equal(currRes.status, 200);
    const unit = await currRes.json();
    assert.equal(unit.lessons.length, 3);

    // 2. Multipart upload DOCX template without Reference PDF first
    const templateDocx = await buildSampleAtsMuTemplateDocx();
    const tplForm = new FormData();
    tplForm.append(
      'docx',
      new Blob([new Uint8Array(templateDocx)], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      }),
      'ATS-MU_Template.docx'
    );
    const tplRes = await fetch(`${baseUrl}/api/template/upload`, {
      method: 'POST',
      body: tplForm,
    });
    assert.equal(tplRes.status, 200);
    const tpl = await tplRes.json();
    assert.equal(tpl.has_reference_pdf, false);
    assert.equal(tpl.page_count_expected, 6);

    // 3. Reject corrupted Reference PDF
    const badRefForm = new FormData();
    badRefForm.append(
      'reference_pdf',
      new Blob(['not a real pdf'], { type: 'application/pdf' }),
      'broken.pdf'
    );
    const badRefRes = await fetch(`${baseUrl}/api/template/${tpl.template_id}/reference-pdf`, {
      method: 'POST',
      body: badRefForm,
    });
    assert.equal(badRefRes.status, 400);

    // 4. Attach valid 6-page Reference PDF independently after DOCX upload
    const refPdf = await buildSampleReferencePdf();
    const refForm = new FormData();
    refForm.append(
      'reference_pdf',
      new Blob([new Uint8Array(refPdf)], { type: 'application/pdf' }),
      'ATS-MU_Ref.pdf'
    );
    const refRes = await fetch(`${baseUrl}/api/template/${tpl.template_id}/reference-pdf`, {
      method: 'POST',
      body: refForm,
    });
    assert.equal(refRes.status, 200);
    const updatedTpl = await refRes.json();
    assert.equal(updatedTpl.has_reference_pdf, true);
    assert.equal(updatedTpl.reference_pdf_pages, 6);

    // 5. Remove Reference PDF independently without losing the Word template
    const delRefRes = await fetch(`${baseUrl}/api/template/${tpl.template_id}/reference-pdf`, {
      method: 'DELETE',
    });
    assert.equal(delRefRes.status, 200);
    const clearedTpl = await delRefRes.json();
    assert.equal(clearedTpl.has_reference_pdf, false);
  } finally {
    server.close();
  }
});



// The pure helper is covered from source without importing the React tree.
test('subject metadata is selected before institution defaults', async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const helper = source.slice(source.indexOf('export function subjectMetadata'), source.indexOf('export default function App'));
  const { transformSync } = await import('esbuild');
  const js = transformSync(helper.replace('export function', 'function'), {loader:'ts',target:'es2022'}).code;
  const metadata = new Function(`${js}; return subjectMetadata;`)();
  const settings = {specialization_ar:'الذكاء الاصطناعي وتحليل البيانات',default_branch:'AI branch',default_job_title:'AI teacher',default_location:'AI lab'};
  for (const subject of ['Physics','الفيزياء','English for AI']) {
    assert.deepEqual(metadata(subject, settings), {branch:subject,job_title:`معلم ${subject}`,location:'يحدده المعلم'});
  }
  assert.deepEqual(metadata(settings.specialization_ar,settings),{branch:'AI branch',job_title:'AI teacher',location:'AI lab'});
  assert.match(source,/branch: subjectMetadata\(advanced.subject, settings\).branch/);
  assert.match(source,/location: subjectMetadata\(advanced.subject, settings\).location/);
});
