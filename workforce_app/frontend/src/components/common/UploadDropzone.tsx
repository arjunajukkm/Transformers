import React, { useRef, useState } from 'react';
import { UploadCloud, FileSpreadsheet, AlertCircle } from 'lucide-react';

interface UploadDropzoneProps {
  onFileSelected: (file: File) => void;
  isUploading?: boolean;
  error?: string | null;
}

export const UploadDropzone: React.FC<UploadDropzoneProps> = ({
  onFileSelected,
  isUploading,
  error,
}) => {
  const [isDragging, setIsDragging] = useState(false);
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
      const file = e.dataTransfer.files[0];
      validateAndUpload(file);
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0];
      validateAndUpload(file);
    }
  };

  const validateAndUpload = (file: File) => {
    const ext = file.name.toLowerCase();
    if (!ext.endsWith('.xlsx') && !ext.endsWith('.xls') && !ext.endsWith('.csv')) {
      alert('Please upload an Excel (.xlsx, .xls) or CSV (.csv) file.');
      return;
    }
    onFileSelected(file);
  };

  return (
    <div className="w-full max-w-2xl mx-auto">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all duration-200 ${
          isDragging
            ? 'border-brand-blue bg-blue-50/50'
            : 'border-app-border hover:border-brand-blue/50 hover:bg-white bg-white/70'
        } ${isUploading ? 'opacity-50 pointer-events-none' : ''}`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.xls,.csv"
          onChange={handleFileInputChange}
          className="hidden"
        />

        <div className="w-14 h-14 rounded-2xl bg-blue-50 border border-blue-100 text-brand-blue flex items-center justify-center mx-auto mb-4">
          <UploadCloud className="w-7 h-7" />
        </div>

        <h3 className="text-base font-bold text-text-primary tracking-tight mb-1">
          Upload attendance, leave and WFH data
        </h3>

        <p className="text-xs text-text-secondary mb-4">
          Drag and drop your spreadsheet here, or <span className="text-brand-blue font-semibold">browse file</span>
        </p>

        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-app-bg border border-app-border text-[11px] text-text-muted font-medium">
          <FileSpreadsheet className="w-3.5 h-3.5 text-text-secondary" />
          <span>Supports Excel (.xlsx, .xls) and CSV (.csv)</span>
        </div>
      </div>

      {error && (
        <div className="mt-4 p-4 rounded-xl bg-rose-50 border border-rose-200 flex items-start gap-3 text-brand-critical">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <div className="text-xs">
            <div className="font-semibold mb-0.5">Unable to process this file</div>
            <div className="text-rose-700 leading-relaxed">{error}</div>
          </div>
        </div>
      )}
    </div>
  );
};
