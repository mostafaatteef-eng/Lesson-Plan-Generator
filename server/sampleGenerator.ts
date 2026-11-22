import JSZip from 'jszip';
import { PDFDocument, StandardFonts, rgb } from 'pdf-lib';

function escapeXml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function makeParagraph(
  text: string,
  opts: {
    rtl?: boolean;
    bold?: boolean;
    sizeHalfPt?: number;
    colorHex?: string;
    align?: 'right' | 'center' | 'left';
    spaceBefore?: number;
    spaceAfter?: number;
  } = {}
): string {
  const rtl = opts.rtl !== false;
  const align = opts.align ?? (rtl ? 'right' : 'left');
  const size = opts.sizeHalfPt ?? 22;
  const color = opts.colorHex ?? '1E293B';
  const boldXml = opts.bold ? '<w:b/><w:bCs/>' : '';
  const bidiXml = rtl ? '<w:bidi/>' : '';
  const rtlRunXml = rtl ? '<w:rtl/>' : '';
  const spacing = `<w:spacing w:before="${opts.spaceBefore ?? 40}" w:after="${opts.spaceAfter ?? 40}"/>`;

  return `<w:p>
    <w:pPr>
      ${bidiXml}
      <w:jc w:val="${align}"/>
      ${spacing}
    </w:pPr>
    <w:r>
      <w:rPr>
        <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Arial"/>
        ${boldXml}
        <w:color w:val="${color}"/>
        <w:sz w:val="${size}"/>
        <w:szCs w:val="${size}"/>
        ${rtlRunXml}
      </w:rPr>
      <w:t xml:space="preserve">${escapeXml(text)}</w:t>
    </w:r>
  </w:p>`;
}

interface CellSpec {
  text: string;
  widthDxa: number;
  shade?: string;
  bold?: boolean;
  colorHex?: string;
  gridSpan?: number;
  align?: 'right' | 'center' | 'left';
  sizeHalfPt?: number;
}

function makeCell(cell: CellSpec): string {
  const spanXml = cell.gridSpan && cell.gridSpan > 1 ? `<w:gridSpan w:val="${cell.gridSpan}"/>` : '';
  const shdXml = cell.shade
    ? `<w:shd w:val="clear" w:color="auto" w:fill="${cell.shade}"/>`
    : '';
  const lines = cell.text.split('\n');
  const paragraphs = lines
    .map((line) =>
      makeParagraph(line, {
        rtl: true,
        bold: cell.bold,
        colorHex: cell.colorHex,
        align: cell.align ?? 'right',
        sizeHalfPt: cell.sizeHalfPt ?? 20,
      })
    )
    .join('');

  return `<w:tc>
    <w:tcPr>
      <w:tcW w:w="${cell.widthDxa}" w:type="dxa"/>
      ${spanXml}
      <w:tcBorders>
        <w:top w:val="single" w:sz="6" w:space="0" w:color="0F5C5C"/>
        <w:left w:val="single" w:sz="6" w:space="0" w:color="0F5C5C"/>
        <w:bottom w:val="single" w:sz="6" w:space="0" w:color="0F5C5C"/>
        <w:right w:val="single" w:sz="6" w:space="0" w:color="0F5C5C"/>
      </w:tcBorders>
      ${shdXml}
      <w:tcMar>
        <w:top w:w="80" w:type="dxa"/>
        <w:left w:w="120" w:type="dxa"/>
        <w:bottom w:w="80" w:type="dxa"/>
        <w:right w:w="120" w:type="dxa"/>
      </w:tcMar>
    </w:tcPr>
    ${paragraphs}
  </w:tc>`;
}

function makeTable(rows: CellSpec[][], colWidths: number[]): string {
  const gridCols = colWidths.map((w) => `<w:gridCol w:w="${w}"/>`).join('');
  const rowsXml = rows
    .map((row) => `<w:tr>${row.map((c) => makeCell(c)).join('')}</w:tr>`)
    .join('');

  return `<w:tbl>
    <w:tblPr>
      <w:tblW w:w="${colWidths.reduce((a, b) => a + b, 0)}" w:type="dxa"/>
      <w:bidiVisual/>
      <w:tblBorders>
        <w:top w:val="single" w:sz="8" w:space="0" w:color="0F5C5C"/>
        <w:left w:val="single" w:sz="8" w:space="0" w:color="0F5C5C"/>
        <w:bottom w:val="single" w:sz="8" w:space="0" w:color="0F5C5C"/>
        <w:right w:val="single" w:sz="8" w:space="0" w:color="0F5C5C"/>
        <w:insideH w:val="single" w:sz="4" w:space="0" w:color="94A3B8"/>
        <w:insideV w:val="single" w:sz="4" w:space="0" w:color="94A3B8"/>
      </w:tblBorders>
    </w:tblPr>
    <w:tblGrid>${gridCols}</w:tblGrid>
    ${rowsXml}
  </w:tbl>`;
}

function makePageBreak(): string {
  return `<w:p><w:r><w:br w:type="page"/></w:r></w:p>`;
}

/**
 * Generates an authentic, structurally valid 6-page Arabic RTL ATS-MU DOCX template
 * preserving every table, merged cell, RTL flag (w:bidi / w:bidiVisual), checkbox (☐),
 * time slot (00:00), quirked label (الغرض النشاط, لعب ادوار), and footer copyright.
 */
export async function buildSampleAtsMuTemplateDocx(): Promise<Buffer> {
  const zip = new JSZip();

  const headerXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  ${makeParagraph('وزارة التربية والتعليم والتعليم الفني — وحدة تشغيل وإدارة مدارس التكنولوجيا التطبيقية (ATS-MU)', {
    rtl: true,
    bold: true,
    sizeHalfPt: 18,
    colorHex: '0F5C5C',
    align: 'center',
  })}
</w:hdr>`;

  const footerXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  ${makeParagraph('© All Copy rights reserved to ATS-MU | التكنولوجيا التطبيقية', {
    rtl: false,
    bold: false,
    sizeHalfPt: 16,
    colorHex: '475569',
    align: 'center',
  })}
</w:ftr>`;

  // PAGE 1: Cover
  const page1 = [
    makeParagraph('وزارة التربية والتعليم والتعليم الفني — التكنولوجيا التطبيقية', {
      rtl: true,
      bold: true,
      sizeHalfPt: 26,
      colorHex: '0F5C5C',
      align: 'center',
      spaceAfter: 160,
    }),
    makeParagraph('تحضير برنامج / مقرر', {
      rtl: true,
      bold: true,
      sizeHalfPt: 36,
      colorHex: '134E4A',
      align: 'center',
      spaceAfter: 240,
    }),
    makeTable(
      [
        [
          { text: 'برنامج / مقرر', widthDxa: 3200, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 6400 },
        ],
        [
          { text: 'الاسم', widthDxa: 3200, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 6400 },
        ],
        [
          { text: 'الوظيفة', widthDxa: 3200, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 6400 },
        ],
        [
          { text: 'العام الدراسي', widthDxa: 3200, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: '٢٠٢٥-٢٠٢٦', widthDxa: 6400 },
        ],
      ],
      [3200, 6400]
    ),
    makePageBreak(),
  ].join('');

  // PAGE 2: Metadata Table
  const page2 = [
    makeParagraph('بيانات المدرسة والبرنامج — 2 of 6', {
      rtl: true,
      bold: true,
      sizeHalfPt: 24,
      colorHex: '0F5C5C',
      align: 'right',
      spaceAfter: 120,
    }),
    makeTable(
      [
        [
          { text: 'المدرسة', widthDxa: 3000, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 6600, gridSpan: 3 },
        ],
        [
          { text: 'البرنامج / المقرر', widthDxa: 3000, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 6600, gridSpan: 3 },
        ],
        [
          { text: 'الصف', widthDxa: 3000, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 6600, gridSpan: 3 },
        ],
        [
          { text: 'العام الدراسي', widthDxa: 3000, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: '2025/2024', widthDxa: 6600, gridSpan: 3 },
        ],
        [
          { text: 'فصل', widthDxa: 3000, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: '2 A', widthDxa: 2200, align: 'center' },
          { text: '2B', widthDxa: 2200, align: 'center' },
          { text: ' ', widthDxa: 2200, align: 'center' },
        ],
      ],
      [3000, 2200, 2200, 2200]
    ),
    makePageBreak(),
  ].join('');

  // PAGE 3: Unit & Outcomes
  const page3 = [
    makeParagraph('تخطيط الوحدة ونواتج التعلم — 3 of 6', {
      rtl: true,
      bold: true,
      sizeHalfPt: 24,
      colorHex: '0F5C5C',
      align: 'right',
      spaceAfter: 80,
    }),
    makeTable(
      [
        [
          { text: 'الوحدة', widthDxa: 2400, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 2400 },
          { text: 'اسم الوحدة', widthDxa: 2400, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 2400 },
        ],
        [
          { text: 'الفرع', widthDxa: 2400, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 2400 },
          { text: 'المعرفة (TPK00)', widthDxa: 2400, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: 'TPK00', widthDxa: 2400 },
        ],
        [
          { text: 'الدرس', widthDxa: 2400, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 7200, gridSpan: 3 },
        ],
        [
          { text: 'نواتج التعلم', widthDxa: 2400, shade: '0F5C5C', bold: true, colorHex: 'FFFFFF' },
          { text: '▪ \n▪ \n▪ \n▪ ', widthDxa: 7200, gridSpan: 3 },
        ],
        [
          { text: 'عناصر الدرس', widthDxa: 7200, shade: '0F5C5C', bold: true, colorHex: 'FFFFFF', gridSpan: 3 },
          { text: 'الزمن', widthDxa: 2400, shade: '0F5C5C', bold: true, colorHex: 'FFFFFF', align: 'center' },
        ],
        [
          { text: '1- ', widthDxa: 7200, gridSpan: 3 },
          { text: '00:00', widthDxa: 2400, align: 'center' },
        ],
        [
          { text: '2- ', widthDxa: 7200, gridSpan: 3 },
          { text: '00:00', widthDxa: 2400, align: 'center' },
        ],
        [
          { text: '3- ', widthDxa: 7200, gridSpan: 3 },
          { text: '00:00', widthDxa: 2400, align: 'center' },
        ],
        [
          { text: '4- ', widthDxa: 7200, gridSpan: 3 },
          { text: '00:00', widthDxa: 2400, align: 'center' },
        ],
        [
          { text: '5- ', widthDxa: 7200, gridSpan: 3 },
          { text: '00:00', widthDxa: 2400, align: 'center' },
        ],
        [
          { text: 'استراتيجيات التدريس', widthDxa: 2400, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          {
            text: '☐ المحاضرة   ☐ مناقشة وحوار   ☐ تعلم تعاوني   ☐ حل مشكلات   ☐ لعب ادوار   ☐ عصف ذهني   ☐ أخرى',
            widthDxa: 7200,
            gridSpan: 3,
          },
        ],
        [
          { text: 'مصادر التعلم', widthDxa: 2400, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          {
            text: '☐ دليل الطالب   ☐ فيديو تعليمي   ☐ المكتبة المدرسية   ☐ منصات تعليمية   ☐ عرض تقديمي   ☐ أخرى',
            widthDxa: 7200,
            gridSpan: 3,
          },
        ],
        [
          { text: 'التقييم — مجموعة ( ١ )', widthDxa: 2400, shade: 'F1F5F9', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 7200, gridSpan: 3 },
        ],
        [
          { text: 'التقييم — مجموعة ( ٢ )', widthDxa: 2400, shade: 'F1F5F9', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 7200, gridSpan: 3 },
        ],
      ],
      [2400, 2400, 2400, 2400]
    ),
    makePageBreak(),
  ].join('');

  // PAGE 4: Assessment Continuation
  const page4 = [
    makeParagraph('تابع التقييم — 4 of 6', {
      rtl: true,
      bold: true,
      sizeHalfPt: 24,
      colorHex: '0F5C5C',
      align: 'right',
      spaceAfter: 100,
    }),
    makeTable(
      [
        [
          { text: 'مجموعة ( ٣ )', widthDxa: 9600, shade: '0F5C5C', bold: true, colorHex: 'FFFFFF' },
        ],
        [
          { text: ' ', widthDxa: 9600 },
        ],
      ],
      [9600]
    ),
    makePageBreak(),
  ].join('');

  // PAGE 5: Lesson Presentation
  const page5 = [
    makeParagraph('عرض الدرس والأنشطة الصفية — 5 of 6', {
      rtl: true,
      bold: true,
      sizeHalfPt: 24,
      colorHex: '0F5C5C',
      align: 'right',
      spaceAfter: 80,
    }),
    makeTable(
      [
        [
          { text: 'اسم الدرس', widthDxa: 1800, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 3000 },
          { text: 'الفصل', widthDxa: 1200, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: '2 A', widthDxa: 1200 },
          { text: 'المكان', widthDxa: 1200, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 1200 },
        ],
        [
          { text: 'التاريخ', widthDxa: 1800, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: ' ', widthDxa: 3000 },
          { text: 'الزمن', widthDxa: 1200, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C' },
          { text: '00:00', widthDxa: 3600, gridSpan: 3 },
        ],
        [
          { text: 'التهيئة', widthDxa: 1800, shade: '0F5C5C', bold: true, colorHex: 'FFFFFF' },
          { text: ' ', widthDxa: 7800, gridSpan: 5 },
        ],
        [
          { text: 'أولا: العنصر الاول في الدرس', widthDxa: 4800, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C', gridSpan: 2 },
          { text: 'استراتيجية التدريس', widthDxa: 2400, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C', gridSpan: 2 },
          { text: '00:00', widthDxa: 2400, align: 'center', gridSpan: 2 },
        ],
        [
          { text: 'وصف مختصر للعنصر الأول', widthDxa: 1800, shade: 'F1F5F9', bold: true },
          { text: ' ', widthDxa: 7800, gridSpan: 5 },
        ],
        [
          { text: 'نشاط ( ١ ) — الزمن', widthDxa: 2400, shade: 'C9A227', bold: true, colorHex: 'FFFFFF', gridSpan: 2 },
          { text: '00:00', widthDxa: 1200, align: 'center' },
          { text: 'النمط: ☐ فردي ☐ جماعي', widthDxa: 2400, gridSpan: 1 },
          { text: 'النوع: ☐ دراسة حالة ☐ بحث ☐ رسم / تصميم ☐ أخرى', widthDxa: 3600, gridSpan: 2 },
        ],
        [
          { text: 'الغرض النشاط', widthDxa: 1800, shade: 'F1F5F9', bold: true },
          { text: ' ', widthDxa: 7800, gridSpan: 5 },
        ],
        [
          { text: 'إجراءات النشاط (دور المعلم)', widthDxa: 4800, shade: 'DCEAE8', bold: true, gridSpan: 3 },
          { text: 'إجراءات النشاط (دور الطالب)', widthDxa: 4800, shade: 'DCEAE8', bold: true, gridSpan: 3 },
        ],
        [
          { text: ' ', widthDxa: 4800, gridSpan: 3 },
          { text: ' ', widthDxa: 4800, gridSpan: 3 },
        ],
        [
          { text: 'عزيزي الطالب / الطالبة', widthDxa: 1800, shade: 'F1F5F9', bold: true },
          { text: ' ', widthDxa: 7800, gridSpan: 5 },
        ],
        [
          { text: 'ثانيا: العنصر الثاني في الدرس', widthDxa: 4800, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C', gridSpan: 2 },
          { text: 'استراتيجية التدريس', widthDxa: 2400, shade: 'DCEAE8', bold: true, colorHex: '0F5C5C', gridSpan: 2 },
          { text: '00:00', widthDxa: 2400, align: 'center', gridSpan: 2 },
        ],
        [
          { text: 'وصف مختصر للعنصر الثاني', widthDxa: 1800, shade: 'F1F5F9', bold: true },
          { text: ' ', widthDxa: 7800, gridSpan: 5 },
        ],
        [
          { text: 'نشاط ( ٢ ) — الزمن', widthDxa: 2400, shade: 'C9A227', bold: true, colorHex: 'FFFFFF', gridSpan: 2 },
          { text: '00:00', widthDxa: 1200, align: 'center' },
          { text: 'النمط: ☐ فردي ☐ جماعي', widthDxa: 2400, gridSpan: 1 },
          { text: 'النوع: ☐ دراسة حالة ☐ بحث ☐ رسم / تصميم ☐ أخرى', widthDxa: 3600, gridSpan: 2 },
        ],
        [
          { text: 'الغرض النشاط ( ٢ )', widthDxa: 1800, shade: 'F1F5F9', bold: true },
          { text: ' ', widthDxa: 7800, gridSpan: 5 },
        ],
        [
          { text: 'إجراءات النشاط ٢ (دور المعلم)', widthDxa: 4800, shade: 'DCEAE8', bold: true, gridSpan: 3 },
          { text: 'إجراءات النشاط ٢ (دور الطالب)', widthDxa: 4800, shade: 'DCEAE8', bold: true, gridSpan: 3 },
        ],
        [
          { text: ' ', widthDxa: 4800, gridSpan: 3 },
          { text: ' ', widthDxa: 4800, gridSpan: 3 },
        ],
        [
          { text: 'عزيزي الطالب / الطالبة ( ٢ )', widthDxa: 1800, shade: 'F1F5F9', bold: true },
          { text: ' ', widthDxa: 7800, gridSpan: 5 },
        ],
      ],
      [1800, 3000, 1200, 1200, 1200, 1200]
    ),
    makePageBreak(),
  ].join('');

  // PAGE 6: Evaluation Rubrics
  const page6 = [
    makeParagraph('معايير التقييم — 6 of 6', {
      rtl: true,
      bold: true,
      sizeHalfPt: 24,
      colorHex: '0F5C5C',
      align: 'right',
      spaceAfter: 80,
    }),
    makeTable(
      [
        [{ text: 'مجموعة ( ١ )', widthDxa: 9600, shade: '0F5C5C', bold: true, colorHex: 'FFFFFF' }],
        [{ text: '-1 ', widthDxa: 9600 }],
        [{ text: '-2 ', widthDxa: 9600 }],
        [{ text: '-3 ', widthDxa: 9600 }],
        [{ text: '-4 ', widthDxa: 9600 }],
        [{ text: '-5 ', widthDxa: 9600 }],
        [{ text: '-6 ', widthDxa: 9600 }],
      ],
      [9600]
    ),
    makeParagraph(' ', { rtl: true, spaceBefore: 120, spaceAfter: 60 }),
    makeTable(
      [
        [{ text: 'مجموعة ( ٢ )', widthDxa: 9600, shade: '0F5C5C', bold: true, colorHex: 'FFFFFF' }],
        [{ text: '-1 ', widthDxa: 9600 }],
        [{ text: '-2 ', widthDxa: 9600 }],
        [{ text: '-3 ', widthDxa: 9600 }],
        [{ text: '-4 ', widthDxa: 9600 }],
        [{ text: '-5 ', widthDxa: 9600 }],
        [{ text: '-6 ', widthDxa: 9600 }],
      ],
      [9600]
    ),
  ].join('');

  const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    ${page1}
    ${page2}
    ${page3}
    ${page4}
    ${page5}
    ${page6}
    <w:sectPr>
      <w:headerReference w:type="default" r:id="rId1"/>
      <w:footerReference w:type="default" r:id="rId2"/>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/>
      <w:bidi/>
    </w:sectPr>
  </w:body>
</w:document>`;

  const contentTypesXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
</Types>`;

  const rootRelsXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`;

  const docRelsXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>`;

  zip.file('[Content_Types].xml', contentTypesXml);
  zip.file('_rels/.rels', rootRelsXml);
  zip.file('word/_rels/document.xml.rels', docRelsXml);
  zip.file('word/document.xml', documentXml);
  zip.file('word/header1.xml', headerXml);
  zip.file('word/footer1.xml', footerXml);

  return zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
}

/**
 * Generates a 6-page A4 Reference PDF corresponding to the approved ATS-MU template layout.
 */
export async function buildSampleReferencePdf(): Promise<Buffer> {
  const pdfDoc = await PDFDocument.create();
  const font = await pdfDoc.embedFont(StandardFonts.Helvetica);
  const bold = await pdfDoc.embedFont(StandardFonts.HelveticaBold);

  const pageTitles = [
    'Page 1 of 6 — ATS-MU Lesson Plan Cover (RTL Arabic Template)',
    'Page 2 of 6 — School, Program, Grade, Academic Year & Classes (2 A / 2B)',
    'Page 3 of 6 — Unit, Outcomes, Lesson Elements (00:00), Strategies & Resources',
    'Page 4 of 6 — Assessment Continuation (Group 3)',
    'Page 5 of 6 — Lesson Presentation, Warm-up, Activity 1 & Activity 2',
    'Page 6 of 6 — Evaluation Rubrics (Group 1 & Group 2: -1 to -6)',
  ];

  for (let i = 0; i < 6; i++) {
    const page = pdfDoc.addPage([595.28, 841.89]); // Exact A4 matching w:pgSz 11906x16838 dxa
    // Top teal header strip
    page.drawRectangle({
      x: 40,
      y: 780,
      width: 515,
      height: 28,
      color: rgb(0.059, 0.361, 0.361),
    });
    page.drawText('ATS-MU Applied Technology Lesson Plan Reference', {
      x: 52,
      y: 790,
      size: 11,
      font: bold,
      color: rgb(1, 1, 1),
    });

    page.drawText(pageTitles[i], {
      x: 40,
      y: 745,
      size: 13,
      font: bold,
      color: rgb(0.07, 0.16, 0.23),
    });

    // Draw reference table grid outline matching page layout
    page.drawRectangle({
      x: 40,
      y: 120,
      width: 515,
      height: 600,
      borderColor: rgb(0.059, 0.361, 0.361),
      borderWidth: 1,
    });

    for (let row = 1; row <= 6; row++) {
      const y = 720 - row * 85;
      page.drawLine({
        start: { x: 40, y },
        end: { x: 555, y },
        thickness: 0.5,
        color: rgb(0.75, 0.82, 0.85),
      });
    }

    // Footer copyright
    page.drawText(`© All Copy rights reserved to ATS-MU  |  ${i + 1} of 6`, {
      x: 175,
      y: 42,
      size: 9,
      font,
      color: rgb(0.35, 0.42, 0.5),
    });
  }

  const bytes = await pdfDoc.save();
  return Buffer.from(bytes);
}

/**
 * Sample Arabic Applied Technology Curriculum Unit with 3 cleanly structured lessons.
 */
export function getSampleCurriculumText(): string {
  return `الوحدة الثالثة: أنظمة التحكم المنطقي المبرمج (PLC) في خطوط الإنتاج الصناعي
الفرع: الأتمتة الصناعية والتحكم الآلي — رمز المعرفة: TPK04
--- PAGE 1 ---
الدرس الأول: مكونات وحدة التحكم المنطقي المبرمج (PLC) وبنيتها الوظيفية

الأهداف التعليمية المستخلصة من المنهج:
تُعد وحدة التحكم المنطقي المبرمج (Programmable Logic Controller - PLC) حاسوباً صناعياً رقمياً مصمماً للعمل في البيئات الصناعية القاسية مثل درجات الحرارة المرتفعة والاهتزازات والتداخل الكهرومغناطيسي. تتكون منظومة الـ PLC الأساسية من خمس وحدات رئيسية متكاملة:
1. وحدة المعالجة المركزية (CPU): تمثل عقل النظام وتقوم بتنفيذ دورة المسح (Scan Cycle) التي تشمل قراءة المداخل، وتنفيذ برنامج المستخدم المخزن في الذاكرة، ثم تحديث المخارج بشكل دوري سريع يقاس بالملي ثانية.
2. وحدة الذاكرة (Memory Unit): وتنقسم إلى ذاكرة النظام (ROM/Firmware) وذاكرة المستخدم (RAM/EEPROM) لحفظ مخططات التحكم وبيانات المؤقتات والعدادات.
3. وحدات الإدخال (Input Modules): تستقبل الإشارات الرقمية (مثل مفاتيح الضغط وحساسات التقارب) أو التناظرية (مثل حساسات الحرارة والضغط) وتحولها عبر العوازل الضوئية (Optocouplers) إلى مستويات جهد آمنة للمعالج.
4. وحدات الإخراج (Output Modules): تحول أوامر المعالج إلى إشارات تشغيل للمشغلات الصناعية مثل المرحلات (Relays) والكونتاكتورات والصمامات الكهرومغناطيسية ومصابيح البيان.
5. وحدة التغذية الكهربائية (Power Supply): تحول التيار المتردد 220V AC إلى تيار مستمر منظم 24V DC لتغذية الدوائر الداخلية والحساسات.

نشاط تطبيقي في المعمل (من دليل الطالب):
يفحص الطلاب لوحة تدريبية لوحدة Siemens S7-1200 ويحددون مواقع أطراف الإدخال (I0.0 - I0.7) وأطراف الإخراج (Q0.0 - Q0.5) ومؤشرات الحالة (RUN / STOP / ERROR)، ثم يرسمون مخططاً صندوقياً يوضح مسار الإشارة خلال دورة المسح.

أسئلة تقويم الدرس الأول:
- قارن بين وظيفة وحدة الإدخال الرقمية ووحدة الإخراج في نظام PLC.
- اشرح مراحل دورة المسح (Scan Cycle) بالترتيب الصحيح.
- ما أهمية العازل الضوئي (Optocoupler) في حماية وحدة المعالجة المركزية؟

--- PAGE 2 ---
الدرس الثاني: بوابات المنطق ومخططات السلم (Ladder Diagram - LD)

مقدمة المنهج:
تُعد لغة مخطط السلم (Ladder Diagram) الأكثر انتشاراً في برمجة وحدات التحكم المنطقي المبرمج وفق المعيار الدولي IEC 61131-3، لأنها تشبه مخططات دوائر التحكم الكهربائي التقليدية (Classic Control). يتكون مخطط السلم من قضيبين رأسيين للطاقة (Power Rails) ودرجات أفقية (Rungs) تحتوي على نقاط تلامس إدخال وملفات إخراج.

المفاهيم الأساسية في الدرس:
1. نقاط التلامس (Contacts): نقطة تلامس مفتوحة طبيعياً (Normally Open - NO) تسمح بمرور الإشارة المنطقية عند تنشيط المدخل، ونقطة تلامس مغلقة طبيعياً (Normally Closed - NC) تقطع الإشارة عند تنشيط المدخل.
2. ملفات الإخراج (Output Coils): تمثل المشغل أو الخرج النهائي على الطرف الأيمن من الدرجة.
3. تمثيل البوابات المنطقية بلغة السلم:
   - بوابة AND: توصيل نقطتي تلامس مفتوحتين على التوالي (Series) لتشغيل المحرك فقط عند تحقق شرطي الأمان معاً.
   - بوابة OR: توصيل نقطتي تلامس مفتوحتين على التوازي (Parallel) لتشغيل الإنذار من أي حساس.
   - دائرة الإمساك الذاتي (Latching / Start-Stop Circuit): استخدام مفتاح تشغيل (Start NO) على التوازي مع نقطة مساعدة من ملف الخرج (Q0.0) ومفتاح إيقاف (Stop NC) على التوالي لضمان استمرار تشغيل السير الناقل بعد رفع اليد عن زر التشغيل.

مثال عملي وتدريب:
تصميم دائرة سلم (Ladder Diagram) للتحكم في سير ناقل يعمل بزر تشغيل I0.0 ويتوقف بزر إيقاف طوارئ I0.1 أو حساس حمل زائد I0.2، مع مصباح بيان أخضر Q0.0 أثناء التشغيل.

تقويم الدرس الثاني:
- ارسم مخطط السلم لدائرة Start-Stop مع مفتاح إيقاف طوارئ.
- استنتج جدول الحقيقة لدائرة تلامسين على التوالي وآخرين على التوازي.

--- PAGE 3 ---
الدرس الثالث: تطبيقات التحكم في المحركات والمؤقتات والعدادات الصناعية

محتوى المنهج:
تتطلب خطوط الإنتاج الحديثة التحكم الزمني والعددي الدقيق باستخدام المؤقتات (Timers) والعدادات (Counters) المدمجة داخل برنامج الـ PLC بدلاً من المؤقتات الميكانيكية التقليدية.

أولاً: المؤقتات الزمنية (Timers):
- مؤقت تأخير التشغيل (TON - On-Delay Timer): يبدأ العد الزمني عند تفعيل المدخل، ويتحول خرجه إلى الحالة المنطقية (1) بعد انتهاء الزمن المضبوط (Preset Time - PT). يُستخدم في تشغيل المحركات بتسلسل زمني (مثل دائرة نجمة-دلتا Star-Delta) لتقليل تيار البدء.
- مؤقت تأخير الإيقاف (TOF - Off-Delay Timer): يحافظ على الخرج مفعلاً لفترة زمنية محددة بعد فصل إشارة الإدخال، ويُستخدم في مراوح تبريد المحركات بعد إيقاف الآلة.

ثانياً: العدادات (Counters):
- العداد التصاعدي (CTU - Count Up): يحسب عدد النبضات القادمة من حساس بصري على خط التعبئة، وعند وصول القيمة الحالية (CV) إلى القيمة المضبوطة (PV) مثل 12 عبوة، يعطي إشارة لإيقاف السير وتشغيل ذراع التغليف ثم إعادة التصفير (Reset).

دراسة حالة صناعية:
خط تعبئة آلي يبدأ عمله بعد 5 ثوانٍ من الضغط على زر التشغيل (TON)، ويعد 10 قطع باستخدام حساس تقارب متصل بمدخل I0.3، وعند اكتمال العدد يتوقف السير لمدة 3 ثوانٍ لإغلاق الصندوق ثم يعيد الدورة تلقائياً.

أسئلة وتطبيقات الدرس الثالث:
- صمم برنامجاً زمنياً باستخدام مؤقت TON لتأخير تشغيل مروحة شفط لمدة 8 ثوانٍ.
- فرق بين وظيفة مؤقت TON ومؤقت TOF مع ذكر تطبيق صناعي لكل منهما.
- وضح دور مدخل إعادة التصفير (Reset) في العداد التصاعدي CTU.`;
}
