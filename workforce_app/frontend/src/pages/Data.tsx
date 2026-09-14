import React from 'react';
import {
  AlertOctagon,
  AlertTriangle,
  Info,
  CheckCircle2,
  Calendar,
  Users,
  Database,
} from 'lucide-react';
import { UploadDropzone } from '../components/common/UploadDropzone';
import { LoadingState } from '../components/common/LoadingState';
import { DashboardResponse } from '../types/workforce';

interface DataProps {
  data: DashboardResponse | null;
  isLoading: boolean;
  onFileUpload: (file: File) => void;
  uploadError: string | null;
}

export const Data: React.FC<DataProps> = ({
  data,
  isLoading,
  onFileUpload,
  uploadError,
}) => {
  const isLoaded = data?.loaded && data?.dataset;

  const getSeverityBadge = (severity: string) => {
    switch (severity) {
      case 'CRITICAL':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-bold bg-rose-50 text-brand-critical border border-rose-200">
            <AlertOctagon className="w-3.5 h-3.5" />
            CRITICAL
          </span>
        );
      case 'WARNING':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-bold bg-amber-50 text-brand-warning border border-amber-200">
            <AlertTriangle className="w-3.5 h-3.5" />
            WARNING
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-bold bg-blue-50 text-brand-blue border border-blue-200">
            <Info className="w-3.5 h-3.5" />
            INFO
          </span>
        );
    }
  };

  return (
    <div className="max-w-7xl mx-auto">
      {/* Page Heading */}
      <div className="pb-6 mb-6 border-b border-app-border flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-brand-blue mb-1">
            Data Foundation & Ingestion
          </div>
          <h1 className="text-2xl font-bold text-text-primary tracking-tight">
            Data Quality & Ingestion
          </h1>
          <p className="text-xs text-text-secondary mt-1">
            Source-data validation, canonical mapping, and quality assurance findings.
          </p>
        </div>
      </div>

      {isLoading && (
        <LoadingState
          message="Processing workforce report..."
          subMessage="Executing schema validation, audit rules, and governed quality checks."
        />
      )}

      {/* When no data loaded: Centered Upload Zone */}
      {!isLoading && !isLoaded && (
        <div className="py-12">
          <UploadDropzone
            onFileSelected={onFileUpload}
            isUploading={isLoading}
            error={uploadError}
          />
        </div>
      )}

      {/* When data is loaded: Dataset Summary + Quality Findings + Re-upload bar */}
      {!isLoading && isLoaded && data.dataset && data.quality && (
        <div className="space-y-6">
          {/* Dataset Summary Cards */}
          <div>
            <h2 className="text-sm font-bold uppercase tracking-wider text-text-secondary mb-3">
              Dataset Summary
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-white border border-app-border rounded-xl p-4 shadow-subtle">
                <div className="flex items-center gap-2 text-text-muted mb-2 text-xs font-semibold uppercase">
                  <Database className="w-3.5 h-3.5" />
                  <span>Ingested Rows</span>
                </div>
                <div className="text-2xl font-bold text-text-primary">
                  {data.dataset.rows}
                </div>
                <div className="text-[11px] text-text-secondary mt-0.5">
                  source rows validated
                </div>
              </div>

              <div className="bg-white border border-app-border rounded-xl p-4 shadow-subtle">
                <div className="flex items-center gap-2 text-text-muted mb-2 text-xs font-semibold uppercase">
                  <Users className="w-3.5 h-3.5" />
                  <span>Unique Employees</span>
                </div>
                <div className="text-2xl font-bold text-text-primary">
                  {data.dataset.unique_employees}
                </div>
                <div className="text-[11px] text-text-secondary mt-0.5">
                  active headcount
                </div>
              </div>

              <div className="bg-white border border-app-border rounded-xl p-4 shadow-subtle">
                <div className="flex items-center gap-2 text-text-muted mb-2 text-xs font-semibold uppercase">
                  <Calendar className="w-3.5 h-3.5" />
                  <span>Date Range</span>
                </div>
                <div className="text-base font-bold text-text-primary truncate">
                  {data.dataset.date_min && data.dataset.date_max
                    ? `${data.dataset.date_min} → ${data.dataset.date_max}`
                    : 'N/A'}
                </div>
                <div className="text-[11px] text-text-secondary mt-0.5">
                  {data.dataset.policy_period === 'PRE_POLICY' ? 'Pre-policy period' : 'Policy monitoring'}
                </div>
              </div>

              <div className="bg-white border border-app-border rounded-xl p-4 shadow-subtle">
                <div className="flex items-center gap-2 text-text-muted mb-2 text-xs font-semibold uppercase">
                  <CheckCircle2 className="w-3.5 h-3.5 text-brand-positive" />
                  <span>Core Completeness</span>
                </div>
                <div className="text-2xl font-bold text-text-primary">
                  {data.quality.core_completeness.toFixed(1)}%
                </div>
                <div className="text-[11px] text-text-secondary mt-0.5">
                  required fields present
                </div>
              </div>
            </div>
          </div>

          {/* Quality Findings Table / Rows */}
          <div className="bg-white border border-app-border rounded-xl p-6 shadow-subtle">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-base font-bold text-text-primary tracking-tight">
                  Data Quality Findings
                </h3>
                <p className="text-xs text-text-secondary">
                  Detailed inspection of record hygiene, anomalies, and metric exclusions.
                </p>
              </div>

              <div className="flex items-center gap-2 text-xs font-semibold">
                <span className="px-2 py-0.5 rounded bg-rose-50 text-brand-critical border border-rose-200">
                  {data.quality.critical_findings} Critical
                </span>
                <span className="px-2 py-0.5 rounded bg-amber-50 text-brand-warning border border-amber-200">
                  {data.quality.warning_findings} Warnings
                </span>
              </div>
            </div>

            {data.quality.findings.length === 0 ? (
              <div className="p-8 text-center bg-app-bg/50 rounded-lg border border-dashed border-app-border">
                <CheckCircle2 className="w-8 h-8 text-brand-positive mx-auto mb-2" />
                <p className="text-xs font-semibold text-text-primary">
                  No data quality issues detected
                </p>
                <p className="text-[11px] text-text-secondary mt-0.5">
                  All source records conform to standard policy validation schemas.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {data.quality.findings.map((f, idx) => (
                  <div
                    key={idx}
                    className="p-4 rounded-xl border border-app-border bg-app-bg/60 hover:bg-app-bg transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                  >
                    <div className="flex items-start gap-3">
                      <div className="mt-0.5">{getSeverityBadge(f.severity)}</div>
                      <div>
                        <div className="text-xs font-bold text-text-primary">
                          {(f.category || f.code || 'DATA QUALITY ISSUE').replace(/_/g, ' ').toUpperCase()}
                          {f.field ? ` · [${f.field}]` : ''}
                        </div>
                        <p className="text-xs text-text-secondary mt-0.5 leading-relaxed">
                          {f.message}
                        </p>
                      </div>
                    </div>

                    <div className="text-right shrink-0">
                      <div className="text-xs font-bold text-text-primary">
                        {f.count} {f.count === 1 ? 'occurrence' : 'occurrences'}
                      </div>
                      <div className="text-[11px] text-text-muted">
                        audit flag
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Upload New / Replace Dataset Accordion/Dropzone */}
          <div className="bg-white border border-app-border rounded-xl p-6 shadow-subtle">
            <h3 className="text-sm font-bold text-text-primary mb-1">
              Upload New Dataset
            </h3>
            <p className="text-xs text-text-secondary mb-4">
              Replace active dataset in session memory with a new workforce report.
            </p>
            <UploadDropzone
              onFileSelected={onFileUpload}
              isUploading={isLoading}
              error={uploadError}
            />
          </div>
        </div>
      )}
    </div>
  );
};
