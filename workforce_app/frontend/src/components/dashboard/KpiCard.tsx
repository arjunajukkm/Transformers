import React from 'react';
import { ShieldCheck, Laptop, AlertCircle, Clock3 } from 'lucide-react';
import { OverviewMetrics, PolicyPeriod } from '../../types/workforce';

interface KpiCardProps {
  label: string;
  value: string;
  subValue?: string;
  caption?: string;
  contextTag?: string;
  note?: string;
  icon: React.ComponentType<{ className?: string }>;
  status?: 'normal' | 'positive' | 'warning' | 'critical' | 'info';
}

export const KpiCard: React.FC<KpiCardProps> = ({
  label,
  value,
  subValue,
  caption,
  contextTag,
  note,
  icon: Icon,
  status = 'normal',
}) => {
  const statusColors = {
    normal: 'text-text-primary',
    positive: 'text-brand-positive',
    warning: 'text-brand-warning',
    critical: 'text-brand-critical',
    info: 'text-brand-info',
  };

  const statusBg = {
    normal: 'bg-app-bg text-text-secondary',
    positive: 'bg-emerald-50 text-brand-positive border-emerald-100',
    warning: 'bg-amber-50 text-brand-warning border-amber-100',
    critical: 'bg-rose-50 text-brand-critical border-rose-100',
    info: 'bg-blue-50 text-brand-info border-blue-100',
  };

  return (
    <div className="bg-white border border-app-border rounded-xl p-5 shadow-subtle hover:shadow-card-hover transition-shadow duration-200 flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between gap-2 mb-3">
          <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
            {label}
          </span>
          <div className={`p-1.5 rounded-lg border border-transparent ${statusBg[status]}`}>
            <Icon className="w-4 h-4" />
          </div>
        </div>

        <div className="flex items-baseline gap-2 mb-1.5">
          <span className={`text-3xl font-bold tracking-tight ${statusColors[status]}`}>
            {value}
          </span>
          {subValue && (
            <span className="text-xs font-medium text-text-muted">
              {subValue}
            </span>
          )}
        </div>

        {caption && (
          <p className="text-xs font-medium text-text-secondary leading-relaxed">
            {caption}
          </p>
        )}
      </div>

      <div className="mt-4 pt-3 border-t border-app-border/60 flex flex-col gap-1">
        {contextTag && (
          <div className="text-[11px] font-semibold tracking-wide uppercase text-text-muted">
            {contextTag}
          </div>
        )}
        {note && (
          <div className="text-[11px] text-amber-600 font-medium">
            {note}
          </div>
        )}
      </div>
    </div>
  );
};

interface PrimaryKpiGridProps {
  metrics: OverviewMetrics;
  policyPeriod: PolicyPeriod;
}

export const PrimaryKpiGrid: React.FC<PrimaryKpiGridProps> = ({ metrics, policyPeriod }) => {
  const isPrePolicy = policyPeriod === 'PRE_POLICY';

  // 1. Leave Compliance / Benchmark
  const leaveData = isPrePolicy
    ? metrics.pre_policy_leave_benchmark
    : metrics.overall_leave_application_compliance;
  const leaveVal = leaveData.rate !== null ? `${leaveData.rate.toFixed(1)}%` : 'N/A';
  const leaveCaption = isPrePolicy
    ? 'Would meet Oct policy'
    : `${leaveData.compliant_count} of ${leaveData.denominator} compliant requests`;
  const leaveTag = isPrePolicy ? 'Benchmark (Pre-Policy)' : 'Policy Compliance';

  // 2. WFH Compliance / Benchmark
  const wfhData = isPrePolicy
    ? metrics.pre_policy_wfh_benchmark
    : metrics.wfh_application_compliance;
  const wfhVal = wfhData.rate !== null ? `${wfhData.rate.toFixed(1)}%` : 'N/A';
  const wfhCaption = isPrePolicy
    ? 'Would meet Oct policy'
    : `${wfhData.compliant_count} of ${wfhData.denominator} compliant events`;
  const wfhTag = isPrePolicy ? 'Benchmark (Pre-Policy)' : 'Policy Compliance';

  // 3. Governed Attendance Exception Rate
  const attData = metrics.attendance_exception_rate;
  const attVal = attData.rate !== null ? `${attData.rate.toFixed(2)}%` : '0.00%';
  const attCaption = `${attData.attendance_exception_days} exception days / ${attData.evaluable_employee_days} evaluable days`;
  const attNote = attData.data_quality_excluded_employee_days > 0
    ? `${attData.data_quality_excluded_employee_days} day excluded for data quality`
    : undefined;

  // 4. Approval Turnaround
  const apprData = metrics.approval_turnaround;
  const apprVal =
    typeof apprData.median_approval_turnaround_days === 'number' && !isNaN(apprData.median_approval_turnaround_days)
      ? `${apprData.median_approval_turnaround_days.toFixed(1)} days`
      : 'N/A';
  const apprCaption = `${apprData.approval_count || 0} approved requests`;
  const apprTag = (apprData.pending_approval_count || 0) > 0
    ? `${apprData.pending_approval_count} pending approval`
    : 'No pending approvals';

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <KpiCard
        label={isPrePolicy ? 'Leave Application Benchmark' : 'Leave Application Compliance'}
        value={leaveVal}
        caption={leaveCaption}
        contextTag={leaveTag}
        icon={ShieldCheck}
        status={leaveData.rate && leaveData.rate >= 90 ? 'positive' : 'normal'}
      />

      <KpiCard
        label={isPrePolicy ? 'WFH Application Benchmark' : 'WFH Application Compliance'}
        value={wfhVal}
        caption={wfhCaption}
        contextTag={wfhTag}
        icon={Laptop}
        status={wfhData.rate && wfhData.rate >= 90 ? 'positive' : 'normal'}
      />

      <KpiCard
        label="Attendance Exception Rate"
        value={attVal}
        caption={attCaption}
        contextTag="Governed Metric"
        note={attNote}
        icon={AlertCircle}
        status={attData.rate && attData.rate > 20 ? 'warning' : 'normal'}
      />

      <KpiCard
        label="Approval Turnaround"
        value={apprVal}
        caption={apprCaption}
        contextTag={apprTag}
        icon={Clock3}
        status="normal"
      />
    </div>
  );
};
