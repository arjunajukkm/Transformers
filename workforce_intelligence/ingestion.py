"""
ingestion.py
────────────
Primary ingestion layer for Workforce Intelligence.
Loads source files (.xlsx, .xls, .csv), maps column names to canonical schema,
validates presence of mandatory dimensions, normalizes data types, derives basic
analytical metrics, and computes data quality diagnostics.
"""

from pathlib import Path
from typing import Tuple, Union
import pandas as pd

from workforce_intelligence.normalization import normalize_workforce_dataframe
from workforce_intelligence.quality import DataQualityReport, compute_quality_report
from workforce_intelligence.schema import resolve_canonical_column
from workforce_intelligence.validation import (
    MissingRequiredColumnsError,
    apply_quality_flags,
    validate_schema,
)


def load_workforce_data(
    file_path: Union[str, Path]
) -> Tuple[pd.DataFrame, DataQualityReport]:
    """
    Ingest and normalize a workforce dataset.

    Parameters:
        file_path: Path to an Excel (.xlsx, .xls) or CSV (.csv) file.

    Returns:
        Tuple of:
            - cleaned_df: Fully normalized pandas DataFrame with derived analytical
              fields, immutable record_id, source_row_number, and row-level data quality flags.
            - quality_report: DataQualityReport detailing data health, missingness,
              same-day quantity validations, exact duplicate counts, and structured findings.

    Raises:
        FileNotFoundError: If the specified file does not exist.
        ValueError: If the file format is unsupported.
        MissingRequiredColumnsError: If any mandatory canonical columns are missing.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Workforce data file not found: {path}")

    ext = path.suffix.lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        raise ValueError(
            f"Unsupported file format '{ext}'. Expected .xlsx, .xls, or .csv"
        )

    # 1. Load Raw File safely
    if ext == ".csv":
        df = pd.read_csv(path, dtype=object)
    else:
        with pd.ExcelFile(path) as xl:
            df = xl.parse(xl.sheet_names[0], dtype=object)

    # 2. Normalize and Map Column Names to Canonical Schema
    column_mapping = {col: resolve_canonical_column(col) for col in df.columns}
    source_columns_mapped = list(column_mapping.values())
    df = df.rename(columns=column_mapping)

    # 3. Validate Required Schema
    _, missing_optional = validate_schema(df)

    # 4. Normalize Data Types, Traceability Fields & Derived Analytical Fields
    normalized_df, norm_meta = normalize_workforce_dataframe(df)

    # 5. Apply Non-Destructive Data Quality Flags
    # Exact duplicate detection strictly evaluates original source columns
    flagged_df = apply_quality_flags(normalized_df, source_columns=source_columns_mapped)

    # 6. Compute Data Quality Report
    quality_report = compute_quality_report(
        flagged_df,
        meta=norm_meta,
        missing_optional_cols=missing_optional,
    )

    return flagged_df, quality_report
