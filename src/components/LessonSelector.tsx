import React, { useState } from 'react';
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Check,
  SlidersHorizontal,
  Edit2,
} from 'lucide-react';
import type { CurriculumUnit, LessonBoundary } from '../types';

export interface AdvancedOptions {
  gradeLevel: string;
  subject: string;
  durationMinutes: number;
  outputLanguage: 'auto' | 'ar' | 'en';
}

interface LessonSelectorProps {
  unit: CurriculumUnit;
  selectedLessonIds: string[];
  onToggleLesson: (lessonId: string) => void;
  onSelectAll: () => void;
  onSaveBoundaryEdit: (
    lessonId: string,
    patch: { title: string; start_page: number; end_page: number }
  ) => Promise<void>;
  savingBoundary: boolean;
  advanced: AdvancedOptions;
  onChangeAdvanced: (next: AdvancedOptions) => void;
  disabled?: boolean;
}

export const LessonSelector: React.FC<LessonSelectorProps> = ({
  unit,
  selectedLessonIds,
  onToggleLesson,
  onSelectAll,
  onSaveBoundaryEdit,
  savingBoundary,
  advanced,
  onChangeAdvanced,
  disabled = false,
}) => {
  const [editingLessonId, setEditingLessonId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftStart, setDraftStart] = useState(1);
  const [draftEnd, setDraftEnd] = useState(1);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const allSelected =
    unit.lessons.length > 0 && selectedLessonIds.length === unit.lessons.length;

  const beginEdit = (lesson: LessonBoundary) => {
    setEditingLessonId(lesson.lesson_id);
    setDraftTitle(lesson.title);
    setDraftStart(lesson.start_page);
    setDraftEnd(lesson.end_page);
  };

  const commitEdit = async (lessonId: string) => {
    const safeStart = Math.max(1, Math.min(unit.total_pages, Number(draftStart) || 1));
    const safeEnd = Math.max(safeStart, Math.min(unit.total_pages, Number(draftEnd) || safeStart));
    await onSaveBoundaryEdit(lessonId, {
      title: draftTitle.trim() || 'Lesson',
      start_page: safeStart,
      end_page: safeEnd,
    });
    setEditingLessonId(null);
  };

  return (
    <div className="space-y-4">
      {/* Compact Lesson Selector Header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-baseline gap-2">
          <h2 className="text-[15px] font-semibold text-[#141716]">Select Lesson</h2>
          <span className="text-[12.5px] text-[#525B58] font-mono-tabular">
            {selectedLessonIds.length} of {unit.lessons.length} selected
          </span>
        </div>

        {unit.lessons.length > 1 && (
          <button
            type="button"
            disabled={disabled}
            onClick={onSelectAll}
            className="text-[12.5px] font-medium text-[#137A74] hover:text-[#0F6661] hover:underline disabled:opacity-50 whitespace-nowrap shrink-0"
          >
            {allSelected ? 'Select first only' : `Select all (${unit.lessons.length})`}
          </button>
        )}
      </div>

      {/* Lesson List */}
      <div className="rounded-[14px] border border-[#E6E1D3] bg-white divide-y divide-[#EFECE2] overflow-hidden">
        {unit.lessons.map((lesson) => {
          const checked = selectedLessonIds.includes(lesson.lesson_id);
          const isEditing = editingLessonId === lesson.lesson_id;
          const uncertain = lesson.is_ambiguous && !lesson.approved;

          return (
            <div
              key={lesson.lesson_id}
              className={`transition-colors ${
                checked ? 'bg-[#FFEAAF]/18' : 'hover:bg-[#FAF9F5]'
              }`}
            >
              <div className="px-4 py-3.5 flex items-start justify-between gap-3">
                <label className="flex items-start gap-3 min-w-0 flex-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={disabled}
                    onChange={() => onToggleLesson(lesson.lesson_id)}
                    className="mt-0.5 h-4 w-4 rounded border-[#CBC0A3] accent-[#137A74] cursor-pointer shrink-0"
                  />
                  <div className="min-w-0 flex-1 space-y-0.5">
                    <div
                      dir="auto"
                      className="text-[14px] font-medium text-[#141716] font-arabic leading-snug"
                    >
                      <span className="font-mono-tabular text-[#525B58] mr-1.5">
                        {lesson.lesson_number}.
                      </span>
                      {lesson.title}
                    </div>
                    <div className="text-[12px] text-[#525B58] font-mono-tabular flex flex-wrap items-center gap-x-2 gap-y-0.5">
                      <span>
                        Pages {lesson.start_page}–{lesson.end_page}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span>{lesson.word_count} words</span>
                      {lesson.user_modified && (
                        <>
                          <span aria-hidden="true">·</span>
                          <span className="text-[#137A74]">Adjusted</span>
                        </>
                      )}
                    </div>

                    {uncertain && !isEditing && (
                      <div className="pt-1 flex items-start gap-1.5 text-[12px] text-[#8A6100]">
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-[#B57F00]" />
                        <span>
                          {lesson.ambiguity_reason || 'Boundary uncertain — confirm page range.'}
                        </span>
                      </div>
                    )}
                  </div>
                </label>

                {/* Inline boundary adjustment trigger */}
                {!isEditing && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => beginEdit(lesson)}
                    className={`inline-flex items-center gap-1 min-h-[32px] px-2.5 py-1 text-[12px] font-medium rounded-[8px] border transition-colors whitespace-nowrap shrink-0 disabled:opacity-40 ${
                      uncertain
                        ? 'border-[#FFD700] bg-[#FFEAAF]/35 text-[#6E4D00] hover:bg-[#FFEAAF]/55'
                        : 'border-transparent text-[#525B58] hover:border-[#E6E1D3] hover:bg-white hover:text-[#141716]'
                    }`}
                  >
                    <Edit2 className="w-3 h-3" />
                    {uncertain ? 'Fix range' : 'Edit'}
                  </button>
                )}
              </div>

              {/* Inline Boundary Correction Control (same page, zero navigation) */}
              {isEditing && (
                <div className="px-4 pb-4 pt-2 bg-[#FAF9F5] border-t border-[#EFECE2] space-y-3">
                  <div className="grid grid-cols-1 sm:grid-cols-12 gap-2.5">
                    <div className="sm:col-span-6">
                      <label className="block text-[11.5px] font-medium text-[#525B58] mb-1">
                        Lesson title
                      </label>
                      <input
                        type="text"
                        dir="auto"
                        value={draftTitle}
                        onChange={(e) => setDraftTitle(e.target.value)}
                        className="w-full min-h-[38px] rounded-[9px] border border-[#CBC0A3] bg-white px-3 py-1.5 text-[13px] font-arabic text-[#141716]"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-2.5 sm:col-span-6">
                      <div>
                        <label className="block text-[11.5px] font-medium text-[#525B58] mb-1">
                          Start page (1–{unit.total_pages})
                        </label>
                        <input
                          type="number"
                          min={1}
                          max={unit.total_pages}
                          value={draftStart}
                          onChange={(e) => setDraftStart(Number(e.target.value) || 1)}
                          className="w-full min-h-[38px] rounded-[9px] border border-[#CBC0A3] bg-white px-3 py-1.5 text-[13px] font-mono-tabular text-[#141716]"
                        />
                      </div>
                      <div>
                        <label className="block text-[11.5px] font-medium text-[#525B58] mb-1">
                          End page (1–{unit.total_pages})
                        </label>
                        <input
                          type="number"
                          min={1}
                          max={unit.total_pages}
                          value={draftEnd}
                          onChange={(e) => setDraftEnd(Number(e.target.value) || 1)}
                          className="w-full min-h-[38px] rounded-[9px] border border-[#CBC0A3] bg-white px-3 py-1.5 text-[13px] font-mono-tabular text-[#141716]"
                        />
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => setEditingLessonId(null)}
                      className="min-h-[34px] px-3 py-1.5 text-[12px] font-medium rounded-[8px] border border-[#E6E1D3] bg-white text-[#525B58] hover:text-[#141716]"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      disabled={savingBoundary}
                      onClick={() => commitEdit(lesson.lesson_id)}
                      className="inline-flex items-center gap-1.5 min-h-[34px] px-3.5 py-1.5 text-[12px] font-semibold rounded-[8px] bg-[#137A74] hover:bg-[#0F6661] text-white disabled:opacity-50"
                    >
                      <Check className="w-3.5 h-3.5" />
                      {savingBoundary ? 'Saving…' : 'Confirm range'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Minimal Advanced Settings Disclosure (Collapsed by Default) */}
      <div className="rounded-[12px] border border-[#E6E1D3] bg-white overflow-hidden">
        <button
          type="button"
          aria-expanded={advancedOpen}
          disabled={disabled}
          onClick={() => setAdvancedOpen((prev) => !prev)}
          className="w-full px-4 py-3 flex items-center justify-between text-left text-[13px] font-medium text-[#525B58] hover:text-[#141716] transition-colors disabled:opacity-50"
        >
          <span className="inline-flex items-center gap-2">
            <SlidersHorizontal className="w-3.5 h-3.5 text-[#137A74]" />
            <span>Advanced settings</span>
            <span className="text-[12px] text-[#6B726F] font-normal">
              · {advanced.durationMinutes} min ·{' '}
              {advanced.outputLanguage === 'auto'
                ? 'Auto language'
                : advanced.outputLanguage === 'ar'
                  ? 'Arabic'
                  : 'English'}
            </span>
          </span>
          {advancedOpen ? (
            <ChevronUp className="w-4 h-4 text-[#6B726F]" />
          ) : (
            <ChevronDown className="w-4 h-4 text-[#6B726F]" />
          )}
        </button>

        {advancedOpen && (
          <div className="px-4 pb-4 pt-3 border-t border-[#EFECE2] grid grid-cols-1 sm:grid-cols-2 gap-3.5 bg-[#FAF9F5]/60">
            <div>
              <label
                htmlFor="ebda-grade"
                className="block text-[12px] font-medium text-[#525B58] mb-1"
              >
                Grade
              </label>
              <input
                id="ebda-grade"
                type="text"
                dir="auto"
                value={advanced.gradeLevel}
                onChange={(e) =>
                  onChangeAdvanced({ ...advanced, gradeLevel: e.target.value })
                }
                className="w-full min-h-[40px] rounded-[10px] border border-[#E6E1D3] bg-white px-3 py-2 text-[13px] font-arabic text-[#141716]"
              />
            </div>

            <div>
              <label
                htmlFor="ebda-subject"
                className="block text-[12px] font-medium text-[#525B58] mb-1"
              >
                Subject
              </label>
              <input
                id="ebda-subject"
                type="text"
                dir="auto"
                value={advanced.subject}
                onChange={(e) =>
                  onChangeAdvanced({ ...advanced, subject: e.target.value })
                }
                className="w-full min-h-[40px] rounded-[10px] border border-[#E6E1D3] bg-white px-3 py-2 text-[13px] font-arabic text-[#141716]"
              />
            </div>

            <div>
              <label
                htmlFor="ebda-duration"
                className="block text-[12px] font-medium text-[#525B58] mb-1"
              >
                Lesson duration (minutes)
              </label>
              <input
                id="ebda-duration"
                type="number"
                min={15}
                max={180}
                value={advanced.durationMinutes}
                onChange={(e) =>
                  onChangeAdvanced({
                    ...advanced,
                    durationMinutes: Math.max(15, Math.min(180, Number(e.target.value) || 45)),
                  })
                }
                className="w-full min-h-[40px] rounded-[10px] border border-[#E6E1D3] bg-white px-3 py-2 text-[13px] font-mono-tabular text-[#141716]"
              />
            </div>

            <div>
              <label
                htmlFor="ebda-language"
                className="block text-[12px] font-medium text-[#525B58] mb-1"
              >
                Output language
              </label>
              <select
                id="ebda-language"
                value={advanced.outputLanguage}
                onChange={(e) =>
                  onChangeAdvanced({
                    ...advanced,
                    outputLanguage: e.target.value as AdvancedOptions['outputLanguage'],
                  })
                }
                className="w-full min-h-[40px] rounded-[10px] border border-[#E6E1D3] bg-white px-3 py-2 text-[13px] text-[#141716]"
              >
                <option value="auto">Match template language</option>
                <option value="ar">Arabic (العربية)</option>
                <option value="en">English</option>
              </select>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
