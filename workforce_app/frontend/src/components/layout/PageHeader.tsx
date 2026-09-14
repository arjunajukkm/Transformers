import React from 'react';
import { Upload, Calendar, Clock } from 'lucide-react';
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
  const isPrePolicy = dataset?.policy_period === 'PRE_POLICY';

  // Format date range
  const dateRangeDisplay = dataset?.date_min && dataset?.date_max
    ? `${dataset.date_min} — ${dataset.date_max}`
    : 'No active date range';

  const defaultSubtitle = isPrePolicy
    ? 'Pre-policy baseline'
    : 'Policy monitoring';

  return (
    <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 mb-6 border-b border-app-border">
      <div>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs font-semibold uppercase tracking-wider text-brand-blue">
            Workforce Intelligence
          </span>
          {dataset && (
            <>
              <span className="text-text-muted">·</span>
              <span className="text-xs text-text-secondary font-medium">
                {subtitle || defaultSubtitle}
              </span>
            </>
          )}
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-2xl font-bold text-text-primary tracking-tight">
            {title}
          </h1>

          {dataset && (
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold tracking-wide uppercase ${
                isPrePolicy
                  ? 'bg-blue-50 text-brand-blue border border-blue-200'
                  : 'bg-emerald-50 text-brand-positive border border-emerald-200'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isPrePolicy ? 'bg-brand-blue' : 'bg-brand-positive'
                }`}
              />
              {isPrePolicy ? 'Pre-Policy Baseline' : 'Policy Monitoring'}
            </span>
          )}
        </div>

        {dataset && (
          <div className="flex items-center gap-3 text-xs text-text-secondary mt-1.5">
            <span className="inline-flex items-center gap-1">
              <Calendar className="w-3.5 h-3.5 text-text-muted" />
              {dateRangeDisplay}
            </span>
            <span className="text-text-muted">·</span>
            <span className="inline-flex items-center gap-1">
              <Clock className="w-3.5 h-3.5 text-text-muted" />
              Effective date: {dataset.policy_effective_date}
            </span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={onUploadClick}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-blue hover:bg-blue-700 text-white text-sm font-semibold transition-all duration-150 shadow-sm hover:shadow active:scale-[0.99]"
        >
          <Upload className="w-4 h-4" />
          Upload Data
        </button>
      </div>
    </div>
  );
};
