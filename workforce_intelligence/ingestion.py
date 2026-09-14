"""
ingestion.py
────────────
Primary ingestion layer for Workforce Intelligence.
Loads source files (.xlsx, .xls, .csv), supports single or multi-file ingestion,
maps column names to canonical schema, validates presence of mandatory dimensions,
normalizes data types, derives basic analytical metrics, preserves source file
traceability, detects cross-file exact duplicates, and computes data quality diagnostics.
"""

from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple, Union
import pandas as pd

from workforce_intelligence.normalization import normalize_workforce_dataframe
from workforce_intelligence.quality import DataQualityReport, compute_quality_report
from workforce_intelligence.schema import CANONICAL_COLUMNS, resolve_canonical_column
from workforce_intelligence.validation import (
    MissingRequiredColumnsError,
    apply_quality_flags,
    validate_schema,
)


def _load_single_file(
    file_path: Union[str, Path],
    file_index: Optional_int = None,
    is_multi: bool = False,
    display_name: Optional[str] = None,
) -> Tuple[pd.DataFrame, DataQualityReport, Dict[str, Any], List[str]]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Workforce data file not found: {path.name}")

    ext = path.suffix.lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        raise ValueError(
            f"Unsupported file format '{ext}' for file '{path.name}'. Expected .xlsx, .xls, or .csv"
        )

    # 1. Load Raw File safely
    if ext == ".csv":
        df = pd.read_csv(path, dtype=object)
    else:
        with pd.ExcelFile(path) as xl:
            df = xl.parse(xl.sheet_names[0], dtype=object)

    # 2. Map Column Names to Canonical Schema
    column_mapping = {col: resolve_canonical_column(col) for col in df.columns}
    source_columns_mapped = list(column_mapping.values())
    df = df.rename(columns=column_mapping)

    # 3. Validate Required Schema
    _, missing_optional = validate_schema(df)

    # 4. Normalize with source file metadata
    source_file_name = display_name if display_name else path.name
    normalized_df, norm_meta = normalize_workforce_dataframe(
        df,
        source_file_name=source_file_name,
        source_file_index=file_index if is_multi else None,
    )

    # 5. Apply row-level quality flags
    flagged_df = apply_quality_flags(normalized_df, source_columns=source_columns_mapped)

    # 6. Single-file quality report
    single_report = compute_quality_report(
        flagged_df,
        meta=norm_meta,
        missing_optional_cols=missing_optional,
    )

    crit_cnt = sum(1 for f in single_report.quality_findings if f.get("severity") == "CRITICAL")
    warn_cnt = sum(1 for f in single_report.quality_findings if f.get("severity") == "WARNING")

    summary_entry = {
        "file_name": source_file_name,
        "file_index": file_index if file_index is not None else 1,
        "rows_ingested": len(flagged_df),
        "duplicate_rows_detected": int((~flagged_df["include_in_analysis"]).sum()) if "include_in_analysis" in flagged_df.columns else 0,
        "rows_included_in_analysis": int(flagged_df["include_in_analysis"].sum()) if "include_in_analysis" in flagged_df.columns else len(flagged_df),
        "unique_employees": single_report.unique_employees,
        "date_from": single_report.date_min,
        "date_to": single_report.date_max,
        "critical_findings": crit_cnt,
        "warnings": warn_cnt,
    }

    return flagged_df, single_report, summary_entry, missing_optional


# Type alias for Optional[int]
Optional_int = Union[int, None]


def load_workforce_data(
    file_input: Union[str, Path, Sequence[Union[str, Path]]],
    file_names: Optional[Sequence[str]] = None,
) -> Tuple[pd.DataFrame, DataQualityReport]:
    """
    Ingest and normalize one or multiple workforce datasets (.xlsx, .xls, .csv).

    Parameters:
        file_input: Single file path (str or Path) or sequence of file paths.
        file_names: Optional original file names to preserve traceability when reading from temporary storage.

    Returns:
        Tuple of:
            - cleaned_df: Fully normalized pandas DataFrame with derived analytical
              fields, immutable record_id, source_file_name, source_file_index,
              include_in_analysis governance flag, and non-destructive data quality flags.
            - quality_report: Comprehensive DataQualityReport with source_files summary,
              cross-file duplicate statistics, and structured findings.

    Raises:
        FileNotFoundError: If any specified file does not exist.
        ValueError: If any file format is unsupported or file_input is empty.
        MissingRequiredColumnsError: If any mandatory canonical columns are missing.
    """
    if isinstance(file_input, (str, Path)):
        file_paths = [Path(file_input)]
        is_multi = False
    else:
        file_paths = [Path(p) for p in file_input]
        if len(file_paths) == 0:
            raise ValueError("No file paths provided for ingestion.")
        is_multi = len(file_paths) > 1

    if not is_multi:
        d_name = file_names[0] if (file_names and len(file_names) > 0) else None
        flagged_df, report, summary_entry, _ = _load_single_file(file_paths[0], file_index=1, is_multi=False, display_name=d_name)
        report.source_files = [summary_entry]
        return flagged_df, report

    # Multi-file ingestion
    dfs: List[pd.DataFrame] = []
    source_summaries: List[Dict[str, Any]] = []
    all_missing_optional: List[str] = []
    combined_meta: Dict[str, int] = {
        "invalid_date_count": 0,
        "invalid_applied_on_count": 0,
        "invalid_approved_on_count": 0,
    }

    for idx, fpath in enumerate(file_paths, start=1):
        d_name = file_names[idx - 1] if (file_names and len(file_names) >= idx) else None
        f_df, f_report, f_summary, f_miss_opt = _load_single_file(fpath, file_index=idx, is_multi=True, display_name=d_name)
        dfs.append(f_df)
        source_summaries.append(f_summary)
        all_missing_optional.extend(f_miss_opt)
        combined_meta["invalid_date_count"] += f_report.invalid_date_count
        combined_meta["invalid_applied_on_count"] += f_report.invalid_applied_on_count
        combined_meta["invalid_approved_on_count"] += f_report.invalid_approved_on_count

    combined_df = pd.concat(dfs, ignore_index=True)

    # Apply deterministic cross-file duplicate governance and dual quantities
    from workforce_intelligence.validation import apply_duplicate_governance
    combined_df = apply_duplicate_governance(combined_df)

    # Update source_summaries to reflect cross-file duplicate findings
    for s_entry in source_summaries:
        f_idx = s_entry["file_index"]
        f_mask = combined_df["source_file_index"] == f_idx
        f_rows = combined_df[f_mask]
        dup_count = int((~f_rows["include_in_analysis"]).sum())
        inc_count = int(f_rows["include_in_analysis"].sum())
        s_entry["duplicate_rows_detected"] = dup_count
        s_entry["rows_included_in_analysis"] = inc_count

    # Compute overall quality report
    unique_missing_optional = sorted(list(set(all_missing_optional)))
    quality_report = compute_quality_report(
        combined_df,
        meta=combined_meta,
        missing_optional_cols=unique_missing_optional,
        source_files=source_summaries,
    )

    return combined_df, quality_report
