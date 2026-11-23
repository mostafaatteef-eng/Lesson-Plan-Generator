// Arabic/English UI strings. The interface language is a runtime toggle;
// content language of uploaded documents is independent (dir="auto" fields).
export type Lang = 'ar' | 'en';

export interface Strings {
  tagline: string;
  langToggle: string;
  builtinTemplateName: string;
  builtinTemplateReady: string;
  generateSingle: string;
  generateMulti: (n: number) => string;
  readinessBoth: string;
  readinessCurriculum: string;
  readinessTemplate: string;
  readinessLessons: string;
  // Upload cards
  curriculumTitle: string;
  curriculumHelper: string;
  templateTitle: string;
  templateHelper: string;
  refPdfTitle: string;
  refPdfHelper: string;
  required: string;
  optional: string;
  analyzing: string;
  dropOrBrowse: string;
  replace: string;
  remove: string;
  removeAria: (title: string) => string;
  errUnsupported: (ext: string, allowed: string) => string;
  errEmpty: string;
  errTooBig: string;
  errCurriculumUpload: string;
  errTemplateUpload: string;
  errRefPdfUpload: string;
  errCurriculumRemove: string;
  errTemplateRemove: string;
  errRefPdfRemove: string;
  errBoundary: string;
  errGenerate: string;
  errGenerateBatch: string;
  errUnexpected: string;
  errPayloadTooLarge: string;
  errQaMissing: string;
  errNetwork: string;
  noLessonsGenerated: string;
  metaLessons: (n: number) => string;
  metaPages: (n: number) => string;
  metaBaseline: (n: number) => string;
  metaAttached: string;
  metaReadyToCompare: string;
  rtlLabel: string;
  ltrLabel: string;
  // Lesson selector
  selectLesson: string;
  selectedCount: (sel: number, total: number) => string;
  selectAll: (n: number) => string;
  selectFirstOnly: string;
  pagesRange: (a: number, b: number) => string;
  wordsCount: (n: number) => string;
  adjusted: string;
  boundaryUncertain: string;
  fixRange: string;
  edit: string;
  lessonTitleLabel: string;
  startPage: (max: number) => string;
  endPage: (max: number) => string;
  cancel: string;
  saving: string;
  confirmRange: string;
  defaultLessonTitle: string;
  advancedSettings: string;
  minutesShort: (n: number) => string;
  autoLanguage: string;
  arabic: string;
  english: string;
  teacherName: string;
  classSection: string;
  lessonDate: string;
  grade: string;
  subject: string;
  durationLabel: string;
  outputLanguage: string;
  matchTemplateLang: string;
  // Generation progress
  stages: string[];
  processing: string;
  lessonsCount: (n: number) => string;
  generationFailed: string;
  tryAgain: string;
  // Results
  qaPass: string;
  qaWarning: string;
  qaFail: string;
  qualityLabel: string;
  planReady: string;
  planNotReady: string;
  failuresTitle: string;
  downloadFailed: string;
  morePlans: (n: number) => string;
  lessonsGenerated: (n: number) => string;
  minutesValue: (sum: number, target: number) => string;
  pagesValue: (rendered: number, expected: number) => string;
  downloadDocx: string;
  downloadPdf: string;
  downloadAllZip: string;
  pdfUnavailable: string;
  pdfFailed: string;
  wordLink: string;
  pdfLink: string;
  notesTitle: string;
  warnPdfFallback: string;
  warnPdfFailed: string;
  warnPageCount: (rendered: number, expected: number) => string;
  warnOverflow: (fields: string) => string;
}

export const STRINGS: Record<Lang, Strings> = {
  en: {
    tagline: 'Smart Lesson Planning, Made Simple.',
    langToggle: 'العربية',
    builtinTemplateName: 'Official template (built in)',
    builtinTemplateReady:
      'The official template is built in. Upload a file only to use a different template.',
    generateSingle: 'Generate Lesson Plan',
    generateMulti: (n) => `Generate ${n} Lesson Plans`,
    readinessBoth: 'Upload a curriculum file and a Word template to continue.',
    readinessCurriculum: 'Upload a curriculum file to detect lessons.',
    readinessTemplate: 'Upload a Word (.docx) lesson plan template to enable generation.',
    readinessLessons: 'Select at least one lesson to generate.',
    curriculumTitle: 'Curriculum / Lesson File',
    curriculumHelper: 'Educational material used as the sole lesson source.',
    templateTitle: 'Lesson Plan Template',
    templateHelper: 'Editable Word template whose layout will be preserved.',
    refPdfTitle: 'Reference PDF',
    refPdfHelper: 'Approved layout baseline to verify page count and fit.',
    required: 'Required',
    optional: 'Optional',
    analyzing: 'Analyzing document…',
    dropOrBrowse: 'Drop file or click to browse',
    replace: 'Replace',
    remove: 'Remove',
    removeAria: (title) => `Remove ${title}`,
    errUnsupported: (ext, allowed) => `Unsupported file type ".${ext}". Allowed: ${allowed}.`,
    errEmpty: 'The selected file is empty. Please choose a valid document.',
    errTooBig: 'File exceeds the 35 MB maximum upload limit.',
    errCurriculumUpload: 'Could not extract text from the uploaded curriculum.',
    errTemplateUpload: 'Could not parse the uploaded Word template.',
    errRefPdfUpload: 'Could not attach Reference PDF.',
    errCurriculumRemove: 'Could not remove the curriculum on the server.',
    errTemplateRemove: 'Could not remove the template on the server.',
    errRefPdfRemove: 'Could not remove the Reference PDF on the server.',
    errBoundary: 'Failed to update lesson range.',
    errGenerate: 'Lesson plan generation failed.',
    errGenerateBatch: 'Batch lesson plan generation failed.',
    errUnexpected: 'An unexpected error occurred during generation.',
    errPayloadTooLarge:
      'The uploaded files are too large for the server. Try fewer lessons or smaller files.',
    errQaMissing:
      'The server returned this lesson without its quality report, so it is not shown. Try again.',
    errNetwork: 'Could not reach the server. Check your internet connection and try again.',
    noLessonsGenerated: 'No lesson could be generated. Review the errors above and try again.',
    metaLessons: (n) => (n === 1 ? '1 lesson' : `${n} lessons`),
    metaPages: (n) => `${n}p`,
    metaBaseline: (n) => `${n}p baseline`,
    metaAttached: 'Attached',
    metaReadyToCompare: 'Ready to compare',
    rtlLabel: 'RTL',
    ltrLabel: 'LTR',
    selectLesson: 'Select Lesson',
    selectedCount: (sel, total) => `${sel} of ${total} selected`,
    selectAll: (n) => `Select all (${n})`,
    selectFirstOnly: 'Select first only',
    pagesRange: (a, b) => `Pages ${a}–${b}`,
    wordsCount: (n) => `${n} words`,
    adjusted: 'Adjusted',
    boundaryUncertain: 'Boundary uncertain — confirm page range.',
    fixRange: 'Fix range',
    edit: 'Edit',
    lessonTitleLabel: 'Lesson title',
    startPage: (max) => `Start page (1–${max})`,
    endPage: (max) => `End page (1–${max})`,
    cancel: 'Cancel',
    saving: 'Saving…',
    confirmRange: 'Confirm range',
    defaultLessonTitle: 'Lesson',
    advancedSettings: 'Advanced settings',
    minutesShort: (n) => `${n} min`,
    autoLanguage: 'Auto language',
    arabic: 'Arabic',
    english: 'English',
    teacherName: 'Teacher name',
    classSection: 'Class / section',
    lessonDate: 'Lesson date',
    grade: 'Grade',
    subject: 'Subject',
    durationLabel: 'Lesson duration (minutes)',
    outputLanguage: 'Output language',
    matchTemplateLang: 'Match template language',
    stages: [
      'Reading curriculum',
      'Identifying lessons',
      'Generating lesson plan',
      'Formatting Word document',
      'Converting to PDF',
      'Validating output',
    ],
    processing: 'Processing',
    lessonsCount: (n) => (n === 1 ? '1 lesson' : `${n} lessons`),
    generationFailed: 'Generation could not be completed',
    tryAgain: 'Try Again',
    qaPass: 'Passed',
    qaWarning: 'Needs Review',
    qaFail: 'Failed',
    qualityLabel: 'Quality:',
    planReady: 'Your Lesson Plan Is Ready',
    planNotReady: 'Plan failed quality checks',
    failuresTitle: 'Lessons that could not be generated',
    downloadFailed: 'Download failed - try again or regenerate the plan.',
    morePlans: (n) => `(+${n} more)`,
    lessonsGenerated: (n) => (n === 1 ? '1 lesson generated' : `${n} lessons generated`),
    minutesValue: (sum, target) => `${sum}/${target} min`,
    pagesValue: (rendered, expected) => `${rendered}/${expected} pages`,
    downloadDocx: 'Download Word (.docx)',
    downloadPdf: 'Download PDF (.pdf)',
    downloadAllZip: 'Download All (.zip)',
    pdfUnavailable: 'PDF Unavailable',
    pdfFailed: 'PDF failed',
    wordLink: 'Word (.docx)',
    pdfLink: 'PDF (.pdf)',
    notesTitle: 'Formatting & Validation Notes',
    warnPdfFallback:
      'PDF generated with the built-in fallback renderer because LibreOffice is unavailable in this environment. Open the Word (.docx) file for full Arabic RTL typography and original template styling.',
    warnPdfFailed:
      'PDF conversion failed; the editable Word (.docx) file remains available for download.',
    warnPageCount: (rendered, expected) =>
      `Rendered page count (${rendered}) differs from template baseline (${expected}).`,
    warnOverflow: (fields) => `Potential cell overflow in: ${fields}.`,
  },
  ar: {
    tagline: 'تخطيط الدروس الذكي، ببساطة.',
    langToggle: 'English',
    builtinTemplateName: 'القالب الرسمي (مدمج)',
    builtinTemplateReady: 'القالب الرسمي مدمج تلقائيًا. ارفع ملفًا فقط لو كنت تريد استخدام قالب مختلف.',
    generateSingle: 'توليد خطة الدرس',
    generateMulti: (n) => `توليد ${n} خطط دروس`,
    readinessBoth: 'ارفع ملف المنهج وقالب Word للمتابعة.',
    readinessCurriculum: 'ارفع ملف المنهج لاكتشاف الدروس.',
    readinessTemplate: 'ارفع قالب خطة الدرس (Word) لتفعيل التوليد.',
    readinessLessons: 'اختر درسًا واحدًا على الأقل للتوليد.',
    curriculumTitle: 'ملف المنهج / الدرس',
    curriculumHelper: 'المادة التعليمية المستخدمة كمصدر وحيد لمحتوى الدرس.',
    templateTitle: 'قالب خطة الدرس',
    templateHelper: 'قالب Word قابل للتعديل سيتم الحفاظ على تنسيقه.',
    refPdfTitle: 'ملف PDF مرجعي',
    refPdfHelper: 'نموذج معتمد للتحقق من عدد الصفحات والملاءمة.',
    required: 'مطلوب',
    optional: 'اختياري',
    analyzing: 'جارٍ تحليل المستند…',
    dropOrBrowse: 'أسقط الملف هنا أو اضغط للاختيار',
    replace: 'استبدال',
    remove: 'إزالة',
    removeAria: (title) => `إزالة ${title}`,
    errUnsupported: (ext, allowed) => `نوع الملف ".${ext}" غير مدعوم. الأنواع المسموحة: ${allowed}.`,
    errEmpty: 'الملف المحدد فارغ. اختر مستندًا صالحًا.',
    errTooBig: 'الملف يتجاوز الحد الأقصى المسموح به (35 ميجابايت).',
    errCurriculumUpload: 'تعذّر استخراج النص من ملف المنهج المرفوع.',
    errTemplateUpload: 'تعذّرت قراءة قالب Word المرفوع.',
    errRefPdfUpload: 'تعذّر إرفاق ملف PDF المرجعي.',
    errCurriculumRemove: 'تعذّر حذف المنهج من الخادم.',
    errTemplateRemove: 'تعذّر حذف القالب من الخادم.',
    errRefPdfRemove: 'تعذّر حذف ملف PDF المرجعي من الخادم.',
    errBoundary: 'تعذّر تحديث نطاق الدرس.',
    errGenerate: 'فشل توليد خطة الدرس.',
    errGenerateBatch: 'فشل توليد خطط الدروس دفعة واحدة.',
    errUnexpected: 'حدث خطأ غير متوقع أثناء التوليد.',
    errPayloadTooLarge: 'الملفات المرفوعة أكبر من حد الخادم. جرّب دروسًا أقل أو ملفات أصغر.',
    errQaMissing: 'أعاد الخادم هذا الدرس دون تقرير الجودة، فلم يُعرض. حاول مجددًا.',
    errNetwork: 'تعذّر الوصول إلى الخادم. تحقق من اتصال الإنترنت ثم حاول مجددًا.',
    noLessonsGenerated: 'تعذّر إنشاء أي درس. راجع الأخطاء أعلاه ثم حاول مجددًا.',
    metaLessons: (n) => (n === 1 ? 'درس واحد' : n === 2 ? 'درسان' : `${n} دروس`),
    metaPages: (n) => `${n} ص`,
    metaBaseline: (n) => `المرجع ${n} ص`,
    metaAttached: 'مرفق',
    metaReadyToCompare: 'جاهز للمقارنة',
    rtlLabel: 'من اليمين لليسار',
    ltrLabel: 'من اليسار لليمين',
    selectLesson: 'اختر الدرس',
    selectedCount: (sel, total) => `${sel} من ${total} محدد`,
    selectAll: (n) => `تحديد الكل (${n})`,
    selectFirstOnly: 'تحديد الأول فقط',
    pagesRange: (a, b) => `الصفحات ${a}–${b}`,
    wordsCount: (n) => `${n} كلمة`,
    adjusted: 'معدَّل',
    boundaryUncertain: 'نطاق الصفحات غير مؤكد — راجع النطاق.',
    fixRange: 'تصحيح النطاق',
    edit: 'تعديل',
    lessonTitleLabel: 'عنوان الدرس',
    startPage: (max) => `صفحة البداية (1–${max})`,
    endPage: (max) => `صفحة النهاية (1–${max})`,
    cancel: 'إلغاء',
    saving: 'جارٍ الحفظ…',
    confirmRange: 'تأكيد النطاق',
    defaultLessonTitle: 'درس',
    advancedSettings: 'إعدادات متقدمة',
    minutesShort: (n) => `${n} دقيقة`,
    autoLanguage: 'لغة تلقائية',
    arabic: 'العربية',
    english: 'الإنجليزية',
    teacherName: 'اسم المعلم',
    classSection: 'الفصل',
    lessonDate: 'التاريخ',
    grade: 'الصف الدراسي',
    subject: 'المادة',
    durationLabel: 'مدة الحصة (بالدقائق)',
    outputLanguage: 'لغة المخرجات',
    matchTemplateLang: 'مطابقة لغة القالب',
    stages: [
      'قراءة المنهج',
      'تحديد الدروس',
      'توليد خطة الدرس',
      'تنسيق مستند Word',
      'التحويل إلى PDF',
      'التحقق من المخرجات',
    ],
    processing: 'جارٍ المعالجة',
    lessonsCount: (n) => (n === 1 ? 'درس واحد' : n === 2 ? 'درسان' : `${n} دروس`),
    generationFailed: 'تعذّر إكمال التوليد',
    tryAgain: 'حاول مجددًا',
    qaPass: 'ناجح',
    qaWarning: 'يحتاج مراجعة',
    qaFail: 'فشل',
    qualityLabel: 'الجودة:',
    planReady: 'خطة الدرس جاهزة',
    planNotReady: 'الخطة لم تجتز فحوصات الجودة',
    failuresTitle: 'دروس تعذّر إنشاؤها',
    downloadFailed: 'فشل التنزيل — حاول مرة أخرى أو أعد إنشاء الخطة.',
    morePlans: (n) => `(+${n} أخرى)`,
    lessonsGenerated: (n) => (n === 1 ? 'تم توليد درس واحد' : `تم توليد ${n} دروس`),
    minutesValue: (sum, target) => `${sum}/${target} دقيقة`,
    pagesValue: (rendered, expected) => `${rendered}/${expected} صفحة`,
    downloadDocx: 'تنزيل Word (.docx)',
    downloadPdf: 'تنزيل PDF (.pdf)',
    downloadAllZip: 'تنزيل الكل (.zip)',
    pdfUnavailable: 'PDF غير متاح',
    pdfFailed: 'فشل إنشاء PDF',
    wordLink: 'Word (.docx)',
    pdfLink: 'PDF (.pdf)',
    notesTitle: 'ملاحظات التنسيق والتحقق',
    warnPdfFallback:
      'تم إنشاء PDF بمحرك بديل لأن LibreOffice غير متوفر في هذه البيئة. افتح ملف Word للحصول على التنسيق العربي الكامل وتصميم القالب الأصلي.',
    warnPdfFailed: 'فشل تحويل PDF؛ يظل ملف Word القابل للتعديل متاحًا للتنزيل.',
    warnPageCount: (rendered, expected) =>
      `عدد الصفحات الناتج (${rendered}) يختلف عن النموذج المرجعي (${expected}).`,
    warnOverflow: (fields) => `احتمال تجاوز المحتوى لحدود الخلايا في: ${fields}.`,
  },
};
