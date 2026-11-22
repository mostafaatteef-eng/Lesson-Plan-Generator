import React from 'react';
import { Check, Loader2, AlertCircle, RotateCcw } from 'lucide-react';
import type { Strings } from '../i18n';

interface GenerationProgressProps {
  activeStageIndex: number;
  selectedCount: number;
  error: string | null;
  onRetry: () => void;
  t: Strings;
}

export const GenerationProgress: React.FC<GenerationProgressProps> = ({
  activeStageIndex,
  selectedCount,
  error,
  onRetry,
  t,
}) => {
  const GENERATION_STAGES = t.stages;
  if (error) {
    return (
      <div
        role="alert"
        className="rounded-[14px] border border-rose-200 bg-rose-50/60 p-5 space-y-3"
      >
        <div className="flex items-start gap-2.5">
          <AlertCircle className="w-4 h-4 text-rose-700 shrink-0 mt-0.5" />
          <div className="space-y-1 min-w-0">
            <div className="text-[14px] font-semibold text-rose-900">
              {t.generationFailed}
            </div>
            <p className="text-[13px] text-rose-800 leading-relaxed">{error}</p>
          </div>
        </div>
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center gap-2 min-h-[40px] px-4 py-2 text-[13px] font-semibold rounded-[10px] bg-[#137A74] hover:bg-[#0F6661] text-white transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            {t.tryAgain}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-[14px] border border-[#E6E1D3] bg-white p-5 space-y-4"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Loader2 className="w-4 h-4 animate-spin text-[#137A74] shrink-0" />
          <span className="text-[14px] font-semibold text-[#141716]">
            {GENERATION_STAGES[activeStageIndex] || t.processing}…
          </span>
        </div>
        <span className="text-[12px] text-[#525B58] font-mono-tabular">
          {t.lessonsCount(selectedCount)}
        </span>
      </div>

      <ol className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 pt-1 border-t border-[#EFECE2]">
        {GENERATION_STAGES.map((stage, idx) => {
          const isComplete = idx < activeStageIndex;
          const isCurrent = idx === activeStageIndex;
          return (
            <li
              key={stage}
              className={`flex items-center gap-2.5 text-[13px] py-0.5 ${
                isCurrent
                  ? 'font-medium text-[#141716]'
                  : isComplete
                    ? 'text-[#137A74]'
                    : 'text-[#8B928F]'
              }`}
            >
              <span className="w-4 h-4 flex items-center justify-center shrink-0">
                {isComplete ? (
                  <Check className="w-3.5 h-3.5 text-[#1CA29A]" />
                ) : isCurrent ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-[#1CA29A]" />
                ) : (
                  <span className="text-[11px] font-mono-tabular text-[#CBC0A3]">
                    {idx + 1}
                  </span>
                )}
              </span>
              <span>{stage}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
};
