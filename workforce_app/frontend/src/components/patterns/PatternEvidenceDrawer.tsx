import React, { useEffect, useState } from 'react';
import { X, FileSpreadsheet } from 'lucide-react';
import { PatternResult, PatternEvidenceItem } from '../../types/workforce';
import { fetchPatternById } from '../../services/api';
import {
  PatternStrengthBadge,
  PatternSeverityBadge,
  PatternStatusBadge,
  PatternPersistenceBadge,
} from './PatternBadges';

interface PatternEvidenceDrawerProps {
  pattern: PatternResult | null;
  onClose: () => void;
}

export const PatternEvidenceDrawer: React.FC<PatternEvidenceDrawerProps> = ({
  pattern,
  onClose,
}) => {
  const [fullPattern, setFullPattern] = useState<PatternResult | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  useEffect(() => {
    if (!pattern) {
      setFullPattern(null);
      return;
    }

    let isMounted = true;
    setIsLoading(true);

    fetchPatternById(pattern.pattern_id)
      .then((data) => {
        if (isMounted) {
          setFullPattern(data);
          setIsLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          console.error('Failed to load full pattern details:', err);
          // Fallback to initial pattern
          setFullPattern(pattern);
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [pattern]);


  // Handle ESC key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  if (!pattern) return null;

  const current = fullPattern || pattern;
  const evidenceList: PatternEvidenceItem[] =
    current.evidence_items || current.evidence_preview || [];

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      <div className="fixed inset-y-0 right-0 max-w-full flex pl-10">
        <div className="w-screen max-w-2xl bg-white shadow-2xl flex flex-col border-l border-app-border">
          {/* Header */}
          <div className="p-5 border-b border-app-border bg-slate-50/70 flex items-start justify-between gap-4">
            <div className="space-y-1 min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-semibold text-brand-blue uppercase tracking-wider bg-blue-50 px-2 py-0.5 rounded border border-blue-100">
                  {current.pattern_category}
                </span>
                <span className="text-xs font-mono text-slate-400">
                  {current.pattern_type}
                </span>
              </div>
              <h2 className="text-lg font-bold text-app-text-primary tracking-tight">
                {current.pattern_title}
              </h2>
              <div className="flex items-center gap-2 text-xs text-app-text-secondary pt-0.5">
                <span className="font-semibold text-slate-800">{current.entity_name}</span>
                <span className="text-slate-300">•</span>
                <span className="text-app-text-muted">{current.entity_type}</span>
                {current.entity_id && (
                  <>
                    <span className="text-slate-300">•</span>
                    <span className="font-mono text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded text-[11px]">
                      {current.entity_id}
                    </span>
                  </>
                )}
              </div>
            </div>

            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-200/60 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Drawer Body */}
          <div className="flex-1 overflow-y-auto p-5 space-y-5 scrollbar-thin">
            {/* Badges Cluster */}
            <div className="flex flex-wrap items-center gap-2">
              <PatternStrengthBadge strength={current.strength} />
              <PatternSeverityBadge severity={current.severity} />
              <PatternStatusBadge status={current.status} />
              <PatternPersistenceBadge persistence={current.persistence} />
            </div>

            {/* Why Detected section */}
            <div className="bg-blue-50/50 border border-blue-100 rounded-xl p-4">
              <div className="text-xs font-bold text-brand-blue uppercase tracking-wider mb-1">
                Why Detected
              </div>
              <p className="text-xs text-slate-700 leading-relaxed font-normal">
                {current.why_detected}
              </p>
            </div>

            {/* Key Analytical Metrics Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              <div className="bg-slate-50 rounded-lg p-3 border border-slate-100">
                <div className="text-[11px] font-medium text-slate-500 uppercase">Supporting Events</div>
                <div className="text-lg font-bold text-slate-800 mt-0.5">
                  {current.event_count}
                </div>
                {current.opportunity_count ? (
                  <div className="text-[11px] text-slate-500">
                    of {current.opportunity_count} opportunities
                  </div>
                ) : null}
              </div>

              <div className="bg-slate-50 rounded-lg p-3 border border-slate-100">
                <div className="text-[11px] font-medium text-slate-500 uppercase">Recurrence Rate</div>
                <div className="text-lg font-bold text-brand-blue mt-0.5">
                  {current.rate !== null && current.rate !== undefined
                    ? `${(current.rate * 100).toFixed(1)}%`
                    : 'N/A'}
                </div>
                {current.reference_rate !== null && current.reference_rate !== undefined && (
                  <div className="text-[11px] text-slate-500">
                    Org baseline: {(current.reference_rate * 100).toFixed(1)}%
                  </div>
                )}
              </div>

              <div className="bg-slate-50 rounded-lg p-3 border border-slate-100">
                <div className="text-[11px] font-medium text-slate-500 uppercase">Distinct Months</div>
                <div className="text-lg font-bold text-slate-800 mt-0.5">
                  {current.distinct_months}
                </div>
                <div className="text-[11px] text-slate-500 truncate" title={current.months_active?.join(', ')}>
                  {current.months_active?.join(', ')}
                </div>
              </div>

              <div className="bg-slate-50 rounded-lg p-3 border border-slate-100">
                <div className="text-[11px] font-medium text-slate-500 uppercase">First Observed</div>
                <div className="text-sm font-semibold text-slate-800 mt-1">
                  {current.first_observed_date || 'N/A'}
                </div>
              </div>

              <div className="bg-slate-50 rounded-lg p-3 border border-slate-100">
                <div className="text-[11px] font-medium text-slate-500 uppercase">Last Observed</div>
                <div className="text-sm font-semibold text-slate-800 mt-1">
                  {current.last_observed_date || 'N/A'}
                </div>
              </div>

              <div className="bg-slate-50 rounded-lg p-3 border border-slate-100">
                <div className="text-[11px] font-medium text-slate-500 uppercase">Pattern Strength Score</div>
                <div className="text-lg font-bold text-purple-700 mt-0.5">
                  {current.pattern_score} / 100
                </div>
                {current.score_components && (
                  <div className="text-[10px] text-slate-500">
                    F:{current.score_components.frequency} P:{current.score_components.persistence} C:{current.score_components.concentration} R:{current.score_components.recency}
                  </div>
                )}
              </div>
            </div>

            {/* Evidence Timeline & Records */}
            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider flex items-center gap-1.5">
                  <FileSpreadsheet className="w-4 h-4 text-brand-blue" />
                  <span>Supporting Evidence Records ({evidenceList.length})</span>
                </h3>
                {isLoading && (
                  <span className="text-[11px] text-slate-400">Loading full records...</span>
                )}
              </div>

              {evidenceList.length === 0 ? (
                <div className="p-4 rounded-lg bg-slate-50 border border-slate-100 text-xs text-slate-500 text-center">
                  No individual record breakdowns available for this group aggregate.
                </div>
              ) : (
                <div className="border border-app-border rounded-xl overflow-hidden shadow-subtle">
                  <div className="overflow-x-auto max-h-96">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead className="bg-slate-50 border-b border-app-border sticky top-0">
                        <tr>
                          <th className="py-2.5 px-3 font-semibold text-slate-700">Date</th>
                          <th className="py-2.5 px-3 font-semibold text-slate-700">Event / Status</th>
                          <th className="py-2.5 px-3 font-semibold text-slate-700">Details</th>
                          <th className="py-2.5 px-3 font-semibold text-slate-700">Source Traceability</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 font-normal">
                        {evidenceList.map((item, idx) => (
                          <tr key={idx} className="hover:bg-slate-50/60 transition-colors">
                            <td className="py-2.5 px-3 font-medium text-slate-900 whitespace-nowrap">
                              {item.date || '—'}
                            </td>
                            <td className="py-2.5 px-3 text-slate-700">
                              <div className="font-medium">{item.event_type || '—'}</div>
                              {item.status && item.status !== item.event_type && (
                                <div className="text-[11px] text-slate-500">{item.status}</div>
                              )}
                              {item.leave_name && (
                                <div className="text-[11px] text-brand-blue font-medium">{item.leave_name}</div>
                              )}
                            </td>
                            <td className="py-2.5 px-3 text-slate-600">
                              <div>{item.details || '—'}</div>
                              {item.application_lag_days !== null && item.application_lag_days !== undefined && (
                                <div className="text-[11px] text-slate-500">
                                  Applied lag: {item.application_lag_days}d
                                </div>
                              )}
                              {item.approval_turnaround_days !== null && item.approval_turnaround_days !== undefined && (
                                <div className="text-[11px] text-slate-500">
                                  Approval turnaround: {item.approval_turnaround_days}d
                                </div>
                              )}
                            </td>
                            <td className="py-2.5 px-3 text-slate-500 text-[11px] whitespace-nowrap">
                              <div className="font-mono text-slate-700">
                                {item.source_file_name ? `${item.source_file_name} · ` : ''}
                                {item.source_row_number ? `Row ${item.source_row_number}` : (item.request_id ? `Req ${item.request_id.slice(0, 12)}` : 'Governed Fact')}
                              </div>
                              {item.record_id && (
                                <div className="text-[10px] text-slate-400 font-mono truncate max-w-[150px]" title={item.record_id}>
                                  {item.record_id.slice(0, 16)}...
                                </div>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>

            {/* Subtle Investigation Disclaimer */}
            <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-[11px] text-slate-500 leading-relaxed">
              <strong>Notice:</strong> Patterns highlight recurring process behaviour for investigation. They do not establish intent, misconduct, or individual performance.
            </div>
          </div>

          {/* Drawer Footer */}

          <div className="p-4 border-t border-app-border bg-slate-50 flex items-center justify-between text-xs text-app-text-muted">
            <span>Pattern ID: {current.pattern_id}</span>
            <button
              onClick={onClose}
              className="px-3.5 py-1.5 bg-white border border-app-border rounded-lg font-medium text-slate-700 hover:bg-slate-100 transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
