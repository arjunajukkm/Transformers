import React from 'react';
import { Users, CalendarCheck, AlertTriangle, FileClock, CheckCircle2 } from 'lucide-react';
import { OverviewMetrics, QualitySummary, DatasetInfo } from '../../types/workforce';

interface MetricStripProps {
  metrics: OverviewMetrics;
  quality?: QualitySummary;
  dataset?: DatasetInfo;
}

export const MetricStrip: React.FC<MetricStripProps> = ({ metrics, quality, dataset }) => {
  const employeesCount = dataset?.unique_employees ?? 0;
  const evaluableDays = metrics.attendance_exception_rate.evaluable_employee_days;
  const exceptionDays = metrics.attendance_exception_rate.attendance_exception_days;
  const pendingApprovals = metrics.approval_turnaround.pending_approval_count;
  const coreCompleteness = quality?.core_completeness ?? 100;

  const rawAge =
    metrics.approval_turnaround.average_pending_approval_age_days ??
    metrics.approval_turnaround.avg_pending_age_days;
  const ageDisplay =
    typeof rawAge === 'number' && !isNaN(rawAge)
      ? `avg age ${rawAge.toFixed(1)}d`
      : 'awaiting action';

  const items = [
    {
      label: 'Employees',
      value: employeesCount.toString(),
      sub: 'in loaded period',
      icon: Users,
    },
    {
      label: 'Evaluable Days',
      value: evaluableDays.toString(),
      sub: 'attendance facts',
      icon: CalendarCheck,
    },
    {
      label: 'Exception Days',
      value: exceptionDays.toString(),
      sub: 'governed exceptions',
      icon: AlertTriangle,
      highlight: exceptionDays > 0,
    },
    {
      label: 'Pending Approvals',
      value: pendingApprovals.toString(),
      sub: ageDisplay,
      icon: FileClock,
    },
    {
      label: 'Core Completeness',
      value: `${coreCompleteness.toFixed(1)}%`,
      sub: 'source rows valid',
      icon: CheckCircle2,
      positive: coreCompleteness === 100,
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
      {items.map((it, idx) => {
        const Icon = it.icon;
        return (
          <div
            key={idx}
            className="bg-white border border-app-border rounded-xl px-4 py-3 shadow-subtle flex items-center gap-3.5"
          >
            <div className="w-9 h-9 rounded-lg bg-app-bg border border-app-border/80 flex items-center justify-center text-text-secondary shrink-0">
              <Icon className="w-4 h-4 text-text-muted" />
            </div>
            <div className="min-w-0">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-text-muted truncate">
                {it.label}
              </div>
              <div className="flex items-baseline gap-1.5">
                <span className="text-lg font-bold text-text-primary tracking-tight">
                  {it.value}
                </span>
                <span className="text-[11px] text-text-secondary truncate">
                  {it.sub}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};
