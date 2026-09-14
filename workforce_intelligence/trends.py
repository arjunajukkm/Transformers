"""
trends.py
─────────
Deterministic workforce time-series and monthly trends analytical engine.
Provides monthly aggregations, month-over-month comparisons, trend direction,
streak detection, regression detection, volume classification, and deterministic
management intelligence observations.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd

from workforce_intelligence.metrics import (
    _safe_rate,
    build_employee_day_facts,
    normalize_approval_state,
)
from workforce_intelligence.policy_config import (
    POLICY_EFFECTIVE_DATE,
    POLICY_EFFECTIVE_DATE_STR,
)


# ── Trend Metric Catalogue ──────────────────────────────────────────────

@dataclass(frozen=True)
class TrendMetricDefinition:
    id: str
    label: str
    category: str       # "Compliance", "Attendance", "Approval", "Working Time"
    format: str         # "percentage", "days", "duration", "time", "integer"
    direction: str      # "higher_is_better", "lower_is_better", "neutral"
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


TREND_METRICS: Dict[str, TrendMetricDefinition] = {
    # 1. Compliance
    "leave_application_compliance": TrendMetricDefinition(
        id="leave_application_compliance",
        label="Leave Application Compliance",
        category="Compliance",
        format="percentage",
        direction="higher_is_better",
        description="Monthly rate of compliant leave requests with full denominator governance.",
    ),
    "pl_application_compliance": TrendMetricDefinition(
        id="pl_application_compliance",
        label="PL Application Compliance",
        category="Compliance",
        format="percentage",
        direction="higher_is_better",
        description="Monthly compliance rate for Privilege Leave applications requiring >= 2 days advance notice.",
    ),
    "non_pl_application_compliance": TrendMetricDefinition(
        id="non_pl_application_compliance",
        label="Non-PL Application Compliance",
        category="Compliance",
        format="percentage",
        direction="higher_is_better",
        description="Monthly compliance rate for Non-PL leave applications requiring submission <= 3 days from start.",
    ),
    "wfh_application_compliance": TrendMetricDefinition(
        id="wfh_application_compliance",
        label="WFH Application Compliance",
        category="Compliance",
        format="percentage",
        direction="higher_is_better",
        description="Monthly compliance rate for Work From Home applications requiring same-day or advance notice.",
    ),

    # 2. Attendance
    "attendance_exception_rate": TrendMetricDefinition(
        id="attendance_exception_rate",
        label="Attendance Exception Rate",
        category="Attendance",
        format="percentage",
        direction="lower_is_better",
        description="Monthly percentage of evaluable eligible employee-days containing an attendance exception.",
    ),
    "missing_swipe_rate": TrendMetricDefinition(
        id="missing_swipe_rate",
        label="Missing Swipe Rate",
        category="Attendance",
        format="percentage",
        direction="lower_is_better",
        description="Monthly percentage of evaluable eligible employee-days with missing in or out swipe.",
    ),
    "absence_rate": TrendMetricDefinition(
        id="absence_rate",
        label="Absence Rate",
        category="Attendance",
        format="percentage",
        direction="lower_is_better",
        description="Monthly percentage of evaluable eligible employee-days marked as absent.",
    ),
    "regularization_rate": TrendMetricDefinition(
        id="regularization_rate",
        label="Attendance Regularisation Rate",
        category="Attendance",
        format="percentage",
        direction="neutral",
        description="Monthly percentage of evaluable eligible employee-days with attendance regularization.",
    ),

    # 3. Approval
    "median_approval_turnaround": TrendMetricDefinition(
        id="median_approval_turnaround",
        label="Median Approval Turnaround",
        category="Approval",
        format="days",
        direction="lower_is_better",
        description="Median turnaround time (in days) from application to approval for requests applied in the month.",
    ),
    "average_approval_turnaround": TrendMetricDefinition(
        id="average_approval_turnaround",
        label="Average Approval Turnaround",
        category="Approval",
        format="days",
        direction="lower_is_better",
        description="Average turnaround time (in days) from application to approval for requests applied in the month.",
    ),
    "pending_approval_count": TrendMetricDefinition(
        id="pending_approval_count",
        label="Pending Approval Count",
        category="Approval",
        format="integer",
        direction="lower_is_better",
        description="Count of pending approval requests applied in the month.",
    ),
    "average_pending_approval_age": TrendMetricDefinition(
        id="average_pending_approval_age",
        label="Average Pending Approval Age",
        category="Approval",
        format="days",
        direction="lower_is_better",
        description="Average age (in days) of pending approval requests applied in the month.",
    ),

    # 4. Working Time
    "average_effective_hours": TrendMetricDefinition(
        id="average_effective_hours",
        label="Average Effective Hours",
        category="Working Time",
        format="duration",
        direction="neutral",
        description="Average effective working hours per valid working day.",
    ),
    "median_effective_hours": TrendMetricDefinition(
        id="median_effective_hours",
        label="Median Effective Hours",
        category="Working Time",
        format="duration",
        direction="neutral",
        description="Median effective working hours per valid working day.",
    ),
    "average_arrival_time": TrendMetricDefinition(
        id="average_arrival_time",
        label="Average Arrival Time",
        category="Working Time",
        format="time",
        direction="neutral",
        description="Average morning arrival time for valid working days.",
    ),
    "median_arrival_time": TrendMetricDefinition(
        id="median_arrival_time",
        label="Median Arrival Time",
        category="Working Time",
        format="time",
        direction="neutral",
        description="Median morning arrival time for valid working days.",
    ),
    "average_exit_time": TrendMetricDefinition(
        id="average_exit_time",
        label="Average Exit Time",
        category="Working Time",
        format="time",
        direction="neutral",
        description="Average evening departure time for valid working days.",
    ),
    "median_exit_time": TrendMetricDefinition(
        id="median_exit_time",
        label="Median Exit Time",
        category="Working Time",
        format="time",
        direction="neutral",
        description="Median evening departure time for valid working days.",
    ),
}


def get_trend_metric_catalogue() -> Dict[str, List[Dict[str, Any]]]:
    """Return trend metric catalogue grouped by category."""
    grouped: Dict[str, List[Dict[str, Any]]] = {
        "Compliance": [],
        "Attendance": [],
        "Approval": [],
        "Working Time": [],
    }
    for m in TREND_METRICS.values():
        grouped[m.category].append(m.to_dict())
    return grouped


# ── Materiality Thresholds ──────────────────────────────────────────────

MATERIALITY_THRESHOLD_RATE = 1.0       # 1.0 percentage point
MATERIALITY_THRESHOLD_DAYS = 0.5       # 0.5 day for approval turnaround
MATERIALITY_THRESHOLD_MINUTES = 10.0   # 10 minutes for timing/duration
MATERIALITY_THRESHOLD_COUNT = 1.0      # 1 unit for integer count


def get_materiality_threshold(metric_def: TrendMetricDefinition) -> float:
    """Return the materiality threshold for a given metric."""
    if metric_def.format == "percentage":
        return MATERIALITY_THRESHOLD_RATE
    if metric_def.format == "days":
        return MATERIALITY_THRESHOLD_DAYS
    if metric_def.format in ("duration", "time"):
        return MATERIALITY_THRESHOLD_MINUTES
    return MATERIALITY_THRESHOLD_COUNT


# ── Volume Classification ───────────────────────────────────────────────

def classify_volume_status(count_or_denominator: Optional[int]) -> str:
    """
    Classify volume status deterministically:
    - LOW: < 10
    - MODERATE: 10 - 49
    - HIGH: >= 50
    """
    if count_or_denominator is None or count_or_denominator < 10:
        return "LOW"
    if count_or_denominator <= 49:
        return "MODERATE"
    return "HIGH"


# ── Formatting Helpers ──────────────────────────────────────────────────

def format_time_minutes(minutes: Optional[Union[float, int]]) -> Optional[str]:
    """Format minutes from midnight into '09:42 AM' or '06:31 PM'."""
    if minutes is None or pd.isna(minutes):
        return None
    total_mins = int(round(float(minutes))) % 1440
    hours = total_mins // 60
    mins = total_mins % 60
    suffix = "AM" if hours < 12 else "PM"
    h12 = hours % 12
    if h12 == 0:
        h12 = 12
    return f"{h12:02d}:{mins:02d} {suffix}"


def format_duration_minutes(minutes: Optional[Union[float, int]]) -> Optional[str]:
    """Format duration minutes into '8h 14m'."""
    if minutes is None or pd.isna(minutes):
        return None
    total_mins = int(round(float(minutes)))
    hours = total_mins // 60
    mins = total_mins % 60
    return f"{hours}h {mins:02d}m"


def format_metric_value(val: Optional[Union[float, int]], format_type: str) -> Optional[str]:
    """Format a metric value for display based on its format type."""
    if val is None or pd.isna(val):
        return None
    fval = float(val)
    if format_type == "percentage":
        return f"{fval:.1f}%"
    if format_type == "days":
        return f"{fval:.1f} d"
    if format_type == "time":
        return format_time_minutes(fval)
    if format_type == "duration":
        return format_duration_minutes(fval)
    if format_type == "integer":
        return f"{int(round(fval))}"
    return f"{fval:.2f}"


def format_period_label(period_month_str: str) -> str:
    """Format '2026-08-01' into 'Aug 2026'."""
    try:
        dt = datetime.strptime(period_month_str, "%Y-%m-01")
        return dt.strftime("%b %Y")
    except Exception:
        return period_month_str


# ── Monthly Point Contract ──────────────────────────────────────────────

@dataclass
class TrendPoint:
    period: str                      # "2026-08-01"
    period_display: str              # "Aug 2026"
    value: Optional[float]           # Metric value (in minutes for time/duration, % for rate, days for turnaround)
    formatted_value: Optional[str]   # Human readable representation (e.g. "84.0%", "8h 14m")
    
    # Denominator & governance context
    total_applicable: Optional[int] = None
    evaluable: Optional[int] = None
    excluded_data_quality: Optional[int] = None
    numerator: Optional[int] = None
    denominator: Optional[int] = None
    rate: Optional[float] = None
    valid_observation_count: Optional[int] = None
    
    # Volume status
    volume_status: Optional[str] = None
    volume_label: Optional[str] = None

    # MoM movement
    previous_value: Optional[float] = None
    mom_change: Optional[float] = None
    mom_change_pp: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Monthly Aggregations ────────────────────────────────────────────────

def extract_canonical_month(dt: Any) -> Optional[str]:
    """Extract canonical 'YYYY-MM-01' period string from any date representation."""
    if dt is None or pd.isna(dt):
        return None
    try:
        ts = pd.to_datetime(dt)
        if pd.isna(ts):
            return None
        return ts.strftime("%Y-%m-01")
    except Exception:
        return None


def calculate_monthly_compliance(
    evaluated_df: pd.DataFrame,
    evaluated_requests: Optional[List[Dict[str, Any]]],
    metric_id: str,
) -> List[TrendPoint]:
    """Aggregate monthly compliance metrics with full denominator governance."""
    metric_def = TREND_METRICS[metric_id]
    points: List[TrendPoint] = []

    if metric_id in ("leave_application_compliance", "pl_application_compliance", "non_pl_application_compliance"):
        if not evaluated_requests:
            return []
        req_df = pd.DataFrame(evaluated_requests)
        if req_df.empty or "request_start_date" not in req_df.columns:
            return []

        req_df["_month"] = req_df["request_start_date"].apply(extract_canonical_month)
        valid_reqs = req_df[req_df["_month"].notna()].copy()

        # Filter by sub-category if applicable
        if metric_id == "pl_application_compliance":
            valid_reqs = valid_reqs[valid_reqs["is_pl"] == True]
        elif metric_id == "non_pl_application_compliance":
            valid_reqs = valid_reqs[valid_reqs["is_pl"] == False]

        for p_month in sorted(valid_reqs["_month"].unique()):
            m_group = valid_reqs[valid_reqs["_month"] == p_month]
            tot = len(m_group)
            dq_ex = int((m_group["compliance_status"] == "DATA_QUALITY_UNCERTAIN").sum())
            evaluable = tot - dq_ex
            
            # Compliance uses benchmark_compliant before 2026-10-01 and policy_compliant on or after
            # Evaluated per request start date
            is_post_policy = pd.to_datetime(p_month).date() >= POLICY_EFFECTIVE_DATE
            if is_post_policy:
                comp_num = int((m_group["policy_compliant"] == True).sum())
            else:
                comp_num = int((m_group["benchmark_compliant"] == True).sum())

            rate = _safe_rate(comp_num, evaluable)
            vol_st = classify_volume_status(evaluable)
            vol_lbl = f"Volume: {vol_st.capitalize()} · {evaluable} evaluable request{'s' if evaluable != 1 else ''}"

            points.append(TrendPoint(
                period=p_month,
                period_display=format_period_label(p_month),
                value=rate,
                formatted_value=format_metric_value(rate, "percentage"),
                total_applicable=tot,
                evaluable=evaluable,
                excluded_data_quality=dq_ex,
                numerator=comp_num,
                denominator=evaluable,
                rate=rate,
                volume_status=vol_st,
                volume_label=vol_lbl,
            ))

    elif metric_id == "wfh_application_compliance":
        wfh_df = evaluated_df[evaluated_df["policy_event_type"] == "WFH"].copy() if "policy_event_type" in evaluated_df.columns else pd.DataFrame()
        if wfh_df.empty or "Date" not in wfh_df.columns:
            return []

        wfh_df["_month"] = wfh_df["Date"].apply(extract_canonical_month)
        valid_wfh = wfh_df[wfh_df["_month"].notna()].copy()

        for p_month in sorted(valid_wfh["_month"].unique()):
            m_group = valid_wfh[valid_wfh["_month"] == p_month]
            tot = len(m_group)
            dq_ex = int((m_group["compliance_status"] == "DATA_QUALITY_UNCERTAIN").sum())
            evaluable = tot - dq_ex
            
            is_post_policy = pd.to_datetime(p_month).date() >= POLICY_EFFECTIVE_DATE
            if is_post_policy:
                comp_num = int((m_group["policy_compliant"] == True).sum())
            else:
                comp_num = int((m_group["benchmark_compliant"] == True).sum())

            rate = _safe_rate(comp_num, evaluable)
            vol_st = classify_volume_status(evaluable)
            vol_lbl = f"Volume: {vol_st.capitalize()} · {evaluable} evaluable event{'s' if evaluable != 1 else ''}"

            points.append(TrendPoint(
                period=p_month,
                period_display=format_period_label(p_month),
                value=rate,
                formatted_value=format_metric_value(rate, "percentage"),
                total_applicable=tot,
                evaluable=evaluable,
                excluded_data_quality=dq_ex,
                numerator=comp_num,
                denominator=evaluable,
                rate=rate,
                volume_status=vol_st,
                volume_label=vol_lbl,
            ))

    return points


def calculate_monthly_attendance(
    employee_day_facts: pd.DataFrame,
    metric_id: str,
) -> List[TrendPoint]:
    """Aggregate monthly governed attendance metrics from employee-day facts."""
    if employee_day_facts.empty or "Date" not in employee_day_facts.columns:
        return []

    facts = employee_day_facts.copy()
    facts["_month"] = facts["Date"].apply(extract_canonical_month)
    valid_facts = facts[facts["_month"].notna()].copy()

    points: List[TrendPoint] = []
    for p_month in sorted(valid_facts["_month"].unique()):
        m_group = valid_facts[valid_facts["_month"] == p_month]
        
        raw_eligible = int((m_group["is_eligible_attendance_day"] == True).sum())
        evaluable_mask = (m_group["is_eligible_attendance_day"] == True) & (m_group["is_metric_evaluable"] == True)
        evaluable = int(evaluable_mask.sum())
        dq_ex = raw_eligible - evaluable

        evaluable_rows = m_group[evaluable_mask]

        if metric_id == "attendance_exception_rate":
            num = int((evaluable_rows["is_attendance_exception"] == True).sum())
        elif metric_id == "missing_swipe_rate":
            num = int((evaluable_rows["has_missing_swipe"] == True).sum())
        elif metric_id == "absence_rate":
            num = int((evaluable_rows["has_absent"] == True).sum())
        elif metric_id == "regularization_rate":
            num = int((evaluable_rows["has_regularization"] == True).sum())
        else:
            num = 0

        rate = _safe_rate(num, evaluable)
        vol_st = classify_volume_status(evaluable)
        vol_lbl = f"Volume: {vol_st.capitalize()} · {evaluable} evaluable employee-days"

        points.append(TrendPoint(
            period=p_month,
            period_display=format_period_label(p_month),
            value=rate,
            formatted_value=format_metric_value(rate, "percentage"),
            total_applicable=raw_eligible,
            evaluable=evaluable,
            excluded_data_quality=dq_ex,
            numerator=num,
            denominator=evaluable,
            rate=rate,
            volume_status=vol_st,
            volume_label=vol_lbl,
        ))

    return points


def calculate_monthly_approvals(
    evaluated_df: pd.DataFrame,
    metric_id: str,
    analysis_as_of_date: Optional[Union[date, datetime]] = None,
) -> List[TrendPoint]:
    """Aggregate monthly manager approval cycle metrics grouped by application month."""
    if evaluated_df.empty or "Applied On" not in evaluated_df.columns:
        return []

    df = evaluated_df.copy()
    df["_app_month"] = df["Applied On"].apply(extract_canonical_month)
    valid_df = df[df["_app_month"].notna()].copy()
    if valid_df.empty:
        return []

    if "approval_state" not in valid_df.columns:
        valid_df["approval_state"] = valid_df["Approval Status"].apply(normalize_approval_state) if "Approval Status" in valid_df.columns else "UNKNOWN"

    # As of date for pending age
    if analysis_as_of_date is None:
        if "Date" in evaluated_df.columns and not evaluated_df["Date"].dropna().empty:
            analysis_as_of_date = pd.to_datetime(evaluated_df["Date"]).dropna().max().date()
        else:
            analysis_as_of_date = date.today()
    elif isinstance(analysis_as_of_date, datetime):
        analysis_as_of_date = analysis_as_of_date.date()

    points: List[TrendPoint] = []
    for p_month in sorted(valid_df["_app_month"].unique()):
        m_group = valid_df[valid_df["_app_month"] == p_month]
        
        approved_rows = m_group[m_group["approval_state"] == "APPROVED"]
        valid_turnarounds = (
            approved_rows["approval_turnaround_days"].dropna().astype(float)
            if "approval_turnaround_days" in approved_rows.columns
            else pd.Series([], dtype=float)
        )
        valid_obs = len(valid_turnarounds)

        pending_rows = m_group[m_group["approval_state"] == "PENDING"]
        pending_cnt = len(pending_rows)

        val: Optional[float] = None
        fmt_type = "days"

        if metric_id == "median_approval_turnaround":
            val = round(float(valid_turnarounds.median()), 2) if not valid_turnarounds.empty else None
        elif metric_id == "average_approval_turnaround":
            val = round(float(valid_turnarounds.mean()), 2) if not valid_turnarounds.empty else None
        elif metric_id == "pending_approval_count":
            val = float(pending_cnt)
            fmt_type = "integer"
            valid_obs = pending_cnt
        elif metric_id == "average_pending_approval_age":
            pending_ages = []
            for _, r in pending_rows.iterrows():
                app_on = r.get("Applied On")
                if pd.notna(app_on):
                    age = (analysis_as_of_date - pd.to_datetime(app_on).date()).days
                    if age >= 0:
                        pending_ages.append(age)
            val = round(float(np.mean(pending_ages)), 2) if pending_ages else None
            valid_obs = len(pending_ages)

        vol_st = classify_volume_status(valid_obs)
        vol_lbl = f"Volume: {vol_st.capitalize()} · {valid_obs} observation{'s' if valid_obs != 1 else ''}"

        points.append(TrendPoint(
            period=p_month,
            period_display=format_period_label(p_month),
            value=val,
            formatted_value=format_metric_value(val, fmt_type),
            valid_observation_count=valid_obs,
            volume_status=vol_st,
            volume_label=vol_lbl,
        ))

    return points


def calculate_monthly_working_time(
    evaluated_df: pd.DataFrame,
    metric_id: str,
) -> List[TrendPoint]:
    """Aggregate monthly working time metrics (minutes internally, formatted for display)."""
    if evaluated_df.empty or "Date" not in evaluated_df.columns:
        return []

    df = evaluated_df.copy()
    df["_month"] = df["Date"].apply(extract_canonical_month)
    valid_df = df[df["_month"].notna()].copy()
    if valid_df.empty:
        return []

    points: List[TrendPoint] = []
    for p_month in sorted(valid_df["_month"].unique()):
        m_group = valid_df[valid_df["_month"] == p_month]

        val: Optional[float] = None
        fmt_type = "duration" if "hours" in metric_id else "time"
        valid_obs = 0

        if metric_id in ("average_effective_hours", "median_effective_hours"):
            series = m_group["effective_hours_minutes"].dropna().astype(float) if "effective_hours_minutes" in m_group.columns else pd.Series([], dtype=float)
            valid_obs = len(series)
            if not series.empty:
                val = round(float(series.mean()), 1) if metric_id == "average_effective_hours" else round(float(series.median()), 1)

        elif metric_id in ("average_arrival_time", "median_arrival_time"):
            series = m_group["in_time_minutes"].dropna().astype(float) if "in_time_minutes" in m_group.columns else pd.Series([], dtype=float)
            valid_obs = len(series)
            if not series.empty:
                val = round(float(series.mean()), 1) if metric_id == "average_arrival_time" else round(float(series.median()), 1)

        elif metric_id in ("average_exit_time", "median_exit_time"):
            series = m_group["out_time_minutes"].dropna().astype(float) if "out_time_minutes" in m_group.columns else pd.Series([], dtype=float)
            valid_obs = len(series)
            if not series.empty:
                val = round(float(series.mean()), 1) if metric_id == "average_exit_time" else round(float(series.median()), 1)

        vol_st = classify_volume_status(valid_obs)
        vol_lbl = f"Volume: {vol_st.capitalize()} · {valid_obs} observation{'s' if valid_obs != 1 else ''}"

        points.append(TrendPoint(
            period=p_month,
            period_display=format_period_label(p_month),
            value=val,
            formatted_value=format_metric_value(val, fmt_type),
            valid_observation_count=valid_obs,
            volume_status=vol_st,
            volume_label=vol_lbl,
        ))

    return points


# ── Time-Series Comparisons & Indicators ─────────────────────────────────

def attach_mom_comparisons(points: List[TrendPoint], metric_def: TrendMetricDefinition) -> List[TrendPoint]:
    """Calculate and attach Month-over-Month changes to each point in the series."""
    for i in range(len(points)):
        if i == 0:
            points[i].previous_value = None
            points[i].mom_change = None
            points[i].mom_change_pp = None
        else:
            prev_val = points[i - 1].value
            curr_val = points[i].value
            points[i].previous_value = prev_val
            if prev_val is not None and curr_val is not None:
                diff = round(curr_val - prev_val, 2)
                points[i].mom_change = diff
                if metric_def.format == "percentage":
                    points[i].mom_change_pp = diff
            else:
                points[i].mom_change = None
                points[i].mom_change_pp = None
    return points


def calculate_trend_direction(
    points: List[TrendPoint],
    metric_def: TrendMetricDefinition,
) -> str:
    """
    Determine deterministic trend direction:
    - If fewer than 3 points: INSUFFICIENT_DATA
    - Uses 3-month window linear slope vs materiality threshold
    - Directional: IMPROVING, DETERIORATING, STABLE
    - Neutral: INCREASING, DECREASING, STABLE
    """
    valid_points = [p for p in points if p.value is not None]
    if len(valid_points) < 3:
        return "INSUFFICIENT_DATA"

    # Take most recent 3 months
    window = valid_points[-3:]
    y = [p.value for p in window]
    x = [0.0, 1.0, 2.0]

    # Linear slope
    slope = float(np.polyfit(x, y, 1)[0])
    threshold = get_materiality_threshold(metric_def)

    if metric_def.direction == "higher_is_better":
        if slope >= threshold:
            return "IMPROVING"
        if slope <= -threshold:
            return "DETERIORATING"
        return "STABLE"

    elif metric_def.direction == "lower_is_better":
        if slope <= -threshold:
            return "IMPROVING"
        if slope >= threshold:
            return "DETERIORATING"
        return "STABLE"

    else:  # "neutral"
        if slope >= threshold:
            return "INCREASING"
        if slope <= -threshold:
            return "DECREASING"
        return "STABLE"


def calculate_streak(
    points: List[TrendPoint],
    metric_def: TrendMetricDefinition,
) -> Tuple[Optional[str], int]:
    """
    Calculate consecutive monthly movement in the same direction above materiality threshold.
    Returns (trend_streak_direction, trend_streak_months).
    """
    valid_points = [p for p in points if p.value is not None]
    if len(valid_points) < 2:
        return None, 0

    threshold = get_materiality_threshold(metric_def)
    
    # Check latest step
    latest_delta = valid_points[-1].value - valid_points[-2].value
    if abs(latest_delta) < threshold:
        return "STABLE", 0

    # Determine step direction
    if metric_def.direction == "higher_is_better":
        target_dir = "IMPROVING" if latest_delta > 0 else "DETERIORATING"
    elif metric_def.direction == "lower_is_better":
        target_dir = "IMPROVING" if latest_delta < 0 else "DETERIORATING"
    else:
        target_dir = "INCREASING" if latest_delta > 0 else "DECREASING"

    # Count consecutive backwards
    streak_count = 0
    for i in range(len(valid_points) - 1, 0, -1):
        delta = valid_points[i].value - valid_points[i - 1].value
        if abs(delta) < threshold:
            break

        if metric_def.direction == "higher_is_better":
            step_dir = "IMPROVING" if delta > 0 else "DETERIORATING"
        elif metric_def.direction == "lower_is_better":
            step_dir = "IMPROVING" if delta < 0 else "DETERIORATING"
        else:
            step_dir = "INCREASING" if delta > 0 else "DECREASING"

        if step_dir == target_dir:
            streak_count += 1
        else:
            break

    return target_dir, streak_count


def detect_regression(
    points: List[TrendPoint],
    metric_def: TrendMetricDefinition,
) -> bool:
    """
    Detect deterministic trend regression:
    Only triggers after meaningful prior improvement followed by sustained deterioration.
    """
    valid_points = [p for p in points if p.value is not None]
    if len(valid_points) < 3 or metric_def.direction == "neutral":
        return False

    threshold = get_materiality_threshold(metric_def)

    # Compute step directions for all consecutive pairs
    step_dirs = []
    for i in range(1, len(valid_points)):
        delta = valid_points[i].value - valid_points[i - 1].value
        if abs(delta) < threshold:
            step_dirs.append("STABLE")
        elif metric_def.direction == "higher_is_better":
            step_dirs.append("IMPROVING" if delta > 0 else "DETERIORATING")
        else:
            step_dirs.append("IMPROVING" if delta < 0 else "DETERIORATING")

    # Look for at least one prior IMPROVING step followed by recent DETERIORATING steps
    has_prior_improvement = False
    for d in step_dirs[:-1]:
        if d == "IMPROVING":
            has_prior_improvement = True
            break

    latest_is_deteriorating = step_dirs[-1] == "DETERIORATING"
    # Sustained or meaningful deterioration: either last 2 steps deteriorating or last step deteriorating after improvement
    if has_prior_improvement and latest_is_deteriorating:
        # Check if the cumulative deterioration reverses prior gains
        if len(step_dirs) >= 2 and step_dirs[-2] == "DETERIORATING":
            return True
        # Or if latest deterioration exceeds cumulative prior improvement
        if len(step_dirs) >= 2 and step_dirs[-2] == "IMPROVING":
            prior_delta = abs(valid_points[-2].value - valid_points[-3].value)
            recent_deterioration = abs(valid_points[-1].value - valid_points[-2].value)
            if recent_deterioration >= prior_delta * 0.8:
                return True

    return False


def generate_trend_observations(
    points: List[TrendPoint],
    metric_def: TrendMetricDefinition,
    current_value: Optional[float],
    previous_value: Optional[float],
    mom_change: Optional[float],
    first_value: Optional[float],
    change_since_first: Optional[float],
    trend_direction: str,
    streak_direction: Optional[str],
    streak_months: int,
    regression_detected: bool,
    volume_status: Optional[str],
) -> List[str]:
    """Generate 3-5 deterministic, management intelligence observations (no AI)."""
    obs: List[str] = []
    label = metric_def.label

    if len(points) == 0:
        return ["No workforce data is available for the selected filters."]

    if len(points) == 1:
        single = points[0]
        obs.append(f"The dataset contains only one month ({single.period_display}); more history is required to determine a trend.")
        if single.formatted_value:
            obs.append(f"{label} for {single.period_display} was {single.formatted_value}.")
        if single.denominator is not None:
            ex_txt = f" ({single.excluded_data_quality} excluded for data quality)" if single.excluded_data_quality else ""
            obs.append(f"Evaluated across {single.denominator} evaluable units{ex_txt} ({single.volume_status or 'Low'} volume).")
        return obs

    latest = points[-1]
    curr_fmt = latest.formatted_value

    # 1. MoM change statement
    if mom_change is not None and previous_value is not None:
        prev_fmt = format_metric_value(previous_value, metric_def.format)
        if metric_def.format == "percentage":
            direction_word = "increased" if mom_change > 0 else "decreased"
            abs_pp = abs(mom_change)
            obs.append(f"{label} {direction_word} by {abs_pp:.1f} percentage points in {latest.period_display} (from {prev_fmt} to {curr_fmt}).")
        elif metric_def.format == "days":
            direction_word = "increased" if mom_change > 0 else "decreased"
            abs_days = abs(mom_change)
            obs.append(f"{label} {direction_word} by {abs_days:.1f} days in {latest.period_display} (from {prev_fmt} to {curr_fmt}).")
        elif metric_def.format in ("duration", "time"):
            direction_word = "increased" if mom_change > 0 else "decreased"
            abs_mins = abs(mom_change)
            obs.append(f"{label} moved by {abs_mins:.0f} minutes in {latest.period_display} (current: {curr_fmt}).")
        else:
            obs.append(f"{label} changed from {prev_fmt} to {curr_fmt} in {latest.period_display}.")

    # 2. Change since first available month
    if len(points) >= 3 and change_since_first is not None and first_value is not None:
        first_p = points[0]
        first_fmt = format_metric_value(first_value, metric_def.format)
        if metric_def.format == "percentage":
            net_word = "up" if change_since_first > 0 else "down"
            obs.append(f"Net change since {first_p.period_display} is {net_word} {abs(change_since_first):.1f} percentage points (baseline: {first_fmt}).")
        elif metric_def.format == "days":
            net_word = "up" if change_since_first > 0 else "down"
            obs.append(f"Turnaround is {net_word} {abs(change_since_first):.1f} days compared to {first_p.period_display} ({first_fmt}).")

    # 3. Streak or Direction Statement
    if streak_months >= 2 and streak_direction:
        dir_word = streak_direction.lower()
        obs.append(f"{label} has been {dir_word} for {streak_months} consecutive months.")
    elif trend_direction in ("IMPROVING", "DETERIORATING"):
        obs.append(f"Recent short-term trajectory indicates a {trend_direction.lower()} trend.")
    elif trend_direction == "STABLE":
        obs.append(f"{label} has remained stable over the recent 3-month window within the materiality threshold.")

    # 4. Regression Warning
    if regression_detected:
        obs.append("Performance regression detected: prior gains were reversed by recent deterioration.")

    # 5. Volume Context
    if latest.volume_status == "LOW" and latest.denominator is not None:
        obs.append(f"{latest.period_display} {label} is based on only {latest.denominator} evaluable observation{'s' if latest.denominator != 1 else ''} (Low volume).")

    # Keep between 3 and 5 observations
    return obs[:5]


# ── Primary Engine Function ─────────────────────────────────────────────

def calculate_time_series_trends(
    evaluated_df: pd.DataFrame,
    evaluated_requests: Optional[List[Dict[str, Any]]] = None,
    employee_day_facts: Optional[pd.DataFrame] = None,
    metric_id: str = "attendance_exception_rate",
    analysis_as_of_date: Optional[Union[date, datetime]] = None,
) -> Dict[str, Any]:
    """
    Main analytical engine entrypoint for Workforce Trends.
    Takes normalized, policy-evaluated datasets and generates a complete,
    deterministic time-series response.
    """
    if metric_id not in TREND_METRICS:
        raise ValueError(f"Unknown trend metric '{metric_id}'. Must be one of {list(TREND_METRICS.keys())}")

    metric_def = TREND_METRICS[metric_id]

    if metric_def.category == "Attendance" and employee_day_facts is None:
        employee_day_facts = build_employee_day_facts(evaluated_df)

    # 1. Monthly Aggregations
    if metric_def.category == "Compliance":
        raw_points = calculate_monthly_compliance(evaluated_df, evaluated_requests, metric_id)
    elif metric_def.category == "Attendance":
        raw_points = calculate_monthly_attendance(employee_day_facts, metric_id)
    elif metric_def.category == "Approval":
        raw_points = calculate_monthly_approvals(evaluated_df, metric_id, analysis_as_of_date)
    elif metric_def.category == "Working Time":
        raw_points = calculate_monthly_working_time(evaluated_df, metric_id)
    else:
        raw_points = []

    # 2. Attach MoM comparisons
    points = attach_mom_comparisons(raw_points, metric_def)

    # 3. Overall Time Series Summary
    valid_points = [p for p in points if p.value is not None]

    current_val: Optional[float] = valid_points[-1].value if valid_points else None
    current_fmt: Optional[str] = valid_points[-1].formatted_value if valid_points else None
    current_period: Optional[str] = valid_points[-1].period if valid_points else None
    current_period_display: Optional[str] = valid_points[-1].period_display if valid_points else None

    previous_val: Optional[float] = valid_points[-2].value if len(valid_points) >= 2 else None
    previous_fmt: Optional[str] = valid_points[-2].formatted_value if len(valid_points) >= 2 else None

    mom_change: Optional[float] = None
    mom_change_pp: Optional[float] = None
    if current_val is not None and previous_val is not None:
        mom_change = round(current_val - previous_val, 2)
        if metric_def.format == "percentage":
            mom_change_pp = mom_change

    first_val: Optional[float] = valid_points[0].value if valid_points else None
    first_fmt: Optional[str] = valid_points[0].formatted_value if valid_points else None
    change_since_first: Optional[float] = None
    change_since_first_pp: Optional[float] = None
    if current_val is not None and first_val is not None:
        change_since_first = round(current_val - first_val, 2)
        if metric_def.format == "percentage":
            change_since_first_pp = change_since_first

    # 4. Trend Direction, Streak, Regression, Volume
    direction = calculate_trend_direction(points, metric_def)
    streak_dir, streak_months = calculate_streak(points, metric_def)
    regression_detected = detect_regression(points, metric_def)
    vol_status = valid_points[-1].volume_status if valid_points else None

    # 5. Deterministic Observations
    observations = generate_trend_observations(
        points=points,
        metric_def=metric_def,
        current_value=current_val,
        previous_value=previous_val,
        mom_change=mom_change,
        first_value=first_val,
        change_since_first=change_since_first,
        trend_direction=direction,
        streak_direction=streak_dir,
        streak_months=streak_months,
        regression_detected=regression_detected,
        volume_status=vol_status,
    )

    # 6. Overall Date Range Display
    if len(points) > 0:
        first_dt = datetime.strptime(points[0].period, "%Y-%m-01")
        last_dt = datetime.strptime(points[-1].period, "%Y-%m-01")
        if first_dt.year == last_dt.year and first_dt.month == last_dt.month:
            date_range_display = first_dt.strftime("%B %Y")
        else:
            date_range_display = f"{first_dt.strftime('%B')}–{last_dt.strftime('%B %Y')}"
    else:
        date_range_display = "No data"

    return {
        "metric": metric_def.to_dict(),
        "time_series": [p.to_dict() for p in points],
        "current_period": current_period,
        "current_period_display": current_period_display,
        "current_value": current_val,
        "current_value_formatted": current_fmt,
        "previous_value": previous_val,
        "previous_value_formatted": previous_fmt,
        "mom_change": mom_change,
        "mom_change_pp": mom_change_pp,
        "first_available_value": first_val,
        "first_available_value_formatted": first_fmt,
        "change_since_first": change_since_first,
        "change_since_first_pp": change_since_first_pp,
        "trend_direction": direction,
        "streak_direction": streak_dir,
        "streak_months": streak_months,
        "regression_detected": regression_detected,
        "volume_status": vol_status,
        "observations": observations,
        "date_range_display": date_range_display,
        "policy_effective_date": POLICY_EFFECTIVE_DATE_STR,
    }
