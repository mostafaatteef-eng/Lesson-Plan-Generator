import React, { useRef, useState } from 'react';
import type { Strings } from '../i18n';
import {
  FileText,
  FileSpreadsheet,
  FileCheck2,
  Upload,
  RefreshCw,
  Trash2,
  Loader2,
  AlertCircle,
  CheckCircle2,
} from 'lucide-react';

export interface UploadedFileSummary {
  name: string;
  // Null when the real size is unknown (e.g. a server-side built-in asset);
  // the card then shows no size rather than a fabricated "0 B".
  sizeBytes: number | null;
  metaLine?: string;
}

interface UploadCardProps {
  id: string;
  title: string;
  required: boolean;
  requirementLabel: string;
  accept: string;
  allowedExtensions: string[];
  formatHint: string;
  helperText: string;
  icon: 'curriculum' | 'template' | 'reference';
  file: UploadedFileSummary | null;
  uploading: boolean;
  error: string | null;
  onSelectFile: (file: File) => void;
  onRemoveFile: () => void;
  onValidationError: (message: string) => void;
  t: Strings;
}

const MAX_FILE_BYTES = 35 * 1024 * 1024;

function formatFileSize(bytes: number): string {
  if (!bytes || bytes < 1024) return `${bytes || 0} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export const UploadCard: React.FC<UploadCardProps> = ({
  id,
  title,
  required,
  requirementLabel,
  accept,
  allowedExtensions,
  formatHint,
  helperText,
  icon,
  file,
  uploading,
  error,
  onSelectFile,
  onRemoveFile,
  onValidationError,
  t,
}) => {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);

  const validateAndForward = (candidate: File | undefined) => {
    if (!candidate) return;
    const ext = (candidate.name.split('.').pop() || '').toLowerCase();
    if (!allowedExtensions.includes(ext)) {
      onValidationError(t.errUnsupported(ext || 'unknown', formatHint));
      return;
    }
    if (candidate.size === 0) {
      onValidationError(t.errEmpty);
      return;
    }
    if (candidate.size > MAX_FILE_BYTES) {
      onValidationError(t.errTooBig);
      return;
    }
    onSelectFile(candidate);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    if (uploading) return;
    validateAndForward(e.dataTransfer.files?.[0]);
  };

  const handleBrowse = () => {
    if (uploading) return;
    inputRef.current?.click();
  };

  const IconComponent =
    icon === 'curriculum' ? FileText : icon === 'template' ? FileSpreadsheet : FileCheck2;

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!uploading) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`rounded-[14px] border transition-colors p-4 sm:p-5 flex flex-col justify-between gap-4 bg-white ${
        error
          ? 'border-rose-300 bg-rose-50/30'
          : dragging
            ? 'border-[#168B83] bg-[#FFF8E9]/25'
            : file
              ? 'border-[#168B83]/50 shadow-[0_1px_2px_rgba(20,23,22,0.03)]'
              : 'border-[#E3EAE7] hover:border-[#CBC0A3] shadow-[0_1px_2px_rgba(20,23,22,0.03)]'
      }`}
    >
      <input
        ref={inputRef}
        id={id}
        type="file"
        accept={accept}
        onChange={(e) => {
          validateAndForward(e.target.files?.[0]);
          e.target.value = '';
        }}
        className="hidden"
      />

      {/* Card Header */}
      <div className="space-y-1.5">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2.5 min-w-0">
            <span
              className={`w-8 h-8 rounded-[10px] flex items-center justify-center shrink-0 ${
                file
                  ? 'bg-[#168B83]/12 text-[#116962]'
                  : 'bg-[#FFF8E9]/35 text-[#596A72]'
              }`}
            >
              {uploading ? (
                <Loader2 className="w-4 h-4 animate-spin text-[#116962]" />
              ) : (
                <IconComponent className="w-4 h-4" />
              )}
            </span>
            <h2 className="text-[14px] font-semibold text-[#17252C] leading-snug">
              {title}
            </h2>
          </div>

          <span
            className={`text-[12px] font-medium shrink-0 ${
              required ? 'text-[#116962]' : 'text-[#596A72]'
            }`}
          >
            {requirementLabel}
          </span>
        </div>

        <p className="text-[12.5px] text-[#596A72] leading-relaxed">
          {helperText}
        </p>
      </div>

      {/* Dropzone OR Uploaded File Summary */}
      {!file ? (
        <button
          type="button"
          onClick={handleBrowse}
          disabled={uploading}
          className={`w-full rounded-[12px] border border-dashed px-3.5 py-5 text-center transition-colors cursor-pointer disabled:cursor-wait ${
            dragging
              ? 'border-[#168B83] bg-[#FFF8E9]/20'
              : 'border-[#CBC0A3] bg-[#F8FAF9]/80 hover:border-[#168B83] hover:bg-[#FFF8E9]/15'
          }`}
        >
          <Upload className="w-4 h-4 mx-auto mb-2 text-[#116962]" />
          <div className="text-[13px] font-medium text-[#17252C]">
            {uploading ? t.analyzing : t.dropOrBrowse}
          </div>
          <div className="mt-1 text-[11.5px] text-[#596A72] font-mono-tabular">
            {formatHint}
          </div>
        </button>
      ) : (
        <div className="rounded-[12px] border border-[#E3EAE7] bg-[#F8FAF9] p-3.5 space-y-3">
          <div className="flex items-start gap-2.5 min-w-0">
            <CheckCircle2 className="w-4 h-4 text-[#116962] shrink-0 mt-0.5" />
            <div className="min-w-0 flex-1 space-y-0.5">
              <div
                dir="auto"
                title={file.name}
                className="text-[13px] font-medium text-[#17252C] truncate font-arabic"
              >
                {file.name}
              </div>
              <div className="text-[11.5px] text-[#596A72] font-mono-tabular flex flex-wrap items-center gap-x-1.5">
                {file.sizeBytes !== null && <span>{formatFileSize(file.sizeBytes)}</span>}
                {file.metaLine && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span>{file.metaLine}</span>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 pt-2 border-t border-[#E3EAE7]">
            <button
              type="button"
              onClick={handleBrowse}
              disabled={uploading}
              className="flex-1 inline-flex items-center justify-center gap-1.5 min-h-[36px] px-3 py-1.5 text-[12px] font-medium rounded-[9px] border border-[#E3EAE7] bg-white text-[#17252C] hover:border-[#168B83] hover:text-[#116962] transition-colors whitespace-nowrap shrink-0 disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${uploading ? 'animate-spin' : ''}`} />
              {t.replace}
            </button>
            <button
              type="button"
              onClick={onRemoveFile}
              disabled={uploading}
              className="inline-flex items-center justify-center gap-1.5 min-h-[36px] px-3 py-1.5 text-[12px] font-medium rounded-[9px] border border-[#E3EAE7] bg-white text-[#596A72] hover:border-rose-300 hover:text-rose-700 transition-colors whitespace-nowrap shrink-0 disabled:opacity-50"
              aria-label={t.removeAria(title)}
            >
              <Trash2 className="w-3.5 h-3.5" />
              {t.remove}
            </button>
          </div>
        </div>
      )}

      {/* Clear Inline Error Feedback */}
      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 text-[12px] text-rose-700 leading-snug"
        >
          <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
};
