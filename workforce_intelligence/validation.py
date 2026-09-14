"""
validation.py
─────────────
Schema and row-level data quality validation for workforce intelligence.
Implements required column validation and non-destructive quality flagging.
"""

from typing import List, Optional, Set, Tuple
import pandas as pd

from workforce_intelligence.schema import (
    CANONICAL_COLUMNS,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
)


class ValidationError(ValueError):
    """Raised when critical schema requirements are not met."""
    pass


class MissingRequiredColumnsError(ValidationError):
    """Raised when required canonical columns are absent from the dataset."""
    def __init__(self, missing_columns: List[str]):
        self.missing_columns = missing_columns
        super().__init__(f"Source dataset is missing required column(s): {', '.join(missing_columns)}")


def validate_schema(df: pd.DataFrame) -> Tuple[List[str], List[str]]:
    """
    Validate presence of required columns in the dataframe.
    Returns:
        (missing_required, missing_optional)
    Raises:
        MissingRequiredColumnsError if any required column is missing.
    """
    existing_cols = set(df.columns)
    missing_required = [col for col in REQUIRED_COLUMNS if col not in existing_cols]
    missing_optional = [col for col in OPTIONAL_COLUMNS if col not in existing_cols]

    if missing_required:
        raise MissingRequiredColumnsError(missing_required)

    return missing_required, missing_optional


def apply_quality_flags(
    df: pd.DataFrame, source_columns: Optional[List[str]] = None
) -> pd.DataFrame:
    """
    Attach non-destructive boolean data-quality flags to each row:
    - dq_missing_employee: True if Employee Number or Employee Name is null
    - dq_missing_date: True if Date is null / NaT
    - dq_invalid_date: True if Date was provided in raw form but was unparseable
    - dq_unknown_attendance: True if attendance_category is 'Unknown'
    - dq_exact_duplicate: True if the complete original source row has been repeated identically
    - dq_multiple_records_same_date: True if more than 1 record exists for (Employee Number, Date)
    - dq_daily_quantity_exceeds_one: True if daily_total_quantity > 1.000001
    - dq_missing_quantity: True if Quantity is missing/null
    """
    df = df.copy()

    # 1. dq_missing_employee
    emp_num_null = df["Employee Number"].isna() if "Employee Number" in df.columns else pd.Series(True, index=df.index)
    emp_name_null = df["Employee Name"].isna() if "Employee Name" in df.columns else pd.Series(True, index=df.index)
    df["dq_missing_employee"] = (emp_num_null | emp_name_null).astype(bool)

    # 2. dq_missing_date
    date_null = df["Date"].isna() if "Date" in df.columns else pd.Series(True, index=df.index)
    df["dq_missing_date"] = date_null.astype(bool)

    # 3. dq_invalid_date
    if "_invalid_date_raw" in df.columns:
        df["dq_invalid_date"] = df["_invalid_date_raw"].astype(bool)
        df.drop(columns=["_invalid_date_raw"], inplace=True)
    else:
        df["dq_invalid_date"] = False

    # 4. dq_unknown_attendance
    if "attendance_category" in df.columns:
        df["dq_unknown_attendance"] = (df["attendance_category"] == "Unknown").astype(bool)
    else:
        df["dq_unknown_attendance"] = False

    # 5. dq_exact_duplicate
    # Uses only original source columns (excluding derived fields, record_id, source_row_number, dq flags)
    if source_columns:
        exact_subset = [c for c in source_columns if c in df.columns]
    else:
        exact_subset = [c for c in CANONICAL_COLUMNS if c in df.columns]

    if exact_subset:
        df["dq_exact_duplicate"] = df.duplicated(subset=exact_subset, keep="first").astype(bool)
    else:
        df["dq_exact_duplicate"] = False

    # 6. dq_multiple_records_same_date
    # Identifies groups with count > 1 for (Employee Number, Date)
    df["dq_multiple_records_same_date"] = False
    valid_emp_date = df["Employee Number"].notna() & df["Date"].notna()
    if valid_emp_date.any() and "record_id" in df.columns:
        counts = df[valid_emp_date].groupby(["Employee Number", "Date"])["record_id"].transform("count")
        df.loc[valid_emp_date, "dq_multiple_records_same_date"] = (counts > 1).astype(bool)

    # 7. dq_daily_quantity_exceeds_one
    # Floating point tolerance check: daily_total_quantity > 1.000001
    if "daily_total_quantity" in df.columns:
        df["dq_daily_quantity_exceeds_one"] = df["daily_total_quantity"].apply(
            lambda q: bool(q is not None and pd.notna(q) and float(q) > 1.000001)
        ).astype(bool)
    else:
        df["dq_daily_quantity_exceeds_one"] = False

    # 8. dq_missing_quantity
    if "Quantity" in df.columns:
        df["dq_missing_quantity"] = df["Quantity"].isna().astype(bool)
    else:
        df["dq_missing_quantity"] = True

    return df
