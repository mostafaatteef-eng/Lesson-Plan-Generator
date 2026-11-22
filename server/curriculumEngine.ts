import crypto from 'crypto';
import JSZip from 'jszip';
import { DOMParser } from '@xmldom/xmldom';
import { PDFDocument, StandardFonts, rgb } from 'pdf-lib';
import type { CurriculumUnit, LessonBoundary } from './types';

function detectLanguage(text: string): 'ar' | 'en' | 'mixed' {
  const arMatches = text.match(/[\u0600-\u06FF]/g)?.length ?? 0;
  const enMatches = text.match(/[A-Za-z]/g)?.length ?? 0;
  if (arMatches > 20 && enMatches > 20) {
    const ratio = arMatches / (arMatches + enMatches);
    if (ratio > 0.75) return 'ar';
    if (ratio < 0.25) return 'en';
    return 'mixed';
  }
  return arMatches >= enMatches ? 'ar' : 'en';
}

function extractKeyConcepts(text: string): string[] {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 4);
  const concepts: string[] = [];
  for (const line of lines) {
    const m = line.match(/^(?:\d+[.)\-]|[-•▪*]|\u2022)\s*([^:–—\n]{4,70})/);
    if (m && m[1]) {
      concepts.push(m[1].trim());
    } else if (line.includes(':') && line.length < 95) {
      const prefix = line.split(':')[0].trim();
      if (prefix.length >= 4 && prefix.length <= 60) {
        concepts.push(prefix);
      }
    }
    if (concepts.length >= 6) break;
  }
  return Array.from(new Set(concepts)).slice(0, 6);
}

async function extractTextFromPdf(buffer: Buffer): Promise<{
  pages: Array<{ page_number: number; text: string }>;
  ocr_used: boolean;
  warnings: string[];
}> {
  const warnings: string[] = [];
  try {
    const pdfjsLib = await import('pdfjs-dist/legacy/build/pdf.mjs');
    const loadingTask = pdfjsLib.getDocument({
      data: new Uint8Array(buffer),
      useSystemFonts: true,
      disableFontFace: true,
    });
    const doc = await loadingTask.promise;
    const pages: Array<{ page_number: number; text: string }> = [];
    let emptyPages = 0;

    for (let i = 1; i <= doc.numPages; i++) {
      const page = await doc.getPage(i);
      const content = await page.getTextContent();
      const strings = content.items
        .map((item) => ('str' in item ? (item as { str: string }).str : ''))
        .join(' ')
        .replace(/\s{2,}/g, ' ')
        .trim();
      if (strings.length < 15) emptyPages++;
      pages.push({ page_number: i, text: strings });
    }

    if (emptyPages > 0) {
      warnings.push(
        `${emptyPages} page(s) contained sparse or scanned text; review lesson boundaries carefully before generation.`
      );
    }

    return { pages, ocr_used: false, warnings };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    warnings.push(`PDF text parser fallback triggered (${msg}).`);
    return {
      pages: [{ page_number: 1, text: buffer.toString('utf8').replace(/[^\x20-\x7E\u0600-\u06FF\n]/g, ' ') }],
      ocr_used: false,
      warnings,
    };
  }
}

async function extractTextFromDocx(buffer: Buffer): Promise<Array<{ page_number: number; text: string }>> {
  const zip = await JSZip.loadAsync(buffer);
  const docFile = zip.file('word/document.xml');
  if (!docFile) {
    throw new Error('Invalid DOCX archive: missing word/document.xml');
  }
  const xml = await docFile.async('string');
  const parser = new DOMParser();
  const doc = parser.parseFromString(xml, 'text/xml');
  const paragraphs = Array.from(doc.getElementsByTagName('w:p'));

  const pages: string[][] = [[]];
  for (const p of paragraphs) {
    const brs = Array.from(p.getElementsByTagName('w:br'));
    const hasPageBreak = brs.some((b) => b.getAttribute('w:type') === 'page');
    const tNodes = Array.from(p.getElementsByTagName('w:t'));
    const line = tNodes
      .map((t) => t.textContent ?? '')
      .join('')
      .trim();
    if (line) {
      pages[pages.length - 1].push(line);
    }
    if (hasPageBreak) {
      pages.push([]);
    }
  }

  const nonEmpty = pages.filter((p) => p.length > 0);
  if (nonEmpty.length === 0) {
    return [{ page_number: 1, text: '' }];
  }
  return nonEmpty.map((lines, idx) => ({
    page_number: idx + 1,
    text: lines.join('\n'),
  }));
}

async function extractTextFromPptx(buffer: Buffer): Promise<Array<{ page_number: number; text: string }>> {
  const zip = await JSZip.loadAsync(buffer);
  const slideNames = Object.keys(zip.files)
    .filter((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name))
    .sort((a, b) => {
      const na = parseInt(a.match(/\d+/)?.[0] ?? '0', 10);
      const nb = parseInt(b.match(/\d+/)?.[0] ?? '0', 10);
      return na - nb;
    });

  const parser = new DOMParser();
  const pages: Array<{ page_number: number; text: string }> = [];

  for (let i = 0; i < slideNames.length; i++) {
    const xml = await zip.file(slideNames[i])!.async('string');
    const doc = parser.parseFromString(xml, 'text/xml');
    const texts = Array.from(doc.getElementsByTagName('a:t'))
      .map((n) => n.textContent ?? '')
      .filter((s) => s.trim().length > 0);
    pages.push({ page_number: i + 1, text: texts.join('\n') });
  }

  return pages.length > 0 ? pages : [{ page_number: 1, text: '' }];
}

function splitPlainTextIntoPages(text: string): Array<{ page_number: number; text: string }> {
  const markerRegex = /---\s*PAGE\s+(\d+)\s*---/gi;
  if (markerRegex.test(text)) {
    const chunks = text.split(/---\s*PAGE\s+\d+\s*---/gi).map((c) => c.trim());
    const preamble = chunks[0];
    const bodyPages = chunks.slice(1).filter((c) => c.length > 0);
    return bodyPages.map((chunk, idx) => ({
      page_number: idx + 1,
      text: idx === 0 && preamble ? `${preamble}\n${chunk}` : chunk,
    }));
  }

  // Chunk long plain text into ~1800-char logical pages without splitting mid-paragraph
  const paragraphs = text.split(/\n{2,}/);
  const pages: Array<{ page_number: number; text: string }> = [];
  let current = '';
  for (const para of paragraphs) {
    if (current.length + para.length > 2000 && current.length > 0) {
      pages.push({ page_number: pages.length + 1, text: current.trim() });
      current = para;
    } else {
      current = current ? `${current}\n\n${para}` : para;
    }
  }
  if (current.trim()) {
    pages.push({ page_number: pages.length + 1, text: current.trim() });
  }
  return pages.length > 0 ? pages : [{ page_number: 1, text }];
}

const LESSON_HEADER_PATTERNS: RegExp[] = [
  /^(?:الدرس)\s+(?:الأول|الاول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر|الحادي عشر|الثاني عشر|\d+|[١-٩٠]+)\s*[:\-–—]?\s*(.*)$/i,
  /^(?:Lesson|Topic|Session|Module)\s+(\d+|[IVX]+)\s*[:\-–—]?\s*(.*)$/i,
  /^(?:الموضوع|المحور)\s+(?:الأول|الثاني|الثالث|الرابع|\d+)\s*[:\-–—]?\s*(.*)$/i,
];

const UNIT_HEADER_PATTERNS: RegExp[] = [
  /^(?:الوحدة)\s+(?:الأولى|الاولى|الثانية|الثالثة|الرابعة|الخامسة|السادسة|\d+|[١-٩٠]+)\s*[:\-–—]?\s*(.*)$/i,
  /^(?:Unit|Chapter)\s+(\d+|[IVX]+)\s*[:\-–—]?\s*(.*)$/i,
];

export function detectLessonBoundaries(
  pages: Array<{ page_number: number; text: string }>,
  fallbackTitle: string
): { unitTitle: string; lessons: LessonBoundary[]; warnings: string[] } {
  const warnings: string[] = [];
  let unitTitle = fallbackTitle.replace(/\.[^.]+$/, '');

  // Search for explicit unit header on early pages
  for (const page of pages.slice(0, 2)) {
    const lines = page.text.split(/\r?\n/).map((l) => l.trim());
    for (const line of lines) {
      for (const pat of UNIT_HEADER_PATTERNS) {
        if (pat.test(line)) {
          unitTitle = line;
          break;
        }
      }
      if (unitTitle !== fallbackTitle.replace(/\.[^.]+$/, '')) break;
    }
  }

  interface DetectedHit {
    pageNumber: number;
    lineIndex: number;
    title: string;
    confidence: number;
  }

  const hits: DetectedHit[] = [];

  for (const page of pages) {
    const lines = page.text.split(/\r?\n/);
    lines.forEach((rawLine, idx) => {
      const line = rawLine.trim();
      if (!line || line.length > 160) return;
      for (const pat of LESSON_HEADER_PATTERNS) {
        if (pat.test(line)) {
          hits.push({
            pageNumber: page.page_number,
            lineIndex: idx,
            title: line,
            confidence: 0.94,
          });
          break;
        }
      }
    });
  }

  const lessons: LessonBoundary[] = [];

  if (hits.length === 0) {
    // Ambiguous single-lesson fallback — flagged explicitly for human approval
    const allText = pages.map((p) => p.text).join('\n\n').trim();
    const firstNonEmpty = allText.split(/\r?\n/).find((l) => l.trim().length > 3)?.trim() ?? unitTitle;
    warnings.push(
      'No explicit lesson boundary headers (e.g. "الدرس الأول" or "Lesson 1") were detected. Flagged for manual boundary review.'
    );
    lessons.push({
      lesson_id: `lsn_${crypto.randomBytes(4).toString('hex')}`,
      lesson_number: 1,
      title: firstNonEmpty.slice(0, 100),
      start_page: 1,
      end_page: Math.max(1, pages.length),
      raw_text: allText,
      word_count: allText.split(/\s+/).filter(Boolean).length,
      confidence: 0.55,
      is_ambiguous: true,
      ambiguity_reason: 'No explicit lesson headings detected; entire document grouped as Lesson 1.',
      approved: false,
      key_concepts: extractKeyConcepts(allText),
    });
    return { unitTitle, lessons, warnings };
  }

  // Slice exact text between detected lesson headers
  const flatLines: Array<{ pageNumber: number; text: string; isHitIndex?: number }> = [];
  for (const page of pages) {
    const lines = page.text.split(/\r?\n/);
    lines.forEach((text, lineIdx) => {
      const hitIdx = hits.findIndex((h) => h.pageNumber === page.page_number && h.lineIndex === lineIdx);
      flatLines.push({
        pageNumber: page.page_number,
        text,
        isHitIndex: hitIdx >= 0 ? hitIdx : undefined,
      });
    });
  }

  const hitPositions = flatLines
    .map((item, idx) => (item.isHitIndex !== undefined ? { flatIdx: idx, hit: hits[item.isHitIndex] } : null))
    .filter((v): v is { flatIdx: number; hit: DetectedHit } => v !== null);

  for (let i = 0; i < hitPositions.length; i++) {
    const startPos = hitPositions[i].flatIdx;
    const endPos = i + 1 < hitPositions.length ? hitPositions[i + 1].flatIdx : flatLines.length;
    const slice = flatLines.slice(startPos, endPos);
    const rawText = slice
      .map((s) => s.text)
      .join('\n')
      .trim();
    const startPage = slice[0]?.pageNumber ?? hitPositions[i].hit.pageNumber;
    const endPage = slice[slice.length - 1]?.pageNumber ?? startPage;
    const wordCount = rawText.split(/\s+/).filter(Boolean).length;
    const isShort = wordCount < 35;

    lessons.push({
      lesson_id: `lsn_${crypto.randomBytes(4).toString('hex')}`,
      lesson_number: i + 1,
      title: hitPositions[i].hit.title,
      start_page: startPage,
      end_page: endPage,
      raw_text: rawText,
      word_count: wordCount,
      confidence: isShort ? 0.68 : hitPositions[i].hit.confidence,
      is_ambiguous: isShort,
      ambiguity_reason: isShort
        ? 'Extracted lesson text is unusually short (< 35 words). Confirm start/end page boundaries.'
        : undefined,
      approved: !isShort,
      key_concepts: extractKeyConcepts(rawText),
    });
  }

  return { unitTitle, lessons, warnings };
}

export async function ingestCurriculumFile(
  buffer: Buffer,
  filename: string
): Promise<{ unit: CurriculumUnit; originalBuffer: Buffer }> {
  const ext = filename.split('.').pop()?.toLowerCase() ?? 'txt';
  let pages: Array<{ page_number: number; text: string }> = [];
  let ocrUsed = false;
  let warnings: string[] = [];
  let fileFormat: CurriculumUnit['file_format'] = 'txt';

  if (ext === 'pdf') {
    fileFormat = 'pdf';
    const res = await extractTextFromPdf(buffer);
    pages = res.pages;
    ocrUsed = res.ocr_used;
    warnings = res.warnings;
  } else if (ext === 'docx') {
    fileFormat = 'docx';
    pages = await extractTextFromDocx(buffer);
  } else if (ext === 'pptx') {
    fileFormat = 'pptx';
    pages = await extractTextFromPptx(buffer);
  } else {
    fileFormat = 'txt';
    pages = splitPlainTextIntoPages(buffer.toString('utf8'));
  }

  const fullText = pages.map((p) => p.text).join('\n');
  const language = detectLanguage(fullText);
  const { unitTitle, lessons, warnings: boundaryWarnings } = detectLessonBoundaries(pages, filename);
  const allWarnings = [...warnings, ...boundaryWarnings];
  const hasAmbiguous = lessons.some((l) => l.is_ambiguous);
  const avgCharsPerPage = fullText.trim().length / Math.max(1, pages.length);
  const extractionQuality: CurriculumUnit['extraction_quality'] =
    allWarnings.length > 0 || hasAmbiguous || avgCharsPerPage < 80
      ? 'needs_review'
      : ocrUsed || avgCharsPerPage < 240
        ? 'medium'
        : 'high';

  const unit: CurriculumUnit = {
    unit_id: `unit_${crypto.randomBytes(4).toString('hex')}`,
    filename,
    file_format: fileFormat,
    file_size_bytes: buffer.length,
    extraction_quality: extractionQuality,
    language,
    unit_title: unitTitle,
    total_pages: pages.length,
    ocr_used: ocrUsed,
    uploaded_at: new Date().toISOString(),
    pages,
    lessons,
    warnings: allWarnings,
  };

  return { unit, originalBuffer: buffer };
}

export function updateUnitBoundaries(
  unit: CurriculumUnit,
  updates: Array<{
    lesson_id: string;
    title: string;
    start_page: number;
    end_page: number;
    approved: boolean;
  }>
): CurriculumUnit {
  const updatedLessons: LessonBoundary[] = updates.map((u, idx) => {
    const existing = unit.lessons.find((l) => l.lesson_id === u.lesson_id);
    const startPage = Math.max(1, Math.min(unit.total_pages, u.start_page));
    const endPage = Math.max(startPage, Math.min(unit.total_pages, u.end_page));

    const slicedText =
      existing && existing.start_page === startPage && existing.end_page === endPage
        ? existing.raw_text
        : unit.pages
            .filter((p) => p.page_number >= startPage && p.page_number <= endPage)
            .map((p) => p.text)
            .join('\n\n')
            .trim();

    const wasModified = Boolean(
      !existing ||
        existing.title !== u.title.trim() ||
        existing.start_page !== startPage ||
        existing.end_page !== endPage
    );

    return {
      lesson_id: u.lesson_id || `lsn_${crypto.randomBytes(4).toString('hex')}`,
      lesson_number: idx + 1,
      title: u.title.trim() || `Lesson ${idx + 1}`,
      start_page: startPage,
      end_page: endPage,
      raw_text: slicedText,
      word_count: slicedText.split(/\s+/).filter(Boolean).length,
      confidence: u.approved ? 1.0 : existing?.confidence ?? 0.85,
      is_ambiguous: u.approved ? false : existing?.is_ambiguous ?? false,
      ambiguity_reason: u.approved ? undefined : existing?.ambiguity_reason,
      approved: u.approved,
      user_modified: existing?.user_modified || wasModified,
      key_concepts: extractKeyConcepts(slicedText),
    };
  });

  const allApproved = updatedLessons.every((l) => l.approved);

  return {
    ...unit,
    extraction_quality: allApproved && unit.warnings.length === 0 ? 'high' : unit.extraction_quality,
    lessons: updatedLessons,
  };
}

/**
 * Exports a separate PDF for a specific lesson.
 * If the source curriculum was a PDF, slices the exact page range cleanly using pdf-lib.
 * Otherwise builds a structured single-lesson source PDF.
 */
export async function exportLessonPdf(
  unit: CurriculumUnit,
  lesson: LessonBoundary,
  originalBuffer?: Buffer
): Promise<Buffer> {
  if (unit.file_format === 'pdf' && originalBuffer) {
    try {
      const srcPdf = await PDFDocument.load(originalBuffer);
      const outPdf = await PDFDocument.create();
      const totalSrcPages = srcPdf.getPageCount();
      const indices: number[] = [];
      for (let p = lesson.start_page; p <= lesson.end_page; p++) {
        if (p >= 1 && p <= totalSrcPages) indices.push(p - 1);
      }
      if (indices.length > 0) {
        const copied = await outPdf.copyPages(srcPdf, indices);
        copied.forEach((pg) => outPdf.addPage(pg));
        return Buffer.from(await outPdf.save());
      }
    } catch {
      // Fallback to structured export below
    }
  }

  const pdfDoc = await PDFDocument.create();
  const font = await pdfDoc.embedFont(StandardFonts.Helvetica);
  const bold = await pdfDoc.embedFont(StandardFonts.HelveticaBold);

  const page = pdfDoc.addPage([595.28, 841.89]);
  page.drawRectangle({
    x: 40,
    y: 775,
    width: 515,
    height: 32,
    color: rgb(0.059, 0.361, 0.361),
  });
  page.drawText(`Lesson ${lesson.lesson_number} Source Extract (Pages ${lesson.start_page}-${lesson.end_page})`, {
    x: 52,
    y: 787,
    size: 12,
    font: bold,
    color: rgb(1, 1, 1),
  });

  const safeAscii = (s: string) => s.replace(/[^\x20-\x7E]/g, ' ').replace(/\s+/g, ' ').trim();
  const asciiTitle = safeAscii(lesson.title) || `Lesson ${lesson.lesson_number} (Arabic Source Content)`;
  page.drawText(`Unit Source: ${safeAscii(unit.filename)}`, {
    x: 40,
    y: 748,
    size: 10,
    font: bold,
    color: rgb(0.15, 0.23, 0.32),
  });
  page.drawText(`Lesson Title: ${asciiTitle.slice(0, 82)}`, {
    x: 40,
    y: 730,
    size: 10,
    font,
    color: rgb(0.25, 0.33, 0.42),
  });
  page.drawText(
    `Language: ${unit.language.toUpperCase()} | Word Count: ${lesson.word_count} | Pages: ${lesson.start_page}-${lesson.end_page}`,
    {
      x: 40,
      y: 712,
      size: 9,
      font,
      color: rgb(0.4, 0.48, 0.55),
    }
  );

  // Render ASCII/Latin tokens & line count summary safely (StandardFonts Helvetica supports WinAnsi)
  const lines = lesson.raw_text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  let y = 682;
  page.drawText(`Extracted Content Lines (${lines.length} lines preserved verbatim in UTF-8 JSON):`, {
    x: 40,
    y,
    size: 10,
    font: bold,
    color: rgb(0.059, 0.361, 0.361),
  });
  y -= 20;

  for (const line of lines.slice(0, 32)) {
    if (y < 60) break;
    const printable = safeAscii(line);
    const display = printable.length > 3 ? printable.slice(0, 92) : '[Arabic UTF-8 Curriculum Line Preserved]';
    page.drawText(display, {
      x: 44,
      y,
      size: 8.5,
      font,
      color: rgb(0.2, 0.25, 0.32),
    });
    y -= 16;
  }

  return Buffer.from(await pdfDoc.save());
}
