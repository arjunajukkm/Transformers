"""
storage/snapshot_service.py
───────────────────────────
High-performance analytical snapshot engine and service for Transformers 2.0.

Provides the decoupled, UI-independent analytical service interface:
- Upload once -> normalize & extract metadata -> precompute standard KPIs
  and 4-level breakdowns -> store reusable AnalyticalSnapshot.
- Atomic dataset replacement with failure isolation and stale-job fencing.
- Thread-safe query and export facade without UI or web dependencies.
"""

from datetime import date
import hashlib
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import pandas as pd

from storage.cache_manager import (
    AnalyticalSnapshot,
    CacheManager,
    snapshot_cache,
)
import time_series_analysis as tsa


def generate_dataset_id(raw_source: str, df: Optional[pd.DataFrame] = None) -> str:
    """Generate a unique, stable dataset identifier based on source and content."""
    base_name = Path(raw_source).name if raw_source else "dataset"
    if df is not None and not df.empty:
        # Sample first and last rows to form content hash
        sample_str = f"{len(df)}_{df.shape[1]}_{df.iloc[0].to_dict()}_{df.iloc[-1].to_dict()}"
        h = hashlib.sha256(sample_str.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"{base_name}_{h}"
    return f"{base_name}_{int(time.time() * 1000)}"


import re


def normalize_dataset_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a raw DataFrame into canonical helper columns if not already normalized."""
    if "_emp_num" in df.columns and "_bu" in df.columns:
        return df

    canon_cols = {}
    for canon in tsa.ALIASES.keys():
        matched = tsa.find_column(df, canon)
        if matched:
            canon_cols[canon] = matched

    work_df = df.copy()

    # 1. Date & Month
    if "date" in canon_cols:
        work_df["_date"] = work_df[canon_cols["date"]].apply(tsa.parse_date_value)
    else:
        work_df["_date"] = None

    if "month" in canon_cols:
        work_df["_month_raw"] = work_df[canon_cols["month"]].astype(str).str.strip()
    elif "date" in canon_cols:
        work_df["_month_raw"] = work_df["_date"].apply(lambda d: d.strftime("%b %Y") if d else "Unknown")
    else:
        work_df["_month_raw"] = "All"

    def _clean_month(m_val, d_val):
        if m_val and m_val not in ("nan", "None", "", "NA", "NaT"):
            parsed = tsa.parse_date_value(m_val)
            if parsed:
                return parsed.strftime("%b %Y")
            if re.match(r'^[A-Za-z]{3}\s*\d{4}', str(m_val)):
                return str(m_val)
        if d_val:
            return d_val.strftime("%b %Y")
        return "Unknown"

    work_df["_month_clean"] = [
        _clean_month(m, d) for m, d in zip(work_df["_month_raw"], work_df["_date"])
    ]

    # 2. Business Unit, Department, RM, Employee
    work_df["_bu"] = work_df[canon_cols["business_unit"]].astype(str).str.strip() if "business_unit" in canon_cols else "General"
    work_df["_dept"] = work_df[canon_cols["department"]].astype(str).str.strip() if "department" in canon_cols else "General"
    work_df["_rm"] = work_df[canon_cols["reporting_manager"]].astype(str).str.strip() if "reporting_manager" in canon_cols else "Unknown"
    work_df["_emp_num"] = work_df[canon_cols["employee_number"]].astype(str).str.strip() if "employee_number" in canon_cols else ""
    work_df["_emp_name"] = work_df[canon_cols["employee_name"]].astype(str).str.strip() if "employee_name" in canon_cols else work_df["_emp_num"]

    work_df["_emp_num"] = work_df["_emp_num"].apply(lambda s: str(s)[:-2] if str(s).endswith(".0") else str(s))

    # 3. Attendance Type & Status
    work_df["_att_type"] = work_df[canon_cols["attendance_type"]].astype(str).str.strip() if "attendance_type" in canon_cols else ""
    work_df["_status"] = work_df[canon_cols["status"]].astype(str).str.strip() if "status" in canon_cols else ""
    work_df["_leave_name"] = work_df[canon_cols["leave_name"]].astype(str).str.strip() if "leave_name" in canon_cols else ""

    # 4. Swipes and Working Hours
    work_df["_in_mins"] = work_df[canon_cols["in_time"]].apply(tsa.parse_time_to_minutes) if "in_time" in canon_cols else None
    work_df["_out_mins"] = work_df[canon_cols["out_time"]].apply(tsa.parse_time_to_minutes) if "out_time" in canon_cols else None

    def _calc_work_hrs(in_m, out_m, att_t):
        if in_m is None or out_m is None or pd.isna(in_m) or pd.isna(out_m):
            return float("nan")
        att_norm = str(att_t).lower()
        if not ("present" in att_norm or "missing swipes" in att_norm or att_norm in ("p", "p(ms)", "ms")):
            return float("nan")
        diff_mins = out_m - in_m
        if diff_mins < 0:
            diff_mins += 1440
        return diff_mins / 60.0

    work_df["_work_hours"] = [
        _calc_work_hrs(i, o, a) for i, o, a in zip(work_df["_in_mins"], work_df["_out_mins"], work_df["_att_type"])
    ]

    # 5. Applied and Approved dates and roles
    work_df["_applied_on"] = work_df[canon_cols["applied_on"]].apply(tsa.parse_date_value) if "applied_on" in canon_cols else None
    work_df["_approved_on"] = work_df[canon_cols["approved_on"]].apply(tsa.parse_date_value) if "approved_on" in canon_cols else None
    work_df["_applied_by"] = work_df[canon_cols["applied_by"]].astype(str).str.strip() if "applied_by" in canon_cols else ""
    work_df["_approved_by"] = work_df[canon_cols["approved_by"]].astype(str).str.strip() if "approved_by" in canon_cols else ""

    return work_df


def create_snapshot(
    file_path_or_df: Union[str, Path, pd.DataFrame],
    dataset_id: Optional[str] = None,
    version: int = 1,
) -> AnalyticalSnapshot:
    """
    Ingest, normalize, extract metadata, and precompute standard metrics
    and breakdowns into an AnalyticalSnapshot.
    Raises descriptive exceptions if processing or normalization fails.
    """
    raw_source = ""
    if isinstance(file_path_or_df, pd.DataFrame):
        fact_df = normalize_dataset_dataframe(file_path_or_df)
        raw_source = "DataFrame"
    else:
        raw_source = str(file_path_or_df)
        p = Path(raw_source)
        if not p.exists():
            raise FileNotFoundError(f"Dataset file not found: {p}")
        fact_df = tsa.load_time_series_dataset(p)

    if fact_df is None or fact_df.empty:
        raise ValueError("Cannot create snapshot: Dataset is empty or contains no valid rows.")

    # Unique dataset ID
    ds_id = dataset_id or generate_dataset_id(raw_source, fact_df)

    # 1. Extract filter options & dimensions
    bus = sorted([
        str(x) for x in fact_df["_bu"].dropna().unique()
        if str(x).strip() not in ("", "nan", "None")
    ]) if "_bu" in fact_df.columns else []

    depts = sorted([
        str(x) for x in fact_df["_dept"].dropna().unique()
        if str(x).strip() not in ("", "nan", "None")
    ]) if "_dept" in fact_df.columns else []

    rms = sorted([
        str(x) for x in fact_df["_rm"].dropna().unique()
        if str(x).strip() not in ("", "nan", "None", "Unknown")
    ]) if "_rm" in fact_df.columns else []

    months = sorted([
        str(x) for x in fact_df["_month_clean"].dropna().unique()
        if str(x).strip() not in ("", "nan", "None")
    ]) if "_month_clean" in fact_df.columns else []

    filter_options = {
        "business_units": bus,
        "departments": depts,
        "managers": rms,
        "months": months,
    }

    # 2. Extract reporting period & metadata
    dates = [d for d in fact_df["_date"].dropna() if isinstance(d, date)] if "_date" in fact_df.columns else []
    min_date_str = min(dates).strftime("%d-%b-%Y") if dates else "N/A"
    max_date_str = max(dates).strftime("%d-%b-%Y") if dates else "N/A"

    row_count = len(fact_df)
    unique_employees = fact_df["_emp_num"].nunique() if "_emp_num" in fact_df.columns else 0

    metadata = {
        "file_name": Path(raw_source).name if raw_source else "In-Memory Dataset",
        "raw_source": raw_source,
        "row_count": row_count,
        "employee_count": unique_employees,
        "date_range": f"{min_date_str} to {max_date_str}",
        "min_date": min_date_str,
        "max_date": max_date_str,
        "business_units_count": len(bus),
        "departments_count": len(depts),
        "managers_count": len(rms),
        "months_count": len(months),
        "version": version,
    }

    # 3. Precompute organization-wide standard metrics (unfiltered)
    standard_metrics = tsa.compute_time_series_metrics(fact_df)

    # 4. Precompute standard breakdowns across all 4 canonical levels (unfiltered)
    standard_breakdowns = {
        "Business Unit": tsa.compute_level_breakdown(fact_df, level="Business Unit"),
        "Department": tsa.compute_level_breakdown(fact_df, level="Department"),
        "Reporting Manager": tsa.compute_level_breakdown(fact_df, level="Reporting Manager"),
        "Employee": tsa.compute_level_breakdown(fact_df, level="Employee"),
    }

    return AnalyticalSnapshot(
        dataset_id=ds_id,
        version=version,
        raw_source=raw_source,
        fact_df=fact_df,
        metrics=standard_metrics,
        breakdowns=standard_breakdowns,
        filter_options=filter_options,
        metadata=metadata,
    )


class TimeSeriesSnapshotService:
    """
    High-level thread-safe analytics service for the desktop application.
    Orchestrates dataset preparation, snapshot lifecycle, atomic replacement,
    and instantaneous retrieval of standard and filtered analytical results.
    """

    def __init__(self, cache_manager: Optional[CacheManager] = None):
        self.cache_manager = cache_manager or snapshot_cache
        self._job_fence_lock = threading.Lock()
        self._latest_completed_job_id: int = 0

    def prepare_dataset(
        self,
        file_path_or_df: Union[str, Path, pd.DataFrame],
        dataset_id: Optional[str] = None,
    ) -> AnalyticalSnapshot:
        """
        Build a new snapshot completely in isolation from the active state.
        If processing succeeds, atomically promotes the snapshot as active.
        If processing fails, leaves the existing active snapshot intact.
        Fences against race conditions where an older job finishes after a newer one.
        """
        job_id = self.cache_manager.next_version()

        # Build snapshot isolated from current state
        new_snapshot = create_snapshot(
            file_path_or_df=file_path_or_df,
            dataset_id=dataset_id,
            version=job_id,
        )

        # Atomic promotion with job fencing
        with self._job_fence_lock:
            if job_id >= self._latest_completed_job_id:
                self.cache_manager.set_active_snapshot(new_snapshot)
                self._latest_completed_job_id = job_id
            else:
                # Discard older job result to prevent stale overwrites
                pass

        return new_snapshot

    def get_active_snapshot(self) -> Optional[AnalyticalSnapshot]:
        """Retrieve the currently active analytical snapshot."""
        return self.cache_manager.get_active_snapshot()

    def has_active_snapshot(self) -> bool:
        """Check if an active snapshot is present and valid."""
        snap = self.get_active_snapshot()
        return snap is not None and snap.is_valid()

    def get_dashboard_metrics(
        self,
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        month: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve dashboard metrics for the active snapshot.
        Returns empty metrics dictionary if no dataset is loaded.
        """
        snap = self.get_active_snapshot()
        if not snap or not snap.is_valid():
            return tsa._empty_metrics()
        return snap.get_metrics(
            business_unit=business_unit,
            department=department,
            month=month,
        )

    def get_breakdown(
        self,
        level: str,
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        month: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve multi-level breakdown table for the active snapshot.
        Returns empty list if no dataset is loaded.
        """
        snap = self.get_active_snapshot()
        if not snap or not snap.is_valid():
            return []
        return snap.get_breakdown(
            level=level,
            business_unit=business_unit,
            department=department,
            month=month,
        )

    def get_filter_options(self) -> Dict[str, List[str]]:
        """Retrieve available filter dropdown values for the active dataset."""
        snap = self.get_active_snapshot()
        if not snap or not snap.is_valid():
            return {"business_units": [], "departments": [], "managers": [], "months": []}
        return {k: list(v) for k, v in snap.filter_options.items()}

    def get_metadata(self) -> Dict[str, Any]:
        """Retrieve dataset summary metadata for the active dataset."""
        snap = self.get_active_snapshot()
        if not snap or not snap.is_valid():
            return {}
        return dict(snap.metadata)

    def invalidate_active_snapshot(self):
        """Invalidate the current active snapshot."""
        self.cache_manager.invalidate()

    def clear(self):
        """Purge all snapshots and reset service state."""
        with self._job_fence_lock:
            self._latest_completed_job_id = 0
            self.cache_manager.clear()

    def export_report(
        self,
        output_path: Union[str, Path],
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        month: Optional[str] = None,
    ) -> Path:
        """Export comprehensive Time Series Excel report from the active dataset."""
        snap = self.get_active_snapshot()
        if not snap or not snap.is_valid():
            raise RuntimeError("Cannot export report: No active analytical dataset is loaded.")
        return tsa.export_time_series_report(
            df=snap.fact_df,
            output_path=output_path,
            business_unit=business_unit,
            department=department,
            month=month,
        )


# Global singleton service instance
snapshot_service = TimeSeriesSnapshotService()
