import React from 'react';
import { UploadCloud } from 'lucide-react';

interface EmptyStateProps {
  onUploadClick: () => void;
}

export const EmptyState: React.FC<EmptyStateProps> = ({ onUploadClick }) => {
  return (
    <div className="bg-white border border-app-border rounded-xl p-12 text-center shadow-subtle max-w-xl mx-auto my-12">
      <div className="w-14 h-14 rounded-2xl bg-blue-50 border border-blue-100 text-brand-blue flex items-center justify-center mx-auto mb-4">
        <UploadCloud className="w-7 h-7" />
      </div>

      <h2 className="text-xl font-bold text-text-primary tracking-tight mb-2">
        No workforce dataset loaded
      </h2>

      <p className="text-sm text-text-secondary max-w-md mx-auto mb-6 leading-relaxed">
        Upload an attendance report to generate compliance, attendance, and approval insights.
      </p>

      <button
        onClick={onUploadClick}
        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-brand-blue hover:bg-blue-700 text-white text-sm font-semibold transition-all duration-150 shadow-sm hover:shadow active:scale-[0.99]"
      >
        <UploadCloud className="w-4 h-4" />
        Upload Data
      </button>
    </div>
  );
};
