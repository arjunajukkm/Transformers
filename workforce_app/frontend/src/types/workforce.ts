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

export interface SourceFileInfo {
  file_name: string;
  file_index: number;
  rows_ingested: number;
  duplicate_rows_detected?: number;
  rows_included_in_analysis?: number;
  unique_employees: number;
  date_from: string | null;
  date_to: string | null;
  critical_findings: number;
  warnings: number;
}

export interface QualitySummary {
  core_completeness: number;
  full_completeness: number;
  exact_duplicate_rows: number;
  cross_file_exact_duplicate_rows?: number;
  duplicate_rows_excluded_from_analysis?: number;
  critical_findings: number;
  warning_findings: number;
  info_findings: number;
  excluded_employee_days: number;
  findings: QualityFinding[];
  missing_optional_columns: string[];
  source_files?: SourceFileInfo[];
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
  employee_number?: string;
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

// ── Stage 4 Trends Interfaces ──────────────────────────────────────────

export interface TrendMetricMeta {
  id: string;
  label: string;
  category: 'Compliance' | 'Attendance' | 'Approval' | 'Working Time';
  format: 'percentage' | 'days' | 'duration' | 'time' | 'integer';
  direction: 'higher_is_better' | 'lower_is_better' | 'neutral';
  description: string;
}

export interface MonthlyTrendPoint {
  period: string;
  period_display: string;
  value: number | null;
  formatted_value: string | null;
  total_applicable?: number | null;
  evaluable?: number | null;
  excluded_data_quality?: number | null;
  numerator?: number | null;
  denominator?: number | null;
  rate?: number | null;
  valid_observation_count?: number | null;
  volume_status?: 'LOW' | 'MODERATE' | 'HIGH' | null;
  volume_label?: string | null;
  previous_value?: number | null;
  mom_change?: number | null;
  mom_change_pp?: number | null;
}

export type TrendDirection =
  | 'IMPROVING'
  | 'DETERIORATING'
  | 'STABLE'
  | 'INCREASING'
  | 'DECREASING'
  | 'INSUFFICIENT_DATA';

export interface TrendResponse {
  loaded: boolean;
  message?: string;
  filename?: string | null;
  metric?: TrendMetricMeta;
  time_series: MonthlyTrendPoint[];
  current_period?: string | null;
  current_period_display?: string | null;
  current_value: number | null;
  current_value_formatted: string | null;
  previous_value: number | null;
  previous_value_formatted: string | null;
  mom_change: number | null;
  mom_change_pp: number | null;
  first_available_value: number | null;
  first_available_value_formatted: string | null;
  change_since_first: number | null;
  change_since_first_pp: number | null;
  trend_direction: TrendDirection;
  streak_direction: string | null;
  streak_months: number;
  regression_detected: boolean;
  volume_status: 'LOW' | 'MODERATE' | 'HIGH' | null;
  observations: string[];
  date_range_display?: string;
  policy_effective_date: string;
  available_filters?: FilterOptions;
  active_filters?: ActiveFilters;
}

export type GroupedTrendMetrics = Record<string, TrendMetricMeta[]>;
