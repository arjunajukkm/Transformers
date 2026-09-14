"""
validation.py
─────────────
Schema and row-level data quality validation for workforce intelligence.
Implements required column validation and non-destructive quality flagging.
"""

from typing import List, Set, Tuple
import pandas as pd

from workforce_intelligence.schema import CANONICAL_COLUMNS, OPTIONAL_COLUMNS, REQUIRED_COLUMNS


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


def apply_quality_flags(df: pd.DataFrame) -> pd.DataFrame:
    """
    Attach non-destructive boolean data-quality flags to each row:
    - dq_missing_employee: True if Employee Number or Employee Name is null
    - dq_missing_date: True if Date is null / NaT
    - dq_invalid_date: True if Date was provided in raw form but was unparseable
    - dq_unknown_attendance: True if attendance_category is 'Unknown'
    """
    df = df.copy()

    # dq_missing_employee
    emp_num_null = df["Employee Number"].isna() if "Employee Number" in df.columns else pd.Series(True, index=df.index)
    emp_name_null = df["Employee Name"].isna() if "Employee Name" in df.columns else pd.Series(True, index=df.index)
    df["dq_missing_employee"] = emp_num_null | emp_name_null

    # dq_missing_date
    date_null = df["Date"].isna() if "Date" in df.columns else pd.Series(True, index=df.index)
    df["dq_missing_date"] = date_null

    # dq_invalid_date
    if "_invalid_date_raw" in df.columns:
        df["dq_invalid_date"] = df["_invalid_date_raw"].astype(bool)
        df.drop(columns=["_invalid_date_raw"], inplace=True)
    else:
        df["dq_invalid_date"] = False

    # dq_unknown_attendance
    if "attendance_category" in df.columns:
        df["dq_unknown_attendance"] = df["attendance_category"] == "Unknown"
    else:
        df["dq_unknown_attendance"] = False

    return df
