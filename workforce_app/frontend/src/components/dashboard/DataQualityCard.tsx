import React from 'react';
import { ShieldCheck, ArrowRight, AlertOctagon, AlertTriangle, UserX } from 'lucide-react';
import { QualitySummary } from '../../types/workforce';

interface DataQualityCardProps {
  quality?: QualitySummary;
  onViewDetails: () => void;
}

export const DataQualityCard: React.FC<DataQualityCardProps> = ({ quality, onViewDetails }) => {
  const coreCompleteness = quality?.core_completeness ?? 100;
  const criticalFindings = quality?.critical_findings ?? 0;
  const warningFindings = quality?.warning_findings ?? 0;
  const excludedDays = quality?.excluded_employee_days ?? 0;

  return (
    <div className="bg-white border border-app-border rounded-xl p-5 md:p-6 shadow-subtle mb-6 min-w-0 overflow-hidden">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4 min-w-0">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="p-1.5 rounded-lg bg-emerald-50 border border-emerald-100 text-brand-positive shrink-0">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h3 className="text-base font-bold text-text-primary tracking-tight truncate">
              Data Quality & Governance
            </h3>
            <p className="text-xs text-text-secondary truncate">
              Source-data integrity, record hygiene, and metric exclusions.
            </p>
          </div>
        </div>

        <button
          onClick={onViewDetails}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-brand-blue hover:text-blue-700 transition-colors shrink-0"
        >
          <span>View Quality Findings</span>
          <ArrowRight className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-3 min-w-0">
        {/* Core Completeness */}
        <div className="p-3 rounded-lg bg-app-bg border border-app-border flex items-center gap-2.5 min-w-0 overflow-hidden">
          <div className="w-8 h-8 rounded-md bg-emerald-100/60 text-brand-positive flex items-center justify-center shrink-0">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-base font-bold text-text-primary truncate">
              {coreCompleteness.toFixed(1)}%
            </div>
            <div className="text-[11px] text-text-secondary font-medium truncate" title="Core Completeness">
              Core Completeness
            </div>
          </div>
        </div>

        {/* Critical Issues */}
        <div className="p-3 rounded-lg bg-app-bg border border-app-border flex items-center gap-2.5 min-w-0 overflow-hidden">
          <div
            className={`w-8 h-8 rounded-md flex items-center justify-center shrink-0 ${
              criticalFindings > 0
                ? 'bg-rose-100 text-brand-critical'
                : 'bg-emerald-100/60 text-brand-positive'
            }`}
          >
            <AlertOctagon className="w-4 h-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-base font-bold text-text-primary truncate">
              {criticalFindings}
            </div>
            <div className="text-[11px] text-text-secondary font-medium truncate" title="Critical Findings">
              Critical Findings
            </div>
          </div>
        </div>

        {/* Warnings */}
        <div className="p-3 rounded-lg bg-app-bg border border-app-border flex items-center gap-2.5 min-w-0 overflow-hidden">
          <div
            className={`w-8 h-8 rounded-md flex items-center justify-center shrink-0 ${
              warningFindings > 0
                ? 'bg-amber-100 text-brand-warning'
                : 'bg-gray-100 text-text-muted'
            }`}
          >
            <AlertTriangle className="w-4 h-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-base font-bold text-text-primary truncate">
              {warningFindings}
            </div>
            <div className="text-[11px] text-text-secondary font-medium truncate" title="Warnings">
              Warnings
            </div>
          </div>
        </div>

        {/* Metric Excluded Days */}
        <div className="p-3 rounded-lg bg-app-bg border border-app-border flex items-center gap-2.5 min-w-0 overflow-hidden">
          <div
            className={`w-8 h-8 rounded-md flex items-center justify-center shrink-0 ${
              excludedDays > 0
                ? 'bg-rose-100 text-brand-critical'
                : 'bg-gray-100 text-text-muted'
            }`}
          >
            <UserX className="w-4 h-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-base font-bold text-text-primary truncate">
              {excludedDays}
            </div>
            <div className="text-[11px] text-text-secondary font-medium truncate" title="Days Excluded">
              Days Excluded
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
