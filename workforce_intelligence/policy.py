"""
policy.py
─────────
Deterministic workforce policy and compliance evaluation engine.
Evaluates leave requests and WFH events against organizational policies,
maintains pre-policy benchmark vs post-policy enforceable distinctions,
and provides transparent, explainable reason codes for every evaluation.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd

from workforce_intelligence.policy_config import (
    DEFAULT_POLICY_CONFIG,
    POLICY_RULES,
    PolicyConfig,
)
from workforce_intelligence.requests import LeaveRequest, build_leave_requests


def classify_policy_event(row: pd.Series, config: PolicyConfig) -> str:
    """
    Classify a workforce event row into a policy event type:
    - PL: Privilege Leave
    - NON_PL_LEAVE: All other leave types
    - WFH: Work From Home
    - ATTENDANCE: Absent, Missing Swipes, Regularization
    - OTHER: Present, Week Off, Holiday, On Duty, etc.
    """
    cat = str(row.get("attendance_category") or "").strip()
    status = str(row.get("Status") or "").strip()
    atype = str(row.get("Attendance Type") or "").strip()
    lname = str(row.get("Leave Name") or "").strip()

    if cat == "Leave" or "leave" in atype.lower() or status.lower() in ("cl", "sl", "pl", "el", "ml", "clsl"):
        if config.is_pl_leave(lname, status):
            return "PL"
        return "NON_PL_LEAVE"

    if cat == "Work From Home" or "wfh" in atype.lower() or status.lower() == "wfh":
        return "WFH"

    if cat in ("Absent", "Missing Swipes", "Attendance Regularized") or status.lower() in ("a", "ab", "ms", "p(ms)", "a(r)", "ar"):
        return "ATTENDANCE"

    return "OTHER"


def evaluate_leave_request(
    req: LeaveRequest, config: PolicyConfig
) -> Dict[str, Any]:
    """
    Evaluate compliance for a reconstructed leave request.
    Distinguishes PRE_POLICY benchmark from POST_POLICY enforceable status.
    """
    # 1. Determine policy period
    is_post_policy = False
    if req.request_start_date:
        is_post_policy = req.request_start_date >= config.policy_effective_date
    policy_period = "POST_POLICY" if is_post_policy else "PRE_POLICY"

    # 2. Handle Critical Data Quality
    if req.has_data_quality_issue:
        rule_code = "PL_NOTICE_2D" if req.is_pl else "NON_PL_APPLY_WITHIN_3D"
        return {
            "request_id": req.request_id,
            "policy_event_type": "PL" if req.is_pl else "NON_PL_LEAVE",
            "policy_rule_code": rule_code,
            "policy_rule_description": POLICY_RULES.get(rule_code, ""),
            "required_notice_days": 2 if req.is_pl else None,
            "allowed_post_days": None if req.is_pl else 3,
            "policy_period": policy_period,
            "benchmark_compliant": None,
            "policy_compliant": None,
            "compliance_status": "DATA_QUALITY_UNCERTAIN",
            "non_compliance_reason": "SOURCE_DATA_QUALITY_CRITICAL",
        }

    # 3. Handle Missing Application Date
    if req.applied_on is None:
        rule_code = "PL_NOTICE_2D" if req.is_pl else "NON_PL_APPLY_WITHIN_3D"
        return {
            "request_id": req.request_id,
            "policy_event_type": "PL" if req.is_pl else "NON_PL_LEAVE",
            "policy_rule_code": rule_code,
            "policy_rule_description": POLICY_RULES.get(rule_code, ""),
            "required_notice_days": 2 if req.is_pl else None,
            "allowed_post_days": None if req.is_pl else 3,
            "policy_period": policy_period,
            "benchmark_compliant": False,
            "policy_compliant": False if is_post_policy else None,
            "compliance_status": "NON_COMPLIANT" if is_post_policy else "PRE_POLICY_BENCHMARK_FAIL",
            "non_compliance_reason": "MISSING_APPLICATION_DATE",
        }

    # 4. Evaluate Timing / Advance Notice
    lag = req.request_application_lag_days or 0
    qty = req.request_total_quantity if req.request_total_quantity is not None else 1.0

    if req.is_pl:
        if qty <= config.pl_short_max_units:
            rule_code = "PL_NOTICE_2D"
            req_notice = config.pl_short_advance_days
        elif qty <= config.pl_medium_max_units:
            rule_code = "PL_NOTICE_15D"
            req_notice = config.pl_medium_advance_days
        else:
            rule_code = "PL_NOTICE_30D"
            req_notice = config.pl_long_advance_days

        # Advance notice: lag must be <= -req_notice
        is_compliant = (lag <= -req_notice)
        reason = None if is_compliant else "INSUFFICIENT_ADVANCE_NOTICE"
        allowed_post = None
    else:
        rule_code = "NON_PL_APPLY_WITHIN_3D"
        req_notice = None
        allowed_post = config.non_pl_max_post_days
        # Within post days: lag must be <= allowed_post_days
        is_compliant = (lag <= allowed_post)
        reason = None if is_compliant else "LATE_APPLICATION"

    if is_compliant:
        comp_status = "COMPLIANT" if is_post_policy else "PRE_POLICY_BENCHMARK_PASS"
        policy_comp = True if is_post_policy else None
        bench_comp = True
    else:
        comp_status = "NON_COMPLIANT" if is_post_policy else "PRE_POLICY_BENCHMARK_FAIL"
        policy_comp = False if is_post_policy else None
        bench_comp = False

    return {
        "request_id": req.request_id,
        "policy_event_type": "PL" if req.is_pl else "NON_PL_LEAVE",
        "policy_rule_code": rule_code,
        "policy_rule_description": POLICY_RULES.get(rule_code, ""),
        "required_notice_days": req_notice,
        "allowed_post_days": allowed_post,
        "policy_period": policy_period,
        "benchmark_compliant": bench_comp,
        "policy_compliant": policy_comp,
        "compliance_status": comp_status,
        "non_compliance_reason": reason or "NONE",
    }


def evaluate_policy(
    df: pd.DataFrame,
    leave_requests: Optional[List[LeaveRequest]] = None,
    config: Optional[PolicyConfig] = None,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """
    Evaluate policy compliance across all rows and leave requests.

    Returns:
        (evaluated_df, evaluated_leave_requests)
    """
    if config is None:
        config = DEFAULT_POLICY_CONFIG

    df = df.copy()

    # 1. Build leave requests if not already provided
    if leave_requests is None:
        leave_requests, df = build_leave_requests(df, config=config)

    # 2. Evaluate all leave requests
    req_eval_map: Dict[str, Dict[str, Any]] = {}
    evaluated_req_list: List[Dict[str, Any]] = []
    for req in leave_requests:
        res = evaluate_leave_request(req, config)
        req_eval_map[req.request_id] = res
        # Combine request metadata with evaluation results
        full_dict = req.to_dict()
        full_dict.update(res)
        evaluated_req_list.append(full_dict)

    # 3. Classify event types for all rows
    df["policy_event_type"] = [classify_policy_event(r, config) for _, r in df.iterrows()]

    # 4. Map request quantity back to rows
    req_qty_map = {r.request_id: r.request_total_quantity for r in leave_requests}
    df["request_total_quantity"] = df["request_id"].map(req_qty_map)

    # 5. Populate row-level policy columns
    rule_codes = []
    rule_descs = []
    req_notices = []
    allowed_posts = []
    periods = []
    bench_compliants = []
    policy_compliants = []
    statuses = []
    reasons = []

    for idx, row in df.iterrows():
        ev_type = row["policy_event_type"]
        req_id = row.get("request_id")
        evt_date = pd.to_datetime(row.get("Date")).date() if pd.notna(row.get("Date")) else None
        is_post_policy = bool(evt_date and evt_date >= config.policy_effective_date)
        period = "POST_POLICY" if is_post_policy else "PRE_POLICY"

        # Case A: Leave Row linked to a LeaveRequest
        if req_id and req_id in req_eval_map:
            eval_res = req_eval_map[req_id]
            rule_codes.append(eval_res["policy_rule_code"])
            rule_descs.append(eval_res["policy_rule_description"])
            req_notices.append(eval_res["required_notice_days"])
            allowed_posts.append(eval_res["allowed_post_days"])
            periods.append(eval_res["policy_period"])
            bench_compliants.append(eval_res["benchmark_compliant"])
            policy_compliants.append(eval_res["policy_compliant"])
            statuses.append(eval_res["compliance_status"])
            reasons.append(eval_res["non_compliance_reason"])

        # Case B: WFH Row
        elif ev_type == "WFH":
            rule_code = "WFH_APPLY_WITHIN_3D"
            rule_desc = POLICY_RULES[rule_code]
            allowed_post = config.wfh_max_post_days

            # Check critical data quality issue on row
            has_dq_issue = bool(row.get("dq_daily_quantity_exceeds_one", False))
            if has_dq_issue:
                rule_codes.append(rule_code)
                rule_descs.append(rule_desc)
                req_notices.append(None)
                allowed_posts.append(allowed_post)
                periods.append(period)
                bench_compliants.append(None)
                policy_compliants.append(None)
                statuses.append("DATA_QUALITY_UNCERTAIN")
                reasons.append("SOURCE_DATA_QUALITY_CRITICAL")
            elif pd.isna(row.get("Applied On")):
                rule_codes.append(rule_code)
                rule_descs.append(rule_desc)
                req_notices.append(None)
                allowed_posts.append(allowed_post)
                periods.append(period)
                bench_compliants.append(False)
                policy_compliants.append(False if is_post_policy else None)
                statuses.append("NON_COMPLIANT" if is_post_policy else "PRE_POLICY_BENCHMARK_FAIL")
                reasons.append("MISSING_APPLICATION_DATE")
            else:
                lag = row.get("application_lag_days")
                if lag is None or pd.isna(lag):
                    app_on = pd.to_datetime(row.get("Applied On"))
                    lag = (app_on.floor("D") - pd.to_datetime(evt_date).floor("D")).days if app_on and evt_date else None

                lag_val = int(lag) if lag is not None and not pd.isna(lag) else 0
                is_comp = (lag_val <= allowed_post)

                rule_codes.append(rule_code)
                rule_descs.append(rule_desc)
                req_notices.append(None)
                allowed_posts.append(allowed_post)
                periods.append(period)

                if is_comp:
                    bench_compliants.append(True)
                    policy_compliants.append(True if is_post_policy else None)
                    statuses.append("COMPLIANT" if is_post_policy else "PRE_POLICY_BENCHMARK_PASS")
                    reasons.append("NONE")
                else:
                    bench_compliants.append(False)
                    policy_compliants.append(False if is_post_policy else None)
                    statuses.append("NON_COMPLIANT" if is_post_policy else "PRE_POLICY_BENCHMARK_FAIL")
                    reasons.append("LATE_APPLICATION")

        # Case C: Unapplicable Event (Present, Absent, Week Off, Holiday, etc.)
        else:
            rule_codes.append("NOT_APPLICABLE")
            rule_descs.append(POLICY_RULES["NOT_APPLICABLE"])
            req_notices.append(None)
            allowed_posts.append(None)
            periods.append(period)
            bench_compliants.append(None)
            policy_compliants.append(None)
            statuses.append("NOT_APPLICABLE")
            reasons.append("NOT_APPLICABLE")

    df["policy_rule_code"] = rule_codes
    df["policy_rule_description"] = rule_descs
    df["required_notice_days"] = req_notices
    df["allowed_post_days"] = allowed_posts
    df["policy_period"] = periods
    df["benchmark_compliant"] = pd.Series(bench_compliants, dtype="boolean")
    df["policy_compliant"] = pd.Series(policy_compliants, dtype="boolean")
    df["compliance_status"] = statuses
    df["non_compliance_reason"] = reasons

    return df, evaluated_req_list
