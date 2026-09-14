"""
quality.py
──────────
Data Quality Engine for workforce attendance and leave analytics.
Computes dataset health metrics, missingness counts, integrity diagnostics,
and packages them into a clean DataQualityReport structure.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import pandas as pd


@dataclass
class DataQualityReport:
    """Standardized workforce dataset quality report."""
    total_rows: int = 0
    total_columns: int = 0
    unique_employees: int = 0
    date_min: Optional[str] = None
    date_max: Optional[str] = None

    # Missing dimension counts
    missing_employee_number: int = 0
    missing_employee_name: int = 0
    missing_date: int = 0
    missing_reporting_manager: int = 0

    # Duplication & validation counts
    duplicate_rows: int = 0
    invalid_date_count: int = 0
    invalid_applied_on_count: int = 0
    invalid_approved_on_count: int = 0
    unknown_attendance_category_count: int = 0

    # Overall dataset health
    data_completeness_percentage: float = 0.0
    missing_expected_optional_columns: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return the report as a serializable dictionary."""
        return asdict(self)


def compute_quality_report(
    df: pd.DataFrame,
    meta: Dict[str, Any],
    missing_optional_cols: List[str],
) -> DataQualityReport:
    """
    Compute comprehensive data quality metrics from a normalized workforce dataframe.
    """
    total_rows = len(df)
    total_columns = len(df.columns)
    warnings: List[str] = []

    if total_rows == 0:
        return DataQualityReport(
            total_rows=0,
            total_columns=total_columns,
            missing_expected_optional_columns=missing_optional_cols,
            warnings=["Dataset contains 0 rows."],
        )

    # Unique employees (ignoring nulls)
    emp_series = df["Employee Number"].dropna() if "Employee Number" in df.columns else pd.Series([], dtype=str)
    unique_employees = int(emp_series.nunique())

    # Date range
    date_min: Optional[str] = None
    date_max: Optional[str] = None
    if "Date" in df.columns:
        valid_dates = df["Date"].dropna()
        if not valid_dates.empty:
            date_min = valid_dates.min().strftime("%Y-%m-%d")
            date_max = valid_dates.max().strftime("%Y-%m-%d")

    # Missing counts
    missing_emp_num = int(df["Employee Number"].isna().sum()) if "Employee Number" in df.columns else total_rows
    missing_emp_name = int(df["Employee Name"].isna().sum()) if "Employee Name" in df.columns else total_rows
    missing_date = int(df["Date"].isna().sum()) if "Date" in df.columns else total_rows
    missing_mgr = int(df["Reporting Manager"].isna().sum()) if "Reporting Manager" in df.columns else total_rows

    # Duplicate rows (on canonical key Employee Number + Date if available, or full row)
    if "Employee Number" in df.columns and "Date" in df.columns:
        duplicate_rows = int(df.duplicated(subset=["Employee Number", "Date"]).sum())
    else:
        duplicate_rows = int(df.duplicated().sum())

    # Invalid dates from normalization metadata
    invalid_date_cnt = meta.get("invalid_date_count", 0)
    invalid_applied_on_cnt = meta.get("invalid_applied_on_count", 0)
    invalid_approved_on_cnt = meta.get("invalid_approved_on_count", 0)

    # Unknown attendance category
    unknown_attendance_cnt = int(
        (df["attendance_category"] == "Unknown").sum()
    ) if "attendance_category" in df.columns else 0

    # Completeness percentage across all columns
    total_cells = total_rows * total_columns
    null_cells = int(df.isna().sum().sum())
    completeness = round(((total_cells - null_cells) / total_cells) * 100.0, 2) if total_cells > 0 else 0.0

    # Formulate warnings
    if missing_emp_num > 0:
        warnings.append(f"{missing_emp_num} row(s) missing Employee Number.")
    if missing_date > 0:
        warnings.append(f"{missing_date} row(s) missing Event Date.")
    if invalid_date_cnt > 0:
        warnings.append(f"{invalid_date_cnt} row(s) have unparseable Event Dates.")
    if duplicate_rows > 0:
        warnings.append(f"{duplicate_rows} duplicate record(s) detected.")
    if unknown_attendance_cnt > 0:
        warnings.append(f"{unknown_attendance_cnt} record(s) categorized as Unknown attendance.")
    if missing_optional_cols:
        warnings.append(f"{len(missing_optional_cols)} expected optional column(s) not in source file.")

    return DataQualityReport(
        total_rows=total_rows,
        total_columns=total_columns,
        unique_employees=unique_employees,
        date_min=date_min,
        date_max=date_max,
        missing_employee_number=missing_emp_num,
        missing_employee_name=missing_emp_name,
        missing_date=missing_date,
        missing_reporting_manager=missing_mgr,
        duplicate_rows=duplicate_rows,
        invalid_date_count=invalid_date_cnt,
        invalid_applied_on_count=invalid_applied_on_cnt,
        invalid_approved_on_count=invalid_approved_on_cnt,
        unknown_attendance_category_count=unknown_attendance_cnt,
        data_completeness_percentage=completeness,
        missing_expected_optional_columns=missing_optional_cols,
        warnings=warnings,
    )
