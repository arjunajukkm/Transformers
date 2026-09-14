"""
patterns.py
───────────
Workforce Pattern Intelligence Engine.

Identifies recurring, evidence-based behavioral and process patterns across
attendance, leave, remote work (WFH), approvals, calendar adjacencies, and sequences.

Guiding Principles:
1. Deterministic & Explainable: No ML, black-box scores, or disciplinary labels.
2. Governed Data Only: Strictly evaluates analytical rows (include_in_analysis == True)
   and governed employee-day facts.
3. Strict Support Gate: Minimum 3 supporting events (MIN_PATTERN_EVENTS = 3).
4. Neutral Terminology: Focuses on process and recurrence ("Recurring pattern detected",
   "High recurrence", "Requires review", "Team-level concentration").
5. Full Audit Traceability: Preserves source record IDs, dates, and file origins.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union
import numpy as np
import pandas as pd

from workforce_intelligence.metrics import build_employee_day_facts
from workforce_intelligence.policy import evaluate_policy
from workforce_intelligence.requests import LeaveRequest, build_leave_requests


# ── CONSTANTS & CONFIGURATION ──────────────────────────────────────────────────
MIN_PATTERN_EVENTS = 3
DEFAULT_LONG_APPROVAL_DAYS = 5
MONTH_BOUNDARY_DAYS = 3  # First / Last 3 calendar days of month


class PatternCategory(str, Enum):
    ATTENDANCE = "Attendance"
    LEAVE = "Leave"
    WFH = "WFH"
    APPROVAL = "Approval"
    CALENDAR = "Calendar"
    SEQUENCE = "Sequence"
    PROCESS = "Process"


class PatternSeverity(str, Enum):
    INFO = "INFO"
    ATTENTION = "ATTENTION"
    PRIORITY = "PRIORITY"


class PatternStrength(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class PatternPersistence(str, Enum):
    SINGLE_PERIOD = "SINGLE_PERIOD"
    MULTI_MONTH = "MULTI_MONTH"
    PERSISTENT = "PERSISTENT"


class PatternStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECENT = "RECENT"
    HISTORICAL = "HISTORICAL"


class EntityType(str, Enum):
    ORGANIZATION = "ORGANIZATION"
    BUSINESS_UNIT = "BUSINESS_UNIT"
    DEPARTMENT = "DEPARTMENT"
    SUB_DEPARTMENT = "SUB_DEPARTMENT"
    REPORTING_MANAGER = "REPORTING_MANAGER"
    EMPLOYEE = "EMPLOYEE"


# ── PATTERN CATALOGUE ──────────────────────────────────────────────────────────
PATTERN_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    # 1. Attendance
    "WEEKDAY_EXCEPTION_CONCENTRATION": {
        "pattern_type": "WEEKDAY_EXCEPTION_CONCENTRATION",
        "label": "Weekday Exception Concentration",
        "category": PatternCategory.ATTENDANCE.value,
        "description": "Attendance exceptions repeatedly concentrate on a specific weekday (e.g. Mondays or Fridays).",
        "default_min_support": 3,
        "severity": PatternSeverity.ATTENTION.value,
        "entity_levels": [EntityType.EMPLOYEE.value, EntityType.REPORTING_MANAGER.value, EntityType.DEPARTMENT.value],
    },
    "RECURRING_MISSING_SWIPE": {
        "pattern_type": "RECURRING_MISSING_SWIPE",
        "label": "Recurring Missing Swipes",
        "category": PatternCategory.ATTENDANCE.value,
        "description": "Repeated missing swipe attendance events observed across multiple dates.",
        "default_min_support": 3,
        "severity": PatternSeverity.ATTENTION.value,
        "entity_levels": [EntityType.EMPLOYEE.value],
    },
    "RECURRING_ABSENCE": {
        "pattern_type": "RECURRING_ABSENCE",
        "label": "Recurring Absence",
        "category": PatternCategory.ATTENDANCE.value,
        "description": "Repeated absence events recorded without an approved leave request.",
        "default_min_support": 3,
        "severity": PatternSeverity.ATTENTION.value,
        "entity_levels": [EntityType.EMPLOYEE.value],
    },
    "RECURRING_REGULARISATION": {
        "pattern_type": "RECURRING_REGULARISATION",
        "label": "Recurring Regularisation",
        "category": PatternCategory.ATTENDANCE.value,
        "description": "Repeated attendance regularisation requests observed across dates.",
        "default_min_support": 3,
        "severity": PatternSeverity.INFO.value,
        "entity_levels": [EntityType.EMPLOYEE.value, EntityType.REPORTING_MANAGER.value],
    },

    # 2. Leave
    "RECURRING_LATE_LEAVE_APPLICATION": {
        "pattern_type": "RECURRING_LATE_LEAVE_APPLICATION",
        "label": "Recurring Late Leave Application",
        "category": PatternCategory.LEAVE.value,
        "description": "Leave applications repeatedly submitted after the configured notice or submission window.",
        "default_min_support": 3,
        "severity": PatternSeverity.ATTENTION.value,
        "entity_levels": [EntityType.EMPLOYEE.value, EntityType.REPORTING_MANAGER.value],
    },
    "RECURRING_MISSING_APPLICATION": {
        "pattern_type": "RECURRING_MISSING_APPLICATION",
        "label": "Missing Application Timestamp",
        "category": PatternCategory.LEAVE.value,
        "description": "Recurring leave or WFH records lacking a documented submission timestamp in the source.",
        "default_min_support": 3,
        "severity": PatternSeverity.PRIORITY.value,
        "entity_levels": [EntityType.EMPLOYEE.value, EntityType.ORGANIZATION.value],
    },

    # 3. WFH
    "RECURRING_LATE_WFH_APPLICATION": {
        "pattern_type": "RECURRING_LATE_WFH_APPLICATION",
        "label": "Recurring Late WFH Application",
        "category": PatternCategory.WFH.value,
        "description": "Work From Home applications repeatedly submitted more than 3 calendar days after the availed date.",
        "default_min_support": 3,
        "severity": PatternSeverity.ATTENTION.value,
        "entity_levels": [EntityType.EMPLOYEE.value, EntityType.REPORTING_MANAGER.value],
    },

    # 4. Approval
    "RECURRING_LONG_APPROVAL_TURNAROUND": {
        "pattern_type": "RECURRING_LONG_APPROVAL_TURNAROUND",
        "label": "Long Approval Turnaround",
        "category": PatternCategory.APPROVAL.value,
        "description": "Manager approval turnaround repeatedly exceeds 5 calendar days from submission.",
        "default_min_support": 3,
        "severity": PatternSeverity.ATTENTION.value,
        "entity_levels": [EntityType.REPORTING_MANAGER.value],
    },

    # 5. Calendar
    "MONDAY_FRIDAY_CONCENTRATION": {
        "pattern_type": "MONDAY_FRIDAY_CONCENTRATION",
        "label": "Monday & Friday Concentration",
        "category": PatternCategory.CALENDAR.value,
        "description": "Leave, WFH, or attendance exceptions concentrate heavily around Mondays and Fridays.",
        "default_min_support": 3,
        "severity": PatternSeverity.INFO.value,
        "entity_levels": [EntityType.EMPLOYEE.value, EntityType.DEPARTMENT.value],
    },
    "WEEKEND_ADJACENT_LEAVE": {
        "pattern_type": "WEEKEND_ADJACENT_LEAVE",
        "label": "Weekend-Adjacent Leave",
        "category": PatternCategory.CALENDAR.value,
        "description": "Leave events repeatedly taken on days immediately adjacent to weekends (Fridays or Mondays).",
        "default_min_support": 3,
        "severity": PatternSeverity.INFO.value,
        "entity_levels": [EntityType.EMPLOYEE.value],
    },
    "HOLIDAY_ADJACENT_LEAVE": {
        "pattern_type": "HOLIDAY_ADJACENT_LEAVE",
        "label": "Holiday-Adjacent Leave",
        "category": PatternCategory.CALENDAR.value,
        "description": "Leave events repeatedly scheduled immediately before or after company holidays.",
        "default_min_support": 3,
        "severity": PatternSeverity.INFO.value,
        "entity_levels": [EntityType.EMPLOYEE.value],
    },
    "LONG_WEEKEND_ADJACENCY": {
        "pattern_type": "LONG_WEEKEND_ADJACENCY",
        "label": "Long Weekend Adjacency",
        "category": PatternCategory.CALENDAR.value,
        "description": "Leave or remote work repeatedly combining with weekends/holidays to form extended breaks.",
        "default_min_support": 3,
        "severity": PatternSeverity.INFO.value,
        "entity_levels": [EntityType.EMPLOYEE.value],
    },

    # 6. Sequence
    "LEAVE_TO_WFH_SEQUENCE": {
        "pattern_type": "LEAVE_TO_WFH_SEQUENCE",
        "label": "Leave → WFH Transition",
        "category": PatternCategory.SEQUENCE.value,
        "description": "Recurring pattern of Leave immediately followed by Work From Home within 1 calendar day.",
        "default_min_support": 3,
        "severity": PatternSeverity.INFO.value,
        "entity_levels": [EntityType.EMPLOYEE.value],
    },
    "WFH_TO_LEAVE_SEQUENCE": {
        "pattern_type": "WFH_TO_LEAVE_SEQUENCE",
        "label": "WFH → Leave Transition",
        "category": PatternCategory.SEQUENCE.value,
        "description": "Recurring pattern of Work From Home immediately followed by Leave within 1 calendar day.",
        "default_min_support": 3,
        "severity": PatternSeverity.INFO.value,
        "entity_levels": [EntityType.EMPLOYEE.value],
    },
    "EXTENDED_REMOTE_LEAVE_SEQUENCE": {
        "pattern_type": "EXTENDED_REMOTE_LEAVE_SEQUENCE",
        "label": "Extended Remote-Leave Sequence",
        "category": PatternCategory.SEQUENCE.value,
        "description": "Recurring combination of Friday WFH and Monday Leave (or vice-versa) bridging across the weekend.",
        "default_min_support": 3,
        "severity": PatternSeverity.INFO.value,
        "entity_levels": [EntityType.EMPLOYEE.value],
    },

    # 7. Process
    "REPEAT_PROCESS_NON_COMPLIANCE": {
        "pattern_type": "REPEAT_PROCESS_NON_COMPLIANCE",
        "label": "Repeat Process Non-Compliance",
        "category": PatternCategory.PROCESS.value,
        "description": "Multiple process timing non-compliances (late leave, insufficient notice, late WFH, missing date) across dates.",
        "default_min_support": 3,
        "severity": PatternSeverity.PRIORITY.value,
        "entity_levels": [EntityType.EMPLOYEE.value],
    },
    "MANAGER_CONCENTRATION": {
        "pattern_type": "MANAGER_CONCENTRATION",
        "label": "Team Concentration Under Manager",
        "category": PatternCategory.PROCESS.value,
        "description": "Team attendance exceptions or late submissions show notable concentration under a reporting manager.",
        "default_min_support": 3,
        "severity": PatternSeverity.ATTENTION.value,
        "entity_levels": [EntityType.REPORTING_MANAGER.value],
    },
    "GROUP_CONCENTRATION": {
        "pattern_type": "GROUP_CONCENTRATION",
        "label": "Department Exception Concentration",
        "category": PatternCategory.PROCESS.value,
        "description": "Department or business unit exception rate is materially higher than the organization baseline.",
        "default_min_support": 3,
        "severity": PatternSeverity.ATTENTION.value,
        "entity_levels": [EntityType.DEPARTMENT.value, EntityType.BUSINESS_UNIT.value],
    },
    "MONTH_END_CONCENTRATION": {
        "pattern_type": "MONTH_END_CONCENTRATION",
        "label": "Month-End Concentration",
        "category": PatternCategory.PROCESS.value,
        "description": "Attendance exceptions or regularisations cluster heavily in the final 3 calendar days of the month.",
        "default_min_support": 3,
        "severity": PatternSeverity.INFO.value,
        "entity_levels": [EntityType.EMPLOYEE.value, EntityType.DEPARTMENT.value],
    },
    "MONTH_START_CONCENTRATION": {
        "pattern_type": "MONTH_START_CONCENTRATION",
        "label": "Month-Start Concentration",
        "category": PatternCategory.PROCESS.value,
        "description": "Attendance exceptions or regularisations cluster heavily in the first 3 calendar days of the month.",
        "default_min_support": 3,
        "severity": PatternSeverity.INFO.value,
        "entity_levels": [EntityType.EMPLOYEE.value, EntityType.DEPARTMENT.value],
    },
}


# ── DATA MODELS ────────────────────────────────────────────────────────────────
@dataclass
class PatternEvidenceItem:
    date: Optional[str] = None
    employee_number: Optional[str] = None
    employee_name: Optional[str] = None
    reporting_manager: Optional[str] = None
    event_type: Optional[str] = None
    status: Optional[str] = None
    leave_name: Optional[str] = None
    quantity: Optional[float] = None
    application_lag_days: Optional[int] = None
    approval_turnaround_days: Optional[float] = None
    details: Optional[str] = None
    source_file_name: Optional[str] = None
    source_row_number: Optional[int] = None
    record_id: Optional[str] = None
    request_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PatternResult:
    pattern_id: str
    pattern_type: str
    pattern_category: str
    pattern_title: str

    entity_type: str
    entity_id: str
    entity_name: str

    severity: str
    strength: str
    persistence: str
    status: str

    event_count: int
    opportunity_count: Optional[int]
    rate: Optional[float]
    reference_rate: Optional[float] = None

    first_observed_date: Optional[str] = None
    last_observed_date: Optional[str] = None

    months_active: List[str] = field(default_factory=list)
    distinct_months: int = 1
    recurrence_count: int = 0

    pattern_score: float = 0.0
    score_components: Dict[str, float] = field(default_factory=dict)

    description: str = ""
    why_detected: str = ""
    summary_evidence: str = ""

    evidence_record_ids: List[str] = field(default_factory=list)
    evidence_source_rows: List[int] = field(default_factory=list)
    evidence_items: List[PatternEvidenceItem] = field(default_factory=list)

    latest_period: Optional[str] = None
    data_quality_excluded_count: int = 0

    def to_dict(self, include_full_evidence: bool = True) -> Dict[str, Any]:
        d = {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "pattern_category": self.pattern_category,
            "pattern_title": self.pattern_title,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "severity": self.severity,
            "strength": self.strength,
            "persistence": self.persistence,
            "status": self.status,
            "event_count": self.event_count,
            "opportunity_count": self.opportunity_count,
            "rate": self.rate,
            "reference_rate": self.reference_rate,
            "first_observed_date": self.first_observed_date,
            "last_observed_date": self.last_observed_date,
            "months_active": self.months_active,
            "distinct_months": self.distinct_months,
            "recurrence_count": self.recurrence_count,
            "pattern_score": self.pattern_score,
            "score_components": self.score_components,
            "description": self.description,
            "why_detected": self.why_detected,
            "summary_evidence": self.summary_evidence,
            "evidence_count": len(self.evidence_items),
            "latest_period": self.latest_period,
            "data_quality_excluded_count": self.data_quality_excluded_count,
        }
        if include_full_evidence:
            d["evidence_record_ids"] = self.evidence_record_ids
            d["evidence_source_rows"] = self.evidence_source_rows
            d["evidence_items"] = [item.to_dict() for item in self.evidence_items]
        else:
            # First 5 items in summary view
            d["evidence_preview"] = [item.to_dict() for item in self.evidence_items[:5]]
        return d


@dataclass
class PatternSummary:
    total_patterns: int = 0
    active_patterns: int = 0
    high_strength_patterns: int = 0
    employees_with_patterns: int = 0
    managers_with_patterns: int = 0
    category_counts: Dict[str, int] = field(default_factory=dict)
    severity_counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── SCORING & CLASSIFICATION HELPERS ──────────────────────────────────────────
def _calculate_pattern_score_and_badges(
    event_count: int,
    opportunity_count: Optional[int],
    rate: Optional[float],
    distinct_months: int,
    days_since_last: Optional[int],
    concentration_ratio: Optional[float] = None,
) -> Tuple[float, Dict[str, float], str, str, str]:
    """
    Compute explainable pattern recurrence score (0-100), strength, persistence, and status.
    Score Weights:
    - Frequency: 35% (normalized event count, scaled to 10 events)
    - Persistence: 30% (1 mo = 33, 2 mo = 66, 3+ mo = 100)
    - Concentration / Rate: 20% (rate or concentration share)
    - Recency: 15% (<=30d: 100, 31-90d: 60, >90d: 20)
    """
    # 1. Frequency (35%)
    freq_score = min(100.0, (event_count / 10.0) * 100.0)

    # 2. Persistence (30%)
    if distinct_months >= 3:
        pers_score = 100.0
        pers_label = PatternPersistence.PERSISTENT.value
    elif distinct_months == 2:
        pers_score = 66.0
        pers_label = PatternPersistence.MULTI_MONTH.value
    else:
        pers_score = 33.0
        pers_label = PatternPersistence.SINGLE_PERIOD.value

    # 3. Concentration / Rate (20%)
    if concentration_ratio is not None:
        conc_score = min(100.0, max(0.0, concentration_ratio * 100.0))
    elif rate is not None:
        conc_score = min(100.0, max(0.0, rate))
    else:
        conc_score = min(100.0, (event_count / 5.0) * 100.0)

    # 4. Recency (15%)
    if days_since_last is None or days_since_last <= 30:
        rec_score = 100.0
        status_label = PatternStatus.ACTIVE.value
    elif days_since_last <= 90:
        rec_score = 60.0
        status_label = PatternStatus.RECENT.value
    else:
        rec_score = 20.0
        status_label = PatternStatus.HISTORICAL.value

    total_score = round(
        (0.35 * freq_score) + (0.30 * pers_score) + (0.20 * conc_score) + (0.15 * rec_score),
        1
    )

    # Strength classification
    if total_score >= 70.0 and (event_count >= 5 or distinct_months >= 3):
        strength_label = PatternStrength.HIGH.value
    elif total_score >= 40.0 and event_count >= 3:
        strength_label = PatternStrength.MODERATE.value
    else:
        strength_label = PatternStrength.LOW.value

    score_components = {
        "frequency": round(freq_score, 1),
        "persistence": round(pers_score, 1),
        "concentration": round(conc_score, 1),
        "recency": round(rec_score, 1),
    }

    return total_score, score_components, strength_label, pers_label, status_label


def _extract_date_metadata(dates: Sequence[Union[date, str, datetime]]) -> Tuple[Optional[str], Optional[str], List[str], int]:
    """Extract first date, last date, distinct month labels (e.g. 'Sep 2026'), and count."""
    clean_dates: List[date] = []
    for d in dates:
        if d is None or pd.isna(d):
            continue
        if isinstance(d, datetime):
            clean_dates.append(d.date())
        elif isinstance(d, date):
            clean_dates.append(d)
        else:
            try:
                dt = pd.to_datetime(d).date()
                clean_dates.append(dt)
            except Exception:
                pass

    if not clean_dates:
        return None, None, [], 0

    sorted_dates = sorted(clean_dates)
    first_d = sorted_dates[0].strftime("%Y-%m-%d")
    last_d = sorted_dates[-1].strftime("%Y-%m-%d")

    month_keys = sorted(list({d.strftime("%b %Y") for d in sorted_dates}), key=lambda m: pd.to_datetime(m))
    return first_d, last_d, month_keys, len(month_keys)


# ── PATTERN CONTEXT ────────────────────────────────────────────────────────────
class PatternContext:
    """
    Centralized analytical context for pattern detection.
    Pre-indexes governed facts, requests, dates, and organizational baselines
    to ensure detectors execute efficiently without redundant processing.
    """

    def __init__(
        self,
        evaluated_df: pd.DataFrame,
        evaluated_requests: Optional[List[Dict[str, Any]]] = None,
        employee_day_facts: Optional[pd.DataFrame] = None,
        min_events: int = MIN_PATTERN_EVENTS,
        long_approval_days: int = DEFAULT_LONG_APPROVAL_DAYS,
    ):
        self.min_events = min_events
        self.long_approval_days = long_approval_days

        # 1. Governed Dataframe (include_in_analysis == True)
        if "include_in_analysis" in evaluated_df.columns:
            self.df = evaluated_df[evaluated_df["include_in_analysis"] == True].copy()
        else:
            self.df = evaluated_df.copy()

        if "approval_turnaround_days" not in self.df.columns or self.df["approval_turnaround_days"].isna().all():
            if "Approved On" in self.df.columns and "Applied On" in self.df.columns:
                def calc_turnaround(row):
                    app_on = row.get("Applied On")
                    apr_on = row.get("Approved On")
                    if pd.notna(app_on) and pd.notna(apr_on):
                        try:
                            return (pd.to_datetime(apr_on).floor("D") - pd.to_datetime(app_on).floor("D")).days
                        except Exception:
                            return None
                    return None

                self.df["approval_turnaround_days"] = self.df.apply(calc_turnaround, axis=1).astype("Int64")

        # 2. Governed Employee-Day Facts
        if employee_day_facts is not None:
            self.facts = employee_day_facts.copy()
        else:
            self.facts = build_employee_day_facts(self.df)

        # 3. Governed Leave Requests
        if evaluated_requests is not None:
            self.requests = list(evaluated_requests)
            self.req_df = pd.DataFrame(evaluated_requests)
        else:
            req_objs, _ = build_leave_requests(self.df)
            _, eval_reqs = evaluate_policy(self.df, leave_requests=req_objs)
            self.requests = eval_reqs
            self.req_df = pd.DataFrame(eval_reqs) if eval_reqs else pd.DataFrame()

        # 4. Max dataset date for recency calculation
        self.dataset_max_date: Optional[date] = None
        if "Date" in self.df.columns and not self.df["Date"].dropna().empty:
            self.dataset_max_date = pd.to_datetime(self.df["Date"]).dropna().max().date()
        elif not self.facts.empty and "Date" in self.facts.columns and not self.facts["Date"].dropna().empty:
            self.dataset_max_date = pd.to_datetime(self.facts["Date"]).dropna().max().date()
        else:
            self.dataset_max_date = date.today()

        # 5. Organization Baselines
        self.org_evaluable_days = int(self.facts["is_metric_evaluable"].sum()) if not self.facts.empty else 0
        self.org_exception_days = int((self.facts["is_attendance_exception"] == True).sum()) if not self.facts.empty else 0
        self.org_exception_rate = (
            round((self.org_exception_days / self.org_evaluable_days) * 100.0, 2)
            if self.org_evaluable_days > 0
            else 0.0
        )

        self.org_missing_swipes = int((self.facts["has_missing_swipe"] == True).sum()) if not self.facts.empty else 0
        self.org_missing_swipe_rate = (
            round((self.org_missing_swipes / self.org_evaluable_days) * 100.0, 2)
            if self.org_evaluable_days > 0
            else 0.0
        )


# ── MODULAR DETECTORS ──────────────────────────────────────────────────────────

def detect_weekday_exception_patterns(ctx: PatternContext) -> List[PatternResult]:
    """
    Detect whether attendance exceptions repeatedly concentrate on a particular weekday.
    Rules:
    - >= 3 exception days on the same weekday
    - That weekday represents >= 40% of entity's total exception days
    - Exposes weekday exception rate (weekday exceptions / eligible days on that weekday).
    """
    results: List[PatternResult] = []
    if ctx.facts.empty:
        return results

    eval_facts = ctx.facts[ctx.facts["is_metric_evaluable"] == True].copy()
    if eval_facts.empty or "Date" not in eval_facts.columns:
        return results

    eval_facts["weekday_name"] = pd.to_datetime(eval_facts["Date"]).dt.day_name()

    # Detect at Employee level
    for (emp_num, emp_name), group in eval_facts.groupby(["Employee Number", "Employee Name"]):
        emp_num_str = str(emp_num)
        emp_name_str = str(emp_name) if pd.notna(emp_name) else emp_num_str
        total_exceptions = int((group["is_attendance_exception"] == True).sum())
        if total_exceptions < ctx.min_events:
            continue

        exception_rows = group[group["is_attendance_exception"] == True]

        for weekday, w_exc_rows in exception_rows.groupby("weekday_name"):
            w_exc_count = len(w_exc_rows)
            if w_exc_count < ctx.min_events:
                continue

            conc_ratio = w_exc_count / total_exceptions
            if conc_ratio < 0.40:
                continue

            # Calculate opportunity denominator on that weekday
            w_eligible_days = int((group["weekday_name"] == weekday).sum())
            weekday_rate = round((w_exc_count / w_eligible_days) * 100.0, 1) if w_eligible_days > 0 else 100.0

            dates = w_exc_rows["Date"].tolist()
            first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

            days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
            score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                event_count=w_exc_count,
                opportunity_count=w_eligible_days,
                rate=weekday_rate,
                distinct_months=dist_months,
                days_since_last=days_since,
                concentration_ratio=conc_ratio,
            )

            # Build evidence
            evidence_items = []
            for _, r in w_exc_rows.iterrows():
                dt_str = pd.to_datetime(r["Date"]).strftime("%Y-%m-%d") if pd.notna(r["Date"]) else ""
                evidence_items.append(
                    PatternEvidenceItem(
                        date=dt_str,
                        employee_number=emp_num_str,
                        employee_name=emp_name_str,
                        reporting_manager=str(r.get("Reporting Manager")) if pd.notna(r.get("Reporting Manager")) else None,
                        event_type="ATTENDANCE_EXCEPTION",
                        status=str(r.get("attendance_exception_types") or "Exception"),
                        details=f"{weekday} attendance exception ({r.get('attendance_exception_types') or 'Exception'})",
                    )
                )

            pattern_id = f"WEEKDAY_EXCEPTION_CONCENTRATION_EMP_{emp_num_str}_{weekday.upper()}"
            title = f"{weekday} Attendance Exceptions Recur Frequently"
            why = (
                f"Detected because {w_exc_count} of {total_exceptions} attendance exceptions ({conc_ratio*100:.1f}%) "
                f"occurred on {weekday}s across {dist_months} month(s), with a {weekday_rate:.1f}% exception rate on that weekday."
            )
            desc = f"Concentration of attendance exceptions on {weekday}s for {emp_name_str}."

            results.append(
                PatternResult(
                    pattern_id=pattern_id,
                    pattern_type="WEEKDAY_EXCEPTION_CONCENTRATION",
                    pattern_category=PatternCategory.ATTENDANCE.value,
                    pattern_title=title,
                    entity_type=EntityType.EMPLOYEE.value,
                    entity_id=emp_num_str,
                    entity_name=emp_name_str,
                    severity=PatternSeverity.ATTENTION.value,
                    strength=strength,
                    persistence=persistence,
                    status=status,
                    event_count=w_exc_count,
                    opportunity_count=w_eligible_days,
                    rate=weekday_rate,
                    first_observed_date=first_d,
                    last_observed_date=last_d,
                    months_active=months_active,
                    distinct_months=dist_months,
                    recurrence_count=w_exc_count,
                    pattern_score=score,
                    score_components=components,
                    description=desc,
                    why_detected=why,
                    summary_evidence=f"{w_exc_count} of {total_exceptions} exceptions occurred on {weekday} ({conc_ratio*100:.1f}% concentration)",
                    evidence_items=evidence_items,
                    latest_period=months_active[-1] if months_active else None,
                )
            )

    return results


def detect_attendance_recurrence_patterns(ctx: PatternContext) -> List[PatternResult]:
    """
    Detect recurring Missing Swipes, Recurring Absence, and Recurring Regularisation.
    """
    results: List[PatternResult] = []
    if ctx.facts.empty:
        return results

    eval_facts = ctx.facts[ctx.facts["is_metric_evaluable"] == True].copy()
    if eval_facts.empty:
        return results

    check_configs = [
        ("has_missing_swipe", "RECURRING_MISSING_SWIPE", "Recurring Missing Swipes", PatternCategory.ATTENDANCE, PatternSeverity.ATTENTION, "missing swipe"),
        ("has_absent", "RECURRING_ABSENCE", "Recurring Absence Events", PatternCategory.ATTENDANCE, PatternSeverity.ATTENTION, "absence"),
        ("has_regularization", "RECURRING_REGULARISATION", "Recurring Attendance Regularisation", PatternCategory.ATTENDANCE, PatternSeverity.INFO, "attendance regularisation"),
    ]

    for col_flag, p_type, title_prefix, cat, sev, term in check_configs:
        for (emp_num, emp_name), group in eval_facts.groupby(["Employee Number", "Employee Name"]):
            emp_num_str = str(emp_num)
            emp_name_str = str(emp_name) if pd.notna(emp_name) else emp_num_str

            matched_rows = group[group[col_flag] == True]
            count = len(matched_rows)
            if count < ctx.min_events:
                continue

            total_opp = len(group)
            rate = round((count / total_opp) * 100.0, 1) if total_opp > 0 else 100.0

            dates = matched_rows["Date"].tolist()
            first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

            days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
            score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                event_count=count,
                opportunity_count=total_opp,
                rate=rate,
                distinct_months=dist_months,
                days_since_last=days_since,
            )

            evidence_items = []
            for _, r in matched_rows.iterrows():
                dt_str = pd.to_datetime(r["Date"]).strftime("%Y-%m-%d") if pd.notna(r["Date"]) else ""
                evidence_items.append(
                    PatternEvidenceItem(
                        date=dt_str,
                        employee_number=emp_num_str,
                        employee_name=emp_name_str,
                        reporting_manager=str(r.get("Reporting Manager")) if pd.notna(r.get("Reporting Manager")) else None,
                        event_type=p_type,
                        status=str(r.get("attendance_exception_types") or term.title()),
                        details=f"{term.capitalize()} observed on {dt_str}",
                    )
                )

            pattern_id = f"{p_type}_EMP_{emp_num_str}"
            why = (
                f"Detected because {count} {term} days were observed across {dist_months} month(s), "
                f"representing {rate:.1f}% of {total_opp} evaluable attendance days."
            )
            desc = f"Recurring {term} events for {emp_name_str}."

            results.append(
                PatternResult(
                    pattern_id=pattern_id,
                    pattern_type=p_type,
                    pattern_category=cat.value,
                    pattern_title=f"{title_prefix} Observed",
                    entity_type=EntityType.EMPLOYEE.value,
                    entity_id=emp_num_str,
                    entity_name=emp_name_str,
                    severity=sev.value,
                    strength=strength,
                    persistence=persistence,
                    status=status,
                    event_count=count,
                    opportunity_count=total_opp,
                    rate=rate,
                    first_observed_date=first_d,
                    last_observed_date=last_d,
                    months_active=months_active,
                    distinct_months=dist_months,
                    recurrence_count=count,
                    pattern_score=score,
                    score_components=components,
                    description=desc,
                    why_detected=why,
                    summary_evidence=f"{count} {term} events in {total_opp} evaluable days ({rate:.1f}% rate)",
                    evidence_items=evidence_items,
                    latest_period=months_active[-1] if months_active else None,
                )
            )

    return results


def detect_leave_wfh_timing_patterns(ctx: PatternContext) -> List[PatternResult]:
    """
    Detect recurring late leave applications, late WFH applications, and missing application dates.
    """
    results: List[PatternResult] = []

    # 1. Leave Timing Patterns (Evaluated Reconstructed Requests)
    if not ctx.req_df.empty:
        # Group by employee
        for emp_num, req_group in ctx.req_df.groupby("employee_number"):
            emp_num_str = str(emp_num)
            first_r = req_group.iloc[0]
            emp_name_str = str(first_r.get("employee_name") or emp_num_str)

            # A. Late Leave Applications
            late_reqs = req_group[
                (req_group["compliance_status"].isin(["NON_COMPLIANT", "PRE_POLICY_BENCHMARK_FAIL"]))
                & (req_group["non_compliance_reason"].isin(["LATE_APPLICATION", "INSUFFICIENT_ADVANCE_NOTICE"]))
            ]
            late_count = len(late_reqs)
            if late_count >= ctx.min_events:
                total_reqs = len(req_group)
                rate = round((late_count / total_reqs) * 100.0, 1) if total_reqs > 0 else 100.0

                dates = late_reqs["request_start_date"].dropna().tolist()
                first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

                days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
                score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                    event_count=late_count,
                    opportunity_count=total_reqs,
                    rate=rate,
                    distinct_months=dist_months,
                    days_since_last=days_since,
                )

                evidence_items = []
                for _, r in late_reqs.iterrows():
                    st_date_str = str(r.get("request_start_date") or "")
                    app_on_str = str(r.get("applied_on") or "")
                    evidence_items.append(
                        PatternEvidenceItem(
                            date=st_date_str,
                            employee_number=emp_num_str,
                            employee_name=emp_name_str,
                            reporting_manager=str(r.get("reporting_manager")) if pd.notna(r.get("reporting_manager")) else None,
                            event_type="LEAVE",
                            leave_name=str(r.get("leave_name_normalized") or "Leave"),
                            quantity=float(r.get("request_total_quantity") or 1.0),
                            application_lag_days=int(r["request_application_lag_days"]) if pd.notna(r.get("request_application_lag_days")) else None,
                            details=f"Applied on {app_on_str} (lag: {r.get('request_application_lag_days')}d, rule: {r.get('policy_rule_code')})",
                            request_id=str(r.get("request_id") or ""),
                        )
                    )

                why = (
                    f"Detected because {late_count} of {total_reqs} leave requests ({rate:.1f}%) "
                    f"were submitted outside the policy notice/submission window across {dist_months} month(s)."
                )

                results.append(
                    PatternResult(
                        pattern_id=f"RECURRING_LATE_LEAVE_APPLICATION_EMP_{emp_num_str}",
                        pattern_type="RECURRING_LATE_LEAVE_APPLICATION",
                        pattern_category=PatternCategory.LEAVE.value,
                        pattern_title="Recurring Late Leave Applications",
                        entity_type=EntityType.EMPLOYEE.value,
                        entity_id=emp_num_str,
                        entity_name=emp_name_str,
                        severity=PatternSeverity.ATTENTION.value,
                        strength=strength,
                        persistence=persistence,
                        status=status,
                        event_count=late_count,
                        opportunity_count=total_reqs,
                        rate=rate,
                        first_observed_date=first_d,
                        last_observed_date=last_d,
                        months_active=months_active,
                        distinct_months=dist_months,
                        recurrence_count=late_count,
                        pattern_score=score,
                        score_components=components,
                        description=f"Repeated late leave submissions for {emp_name_str}.",
                        why_detected=why,
                        summary_evidence=f"{late_count} of {total_reqs} leave requests submitted late ({rate:.1f}%)",
                        evidence_items=evidence_items,
                        latest_period=months_active[-1] if months_active else None,
                    )
                )

            # B. Missing Application Date on Leave Requests
            missing_app_reqs = req_group[req_group["non_compliance_reason"] == "MISSING_APPLICATION_DATE"]
            missing_count = len(missing_app_reqs)
            if missing_count >= ctx.min_events:
                total_reqs = len(req_group)
                rate = round((missing_count / total_reqs) * 100.0, 1) if total_reqs > 0 else 100.0
                dates = missing_app_reqs["request_start_date"].dropna().tolist()
                first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

                days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
                score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                    event_count=missing_count,
                    opportunity_count=total_reqs,
                    rate=rate,
                    distinct_months=dist_months,
                    days_since_last=days_since,
                )

                evidence_items = []
                for _, r in missing_app_reqs.iterrows():
                    st_date_str = str(r.get("request_start_date") or "")
                    evidence_items.append(
                        PatternEvidenceItem(
                            date=st_date_str,
                            employee_number=emp_num_str,
                            employee_name=emp_name_str,
                            reporting_manager=str(r.get("reporting_manager")) if pd.notna(r.get("reporting_manager")) else None,
                            event_type="LEAVE",
                            leave_name=str(r.get("leave_name_normalized") or "Leave"),
                            quantity=float(r.get("request_total_quantity") or 1.0),
                            details="No application timestamp recorded in source",
                            request_id=str(r.get("request_id") or ""),
                        )
                    )

                results.append(
                    PatternResult(
                        pattern_id=f"RECURRING_MISSING_APPLICATION_EMP_{emp_num_str}",
                        pattern_type="RECURRING_MISSING_APPLICATION",
                        pattern_category=PatternCategory.LEAVE.value,
                        pattern_title="Recurring Missing Application Timestamps",
                        entity_type=EntityType.EMPLOYEE.value,
                        entity_id=emp_num_str,
                        entity_name=emp_name_str,
                        severity=PatternSeverity.PRIORITY.value,
                        strength=strength,
                        persistence=persistence,
                        status=status,
                        event_count=missing_count,
                        opportunity_count=total_reqs,
                        rate=rate,
                        first_observed_date=first_d,
                        last_observed_date=last_d,
                        months_active=months_active,
                        distinct_months=dist_months,
                        recurrence_count=missing_count,
                        pattern_score=score,
                        score_components=components,
                        description=f"Leave requests lacking application timestamp for {emp_name_str}.",
                        why_detected=f"Detected because {missing_count} leave requests lacked an application timestamp across {dist_months} month(s).",
                        summary_evidence=f"{missing_count} leave requests with missing application dates",
                        evidence_items=evidence_items,
                        latest_period=months_active[-1] if months_active else None,
                    )
                )

    # 2. WFH Application Timing Patterns (Evaluated WFH Rows)
    if not ctx.df.empty and "policy_event_type" in ctx.df.columns:
        wfh_df = ctx.df[ctx.df["policy_event_type"] == "WFH"].copy()
        if not wfh_df.empty:
            for (emp_num, emp_name), group in wfh_df.groupby(["Employee Number", "Employee Name"]):
                emp_num_str = str(emp_num)
                emp_name_str = str(emp_name) if pd.notna(emp_name) else emp_num_str

                late_wfh = group[
                    (group["compliance_status"].isin(["NON_COMPLIANT", "PRE_POLICY_BENCHMARK_FAIL"]))
                    & (group["non_compliance_reason"] == "LATE_APPLICATION")
                ]
                late_count = len(late_wfh)
                if late_count >= ctx.min_events:
                    total_wfh = len(group)
                    rate = round((late_count / total_wfh) * 100.0, 1) if total_wfh > 0 else 100.0

                    dates = late_wfh["Date"].dropna().tolist()
                    first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

                    days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
                    score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                        event_count=late_count,
                        opportunity_count=total_wfh,
                        rate=rate,
                        distinct_months=dist_months,
                        days_since_last=days_since,
                    )

                    evidence_items = []
                    for _, r in late_wfh.iterrows():
                        dt_str = pd.to_datetime(r["Date"]).strftime("%Y-%m-%d") if pd.notna(r["Date"]) else ""
                        evidence_items.append(
                            PatternEvidenceItem(
                                date=dt_str,
                                employee_number=emp_num_str,
                                employee_name=emp_name_str,
                                reporting_manager=str(r.get("Reporting Manager")) if pd.notna(r.get("Reporting Manager")) else None,
                                event_type="WFH",
                                status="Work From Home",
                                application_lag_days=int(r["application_lag_days"]) if pd.notna(r.get("application_lag_days")) else None,
                                details=f"Applied on {r.get('Applied On')} (lag: {r.get('application_lag_days')}d, allowed: 3d)",
                                source_file_name=str(r.get("source_file_name")) if pd.notna(r.get("source_file_name")) else None,
                                source_row_number=int(r["source_row_number"]) if pd.notna(r.get("source_row_number")) else None,
                                record_id=str(r.get("record_id")) if pd.notna(r.get("record_id")) else None,
                            )
                        )

                    results.append(
                        PatternResult(
                            pattern_id=f"RECURRING_LATE_WFH_APPLICATION_EMP_{emp_num_str}",
                            pattern_type="RECURRING_LATE_WFH_APPLICATION",
                            pattern_category=PatternCategory.WFH.value,
                            pattern_title="Recurring Late WFH Applications",
                            entity_type=EntityType.EMPLOYEE.value,
                            entity_id=emp_num_str,
                            entity_name=emp_name_str,
                            severity=PatternSeverity.ATTENTION.value,
                            strength=strength,
                            persistence=persistence,
                            status=status,
                            event_count=late_count,
                            opportunity_count=total_wfh,
                            rate=rate,
                            first_observed_date=first_d,
                            last_observed_date=last_d,
                            months_active=months_active,
                            distinct_months=dist_months,
                            recurrence_count=late_count,
                            pattern_score=score,
                            score_components=components,
                            description=f"Repeated late WFH submissions for {emp_name_str}.",
                            why_detected=f"Detected because {late_count} of {total_wfh} WFH events ({rate:.1f}%) were submitted >3 days after the availed date across {dist_months} month(s).",
                            summary_evidence=f"{late_count} of {total_wfh} WFH applications submitted late ({rate:.1f}%)",
                            evidence_items=evidence_items,
                            latest_period=months_active[-1] if months_active else None,
                        )
                    )

    return results


def detect_approval_delay_patterns(ctx: PatternContext) -> List[PatternResult]:
    """
    Detect recurring long approval turnarounds (>=5 calendar days) attached to Reporting Manager.
    """
    results: List[PatternResult] = []
    if ctx.df.empty or "approval_turnaround_days" not in ctx.df.columns or "Reporting Manager" not in ctx.df.columns:
        return results

    # Filter to approved rows with valid turnaround
    appr_df = ctx.df[
        (ctx.df["approval_turnaround_days"].notna())
        & (ctx.df["Reporting Manager"].notna())
        & (ctx.df["Reporting Manager"].astype(str).str.strip() != "")
    ].copy()

    if appr_df.empty:
        return results

    for mgr, group in appr_df.groupby("Reporting Manager"):
        mgr_str = str(mgr).strip()
        if not mgr_str or mgr_str.lower() == "nan":
            continue

        long_approvals = group[group["approval_turnaround_days"] >= ctx.long_approval_days]
        long_count = len(long_approvals)
        if long_count < ctx.min_events:
            continue

        total_appr = len(group)
        pct_long = round((long_count / total_appr) * 100.0, 1) if total_appr > 0 else 100.0
        med_turnaround = round(float(long_approvals["approval_turnaround_days"].median()), 1)
        avg_turnaround = round(float(long_approvals["approval_turnaround_days"].mean()), 1)

        dates = long_approvals["Date"].dropna().tolist()
        first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

        days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
        score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
            event_count=long_count,
            opportunity_count=total_appr,
            rate=pct_long,
            distinct_months=dist_months,
            days_since_last=days_since,
        )

        evidence_items = []
        for _, r in long_approvals.iterrows():
            dt_str = pd.to_datetime(r["Date"]).strftime("%Y-%m-%d") if pd.notna(r["Date"]) else ""
            evidence_items.append(
                PatternEvidenceItem(
                    date=dt_str,
                    employee_number=str(r.get("Employee Number") or ""),
                    employee_name=str(r.get("Employee Name") or ""),
                    reporting_manager=mgr_str,
                    event_type=str(r.get("Attendance Type") or "Approval"),
                    status=str(r.get("Approval Status") or "Approved"),
                    approval_turnaround_days=float(r["approval_turnaround_days"]),
                    details=f"Approval turnaround {r['approval_turnaround_days']}d (applied: {r.get('Applied On')}, approved: {r.get('Approved On')})",
                    source_file_name=str(r.get("source_file_name")) if pd.notna(r.get("source_file_name")) else None,
                    source_row_number=int(r["source_row_number"]) if pd.notna(r.get("source_row_number")) else None,
                    record_id=str(r.get("record_id")) if pd.notna(r.get("record_id")) else None,
                )
            )

        pattern_id = f"RECURRING_LONG_APPROVAL_TURNAROUND_MGR_{mgr_str.replace(' ', '_').upper()}"
        why = (
            f"Detected because {long_count} of {total_appr} approved requests ({pct_long:.1f}%) "
            f"had an approval turnaround >= {ctx.long_approval_days} calendar days (median: {med_turnaround}d, avg: {avg_turnaround}d) "
            f"across {dist_months} month(s)."
        )

        results.append(
            PatternResult(
                pattern_id=pattern_id,
                pattern_type="RECURRING_LONG_APPROVAL_TURNAROUND",
                pattern_category=PatternCategory.APPROVAL.value,
                pattern_title="Recurring Long Approval Turnaround",
                entity_type=EntityType.REPORTING_MANAGER.value,
                entity_id=mgr_str,
                entity_name=mgr_str,
                severity=PatternSeverity.ATTENTION.value,
                strength=strength,
                persistence=persistence,
                status=status,
                event_count=long_count,
                opportunity_count=total_appr,
                rate=pct_long,
                first_observed_date=first_d,
                last_observed_date=last_d,
                months_active=months_active,
                distinct_months=dist_months,
                recurrence_count=long_count,
                pattern_score=score,
                score_components=components,
                description=f"Long approval cycles for requests under {mgr_str}.",
                why_detected=why,
                summary_evidence=f"{long_count} of {total_appr} approvals took >={ctx.long_approval_days} days (median: {med_turnaround}d)",
                evidence_items=evidence_items,
                latest_period=months_active[-1] if months_active else None,
            )
        )

    return results


def detect_calendar_patterns(ctx: PatternContext) -> List[PatternResult]:
    """
    Detect calendar-related concentrations:
    - Monday & Friday Concentration (Leave, WFH, Attendance Exceptions >= 60%)
    - Weekend-Adjacent Leave (Fridays / Mondays)
    - Holiday-Adjacent Leave
    - Long Weekend Adjacency
    """
    results: List[PatternResult] = []
    if ctx.facts.empty:
        return results

    eval_facts = ctx.facts[ctx.facts["is_metric_evaluable"] == True].copy()
    if eval_facts.empty or "Date" not in eval_facts.columns:
        return results

    eval_facts["dt"] = pd.to_datetime(eval_facts["Date"]).dt.date
    eval_facts["weekday_num"] = pd.to_datetime(eval_facts["Date"]).dt.weekday  # Mon=0, Fri=4, Sat=5, Sun=6
    eval_facts["is_mon_or_fri"] = eval_facts["weekday_num"].isin([0, 4])

    # Find holiday dates present in source
    holiday_dates = set()
    if "has_holiday" in ctx.facts.columns:
        hol_rows = ctx.facts[ctx.facts["has_holiday"] == True]
        holiday_dates = set(pd.to_datetime(hol_rows["Date"]).dt.date.dropna())

    for (emp_num, emp_name), group in eval_facts.groupby(["Employee Number", "Employee Name"]):
        emp_num_str = str(emp_num)
        emp_name_str = str(emp_name) if pd.notna(emp_name) else emp_num_str
        dates_set = set(group["dt"])

        # 1. Monday & Friday Concentration on Leave or Exceptions
        # Focus on leave days or exception days
        target_events = group[(group["has_leave"] == True) | (group["is_attendance_exception"] == True) | (group["has_wfh"] == True)]
        tot_target = len(target_events)
        if tot_target >= ctx.min_events:
            mon_fri_events = target_events[target_events["is_mon_or_fri"] == True]
            mon_fri_count = len(mon_fri_events)
            if mon_fri_count >= ctx.min_events and (mon_fri_count / tot_target) >= 0.60:
                conc_ratio = mon_fri_count / tot_target
                dates = mon_fri_events["Date"].tolist()
                first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

                days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
                score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                    event_count=mon_fri_count,
                    opportunity_count=tot_target,
                    rate=round(conc_ratio * 100.0, 1),
                    distinct_months=dist_months,
                    days_since_last=days_since,
                    concentration_ratio=conc_ratio,
                )

                evidence_items = []
                for _, r in mon_fri_events.iterrows():
                    dt_str = pd.to_datetime(r["Date"]).strftime("%Y-%m-%d")
                    w_name = pd.to_datetime(r["Date"]).strftime("%A")
                    evidence_items.append(
                        PatternEvidenceItem(
                            date=dt_str,
                            employee_number=emp_num_str,
                            employee_name=emp_name_str,
                            reporting_manager=str(r.get("Reporting Manager")) if pd.notna(r.get("Reporting Manager")) else None,
                            event_type="CALENDAR_CONCENTRATION",
                            status=f"{w_name} Event",
                            details=f"{w_name} event ({'Leave' if r.get('has_leave') else 'WFH' if r.get('has_wfh') else 'Exception'})",
                        )
                    )

                results.append(
                    PatternResult(
                        pattern_id=f"MONDAY_FRIDAY_CONCENTRATION_EMP_{emp_num_str}",
                        pattern_type="MONDAY_FRIDAY_CONCENTRATION",
                        pattern_category=PatternCategory.CALENDAR.value,
                        pattern_title="Monday & Friday Concentration",
                        entity_type=EntityType.EMPLOYEE.value,
                        entity_id=emp_num_str,
                        entity_name=emp_name_str,
                        severity=PatternSeverity.INFO.value,
                        strength=strength,
                        persistence=persistence,
                        status=status,
                        event_count=mon_fri_count,
                        opportunity_count=tot_target,
                        rate=round(conc_ratio * 100.0, 1),
                        first_observed_date=first_d,
                        last_observed_date=last_d,
                        months_active=months_active,
                        distinct_months=dist_months,
                        recurrence_count=mon_fri_count,
                        pattern_score=score,
                        score_components=components,
                        description=f"Leave, WFH, or exceptions concentrate around Mondays and Fridays for {emp_name_str}.",
                        why_detected=f"Detected because {mon_fri_count} of {tot_target} events ({conc_ratio*100:.1f}%) occurred on Mondays or Fridays across {dist_months} month(s).",
                        summary_evidence=f"{mon_fri_count} of {tot_target} events occurred on Mon/Fri ({conc_ratio*100:.1f}%)",
                        evidence_items=evidence_items,
                        latest_period=months_active[-1] if months_active else None,
                    )
                )

        # 2. Weekend-Adjacent Leave (Fridays: weekday=4, Mondays: weekday=0)
        leave_rows = group[group["has_leave"] == True]
        tot_leave = len(leave_rows)
        if tot_leave >= ctx.min_events:
            adj_rows = leave_rows[leave_rows["weekday_num"].isin([0, 4])]
            adj_count = len(adj_rows)
            if adj_count >= ctx.min_events:
                conc_ratio = adj_count / tot_leave
                dates = adj_rows["Date"].tolist()
                first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

                days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
                score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                    event_count=adj_count,
                    opportunity_count=tot_leave,
                    rate=round(conc_ratio * 100.0, 1),
                    distinct_months=dist_months,
                    days_since_last=days_since,
                    concentration_ratio=conc_ratio,
                )

                evidence_items = []
                for _, r in adj_rows.iterrows():
                    dt_str = pd.to_datetime(r["Date"]).strftime("%Y-%m-%d")
                    w_name = pd.to_datetime(r["Date"]).strftime("%A")
                    evidence_items.append(
                        PatternEvidenceItem(
                            date=dt_str,
                            employee_number=emp_num_str,
                            employee_name=emp_name_str,
                            reporting_manager=str(r.get("Reporting Manager")) if pd.notna(r.get("Reporting Manager")) else None,
                            event_type="LEAVE",
                            status=f"{w_name} Leave",
                            details=f"Leave on {w_name} adjacent to weekend",
                        )
                    )

                results.append(
                    PatternResult(
                        pattern_id=f"WEEKEND_ADJACENT_LEAVE_EMP_{emp_num_str}",
                        pattern_type="WEEKEND_ADJACENT_LEAVE",
                        pattern_category=PatternCategory.CALENDAR.value,
                        pattern_title="Weekend-Adjacent Leave",
                        entity_type=EntityType.EMPLOYEE.value,
                        entity_id=emp_num_str,
                        entity_name=emp_name_str,
                        severity=PatternSeverity.INFO.value,
                        strength=strength,
                        persistence=persistence,
                        status=status,
                        event_count=adj_count,
                        opportunity_count=tot_leave,
                        rate=round(conc_ratio * 100.0, 1),
                        first_observed_date=first_d,
                        last_observed_date=last_d,
                        months_active=months_active,
                        distinct_months=dist_months,
                        recurrence_count=adj_count,
                        pattern_score=score,
                        score_components=components,
                        description=f"Leave events frequently adjacent to weekends for {emp_name_str}.",
                        why_detected=f"Detected because {adj_count} of {tot_leave} leave days ({conc_ratio*100:.1f}%) were taken on Friday or Monday.",
                        summary_evidence=f"{adj_count} weekend-adjacent leave events ({conc_ratio*100:.1f}% of leave days)",
                        evidence_items=evidence_items,
                        latest_period=months_active[-1] if months_active else None,
                    )
                )

        # 3. Holiday-Adjacent Leave
        if holiday_dates and tot_leave >= ctx.min_events:
            hol_adj_items = []
            for _, r in leave_rows.iterrows():
                d_val = r["dt"]
                day_before = d_val - timedelta(days=1)
                day_after = d_val + timedelta(days=1)
                if day_before in holiday_dates or day_after in holiday_dates:
                    hol_adj_items.append(r)

            if len(hol_adj_items) >= ctx.min_events:
                hol_adj_count = len(hol_adj_items)
                dates = [r["Date"] for r in hol_adj_items]
                first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

                days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
                score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                    event_count=hol_adj_count,
                    opportunity_count=tot_leave,
                    rate=round((hol_adj_count / tot_leave) * 100.0, 1),
                    distinct_months=dist_months,
                    days_since_last=days_since,
                )

                evidence_items = []
                for r in hol_adj_items:
                    dt_str = pd.to_datetime(r["Date"]).strftime("%Y-%m-%d")
                    evidence_items.append(
                        PatternEvidenceItem(
                            date=dt_str,
                            employee_number=emp_num_str,
                            employee_name=emp_name_str,
                            reporting_manager=str(r.get("Reporting Manager")) if pd.notna(r.get("Reporting Manager")) else None,
                            event_type="LEAVE",
                            status="Holiday Adjacent",
                            details=f"Leave adjacent to holiday on {dt_str}",
                        )
                    )

                results.append(
                    PatternResult(
                        pattern_id=f"HOLIDAY_ADJACENT_LEAVE_EMP_{emp_num_str}",
                        pattern_type="HOLIDAY_ADJACENT_LEAVE",
                        pattern_category=PatternCategory.CALENDAR.value,
                        pattern_title="Holiday-Adjacent Leave",
                        entity_type=EntityType.EMPLOYEE.value,
                        entity_id=emp_num_str,
                        entity_name=emp_name_str,
                        severity=PatternSeverity.INFO.value,
                        strength=strength,
                        persistence=persistence,
                        status=status,
                        event_count=hol_adj_count,
                        opportunity_count=tot_leave,
                        rate=round((hol_adj_count / tot_leave) * 100.0, 1),
                        first_observed_date=first_d,
                        last_observed_date=last_d,
                        months_active=months_active,
                        distinct_months=dist_months,
                        recurrence_count=hol_adj_count,
                        pattern_score=score,
                        score_components=components,
                        description=f"Leave scheduled adjacent to company holidays for {emp_name_str}.",
                        why_detected=f"Detected because {hol_adj_count} leave events occurred immediately before or after a documented holiday across {dist_months} month(s).",
                        summary_evidence=f"{hol_adj_count} holiday-adjacent leave events",
                        evidence_items=evidence_items,
                        latest_period=months_active[-1] if months_active else None,
                    )
                )

    return results


def detect_sequence_patterns(ctx: PatternContext) -> List[PatternResult]:
    """
    Detect chronological transitions:
    - LEAVE_TO_WFH_SEQUENCE: Leave followed by WFH within 1 calendar day
    - WFH_TO_LEAVE_SEQUENCE: WFH followed by Leave within 1 calendar day
    - EXTENDED_REMOTE_LEAVE_SEQUENCE: Friday WFH -> Weekend -> Monday Leave (or Fri Leave -> Mon WFH)
    """
    results: List[PatternResult] = []
    if ctx.facts.empty:
        return results

    eval_facts = ctx.facts[ctx.facts["is_metric_evaluable"] == True].copy()
    if eval_facts.empty or "Date" not in eval_facts.columns:
        return results

    eval_facts["dt"] = pd.to_datetime(eval_facts["Date"]).dt.date
    eval_facts = eval_facts.sort_values(["Employee Number", "dt"])

    for (emp_num, emp_name), group in eval_facts.groupby(["Employee Number", "Employee Name"]):
        emp_num_str = str(emp_num)
        emp_name_str = str(emp_name) if pd.notna(emp_name) else emp_num_str

        sorted_rows = group.to_dict("records")
        if len(sorted_rows) < 2:
            continue

        l_to_wfh_matches = []
        wfh_to_l_matches = []
        remote_bridge_matches = []

        for i in range(len(sorted_rows) - 1):
            curr = sorted_rows[i]
            nxt = sorted_rows[i + 1]

            d_curr = curr["dt"]
            d_nxt = nxt["dt"]
            day_diff = (d_nxt - d_curr).days

            # 1. 1-day proximity (consecutive calendar days)
            if day_diff == 1:
                if curr.get("has_leave") and nxt.get("has_wfh"):
                    l_to_wfh_matches.append((curr, nxt))
                elif curr.get("has_wfh") and nxt.get("has_leave"):
                    wfh_to_l_matches.append((curr, nxt))

            # 2. Weekend bridge (Friday -> Monday, day_diff == 3, Friday is weekday 4, Monday is weekday 0)
            elif day_diff == 3 and d_curr.weekday() == 4 and d_nxt.weekday() == 0:
                if (curr.get("has_wfh") and nxt.get("has_leave")) or (curr.get("has_leave") and nxt.get("has_wfh")):
                    remote_bridge_matches.append((curr, nxt))

        # A. Leave -> WFH
        if len(l_to_wfh_matches) >= ctx.min_events:
            count = len(l_to_wfh_matches)
            dates = [p[0]["Date"] for p in l_to_wfh_matches]
            first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

            days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
            score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                event_count=count,
                opportunity_count=None,
                rate=None,
                distinct_months=dist_months,
                days_since_last=days_since,
            )

            evidence_items = []
            for c, n in l_to_wfh_matches:
                d1 = pd.to_datetime(c["Date"]).strftime("%Y-%m-%d")
                d2 = pd.to_datetime(n["Date"]).strftime("%Y-%m-%d")
                evidence_items.append(
                    PatternEvidenceItem(
                        date=d1,
                        employee_number=emp_num_str,
                        employee_name=emp_name_str,
                        reporting_manager=str(c.get("Reporting Manager")) if pd.notna(c.get("Reporting Manager")) else None,
                        event_type="SEQUENCE",
                        status="Leave → WFH",
                        details=f"Leave on {d1} followed by WFH on {d2}",
                    )
                )

            results.append(
                PatternResult(
                    pattern_id=f"LEAVE_TO_WFH_SEQUENCE_EMP_{emp_num_str}",
                    pattern_type="LEAVE_TO_WFH_SEQUENCE",
                    pattern_category=PatternCategory.SEQUENCE.value,
                    pattern_title="Leave → WFH Sequence",
                    entity_type=EntityType.EMPLOYEE.value,
                    entity_id=emp_num_str,
                    entity_name=emp_name_str,
                    severity=PatternSeverity.INFO.value,
                    strength=strength,
                    persistence=persistence,
                    status=status,
                    event_count=count,
                    opportunity_count=None,
                    rate=None,
                    first_observed_date=first_d,
                    last_observed_date=last_d,
                    months_active=months_active,
                    distinct_months=dist_months,
                    recurrence_count=count,
                    pattern_score=score,
                    score_components=components,
                    description=f"Consecutive Leave followed by Work From Home for {emp_name_str}.",
                    why_detected=f"Detected because {count} occurrences of Leave immediately followed by WFH were observed across {dist_months} month(s).",
                    summary_evidence=f"{count} Leave → WFH transitions observed",
                    evidence_items=evidence_items,
                    latest_period=months_active[-1] if months_active else None,
                )
            )

        # B. WFH -> Leave
        if len(wfh_to_l_matches) >= ctx.min_events:
            count = len(wfh_to_l_matches)
            dates = [p[0]["Date"] for p in wfh_to_l_matches]
            first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

            days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
            score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                event_count=count,
                opportunity_count=None,
                rate=None,
                distinct_months=dist_months,
                days_since_last=days_since,
            )

            evidence_items = []
            for c, n in wfh_to_l_matches:
                d1 = pd.to_datetime(c["Date"]).strftime("%Y-%m-%d")
                d2 = pd.to_datetime(n["Date"]).strftime("%Y-%m-%d")
                evidence_items.append(
                    PatternEvidenceItem(
                        date=d1,
                        employee_number=emp_num_str,
                        employee_name=emp_name_str,
                        reporting_manager=str(c.get("Reporting Manager")) if pd.notna(c.get("Reporting Manager")) else None,
                        event_type="SEQUENCE",
                        status="WFH → Leave",
                        details=f"WFH on {d1} followed by Leave on {d2}",
                    )
                )

            results.append(
                PatternResult(
                    pattern_id=f"WFH_TO_LEAVE_SEQUENCE_EMP_{emp_num_str}",
                    pattern_type="WFH_TO_LEAVE_SEQUENCE",
                    pattern_category=PatternCategory.SEQUENCE.value,
                    pattern_title="WFH → Leave Sequence",
                    entity_type=EntityType.EMPLOYEE.value,
                    entity_id=emp_num_str,
                    entity_name=emp_name_str,
                    severity=PatternSeverity.INFO.value,
                    strength=strength,
                    persistence=persistence,
                    status=status,
                    event_count=count,
                    opportunity_count=None,
                    rate=None,
                    first_observed_date=first_d,
                    last_observed_date=last_d,
                    months_active=months_active,
                    distinct_months=dist_months,
                    recurrence_count=count,
                    pattern_score=score,
                    score_components=components,
                    description=f"Consecutive Work From Home followed by Leave for {emp_name_str}.",
                    why_detected=f"Detected because {count} occurrences of WFH immediately followed by Leave were observed across {dist_months} month(s).",
                    summary_evidence=f"{count} WFH → Leave transitions observed",
                    evidence_items=evidence_items,
                    latest_period=months_active[-1] if months_active else None,
                )
            )

        # C. Extended Remote-Leave Weekend Bridge
        if len(remote_bridge_matches) >= ctx.min_events:
            count = len(remote_bridge_matches)
            dates = [p[0]["Date"] for p in remote_bridge_matches]
            first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

            days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
            score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                event_count=count,
                opportunity_count=None,
                rate=None,
                distinct_months=dist_months,
                days_since_last=days_since,
            )

            evidence_items = []
            for c, n in remote_bridge_matches:
                d1 = pd.to_datetime(c["Date"]).strftime("%Y-%m-%d")
                d2 = pd.to_datetime(n["Date"]).strftime("%Y-%m-%d")
                t1 = "WFH" if c.get("has_wfh") else "Leave"
                t2 = "Leave" if n.get("has_leave") else "WFH"
                evidence_items.append(
                    PatternEvidenceItem(
                        date=d1,
                        employee_number=emp_num_str,
                        employee_name=emp_name_str,
                        reporting_manager=str(c.get("Reporting Manager")) if pd.notna(c.get("Reporting Manager")) else None,
                        event_type="SEQUENCE",
                        status="Weekend Bridge",
                        details=f"Friday {t1} ({d1}) bridging weekend to Monday {t2} ({d2})",
                    )
                )

            results.append(
                PatternResult(
                    pattern_id=f"EXTENDED_REMOTE_LEAVE_SEQUENCE_EMP_{emp_num_str}",
                    pattern_type="EXTENDED_REMOTE_LEAVE_SEQUENCE",
                    pattern_category=PatternCategory.SEQUENCE.value,
                    pattern_title="Extended Remote-Leave Sequence",
                    entity_type=EntityType.EMPLOYEE.value,
                    entity_id=emp_num_str,
                    entity_name=emp_name_str,
                    severity=PatternSeverity.INFO.value,
                    strength=strength,
                    persistence=persistence,
                    status=status,
                    event_count=count,
                    opportunity_count=None,
                    rate=None,
                    first_observed_date=first_d,
                    last_observed_date=last_d,
                    months_active=months_active,
                    distinct_months=dist_months,
                    recurrence_count=count,
                    pattern_score=score,
                    score_components=components,
                    description=f"Friday/Monday remote and leave combination bridging the weekend for {emp_name_str}.",
                    why_detected=f"Detected because {count} remote-and-leave weekend combinations were observed across {dist_months} month(s).",
                    summary_evidence=f"{count} remote-leave weekend bridges observed",
                    evidence_items=evidence_items,
                    latest_period=months_active[-1] if months_active else None,
                )
            )

    return results


def detect_process_non_compliance_patterns(ctx: PatternContext) -> List[PatternResult]:
    """
    Detect broader multi-type process non-compliance at the employee level:
    Aggregates late leave, insufficient notice, late WFH, and missing timestamps.
    Requirements:
    - >= 3 failures
    - >= 2 distinct dates
    """
    results: List[PatternResult] = []

    # Map failures per employee
    emp_failures: Dict[str, List[Dict[str, Any]]] = {}

    # 1. Reconstructed Leave Requests
    if not ctx.req_df.empty:
        non_comp_reqs = ctx.req_df[
            (ctx.req_df["compliance_status"].isin(["NON_COMPLIANT", "PRE_POLICY_BENCHMARK_FAIL"]))
            & (ctx.req_df["non_compliance_reason"].isin(["LATE_APPLICATION", "INSUFFICIENT_ADVANCE_NOTICE", "MISSING_APPLICATION_DATE"]))
        ]
        for _, r in non_comp_reqs.iterrows():
            emp_num = str(r.get("employee_number") or "UNKNOWN")
            if emp_num not in emp_failures:
                emp_failures[emp_num] = []
            st_d = str(r.get("request_start_date") or "")
            emp_failures[emp_num].append({
                "date": st_d,
                "type": f"Leave ({r.get('leave_name_normalized') or 'Leave'})",
                "reason": str(r.get("non_compliance_reason")),
                "name": str(r.get("employee_name") or emp_num),
                "manager": str(r.get("reporting_manager") or ""),
                "lag": r.get("request_application_lag_days"),
                "req_id": r.get("request_id"),
            })

    # 2. WFH Rows
    if not ctx.df.empty and "policy_event_type" in ctx.df.columns:
        wfh_fails = ctx.df[
            (ctx.df["policy_event_type"] == "WFH")
            & (ctx.df["compliance_status"].isin(["NON_COMPLIANT", "PRE_POLICY_BENCHMARK_FAIL"]))
            & (ctx.df["non_compliance_reason"].isin(["LATE_APPLICATION", "MISSING_APPLICATION_DATE"]))
        ]
        for _, r in wfh_fails.iterrows():
            emp_num = str(r.get("Employee Number") or "UNKNOWN")
            if emp_num not in emp_failures:
                emp_failures[emp_num] = []
            dt_str = pd.to_datetime(r["Date"]).strftime("%Y-%m-%d") if pd.notna(r.get("Date")) else ""
            emp_failures[emp_num].append({
                "date": dt_str,
                "type": "Work From Home",
                "reason": str(r.get("non_compliance_reason")),
                "name": str(r.get("Employee Name") or emp_num),
                "manager": str(r.get("Reporting Manager") or ""),
                "lag": r.get("application_lag_days"),
                "rec_id": r.get("record_id"),
                "source_file": r.get("source_file_name"),
                "source_row": r.get("source_row_number"),
            })

    for emp_num, fails in emp_failures.items():
        if len(fails) < ctx.min_events:
            continue

        distinct_dates = {f["date"] for f in fails if f["date"]}
        if len(distinct_dates) < 2:
            continue

        count = len(fails)
        emp_name_str = fails[0]["name"]
        dates = list(distinct_dates)
        first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

        days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
        score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
            event_count=count,
            opportunity_count=None,
            rate=None,
            distinct_months=dist_months,
            days_since_last=days_since,
        )

        fail_types = sorted(list({f["type"] for f in fails}))
        evidence_items = []
        for f in fails:
            evidence_items.append(
                PatternEvidenceItem(
                    date=f["date"],
                    employee_number=emp_num,
                    employee_name=emp_name_str,
                    reporting_manager=f["manager"] or None,
                    event_type="PROCESS_NON_COMPLIANCE",
                    status=f["type"],
                    details=f"{f['type']}: {f['reason'].replace('_', ' ').title()}",
                    request_id=f.get("req_id"),
                    record_id=f.get("rec_id"),
                    source_file_name=f.get("source_file"),
                    source_row_number=f.get("source_row"),
                )
            )

        why = (
            f"Detected because {count} process non-compliance events across {len(distinct_dates)} distinct dates "
            f"were observed across {dist_months} month(s) (involving {', '.join(fail_types)})."
        )

        results.append(
            PatternResult(
                pattern_id=f"REPEAT_PROCESS_NON_COMPLIANCE_EMP_{emp_num}",
                pattern_type="REPEAT_PROCESS_NON_COMPLIANCE",
                pattern_category=PatternCategory.PROCESS.value,
                pattern_title="Repeat Process Non-Compliance",
                entity_type=EntityType.EMPLOYEE.value,
                entity_id=emp_num,
                entity_name=emp_name_str,
                severity=PatternSeverity.PRIORITY.value,
                strength=strength,
                persistence=persistence,
                status=status,
                event_count=count,
                opportunity_count=None,
                rate=None,
                first_observed_date=first_d,
                last_observed_date=last_d,
                months_active=months_active,
                distinct_months=dist_months,
                recurrence_count=count,
                pattern_score=score,
                score_components=components,
                description=f"Multiple process timing failures across leave and WFH for {emp_name_str}.",
                why_detected=why,
                summary_evidence=f"{count} process failures across {len(distinct_dates)} dates ({', '.join(fail_types)})",
                evidence_items=evidence_items,
                latest_period=months_active[-1] if months_active else None,
            )
        )

    return results


def detect_group_concentration_patterns(ctx: PatternContext) -> List[PatternResult]:
    """
    Detect concentration at Business Unit, Department, Sub-Department, and Reporting Manager levels.
    Compares group exception rate vs. organization rate.
    Requirements:
    - Group evaluable opportunities >= 10
    - Group exception rate >= Organization exception rate + 10.0 percentage points
    """
    results: List[PatternResult] = []
    if ctx.facts.empty:
        return results

    eval_facts = ctx.facts[ctx.facts["is_metric_evaluable"] == True].copy()
    if eval_facts.empty:
        return results

    dimensions = [
        ("Department", EntityType.DEPARTMENT, "GROUP_CONCENTRATION"),
        ("Business Unit", EntityType.BUSINESS_UNIT, "GROUP_CONCENTRATION"),
        ("Reporting Manager", EntityType.REPORTING_MANAGER, "MANAGER_CONCENTRATION"),
    ]

    for col_name, ent_type, p_type in dimensions:
        if col_name not in eval_facts.columns:
            continue

        for group_val, group_df in eval_facts.groupby(col_name):
            group_name = str(group_val).strip()
            if not group_name or group_name.lower() == "nan":
                continue

            opp_count = len(group_df)
            if opp_count < 10:  # Gating threshold
                continue

            exc_count = int((group_df["is_attendance_exception"] == True).sum())
            if exc_count < ctx.min_events:
                continue

            group_rate = round((exc_count / opp_count) * 100.0, 1)

            # Materially higher than organization baseline
            if group_rate < (ctx.org_exception_rate + 10.0):
                continue

            dates = group_df[group_df["is_attendance_exception"] == True]["Date"].tolist()
            first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

            days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
            score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                event_count=exc_count,
                opportunity_count=opp_count,
                rate=group_rate,
                distinct_months=dist_months,
                days_since_last=days_since,
            )

            # Evidence sample
            evidence_items = []
            exc_rows = group_df[group_df["is_attendance_exception"] == True]
            for _, r in exc_rows.iterrows():
                dt_str = pd.to_datetime(r["Date"]).strftime("%Y-%m-%d") if pd.notna(r["Date"]) else ""
                evidence_items.append(
                    PatternEvidenceItem(
                        date=dt_str,
                        employee_number=str(r.get("Employee Number") or ""),
                        employee_name=str(r.get("Employee Name") or ""),
                        reporting_manager=str(r.get("Reporting Manager")) if pd.notna(r.get("Reporting Manager")) else None,
                        event_type="ATTENDANCE_EXCEPTION",
                        status=str(r.get("attendance_exception_types") or "Exception"),
                        details=f"Team exception in {group_name} on {dt_str}",
                    )
                )

            ent_key = group_name.replace(" ", "_").upper()
            pattern_id = f"{p_type}_{ent_type.value}_{ent_key}"

            if ent_type == EntityType.REPORTING_MANAGER:
                title = f"Team Exception Concentration Under {group_name}"
                desc = f"Attendance exceptions for team members reporting to {group_name} exceed organization average."
                why = (
                    f"Detected because the team under {group_name} recorded {exc_count} exceptions in {opp_count} evaluable days "
                    f"({group_rate:.1f}%), exceeding the organization baseline of {ctx.org_exception_rate:.1f}% by {group_rate - ctx.org_exception_rate:.1f} points."
                )
            else:
                title = f"{group_name} Exception Rate Concentration"
                desc = f"Exception rate in {group_name} is materially higher than the organization baseline."
                why = (
                    f"Detected because {group_name} recorded {exc_count} exceptions across {opp_count} evaluable days "
                    f"({group_rate:.1f}%), compared to the organization baseline of {ctx.org_exception_rate:.1f}%."
                )

            results.append(
                PatternResult(
                    pattern_id=pattern_id,
                    pattern_type=p_type,
                    pattern_category=PatternCategory.PROCESS.value,
                    pattern_title=title,
                    entity_type=ent_type.value,
                    entity_id=group_name,
                    entity_name=group_name,
                    severity=PatternSeverity.ATTENTION.value,
                    strength=strength,
                    persistence=persistence,
                    status=status,
                    event_count=exc_count,
                    opportunity_count=opp_count,
                    rate=group_rate,
                    reference_rate=ctx.org_exception_rate,
                    first_observed_date=first_d,
                    last_observed_date=last_d,
                    months_active=months_active,
                    distinct_months=dist_months,
                    recurrence_count=exc_count,
                    pattern_score=score,
                    score_components=components,
                    description=desc,
                    why_detected=why,
                    summary_evidence=f"{group_rate:.1f}% exception rate vs {ctx.org_exception_rate:.1f}% organization baseline ({opp_count} evaluable days)",
                    evidence_items=evidence_items,
                    latest_period=months_active[-1] if months_active else None,
                )
            )

    return results


def detect_month_boundary_patterns(ctx: PatternContext) -> List[PatternResult]:
    """
    Detect clustering in the first 3 or last 3 calendar days of the month.
    Requirements:
    - >= 3 events
    - >= 40% of relevant events occur inside the boundary window
    """
    results: List[PatternResult] = []
    if ctx.facts.empty:
        return results

    eval_facts = ctx.facts[ctx.facts["is_metric_evaluable"] == True].copy()
    if eval_facts.empty or "Date" not in eval_facts.columns:
        return results

    eval_facts["dt"] = pd.to_datetime(eval_facts["Date"])
    eval_facts["day_of_month"] = eval_facts["dt"].dt.day
    eval_facts["days_in_month"] = eval_facts["dt"].dt.days_in_month
    eval_facts["is_month_start"] = eval_facts["day_of_month"] <= MONTH_BOUNDARY_DAYS
    eval_facts["is_month_end"] = eval_facts["day_of_month"] > (eval_facts["days_in_month"] - MONTH_BOUNDARY_DAYS)

    for (emp_num, emp_name), group in eval_facts.groupby(["Employee Number", "Employee Name"]):
        emp_num_str = str(emp_num)
        emp_name_str = str(emp_name) if pd.notna(emp_name) else emp_num_str

        exc_rows = group[group["is_attendance_exception"] == True]
        tot_exc = len(exc_rows)
        if tot_exc < ctx.min_events:
            continue

        # Month-End Concentration
        end_rows = exc_rows[exc_rows["is_month_end"] == True]
        end_count = len(end_rows)
        if end_count >= ctx.min_events and (end_count / tot_exc) >= 0.40:
            conc_ratio = end_count / tot_exc
            dates = end_rows["Date"].tolist()
            first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

            days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
            score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                event_count=end_count,
                opportunity_count=tot_exc,
                rate=round(conc_ratio * 100.0, 1),
                distinct_months=dist_months,
                days_since_last=days_since,
                concentration_ratio=conc_ratio,
            )

            evidence_items = []
            for _, r in end_rows.iterrows():
                dt_str = pd.to_datetime(r["Date"]).strftime("%Y-%m-%d")
                evidence_items.append(
                    PatternEvidenceItem(
                        date=dt_str,
                        employee_number=emp_num_str,
                        employee_name=emp_name_str,
                        reporting_manager=str(r.get("Reporting Manager")) if pd.notna(r.get("Reporting Manager")) else None,
                        event_type="ATTENDANCE_EXCEPTION",
                        status="Month-End",
                        details=f"Exception on {dt_str} (day {r['day_of_month']} of {r['days_in_month']})",
                    )
                )

            results.append(
                PatternResult(
                    pattern_id=f"MONTH_END_CONCENTRATION_EMP_{emp_num_str}",
                    pattern_type="MONTH_END_CONCENTRATION",
                    pattern_category=PatternCategory.PROCESS.value,
                    pattern_title="Month-End Exception Clustering",
                    entity_type=EntityType.EMPLOYEE.value,
                    entity_id=emp_num_str,
                    entity_name=emp_name_str,
                    severity=PatternSeverity.INFO.value,
                    strength=strength,
                    persistence=persistence,
                    status=status,
                    event_count=end_count,
                    opportunity_count=tot_exc,
                    rate=round(conc_ratio * 100.0, 1),
                    first_observed_date=first_d,
                    last_observed_date=last_d,
                    months_active=months_active,
                    distinct_months=dist_months,
                    recurrence_count=end_count,
                    pattern_score=score,
                    score_components=components,
                    description=f"Attendance exceptions cluster heavily near the end of the month for {emp_name_str}.",
                    why_detected=f"Detected because {end_count} of {tot_exc} exceptions ({conc_ratio*100:.1f}%) occurred in the final 3 days of the month across {dist_months} month(s).",
                    summary_evidence=f"{end_count} of {tot_exc} exceptions in final 3 calendar days of month",
                    evidence_items=evidence_items,
                    latest_period=months_active[-1] if months_active else None,
                )
            )

        # Month-Start Concentration
        start_rows = exc_rows[exc_rows["is_month_start"] == True]
        start_count = len(start_rows)
        if start_count >= ctx.min_events and (start_count / tot_exc) >= 0.40:
            conc_ratio = start_count / tot_exc
            dates = start_rows["Date"].tolist()
            first_d, last_d, months_active, dist_months = _extract_date_metadata(dates)

            days_since = (ctx.dataset_max_date - pd.to_datetime(last_d).date()).days if last_d and ctx.dataset_max_date else 0
            score, components, strength, persistence, status = _calculate_pattern_score_and_badges(
                event_count=start_count,
                opportunity_count=tot_exc,
                rate=round(conc_ratio * 100.0, 1),
                distinct_months=dist_months,
                days_since_last=days_since,
                concentration_ratio=conc_ratio,
            )

            evidence_items = []
            for _, r in start_rows.iterrows():
                dt_str = pd.to_datetime(r["Date"]).strftime("%Y-%m-%d")
                evidence_items.append(
                    PatternEvidenceItem(
                        date=dt_str,
                        employee_number=emp_num_str,
                        employee_name=emp_name_str,
                        reporting_manager=str(r.get("Reporting Manager")) if pd.notna(r.get("Reporting Manager")) else None,
                        event_type="ATTENDANCE_EXCEPTION",
                        status="Month-Start",
                        details=f"Exception on {dt_str} (day {r['day_of_month']})",
                    )
                )

            results.append(
                PatternResult(
                    pattern_id=f"MONTH_START_CONCENTRATION_EMP_{emp_num_str}",
                    pattern_type="MONTH_START_CONCENTRATION",
                    pattern_category=PatternCategory.PROCESS.value,
                    pattern_title="Month-Start Exception Clustering",
                    entity_type=EntityType.EMPLOYEE.value,
                    entity_id=emp_num_str,
                    entity_name=emp_name_str,
                    severity=PatternSeverity.INFO.value,
                    strength=strength,
                    persistence=persistence,
                    status=status,
                    event_count=start_count,
                    opportunity_count=tot_exc,
                    rate=round(conc_ratio * 100.0, 1),
                    first_observed_date=first_d,
                    last_observed_date=last_d,
                    months_active=months_active,
                    distinct_months=dist_months,
                    recurrence_count=start_count,
                    pattern_score=score,
                    score_components=components,
                    description=f"Attendance exceptions cluster heavily in the first 3 days of the month for {emp_name_str}.",
                    why_detected=f"Detected because {start_count} of {tot_exc} exceptions ({conc_ratio*100:.1f}%) occurred in the first 3 days of the month across {dist_months} month(s).",
                    summary_evidence=f"{start_count} of {tot_exc} exceptions in first 3 calendar days of month",
                    evidence_items=evidence_items,
                    latest_period=months_active[-1] if months_active else None,
                )
            )

    return results


# ── MASTER PATTERN DETECTOR ORCHESTRATOR ───────────────────────────────────────
def detect_patterns(
    evaluated_df: pd.DataFrame,
    evaluated_requests: Optional[List[Dict[str, Any]]] = None,
    employee_day_facts: Optional[pd.DataFrame] = None,
    filters: Optional[Dict[str, Any]] = None,
    min_events: int = MIN_PATTERN_EVENTS,
    long_approval_days: int = DEFAULT_LONG_APPROVAL_DAYS,
) -> Tuple[PatternSummary, List[PatternResult]]:
    """
    Execute all modular pattern detectors against the governed analytical context.
    Deduplicates patterns deterministically by pattern_id, filters results,
    and sorts them logically (ACTIVE status first, then strength, score, and latest date).
    """
    ctx = PatternContext(
        evaluated_df=evaluated_df,
        evaluated_requests=evaluated_requests,
        employee_day_facts=employee_day_facts,
        min_events=min_events,
        long_approval_days=long_approval_days,
    )

    all_patterns: List[PatternResult] = []

    # Run modular detectors
    all_patterns.extend(detect_weekday_exception_patterns(ctx))
    all_patterns.extend(detect_attendance_recurrence_patterns(ctx))
    all_patterns.extend(detect_leave_wfh_timing_patterns(ctx))
    all_patterns.extend(detect_approval_delay_patterns(ctx))
    all_patterns.extend(detect_calendar_patterns(ctx))
    all_patterns.extend(detect_sequence_patterns(ctx))
    all_patterns.extend(detect_process_non_compliance_patterns(ctx))
    all_patterns.extend(detect_group_concentration_patterns(ctx))
    all_patterns.extend(detect_month_boundary_patterns(ctx))

    # Deduplicate by pattern_id
    deduped: Dict[str, PatternResult] = {}
    for p in all_patterns:
        if p.pattern_id not in deduped:
            deduped[p.pattern_id] = p
        else:
            # If duplicate ID exists, keep the one with higher event_count or score
            if p.pattern_score > deduped[p.pattern_id].pattern_score:
                deduped[p.pattern_id] = p

    pattern_list = list(deduped.values())

    # Apply optional query filters
    if filters:
        category_filter = filters.get("category")
        if category_filter and category_filter.lower() != "all":
            pattern_list = [p for p in pattern_list if p.pattern_category.lower() == str(category_filter).lower()]

        ptype_filter = filters.get("pattern_type")
        if ptype_filter:
            pattern_list = [p for p in pattern_list if p.pattern_type.lower() == str(ptype_filter).lower()]

        entity_type_filter = filters.get("entity_type")
        if entity_type_filter:
            pattern_list = [p for p in pattern_list if p.entity_type.lower() == str(entity_type_filter).lower()]

        strength_filter = filters.get("strength")
        if strength_filter:
            pattern_list = [p for p in pattern_list if p.strength.lower() == str(strength_filter).lower()]

        status_filter = filters.get("status")
        if status_filter:
            pattern_list = [p for p in pattern_list if p.status.lower() == str(status_filter).lower()]

        emp_filter = filters.get("employee_number")
        if emp_filter:
            pattern_list = [
                p for p in pattern_list
                if (p.entity_type == EntityType.EMPLOYEE.value and p.entity_id == str(emp_filter))
                or any(item.employee_number == str(emp_filter) for item in p.evidence_items)
            ]

        mgr_filter = filters.get("reporting_manager")
        if mgr_filter:
            pattern_list = [
                p for p in pattern_list
                if (p.entity_type == EntityType.REPORTING_MANAGER.value and p.entity_id.lower() == str(mgr_filter).lower())
                or any(item.reporting_manager and item.reporting_manager.lower() == str(mgr_filter).lower() for item in p.evidence_items)
            ]

    # Rank results deterministically:
    # 1. Status: ACTIVE (0), RECENT (1), HISTORICAL (2)
    # 2. Strength: HIGH (0), MODERATE (1), LOW (2)
    # 3. Pattern Score (descending)
    # 4. Latest Observed Date (descending)
    status_rank = {PatternStatus.ACTIVE.value: 0, PatternStatus.RECENT.value: 1, PatternStatus.HISTORICAL.value: 2}
    strength_rank = {PatternStrength.HIGH.value: 0, PatternStrength.MODERATE.value: 1, PatternStrength.LOW.value: 2}

    def sort_key(p: PatternResult):
        st_r = status_rank.get(p.status, 99)
        str_r = strength_rank.get(p.strength, 99)
        score_r = -p.pattern_score
        date_r = p.last_observed_date or "1970-01-01"
        return (st_r, str_r, score_r, date_r)

    pattern_list.sort(key=sort_key)

    # Compute Pattern Summary
    emp_ids: Set[str] = set()
    mgr_ids: Set[str] = set()
    cat_counts: Dict[str, int] = {}
    sev_counts: Dict[str, int] = {}
    active_count = 0
    high_count = 0

    for p in pattern_list:
        if p.status == PatternStatus.ACTIVE.value:
            active_count += 1
        if p.strength == PatternStrength.HIGH.value:
            high_count += 1

        if p.entity_type == EntityType.EMPLOYEE.value:
            emp_ids.add(p.entity_id)
        elif p.entity_type == EntityType.REPORTING_MANAGER.value:
            mgr_ids.add(p.entity_id)

        cat_counts[p.pattern_category] = cat_counts.get(p.pattern_category, 0) + 1
        sev_counts[p.severity] = sev_counts.get(p.severity, 0) + 1

    summary = PatternSummary(
        total_patterns=len(pattern_list),
        active_patterns=active_count,
        high_strength_patterns=high_count,
        employees_with_patterns=len(emp_ids),
        managers_with_patterns=len(mgr_ids),
        category_counts=cat_counts,
        severity_counts=sev_counts,
    )

    return summary, pattern_list
