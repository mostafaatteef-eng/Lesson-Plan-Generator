import React from 'react';
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Download,
  FileText,
  Archive,
} from 'lucide-react';
import type { GeneratedPlanRecord, GenerationFailure } from '../types';
import type { Strings } from '../i18n';

/** Browser-held artifact URLs decoded from the generation response. */
export interface PlanArtifacts {
  docxUrl: string;
  docxName: string;
  pdfUrl: string | null;
  pdfName: string | null;
}

export interface ZipArtifact {
  url: string;
  filename: string;
}

interface ResultsPanelProps {
  plans: GeneratedPlanRecord[];
  artifacts: Record<string, PlanArtifacts>;
  batchDownload: ZipArtifact | null;
  failures: GenerationFailure[];
  t: Strings;
}

function saveBlob(objUrl: string, filename: string) {
  const a = document.createElement('a');
  a.href = objUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function getQaStatus(status: 'pass' | 'warning' | 'fail', t: Strings) {
  if (status === 'pass') {
    return {
      label: t.qaPass,
      textClass: 'text-[#116962]',
      icon: <CheckCircle2 className="w-4 h-4 text-[#168B83] shrink-0" />,
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
      pushUnique(t.warnPdfFailed);
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

function FailuresList({ items, t }: { items: GenerationFailure[]; t: Strings }) {
  if (items.length === 0) return null;
  return (
    <div
      role="alert"
      className="rounded-[12px] border border-rose-200 bg-rose-50 px-4 py-3 space-y-1.5"
    >
      <div className="flex items-center gap-1.5 text-[12.5px] font-semibold text-rose-800">
        <XCircle className="w-3.5 h-3.5 shrink-0" />
        <span>{t.failuresTitle}</span>
      </div>
      <ul className="space-y-1 text-[12.5px] text-rose-700 leading-relaxed">
        {items.map((f) => (
          <li key={f.lesson_id}>
            • <span dir="auto" className="font-arabic font-medium">{f.lesson_title}</span>
            {' — '}
            {f.blocking_gates && f.blocking_gates.length > 0
              ? f.blocking_gates.map((g) => g.message).join('؛ ')
              : f.detail}
          </li>
        ))}
      </ul>
    </div>
  );
}

export const ResultsPanel: React.FC<ResultsPanelProps> = ({
  plans,
  artifacts,
  batchDownload,
  failures,
  t,
}) => {
  // Defensive guard: a plan that arrives without its QA report is never a
  // success. Show it as an honest failure instead of crashing the panel.
  const validPlans = plans.filter((p) => p.qa_report != null);
  const missingQaFailures: GenerationFailure[] = plans
    .filter((p) => p.qa_report == null)
    .map((p) => ({
      lesson_id: p.plan_id,
      lesson_title: p.lesson_title,
      detail: t.errQaMissing,
      qa_blocked: true,
    }));
  const shownFailures = [...failures, ...missingQaFailures];

  if (validPlans.length === 0) {
    if (shownFailures.length === 0) return null;
    return (
      <section
        aria-labelledby="results-heading"
        className="rounded-[16px] border border-[#E3EAE7] bg-white overflow-hidden shadow-[0_1px_3px_rgba(20,23,22,0.04)]"
      >
        <div className="h-[3px] w-full flex" aria-hidden="true">
          <div className="flex-1 bg-[#168B83]" />
          <div className="w-16 bg-[#FFD700]" />
        </div>
        <div className="p-5 sm:p-6 space-y-5">
          <FailuresList items={shownFailures} t={t} />
        </div>
      </section>
    );
  }

  const primaryPlan = validPlans[0];
  const isBatch = validPlans.length > 1;

  const aggregateStatus: 'pass' | 'warning' | 'fail' = validPlans.some(
    (p) => p.qa_report.overall_status === 'fail'
  )
    ? 'fail'
    : validPlans.some((p) => p.qa_report.overall_status === 'warning')
      ? 'warning'
      : 'pass';

  const statusMeta = getQaStatus(aggregateStatus, t);
  const warnings = collectFormattingWarnings(validPlans, t);

  return (
    <section
      aria-labelledby="results-heading"
      className="rounded-[16px] border border-[#E3EAE7] bg-white overflow-hidden shadow-[0_1px_3px_rgba(20,23,22,0.04)]"
    >
      {/* Subtle Official EBDA Teal + Yellow Top Hairline Accent */}
      <div className="h-[3px] w-full flex" aria-hidden="true">
        <div className="flex-1 bg-[#168B83]" />
        <div className="w-16 bg-[#FFD700]" />
      </div>

      <div className="p-5 sm:p-6 space-y-5">
        {/* Success Header & Factual Summary */}
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1.5 min-w-0 flex-1">
            <div className="flex items-center gap-2">
              {aggregateStatus === 'fail' ? (
                <XCircle className="w-4 h-4 text-rose-600 shrink-0" />
              ) : (
                <CheckCircle2 className="w-4 h-4 text-[#168B83] shrink-0" />
              )}
              <h2
                id="results-heading"
                className="text-[16px] font-semibold text-[#17252C]"
              >
                {aggregateStatus === 'fail' ? t.planNotReady : t.planReady}
              </h2>
            </div>

            <div
              dir="auto"
              className="text-[15px] font-medium text-[#17252C] font-arabic leading-snug"
            >
              {isBatch
                ? `${primaryPlan.lesson_title} ${t.morePlans(validPlans.length - 1)}`
                : primaryPlan.lesson_title}
            </div>

            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-[#596A72] font-mono-tabular">
              <span>
                {t.lessonsGenerated(validPlans.length)}
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

        {/* Prominent Download Actions (hidden when quality checks failed) */}
        {aggregateStatus !== 'fail' && (
        <div className="flex flex-col sm:flex-row flex-wrap items-stretch sm:items-center gap-3">
          <button
            type="button"
            onClick={() => {
              const a = artifacts[primaryPlan.plan_id];
              if (a?.docxUrl) saveBlob(a.docxUrl, a.docxName);
            }}
            className="inline-flex items-center justify-center gap-2 min-h-[44px] px-5 py-2.5 text-[14px] font-semibold rounded-[12px] bg-[#116962] hover:bg-[#0A544F] text-white transition-colors whitespace-nowrap shrink-0"
          >
            <Download className="w-4 h-4" />
            {t.downloadDocx}
          </button>

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
            <button
              type="button"
              onClick={() => {
                const a = artifacts[primaryPlan.plan_id];
                if (a?.pdfUrl && a.pdfName) saveBlob(a.pdfUrl, a.pdfName);
              }}
              className="inline-flex items-center justify-center gap-2 min-h-[44px] px-5 py-2.5 text-[14px] font-semibold rounded-[12px] border border-[#CBC0A3] bg-white hover:bg-[#FFF8E9]/25 text-[#17252C] transition-colors whitespace-nowrap shrink-0"
            >
              <FileText className="w-4 h-4 text-[#116962]" />
              {t.downloadPdf}
            </button>
          )}

          {isBatch && batchDownload && (
            <button
              type="button"
              onClick={() => saveBlob(batchDownload.url, batchDownload.filename)}
              className="inline-flex items-center justify-center gap-2 min-h-[44px] px-5 py-2.5 text-[14px] font-semibold rounded-[12px] border border-[#168B83]/40 bg-[#FFF8E9]/30 hover:bg-[#FFF8E9]/50 text-[#17252C] transition-colors whitespace-nowrap shrink-0"
            >
              <Archive className="w-4 h-4 text-[#116962]" />
              {t.downloadAllZip}
            </button>
          )}
        </div>
        )}

        {/* Multi-Lesson Individual Downloads (compact list only when >1 lesson) */}
        {isBatch && (
          <div className="rounded-[12px] border border-[#E3EAE7] divide-y divide-[#E3EAE7] bg-[#F8FAF9]/60">
            {validPlans.map((plan, idx) => (
              <div
                key={plan.plan_id}
                className="px-3.5 py-2.5 flex flex-wrap items-center justify-between gap-3 text-[13px]"
              >
                <div dir="auto" className="min-w-0 flex-1 font-medium text-[#17252C] font-arabic truncate">
                  <span className="font-mono-tabular text-[#596A72] mr-1.5">{idx + 1}.</span>
                  {plan.lesson_title}
                </div>
                <div className="flex items-center gap-3 shrink-0 text-[12.5px] font-medium">
                  <button
                    type="button"
                    onClick={() => {
                      const a = artifacts[plan.plan_id];
                      if (a?.docxUrl) saveBlob(a.docxUrl, a.docxName);
                    }}
                    className="text-[#116962] hover:underline whitespace-nowrap"
                  >
                    {t.wordLink}
                  </button>
                  {plan.pdf_available !== false ? (
                    <button
                      type="button"
                      onClick={() => {
                        const a = artifacts[plan.plan_id];
                        if (a?.pdfUrl && a.pdfName) saveBlob(a.pdfUrl, a.pdfName);
                      }}
                      className="text-[#596A72] hover:text-[#17252C] hover:underline whitespace-nowrap"
                    >
                      {t.pdfLink}
                    </button>
                  ) : (
                    <span className="text-rose-700 whitespace-nowrap">{t.pdfFailed}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        <FailuresList items={shownFailures} t={t} />

        {/* Honest Document-Formatting Warnings */}
        {warnings.length > 0 && (
          <div className="rounded-[12px] bg-[#FFF8E9]/25 border border-[#CBC0A3]/60 px-4 py-3 space-y-1.5">
            <div className="flex items-center gap-1.5 text-[12.5px] font-semibold text-[#6E4D00]">
              <AlertTriangle className="w-3.5 h-3.5 text-[#B57F00] shrink-0" />
              <span>{t.notesTitle}</span>
            </div>
            <ul className="space-y-1 text-[12.5px] text-[#596A72] leading-relaxed">
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
