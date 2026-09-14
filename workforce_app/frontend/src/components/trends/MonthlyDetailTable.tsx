import React from 'react';
import { MonthlyTrendPoint, TrendMetricMeta } from '../../types/workforce';

interface MonthlyDetailTableProps {
  timeSeries: MonthlyTrendPoint[];
  metric?: TrendMetricMeta;
}

export const MonthlyDetailTable: React.FC<MonthlyDetailTableProps> = ({
  timeSeries,
  metric,
}) => {
  if (!timeSeries || timeSeries.length === 0) return null;

  const isRateMetric = metric?.format === 'percentage';
  const isTurnaround = metric?.format === 'days';

  return (
    <div className="bg-white border border-app-border rounded-2xl p-5 md:p-6 shadow-subtle min-w-0">
      <div className="flex items-center justify-between gap-3 mb-4">
        <div>
          <h3 className="text-sm font-bold text-text-primary tracking-tight">
            Monthly Detail
          </h3>
          <p className="text-xs text-text-secondary">
            Underlying counts, denominators, and movement per canonical month.
          </p>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs text-text-primary">
          <thead>
            <tr className="border-b border-app-border text-[11px] uppercase tracking-wider text-text-muted font-semibold bg-app-bg/50">
              <th className="py-2.5 px-3">Month</th>
              <th className="py-2.5 px-3">Value</th>
              {isRateMetric ? (
                <>
                  <th className="py-2.5 px-3">Numerator / Denominator</th>
                  <th className="py-2.5 px-3">Excluded (DQ)</th>
                </>
              ) : (
                <th className="py-2.5 px-3">
                  {isTurnaround ? 'Approved Requests' : 'Valid Observations'}
                </th>
              )}
              <th className="py-2.5 px-3">Change vs Prev Month</th>
              <th className="py-2.5 px-3">Volume Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-app-border/60">
            {timeSeries.map((pt, idx) => (
              <tr key={idx} className="hover:bg-app-bg/40 transition-colors">
                <td className="py-2.5 px-3 font-semibold text-text-primary">
                  {pt.period_display}
                </td>
                <td className="py-2.5 px-3 font-bold text-text-primary">
                  {pt.formatted_value || '—'}
                </td>
                {isRateMetric ? (
                  <>
                    <td className="py-2.5 px-3 font-mono">
                      {pt.numerator !== null && pt.denominator !== null
                        ? `${pt.numerator} / ${pt.denominator}`
                        : '—'}
                    </td>
                    <td className="py-2.5 px-3 font-mono">
                      {pt.excluded_data_quality && pt.excluded_data_quality > 0 ? (
                        <span className="text-brand-critical font-bold">
                          {pt.excluded_data_quality}
                        </span>
                      ) : (
                        <span className="text-text-muted">0</span>
                      )}
                    </td>
                  </>
                ) : (
                  <td className="py-2.5 px-3 font-mono">
                    {pt.valid_observation_count ?? '—'}
                  </td>
                )}
                <td className="py-2.5 px-3 font-medium">
                  {pt.mom_change !== null && pt.mom_change !== undefined ? (
                    pt.mom_change > 0 ? (
                      <span className="text-text-primary">
                        +{pt.mom_change.toFixed(1)} {isRateMetric ? 'pp' : ''}
                      </span>
                    ) : pt.mom_change < 0 ? (
                      <span className="text-text-primary">
                        {pt.mom_change.toFixed(1)} {isRateMetric ? 'pp' : ''}
                      </span>
                    ) : (
                      <span className="text-text-muted">0.0</span>
                    )
                  ) : (
                    <span className="text-text-muted">—</span>
                  )}
                </td>
                <td className="py-2.5 px-3">
                  {pt.volume_status ? (
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border ${
                        pt.volume_status === 'LOW'
                          ? 'bg-amber-50 text-amber-800 border-amber-200'
                          : pt.volume_status === 'MODERATE'
                          ? 'bg-blue-50 text-blue-800 border-blue-200'
                          : 'bg-emerald-50 text-emerald-800 border-emerald-200'
                      }`}
                    >
                      {pt.volume_status.charAt(0) + pt.volume_status.slice(1).toLowerCase()}
                    </span>
                  ) : (
                    <span className="text-text-muted">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
