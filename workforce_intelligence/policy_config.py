"""
policy_config.py
────────────────
Centralized policy rules, thresholds, rule descriptions, aliases,
and category enumerations for the Workforce Intelligence Policy Engine.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, Set, Tuple


# ── Core Policy Parameters ────────────────────────────────────────────

POLICY_EFFECTIVE_DATE_STR: str = "2026-10-01"
POLICY_EFFECTIVE_DATE: date = date(2026, 10, 1)

# Application lag threshold (calendar days after event)
NON_PL_MAX_POST_DAYS: int = 3
WFH_MAX_POST_DAYS: int = 3

# Privilege Leave (PL) advance notice buckets
PL_SHORT_MAX_UNITS: float = 3.0
PL_SHORT_ADVANCE_DAYS: int = 2

PL_MEDIUM_MAX_UNITS: float = 7.0
PL_MEDIUM_ADVANCE_DAYS: int = 15

PL_LONG_ADVANCE_DAYS: int = 30

# Case-insensitive aliases for Privilege Leave
DEFAULT_PL_ALIASES: Tuple[str, ...] = (
    "pl",
    "privilege leave",
    "privilege",
)


# ── Policy Rule Codes and Descriptions ────────────────────────────────

POLICY_RULES: Dict[str, str] = {
    "PL_NOTICE_2D": "Privilege Leave up to 3 units requires application at least 2 calendar days before the leave start date.",
    "PL_NOTICE_15D": "Privilege Leave over 3 and up to 7 units requires application at least 15 calendar days before the leave start date.",
    "PL_NOTICE_30D": "Privilege Leave over 7 units requires application at least 30 calendar days before the leave start date.",
    "NON_PL_APPLY_WITHIN_3D": "Non-PL leave must be applied no later than 3 calendar days after the availed date.",
    "WFH_APPLY_WITHIN_3D": "WFH must be applied no later than 3 calendar days after the availed date.",
    "NOT_APPLICABLE": "Record is not subject to leave or WFH application policy.",
}


# ── Attendance Exception Mapping ──────────────────────────────────────

ATTENDANCE_EXCEPTION_MAP: Dict[str, str] = {
    "absent": "ABSENT",
    "missing swipes": "MISSING_SWIPE",
    "missing swipe": "MISSING_SWIPE",
    "attendance regularized": "ATTENDANCE_REGULARIZED",
    "regularized": "ATTENDANCE_REGULARIZED",
}


# ── Approval State Mapping ────────────────────────────────────────────

APPROVAL_STATE_MAP: Dict[str, str] = {
    "approved": "APPROVED",
    "auto approved": "APPROVED",
    "accepted": "APPROVED",
    "pending": "PENDING",
    "submitted": "PENDING",
    "in process": "PENDING",
    "applied": "PENDING",
    "rejected": "REJECTED",
    "denied": "REJECTED",
    "cancelled": "CANCELLED",
    "canceled": "CANCELLED",
    "withdrawn": "CANCELLED",
}


@dataclass(frozen=True)
class PolicyConfig:
    """Configurable policy thresholds and aliases."""
    policy_effective_date: date = POLICY_EFFECTIVE_DATE
    non_pl_max_post_days: int = NON_PL_MAX_POST_DAYS
    wfh_max_post_days: int = WFH_MAX_POST_DAYS
    pl_short_max_units: float = PL_SHORT_MAX_UNITS
    pl_short_advance_days: int = PL_SHORT_ADVANCE_DAYS
    pl_medium_max_units: float = PL_MEDIUM_MAX_UNITS
    pl_medium_advance_days: int = PL_MEDIUM_ADVANCE_DAYS
    pl_long_advance_days: int = PL_LONG_ADVANCE_DAYS
    pl_aliases: Tuple[str, ...] = DEFAULT_PL_ALIASES

    def is_pl_leave(self, leave_name: str, status: str = "") -> bool:
        """Check if a leave name or status corresponds to Privilege Leave."""
        ln_clean = str(leave_name).strip().lower() if leave_name else ""
        st_clean = str(status).strip().lower() if status else ""

        for alias in self.pl_aliases:
            if ln_clean == alias or alias in ln_clean:
                return True
            if st_clean == alias:
                return True
        return False


# Global default configuration instance
DEFAULT_POLICY_CONFIG = PolicyConfig()
