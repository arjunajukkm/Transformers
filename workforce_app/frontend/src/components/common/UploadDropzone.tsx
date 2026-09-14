import React, { useRef, useState } from 'react';
import { UploadCloud, FileSpreadsheet, AlertCircle, X, Layers } from 'lucide-react';

interface UploadDropzoneProps {
  onFilesSelected?: (files: File[]) => void;
  onFileSelected?: (file: File) => void;
  isUploading?: boolean;
  error?: string | null;
}

export const UploadDropzone: React.FC<UploadDropzoneProps> = ({
  onFilesSelected,
  onFileSelected,
  isUploading,
  error,
}) => {
  const [isDragging, setIsDragging] = useState(false);
  const [queuedFiles, setQueuedFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addFiles(Array.from(e.dataTransfer.files));
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(Array.from(e.target.files));
    }
  };

  const addFiles = (files: File[]) => {
    const validExts = ['.xlsx', '.xls', '.csv'];
    const validFiles: File[] = [];
    let hasInvalid = false;

    for (const f of files) {
      const ext = f.name.toLowerCase();
      if (validExts.some((e) => ext.endsWith(e))) {
        validFiles.push(f);
      } else {
        hasInvalid = true;
      }
    }

    if (hasInvalid) {
      alert('Only Excel (.xlsx, .xls) and CSV (.csv) files are supported.');
    }

    if (validFiles.length > 0) {
      setQueuedFiles((prev) => {
        // Avoid duplicate file objects by name and size
        const existingKeys = new Set(prev.map((f) => `${f.name}-${f.size}`));
        const newToAdd = validFiles.filter((f) => !existingKeys.has(`${f.name}-${f.size}`));
        return [...prev, ...newToAdd];
      });
    }

    // Reset input so same file can be re-selected if removed
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const removeFile = (idx: number, e: React.MouseEvent) => {
    e.stopPropagation();
    setQueuedFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleTriggerUpload = () => {
    if (queuedFiles.length === 0) return;
    if (onFilesSelected) {
      onFilesSelected(queuedFiles);
    } else if (onFileSelected) {
      onFileSelected(queuedFiles[0]);
    }
  };

  return (
    <div className="w-full max-w-2xl mx-auto">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-all duration-200 ${
          isDragging
            ? 'border-brand-blue bg-blue-50/50'
            : 'border-app-border hover:border-brand-blue/50 hover:bg-white bg-white/70'
        } ${isUploading ? 'opacity-50 pointer-events-none' : ''}`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.xls,.csv"
          multiple
          onChange={handleFileInputChange}
          className="hidden"
        />

        <div className="w-14 h-14 rounded-2xl bg-blue-50 border border-blue-100 text-brand-blue flex items-center justify-center mx-auto mb-4">
          <UploadCloud className="w-7 h-7" />
        </div>

        <h3 className="text-base font-bold text-text-primary tracking-tight mb-1">
          Upload one or more attendance reports
        </h3>

        <p className="text-xs text-text-secondary mb-4">
          Drag and drop monthly reports here, or <span className="text-brand-blue font-semibold">browse files</span>
        </p>

        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-app-bg border border-app-border text-[11px] text-text-muted font-medium">
          <FileSpreadsheet className="w-3.5 h-3.5 text-text-secondary" />
          <span>Supports Excel (.xlsx, .xls) and CSV (.csv) · Multi-month support</span>
        </div>
      </div>

      {/* Selected Files Queue */}
      {queuedFiles.length > 0 && (
        <div className="mt-4 p-4 rounded-xl bg-white border border-app-border shadow-subtle">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
              <Layers className="w-4 h-4 text-brand-blue" />
              <span>Selected files ({queuedFiles.length})</span>
            </div>
            <button
              onClick={() => setQueuedFiles([])}
              className="text-[11px] text-text-muted hover:text-brand-critical transition-colors"
            >
              Clear all
            </button>
          </div>

          <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
            {queuedFiles.map((file, idx) => (
              <div
                key={`${file.name}-${idx}`}
                className="flex items-center justify-between p-2 rounded-lg bg-app-bg border border-app-border/70 text-xs text-text-primary"
              >
                <div className="flex items-center gap-2 truncate mr-2">
                  <FileSpreadsheet className="w-4 h-4 text-brand-blue shrink-0" />
                  <span className="truncate font-medium">{file.name}</span>
                  <span className="text-[10px] text-text-muted shrink-0">
                    ({(file.size / 1024).toFixed(1)} KB)
                  </span>
                </div>
                <button
                  onClick={(e) => removeFile(idx, e)}
                  className="p-1 rounded-md text-text-muted hover:text-brand-critical hover:bg-red-50 transition-colors shrink-0"
                  title="Remove file"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>

          <div className="mt-4 pt-3 border-t border-app-border flex justify-end">
            <button
              onClick={handleTriggerUpload}
              disabled={isUploading}
              className="inline-flex items-center gap-2 px-5 py-2 rounded-xl bg-brand-blue hover:bg-blue-700 text-white text-xs font-semibold shadow-sm transition-colors disabled:opacity-50"
            >
              {isUploading ? (
                <span>Processing...</span>
              ) : (
                <span>
                  Analyse {queuedFiles.length} {queuedFiles.length === 1 ? 'File' : 'Files'}
                </span>
              )}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="mt-4 p-4 rounded-xl bg-rose-50 border border-rose-200 flex items-start gap-3 text-brand-critical">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <div className="text-xs">
            <div className="font-semibold mb-0.5">Unable to process file(s)</div>
            <div className="text-rose-700 leading-relaxed">{error}</div>
          </div>
        </div>
      )}
    </div>
  );
};
