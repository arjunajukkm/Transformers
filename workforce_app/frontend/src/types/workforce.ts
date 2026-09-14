/**
 * workforce.ts
 * ────────────
 * Type definitions for Workforce Intelligence API requests and responses.
 */

export type PolicyPeriod = 'PRE_POLICY' | 'POST_POLICY';

export interface DatasetInfo {
  rows: number;
  total_source_rows: number;
  unique_employees: number;
  date_min: string | null;
  date_max: string | null;
  display_period?: string;
  policy_period: PolicyPeriod;
  policy_effective_date: string;
}

export interface QualityFinding {
  severity: 'CRITICAL' | 'WARNING' | 'INFO';
  category?: string;
  code?: string;
  field?: string;
  count: number;
  message: string;
}

export interface QualitySummary {
  core_completeness: number;
  full_completeness: number;
  exact_duplicate_rows: number;
  critical_findings: number;
  warning_findings: number;
  info_findings: number;
  excluded_employee_days: number;
  findings: QualityFinding[];
  missing_optional_columns: string[];
}

export interface AttendanceMetric {
  rate: number | null;
  attendance_exception_days: number;
  evaluable_employee_days: number;
  data_quality_excluded_employee_days: number;
  raw_eligible_employee_days: number;
  raw_attendance_exceptions: number;
  raw_exception_rate: number | null;
  policy_effective_date: string;
  metric_governance: string;
}

export interface ComplianceMetric {
  rate: number | null;
  compliant_count: number;
  denominator: number;
  policy_period: PolicyPeriod;
  evaluable_count: number;
  excluded_count: number;
  notes?: string;
}

export interface ApprovalTurnaroundMetric {
  median_approval_turnaround_days: number | null;
  average_approval_turnaround_days: number | null;
  mean_approval_turnaround_days?: number | null;
  approval_count: number;
  pending_approval_count: number;
  average_pending_approval_age_days: number | null;
  avg_pending_age_days?: number | null;
  max_pending_approval_age_days?: number | null;
}

export interface OverviewMetrics {
  policy_period: PolicyPeriod;
  policy_effective_date: string;
  is_post_policy_dataset: boolean;
  attendance_exception_rate: AttendanceMetric;
  overall_leave_application_compliance: ComplianceMetric;
  pre_policy_leave_benchmark: ComplianceMetric;
  wfh_application_compliance: ComplianceMetric;
  pre_policy_wfh_benchmark: ComplianceMetric;
  approval_turnaround: ApprovalTurnaroundMetric;
}

export interface TrendPoint {
  month: string;
  attendance_exception_rate: number | null;
  leave_compliance_rate: number | null;
  wfh_compliance_rate: number | null;
  approval_turnaround_days: number | null;
}

export interface Observation {
  type: 'attendance' | 'data_quality' | 'policy' | 'approval';
  text: string;
}

export interface FilterOptions {
  business_unit: string[];
  department: string[];
  sub_department: string[];
  location: string[];
  reporting_manager: string[];
}

export interface ActiveFilters {
  business_unit?: string;
  department?: string;
  sub_department?: string;
  location?: string;
  reporting_manager?: string;
}

export interface DashboardResponse {
  loaded: boolean;
  message?: string;
  filename?: string | null;
  upload_timestamp?: string | null;
  dataset?: DatasetInfo;
  quality?: QualitySummary;
  metrics?: OverviewMetrics;
  trends?: TrendPoint[];
  observations?: Observation[];
  filters?: FilterOptions;
  active_filters?: ActiveFilters;
}
