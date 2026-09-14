import React from 'react';
import { Upload, Calendar } from 'lucide-react';
import { DatasetInfo } from '../../types/workforce';

interface PageHeaderProps {
  dataset?: DatasetInfo;
  onUploadClick: () => void;
  title?: string;
  subtitle?: string;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  dataset,
  onUploadClick,
  title = 'Workforce Process Health',
  subtitle,
}) => {
  // Use display_period if provided by backend, or fallback to date_min - date_max
  const periodDisplay =
    subtitle ||
    dataset?.display_period ||
    (dataset?.date_min && dataset?.date_max ? `${dataset.date_min} — ${dataset.date_max}` : undefined);

  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 mb-6 border-b border-app-border min-w-0">
      <div className="min-w-0">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-blue mb-1">
          Workforce Intelligence
        </div>

        <div className="flex items-baseline gap-3 flex-wrap min-w-0">
          <h1 className="text-2xl lg:text-3xl font-bold text-text-primary tracking-tight truncate">
            {title}
          </h1>

          {periodDisplay && (
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md bg-white border border-app-border text-xs font-semibold text-text-primary shadow-subtle">
              <Calendar className="w-3.5 h-3.5 text-brand-blue" />
              <span>{periodDisplay}</span>
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 shrink-0">
        <button
          onClick={onUploadClick}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-blue hover:bg-blue-700 text-white text-xs font-semibold transition-all duration-150 shadow-sm hover:shadow active:scale-[0.99]"
        >
          <Upload className="w-3.5 h-3.5" />
          <span>Upload Data</span>
        </button>
      </div>
    </div>
  );
};
