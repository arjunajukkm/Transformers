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

    # 5. dq_exact_duplicate & 6. dq_multiple_records_same_date
    if "dq_cross_file_exact_duplicate" not in df.columns:
        df["dq_cross_file_exact_duplicate"] = False

    # Identifies groups with count > 1 for (Employee Number, Date)
    df["dq_multiple_records_same_date"] = False
    valid_emp_date = df["Employee Number"].notna() & df["Date"].notna()
    if valid_emp_date.any() and "record_id" in df.columns:
        counts = df[valid_emp_date].groupby(["Employee Number", "Date"])["record_id"].transform("count")
        df.loc[valid_emp_date, "dq_multiple_records_same_date"] = (counts > 1).astype(bool)

    # 7. dq_missing_quantity
    if "Quantity" in df.columns:
        df["dq_missing_quantity"] = df["Quantity"].isna().astype(bool)
    else:
        df["dq_missing_quantity"] = True

    # 8. Apply deterministic duplicate governance and dual daily quantities
    df = apply_duplicate_governance(df, source_columns=source_columns)

    return df


def apply_duplicate_governance(
    df: pd.DataFrame, source_columns: Optional[List[str]] = None
) -> pd.DataFrame:
    """
    Apply deterministic duplicate precedence and calculate governed analytical fields.
    Precedence: lowest source_file_index, then lowest source_row_number.
    - First occurrence: include_in_analysis = True, analysis_exclusion_reason = "NONE"
    - Subsequent same-file: include_in_analysis = False, analysis_exclusion_reason = "EXACT_DUPLICATE"
    - Subsequent cross-file: include_in_analysis = False, analysis_exclusion_reason = "CROSS_FILE_EXACT_DUPLICATE"
    - Dual quantities: raw_daily_total_quantity and analytical_daily_total_quantity
    - Governed critical flag: dq_analytical_daily_quantity_exceeds_one
    """
    df = df.copy()
    if len(df) == 0:
        return df

    # Prepare sorting keys for deterministic precedence
    df["_orig_idx"] = df.index
    file_idx_series = (
        df["source_file_index"].fillna(1).astype(int)
        if "source_file_index" in df.columns
        else pd.Series(1, index=df.index)
    )
    row_num_series = (
        df["source_row_number"].fillna(df["_orig_idx"]).astype(int)
        if "source_row_number" in df.columns
        else df["_orig_idx"]
    )

    df["_sort_f_idx"] = file_idx_series
    df["_sort_r_idx"] = row_num_series

    # Identify canonical subset
    if source_columns:
        exact_subset = [c for c in source_columns if c in df.columns]
    else:
        exact_subset = [c for c in CANONICAL_COLUMNS if c in df.columns]

    if exact_subset:
        # Sort deterministically
        sorted_df = df.sort_values(by=["_sort_f_idx", "_sort_r_idx", "_orig_idx"])

        # Compute group cumcount and min source_file_index
        cumcount = sorted_df.groupby(exact_subset, dropna=False).cumcount()
        min_file_idx = sorted_df.groupby(exact_subset, dropna=False)["_sort_f_idx"].transform("min")

        is_first = cumcount == 0
        is_cross = (~is_first) & (sorted_df["_sort_f_idx"] > min_file_idx)
        is_same = (~is_first) & (sorted_df["_sort_f_idx"] == min_file_idx)

        sorted_df["include_in_analysis"] = is_first
        sorted_df["dq_exact_duplicate"] = is_same
        sorted_df["dq_cross_file_exact_duplicate"] = is_cross

        exclusion_reasons = pd.Series("NONE", index=sorted_df.index)
        exclusion_reasons[is_same] = "EXACT_DUPLICATE"
        exclusion_reasons[is_cross] = "CROSS_FILE_EXACT_DUPLICATE"
        sorted_df["analysis_exclusion_reason"] = exclusion_reasons

        # Restore original index order
        df = sorted_df.sort_values(by="_orig_idx").drop(columns=["_orig_idx", "_sort_f_idx", "_sort_r_idx"])
    else:
        df["include_in_analysis"] = True
        df["analysis_exclusion_reason"] = "NONE"
        df["dq_exact_duplicate"] = False
        df["dq_cross_file_exact_duplicate"] = False
        df.drop(columns=["_orig_idx", "_sort_f_idx", "_sort_r_idx"], errors="ignore", inplace=True)

    # Calculate dual daily quantities per (Employee Number, Date)
    if "Employee Number" in df.columns and "Date" in df.columns:
        valid_mask = df["Employee Number"].notna() & df["Date"].notna()
        df["raw_daily_total_quantity"] = None
        df["analytical_daily_total_quantity"] = None

        if valid_mask.any() and "Quantity" in df.columns:
            def sum_quantities(s):
                valid_vals = s.dropna()
                return round(float(valid_vals.sum()), 4) if not valid_vals.empty else None

            # Raw sum across all rows
            df.loc[valid_mask, "raw_daily_total_quantity"] = (
                df[valid_mask]
                .groupby(["Employee Number", "Date"])["Quantity"]
                .transform(sum_quantities)
            )

            # Analytical sum across included rows only
            included_valid_mask = valid_mask & df["include_in_analysis"]
            if included_valid_mask.any():
                grp_sums = (
                    df[included_valid_mask]
                    .groupby(["Employee Number", "Date"])["Quantity"]
                    .agg(sum_quantities)
                )
                emp_dt_keys = list(zip(df.loc[valid_mask, "Employee Number"], df.loc[valid_mask, "Date"]))
                df.loc[valid_mask, "analytical_daily_total_quantity"] = [
                    grp_sums.get(k, 0.0) for k in emp_dt_keys
                ]
            else:
                df.loc[valid_mask, "analytical_daily_total_quantity"] = 0.0

        # For invalid mask, quantities are their own quantity
        invalid_mask = ~valid_mask
        if invalid_mask.any():
            qty_col = df.loc[invalid_mask, "Quantity"] if "Quantity" in df.columns else None
            df.loc[invalid_mask, "raw_daily_total_quantity"] = qty_col
            df.loc[invalid_mask, "analytical_daily_total_quantity"] = qty_col
    else:
        qty_col = df["Quantity"] if "Quantity" in df.columns else None
        df["raw_daily_total_quantity"] = qty_col
        df["analytical_daily_total_quantity"] = qty_col

    # daily_total_quantity reflects analytical_daily_total_quantity for leadership analytics
    df["daily_total_quantity"] = df["analytical_daily_total_quantity"]

    # Critical quantity flags
    def check_exceed(val):
        return bool(val is not None and pd.notna(val) and float(val) > 1.000001)

    df["dq_daily_quantity_exceeds_one"] = df["raw_daily_total_quantity"].apply(check_exceed).astype(bool)
    df["dq_analytical_daily_quantity_exceeds_one"] = df["analytical_daily_total_quantity"].apply(check_exceed).astype(bool)

    return df
