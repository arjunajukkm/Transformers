"""
quality.py
──────────
Data Quality Engine for workforce attendance and leave analytics.
Computes dataset health metrics, missingness counts, exact duplication,
same-day quantity validations, and structured data-quality findings.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import pandas as pd

from workforce_intelligence.schema import CANONICAL_COLUMNS, CORE_COLUMNS


@dataclass
class QualityFinding:
    """Structured data-quality finding with severity and category code."""
    severity: str  # "INFO", "WARNING", "CRITICAL"
    code: str      # Machine-readable code e.g. "DAILY_QUANTITY_EXCEEDS_ONE"
    count: int
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DataQualityReport:
    """Standardized workforce dataset quality report."""
    total_rows: int = 0
    total_columns: int = 0
    unique_employees: int = 0
    date_min: Optional[str] = None
    date_max: Optional[str] = None

    # Completeness metrics
    core_data_completeness_percentage: float = 0.0
    full_data_completeness_percentage: float = 0.0

    # Duplication & same-day distribution
    exact_duplicate_rows: int = 0
    cross_file_exact_duplicate_rows: int = 0
    employee_date_multiple_record_groups: int = 0
    daily_quantity_exceeds_one_groups: int = 0
    daily_quantity_exceeds_one_rows: int = 0
    max_daily_quantity: Optional[float] = None

    # Missing dimension counts
    missing_employee_number: int = 0
    missing_employee_name: int = 0
    missing_date: int = 0
    missing_reporting_manager: int = 0
    missing_quantity_count: int = 0

    # Integrity counts
    invalid_date_count: int = 0
    invalid_applied_on_count: int = 0
    invalid_approved_on_count: int = 0
    unknown_attendance_category_count: int = 0

    # Source files summary
    source_files: List[Dict[str, Any]] = field(default_factory=list)

    # Diagnostics & findings
    missing_expected_optional_columns: List[str] = field(default_factory=list)
    quality_findings: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Backward compatibility aliases
    data_completeness_percentage: float = 0.0
    duplicate_rows: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Return the report as a serializable dictionary."""
        return asdict(self)


def compute_quality_report(
    df: pd.DataFrame,
    meta: Dict[str, Any],
    missing_optional_cols: List[str],
    source_files: Optional[List[Dict[str, Any]]] = None,
) -> DataQualityReport:
    """
    Compute comprehensive data quality metrics and structured findings
    from a normalized workforce dataframe.
    """
    total_rows = len(df)
    total_columns = len(df.columns)

    if total_rows == 0:
        empty_finding = QualityFinding(
            severity="WARNING",
            code="EMPTY_DATASET",
            count=0,
            message="Dataset contains 0 rows.",
        )
        return DataQualityReport(
            total_rows=0,
            total_columns=total_columns,
            missing_expected_optional_columns=missing_optional_cols,
            quality_findings=[empty_finding.to_dict()],
            warnings=["Dataset contains 0 rows."],
            source_files=source_files or [],
        )

    # 1. Unique employees
    emp_series = df["Employee Number"].dropna() if "Employee Number" in df.columns else pd.Series([], dtype=str)
    unique_employees = int(emp_series.nunique())

    # 2. Date range
    date_min: Optional[str] = None
    date_max: Optional[str] = None
    if "Date" in df.columns:
        valid_dates = df["Date"].dropna()
        if not valid_dates.empty:
            date_min = valid_dates.min().strftime("%Y-%m-%d")
            date_max = valid_dates.max().strftime("%Y-%m-%d")

    # 3. Missing dimension counts
    missing_emp_num = int(df["Employee Number"].isna().sum()) if "Employee Number" in df.columns else total_rows
    missing_emp_name = int(df["Employee Name"].isna().sum()) if "Employee Name" in df.columns else total_rows
    missing_date = int(df["Date"].isna().sum()) if "Date" in df.columns else total_rows
    missing_mgr = int(df["Reporting Manager"].isna().sum()) if "Reporting Manager" in df.columns else total_rows
    missing_qty = int(df["Quantity"].isna().sum()) if "Quantity" in df.columns else total_rows

    # 4. Exact duplicate rows
    exact_duplicate_rows = int(df["dq_exact_duplicate"].sum()) if "dq_exact_duplicate" in df.columns else 0
    cross_file_exact_duplicate_rows = int(df["dq_cross_file_exact_duplicate"].sum()) if "dq_cross_file_exact_duplicate" in df.columns else 0

    # 5. Multiple records on same (Employee Number, Date)
    employee_date_multiple_record_groups = 0
    valid_emp_date = df["Employee Number"].notna() & df["Date"].notna() if ("Employee Number" in df.columns and "Date" in df.columns) else pd.Series(False, index=df.index)
    if valid_emp_date.any():
        group_sizes = df[valid_emp_date].groupby(["Employee Number", "Date"]).size()
        employee_date_multiple_record_groups = int((group_sizes > 1).sum())

    # 6. Daily quantity exceeds 1.000001
    daily_quantity_exceeds_one_rows = int(df["dq_daily_quantity_exceeds_one"].sum()) if "dq_daily_quantity_exceeds_one" in df.columns else 0
    daily_quantity_exceeds_one_groups = 0
    if valid_emp_date.any() and "daily_total_quantity" in df.columns:
        # distinct groups with quantity > 1.000001
        exceed_mask = df["daily_total_quantity"].apply(lambda q: bool(q is not None and pd.notna(q) and float(q) > 1.000001))
        if exceed_mask.any():
            daily_quantity_exceeds_one_groups = int(df[exceed_mask].groupby(["Employee Number", "Date"]).ngroups)

    # Max daily quantity
    max_daily_qty: Optional[float] = None
    if "daily_total_quantity" in df.columns:
        valid_daily_qty = df["daily_total_quantity"].dropna()
        if not valid_daily_qty.empty:
            max_daily_qty = round(float(valid_daily_qty.max()), 4)

    # 7. Invalid dates from metadata
    invalid_date_cnt = meta.get("invalid_date_count", 0)
    invalid_applied_on_cnt = meta.get("invalid_applied_on_count", 0)
    invalid_approved_on_cnt = meta.get("invalid_approved_on_count", 0)

    # 8. Unknown attendance category count
    unknown_attendance_cnt = int(
        (df["attendance_category"] == "Unknown").sum()
    ) if "attendance_category" in df.columns else 0

    # 9. Completeness Measures
    # A. Core Completeness: Employee Number, Employee Name, Date, Status, Attendance Type
    core_present = [c for c in CORE_COLUMNS if c in df.columns]
    total_core_cells = total_rows * len(core_present)
    filled_core_cells = int(df[core_present].notna().sum().sum())
    core_completeness = round((filled_core_cells / total_core_cells) * 100.0, 2) if total_core_cells > 0 else 0.0

    # B. Full Completeness: Expected source columns that actually exist in the dataset
    expected_existing_cols = [c for c in CANONICAL_COLUMNS if c in df.columns and c not in missing_optional_cols]
    total_full_cells = total_rows * len(expected_existing_cols)
    filled_full_cells = int(df[expected_existing_cols].notna().sum().sum())
    full_completeness = round((filled_full_cells / total_full_cells) * 100.0, 2) if total_full_cells > 0 else 0.0

    # 10. Structured Quality Findings
    findings: List[QualityFinding] = []

    # CRITICAL Findings
    if daily_quantity_exceeds_one_groups > 0:
        findings.append(QualityFinding(
            severity="CRITICAL",
            code="DAILY_QUANTITY_EXCEEDS_ONE",
            count=daily_quantity_exceeds_one_groups,
            message=f"{daily_quantity_exceeds_one_groups} employee-date group(s) ({daily_quantity_exceeds_one_rows} rows) have total Quantity greater than 1.0 (max: {max_daily_qty}).",
        ))
    if missing_emp_num > 0:
        findings.append(QualityFinding(
            severity="CRITICAL",
            code="MISSING_EMPLOYEE_NUMBER",
            count=missing_emp_num,
            message=f"{missing_emp_num} row(s) missing mandatory Employee Number.",
        ))
    if missing_date > 0:
        findings.append(QualityFinding(
            severity="CRITICAL",
            code="MISSING_DATE",
            count=missing_date,
            message=f"{missing_date} row(s) missing mandatory Event Date.",
        ))
    if invalid_date_cnt > 0:
        findings.append(QualityFinding(
            severity="CRITICAL",
            code="INVALID_DATE",
            count=invalid_date_cnt,
            message=f"{invalid_date_cnt} row(s) have unparseable Event Dates.",
        ))

    # WARNING Findings
    if exact_duplicate_rows > 0:
        findings.append(QualityFinding(
            severity="WARNING",
            code="EXACT_DUPLICATE",
            count=exact_duplicate_rows,
            message=f"{exact_duplicate_rows} exact duplicate row(s) detected in source dataset.",
        ))
    if cross_file_exact_duplicate_rows > 0:
        findings.append(QualityFinding(
            severity="WARNING",
            code="CROSS_FILE_EXACT_DUPLICATE",
            count=cross_file_exact_duplicate_rows,
            message=f"{cross_file_exact_duplicate_rows} exact duplicate row(s) detected across uploaded source files.",
        ))
    if missing_qty > 0:
        findings.append(QualityFinding(
            severity="WARNING",
            code="MISSING_QUANTITY",
            count=missing_qty,
            message=f"{missing_qty} row(s) have missing Quantity.",
        ))
    if unknown_attendance_cnt > 0:
        findings.append(QualityFinding(
            severity="WARNING",
            code="UNKNOWN_ATTENDANCE_CATEGORY",
            count=unknown_attendance_cnt,
            message=f"{unknown_attendance_cnt} record(s) categorized as Unknown attendance.",
        ))
    if invalid_applied_on_cnt > 0:
        findings.append(QualityFinding(
            severity="WARNING",
            code="INVALID_APPLIED_ON",
            count=invalid_applied_on_cnt,
            message=f"{invalid_applied_on_cnt} row(s) have unparseable Applied On timestamps.",
        ))
    if invalid_approved_on_cnt > 0:
        findings.append(QualityFinding(
            severity="WARNING",
            code="INVALID_APPROVED_ON",
            count=invalid_approved_on_cnt,
            message=f"{invalid_approved_on_cnt} row(s) have unparseable Approved On timestamps.",
        ))

    # INFO Findings
    if employee_date_multiple_record_groups > 0:
        findings.append(QualityFinding(
            severity="INFO",
            code="MULTIPLE_RECORDS_SAME_DATE",
            count=employee_date_multiple_record_groups,
            message=f"{employee_date_multiple_record_groups} employee-date group(s) have multiple valid records (e.g. half-day combinations).",
        ))
    if missing_optional_cols:
        findings.append(QualityFinding(
            severity="INFO",
            code="MISSING_OPTIONAL_COLUMNS",
            count=len(missing_optional_cols),
            message=f"{len(missing_optional_cols)} expected optional column(s) not in source file.",
        ))

    # Warnings list for backward compatibility (CRITICAL and WARNING messages)
    warnings = [f.message for f in findings if f.severity in ("WARNING", "CRITICAL")]

    return DataQualityReport(
        total_rows=total_rows,
        total_columns=total_columns,
        unique_employees=unique_employees,
        date_min=date_min,
        date_max=date_max,
        core_data_completeness_percentage=core_completeness,
        full_data_completeness_percentage=full_completeness,
        exact_duplicate_rows=exact_duplicate_rows,
        cross_file_exact_duplicate_rows=cross_file_exact_duplicate_rows,
        employee_date_multiple_record_groups=employee_date_multiple_record_groups,
        daily_quantity_exceeds_one_groups=daily_quantity_exceeds_one_groups,
        daily_quantity_exceeds_one_rows=daily_quantity_exceeds_one_rows,
        max_daily_quantity=max_daily_qty,
        missing_employee_number=missing_emp_num,
        missing_employee_name=missing_emp_name,
        missing_date=missing_date,
        missing_reporting_manager=missing_mgr,
        missing_quantity_count=missing_qty,
        missing_expected_optional_columns=missing_optional_cols,
        invalid_date_count=invalid_date_cnt,
        invalid_applied_on_count=invalid_applied_on_cnt,
        invalid_approved_on_count=invalid_approved_on_cnt,
        unknown_attendance_category_count=unknown_attendance_cnt,
        source_files=source_files or [],
        quality_findings=[f.to_dict() for f in findings],
        warnings=warnings,
        data_completeness_percentage=full_completeness,
        duplicate_rows=exact_duplicate_rows,
    )
