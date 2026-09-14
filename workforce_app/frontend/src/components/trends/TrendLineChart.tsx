import React from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from 'recharts';
import { Info } from 'lucide-react';
import { MonthlyTrendPoint, TrendMetricMeta } from '../../types/workforce';

interface TrendLineChartProps {
  timeSeries: MonthlyTrendPoint[];
  metric?: TrendMetricMeta;
  policyEffectiveDate?: string;
}

export const TrendLineChart: React.FC<TrendLineChartProps> = ({
  timeSeries,
  metric,
}) => {
  if (!timeSeries || timeSeries.length === 0) {
    return (
      <div className="bg-white border border-app-border rounded-2xl p-8 text-center text-text-secondary text-xs">
        No time-series data available for the current selection.
      </div>
    );
  }

  // Format chart data
  const chartData = timeSeries.map((pt) => ({
    ...pt,
    // Use period_display for X-axis
    name: pt.period_display,
    // y-value
    displayValue: pt.value,
  }));

  // Check if October 2026 is in the dataset
  const hasOctober2026 = timeSeries.some((pt) => pt.period_display.includes('Oct 2026'));

  // Custom tooltip
  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data: MonthlyTrendPoint = payload[0].payload;
      return (
        <div className="bg-white border border-app-border shadow-elevation rounded-xl p-3.5 text-xs text-text-primary z-50 min-w-[200px]">
          <div className="font-bold text-text-primary border-b border-app-border pb-1.5 mb-2 flex items-center justify-between">
            <span>{data.period_display}</span>
            {data.volume_status && (
              <span className="text-[10px] font-semibold text-text-muted">
                {data.volume_status.charAt(0) + data.volume_status.slice(1).toLowerCase()} volume
              </span>
            )}
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-text-secondary">{metric?.label || 'Value'}:</span>
              <span className="font-extrabold text-brand-blue">{data.formatted_value || 'N/A'}</span>
            </div>

            {data.denominator !== undefined && data.denominator !== null && (
              <>
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-text-muted">Numerator / Denominator:</span>
                  <span className="font-mono font-medium">
                    {data.numerator} / {data.denominator}
                  </span>
                </div>

                {Boolean(data.excluded_data_quality && data.excluded_data_quality > 0) && (
                  <div className="flex items-center justify-between text-[11px] text-brand-critical">
                    <span>Excluded (Data Quality):</span>
                    <span className="font-mono font-bold">{data.excluded_data_quality}</span>
                  </div>
                )}
              </>
            )}

            {data.valid_observation_count !== undefined && data.valid_observation_count !== null && (
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-text-muted">Observations:</span>
                <span className="font-mono font-medium">{data.valid_observation_count}</span>
              </div>
            )}

            {data.mom_change !== undefined && data.mom_change !== null && (
              <div className="flex items-center justify-between text-[11px] pt-1 border-t border-app-border/60">
                <span className="text-text-muted">MoM Movement:</span>
                <span className="font-medium">
                  {data.mom_change > 0 ? `+${data.mom_change.toFixed(1)}` : data.mom_change.toFixed(1)}
                  {metric?.format === 'percentage' ? ' pp' : ''}
                </span>
              </div>
            )}
          </div>
        </div>
      );
    }
    return null;
  };

  // Y-axis tick formatter
  const formatYAxis = (val: number) => {
    if (metric?.format === 'percentage') {
      return `${val}%`;
    }
    if (metric?.format === 'days') {
      return `${val}d`;
    }
    if (metric?.format === 'duration') {
      const h = Math.floor(val / 60);
      return `${h}h`;
    }
    if (metric?.format === 'time') {
      const h = Math.floor(val / 60);
      const m = Math.round(val % 60);
      const suffix = h < 12 ? 'AM' : 'PM';
      const h12 = h % 12 === 0 ? 12 : h % 12;
      return `${h12}:${m < 10 ? '0' : ''}${m} ${suffix}`;
    }
    return `${val}`;
  };

  return (
    <div className="bg-white border border-app-border rounded-2xl p-5 md:p-6 shadow-subtle min-w-0">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4 min-w-0">
        <div>
          <h3 className="text-sm font-bold text-text-primary tracking-tight">
            Monthly Trajectory
          </h3>
          <p className="text-xs text-text-secondary">
            Process movement and governance by canonical analytical month.
          </p>
        </div>

        {timeSeries.length === 1 && (
          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-50 text-amber-800 border border-amber-200 text-xs shrink-0">
            <Info className="w-3.5 h-3.5 text-brand-warning shrink-0" />
            <span>More historical data is needed to determine a trend</span>
          </div>
        )}
      </div>

      <div className="w-full h-[320px] min-w-0">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={chartData}
            margin={{ top: 20, right: 25, left: 0, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
            <XAxis
              dataKey="name"
              stroke="#94a3b8"
              fontSize={11}
              tickLine={false}
              axisLine={{ stroke: '#e2e8f0' }}
            />
            <YAxis
              stroke="#94a3b8"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              tickFormatter={formatYAxis}
              domain={metric?.format === 'percentage' ? [0, 100] : ['auto', 'auto']}
            />
            <Tooltip content={<CustomTooltip />} />

            {/* Subtle policy reference line: drawn ONLY when Oct 2026 is visible */}
            {hasOctober2026 && (
              <ReferenceLine
                x="Oct 2026"
                stroke="#94a3b8"
                strokeDasharray="4 4"
                label={{
                  value: 'Policy effective',
                  position: 'top',
                  fill: '#64748b',
                  fontSize: 10,
                  fontWeight: 600,
                }}
              />
            )}

            <Line
              type="monotone"
              dataKey="displayValue"
              stroke="#2563eb"
              strokeWidth={2.5}
              dot={{
                r: timeSeries.length === 1 ? 6 : 4,
                stroke: '#2563eb',
                strokeWidth: 2,
                fill: '#ffffff',
              }}
              activeDot={{ r: 6, fill: '#2563eb' }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
