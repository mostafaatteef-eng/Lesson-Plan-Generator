import crypto from 'crypto';
import JSZip from 'jszip';
import { DOMParser, XMLSerializer } from '@xmldom/xmldom';
import type { Document as XmlDocument, Element as XmlElement } from '@xmldom/xmldom';
import { PDFDocument } from 'pdf-lib';
import type {
  LessonPlanPayload,
  TemplateField,
  TemplateSchema,
  TemplateTableSummary,
} from './types';

function getDirectChildren(node: XmlElement, tagName: string): XmlElement[] {
  const result: XmlElement[] = [];
  for (let i = 0; i < node.childNodes.length; i++) {
    const child = node.childNodes[i];
    if (child.nodeType === 1 && (child as unknown as XmlElement).tagName === tagName) {
      result.push(child as unknown as XmlElement);
    }
  }
  return result;
}

function getElementText(el: XmlElement): string {
  const ts = Array.from(el.getElementsByTagName('w:t'));
  return ts.map((t) => t.textContent ?? '').join('');
}

function getCellParagraphTexts(tc: XmlElement): string[] {
  const ps = getDirectChildren(tc, 'w:p');
  return ps.map((p) => getElementText(p));
}

function dxaToPt(dxa: number): number {
  return Math.round((dxa / 20) * 100) / 100;
}

function estimateCellMaxChars(widthDxa: number, fieldType: TemplateField['field_type']): number {
  const widthInches = Math.max(0.8, widthDxa / 1440);
  const charsPerLine = Math.round(widthInches * 14);
  if (fieldType === 'multiline' || fieldType === 'bullet_list' || fieldType === 'rubric_list') {
    return charsPerLine * 6;
  }
  if (fieldType === 'time_slot') return 12;
  if (fieldType === 'checkbox_group') return charsPerLine * 2;
  return Math.max(40, charsPerLine * 2);
}

/**
 * Maps known ATS-MU Arabic and generic English field labels to canonical keys
 * WITHOUT ever altering the original label string in the DOCX.
 */
function normalizeLabelToKey(rawLabel: string, occurrenceMap: Map<string, number>): string {
  const clean = rawLabel.replace(/\s+/g, ' ').trim();
  let base = '';

  if (/^برنامج\s*\/\s*مقرر$/.test(clean)) base = 'program_or_course';
  else if (/^البرنامج\s*\/\s*المقرر$/.test(clean)) base = 'program_or_course_meta';
  else if (/^الاسم$/.test(clean)) base = 'teacher_name';
  else if (/^الوظيفة$/.test(clean)) base = 'job_title';
  else if (/^العام الدراسي$/.test(clean)) base = 'academic_year';
  else if (/^المدرسة$/.test(clean)) base = 'school_name';
  else if (/^الصف$/.test(clean)) base = 'grade_level';
  else if (/^فصل$/.test(clean)) base = 'class_sections';
  else if (/^الوحدة$/.test(clean)) base = 'unit_number';
  else if (/^اسم الوحدة$/.test(clean)) base = 'unit_name';
  else if (/^الفرع$/.test(clean)) base = 'branch';
  else if (/المعرفة|TPK/i.test(clean)) base = 'knowledge_code';
  else if (/^الدرس$/.test(clean)) base = 'lesson_title';
  else if (/^اسم الدرس$/.test(clean)) base = 'lesson_title_presentation';
  else if (/نواتج التعلم|learning outcomes|objectives/i.test(clean)) base = 'learning_outcomes';
  else if (/استراتيجيات التدريس|teaching strategies/i.test(clean)) base = 'selected_strategies';
  else if (/مصادر التعلم|learning resources/i.test(clean)) base = 'selected_resources';
  else if (/التقييم.*مجموعة.*١|مجموعة.*1/i.test(clean)) base = 'assessment_group_1';
  else if (/التقييم.*مجموعة.*٢|مجموعة.*2/i.test(clean)) base = 'assessment_group_2';
  else if (/مجموعة.*٣|مجموعة.*3/i.test(clean)) base = 'assessment_group_3';
  else if (/^الفصل$/.test(clean)) base = 'presentation_class';
  else if (/^المكان$/.test(clean)) base = 'location';
  else if (/^التاريخ$/.test(clean)) base = 'lesson_date';
  else if (/^الزمن$/.test(clean)) base = 'total_duration';
  else if (/^التهيئة$|warm.?up/i.test(clean)) base = 'warm_up';
  else if (/وصف مختصر للعنصر الأول/.test(clean)) base = 'element_1_summary';
  else if (/وصف مختصر للعنصر الثاني/.test(clean)) base = 'element_2_summary';
  else if (/الغرض النشاط\s*\(\s*٢\s*\)/.test(clean)) base = 'activity_2_purpose';
  else if (/الغرض النشاط|غرض النشاط|انشاط/.test(clean)) base = 'activity_1_purpose';
  else if (/عزيزي الطالب.*٢/.test(clean)) base = 'activity_2_student_note';
  else if (/عزيزي الطالب/.test(clean)) base = 'activity_1_student_note';
  else if (/^أولا.*العنصر/.test(clean)) base = 'element_1_header';
  else if (/^ثانيا.*العنصر/.test(clean)) base = 'element_2_header';
  else base = clean.toLowerCase().replace(/[^\w\u0600-\u06FF]+/g, '_').slice(0, 42) || 'field';

  const count = (occurrenceMap.get(base) ?? 0) + 1;
  occurrenceMap.set(base, count);
  return count === 1 ? base : `${base}_${count}`;
}

export async function parseTemplateDocx(
  docxBuffer: Buffer,
  filename: string,
  refPdfBuffer?: Buffer,
  refPdfFilename?: string
): Promise<TemplateSchema> {
  const zip = await JSZip.loadAsync(docxBuffer);
  const docFile = zip.file('word/document.xml');
  if (!docFile) {
    throw new Error('Uploaded template is not a valid .docx archive (missing word/document.xml).');
  }

  const docXml = await docFile.async('string');
  const parser = new DOMParser();
  const doc = parser.parseFromString(docXml, 'text/xml');

  // Extract locked identity markers from headers, footers, and top paragraphs
  const lockedMarkers: string[] = [];
  for (const name of Object.keys(zip.files)) {
    if (/^word\/(header|footer)\d*\.xml$/.test(name)) {
      const hfXml = await zip.file(name)!.async('string');
      const hfDoc = parser.parseFromString(hfXml, 'text/xml');
      const txt = Array.from(hfDoc.getElementsByTagName('w:t'))
        .map((t) => t.textContent ?? '')
        .join('')
        .trim();
      if (txt) lockedMarkers.push(txt);
    }
  }

  const body = doc.getElementsByTagName('w:body')[0];
  const sectPr = doc.getElementsByTagName('w:sectPr')[0];
  let pageWidthPt = 595.3;
  let pageHeightPt = 841.9;
  const marginsPt = { top: 56.7, bottom: 56.7, left: 56.7, right: 56.7 };

  if (sectPr) {
    const pgSz = sectPr.getElementsByTagName('w:pgSz')[0];
    if (pgSz) {
      pageWidthPt = dxaToPt(parseInt(pgSz.getAttribute('w:w') || '11906', 10));
      pageHeightPt = dxaToPt(parseInt(pgSz.getAttribute('w:h') || '16838', 10));
    }
    const pgMar = sectPr.getElementsByTagName('w:pgMar')[0];
    if (pgMar) {
      marginsPt.top = dxaToPt(parseInt(pgMar.getAttribute('w:top') || '1134', 10));
      marginsPt.bottom = dxaToPt(parseInt(pgMar.getAttribute('w:bottom') || '1134', 10));
      marginsPt.left = dxaToPt(parseInt(pgMar.getAttribute('w:left') || '1134', 10));
      marginsPt.right = dxaToPt(parseInt(pgMar.getAttribute('w:right') || '1134', 10));
    }
  }

  const bidiCount = doc.getElementsByTagName('w:bidi').length + doc.getElementsByTagName('w:bidiVisual').length;
  const allText = Array.from(doc.getElementsByTagName('w:t'))
    .map((t) => t.textContent ?? '')
    .join(' ');
  const arChars = allText.match(/[\u0600-\u06FF]/g)?.length ?? 0;
  const enChars = allText.match(/[A-Za-z]/g)?.length ?? 0;
  const language: TemplateSchema['language'] =
    arChars > 20 && enChars > 20 ? (arChars > enChars * 2 ? 'ar' : 'mixed') : arChars >= enChars ? 'ar' : 'en';
  const isRtl = bidiCount > 0 || language === 'ar';

  // Walk body children to track page breaks and map tables to page numbers
  let currentPage = 1;
  let tableIdx = 0;
  const tables: TemplateTableSummary[] = [];
  const fields: TemplateField[] = [];
  const occMap = new Map<string, number>();

  if (body) {
    for (let i = 0; i < body.childNodes.length; i++) {
      const node = body.childNodes[i];
      if (node.nodeType !== 1) continue;
      const el = node as unknown as XmlElement;

      if (el.tagName === 'w:p') {
        const pTxt = getElementText(el).trim();
        if (/تحضير برنامج|التكنولوجيا التطبيقية|ATS-MU/i.test(pTxt) && !lockedMarkers.includes(pTxt)) {
          lockedMarkers.push(pTxt);
        }
        const brs = Array.from(el.getElementsByTagName('w:br'));
        if (brs.some((b) => b.getAttribute('w:type') === 'page')) {
          currentPage++;
        }
      } else if (el.tagName === 'w:tbl') {
        const tblPr = getDirectChildren(el, 'w:tblPr')[0];
        const tblRtl = Boolean(tblPr?.getElementsByTagName('w:bidiVisual')[0]) || isRtl;
        const tblGrid = getDirectChildren(el, 'w:tblGrid')[0];
        const colWidths = tblGrid
          ? getDirectChildren(tblGrid, 'w:gridCol').map((gc) => parseInt(gc.getAttribute('w:w') || '2400', 10))
          : [];

        const trs = getDirectChildren(el, 'w:tr');
        let mergedCells = 0;
        let maxCols = colWidths.length;

        trs.forEach((tr, rIdx) => {
          const tcs = getDirectChildren(tr, 'w:tc');
          maxCols = Math.max(maxCols, tcs.length);

          tcs.forEach((tc, cIdx) => {
            const tcPr = getDirectChildren(tc, 'w:tcPr')[0];
            const tcWEl = tcPr?.getElementsByTagName('w:tcW')[0];
            const tcWidth = parseInt(tcWEl?.getAttribute('w:w') || String(colWidths[cIdx] ?? 2400), 10);
            const gridSpan = tcPr?.getElementsByTagName('w:gridSpan')[0];
            const vMerge = tcPr?.getElementsByTagName('w:vMerge')[0];
            const isMerged = Boolean(gridSpan || vMerge);
            if (isMerged) mergedCells++;

            const cellLines = getCellParagraphTexts(tc);
            const cellText = cellLines.join('\n').trim();

            // Check if this cell contains checkboxes
            if (cellText.includes('☐') || cellText.includes('☑')) {
              const options = cellText
                .split(/[☐☑]/)
                .slice(1)
                .map((opt) => opt.trim())
                .filter(Boolean);
              const prevLabel = cIdx > 0 ? getElementText(tcs[cIdx - 1]).trim() : `checkbox_t${tableIdx}_r${rIdx}`;
              const key = normalizeLabelToKey(prevLabel || cellText, occMap);
              fields.push({
                field_id: `f_t${tableIdx}_r${rIdx}_c${cIdx}`,
                label: prevLabel || cellText.slice(0, 40),
                normalized_key: key,
                page_hint: currentPage,
                field_type: 'checkbox_group',
                table_index: tableIdx,
                row_index: rIdx,
                col_index: cIdx,
                is_rtl: tblRtl,
                max_chars: estimateCellMaxChars(tcWidth, 'checkbox_group'),
                current_value: cellText,
                checkbox_options: options,
                is_merged: isMerged,
                locked_label: prevLabel,
              });
              return;
            }

            // Check if this cell is a 00:00 time slot
            if (/^\d{2}:\d{2}$/.test(cellText)) {
              const prevLabel = cIdx > 0 ? getElementText(tcs[cIdx - 1]).trim() : `time_t${tableIdx}_r${rIdx}`;
              fields.push({
                field_id: `f_t${tableIdx}_r${rIdx}_c${cIdx}`,
                label: `${prevLabel || 'الزمن'} (00:00)`,
                normalized_key: `time_slot_t${tableIdx}_r${rIdx}_c${cIdx}`,
                page_hint: currentPage,
                field_type: 'time_slot',
                table_index: tableIdx,
                row_index: rIdx,
                col_index: cIdx,
                is_rtl: false,
                max_chars: 10,
                current_value: cellText,
                has_time_placeholder: true,
                is_merged: isMerged,
              });
              return;
            }

            // Check for ▪ bullet list cells
            if (cellText.includes('▪')) {
              const prevLabel = cIdx > 0 ? getElementText(tcs[cIdx - 1]).trim() : 'نواتج التعلم';
              fields.push({
                field_id: `f_t${tableIdx}_r${rIdx}_c${cIdx}`,
                label: prevLabel,
                normalized_key: normalizeLabelToKey(prevLabel, occMap),
                page_hint: currentPage,
                field_type: 'bullet_list',
                table_index: tableIdx,
                row_index: rIdx,
                col_index: cIdx,
                is_rtl: tblRtl,
                max_chars: estimateCellMaxChars(tcWidth, 'bullet_list'),
                current_value: cellText,
                is_merged: isMerged,
                locked_label: prevLabel,
              });
              return;
            }

            // Check for rubric rows (-1 to -6)
            if (/^-\d+\s*$/.test(cellText)) {
              fields.push({
                field_id: `f_t${tableIdx}_r${rIdx}_c${cIdx}`,
                label: `Rubric Row ${cellText.trim()} (Table ${tableIdx + 1})`,
                normalized_key: `rubric_t${tableIdx}_r${rIdx}`,
                page_hint: currentPage,
                field_type: 'rubric_list',
                table_index: tableIdx,
                row_index: rIdx,
                col_index: cIdx,
                is_rtl: tblRtl,
                max_chars: estimateCellMaxChars(tcWidth, 'text'),
                current_value: cellText,
                is_merged: isMerged,
              });
              return;
            }

            // Check for numbered lesson element rows (1-, 2-, ...)
            if (/^[1-5]-\s*$/.test(cellText)) {
              fields.push({
                field_id: `f_t${tableIdx}_r${rIdx}_c${cIdx}`,
                label: `عنصر الدرس ${cellText.trim()}`,
                normalized_key: `lesson_element_${cellText.trim().replace('-', '')}`,
                page_hint: currentPage,
                field_type: 'text',
                table_index: tableIdx,
                row_index: rIdx,
                col_index: cIdx,
                is_rtl: tblRtl,
                max_chars: estimateCellMaxChars(tcWidth, 'text'),
                current_value: cellText,
                is_merged: isMerged,
              });
              return;
            }

            // Empty or placeholder value cell adjacent to a label cell
            const isEditableValueCell =
              cellText === '' ||
              cellText === ' ' ||
              /^(?:TPK00|2025\/2024|٢٠٢٥-٢٠٢٦|2 A|2B)$/.test(cellText);
            if (isEditableValueCell && cIdx > 0) {
              const prevLabel = getElementText(tcs[cIdx - 1]).trim();
              if (prevLabel) {
                const fType: TemplateField['field_type'] = tcWidth >= 6000 ? 'multiline' : 'text';
                fields.push({
                  field_id: `f_t${tableIdx}_r${rIdx}_c${cIdx}`,
                  label: prevLabel,
                  normalized_key: normalizeLabelToKey(prevLabel, occMap),
                  page_hint: currentPage,
                  field_type: fType,
                  table_index: tableIdx,
                  row_index: rIdx,
                  col_index: cIdx,
                  is_rtl: tblRtl,
                  max_chars: estimateCellMaxChars(tcWidth, fType),
                  current_value: cellText,
                  is_merged: isMerged,
                  locked_label: prevLabel,
                });
              }
            } else if (cellText === '' && rIdx > 0 && tcs.length === 1) {
              // Single-column value row beneath a header row (e.g. مجموعة ( ٣ ))
              const aboveCells = getDirectChildren(trs[rIdx - 1], 'w:tc');
              const aboveLabel = aboveCells[0] ? getElementText(aboveCells[0]).trim() : `section_t${tableIdx}_r${rIdx}`;
              fields.push({
                field_id: `f_t${tableIdx}_r${rIdx}_c${cIdx}`,
                label: aboveLabel,
                normalized_key: normalizeLabelToKey(aboveLabel, occMap),
                page_hint: currentPage,
                field_type: 'multiline',
                table_index: tableIdx,
                row_index: rIdx,
                col_index: cIdx,
                is_rtl: tblRtl,
                max_chars: estimateCellMaxChars(tcWidth, 'multiline'),
                current_value: cellText,
                is_merged: isMerged,
                locked_label: aboveLabel,
              });
            }
          });
        });

        tables.push({
          table_index: tableIdx,
          page_hint: currentPage,
          rows: trs.length,
          cols: maxCols,
          is_rtl: tblRtl,
          merged_cells: mergedCells,
          column_widths_dxa: colWidths,
        });
        tableIdx++;
      }
    }
  }

  let refPdfPages: number | undefined;
  let refPdfDims: Array<{ page: number; width_pt: number; height_pt: number }> | undefined;
  if (refPdfBuffer) {
    try {
      const refPdf = await PDFDocument.load(refPdfBuffer);
      refPdfPages = refPdf.getPageCount();
      refPdfDims = refPdf.getPages().map((pg, idx) => {
        const { width, height } = pg.getSize();
        return {
          page: idx + 1,
          width_pt: Math.round(width * 100) / 100,
          height_pt: Math.round(height * 100) / 100,
        };
      });
    } catch {
      // Ignore unreadable reference PDF metadata
    }
  }

  const isAtsMu = /ATS-MU|تحضير برنامج|التكنولوجيا التطبيقية|الغرض النشاط/.test(
    `${allText} ${lockedMarkers.join(' ')}`
  );

  return {
    template_id: `tpl_${crypto.randomBytes(4).toString('hex')}`,
    filename,
    uploaded_at: new Date().toISOString(),
    is_locked: false,
    language,
    is_rtl: isRtl,
    page_count_expected: refPdfPages ?? currentPage,
    page_width_pt: pageWidthPt,
    page_height_pt: pageHeightPt,
    margins_pt: marginsPt,
    template_profile: isAtsMu ? 'ATS-MU 6-Page Arabic RTL Lesson Plan' : 'Custom DOCX Lesson Plan Template',
    locked_identity_markers: lockedMarkers,
    tables,
    fields,
    has_reference_pdf: Boolean(refPdfBuffer),
    reference_pdf_filename: refPdfFilename,
    reference_pdf_pages: refPdfPages,
    reference_pdf_dimensions: refPdfDims,
  };
}

/**
 * XML-Safe paragraph text replacement:
 * Modifies ONLY <w:t> inside existing <w:r> nodes, preserving all w:rPr, w:pPr, w:bidi, w:rtl, fonts, colors.
 */
function setParagraphTextPreserveFormat(doc: XmlDocument, p: XmlElement, newText: string): void {
  const runs = getDirectChildren(p, 'w:r');
  if (runs.length === 0) {
    const r = doc.createElement('w:r');
    const t = doc.createElement('w:t');
    t.setAttribute('xml:space', 'preserve');
    t.textContent = newText;
    r.appendChild(t);
    p.appendChild(r);
    return;
  }

  // Write full text into the first run's <w:t> and clear subsequent <w:t> nodes without stripping run formatting
  let placed = false;
  for (const run of runs) {
    const tNodes = getDirectChildren(run, 'w:t');
    for (const t of tNodes) {
      if (!placed) {
        t.setAttribute('xml:space', 'preserve');
        t.textContent = newText;
        placed = true;
      } else {
        t.textContent = '';
      }
    }
  }

  if (!placed) {
    const t = doc.createElement('w:t');
    t.setAttribute('xml:space', 'preserve');
    t.textContent = newText;
    runs[0].appendChild(t);
  }
}

/**
 * XML-Safe cell injection:
 * - Updates existing paragraphs in-place (preserving w:pPr, w:rPr, w:bidi).
 * - Clones the last paragraph XML node ONLY when multi-line content needs extra paragraphs inside the cell.
 * - Never touches w:tcW, w:tcBorders, w:shd, w:gridSpan, or w:vMerge.
 */
function setCellTextXmlSafe(doc: XmlDocument, tc: XmlElement, lines: string[]): void {
  const cleanLines = lines.length > 0 ? lines : [' '];
  const existingPs = getDirectChildren(tc, 'w:p');
  if (existingPs.length === 0) return;

  for (let i = 0; i < cleanLines.length; i++) {
    if (i < existingPs.length) {
      setParagraphTextPreserveFormat(doc, existingPs[i], cleanLines[i]);
    } else {
      const cloned = existingPs[existingPs.length - 1].cloneNode(true) as unknown as XmlElement;
      setParagraphTextPreserveFormat(doc, cloned, cleanLines[i]);
      tc.appendChild(cloned);
    }
  }

  // Clear unused trailing template paragraphs without deleting table geometry
  for (let i = cleanLines.length; i < existingPs.length; i++) {
    setParagraphTextPreserveFormat(doc, existingPs[i], '');
  }
}

/**
 * Toggles checkboxes (☐ -> ☑) strictly in-place inside existing text,
 * never altering the exact original Arabic/English option labels.
 */
export function applyCheckboxSelections(originalText: string, selectedItems: string[]): string {
  const normalizedSelected = selectedItems.map((s) => s.replace(/\s+/g, ' ').trim());
  const parts = originalText.split(/(?=[☐☑])/);

  return parts
    .map((part) => {
      if (!part.startsWith('☐') && !part.startsWith('☑')) return part;
      const optionLabel = part.slice(1).trim();
      const isMatch = normalizedSelected.some((sel) => {
        if (!sel) return false;
        return (
          optionLabel === sel ||
          optionLabel.includes(sel) ||
          sel.includes(optionLabel) ||
          // Handle slight Arabic spelling variations like أدوار vs ادوار
          optionLabel.replace(/[أإآ]/g, 'ا') === sel.replace(/[أإآ]/g, 'ا')
        );
      });
      return (isMatch ? '☑' : '☐') + part.slice(1);
    })
    .join('');
}

export interface InjectionResult {
  docxBuffer: Buffer;
  injectedCount: number;
  checkboxesChecked: number;
  overflowFields: Array<{ field_label: string; char_count: number; max_chars: number }>;
  xmlChecks: {
    tablesBefore: number;
    tablesAfter: number;
    cellsBefore: number;
    cellsAfter: number;
    widthsUnchanged: boolean;
    bidiPreserved: boolean;
  };
}

export async function injectLessonPlanIntoDocx(
  templateBuffer: Buffer,
  schema: TemplateSchema,
  payload: LessonPlanPayload
): Promise<InjectionResult> {
  const zip = await JSZip.loadAsync(templateBuffer);
  const docFile = zip.file('word/document.xml');
  if (!docFile) {
    throw new Error('Template missing word/document.xml');
  }

  const origXml = await docFile.async('string');
  const parser = new DOMParser();
  const doc = parser.parseFromString(origXml, 'text/xml');

  const tablesBefore = doc.getElementsByTagName('w:tbl').length;
  const cellsBefore = doc.getElementsByTagName('w:tc').length;
  const bidiBefore = doc.getElementsByTagName('w:bidi').length + doc.getElementsByTagName('w:bidiVisual').length;
  const widthsBefore = Array.from(doc.getElementsByTagName('w:tcW')).map((n) => n.getAttribute('w:w') ?? '');

  const tblElements = Array.from(doc.getElementsByTagName('w:tbl'));
  let injectedCount = 0;
  let checkboxesChecked = 0;
  const overflowFields: Array<{ field_label: string; char_count: number; max_chars: number }> = [];

  const checkOverflow = (label: string, text: string, maxChars: number) => {
    if (text.length > maxChars) {
      overflowFields.push({ field_label: label, char_count: text.length, max_chars: maxChars });
    }
  };

  // Helper to safely update a specific cell by table, row, col
  const writeCell = (tIdx: number, rIdx: number, cIdx: number, lines: string[], label: string, maxChars = 400) => {
    const tbl = tblElements[tIdx];
    if (!tbl) return;
    const trs = getDirectChildren(tbl, 'w:tr');
    const tr = trs[rIdx];
    if (!tr) return;
    const tcs = getDirectChildren(tr, 'w:tc');
    const tc = tcs[cIdx];
    if (!tc) return;
    setCellTextXmlSafe(doc, tc, lines);
    injectedCount++;
    checkOverflow(label, lines.join(' '), maxChars);
  };

  // Walk every table/row/cell using label-guided & structural matching so it works both for ATS-MU and arbitrary templates
  let rubricTableCount = 0;
  let elementHeaderCount = 0;
  let activityRowCount = 0;

  tblElements.forEach((tbl, tIdx) => {
    const trs = getDirectChildren(tbl, 'w:tr');

    // Detect rubric tables (Page 6: مجموعة ( ١ ) and مجموعة ( ٢ ) with -1 to -6)
    const firstRowText = trs[0] ? getElementText(trs[0]).trim() : '';
    const secondRowText = trs[1] ? getElementText(trs[1]).trim() : '';
    if (/^-1\s*$/.test(secondRowText) && trs.length >= 7) {
      rubricTableCount++;
      const items = rubricTableCount === 1 ? payload.rubric_group_1_items : payload.rubric_group_2_items;
      const headerLabel = rubricTableCount === 1 ? payload.rubric_group_1_header : payload.rubric_group_2_header;
      if (headerLabel && !firstRowText.includes(headerLabel)) {
        writeCell(tIdx, 0, 0, [`${firstRowText} — ${headerLabel}`], firstRowText, 180);
      }
      for (let k = 0; k < 6; k++) {
        const val = items[k] ?? '';
        writeCell(tIdx, k + 1, 0, [`-${k + 1} ${val}`.trim()], `${firstRowText} -${k + 1}`, 220);
      }
      return;
    }

    trs.forEach((tr, rIdx) => {
      const tcs = getDirectChildren(tr, 'w:tc');

      // Special handling for 2-column Activity Procedures row (below إجراءات النشاط headers)
      if (rIdx > 0 && tcs.length === 2) {
        const prevRowText = getElementText(trs[rIdx - 1]);
        if (prevRowText.includes('إجراءات النشاط')) {
          const isSecond = prevRowText.includes('٢') || activityRowCount > 0;
          const act = isSecond ? payload.activity_2 : payload.activity_1;
          writeCell(tIdx, rIdx, 0, act.teacher_procedures.split('\n'), 'إجراءات النشاط (دور المعلم)', 420);
          writeCell(tIdx, rIdx, 1, act.student_procedures.split('\n'), 'إجراءات النشاط (دور الطالب)', 420);
          activityRowCount++;
          return;
        }
      }

      // Single-column value row beneath مجموعة ( ٣ )
      if (rIdx > 0 && tcs.length === 1) {
        const prevText = getElementText(trs[rIdx - 1]).trim();
        if (/مجموعة.*٣/.test(prevText)) {
          writeCell(tIdx, rIdx, 0, payload.assessment_group_3.split('\n'), 'مجموعة ( ٣ )', 900);
          return;
        }
      }

      tcs.forEach((tc, cIdx) => {
        const txt = getElementText(tc).trim();

        // Lesson Element numbered rows (1- to 5-) + adjacent 00:00 time slot
        const elemMatch = txt.match(/^([1-5])-\s*$/);
        if (elemMatch) {
          const idx = parseInt(elemMatch[1], 10) - 1;
          const elem = payload.lesson_elements[idx];
          if (elem) {
            writeCell(tIdx, rIdx, cIdx, [`${idx + 1}- ${elem.title}`], `عنصر الدرس ${idx + 1}`, 180);
            if (cIdx + 1 < tcs.length) {
              writeCell(tIdx, rIdx, cIdx + 1, [elem.time_formatted], `زمن العنصر ${idx + 1}`, 12);
            }
          }
          return;
        }

        // Checkboxes: Teaching strategies, Learning resources, Activity pattern/type
        if (txt.includes('☐') || txt.includes('☑')) {
          const prevLabel = cIdx > 0 ? getElementText(tcs[cIdx - 1]).trim() : '';
          let selected: string[] = [];
          if (/استراتيجيات التدريس/.test(prevLabel)) {
            selected = payload.selected_strategies;
          } else if (/مصادر التعلم/.test(prevLabel)) {
            selected = payload.selected_resources;
          } else if (txt.includes('فردي') || txt.includes('جماعي')) {
            const isSecond = getElementText(tr).includes('٢');
            selected = [isSecond ? payload.activity_2.pattern : payload.activity_1.pattern];
          } else if (txt.includes('دراسة حالة') || txt.includes('بحث')) {
            const isSecond = getElementText(tr).includes('٢');
            selected = [isSecond ? payload.activity_2.activity_type : payload.activity_1.activity_type];
          }
          if (selected.length > 0) {
            const updated = applyCheckboxSelections(txt, selected);
            checkboxesChecked += (updated.match(/☑/g) ?? []).length;
            setCellTextXmlSafe(doc, tc, [updated]);
            injectedCount++;
          }
          return;
        }

        // Activity header row (نشاط ( ١ ) / نشاط ( ٢ )) time cell
        if (/نشاط\s*\(\s*[١1]\s*\)/.test(txt) && cIdx + 1 < tcs.length) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.activity_1.time_formatted], 'زمن نشاط ( ١ )', 12);
          return;
        }
        if (/نشاط\s*\(\s*[٢2]\s*\)/.test(txt) && cIdx + 1 < tcs.length) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.activity_2.time_formatted], 'زمن نشاط ( ٢ )', 12);
          return;
        }

        // Element 1 / Element 2 presentation header rows
        if (/أولا.*العنصر/.test(txt)) {
          elementHeaderCount = 1;
          if (cIdx + 1 < tcs.length) {
            writeCell(
              tIdx,
              rIdx,
              cIdx + 1,
              [`استراتيجية التدريس: ${payload.element_1_strategy}`],
              'استراتيجية العنصر الأول',
              120
            );
          }
          if (cIdx + 2 < tcs.length) {
            writeCell(tIdx, rIdx, cIdx + 2, [payload.element_1_time], 'زمن العنصر الأول', 12);
          }
          return;
        }
        if (/ثانيا.*العنصر/.test(txt)) {
          elementHeaderCount = 2;
          if (cIdx + 1 < tcs.length) {
            writeCell(
              tIdx,
              rIdx,
              cIdx + 1,
              [`استراتيجية التدريس: ${payload.element_2_strategy}`],
              'استراتيجية العنصر الثاني',
              120
            );
          }
          if (cIdx + 2 < tcs.length) {
            writeCell(tIdx, rIdx, cIdx + 2, [payload.element_2_time], 'زمن العنصر الثاني', 12);
          }
          return;
        }

        // Label -> next cell mapping (strictly preserving label cell untouched!)
        if (cIdx + 1 >= tcs.length) return;
        const nextCell = tcs[cIdx + 1];
        const nextText = getElementText(nextCell).trim();

        if (/^برنامج\s*\/\s*مقرر$|^البرنامج\s*\/\s*المقرر$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.program_or_course], txt, 140);
        } else if (/^الاسم$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.teacher_name], txt, 120);
        } else if (/^الوظيفة$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.job_title], txt, 120);
        } else if (/^العام الدراسي$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.academic_year], txt, 40);
        } else if (/^المدرسة$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.school_name], txt, 160);
        } else if (/^الصف$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.grade_level], txt, 80);
        } else if (/^فصل$/.test(txt)) {
          payload.class_sections.forEach((sec, sIdx) => {
            if (cIdx + 1 + sIdx < tcs.length) {
              writeCell(tIdx, rIdx, cIdx + 1 + sIdx, [sec], `فصل ${sIdx + 1}`, 30);
            }
          });
        } else if (/^الوحدة$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.unit_number], txt, 60);
        } else if (/^اسم الوحدة$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.unit_name], txt, 160);
        } else if (/^الفرع$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.branch], txt, 100);
        } else if (/المعرفة|TPK/i.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.knowledge_code], txt, 60);
        } else if (/^الدرس$|^اسم الدرس$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.lesson_title], txt, 180);
        } else if (/^نواتج التعلم$/.test(txt)) {
          const bullets = payload.learning_outcomes.slice(0, 4).map((o) => (o.startsWith('▪') ? o : `▪ ${o}`));
          writeCell(tIdx, rIdx, cIdx + 1, bullets, txt, 600);
        } else if (/التقييم.*مجموعة.*١/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, payload.assessment_group_1.split('\n'), txt, 500);
        } else if (/التقييم.*مجموعة.*٢/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, payload.assessment_group_2.split('\n'), txt, 500);
        } else if (/^الفصل$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.presentation_class], txt, 40);
        } else if (/^المكان$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.location], txt, 80);
        } else if (/^التاريخ$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.lesson_date], txt, 40);
        } else if (/^الزمن$/.test(txt) && /^\d{2}:\d{2}$/.test(nextText)) {
          const formattedTotal = `${String(payload.total_duration_minutes).padStart(2, '0')}:00`;
          writeCell(tIdx, rIdx, cIdx + 1, [formattedTotal], txt, 16);
        } else if (/^التهيئة$/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, payload.warm_up.split('\n'), txt, 450);
        } else if (/وصف مختصر للعنصر الأول/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, payload.element_1_summary.split('\n'), txt, 450);
        } else if (/وصف مختصر للعنصر الثاني/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, payload.element_2_summary.split('\n'), txt, 450);
        } else if (/الغرض النشاط\s*\(\s*٢\s*\)/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.activity_2.purpose], txt, 320);
        } else if (/الغرض النشاط|غرض النشاط/.test(txt)) {
          const useSecond = elementHeaderCount === 2;
          writeCell(tIdx, rIdx, cIdx + 1, [useSecond ? payload.activity_2.purpose : payload.activity_1.purpose], txt, 320);
        } else if (/عزيزي الطالب.*٢/.test(txt)) {
          writeCell(tIdx, rIdx, cIdx + 1, [payload.activity_2.student_note], txt, 320);
        } else if (/عزيزي الطالب/.test(txt)) {
          const useSecond = elementHeaderCount === 2;
          writeCell(
            tIdx,
            rIdx,
            cIdx + 1,
            [useSecond ? payload.activity_2.student_note : payload.activity_1.student_note],
            txt,
            320
          );
        }
      });
    });
  });

  // Verify XML structural invariants after injection
  const tablesAfter = doc.getElementsByTagName('w:tbl').length;
  const cellsAfter = doc.getElementsByTagName('w:tc').length;
  const bidiAfter = doc.getElementsByTagName('w:bidi').length + doc.getElementsByTagName('w:bidiVisual').length;
  const widthsAfter = Array.from(doc.getElementsByTagName('w:tcW')).map((n) => n.getAttribute('w:w') ?? '');
  const widthsUnchanged =
    widthsBefore.length === widthsAfter.length && widthsBefore.every((w, i) => w === widthsAfter[i]);

  const serializer = new XMLSerializer();
  const updatedXml = serializer.serializeToString(doc);
  zip.file('word/document.xml', updatedXml);

  const outBuffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });

  return {
    docxBuffer: outBuffer,
    injectedCount,
    checkboxesChecked,
    overflowFields,
    xmlChecks: {
      tablesBefore,
      tablesAfter,
      cellsBefore,
      cellsAfter,
      widthsUnchanged,
      bidiPreserved: bidiAfter >= bidiBefore,
    },
  };
}
