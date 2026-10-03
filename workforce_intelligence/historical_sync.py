"""
workforce_intelligence/historical_sync.py
──────────────────────────────────────────
Historical Data Sync & Archive Manager for Transformers Workforce Intelligence.

Handles Keka's 1-month API/export restriction by:
  1. Partitioning multi-month requests into individual calendar-month sync tasks.
  2. Persisting each monthly dataset locally into `local_data/historical_archive/`.
  3. Maintaining a JSON sync registry tracking record counts, sync timestamps, and DQ status.
  4. Allowing one-click individual month re-sync or batch historical sync.
  5. Assembling all archived historical months into a single unified analytical dataset.
"""

import os
import io
import time
import json
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple, Callable
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_ARCHIVE_DIR = Path("local_data") / "historical_archive"
REGISTRY_FILENAME = "sync_registry.json"


class HistoricalSyncManager:
    """
    Manages historical multi-month time series synchronization and local archival.
    """

    def __init__(self, archive_dir: Optional[Path] = None):
        self.archive_dir = Path(archive_dir) if archive_dir else DEFAULT_ARCHIVE_DIR
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.archive_dir / REGISTRY_FILENAME
        self._ensure_registry()

    def _ensure_registry(self):
        """Initialize registry file if not present."""
        if not self.registry_path.exists():
            initial_data = {
                "version": "1.0",
                "months": {},
                "last_updated": None,
                "active_selection": []
            }
            try:
                with open(self.registry_path, "w", encoding="utf-8") as f:
                    json.dump(initial_data, f, indent=2)
            except Exception as e:
                logger.error(f"Failed to create sync registry: {e}")

    def load_registry(self) -> Dict[str, Any]:
        """Load the sync registry JSON."""
        self._ensure_registry()
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read sync registry: {e}")
            return {"version": "1.0", "months": {}, "last_updated": None, "active_selection": []}

    def save_registry(self, registry_data: Dict[str, Any]):
        """Persist the sync registry JSON."""
        registry_data["last_updated"] = datetime.now().isoformat()
        try:
            with open(self.registry_path, "w", encoding="utf-8") as f:
                json.dump(registry_data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save sync registry: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Month Utilities
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def get_month_boundaries(year: int, month: int) -> Tuple[date, date]:
        """Return (first_day, last_day) of a given calendar month."""
        first_day = date(year, month, 1)
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)
        return first_day, last_day

    @staticmethod
    def parse_month_key(month_key: str) -> Tuple[int, int]:
        """Parse 'YYYY-MM' into (year, month)."""
        parts = month_key.strip().split("-")
        return int(parts[0]), int(parts[1])

    @staticmethod
    def format_month_key(dt: date) -> str:
        """Format a date into 'YYYY-MM'."""
        return dt.strftime("%Y-%m-%d")[:7]

    @staticmethod
    def get_month_display_name(month_key: str) -> str:
        """Convert '2026-10' to 'October 2026'."""
        try:
            dt = datetime.strptime(month_key.strip() + "-01", "%Y-%m-%d")
            return dt.strftime("%B %Y")
        except Exception:
            return month_key

    @staticmethod
    def get_keka_api_window_start(ref_date: Optional[date] = None) -> date:
        """
        Keka Attendance API enforces a strict rolling 3-month window.
        Returns the earliest 1st of month accessible via Keka API.
        e.g., in Oct 2026 -> 2026-07-01.
        """
        if not ref_date:
            ref_date = datetime.now().date()
        m = ref_date.month - 3
        y = ref_date.year
        if m < 1:
            m += 12
            y -= 1
        return date(y, m, 1)

    def get_available_months_grid(self, past_n_months: int = 12) -> List[Dict[str, Any]]:
        """
        Generate list of past N months including current month with their sync status
        and Keka API eligibility (3-month rolling window check).
        """
        registry = self.load_registry()
        synced_months = registry.get("months", {})

        now = datetime.now().date()
        min_api_date = self.get_keka_api_window_start(now)
        result = []
        cur_year = now.year
        cur_month = now.month

        for _ in range(past_n_months):
            m_key = f"{cur_year:04d}-{cur_month:02d}"
            f_day, l_day = self.get_month_boundaries(cur_year, cur_month)
            display_name = f_day.strftime("%B %Y")

            info = synced_months.get(m_key, {})
            is_synced = bool(info.get("status") == "SYNCED")
            file_exists = False
            if is_synced and info.get("file_name"):
                file_exists = (self.archive_dir / info["file_name"]).exists()
                if not file_exists:
                    is_synced = False

            is_api_eligible = (l_day >= min_api_date)

            result.append({
                "month_key": m_key,
                "display_name": display_name,
                "from_date": f_day.strftime("%Y-%m-%d"),
                "to_date": l_day.strftime("%Y-%m-%d"),
                "is_synced": is_synced,
                "is_api_eligible": is_api_eligible,
                "source": info.get("source", "API" if is_api_eligible else "FILE_IMPORT"),
                "record_count": info.get("record_count", 0) if is_synced else 0,
                "headcount": info.get("headcount", 0) if is_synced else 0,
                "last_synced": info.get("last_synced", "Never") if is_synced else "Not Synced",
                "status_label": "Synced" if is_synced else ("API Ready (Last 3M)" if is_api_eligible else "File Import Needed (>3M)"),
                "file_name": info.get("file_name", f"attendance_{m_key.replace('-', '_')}.parquet"),
            })

            # Move back 1 month
            cur_month -= 1
            if cur_month < 1:
                cur_month = 12
                cur_year -= 1

        return result

    # ──────────────────────────────────────────────────────────────────────────
    # File Import into Archive
    # ──────────────────────────────────────────────────────────────────────────
    def import_attendance_file(
        self,
        file_path: Any,
        target_month_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Import an exported Keka Daily Performance Report or Attendance Excel/CSV file
        directly into the local historical archive.
        Supports single-month or multi-month files.
        """
        fp = Path(file_path)
        if not fp.exists():
            return {"success": False, "error": f"File does not exist: {file_path}", "imported_months": [], "total_records": 0}

        try:
            if fp.suffix.lower() in [".xlsx", ".xls"]:
                df = pd.read_excel(fp)
            elif fp.suffix.lower() == ".csv":
                df = pd.read_csv(fp)
            elif fp.suffix.lower() == ".parquet":
                df = pd.read_parquet(fp)
            else:
                return {"success": False, "error": f"Unsupported file type: {fp.suffix}", "imported_months": [], "total_records": 0}
        except Exception as e:
            return {"success": False, "error": f"Could not read file: {e}", "imported_months": [], "total_records": 0}

        if df.empty:
            return {"success": False, "error": "Imported file is empty.", "imported_months": [], "total_records": 0}

        # Locate Date column
        date_col = None
        for col in df.columns:
            c_clean = str(col).strip().lower()
            if c_clean in ["date", "attendancedate", "log date", "attendance date", "event date"]:
                date_col = col
                break
        if not date_col:
            for col in df.columns:
                if "date" in str(col).lower():
                    date_col = col
                    break

        if not date_col:
            return {"success": False, "error": "Could not find a 'Date' column in the imported file.", "imported_months": [], "total_records": 0}

        # Parse dates to month keys (handle ISO YYYY-MM-DD vs DD-MM-YYYY)
        sample_str = df[date_col].dropna().astype(str).str.strip().tolist()
        use_dayfirst = True
        if sample_str and len(sample_str[0]) >= 4 and sample_str[0][:4].isdigit():
            use_dayfirst = False

        df["_parsed_dt"] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=use_dayfirst)
        valid_mask = df["_parsed_dt"].notna()
        df_valid = df[valid_mask].copy()

        if df_valid.empty:
            return {"success": False, "error": "No valid dates found in the file's Date column.", "imported_months": [], "total_records": 0}

        df_valid["_month_key"] = df_valid["_parsed_dt"].dt.strftime("%Y-%m")
        unique_months = sorted(df_valid["_month_key"].unique())

        if target_month_key and target_month_key not in unique_months:
            return {
                "success": False,
                "error": f"Selected file does not contain records for {self.get_month_display_name(target_month_key)}. Found months: {', '.join(unique_months)}",
                "imported_months": [],
                "total_records": 0
            }

        months_to_save = [target_month_key] if target_month_key else unique_months
        imported_keys = []
        total_recs = 0

        registry = self.load_registry()

        for m_key in months_to_save:
            m_df = df_valid[df_valid["_month_key"] == m_key].copy()
            if m_df.empty:
                continue

            # Cleanup helper columns
            m_df = m_df.drop(columns=["_parsed_dt", "_month_key"], errors="ignore")

            file_base = f"attendance_{m_key.replace('-', '_')}"
            parquet_file = self.archive_dir / f"{file_base}.parquet"
            excel_file = self.archive_dir / f"{file_base}.xlsx"

            try:
                m_df.to_parquet(parquet_file, index=False)
            except Exception:
                pass

            try:
                with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
                    m_df.to_excel(writer, sheet_name="Daily Performance Report", index=False)
            except Exception as e:
                logger.warning(f"Could not write Excel backup during file import for {m_key}: {e}")

            # Calculate metrics
            emp_c = None
            for c in ["Employee Number", "Employee No", "Emp No", "employeeNumber", "EmployeeCode"]:
                if c in m_df.columns:
                    emp_c = c
                    break
            hc = int(m_df[emp_c].nunique()) if emp_c else len(m_df)
            y, m = self.parse_month_key(m_key)
            f_day, l_day = self.get_month_boundaries(y, m)

            registry.setdefault("months", {})[m_key] = {
                "month_key": m_key,
                "display_name": self.get_month_display_name(m_key),
                "from_date": f_day.strftime("%Y-%m-%d"),
                "to_date": l_day.strftime("%Y-%m-%d"),
                "record_count": len(m_df),
                "headcount": hc,
                "last_synced": f"{datetime.now().strftime('%d-%b-%Y %H:%M')} (File Import)",
                "status": "SYNCED",
                "source": "FILE_IMPORT",
                "file_name": f"{file_base}.parquet" if parquet_file.exists() else f"{file_base}.xlsx",
            }

            imported_keys.append(m_key)
            total_recs += len(m_df)

        self.save_registry(registry)
        return {
            "success": True,
            "error": None,
            "imported_months": imported_keys,
            "total_records": total_recs,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Single & Multi-Month Syncing
    # ──────────────────────────────────────────────────────────────────────────
    def sync_single_month_keka(
        self,
        month_key: str,
        keka_fetcher: Any,
        cached_emp_df: Optional[pd.DataFrame] = None,
        progress_callback: Optional[Callable[[float, str, str], None]] = None
    ) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[str]]:
        """
        Fetch a single calendar month from Keka REST API.
        Respects Keka's 1-month API limit and 3-month rolling window policy.
        Returns: (monthly_attendance_df, emp_df, error_message)
        """
        def _notify(pct: float, step: str, detail: str = ""):
            if progress_callback:
                progress_callback(pct, step, detail)

        y, m = self.parse_month_key(month_key)
        f_day, l_day = self.get_month_boundaries(y, m)
        from_iso = f_day.strftime("%Y-%m-%d")
        to_iso = l_day.strftime("%Y-%m-%d")
        disp_name = self.get_month_display_name(month_key)

        _notify(0.10, f"Syncing {disp_name}...", "Fetching Employee Master...")
        emp_df = cached_emp_df
        if emp_df is None or emp_df.empty:
            emp_df, emp_err = keka_fetcher.fetch_employee_master()
            if emp_err and (emp_df is None or emp_df.empty):
                return None, None, f"Failed to fetch Employee Master: {emp_err}"

        _notify(0.35, f"Syncing {disp_name}...", f"Fetching OD/WFH Requests ({from_iso} to {to_iso})...")
        wfh_df, wfh_err = keka_fetcher.fetch_od_wfh_requests(from_date=from_iso, to_date=to_iso)

        _notify(0.60, f"Syncing {disp_name}...", f"Pulling Attendance Records ({from_iso} to {to_iso})...")
        att_df, att_err = keka_fetcher.fetch_attendance_report(
            from_date=from_iso,
            to_date=to_iso,
            emp_df=emp_df,
            wfh_df=wfh_df,
            progress_callback=lambda p, m: _notify(0.60 + p * 0.30, f"Syncing {disp_name}...", m)
        )

        if att_err and (att_df is None or att_df.empty):
            return None, emp_df, f"Keka attendance sync failed for {disp_name}: {att_err}"

        if att_df is None or att_df.empty:
            return None, emp_df, f"No attendance records returned for {disp_name}."

        # Save to local archive (both Parquet for fast loading and Excel for export inspection)
        file_base = f"attendance_{month_key.replace('-', '_')}"
        parquet_file = self.archive_dir / f"{file_base}.parquet"
        excel_file = self.archive_dir / f"{file_base}.xlsx"

        _notify(0.92, f"Saving {disp_name} Archive...", "Writing dataset...")
        try:
            att_df.to_parquet(parquet_file, index=False)
        except Exception:
            pass  # Fallback to excel if pyarrow not available

        try:
            with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
                att_df.to_excel(writer, sheet_name="Daily Performance Report", index=False)
        except Exception as e:
            logger.warning(f"Could not write Excel backup for {month_key}: {e}")

        # Update registry
        emp_col = "Employee Number" if "Employee Number" in att_df.columns else "Employee No"
        hc = int(att_df[emp_col].nunique()) if emp_col in att_df.columns else len(emp_df)

        registry = self.load_registry()
        registry.setdefault("months", {})[month_key] = {
            "month_key": month_key,
            "display_name": disp_name,
            "from_date": from_iso,
            "to_date": to_iso,
            "record_count": len(att_df),
            "headcount": hc,
            "last_synced": datetime.now().strftime("%d-%b-%Y %H:%M:%S"),
            "status": "SYNCED",
            "file_name": f"{file_base}.parquet" if parquet_file.exists() else f"{file_base}.xlsx",
        }
        self.save_registry(registry)

        _notify(1.0, f"Synced {disp_name}!", f"Successfully saved {len(att_df):,} records ({hc} employees)")
        return att_df, emp_df, None

    def sync_multiple_months_keka(
        self,
        month_keys: List[str],
        keka_fetcher: Any,
        batch_progress_callback: Optional[Callable[[int, int, str, float, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Sequentially synchronize a list of months from Keka.
        Handles rate limits gracefully and shares cached Employee Master across iterations.
        """
        month_keys = sorted(list(set(month_keys)))
        total_months = len(month_keys)
        synced_dfs = []
        errors = []
        cached_emp_df = None

        for idx, m_key in enumerate(month_keys, start=1):
            disp_name = self.get_month_display_name(m_key)

            def _step_prog(pct, step, detail):
                if batch_progress_callback:
                    batch_progress_callback(idx, total_months, disp_name, pct, f"{step} {detail}".strip())

            _step_prog(0.05, f"Starting {disp_name}", f"({idx}/{total_months})")
            df_m, emp_df, err = self.sync_single_month_keka(
                month_key=m_key,
                keka_fetcher=keka_fetcher,
                cached_emp_df=cached_emp_df,
                progress_callback=_step_prog
            )

            if emp_df is not None and not emp_df.empty:
                cached_emp_df = emp_df

            if err:
                errors.append(f"{disp_name}: {err}")
            elif df_m is not None and not df_m.empty:
                synced_dfs.append(df_m)

            # Small cooldown between months to allow Keka rate-limit window to refresh
            time.sleep(0.4)

        # Assemble unified dataset
        unified_df = pd.DataFrame()
        if synced_dfs:
            unified_df = pd.concat(synced_dfs, ignore_index=True)
            emp_c = "Employee Number" if "Employee Number" in unified_df.columns else "Employee No"
            dt_c = "Date" if "Date" in unified_df.columns else "attendanceDate"
            if emp_c in unified_df.columns and dt_c in unified_df.columns:
                unified_df = unified_df.drop_duplicates(subset=[emp_c, dt_c], keep="last")

        return {
            "success": len(errors) == 0,
            "total_requested": total_months,
            "total_synced": len(synced_dfs),
            "total_records": len(unified_df),
            "errors": errors,
            "unified_df": unified_df,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Unified History Loading & Snapshot Generation
    # ──────────────────────────────────────────────────────────────────────────
    def load_unified_history(
        self,
        month_keys: Optional[List[str]] = None
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Load all or selected synced historical monthly datasets from local archive
        into a consolidated time-series DataFrame.
        """
        registry = self.load_registry()
        synced_months = registry.get("months", {})

        target_keys = sorted(month_keys) if month_keys else sorted(synced_months.keys())
        loaded_dfs = []
        loaded_months_info = []

        for m_key in target_keys:
            info = synced_months.get(m_key)
            if not info or info.get("status") != "SYNCED":
                continue

            f_name = info.get("file_name", f"attendance_{m_key.replace('-', '_')}.parquet")
            file_path = self.archive_dir / f_name
            excel_path = self.archive_dir / f"attendance_{m_key.replace('-', '_')}.xlsx"

            df_m = None
            if file_path.exists() and str(file_path).endswith(".parquet"):
                try:
                    df_m = pd.read_parquet(file_path)
                except Exception:
                    df_m = None

            if (df_m is None or df_m.empty) and excel_path.exists():
                try:
                    df_m = pd.read_excel(excel_path)
                except Exception:
                    df_m = None

            if df_m is not None and not df_m.empty:
                loaded_dfs.append(df_m)
                loaded_months_info.append(m_key)

        if not loaded_dfs:
            return pd.DataFrame(), {"total_records": 0, "months_count": 0, "months": []}

        unified = pd.concat(loaded_dfs, ignore_index=True)
        emp_c = "Employee Number" if "Employee Number" in unified.columns else "Employee No"
        dt_c = "Date" if "Date" in unified.columns else "attendanceDate"
        if emp_c in unified.columns and dt_c in unified.columns:
            unified = unified.drop_duplicates(subset=[emp_c, dt_c], keep="last")

        summary = {
            "total_records": len(unified),
            "months_count": len(loaded_months_info),
            "months": loaded_months_info,
            "min_date": str(unified[dt_c].min()) if dt_c in unified.columns and not unified.empty else None,
            "max_date": str(unified[dt_c].max()) if dt_c in unified.columns and not unified.empty else None,
        }
        return unified, summary

    def delete_month(self, month_key: str) -> bool:
        """Remove a single month from local archive and update registry."""
        registry = self.load_registry()
        if month_key in registry.get("months", {}):
            del registry["months"][month_key]
            self.save_registry(registry)

        file_base = f"attendance_{month_key.replace('-', '_')}"
        for ext in [".parquet", ".xlsx", ".csv"]:
            fp = self.archive_dir / f"{file_base}{ext}"
            if fp.exists():
                try:
                    fp.unlink()
                except Exception:
                    pass
        return True


# Global singleton instance
historical_sync_manager = HistoricalSyncManager()
