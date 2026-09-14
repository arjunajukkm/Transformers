import React, { useState } from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from 'recharts';
import { Info, TrendingUp } from 'lucide-react';
import { TrendPoint, PolicyPeriod } from '../../types/workforce';

interface TrendChartProps {
  data: TrendPoint[];
  policyPeriod: PolicyPeriod;
}

type MetricKey =
  | 'attendance_exception_rate'
  | 'leave_compliance_rate'
  | 'wfh_compliance_rate'
  | 'approval_turnaround_days';

interface MetricOption {
  key: MetricKey;
  label: string;
  unit: string;
  color: string;
  domain: [number, number];
}

const METRIC_OPTIONS: MetricOption[] = [
  {
    key: 'attendance_exception_rate',
    label: 'Attendance Exceptions',
    unit: '%',
    color: '#F79009', // Warning orange
    domain: [0, 100],
  },
  {
    key: 'leave_compliance_rate',
    label: 'Leave Compliance',
    unit: '%',
    color: '#12B76A', // Positive green
    domain: [0, 100],
  },
  {
    key: 'wfh_compliance_rate',
    label: 'WFH Compliance',
    unit: '%',
    color: '#194CFF', // Primary blue
    domain: [0, 100],
  },
  {
    key: 'approval_turnaround_days',
    label: 'Approval Turnaround',
    unit: ' days',
    color: '#6172F3', // Info purple
    domain: [0, 30],
  },
];

export const TrendChart: React.FC<TrendChartProps> = ({ data, policyPeriod }) => {
  const [selectedKey, setSelectedKey] = useState<MetricKey>('attendance_exception_rate');

  const activeOption = METRIC_OPTIONS.find((o) => o.key === selectedKey) || METRIC_OPTIONS[0];
  const hasSingleMonth = data.length <= 1;
  const isPrePolicy = policyPeriod === 'PRE_POLICY';

  // Format data for Recharts
  const chartData = data.map((d) => ({
    month: d.month,
    value: d[selectedKey] !== null ? Number(d[selectedKey]) : 0,
    raw: d[selectedKey],
  }));

  // Custom Minimal Tooltip
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const p = payload[0];
      return (
        <div className="bg-white border border-app-border rounded-lg shadow-subtle p-2.5 text-xs">
          <div className="font-semibold text-text-primary mb-1">{label}</div>
          <div className="flex items-center gap-2">
            <span
              className="w-2.5 h-2.5 rounded-sm"
              style={{ backgroundColor: activeOption.color }}
            />
            <span className="text-text-secondary">{activeOption.label}:</span>
            <span className="font-bold text-text-primary">
              {p.value !== null ? `${p.value.toFixed(1)}${activeOption.unit}` : 'N/A'}
            </span>
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="bg-white border border-app-border rounded-xl p-6 shadow-subtle mb-6">
      {/* Chart Header & Metric Selectors */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <div className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-brand-blue" />
            <h3 className="text-base font-bold text-text-primary tracking-tight">
              Process Health Trend
            </h3>
          </div>
          <p className="text-xs text-text-secondary mt-0.5">
            Monthly aggregate process and compliance trajectory.
          </p>
        </div>

        {/* Metric Selector Tabs */}
        <div className="flex flex-wrap items-center bg-app-bg p-1 rounded-lg border border-app-border gap-1">
          {METRIC_OPTIONS.map((opt) => {
            const isSelected = opt.key === selectedKey;
            return (
              <button
                key={opt.key}
                onClick={() => setSelectedKey(opt.key)}
                className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all duration-150 ${
                  isSelected
                    ? 'bg-white text-brand-blue shadow-sm'
                    : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Policy Callout banner if pre-policy */}
      {isPrePolicy ? (
        <div className="mb-4 px-3.5 py-2.5 rounded-lg bg-blue-50/70 border border-blue-100 flex items-center gap-2.5 text-xs text-blue-900">
          <Info className="w-4 h-4 text-brand-blue shrink-0" />
          <span>
            Current dataset is pre-policy and is being used as the baseline.
          </span>
        </div>
      ) : (
        <div className="mb-4 px-3.5 py-2.5 rounded-lg bg-emerald-50/70 border border-emerald-100 flex items-center gap-2.5 text-xs text-emerald-900">
          <Info className="w-4 h-4 text-brand-positive shrink-0" />
          <span>
            Active monitoring against policy effective from 01 Oct 2026.
          </span>
        </div>
      )}

      {/* Chart Canvas */}
      <div className="h-64 w-full">
        {data.length === 0 ? (
          <div className="h-full flex items-center justify-center text-xs text-text-muted">
            No trend points available for this selection.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartData}
              margin={{ top: 10, right: 20, left: -10, bottom: 0 }}
              barSize={hasSingleMonth ? 60 : 36}
            >
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#EAECF0" />
              <XAxis
                dataKey="month"
                stroke="#98A2B3"
                fontSize={12}
                tickLine={false}
                axisLine={{ stroke: '#EAECF0' }}
              />
              <YAxis
                stroke="#98A2B3"
                fontSize={12}
                tickLine={false}
                axisLine={{ stroke: '#EAECF0' }}
                unit={activeOption.unit === '%' ? '%' : ''}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: '#F7F8FA' }} />
              {/* If dataset crosses policy date, vertical reference line could be drawn */}
              {!isPrePolicy && data.some((d) => d.month.includes('Oct 2026')) && (
                <ReferenceLine
                  x="Oct 2026"
                  stroke="#194CFF"
                  strokeDasharray="4 4"
                  label={{
                    value: 'Policy effective · 1 Oct 2026',
                    position: 'top',
                    fill: '#194CFF',
                    fontSize: 11,
                  }}
                />
              )}
              <Bar
                dataKey="value"
                fill={activeOption.color}
                radius={[6, 6, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Single Month Subtle Note as required */}
      {hasSingleMonth && data.length > 0 && (
        <div className="mt-4 pt-3 border-t border-app-border/60 text-center">
          <p className="text-xs text-text-muted italic">
            More months of data will reveal the trend.
          </p>
        </div>
      )}
    </div>
  );
};
