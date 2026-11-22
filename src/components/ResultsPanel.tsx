const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'https://mostafaatteef.pythonanywhere.com').replace(/\/$/, '');
import React from 'react';
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Download,
  FileText,
  Archive,
} from 'lucide-react';
import type { GeneratedPlanRecord } from '../types';
import type { Strings } from '../i18n';

interface ResultsPanelProps {
  plans: GeneratedPlanRecord[];
  batchDownload: { batchId: string; filename: string } | null;
  t: Strings;
}

function getQaStatus(status: 'pass' | 'warning' | 'fail', t: Strings) {
  if (status === 'pass') {
    return {
      label: t.qaPass,
      textClass: 'text-[#137A74]',
      icon: <CheckCircle2 className="w-4 h-4 text-[#1CA29A] shrink-0" />,
    };
  }
  if (status === 'warning') {
    return {
      label: t.qaWarning,
      textClass: 'text-[#8A6100]',
      icon: <AlertTriangle className="w-4 h-4 text-[#C28A00] shrink-0" />,
    };
  }
  return {
    label: t.qaFail,
    textClass: 'text-rose-700',
    icon: <XCircle className="w-4 h-4 text-rose-600 shrink-0" />,
  };
}

function collectFormattingWarnings(plans: GeneratedPlanRecord[], t: Strings): string[] {
  const warnings: string[] = [];
  const seen = new Set<string>();

  const pushUnique = (msg: string) => {
    if (!seen.has(msg)) {
      seen.add(msg);
      warnings.push(msg);
    }
  };

  for (const plan of plans) {
    if (plan.pdf_available === false) {
      pushUnique(plan.pdf_error || t.warnPdfFailed);
    } else if (!plan.qa_report.libreoffice_used) {
      pushUnique(t.warnPdfFallback);
    }

    if (plan.qa_report.page_count_rendered !== plan.qa_report.page_count_expected) {
      pushUnique(
        t.warnPageCount(plan.qa_report.page_count_rendered, plan.qa_report.page_count_expected)
      );
    }

    if (plan.qa_report.overflow_fields.length > 0) {
      pushUnique(t.warnOverflow(plan.qa_report.overflow_fields.slice(0, 3).join(', ')));
    }

    for (const gate of plan.qa_report.approval_gates) {
      if (gate.severity === 'blocking' || gate.category === 'missing_curriculum_info') {
        pushUnique(gate.message);
      }
    }
  }

  return warnings;
}

export const ResultsPanel: React.FC<ResultsPanelProps> = ({ plans, batchDownload, t }) => {
  if (plans.length === 0) return null;

  const primaryPlan = plans[0];
  const isBatch = plans.length > 1;

  const aggregateStatus: 'pass' | 'warning' | 'fail' = plans.some(
    (p) => p.qa_report.overall_status === 'fail'
  )
    ? 'fail'
    : plans.some((p) => p.qa_report.overall_status === 'warning')
      ? 'warning'
      : 'pass';

  const statusMeta = getQaStatus(aggregateStatus, t);
  const warnings = collectFormattingWarnings(plans, t);

  return (
    <section
      aria-labelledby="results-heading"
      className="rounded-[16px] border border-[#E6E1D3] bg-white overflow-hidden shadow-[0_1px_3px_rgba(20,23,22,0.04)]"
    >
      {/* Subtle Official EBDA Teal + Yellow Top Hairline Accent */}
      <div className="h-[3px] w-full flex" aria-hidden="true">
        <div className="flex-1 bg-[#1CA29A]" />
        <div className="w-16 bg-[#FFD700]" />
      </div>

      <div className="p-5 sm:p-6 space-y-5">
        {/* Success Header & Factual Summary */}
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1.5 min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-[#1CA29A] shrink-0" />
              <h2
                id="results-heading"
                className="text-[16px] font-semibold text-[#141716]"
              >
                {t.planReady}
              </h2>
            </div>

            <div
              dir="auto"
              className="text-[15px] font-medium text-[#141716] font-arabic leading-snug"
            >
              {isBatch
                ? `${primaryPlan.lesson_title} ${t.morePlans(plans.length - 1)}`
                : primaryPlan.lesson_title}
            </div>

            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-[#525B58] font-mono-tabular">
              <span>
                {t.lessonsGenerated(plans.length)}
              </span>
              <span aria-hidden="true">·</span>
              <span>
                {t.minutesValue(
                  primaryPlan.qa_report.time_sum_minutes,
                  primaryPlan.qa_report.target_duration_minutes
                )}
              </span>
              <span aria-hidden="true">·</span>
              <span>
                {t.pagesValue(
                  primaryPlan.qa_report.page_count_rendered,
                  primaryPlan.qa_report.page_count_expected
                )}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-1.5 text-[13px] font-semibold shrink-0">
            {statusMeta.icon}
            <span className={statusMeta.textClass}>{t.qualityLabel} {statusMeta.label}</span>
          </div>
        </div>

        {/* Prominent Download Actions */}
        <div className="flex flex-col sm:flex-row flex-wrap items-stretch sm:items-center gap-3">
          <a
            href={`${API_BASE_URL}/api/download/${primaryPlan.plan_id}/docx`}
            className="inline-flex items-center justify-center gap-2 min-h-[44px] px-5 py-2.5 text-[14px] font-semibold rounded-[12px] bg-[#137A74] hover:bg-[#0F6661] text-white transition-colors whitespace-nowrap shrink-0"
          >
            <Download className="w-4 h-4" />
            {t.downloadDocx}
          </a>

          {primaryPlan.pdf_available === false ? (
            <button
              type="button"
              disabled
              className="inline-flex items-center justify-center gap-2 min-h-[44px] px-5 py-2.5 text-[14px] font-medium rounded-[12px] border border-rose-200 bg-rose-50 text-rose-700 cursor-not-allowed whitespace-nowrap shrink-0"
            >
              <XCircle className="w-4 h-4" />
              {t.pdfUnavailable}
            </button>
          ) : (
            <a
              href={`${API_BASE_URL}/api/download/${primaryPlan.plan_id}/pdf`}
              className="inline-flex items-center justify-center gap-2 min-h-[44px] px-5 py-2.5 text-[14px] font-semibold rounded-[12px] border border-[#CBC0A3] bg-white hover:bg-[#FFEAAF]/25 text-[#141716] transition-colors whitespace-nowrap shrink-0"
            >
              <FileText className="w-4 h-4 text-[#137A74]" />
              {t.downloadPdf}
            </a>
          )}

          {isBatch && batchDownload && (
            <a
              href={`${API_BASE_URL}/api/download/batch/${batchDownload.batchId}`}
              className="inline-flex items-center justify-center gap-2 min-h-[44px] px-5 py-2.5 text-[14px] font-semibold rounded-[12px] border border-[#1CA29A]/40 bg-[#FFEAAF]/30 hover:bg-[#FFEAAF]/50 text-[#141716] transition-colors whitespace-nowrap shrink-0"
            >
              <Archive className="w-4 h-4 text-[#137A74]" />
              {t.downloadAllZip}
            </a>
          )}
        </div>

        {/* Multi-Lesson Individual Downloads (compact list only when >1 lesson) */}
        {isBatch && (
          <div className="rounded-[12px] border border-[#EFECE2] divide-y divide-[#EFECE2] bg-[#FAF9F5]/60">
            {plans.map((plan, idx) => (
              <div
                key={plan.plan_id}
                className="px-3.5 py-2.5 flex flex-wrap items-center justify-between gap-3 text-[13px]"
              >
                <div dir="auto" className="min-w-0 flex-1 font-medium text-[#141716] font-arabic truncate">
                  <span className="font-mono-tabular text-[#525B58] mr-1.5">{idx + 1}.</span>
                  {plan.lesson_title}
                </div>
                <div className="flex items-center gap-3 shrink-0 text-[12.5px] font-medium">
                  <a
                    href={`${API_BASE_URL}/api/download/${plan.plan_id}/docx`}
                    className="text-[#137A74] hover:underline whitespace-nowrap"
                  >
                    {t.wordLink}
                  </a>
                  {plan.pdf_available !== false ? (
                    <a
                      href={`${API_BASE_URL}/api/download/${plan.plan_id}/pdf`}
                      className="text-[#525B58] hover:text-[#141716] hover:underline whitespace-nowrap"
                    >
                      {t.pdfLink}
                    </a>
                  ) : (
                    <span className="text-rose-700 whitespace-nowrap">{t.pdfFailed}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Honest Document-Formatting Warnings */}
        {warnings.length > 0 && (
          <div className="rounded-[12px] bg-[#FFEAAF]/25 border border-[#CBC0A3]/60 px-4 py-3 space-y-1.5">
            <div className="flex items-center gap-1.5 text-[12.5px] font-semibold text-[#6E4D00]">
              <AlertTriangle className="w-3.5 h-3.5 text-[#B57F00] shrink-0" />
              <span>{t.notesTitle}</span>
            </div>
            <ul className="space-y-1 text-[12.5px] text-[#525B58] leading-relaxed">
              {warnings.map((w, idx) => (
                <li key={idx}>• {w}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
};
