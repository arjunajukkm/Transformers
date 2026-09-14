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
    <div className="bg-white border border-app-border rounded-xl p-6 shadow-subtle mb-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-5">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-emerald-50 border border-emerald-100 text-brand-positive">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-base font-bold text-text-primary tracking-tight">
              Data Quality & Governance
            </h3>
            <p className="text-xs text-text-secondary">
              Source-data integrity, record hygiene, and metric exclusions.
            </p>
          </div>
        </div>

        <button
          onClick={onViewDetails}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-brand-blue hover:text-blue-700 transition-colors"
        >
          <span>View Data Quality Findings</span>
          <ArrowRight className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {/* Core Completeness */}
        <div className="p-3.5 rounded-lg bg-app-bg border border-app-border flex items-center gap-3">
          <div className="w-8 h-8 rounded-md bg-emerald-100/60 text-brand-positive flex items-center justify-center shrink-0">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <div>
            <div className="text-base font-bold text-text-primary">
              {coreCompleteness.toFixed(1)}%
            </div>
            <div className="text-[11px] text-text-secondary font-medium">
              Core Completeness
            </div>
          </div>
        </div>

        {/* Critical Issues */}
        <div className="p-3.5 rounded-lg bg-app-bg border border-app-border flex items-center gap-3">
          <div
            className={`w-8 h-8 rounded-md flex items-center justify-center shrink-0 ${
              criticalFindings > 0
                ? 'bg-rose-100 text-brand-critical'
                : 'bg-emerald-100/60 text-brand-positive'
            }`}
          >
            <AlertOctagon className="w-4 h-4" />
          </div>
          <div>
            <div className="text-base font-bold text-text-primary">
              {criticalFindings}
            </div>
            <div className="text-[11px] text-text-secondary font-medium">
              Critical Findings
            </div>
          </div>
        </div>

        {/* Warnings */}
        <div className="p-3.5 rounded-lg bg-app-bg border border-app-border flex items-center gap-3">
          <div
            className={`w-8 h-8 rounded-md flex items-center justify-center shrink-0 ${
              warningFindings > 0
                ? 'bg-amber-100 text-brand-warning'
                : 'bg-gray-100 text-text-muted'
            }`}
          >
            <AlertTriangle className="w-4 h-4" />
          </div>
          <div>
            <div className="text-base font-bold text-text-primary">
              {warningFindings}
            </div>
            <div className="text-[11px] text-text-secondary font-medium">
              Warnings
            </div>
          </div>
        </div>

        {/* Metric Excluded Days */}
        <div className="p-3.5 rounded-lg bg-app-bg border border-app-border flex items-center gap-3">
          <div
            className={`w-8 h-8 rounded-md flex items-center justify-center shrink-0 ${
              excludedDays > 0
                ? 'bg-rose-100 text-brand-critical'
                : 'bg-gray-100 text-text-muted'
            }`}
          >
            <UserX className="w-4 h-4" />
          </div>
          <div>
            <div className="text-base font-bold text-text-primary">
              {excludedDays}
            </div>
            <div className="text-[11px] text-text-secondary font-medium">
              Days Excluded from KPIs
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
