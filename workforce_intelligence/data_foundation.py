"""
workforce_intelligence/data_foundation.py
──────────────────────────────────────────
Canonical Workforce Data Model and Foundation Layer for Transformers 2.0.

Provides UI-independent, strongly typed canonical entities and aggregation logic:
- Employee (stable identity, organizational attributes, historical tracking)
- AttendanceRecord (source-level event preservation, provenance, swipe hours)
- WorkforceRequest (extensible Leave and WFH request reconstruction with provenance)
- EmployeeDayFact (daily analytical facts, exception classifications, daily quantities)
- OrganizationalStructure (hierarchy and membership lookups without inference)
- CanonicalWorkforceData (unified in-memory container with non-destructive transformation)

Known Limitation & Shared DataFrame Contract:
The canonical foundation shares the active analytical snapshot's DataFrame for memory
efficiency. Direct raw_dataframe access follows a read-only usage contract but is not
technically immutable. Consumers requiring modifications must use get_raw_dataframe(copy=True).
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

import numpy as np
import pandas as pd

from workforce_intelligence.normalization import (
    normalize_attendance_category,
    normalize_employee_number,
    normalize_quantity,
    normalize_text,
    parse_time_to_minutes,
)
from workforce_intelligence.schema import (
    CANONICAL_COLUMNS,
    resolve_canonical_column,
)
import time_series_analysis as tsa


# ─────────────────────────────────────────────────────────────────────────────
# Canonical Entity Definitions
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Employee:
    """
    Canonical Employee identity and organizational profile.
    Uses employee_id as primary stable identifier. Employees sharing identical
    names are kept strictly separate if employee_id differs.
    """
    employee_id: str
    employee_name: Optional[str] = None
    business_unit: Optional[str] = None
    department: Optional[str] = None
    sub_department: Optional[str] = None
    location: Optional[str] = None
    reporting_manager: Optional[str] = None
    job_title: Optional[str] = None
    effective_business_unit: Optional[str] = None
    historical_attributes: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AttendanceRecord:
    """
    Source-level workforce event record preserving exact file provenance.
    """
    record_id: str
    source_row_number: int
    source_file_name: Optional[str] = None
    employee_id: str = ""
    employee_name: Optional[str] = None
    business_unit: Optional[str] = None
    department: Optional[str] = None
    reporting_manager: Optional[str] = None
    date: Optional[date] = None
    attendance_status: Optional[str] = None
    attendance_type: Optional[str] = None
    attendance_category: str = "Unknown"
    leave_name: Optional[str] = None
    in_time: Optional[str] = None
    out_time: Optional[str] = None
    in_time_minutes: Optional[int] = None
    out_time_minutes: Optional[int] = None
    working_hours: Optional[float] = None
    quantity: Optional[float] = None
    applied_by: Optional[str] = None
    applied_on: Optional[date] = None
    approved_by: Optional[str] = None
    approved_on: Optional[date] = None
    approval_status: Optional[str] = None
    source_request_id: Optional[str] = None
    is_attendance_exception: bool = False
    attendance_exception_types: List[str] = field(default_factory=list)
    include_in_analysis: bool = True
    analysis_exclusion_reason: str = "NONE"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.date:
            d["date"] = self.date.isoformat()
        if self.applied_on:
            d["applied_on"] = self.applied_on.isoformat()
        if self.approved_on:
            d["approved_on"] = self.approved_on.isoformat()
        return d


@dataclass
class WorkforceRequest:
    """
    Logical leave or WFH request spanning one or more consecutive days.
    Preserves exact provenance back to source-level AttendanceRecord IDs.
    Distinguishes inferred groupings from explicit source request identifiers.
    """
    request_id: str
    employee_id: str
    request_type: str  # "LEAVE" or "WFH"
    leave_name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    request_dates: List[date] = field(default_factory=list)
    applied_on: Optional[date] = None
    approved_on: Optional[date] = None
    applied_by: Optional[str] = None
    approved_by: Optional[str] = None
    approval_status: Optional[str] = None
    total_quantity: Optional[float] = None
    application_lag_days: Optional[int] = None
    approval_turnaround_days: Optional[int] = None
    source_request_id: Optional[str] = None
    is_inferred: bool = False
    record_ids: List[str] = field(default_factory=list)
    source_row_numbers: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.start_date:
            d["start_date"] = self.start_date.isoformat()
        if self.end_date:
            d["end_date"] = self.end_date.isoformat()
        if self.request_dates:
            d["request_dates"] = [d_val.isoformat() for d_val in self.request_dates]
        if self.applied_on:
            d["applied_on"] = self.applied_on.isoformat()
        if self.approved_on:
            d["approved_on"] = self.approved_on.isoformat()
        return d


@dataclass
class EmployeeDayFact:
    """
    Daily analytical reality for an employee on a specific date.
    Consolidates intra-day attendance events while preserving links to source records.
    Historical attributes (business_unit, department, manager) are derived from
    the specific date's records rather than projected from a global latest profile.
    """
    employee_id: str
    date: date
    business_unit: Optional[str] = None
    raw_business_unit: Optional[str] = None
    effective_business_unit: Optional[str] = None
    department: Optional[str] = None
    sub_department: Optional[str] = None
    location: Optional[str] = None
    reporting_manager: Optional[str] = None
    record_count: int = 0
    raw_record_count: int = 0
    daily_total_quantity: Optional[float] = None
    raw_daily_total_quantity: Optional[float] = None
    has_present: bool = False
    has_leave: bool = False
    has_wfh: bool = False
    has_absent: bool = False
    has_missing_swipe: bool = False
    has_regularization: bool = False
    has_week_off: bool = False
    has_holiday: bool = False
    has_on_duty: bool = False
    is_attendance_exception: bool = False
    attendance_exception_types: List[str] = field(default_factory=list)
    is_eligible_attendance_day: bool = False
    working_hours: Optional[float] = None
    in_time_minutes: Optional[int] = None
    out_time_minutes: Optional[int] = None
    record_ids: List[str] = field(default_factory=list)
    quality_status: str = "VALID"  # "VALID", "WARNING", "CRITICAL"
    is_evaluable: bool = True
    has_conflict: bool = False
    conflict_reasons: List[str] = field(default_factory=list)
    dq_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d


class OrganizationalStructure:
    """
    Hierarchy and grouping lookups derived strictly from active dataset attributes.
    Does not guess or hallucinate missing relationships.
    """
    def __init__(self, employees: Dict[str, Employee]):
        self._employees = employees
        self._bu_map: Dict[str, List[str]] = {}
        self._dept_map: Dict[str, List[str]] = {}
        self._rm_map: Dict[str, List[str]] = {}
        self._build_indexes()

    def _build_indexes(self):
        for emp_id, emp in self._employees.items():
            # Business Unit
            bu = emp.effective_business_unit or emp.business_unit
            if bu:
                self._bu_map.setdefault(bu, []).append(emp_id)

            # Department
            dept = emp.department
            if dept:
                self._dept_map.setdefault(dept, []).append(emp_id)

            # Manager
            rm = emp.reporting_manager
            if rm:
                self._rm_map.setdefault(rm, []).append(emp_id)

    def get_manager(self, employee_id: str) -> Optional[str]:
        emp = self._employees.get(employee_id)
        return emp.reporting_manager if emp else None

    def get_direct_reports(self, manager_name_or_id: str) -> List[str]:
        return self._rm_map.get(str(manager_name_or_id).strip(), [])

    def get_department_members(self, department: str) -> List[str]:
        return self._dept_map.get(str(department).strip(), [])

    def get_business_unit_members(self, business_unit: str) -> List[str]:
        return self._bu_map.get(str(business_unit).strip(), [])

    def get_all_business_units(self) -> List[str]:
        return sorted(self._bu_map.keys())

    def get_all_departments(self) -> List[str]:
        return sorted(self._dept_map.keys())

    def get_all_managers(self) -> List[str]:
        return sorted(self._rm_map.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Canonical Data Foundation Container
# ─────────────────────────────────────────────────────────────────────────────

class CanonicalWorkforceData:
    """
    Unified workforce data container holding typed entities, lookups, and provenance.
    """
    def __init__(
        self,
        employees: Dict[str, Employee],
        attendance_records: List[AttendanceRecord],
        requests: List[WorkforceRequest],
        employee_day_facts: List[EmployeeDayFact],
        org_structure: OrganizationalStructure,
        raw_dataframe: pd.DataFrame,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.employees = employees
        self.attendance_records = attendance_records
        self.requests = requests
        self.employee_day_facts = employee_day_facts
        self.org_structure = org_structure
        self._raw_dataframe = raw_dataframe
        self.metadata = metadata or {}

        # Fast lookup indexes
        self._emp_records: Dict[str, List[AttendanceRecord]] = {}
        self._emp_facts: Dict[str, List[EmployeeDayFact]] = {}
        self._fact_map: Dict[Tuple[str, date], EmployeeDayFact] = {}
        self._emp_requests: Dict[str, List[WorkforceRequest]] = {}
        self._build_internal_indexes()

    @property
    def raw_dataframe(self) -> pd.DataFrame:
        """
        Direct reference to the underlying dataset DataFrame held by AnalyticalSnapshot.

        Ownership & Mutation Rules:
        - The underlying DataFrame is owned by the active AnalyticalSnapshot.
        - CanonicalWorkforceData holds this reference to prevent redundant in-memory copying.
        - Read-Only Contract: Callers must treat raw_dataframe as read-only. Modifying
          this DataFrame in place will mutate the snapshot's fact_df.
        - If in-place mutations or column alterations are required, the caller must
          explicitly create a copy via raw_dataframe.copy() or get_raw_dataframe(copy=True).
        """
        return self._raw_dataframe

    def get_raw_dataframe(self, copy: bool = False) -> pd.DataFrame:
        """
        Retrieve the raw DataFrame with optional defensive copying.
        """
        if copy:
            return self._raw_dataframe.copy(deep=True)
        return self._raw_dataframe

    def _build_internal_indexes(self):
        for rec in self.attendance_records:
            self._emp_records.setdefault(rec.employee_id, []).append(rec)

        for fact in self.employee_day_facts:
            self._emp_facts.setdefault(fact.employee_id, []).append(fact)
            self._fact_map[(fact.employee_id, fact.date)] = fact

        for req in self.requests:
            self._emp_requests.setdefault(req.employee_id, []).append(req)

    def get_employee(self, employee_id: str) -> Optional[Employee]:
        return self.employees.get(str(employee_id).strip())

    def get_records_for_employee(self, employee_id: str) -> List[AttendanceRecord]:
        return self._emp_records.get(str(employee_id).strip(), [])

    def get_facts_for_employee(self, employee_id: str) -> List[EmployeeDayFact]:
        return self._emp_facts.get(str(employee_id).strip(), [])

    def get_fact(self, employee_id: str, fact_date: date) -> Optional[EmployeeDayFact]:
        return self._fact_map.get((str(employee_id).strip(), fact_date))

    def get_requests_for_employee(self, employee_id: str) -> List[WorkforceRequest]:
        return self._emp_requests.get(str(employee_id).strip(), [])

    # ─────────────────────────────────────────────────────────────────────────
    # Factory: Non-destructive Transformation from DataFrame
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    def from_dataframe(
        cls,
        df: pd.DataFrame,
        source_file_name: Optional[str] = None,
        source_file_index: Optional[int] = None,
    ) -> "CanonicalWorkforceData":
        """
        Transform an existing attendance or time-series DataFrame into canonical structures.
        Does NOT modify the incoming DataFrame in place.
        """
        # We read directly from df without creating a second full duplicate in memory
        work_df = df

        # 2. Extract column mappings
        col_map: Dict[str, str] = {}
        for canon_key in tsa.ALIASES.keys():
            matched = tsa.find_column(work_df, canon_key)
            if matched:
                col_map[canon_key] = matched

        # Also support schema CANONICAL_COLUMNS and request ID aliases
        request_id_candidates = ["request id", "request_id", "application id", "application no", "application number", "req id", "req_id", "leave id"]
        for c in work_df.columns:
            c_str = str(c).strip()
            c_lower = c_str.lower()
            res = resolve_canonical_column(c_str)
            if res == "Employee Number" and "employee_number" not in col_map:
                col_map["employee_number"] = c
            elif res == "Employee Name" and "employee_name" not in col_map:
                col_map["employee_name"] = c
            elif res == "Business Unit" and "business_unit" not in col_map:
                col_map["business_unit"] = c
            elif res == "Department" and "department" not in col_map:
                col_map["department"] = c
            elif res == "Sub Department" and "sub_department" not in col_map:
                col_map["sub_department"] = c
            elif res == "Reporting Manager" and "reporting_manager" not in col_map:
                col_map["reporting_manager"] = c
            elif res == "Date" and "date" not in col_map:
                col_map["date"] = c
            elif res == "Status" and "status" not in col_map:
                col_map["status"] = c
            elif res == "Attendance Type" and "attendance_type" not in col_map:
                col_map["attendance_type"] = c
            elif res == "Leave Name" and "leave_name" not in col_map:
                col_map["leave_name"] = c
            elif res == "Quantity" and "quantity" not in col_map:
                col_map["quantity"] = c
            elif res == "In Time" and "in_time" not in col_map:
                col_map["in_time"] = c
            elif res == "Out Time" and "out_time" not in col_map:
                col_map["out_time"] = c
            elif res == "Applied By" and "applied_by" not in col_map:
                col_map["applied_by"] = c
            elif res == "Applied On" and "applied_on" not in col_map:
                col_map["applied_on"] = c
            elif res == "Approved By" and "approved_by" not in col_map:
                col_map["approved_by"] = c
            elif res == "Approved On" and "approved_on" not in col_map:
                col_map["approved_on"] = c
            elif res == "Approval Status" and "approval_status" not in col_map:
                col_map["approval_status"] = c

            if "source_request_id" not in col_map:
                if c_lower in request_id_candidates or re.sub(r'[^a-z0-9]', '', c_lower) in ("requestid", "applicationid", "applicationno", "reqid"):
                    col_map["source_request_id"] = c

        # 3. Build AttendanceRecords with duplicate governance
        attendance_records: List[AttendanceRecord] = []
        seen_exact_signatures: Set[Tuple] = set()

        f_name = source_file_name or "dataset"
        f_idx = source_file_index or 1

        records_list = work_df.to_dict(orient="records")
        emp_profiles: Dict[str, Dict[str, Any]] = {}

        for i, row in enumerate(records_list):
            row_num = i + 2  # Physical 1-based row assuming header at row 1
            rec_id = f"f{f_idx:03d}_rec_{i+1:06d}"

            # Employee ID & Name
            raw_emp_id = row.get(col_map["employee_number"]) if "employee_number" in col_map else row.get("_emp_num", "")
            emp_id = normalize_employee_number(raw_emp_id) or f"UNKNOWN_{i+1}"

            raw_emp_name = row.get(col_map["employee_name"]) if "employee_name" in col_map else row.get("_emp_name", None)
            emp_name = normalize_text(raw_emp_name) or emp_id

            # Date
            raw_dt = row.get(col_map["date"]) if "date" in col_map else row.get("_date", None)
            dt = tsa.parse_date_value(raw_dt)

            # Org Attributes
            bu = normalize_text(row.get(col_map["business_unit"])) if "business_unit" in col_map else normalize_text(row.get("_bu", None))
            dept = normalize_text(row.get(col_map["department"])) if "department" in col_map else normalize_text(row.get("_dept", None))
            sub_dept = normalize_text(row.get(col_map["sub_department"])) if "sub_department" in col_map else None
            loc = normalize_text(row.get("Location", None))
            rm = normalize_text(row.get(col_map["reporting_manager"])) if "reporting_manager" in col_map else normalize_text(row.get("_rm", None))
            job_title = normalize_text(row.get("Job Title", None))

            # Store / update employee profile
            if emp_id not in emp_profiles:
                emp_profiles[emp_id] = {
                    "employee_id": emp_id,
                    "employee_name": emp_name,
                    "business_unit": bu,
                    "department": dept,
                    "sub_department": sub_dept,
                    "location": loc,
                    "reporting_manager": rm,
                    "job_title": job_title,
                    "historical_attributes": [],
                }
            else:
                # Track historical attribute changes across dates
                curr = emp_profiles[emp_id]
                diffs = {}
                if bu and bu != curr["business_unit"]:
                    diffs["business_unit"] = bu
                if dept and dept != curr["department"]:
                    diffs["department"] = dept
                if rm and rm != curr["reporting_manager"]:
                    diffs["reporting_manager"] = rm
                if diffs:
                    diffs["date"] = dt.isoformat() if dt else None
                    diffs["source_row_number"] = row_num
                    curr["historical_attributes"].append(diffs)

            # Status and category
            raw_status = row.get(col_map["status"]) if "status" in col_map else row.get("_status", None)
            raw_att_type = row.get(col_map["attendance_type"]) if "attendance_type" in col_map else row.get("_att_type", None)
            status_clean = normalize_text(raw_status)
            att_type_clean = normalize_text(raw_att_type)
            cat = normalize_attendance_category(status_clean, att_type_clean)

            # Quantity (preserve float 0.5, 1.0, do not coerce missing to 0)
            raw_qty = row.get(col_map["quantity"]) if "quantity" in col_map else row.get("Quantity", None)
            qty = normalize_quantity(raw_qty)

            # Swipes and working hours
            raw_in = row.get(col_map["in_time"]) if "in_time" in col_map else row.get("_in_mins", None)
            raw_out = row.get(col_map["out_time"]) if "out_time" in col_map else row.get("_out_mins", None)

            # In / Out string vs minutes
            if isinstance(raw_in, (int, float)) and not math.isnan(raw_in):
                in_mins = int(raw_in)
                in_str = tsa.minutes_to_time_str(in_mins, use_12hr=True)
            else:
                in_str = normalize_text(raw_in)
                in_mins = parse_time_to_minutes(in_str)

            if isinstance(raw_out, (int, float)) and not math.isnan(raw_out):
                out_mins = int(raw_out)
                out_str = tsa.minutes_to_time_str(out_mins, use_12hr=True)
            else:
                out_str = normalize_text(raw_out)
                out_mins = parse_time_to_minutes(out_str)

            # Working hours calculation: only for Present and Missing Swipes with both valid punches
            work_hrs = None
            if in_mins is not None and out_mins is not None:
                is_eligible_swipe = cat in ("Present", "Missing Swipes")
                if is_eligible_swipe:
                    diff_m = out_mins - in_mins
                    if diff_m < 0:
                        diff_m += 1440
                    work_hrs = round(diff_m / 60.0, 2)

            # Leave and approval fields
            raw_leave_name = row.get(col_map["leave_name"]) if "leave_name" in col_map else row.get("_leave_name", None)
            leave_name = normalize_text(raw_leave_name)

            applied_by = normalize_text(row.get(col_map["applied_by"])) if "applied_by" in col_map else normalize_text(row.get("_applied_by", None))
            approved_by = normalize_text(row.get(col_map["approved_by"])) if "approved_by" in col_map else normalize_text(row.get("_approved_by", None))

            raw_app_on = row.get(col_map["applied_on"]) if "applied_on" in col_map else row.get("_applied_on", None)
            applied_on = tsa.parse_date_value(raw_app_on)

            raw_appr_on = row.get(col_map["approved_on"]) if "approved_on" in col_map else row.get("_approved_on", None)
            approved_on = tsa.parse_date_value(raw_appr_on)

            raw_appr_st = row.get(col_map["approval_status"]) if "approval_status" in col_map else row.get("Approval Status", None)
            appr_st = normalize_text(raw_appr_st)

            # Explicit request identifier from source, if present
            raw_src_req_id = row.get(col_map["source_request_id"]) if "source_request_id" in col_map else None
            src_req_id = normalize_text(raw_src_req_id)

            # Exception classifications
            is_exc = cat in ("Absent", "Missing Swipes", "Attendance Regularized")
            exc_types = []
            if cat == "Absent":
                exc_types.append("ABSENT")
            elif cat == "Missing Swipes":
                exc_types.append("MISSING_SWIPE")
            elif cat == "Attendance Regularized":
                exc_types.append("ATTENDANCE_REGULARIZED")

            # If date is missing, exclude from daily analysis
            if dt is None:
                inc_analysis = False
                excl_reason = "MISSING_DATE"
            else:
                # Duplicate governance signature
                sig = (
                    emp_id,
                    dt.isoformat() if dt else None,
                    status_clean,
                    att_type_clean,
                    leave_name,
                    qty,
                    in_str,
                    out_str,
                    applied_on.isoformat() if applied_on else None,
                    approved_on.isoformat() if approved_on else None,
                    src_req_id,
                )

                if sig in seen_exact_signatures:
                    inc_analysis = False
                    excl_reason = "EXACT_DUPLICATE"
                else:
                    seen_exact_signatures.add(sig)
                    inc_analysis = True
                    excl_reason = "NONE"

            rec = AttendanceRecord(
                record_id=rec_id,
                source_row_number=row_num,
                source_file_name=f_name,
                employee_id=emp_id,
                employee_name=emp_name,
                business_unit=bu,
                department=dept,
                reporting_manager=rm,
                date=dt,
                attendance_status=status_clean,
                attendance_type=att_type_clean,
                attendance_category=cat,
                leave_name=leave_name,
                in_time=in_str,
                out_time=out_str,
                in_time_minutes=in_mins,
                out_time_minutes=out_mins,
                working_hours=work_hrs,
                quantity=qty,
                applied_by=applied_by,
                applied_on=applied_on,
                approved_by=approved_by,
                approved_on=approved_on,
                approval_status=appr_st,
                source_request_id=src_req_id,
                is_attendance_exception=is_exc,
                attendance_exception_types=exc_types,
                include_in_analysis=inc_analysis,
                analysis_exclusion_reason=excl_reason,
            )
            attendance_records.append(rec)

        # 4. Construct Employee Objects
        employees: Dict[str, Employee] = {}
        for emp_id, prof in emp_profiles.items():
            bu_val = prof["business_unit"]
            dept_val = prof["department"]
            # Lending special business rule: If BU == 'Lending', Department acts as effective BU
            eff_bu = bu_val
            if bu_val and str(bu_val).strip().lower() == "lending" and dept_val:
                eff_bu = dept_val

            employees[emp_id] = Employee(
                employee_id=emp_id,
                employee_name=prof["employee_name"],
                business_unit=bu_val,
                department=dept_val,
                sub_department=prof["sub_department"],
                location=prof["location"],
                reporting_manager=prof["reporting_manager"],
                job_title=prof["job_title"],
                effective_business_unit=eff_bu,
                historical_attributes=prof["historical_attributes"],
            )

        # 5. Build Organizational Structure
        org_struct = OrganizationalStructure(employees)

        # 6. Build WorkforceRequests (Leave and WFH)
        requests: List[WorkforceRequest] = []
        req_counter = 0

        # Separate records by employee
        req_eligible = [
            r for r in attendance_records
            if r.include_in_analysis and (
                r.attendance_category in ("Leave", "Work From Home")
                or (r.leave_name and r.leave_name not in ("-", "", "NA"))
            )
        ]

        # Group by employee first, then reconstruct requests chronologically
        emp_req_records: Dict[str, List[AttendanceRecord]] = {}
        for r in req_eligible:
            emp_req_records.setdefault(r.employee_id, []).append(r)

        for emp_id, emp_recs in emp_req_records.items():
            # Sort chronologically by date
            sorted_recs = sorted(emp_recs, key=lambda x: (x.date or date.min, x.source_row_number))

            # Reconstruct clusters
            current_cluster: List[AttendanceRecord] = []
            clusters: List[List[AttendanceRecord]] = []

            for rec in sorted_recs:
                if not current_cluster:
                    current_cluster = [rec]
                    continue

                prev = current_cluster[-1]

                # Check if this record belongs to the same request:
                # 1. If explicit source_request_id is present on either record, must match exactly
                if rec.source_request_id or prev.source_request_id:
                    same_request = (
                        rec.source_request_id is not None
                        and prev.source_request_id is not None
                        and rec.source_request_id == prev.source_request_id
                    )
                else:
                    # 2. Check metadata match
                    same_type = (rec.attendance_category == prev.attendance_category)
                    same_leave = (rec.leave_name == prev.leave_name)
                    same_applied = (rec.applied_on == prev.applied_on)
                    same_approved = (rec.approved_on == prev.approved_on)
                    same_approver = (rec.approved_by == prev.approved_by)
                    same_status = (rec.approval_status == prev.approval_status)

                    # Consecutive dates condition
                    consecutive_days = False
                    if rec.date and prev.date:
                        diff = (rec.date - prev.date).days
                        consecutive_days = (diff <= 1)

                    # Both applications must share exact application/approval metadata AND be consecutive
                    same_request = (
                        same_type
                        and same_leave
                        and same_applied
                        and same_approved
                        and same_approver
                        and same_status
                        and consecutive_days
                    )

                if same_request:
                    current_cluster.append(rec)
                else:
                    clusters.append(current_cluster)
                    current_cluster = [rec]

            if current_cluster:
                clusters.append(current_cluster)

            # Build WorkforceRequest objects from clusters
            for cluster in clusters:
                req_counter += 1
                first_r = cluster[0]
                req_type = "WFH" if first_r.attendance_category == "Work From Home" else "LEAVE"
                has_explicit_id = bool(first_r.source_request_id)

                req_id = first_r.source_request_id if has_explicit_id else f"req_{req_counter:05d}"
                is_inferred = not has_explicit_id

                dates_with_rec = sorted([r for r in cluster if r.date is not None], key=lambda x: x.date)
                date_list = [r.date for r in dates_with_rec]
                s_date = date_list[0] if date_list else None
                e_date = date_list[-1] if date_list else None

                quantities = [r.quantity for r in cluster if r.quantity is not None]
                tot_qty = round(sum(quantities), 4) if quantities else (float(len(cluster)) if cluster else None)

                app_lag = (s_date - first_r.applied_on).days if (s_date and first_r.applied_on) else None
                appr_turn = (first_r.approved_on - first_r.applied_on).days if (first_r.approved_on and first_r.applied_on) else None

                w_req = WorkforceRequest(
                    request_id=req_id,
                    employee_id=emp_id,
                    request_type=req_type,
                    leave_name=first_r.leave_name,
                    start_date=s_date,
                    end_date=e_date,
                    request_dates=date_list,
                    applied_on=first_r.applied_on,
                    approved_on=first_r.approved_on,
                    applied_by=first_r.applied_by,
                    approved_by=first_r.approved_by,
                    approval_status=first_r.approval_status,
                    total_quantity=tot_qty,
                    application_lag_days=app_lag,
                    approval_turnaround_days=appr_turn,
                    source_request_id=first_r.source_request_id,
                    is_inferred=is_inferred,
                    record_ids=[r.record_id for r in cluster],
                    source_row_numbers=[r.source_row_number for r in cluster],
                )
                requests.append(w_req)

        # 7. Build EmployeeDayFacts with Date-Specific Organizational Attributes & Conflict Detection
        day_facts: List[EmployeeDayFact] = []
        day_groups: Dict[Tuple[str, date], List[AttendanceRecord]] = {}
        missing_date_records = []

        for rec in attendance_records:
            if rec.date:
                day_groups.setdefault((rec.employee_id, rec.date), []).append(rec)
            else:
                missing_date_records.append(rec)

        for (emp_id, d_val), group_recs in day_groups.items():
            included_recs = [r for r in group_recs if r.include_in_analysis]
            eval_recs = included_recs if included_recs else group_recs

            # Organizational attributes derived directly from the date's specific records
            # to guarantee historical precision
            emp_obj = employees.get(emp_id)
            primary_rec = eval_recs[0]

            day_bu = primary_rec.business_unit or (emp_obj.business_unit if emp_obj else None)
            day_dept = primary_rec.department or (emp_obj.department if emp_obj else None)
            day_rm = primary_rec.reporting_manager or (emp_obj.reporting_manager if emp_obj else None)
            sub_dept_val = emp_obj.sub_department if emp_obj else None
            loc_val = emp_obj.location if emp_obj else None

            # Effective Business Unit logic: Lending BU -> Department
            eff_bu = day_bu
            if day_bu and str(day_bu).strip().lower() == "lending" and day_dept:
                eff_bu = day_dept

            cats = {r.attendance_category for r in eval_recs}
            statuses = {str(r.attendance_status).upper() for r in eval_recs if r.attendance_status}

            has_pres = "Present" in cats or "P" in statuses
            has_lv = "Leave" in cats or any(s in ("CL", "SL", "PL", "EL", "ML", "CLSL", "L") for s in statuses)
            has_wfh = "Work From Home" in cats or "WFH" in statuses
            has_abs = "Absent" in cats or "A" in statuses or "AB" in statuses
            has_ms = "Missing Swipes" in cats or any("MS" in s for s in statuses)
            has_reg = "Attendance Regularized" in cats or any("(R)" in s or s in ("AR", "PR") for s in statuses)
            has_wo = "Week Off" in cats or "WO" in statuses or "W/O" in statuses
            has_hol = "Holiday" in cats or "H" in statuses or "PH" in statuses
            has_od = "On Duty" in cats or "OD" in statuses

            # Exceptions
            exc_types = []
            if has_abs:
                exc_types.append("ABSENT")
            if has_ms:
                exc_types.append("MISSING_SWIPE")
            if has_reg:
                exc_types.append("ATTENDANCE_REGULARIZED")
            is_exc = len(exc_types) > 0

            # Eligibility: pure week-off or pure holiday without active work is ineligible
            has_active = has_pres or has_lv or has_wfh or has_abs or has_ms or has_reg or has_od
            is_eligible = bool(has_active)

            # Quantities
            raw_quantities = [r.quantity for r in group_recs if r.quantity is not None]
            raw_qty_sum = round(sum(raw_quantities), 4) if raw_quantities else None

            analytical_quantities = [r.quantity for r in eval_recs if r.quantity is not None]
            analytical_qty_sum = round(sum(analytical_quantities), 4) if analytical_quantities else None

            # Working hours & swipes
            valid_hrs = [r.working_hours for r in eval_recs if r.working_hours is not None and not math.isnan(r.working_hours)]
            day_work_hrs = round(sum(valid_hrs), 2) if valid_hrs else None

            valid_in_mins = [r.in_time_minutes for r in eval_recs if r.in_time_minutes is not None]
            day_in_mins = min(valid_in_mins) if valid_in_mins else None

            valid_out_mins = [r.out_time_minutes for r in eval_recs if r.out_time_minutes is not None]
            day_out_mins = max(valid_out_mins) if valid_out_mins else None

            # Conflict Detection & Data Quality
            dq_reasons = []
            conflict_reasons = []
            has_conflict = False

            if analytical_qty_sum is not None and analytical_qty_sum > 1.0001:
                dq_reasons.append("DAILY_QUANTITY_EXCEEDS_ONE")
                conflict_reasons.append("TOTAL_QUANTITY_EXCEEDS_ONE")
                has_conflict = True

            # Direct status contradictions
            if has_pres and has_abs:
                dq_reasons.append("CONFLICTING_STATUS_PRESENT_AND_ABSENT")
                conflict_reasons.append("PRESENT_AND_ABSENT_COEXIST")
                has_conflict = True

            if has_abs and has_lv:
                dq_reasons.append("CONFLICTING_STATUS_ABSENT_AND_LEAVE")
                conflict_reasons.append("ABSENT_AND_LEAVE_COEXIST")
                has_conflict = True

            if not emp_id or emp_id.startswith("UNKNOWN"):
                dq_reasons.append("MISSING_EMPLOYEE")

            if any(r.analysis_exclusion_reason == "EXACT_DUPLICATE" for r in group_recs):
                dq_reasons.append("DUPLICATE_ROWS_DETECTED")

            if has_conflict or "MISSING_EMPLOYEE" in dq_reasons:
                q_status = "CRITICAL"
                evaluable = False
            elif dq_reasons:
                q_status = "WARNING"
                evaluable = True
            else:
                q_status = "VALID"
                evaluable = True

            fact = EmployeeDayFact(
                employee_id=emp_id,
                date=d_val,
                business_unit=eff_bu,
                raw_business_unit=day_bu,
                effective_business_unit=eff_bu,
                department=day_dept,
                sub_department=sub_dept_val,
                location=loc_val,
                reporting_manager=day_rm,
                record_count=len(eval_recs),
                raw_record_count=len(group_recs),
                daily_total_quantity=analytical_qty_sum,
                raw_daily_total_quantity=raw_qty_sum,
                has_present=has_pres,
                has_leave=has_lv,
                has_wfh=has_wfh,
                has_absent=has_abs,
                has_missing_swipe=has_ms,
                has_regularization=has_reg,
                has_week_off=has_wo,
                has_holiday=has_hol,
                has_on_duty=has_od,
                is_attendance_exception=is_exc,
                attendance_exception_types=exc_types,
                is_eligible_attendance_day=is_eligible,
                working_hours=day_work_hrs,
                in_time_minutes=day_in_mins,
                out_time_minutes=day_out_mins,
                record_ids=[r.record_id for r in group_recs],
                quality_status=q_status,
                is_evaluable=evaluable,
                has_conflict=has_conflict,
                conflict_reasons=conflict_reasons,
                dq_reasons=dq_reasons,
            )
            day_facts.append(fact)

        metadata = {
            "source_file_name": f_name,
            "total_records": len(attendance_records),
            "unique_employees": len(employees),
            "total_requests": len(requests),
            "total_employee_day_facts": len(day_facts),
            "missing_date_records_count": len(missing_date_records),
            "date_range": (
                min((r.date for r in attendance_records if r.date), default=None),
                max((r.date for r in attendance_records if r.date), default=None),
            )
        }

        return cls(
            employees=employees,
            attendance_records=attendance_records,
            requests=requests,
            employee_day_facts=day_facts,
            org_structure=org_struct,
            raw_dataframe=work_df,
            metadata=metadata,
        )
