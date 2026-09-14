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
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-bold bg-rose-50 text-brand-critical border border-rose-200 shrink-0">
            <AlertOctagon className="w-3.5 h-3.5" />
            CRITICAL
          </span>
        );
      case 'WARNING':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-bold bg-amber-50 text-brand-warning border border-amber-200 shrink-0">
            <AlertTriangle className="w-3.5 h-3.5" />
            WARNING
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-bold bg-blue-50 text-brand-blue border border-blue-200 shrink-0">
            <Info className="w-3.5 h-3.5" />
            INFO
          </span>
        );
    }
  };

  return (
    <div className="max-w-7xl mx-auto min-w-0">
      {/* Page Heading */}
      <div className="pb-5 mb-6 border-b border-app-border min-w-0">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-blue mb-1">
          Data Foundation & Ingestion
        </div>
        <h1 className="text-2xl lg:text-3xl font-bold text-text-primary tracking-tight truncate">
          Data Quality & Ingestion
        </h1>
        <p className="text-xs text-text-secondary mt-1 truncate">
          Source-data validation, canonical mapping, and quality assurance findings.
        </p>
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
        <div className="space-y-6 min-w-0">
          {/* Dataset Summary Cards */}
          <div className="min-w-0">
            <h2 className="text-xs font-bold uppercase tracking-wider text-text-secondary mb-3">
              Dataset Summary
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5 min-w-0">
              <div className="bg-white border border-app-border rounded-xl p-4 shadow-subtle min-w-0 overflow-hidden">
                <div className="flex items-center gap-2 text-text-muted mb-2 text-xs font-semibold uppercase truncate">
                  <Database className="w-3.5 h-3.5 shrink-0" />
                  <span className="truncate">Ingested Rows</span>
                </div>
                <div className="text-2xl font-bold text-text-primary truncate">
                  {data.dataset.rows}
                </div>
                <div className="text-[11px] text-text-secondary mt-0.5 truncate">
                  source rows validated
                </div>
              </div>

              <div className="bg-white border border-app-border rounded-xl p-4 shadow-subtle min-w-0 overflow-hidden">
                <div className="flex items-center gap-2 text-text-muted mb-2 text-xs font-semibold uppercase truncate">
                  <Users className="w-3.5 h-3.5 shrink-0" />
                  <span className="truncate">Unique Employees</span>
                </div>
                <div className="text-2xl font-bold text-text-primary truncate">
                  {data.dataset.unique_employees}
                </div>
                <div className="text-[11px] text-text-secondary mt-0.5 truncate">
                  active headcount
                </div>
              </div>

              <div className="bg-white border border-app-border rounded-xl p-4 shadow-subtle min-w-0 overflow-hidden">
                <div className="flex items-center gap-2 text-text-muted mb-2 text-xs font-semibold uppercase truncate">
                  <Calendar className="w-3.5 h-3.5 shrink-0" />
                  <span className="truncate">Period</span>
                </div>
                <div
                  className="text-base font-bold text-text-primary truncate"
                  title={data.dataset.display_period || `${data.dataset.date_min} → ${data.dataset.date_max}`}
                >
                  {data.dataset.display_period ||
                    (data.dataset.date_min && data.dataset.date_max
                      ? `${data.dataset.date_min} → ${data.dataset.date_max}`
                      : 'N/A')}
                </div>
                <div className="text-[11px] text-text-secondary mt-0.5 truncate">
                  validated date range
                </div>
              </div>

              <div className="bg-white border border-app-border rounded-xl p-4 shadow-subtle min-w-0 overflow-hidden">
                <div className="flex items-center gap-2 text-text-muted mb-2 text-xs font-semibold uppercase truncate">
                  <CheckCircle2 className="w-3.5 h-3.5 text-brand-positive shrink-0" />
                  <span className="truncate">Core Completeness</span>
                </div>
                <div className="text-2xl font-bold text-text-primary truncate">
                  {data.quality.core_completeness.toFixed(1)}%
                </div>
                <div className="text-[11px] text-text-secondary mt-0.5 truncate">
                  required fields present
                </div>
              </div>
            </div>
          </div>

          {/* Quality Findings Table / Rows */}
          <div className="bg-white border border-app-border rounded-xl p-5 md:p-6 shadow-subtle min-w-0 overflow-hidden">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4 min-w-0">
              <div className="min-w-0">
                <h3 className="text-base font-bold text-text-primary tracking-tight truncate">
                  Data Quality Findings
                </h3>
                <p className="text-xs text-text-secondary truncate">
                  Detailed inspection of record hygiene, anomalies, and metric exclusions.
                </p>
              </div>

              <div className="flex items-center gap-2 text-xs font-semibold shrink-0">
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
              <div className="space-y-3 min-w-0">
                {data.quality.findings.map((f, idx) => (
                  <div
                    key={idx}
                    className="p-4 rounded-xl border border-app-border bg-app-bg/60 hover:bg-app-bg transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3 min-w-0 overflow-hidden"
                  >
                    <div className="flex items-start gap-3 min-w-0 flex-1">
                      <div className="mt-0.5 shrink-0">{getSeverityBadge(f.severity)}</div>
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-bold text-text-primary truncate">
                          {(f.category || f.code || 'DATA QUALITY ISSUE').replace(/_/g, ' ').toUpperCase()}
                          {f.field ? ` · [${f.field}]` : ''}
                        </div>
                        <p className="text-xs text-text-secondary mt-0.5 leading-relaxed break-words">
                          {f.message}
                        </p>
                      </div>
                    </div>

                    <div className="text-left sm:text-right shrink-0">
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

          {/* Upload New / Replace Dataset Dropzone */}
          <div className="bg-white border border-app-border rounded-xl p-5 md:p-6 shadow-subtle min-w-0 overflow-hidden">
            <h3 className="text-sm font-bold text-text-primary mb-1 truncate">
              Upload New Dataset
            </h3>
            <p className="text-xs text-text-secondary mb-4 truncate">
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
