"""
keka_data_fetcher.py
────────────────────
Hybrid data fetcher for the Absent Management module.

Strategy (Hybrid):
  ✅ API  → Employee Master (GET /hris/employees)
  ✅ API  → OD/WFH Requests (GET /time/wfh + GET /time/od)
  🌐 Selenium → Attendance Report (the portal Status codes like A, P, WO, A:CL
                  are NOT available via API — only the portal export has them)

Usage:
  from keka_data_fetcher import KekaDataFetcher

  fetcher = KekaDataFetcher(subdomain="finbox")
  emp_df  = fetcher.fetch_employee_master()         # API
  wfh_df  = fetcher.fetch_od_wfh_requests(...)      # API
  att_df  = fetcher.fetch_attendance_report(...)     # Selenium (portal)

Dependencies:
  - requests, pandas, openpyxl (existing)
  - selenium, webdriver-manager (new — for attendance report only)
"""

import os
import io
import re
import sys
import time
import math
import base64
import logging
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from typing import Optional, Tuple, Callable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import requests
import concurrent.futures
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_OCR_INSTANCE = None


def clean_keka_subdomain(subdomain: Optional[str] = None) -> str:
    """Normalizes subdomain string or full URL into a clean subdomain slug (e.g. 'moshpit')."""
    sub = (subdomain or os.getenv("KEKA_SUBDOMAIN", "moshpit")).strip()
    if not sub:
        sub = "moshpit"
    if "://" in sub:
        sub = sub.split("://", 1)[1]
    if "/" in sub:
        sub = sub.split("/", 1)[0]
    if ".keka.com" in sub:
        sub = sub.replace(".keka.com", "")
    return sub.strip() or "moshpit"


# ==============================================================================
# TOKEN CACHE (Shared with generate_id_cards.py pattern)
# ==============================================================================
_KEKA_TOKEN_CACHE = {
    "access_token": None,
    "expires_at": 0.0,
    "cache_key": ""
}


def get_keka_access_token(api_key=None, client_id=None, client_secret=None, subdomain=None):
    """
    Obtains a valid Keka Bearer access token.
    Supports TWO flows:
      1. OAuth Client Credentials Flow: client_id + client_secret + api_key → POST /connect/token
      2. Direct Token Flow: api_key used as-is
    Returns: (access_token: str | None, error_msg: str | None)
    """
    if api_key is not None and client_id is None and client_secret is None:
        key = api_key.strip()
        if key:
            return key, None

    cid = (client_id if client_id is not None else os.getenv("KEKA_CLIENT_ID", "")).strip()
    csec = (client_secret if client_secret is not None else os.getenv("KEKA_CLIENT_SECRET", "")).strip()
    key = (api_key if api_key is not None else os.getenv("KEKA_API_KEY", "")).strip()

    if cid and csec and key:
        cache_id = f"{cid}:{key}"
        now = time.time()
        if (_KEKA_TOKEN_CACHE["access_token"]
                and _KEKA_TOKEN_CACHE["cache_key"] == cache_id
                and _KEKA_TOKEN_CACHE["expires_at"] > now + 60):
            return _KEKA_TOKEN_CACHE["access_token"], None

        token_url = "https://login.keka.com/connect/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "Mozilla"
        }
        data = {
            "grant_type": "kekaapi",
            "scope": "kekaapi",
            "client_id": cid,
            "client_secret": csec,
            "api_key": key
        }
        try:
            res = requests.post(token_url, data=data, headers=headers, timeout=12)
            if res.status_code == 200:
                payload = res.json()
                tok = payload.get("access_token")
                expires_in = int(payload.get("expires_in", 86400))
                if tok:
                    _KEKA_TOKEN_CACHE["access_token"] = tok
                    _KEKA_TOKEN_CACHE["expires_at"] = now + expires_in
                    _KEKA_TOKEN_CACHE["cache_key"] = cache_id
                    return tok, None
                return None, "Keka Token endpoint did not return access_token"
            elif res.status_code in (400, 401):
                try:
                    err_json = res.json()
                    err_desc = err_json.get("error_description") or err_json.get("error") or str(res.status_code)
                except Exception:
                    err_desc = res.text[:100]
                return None, f"Keka OAuth Auth Failed: {err_desc}"
            else:
                return None, f"Keka Identity server returned HTTP {res.status_code}"
        except Exception as e:
            return None, f"Error connecting to Keka Identity server: {e}"

    if key:
        return key, None
    if cid and not csec:
        return None, "KEKA_CLIENT_SECRET missing"
    if csec and not cid:
        return None, "KEKA_CLIENT_ID missing"
    return None, "Keka credentials missing (need Client ID, Client Secret & API Key, or Bearer Token)"


def _clean_chrome_profile_locks(profile_dir: Path):
    """
    Terminates any orphaned chrome.exe processes specifically bound to this profile directory
    and clears stale lock files. This prevents:
    'Chrome failed to start: crashed (session not created: DevToolsActivePort file doesn't exist)'
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        import subprocess
        import base64
        dir_name = profile_dir.name
        ps_script = f"""
        Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" | ForEach-Object {{
            if ($_.CommandLine -like '*{dir_name}*') {{
                Stop-Process -Id $_.ProcessId -Force
            }}
        }}
        """
        b64_cmd = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", b64_cmd],
            capture_output=True,
            timeout=5
        )
    except Exception as e:
        logger.debug(f"Profile process cleanup note: {e}")

    # Remove stale lock files left by crashed processes
    for parent in [profile_dir, profile_dir / "Default"]:
        if parent.exists():
            for fname in ["SingletonLock", "SingletonCookie", "SingletonSocket", "LOCK", "DevToolsActivePort", "lockfile"]:
                try:
                    f = parent / fname
                    if f.exists():
                        f.unlink(missing_ok=True)
                except Exception:
                    pass


def _create_chrome_driver(
    profile_dir: Optional[Path] = None,
    headless: bool = True,
    download_dir: Optional[str] = None,
    interactive: bool = False
):
    """
    Initializes a Chrome webdriver instance with anti-crash options and automatic profile lock cleanup.
    If profile_dir is None, starts an ephemeral, ultra-fast isolated session.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from webdriver_manager.chrome import ChromeDriverManager

    if profile_dir is not None:
        _clean_chrome_profile_locks(profile_dir)

    chrome_options = ChromeOptions()
    chrome_options.page_load_strategy = "eager"
    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--window-size=1920,1080")
    else:
        chrome_options.add_argument("--window-size=1280,850")

    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-proxy-server")

    if profile_dir is not None:
        chrome_options.add_argument(f"--user-data-dir={profile_dir}")

    if interactive:
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

    if download_dir:
        chrome_options.add_experimental_option("prefs", {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True
        })

    service = ChromeService(ChromeDriverManager().install())
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(35)
        return driver
    except Exception as e:
        err_str = str(e).lower()
        if "devtoolsactiveport" in err_str or "crashed" in err_str:
            logger.warning(f"Chrome launch crash detected ({e}). Performing force cleanup and retrying...")
            if profile_dir is not None:
                _clean_chrome_profile_locks(profile_dir)
            time.sleep(2)
            try:
                driver = webdriver.Chrome(service=service, options=chrome_options)
                driver.set_page_load_timeout(35)
                return driver
            except Exception as e2:
                if profile_dir is not None:
                    logger.warning(f"Persistent profile crash ({e2}). Recreating clean profile...")
                    import shutil
                    try:
                        shutil.rmtree(profile_dir, ignore_errors=True)
                        profile_dir.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        pass
                time.sleep(1)
                driver = webdriver.Chrome(service=service, options=chrome_options)
                driver.set_page_load_timeout(35)
                return driver
        raise


class KekaDataFetcher:
    """
    Hybrid Keka data fetcher for Absent Management.

    API endpoints for Employee Master + OD/WFH.
    Selenium browser automation for the Attendance report (Status codes).
    """

    def __init__(
        self,
        subdomain: str = None,
        api_key: str = None,
        client_id: str = None,
        client_secret: str = None,
        keka_email: str = None,
        keka_password: str = None
    ):
        self.subdomain = clean_keka_subdomain(subdomain)
        self.base_url = f"https://{self.subdomain}.keka.com/api/v1"
        self.api_key = api_key
        self.client_id = client_id
        self.client_secret = client_secret
        # Credentials for Selenium login (portal)
        self.keka_email = os.getenv("KEKA_LOGIN_EMAIL", "") if keka_email is None else keka_email
        self.keka_password = os.getenv("KEKA_LOGIN_PASSWORD", "") if keka_password is None else keka_password
        # Persistent HTTP session for fast connection reuse
        self.session = requests.Session()

    def _get_headers(self) -> Tuple[dict, Optional[str]]:
        """Returns (headers_dict, error_string_or_None)."""
        token, err = get_keka_access_token(
            api_key=self.api_key,
            client_id=self.client_id,
            client_secret=self.client_secret,
            subdomain=self.subdomain
        )
        if not token:
            return {}, err
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }, None

    def _paginated_get(
        self,
        endpoint: str,
        params: dict = None,
        max_pages: int = 100,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        label: str = "Records"
    ) -> Tuple[list, Optional[str]]:
        """
        Generic paginated GET for Keka API.
        Uses persistent session for maximum throughput and supports progress callbacks.
        Returns (list_of_all_records, error_or_None).
        """
        headers, err = self._get_headers()
        if err:
            return [], err

        if params is None:
            params = {}
        params.setdefault("pageSize", 200)
        params.setdefault("pageNumber", 1)

        # Use session.get, but allow requests.get fallback if monkeypatched in unit tests
        getter = self.session.get
        if getattr(requests.get, "__module__", None) != "requests.api":
            getter = requests.get

        all_records = []
        for page in range(1, max_pages + 1):
            params["pageNumber"] = page
            
            # Retry loop for HTTP 429 (Rate Limiting) and transient network/server hiccups
            max_retries = 4
            success = False
            for attempt in range(max_retries):
                try:
                    url = f"{self.base_url}/{endpoint.lstrip('/')}"
                    res = getter(url, headers=headers, params=params, timeout=30)
                    
                    if res.status_code == 429:
                        # Rate limit hit: extract Retry-After or apply exponential backoff
                        retry_after = res.headers.get("Retry-After")
                        wait_sec = float(retry_after) if retry_after else (1.5 * (attempt + 1))
                        logger.warning(f"Keka Rate Limit (HTTP 429) on {endpoint}. Backing off for {wait_sec:.1f}s (attempt {attempt + 1}/{max_retries})...")
                        time.sleep(wait_sec)
                        continue

                    if res.status_code in (500, 502, 503, 504) and attempt < max_retries - 1:
                        time.sleep(1.0 * (attempt + 1))
                        continue

                    if res.status_code == 401:
                        return all_records, "Authentication failed (HTTP 401). Invalid or expired token."
                    if res.status_code == 403:
                        try:
                            err_text = res.text.strip('" ')
                        except Exception:
                            err_text = "Forbidden"
                        return all_records, f"Privilege missing for {endpoint} (HTTP 403: {err_text}). Enable this scope in Keka Admin Settings."
                    if res.status_code != 200:
                        try:
                            err_msg = res.json().get("message") or res.text[:200]
                        except Exception:
                            err_msg = res.text[:200] if hasattr(res, "text") else ""
                        return all_records, f"API error: HTTP {res.status_code} on page {page} ({err_msg})"

                    body = res.json()
                    data = body.get("data", [])
                    if isinstance(data, list):
                        all_records.extend(data)
                    elif isinstance(data, dict):
                        all_records.append(data)

                    total_pages = body.get("totalPages", 1)
                    if progress_callback:
                        try:
                            progress_callback(page, total_pages, f"Fetched {label} page {page}/{total_pages} ({len(all_records)} records)")
                        except Exception:
                            pass

                    success = True
                    # Small throttle between pages to stay well below rate limit threshold
                    time.sleep(0.15)

                    if page >= total_pages:
                        return all_records, None
                    break

                except requests.Timeout:
                    if attempt < max_retries - 1:
                        time.sleep(1.0 * (attempt + 1))
                        continue
                    return all_records, f"Request timed out on page {page}"
                except Exception as e:
                    return all_records, f"Error on page {page}: {e}"

            if not success:
                return all_records, f"API rate limit or connection failure after {max_retries} attempts on page {page}"

        return all_records, None

    # ──────────────────────────────────────────────────────────────────────────
    # REPORT 1: EMPLOYEE MASTER (via API)
    # ──────────────────────────────────────────────────────────────────────────
    def fetch_employee_master(
        self,
        active_only: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Tuple[pd.DataFrame, Optional[str]]:
        """
        Fetches Employee Master from Keka API: GET /hris/employees

        Returns a DataFrame with columns matching what absent_management.py expects:
          Employee Number, Employee Name, Work Email, Reporting Manager,
          Reporting Manager Email, Last Working Day, Location
        """
        params = {}
        if active_only:
            params["employeeStatus"] = "Active"

        records, err = self._paginated_get(
            "/hris/employees",
            params,
            progress_callback=progress_callback,
            label="Employees"
        )
        if err and not records:
            return pd.DataFrame(), err

        # ── Build Department Hierarchy Lookup (Parent -> Child / Sub-Department) ──
        dept_hierarchy = {}
        dept_records, _ = self._paginated_get("/hris/departments", label="Departments")
        if isinstance(dept_records, list):
            dept_by_id = {
                d.get("id"): d for d in dept_records
                if isinstance(d, dict) and d.get("id")
            }
            for d_id, d in dept_by_id.items():
                d_name = (d.get("name") or "").strip()
                pid = d.get("parentId")
                if pid and pid in dept_by_id:
                    pname = (dept_by_id[pid].get("name") or "").strip()
                    dept_hierarchy[d_id] = {
                        "department": pname,
                        "sub_department": d_name,
                    }
                else:
                    dept_hierarchy[d_id] = {
                        "department": d_name,
                        "sub_department": "",
                    }

        rows = []
        # Build a mapping of employee ID → email for RM email lookup
        id_to_email = {}
        for r in records:
            eid = r.get("id") or r.get("identifier") or ""
            email = (r.get("email") or r.get("workEmail") or "").strip()
            if eid and email:
                id_to_email[eid] = email

        for r in records:
            emp_no = (r.get("employeeNumber") or "").strip()
            name = (
                r.get("displayName") or
                r.get("fullName") or
                r.get("employeeName") or
                ""
            ).strip()
            # If no display name, try constructing from firstName + lastName
            if not name:
                fn = (r.get("firstName") or "").strip()
                ln = (r.get("lastName") or "").strip()
                name = f"{fn} {ln}".strip()
            email = (
                r.get("email") or
                r.get("workEmail") or
                r.get("emailAddress") or
                r.get("officialEmail") or
                ""
            ).strip()

            # ── Reporting Manager ───────────────────────────────────────────
            rm_info = r.get("reportsTo") or r.get("reportingManager") or r.get("manager") or {}
            rm_name = ""
            rm_email = ""
            if isinstance(rm_info, dict):
                rm_name = (
                    rm_info.get("displayName") or
                    rm_info.get("name") or
                    rm_info.get("fullName") or
                    rm_info.get("employeeName") or
                    ""
                ).strip()
                # Try firstName+lastName if no display name
                if not rm_name:
                    fn = (rm_info.get("firstName") or "").strip()
                    ln = (rm_info.get("lastName") or "").strip()
                    rm_name = f"{fn} {ln}".strip()
                rm_id = (
                    rm_info.get("id") or
                    rm_info.get("identifier") or
                    rm_info.get("employeeId") or
                    ""
                )
                rm_email = (
                    rm_info.get("email") or
                    rm_info.get("workEmail") or
                    rm_info.get("emailAddress") or
                    ""
                ).strip()
                if not rm_email and rm_id:
                    rm_email = id_to_email.get(rm_id, "")
            elif isinstance(rm_info, str):
                rm_name = rm_info.strip()

            # ── Location ────────────────────────────────────────────────────
            loc_info = r.get("location") or r.get("workLocation") or {}
            location = ""
            if isinstance(loc_info, dict):
                location = (
                    loc_info.get("name") or
                    loc_info.get("locationName") or
                    loc_info.get("city") or
                    loc_info.get("officeName") or
                    loc_info.get("displayName") or
                    ""
                ).strip()
            elif isinstance(loc_info, str):
                location = loc_info.strip()
            # Fallback: try top-level city/workLocation string
            if not location:
                location = (
                    r.get("city") or
                    r.get("officeName") or
                    ""
                ).strip()

            # ── Last Working Day (DD-MMM-YY format) ─────────────────────────
            emp_details = r.get("employmentDetails") or {}
            if not isinstance(emp_details, dict):
                emp_details = {}
            lwd_raw = (
                r.get("lastWorkingDay") or
                r.get("lastDay") or
                r.get("exitDate") or
                r.get("relievingDate") or
                emp_details.get("lastWorkingDay") or
                emp_details.get("exitDate") or
                emp_details.get("relievingDate") or
                ""
            )
            lwd = ""
            if lwd_raw:
                try:
                    if isinstance(lwd_raw, str):
                        if "T" in lwd_raw:
                            dt_lwd = datetime.fromisoformat(lwd_raw.replace("Z", "+00:00"))
                        else:
                            dt_lwd = pd.to_datetime(lwd_raw, dayfirst=True)
                    else:
                        dt_lwd = pd.to_datetime(lwd_raw)
                    if pd.notna(dt_lwd):
                        lwd = dt_lwd.strftime("%d-%b-%y")
                except Exception:
                    lwd = str(lwd_raw)

            # ── Job Title ───────────────────────────────────────────────────
            jt_info = r.get("jobTitle") or r.get("designation") or {}
            job_title = ""
            if isinstance(jt_info, dict):
                job_title = (
                    jt_info.get("title") or
                    jt_info.get("name") or
                    jt_info.get("displayName") or
                    ""
                ).strip()
            elif isinstance(jt_info, str):
                job_title = jt_info.strip()

            # ── Groups: Business Unit, Department, Sub-Department ───────────
            # Confirmed groupType codes for Moshpit's Keka account:
            #   1  = Business Unit   (e.g. "Sentinel", "FinBox", "Lending", "Corporate")
            #   2  = Department / Sub-Department (resolved via /hris/departments parentId hierarchy)
            #   3  = Office/Location (e.g. "Bangalore") — skip, handled via location field
            #   5  = Pay Group — skip
            #   9  = Legal Entity    (e.g. "Moshpit Technologies Private Limited") — skip for BU
            # Also matched by groupTypeName string for forward-compatibility.
            dept = ""
            bu = ""
            sub_dept = ""
            groups = r.get("groups") or []

            # Integer codes to skip (not part of org reporting hierarchy)
            SKIP_TYPE_CODES  = {3, 5, 9, 10, 11}  # location, pay group, legal entity
            BU_TYPE_CODES    = {1}                  # business unit / product line
            DEPT_TYPE_CODES  = {2, 4}               # department
            SUB_TYPE_CODES   = {7}                  # sub-department (if present)

            if isinstance(groups, list):
                for g in groups:
                    if not isinstance(g, dict):
                        continue
                    g_type = g.get("groupType")
                    g_type_name = str(
                        g.get("groupTypeName") or g.get("typeName") or g.get("type") or ""
                    ).strip().lower()
                    g_title = (g.get("title") or g.get("name") or g.get("displayName") or "").strip()
                    g_id = g.get("id") or g.get("identifier") or ""
                    if not g_title:
                        continue

                    # Skip legal entity / location / pay group
                    if g_type in SKIP_TYPE_CODES:
                        continue

                    # Classify by type code first, then by name string
                    is_bu = (
                        g_type in BU_TYPE_CODES or
                        any(kw in g_type_name for kw in ("business unit", "businessunit", "vertical", "product line"))
                    )
                    is_sub_dept = (
                        g_type in SUB_TYPE_CODES or
                        any(kw in g_type_name for kw in ("sub department", "subdepartment", "sub dept", "sub-department", "team"))
                    )
                    is_dept = (
                        not is_sub_dept and (
                            g_type in DEPT_TYPE_CODES or
                            any(kw in g_type_name for kw in ("department", "dept"))
                        )
                    )

                    if is_bu and not bu:
                        bu = g_title
                    elif is_sub_dept and not sub_dept:
                        sub_dept = g_title
                    elif is_dept:
                        # Resolve department vs sub-department using hierarchy if available
                        if g_id and g_id in dept_hierarchy:
                            h = dept_hierarchy[g_id]
                            if h.get("department"):
                                dept = h["department"]
                            if h.get("sub_department") and not sub_dept:
                                sub_dept = h["sub_department"]
                        else:
                            if not dept:
                                dept = g_title
                    else:
                        logger.debug(
                            f"Employee {emp_no}: unclassified group "
                            f"type={g_type!r} typeName={g_type_name!r} title={g_title!r} — skipping"
                        )

            rows.append({
                "Employee Number": emp_no,
                "Employee Name": name,
                "Work Email": email,
                "Reporting Manager": rm_name,
                "Reporting Manager Email": rm_email,
                "RM Mail ID": rm_email,          # alias expected by absent_management.py
                "Last Working Day": lwd,
                "LWD": lwd,
                "Location": location,
                "Job Title": job_title,
                "Department": dept,
                "Sub Department": sub_dept,
                "Business Unit": bu,
            })

        df = pd.DataFrame(rows)
        logger.info(
            f"Employee Master: {len(df)} employees fetched via API. "
            f"BU populated: {(df['Business Unit'] != '').sum()}, "
            f"RM populated: {(df['Reporting Manager'] != '').sum()}, "
            f"Location populated: {(df['Location'] != '').sum()}"
        )
        return df, err

    # ──────────────────────────────────────────────────────────────────────────
    # ──────────────────────────────────────────────────────────────────────────
    # REPORT 3: OD/WFH REQUESTS (via API)
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _is_cancelled_or_invalid_status(status_val, record_dict: dict = None, is_leave: bool = False) -> bool:
        """
        Returns True if the request status or record indicates Cancelled, Rejected, Revoked, or Withdrawn.
        Such records should be ignored and never brought to final reports.
        """
        if record_dict and isinstance(record_dict, dict):
            if record_dict.get("isCancelled") is True:
                return True
            cs = record_dict.get("cancellationStatus")
            if cs not in (None, 0, "0", "", "None"):
                return True
            s_name = str(record_dict.get("statusName") or "").strip().lower()
            if any(term in s_name for term in ["cancel", "reject", "revok", "withdraw"]):
                return True
        if status_val is None:
            return False
        if isinstance(status_val, int):
            if is_leave:
                # Keka Leaves: 0=Pending, 1=Approved, 2=Rejected, 3=Cancelled
                return status_val in (2, 3) or status_val not in (0, 1)
            else:
                # Keka WFH/OD: 1=Pending, 2=Approved, 3=Rejected, 4=Cancelled, 5=Revoked
                return status_val in (3, 4, 5) or status_val not in (1, 2)
        s = str(status_val).strip().lower()
        if s in ("cancelled", "canceled", "rejected", "revoked", "withdrawn", "reject", "cancel"):
            return True
        return any(term in s for term in ["cancel", "reject", "revok", "withdraw"])

    @staticmethod
    def _extract_request_audit_info(r: dict) -> Tuple[str, str, str, str]:
        """
        Extracts (requested_by, requested_on, action_taken_by, action_taken_on) from Keka API request dict.
        """
        if not r or not isinstance(r, dict):
            return "", "", "", ""

        # 1. Requested By
        req_by_obj = r.get("requestedBy") or r.get("applicant") or r.get("requester") or r.get("createdBy") or r.get("submittedBy") or r.get("employee")
        req_by = ""
        if isinstance(req_by_obj, dict):
            req_by = (
                req_by_obj.get("displayName") or
                req_by_obj.get("name") or
                f"{req_by_obj.get('firstName', '')} {req_by_obj.get('lastName', '')}"
            ).strip()
        elif isinstance(req_by_obj, str):
            req_by = req_by_obj.strip()

        # 2. Requested On
        req_on = r.get("requestedOn") or r.get("createdOn") or r.get("appliedOn") or r.get("submittedOn") or ""

        # 3. Approver / Action Taken By & Action Taken On
        act_by = ""
        act_on = ""
        approvers = r.get("approvers") or []
        if isinstance(approvers, list) and approvers:
            for app in approvers:
                if isinstance(app, dict):
                    an = (
                        app.get("displayName") or
                        app.get("name") or
                        f"{app.get('firstName', '')} {app.get('lastName', '')}"
                    ).strip()
                    ao = app.get("actionedOn") or app.get("approvedOn") or app.get("actionTakenOn") or app.get("lastModified") or ""
                    if an:
                        act_by = an
                        act_on = ao
                        if app.get("status") in (2, "Approved", "approved"):
                            break
        if not act_by:
            app_obj = r.get("actionTakenBy") or r.get("approvedBy") or r.get("approver") or {}
            if isinstance(app_obj, dict):
                act_by = (
                    app_obj.get("displayName") or
                    app_obj.get("name") or
                    f"{app_obj.get('firstName', '')} {app_obj.get('lastName', '')}"
                ).strip()
            elif isinstance(app_obj, str):
                act_by = app_obj.strip()
            act_on = act_on or r.get("actionTakenOn") or r.get("lastActionTakenOn") or r.get("approvedOn") or r.get("lastModified") or ""

        if not act_on:
            act_on = r.get("lastActionTakenOn") or r.get("actionTakenOn") or r.get("approvedOn") or r.get("lastModified") or ""

        return req_by, req_on, act_by, act_on

    @staticmethod
    def _get_leave_status_code(leave_name: str, fallback: str = "CL/SL") -> str:
        """
        Maps leave type name to its correct status abbreviation.
        Never defaults blindly to 'CLSL' regardless of leave type.
        """
        name_clean = str(leave_name or "").strip()
        nl = name_clean.lower()
        if not nl or nl == "-":
            return fallback
        if "casual" in nl and "sick" in nl:
            return "CL/SL"
        if "casual" in nl:
            return "CL"
        if "sick" in nl:
            return "SL"
        if "earned" in nl:
            return "EL"
        if "privilege" in nl:
            return "PL"
        if "annual" in nl:
            return "AL"
        if "maternity" in nl:
            return "ML"
        if "paternity" in nl:
            return "PT"
        if "compensatory" in nl or "comp" in nl:
            return "CO"
        if "bereavement" in nl:
            return "BL"
        if "wedding" in nl:
            return "WL"
        if "marriage" in nl:
            return "ML"
        if "garden" in nl:
            return "GL"
        if "wellness" in nl:
            return "WL"
        if "happiness" in nl:
            return "HL"
        if "loss of pay" in nl or "unpaid" in nl or "without pay" in nl or "lwp" in nl:
            return "LWP"
        if "floating" in nl or "optional" in nl:
            return "FL"

        # Check if name is already a standard uppercase code
        if re.match(r'^[A-Z]{1,4}(?:/[A-Z]{1,4})?$', name_clean):
            return name_clean

        # Initial letters of words before 'Leave'
        words = [w for w in re.split(r'[^a-zA-Z]', name_clean) if w and w.lower() != "leave"]
        if words:
            abbr = "".join(w[0].upper() for w in words[:3])
            if abbr:
                return abbr

        return fallback

    @staticmethod
    def _compute_applied_by(
        requester_name: Any,
        employee_name: Any,
        leave_name: str = "",
        requested_on: str = "",
        action_taken_on: str = ""
    ) -> str:
        """
        Applied By Logic:
        Admin users are Arjun S and E Janani Sri.
        If the leave or WFH applied by Admin and if it is not for themself, consider that the application is applied by Admin,
        else applied by Employee.
        If leave_name is 'Garden Leave', it is always applied by Admin.
        If requested_on and action_taken_on are identical (instant admin creation/approval), consider applied by Admin.
        """
        ln = str(leave_name or "").strip().lower()
        if "garden" in ln:
            return "Admin"

        req_str = str(requested_on or "").strip()
        act_str = str(action_taken_on or "").strip()
        has_time = (":" in req_str or "T" in req_str)

        req = str(requester_name or "").strip().lower()
        emp = str(employee_name or "").strip().lower()

        # If requester is explicitly present
        if req:
            clean_r = re.sub(r'[^a-z0-9]', '', req)
            clean_e = re.sub(r'[^a-z0-9]', '', emp)
            if clean_r and clean_r == clean_e:
                # If self-application but identical high-precision timestamp (instant admin approval), tag as Admin
                if has_time and req_str and act_str and req_str == act_str:
                    return "Admin"
                return "Employee"

            admin_users = {"arjun s", "e janani sri", "janani sri e", "janani sri", "hr ops", "admin", "hr"}
            is_admin = any(adm in req or clean_r == re.sub(r'[^a-z0-9]', '', adm) for adm in admin_users)
            if is_admin:
                return "Admin"
            return "Admin"

        # If requester not provided, check identical timestamps
        if req_str and act_str and req_str == act_str and req_str.upper() not in ("", "NA", "NONE"):
            return "Admin"

        return "Employee"

    @staticmethod
    def _compute_approved_by(action_taken_by: Any, reporting_manager: Any = "", is_admin_applied: bool = False) -> str:
        """
        Approved By Logic:
        If approved by Name matching Reporting Manager -> 'Manager'.
        Else if approved by Arjun S or E Janani Sri (or admin applied) -> 'Admin'.
        Approved By should NEVER come as 'Employee', it must always be 'Manager' or 'Admin'.
        If action_taken_by is empty/unknown:
          If is_admin_applied or reporting_manager is Admin -> 'Admin'.
          Else -> 'Manager'.
        """
        act = str(action_taken_by or "").strip().lower()
        rm = str(reporting_manager or "").strip().lower()
        admin_users = {"arjun s", "e janani sri", "janani sri e", "janani sri", "hr ops", "admin"}

        clean_act = re.sub(r'[^a-z0-9]', '', act)
        clean_rm = re.sub(r'[^a-z0-9]', '', rm)

        if clean_act:
            if clean_rm and (clean_act == clean_rm or clean_rm in clean_act or clean_act in clean_rm):
                return "Manager"
            for adm in admin_users:
                clean_adm = re.sub(r'[^a-z0-9]', '', adm)
                if clean_adm and (clean_act == clean_adm or adm in act):
                    return "Admin"

        if is_admin_applied:
            return "Admin"

        if clean_rm and any(adm in rm or clean_rm == re.sub(r'[^a-z0-9]', '', adm) for adm in admin_users):
            return "Admin"

        return "Manager"

    def fetch_od_wfh_requests(
        self,
        from_date: str = None,
        to_date: str = None,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Tuple[pd.DataFrame, Optional[str]]:
        """
        Fetches OD/WFH requests from Keka API in parallel:
          GET /time/wfh  +  GET /time/od

        Filters out any Cancelled, Rejected, Revoked, or Withdrawn applications.
        Returns a DataFrame with columns matching what absent_management.py expects:
          Employee Number, Employee Name, From Date, To Date, Request Status,
          Request Type (WFH/OD)
        """
        # Parse dates into datetime objects
        f_dt = None
        t_dt = None
        for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]:
            try:
                if not f_dt and from_date:
                    f_dt = datetime.strptime(from_date.strip(), fmt).date()
                if not t_dt and to_date:
                    t_dt = datetime.strptime(to_date.strip(), fmt).date()
            except Exception:
                pass
        if not f_dt:
            f_dt = datetime.now().replace(day=1).date()
        if not t_dt:
            t_dt = datetime.now().date()

        # Partition into safe <= 15-day intervals
        chunks = []
        c_start = f_dt
        while c_start <= t_dt:
            c_end = min(c_start + timedelta(days=14), t_dt)
            chunks.append((c_start.strftime("%Y-%m-%d"), c_end.strftime("%Y-%m-%d")))
            c_start = c_end + timedelta(days=1)

        all_rows = []
        errors = []
        status_map = {
            1: "Pending",
            2: "Approved",
            3: "Rejected",
            4: "Cancelled",
            5: "Revoked"
        }

        wfh_records = []
        od_records = []

        for c_idx, (c_from, c_to) in enumerate(chunks, 1):
            if progress_callback:
                progress_callback(f"Querying WFH and OD requests (slice {c_idx}/{len(chunks)}: {c_from} to {c_to})...")

            wfh_params = {"from": c_from, "to": c_to}
            od_params = {"from": c_from, "to": c_to}

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                future_wfh = executor.submit(self._paginated_get, "/time/wfh", wfh_params)
                future_od = executor.submit(self._paginated_get, "/time/od", od_params)

                w_recs, w_err = future_wfh.result()
                o_recs, o_err = future_od.result()

            if w_err and not w_recs:
                errors.append(f"WFH: {w_err}")
            elif w_recs:
                wfh_records.extend(w_recs)

            if o_err and not o_recs:
                errors.append(f"OD: {o_err}")
            elif o_recs:
                od_records.extend(o_recs)

            time.sleep(0.1)

        # Deduplicate records by ID
        seen_wfh = set()
        unique_wfh = []
        for r in wfh_records:
            rid = r.get("id") or str(r)
            if rid not in seen_wfh:
                seen_wfh.add(rid)
                unique_wfh.append(r)
        wfh_records = unique_wfh

        seen_od = set()
        unique_od = []
        for r in od_records:
            rid = r.get("id") or str(r)
            if rid not in seen_od:
                seen_od.add(rid)
                unique_od.append(r)
        od_records = unique_od

        for r in wfh_records:
            status_val = r.get("status", "")
            if self._is_cancelled_or_invalid_status(status_val, r):
                continue
            if isinstance(status_val, int):
                status_val = status_map.get(status_val, str(status_val))
            if self._is_cancelled_or_invalid_status(status_val):
                continue

            fs = r.get("fromSession")
            ts = r.get("toSession")
            note_str = str(r.get("note") or "").lower()
            dur_raw = r.get("duration")
            is_half = (fs is not None and ts is not None and fs == ts and fs in (0, 1)) or ("half" in note_str) or (dur_raw == 0.5)
            wfh_duration = 0.5 if is_half else 1.0
            session_str = "Full Day"
            if is_half:
                session_str = "First Half" if fs == 0 else "Second Half"

            req_by, req_on, act_by, act_on = self._extract_request_audit_info(r)
            if not act_on and str(status_val).lower() == "approved":
                act_on = r.get("lastModified") or r.get("requestedOn") or ""

            all_rows.append({
                "Employee Number": (r.get("employeeNumber") or "").strip(),
                "Employee Name": (r.get("employeeName") or "").strip(),
                "From Date": self._format_date(r.get("fromDate")),
                "To Date": self._format_date(r.get("toDate")),
                "Request Status": str(status_val).strip(),
                "Request Type": "WFH",
                "Duration": wfh_duration,
                "Session": session_str,
                "Requested By": req_by,
                "Requested On": req_on,
                "Action Taken By": act_by,
                "Action Taken On": act_on,
                "Requester": req_by,
                "Approver": act_by,
            })

        for r in od_records:
            status_val = r.get("status", "")
            if self._is_cancelled_or_invalid_status(status_val, r):
                continue
            if isinstance(status_val, int):
                status_val = status_map.get(status_val, str(status_val))
            if self._is_cancelled_or_invalid_status(status_val):
                continue

            fs = r.get("fromSession")
            ts = r.get("toSession")
            note_str = str(r.get("note") or "").lower()
            dur_raw = r.get("duration")
            is_half = (fs is not None and ts is not None and fs == ts and fs in (0, 1)) or ("half" in note_str) or (dur_raw == 0.5)
            od_duration = 0.5 if is_half else 1.0
            session_str = "Full Day"
            if is_half:
                session_str = "First Half" if fs == 0 else "Second Half"

            req_by, req_on, act_by, act_on = self._extract_request_audit_info(r)
            if not act_on and str(status_val).lower() == "approved":
                act_on = r.get("lastModified") or r.get("requestedOn") or ""

            all_rows.append({
                "Employee Number": (r.get("employeeNumber") or "").strip(),
                "Employee Name": (r.get("employeeName") or "").strip(),
                "From Date": self._format_date(r.get("fromDate")),
                "To Date": self._format_date(r.get("toDate")),
                "Request Status": str(status_val).strip(),
                "Request Type": "OD",
                "Duration": od_duration,
                "Session": session_str,
                "Requested By": req_by,
                "Requested On": req_on,
                "Action Taken By": act_by,
                "Action Taken On": act_on,
                "Requester": req_by,
                "Approver": act_by,
            })

        df = pd.DataFrame(all_rows)
        if df.empty:
            df = pd.DataFrame(columns=[
                "Employee Number", "Employee Name", "From Date", "To Date", "Request Status", "Request Type",
                "Duration", "Session", "Requested By", "Requested On", "Action Taken By", "Action Taken On", "Requester", "Approver"
            ])
        combined_err = "; ".join(errors) if errors else None
        logger.info(f"OD/WFH Requests: {len(df)} active records fetched via API ({len(wfh_records)} raw WFH, {len(od_records)} raw OD)")
        return df, combined_err


    def _solve_keka_captcha(self, driver) -> Optional[str]:
        """Detects and solves the 5-char alphanumeric Keka captcha using ddddocr."""
        global _OCR_INSTANCE
        try:
            from selenium.webdriver.common.by import By
            captcha_imgs = driver.find_elements(By.ID, "imgCaptcha")
            if not captcha_imgs or not captcha_imgs[0].is_displayed():
                return None
            
            if _OCR_INSTANCE is None:
                import ddddocr
                _OCR_INSTANCE = ddddocr.DdddOcr(show_ad=False)

            # Try up to 3 times to get a clean 5-character alphanumeric solution
            for _ in range(3):
                src = captcha_imgs[0].get_attribute("src") or ""
                if "base64," in src:
                    b64_data = src.split("base64,")[1]
                    img_bytes = base64.b64decode(b64_data)
                else:
                    img_bytes = captcha_imgs[0].screenshot_as_png

                code = _OCR_INSTANCE.classification(img_bytes)
                code_str = str(code).strip() if code else ""
                if len(code_str) == 5 and code_str.isalnum():
                    return code_str

                # If solve wasn't exactly 5 chars, click the refresh button for a new image
                refresh_btns = driver.find_elements(By.ID, "retryCaptcha")
                if refresh_btns and refresh_btns[0].is_displayed():
                    try:
                        refresh_btns[0].click()
                        time.sleep(0.6)
                        captcha_imgs = driver.find_elements(By.ID, "imgCaptcha")
                    except Exception:
                        break
                else:
                    if code_str:
                        return code_str
                    break

            return code_str if code_str else None
        except Exception as e:
            logger.warning(f"Captcha solving error: {e}")
        return None

    def _perform_portal_login(
        self,
        driver,
        wait,
        timeout: int = 25,
        otp_callback: Optional[Callable[[str], Optional[str]]] = None
    ) -> Tuple[bool, str, dict]:
        """
        Executes Keka portal login flow:
         1. Navigates to subdomain URL
         2. Checks if already authenticated via persistent session (skips login)
         3. Clicks 'Continue with Password' if on landing page
         4. Enters Email & Password
         5. Automatically detects and solves visual captcha using OCR
         6. Submits login form
         7. If 2FA OTP is required:
            - If otp_callback provided: requests code, checks 'Remember this browser', submits
            - If no callback: reports 2FA is active
         8. Detects outcome: Dashboard, 2FA prompt, or invalid credentials
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException

        try:
            sub = self.subdomain
            start_url = f"https://{sub}.keka.com"
            cur_url = (driver.current_url or "").lower()
            if not cur_url or "data:" in cur_url or "about:blank" in cur_url:
                logger.info(f"Navigating to Keka portal: {start_url}")
                try:
                    driver.get(start_url)
                except TimeoutException:
                    pass
                time.sleep(1.5)
                cur_url = (driver.current_url or "").lower()

            # Check if tenant not found immediately
            if "tenant-not-found" in cur_url or "tenantnotfound" in cur_url:
                return False, f"Keka organization tenant '{sub}' not found. Please verify your company subdomain in Settings.", {"status": "tenant_not_found"}

            # Check if already authenticated (e.g. from persisted session redirect)
            if cur_url and any(k in cur_url for k in ["/ui/#", "/#", "/home", "/dashboard", "/me", "/timeattendance"]):
                if not any(k in cur_url for k in ["/account/login", "/account/kekalogin", "/account/sendcode", "tenant-not-found"]):
                    logger.info("Already authenticated via existing session.")
                    return True, "Authenticated via active session", {"status": "authenticated"}

            # If on Account/Login landing page (which has SSO + 'Continue with Password')
            if "/account/login" in cur_url and "/kekalogin" not in cur_url:
                try:
                    continue_pwd_btns = driver.find_elements(
                        By.XPATH, "//button[contains(., 'Continue with Password')] | //a[contains(., 'Continue with Password')]"
                    )
                    disp_btns = [b for b in continue_pwd_btns if b.is_displayed()]
                    if disp_btns:
                        logger.info("Clicking 'Continue with Password'...")
                        disp_btns[0].click()
                        time.sleep(1.5)
                        cur_url = (driver.current_url or "").lower()
                except Exception as e:
                    logger.debug(f"Clicking Continue with Password: {e}")

            # If not already at 2FA verification screen, enter credentials and solve captcha
            if not any(k in cur_url for k in ["/account/sendcode", "/account/verifycode", "twofactor", "verify"]):
                if "/kekalogin" not in cur_url:
                    try:
                        driver.get(start_url)
                        time.sleep(1.5)
                        cur_url = (driver.current_url or "").lower()
                    except TimeoutException:
                        pass
                    if "/account/login" in cur_url and "/kekalogin" not in cur_url:
                        continue_pwd_btns = driver.find_elements(
                            By.XPATH, "//button[contains(., 'Continue with Password')] | //a[contains(., 'Continue with Password')]"
                        )
                        disp_btns = [b for b in continue_pwd_btns if b.is_displayed()]
                        if disp_btns:
                            disp_btns[0].click()
                            time.sleep(1.5)

                # Login form submission with automatic captcha retry loop (up to 3 attempts)
                max_captcha_attempts = 3
                for attempt in range(1, max_captcha_attempts + 1):
                    # Enter email (if not already filled)
                    email_inputs = driver.find_elements(By.CSS_SELECTOR, "input#email, input[name='Email'], input[type='email']")
                    disp_emails = [i for i in email_inputs if i.is_displayed()]
                    target_email = disp_emails[0] if disp_emails else None
                    if not target_email:
                        target_email = wait.until(EC.visibility_of_element_located(
                            (By.CSS_SELECTOR, "input#email, input[name='Email'], input[type='email']")
                        ))
                    val = target_email.get_attribute("value") or ""
                    if not val or val.strip().lower() != self.keka_email.lower():
                        try:
                            target_email.clear()
                        except Exception:
                            pass
                        try:
                            driver.execute_script("arguments[0].value = '';", target_email)
                        except Exception:
                            pass
                        target_email.send_keys(self.keka_email)

                    # Find and fill password
                    pwd_inputs = driver.find_elements(By.CSS_SELECTOR, "input#password, input[name='Password'], input[type='password']")
                    disp_pwds = [p for p in pwd_inputs if p.is_displayed()]
                    target_pwd = disp_pwds[0] if disp_pwds else None
                    if not target_pwd:
                        target_pwd = wait.until(EC.visibility_of_element_located(
                            (By.CSS_SELECTOR, "input#password, input[name='Password'], input[type='password']")
                        ))
                    try:
                        target_pwd.clear()
                    except Exception:
                        pass
                    try:
                        driver.execute_script("arguments[0].value = '';", target_pwd)
                    except Exception:
                        pass
                    target_pwd.send_keys(self.keka_password)

                    # Solve visual captcha if present
                    captcha_code = self._solve_keka_captcha(driver)
                    if captcha_code:
                        logger.info(f"Solved captcha (attempt {attempt}): {captcha_code}")
                        captcha_inputs = driver.find_elements(By.CSS_SELECTOR, "input#captcha, input[name='captcha']")
                        disp_caps = [c for c in captcha_inputs if c.is_displayed()]
                        target_cap = disp_caps[0] if disp_caps else None
                        if target_cap:
                            try:
                                target_cap.clear()
                            except Exception:
                                pass
                            try:
                                driver.execute_script("arguments[0].value = '';", target_cap)
                            except Exception:
                                pass
                            target_cap.send_keys(captcha_code)

                    # Click login button
                    login_btn = wait.until(EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(., 'Login')] | //button[contains(@class, 'btn-primary')] | button[type='submit']")
                    ))
                    login_btn.click()
                    logger.info(f"Submitted login credentials (attempt {attempt}), awaiting response...")
                    time.sleep(4)

                    post_url = (driver.current_url or "").lower()
                    # If reached 2FA screen or Dashboard, exit retry loop
                    if any(k in post_url for k in ["/account/sendcode", "/account/verifycode", "twofactor", "verify"]):
                        break
                    if any(k in post_url for k in ["/ui/#", "/home", "/dashboard", f"{self.subdomain}.keka.com"]):
                        if not any(k in post_url for k in ["/account/login", "/account/kekalogin", "/account/sendcode"]):
                            break

                    # Check for on-page captcha error
                    err_els = driver.find_elements(
                        By.CSS_SELECTOR, ".alert-danger, .validation-summary-errors, .field-validation-error, .text-danger"
                    )
                    err_text = " ".join([e.text.strip() for e in err_els if e.is_displayed() and e.text.strip()])
                    if "captcha" in err_text.lower() and attempt < max_captcha_attempts:
                        logger.info(f"Captcha rejected ('{err_text}'), retrying ({attempt + 1}/{max_captcha_attempts})...")
                        time.sleep(1)
                        continue
                    else:
                        break

            # Check post-login URL and DOM
            post_url = (driver.current_url or "").lower()
            logger.info(f"Post-login URL: {post_url}")

            if "tenant-not-found" in post_url or "tenantnotfound" in post_url:
                return False, f"Keka organization tenant '{self.subdomain}' not found. Please verify your company subdomain in Settings.", {"status": "tenant_not_found"}

            # Case A: Success (Dashboard)
            if any(k in post_url for k in ["/ui/#", "/home", "/dashboard", f"{self.subdomain}.keka.com"]):
                if not any(k in post_url for k in ["/account/login", "/account/kekalogin", "/account/sendcode", "tenant-not-found"]):
                    return True, "Login successful", {"status": "authenticated"}

            # Case B: 2FA Identity Verification (SendCode / VerifyCode / OTP)
            if any(k in post_url for k in ["/account/sendcode", "/account/verifycode", "twofactor", "verify"]):
                logger.info(f"Keka 2FA / OTP verification reached: {post_url}")

                # If on SendCode screen, trigger sending code to email
                if "/account/sendcode" in post_url:
                    send_btns = driver.find_elements(
                        By.XPATH, "//button[contains(., 'email') or contains(., 'Email')] | //button[contains(@class, 'verify-btn')] | //form[contains(@action, 'SendCode')]//button"
                    )
                    if send_btns:
                        logger.info("Triggering OTP dispatch to email...")
                        send_btns[0].click()
                        time.sleep(3)

                if otp_callback is not None:
                    logger.info("Prompting user for 2FA OTP via otp_callback...")
                    user_code = otp_callback("email")
                    if user_code and str(user_code).strip():
                        code_str = str(user_code).strip()
                        code_inputs = driver.find_elements(
                            By.CSS_SELECTOR, "input#Code, input[name='Code'], input[type='text'], input[placeholder*='code' i]"
                        )
                        if code_inputs:
                            code_inputs[0].clear()
                            code_inputs[0].send_keys(code_str)
                            logger.info(f"Entered 2FA code ({len(code_str)} chars)")

                            # Check 'Remember this browser' to persist session in Chrome profile
                            remember_boxes = driver.find_elements(
                                By.CSS_SELECTOR, "input#RememberBrowser, input[name='RememberBrowser'], input[type='checkbox']"
                            )
                            for rb in remember_boxes:
                                try:
                                    if not rb.is_selected():
                                        rb.click()
                                        logger.info("Checked 'Remember this browser' checkbox")
                                except Exception:
                                    pass

                            # Click Verify / Submit button
                            verify_btns = driver.find_elements(
                                By.XPATH, "//button[contains(., 'Verify')] | //button[contains(@class, 'btn-primary')] | //button[@type='submit']"
                            )
                            if verify_btns:
                                verify_btns[0].click()
                                logger.info("Submitted 2FA verification code, awaiting dashboard redirect...")
                                time.sleep(6)

                                post_2fa_url = (driver.current_url or "").lower()
                                if post_2fa_url and any(k in post_2fa_url for k in ["/ui/#", "/home", "/dashboard", f"{self.subdomain}.keka.com"]) and not any(k in post_2fa_url for k in ["/account/", "/login", "/verify"]):
                                    return True, "Login successful: 2FA verified and session remembered!", {"status": "authenticated"}

                                # Check for error messages on page
                                err_els = driver.find_elements(
                                    By.CSS_SELECTOR, ".alert-danger, .validation-summary-errors, .field-validation-error, .text-danger"
                                )
                                err_text = " ".join([e.text.strip() for e in err_els if e.is_displayed() and e.text.strip()])
                                if err_text:
                                    return False, f"2FA verification failed: {err_text}", {"status": "2fa_failed", "error": err_text}

                                if "verifycode" in post_2fa_url:
                                    return False, "2FA verification failed: Invalid OTP code entered.", {"status": "2fa_failed"}

                                return True, "Login successful after 2FA verification", {"status": "authenticated"}
                        else:
                            return False, "Could not find OTP input field on verification page.", {"status": "2fa_error"}
                    else:
                        return False, "2FA verification cancelled by user.", {"status": "2fa_cancelled"}
                else:
                    return True, "Credentials & Captcha verified! Keka 2FA (OTP) is active on this account.", {"status": "2fa_required"}

            # Case C: Page error alerts (invalid password, bad captcha, locked out)
            error_els = driver.find_elements(
                By.CSS_SELECTOR, ".alert-danger, .validation-summary-errors, .field-validation-error, .text-danger"
            )
            for err in error_els:
                if err.is_displayed() and err.text.strip():
                    err_msg = err.text.strip()
                    logger.warning(f"Keka login error on page: {err_msg}")
                    return False, f"Login failed: {err_msg}", {"status": "auth_failed", "error": err_msg}

            # Case D: Still on KekaLogin (possible captcha retry or timeout)
            if "/kekalogin" in post_url or "/account/login" in post_url:
                return False, "Login failed: Credentials or captcha rejected by Keka portal.", {"status": "auth_failed"}

            return True, "Portal authenticated", {"status": "authenticated"}

        except TimeoutException:
            logger.warning("Keka portal interaction timed out during login.")
            return False, "Keka portal interaction timed out while connecting or waiting for page response. Please verify your credentials and network connection.", {"status": "timeout"}
        except Exception as e:
            return False, f"Portal login error: {str(e)}", {"status": "error"}

    def test_portal_login(
        self,
        headless: bool = True,
        otp_callback: Optional[Callable[[str], Optional[str]]] = None
    ) -> Tuple[bool, str, dict]:
        """
        Tests Keka web portal login connectivity.
        Validates login email, password, and visual captcha solving.
        """
        if not self.keka_email or not self.keka_password:
            return False, "Portal login email and password are required. Set them in Settings.", {"status": "missing_credentials"}

        try:
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError as e:
            return False, f"Selenium or Chrome driver missing: {e}", {"status": "missing_dependencies"}

        profile_dir = None
        driver = None
        try:
            driver = _create_chrome_driver(profile_dir=profile_dir, headless=headless)
            wait = WebDriverWait(driver, 15)
            return self._perform_portal_login(driver, wait, timeout=15, otp_callback=otp_callback)
        except Exception as e:
            return False, f"Failed to launch Chrome driver: {str(e)[:100]}", {"status": "driver_error"}
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    # ──────────────────────────────────────────────────────────────────────────
    # REPORT 2: ATTENDANCE & DAILY PERFORMANCE REPORT (via REST API)
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _format_hours_hhmm(hours_float) -> str:
        """Converts decimal hours (e.g. 4.11) to HH:MM format (e.g. '04:06')."""
        if not hours_float or pd.isna(hours_float) or hours_float <= 0:
            return "00:00"
        h = int(hours_float)
        m = int(round((hours_float - h) * 60))
        if m >= 60:
            h += 1
            m = 0
        return f"{h:02d}:{m:02d}"

    @staticmethod
    def _format_punch_time(punch_dict) -> str:
        """Extracts and converts UTC punch timestamp to IST HH:MM string."""
        if not punch_dict or not isinstance(punch_dict, dict):
            return ""
        ts = punch_dict.get("timestamp")
        if not ts:
            return ""
        try:
            ist = timezone(timedelta(hours=5, minutes=30))
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ist)
            return dt.strftime("%H:%M")
        except Exception:
            return ""

    def fetch_leave_requests(
        self,
        from_date: str = None,
        to_date: str = None,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Tuple[list, Optional[str]]:
        """
        Fetches leave requests from Keka API: GET /time/leaverequests
        Filters out any Cancelled, Rejected, Revoked, or Withdrawn requests.
        """
        if not from_date or not to_date:
            today = datetime.now()
            first_day = today.replace(day=1)
            from_date = first_day.strftime("%Y-%m-%d")
            to_date = today.strftime("%Y-%m-%d")

        if progress_callback:
            progress_callback("Querying Leave Requests via Keka API...")

        params = {"from": from_date, "to": to_date, "pageSize": 200}
        records, err = self._paginated_get("/time/leaverequests", params, label="Leave Requests")
        valid_records = [
            r for r in (records or [])
            if not self._is_cancelled_or_invalid_status(r.get("status"), r, is_leave=True)
        ]
        return valid_records, err

    def fetch_attendance_records_api(
        self,
        from_date: str = None,
        to_date: str = None,
        emp_df: Optional[pd.DataFrame] = None,
        wfh_df: Optional[pd.DataFrame] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Tuple[pd.DataFrame, Optional[str]]:
        """
        Fetches attendance records directly via Keka REST API:
          GET /time/attendance
        and reconciles with Employee Master and Leave/WFH requests to synthesize
        the full 24-column Daily Performance Report.
        """
        import concurrent.futures

        # Standardize dates
        from_dt = None
        to_dt = None
        for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]:
            try:
                if not from_dt and from_date:
                    from_dt = datetime.strptime(from_date.strip(), fmt)
                if not to_dt and to_date:
                    to_dt = datetime.strptime(to_date.strip(), fmt)
            except Exception:
                pass
        if not from_dt:
            from_dt = datetime.now().replace(day=1)
        if not to_dt:
            to_dt = datetime.now()

        from_iso = from_dt.strftime("%Y-%m-%d")
        to_iso = to_dt.strftime("%Y-%m-%d")

        if progress_callback:
            progress_callback(0.70, f"Pulling Attendance & Leave records ({from_iso} to {to_iso}) via API...")

        # Partition into safe <= 15-day intervals so Keka 30-day API limit is never violated
        chunks = []
        c_start = from_dt.date() if isinstance(from_dt, datetime) else from_dt
        c_end_final = to_dt.date() if isinstance(to_dt, datetime) else to_dt
        while c_start <= c_end_final:
            c_end = min(c_start + timedelta(days=14), c_end_final)
            chunks.append((c_start.strftime("%Y-%m-%d"), c_end.strftime("%Y-%m-%d")))
            c_start = c_end + timedelta(days=1)

        att_records = []
        leave_records = []
        att_err = None

        for c_idx, (c_from, c_to) in enumerate(chunks, 1):
            if progress_callback:
                progress_callback(0.70 + (c_idx / len(chunks)) * 0.15, f"Pulling Attendance & Leaves ({c_from} to {c_to})...")

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                future_att = executor.submit(
                    self._paginated_get,
                    "/time/attendance",
                    {"from": c_from, "to": c_to, "pageSize": 200},
                    max_pages=50,
                    label="Attendance"
                )
                future_leave = executor.submit(
                    self._paginated_get,
                    "/time/leaverequests",
                    {"from": c_from, "to": c_to, "pageSize": 200},
                    max_pages=20,
                    label="Leaves"
                )
                c_att, c_att_err = future_att.result()
                c_lve, c_lve_err = future_leave.result()

            if c_att_err and not c_att:
                att_err = c_att_err
            elif c_att:
                att_records.extend(c_att)

            if c_lve:
                leave_records.extend(c_lve)

            time.sleep(0.15)

        # Deduplicate attendance logs by (employeeNumber, attendanceDate)
        seen_att = set()
        unique_att = []
        for a in att_records:
            k = (str(a.get("employeeNumber") or ""), str(a.get("attendanceDate") or "")[:10])
            if k not in seen_att:
                seen_att.add(k)
                unique_att.append(a)
        att_records = unique_att

        if att_err and not att_records:
            if "last three months only" in str(att_err).lower() or "allowed to access attendance summary" in str(att_err).lower():
                return pd.DataFrame(), (
                    f"Keka API 3-Month Window Limit: Keka only permits live attendance queries for the last 3 months ({att_err}). "
                    f"To analyze older months, please export the report from Keka and use 'Import Historical File'."
                )
            return pd.DataFrame(), f"Attendance API error: {att_err}"

        if progress_callback:
            progress_callback(0.85, f"Synthesizing Daily Performance report from {len(att_records)} attendance logs...")

        # 2. Build Employee lookup
        emp_map = {}
        if emp_df is not None and not emp_df.empty:
            for _, r in emp_df.iterrows():
                emp_num = str(r.get("Employee Number", "")).strip()
                if emp_num:
                    emp_map[emp_num] = r.to_dict()

        def _fmt_audit_date(raw):
            if not raw or str(raw).strip() in ("", "None", "nan", "NA"):
                return "NA"
            s = str(raw).strip()
            try:
                if "T" in s:
                    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                else:
                    dt = pd.to_datetime(s, dayfirst=True)
                if pd.notna(dt):
                    return dt.strftime("%d-%b-%y")
            except Exception:
                pass
            return s[:10]

        # 3. Build Leave lookup by (employeeNumber, YYYY-MM-DD)
        # Cancelled, rejected, or revoked leaves are strictly ignored
        leave_lookup = {}
        for lr in (leave_records or []):
            st = lr.get("status")
            if self._is_cancelled_or_invalid_status(st, lr, is_leave=True):
                continue
            if st in [0, 1] or str(st).lower() in ["pending", "approved"]:  # Pending (0) or Approved (1)
                emp_num = str(lr.get("employeeNumber") or "").strip()
                from_d_str = (lr.get("fromDate") or "")[:10]
                to_d_str = (lr.get("toDate") or "")[:10]
                sel = lr.get("selection", [])
                lt_name = sel[0].get("leaveTypeName", "Leave") if sel else "Leave"
                st_code = self._get_leave_status_code(lt_name)

                # Check if half day: selection count 0.5, or totalDuration 0.5, or "half" in name/dayType
                is_half = False
                if sel:
                    for s_item in sel:
                        c_val = s_item.get("count", 1.0)
                        dt_val = s_item.get("dayType")
                        if c_val == 0.5 or (isinstance(dt_val, str) and "half" in dt_val.lower()):
                            is_half = True
                            break
                if not is_half:
                    tot_dur = lr.get("totalDuration")
                    if tot_dur == 0.5 or "half" in str(lt_name).lower():
                        is_half = True

                count = 0.5 if is_half else 1.0
                st_text = "Approved" if (st == 1 or str(st).lower() == "approved") else "Pending"

                lr_req_by, lr_req_on, lr_act_by, lr_act_on = self._extract_request_audit_info(lr)
                fmt_lr_req_on = _fmt_audit_date(lr_req_on)
                # If approval status is Pending, Approved By & Approved On must be NA
                # If Approved, ensure approved_on is populated
                if st_text == "Approved":
                    fmt_lr_act_on = _fmt_audit_date(lr_act_on) if lr_act_on else fmt_lr_req_on
                    act_by_clean = lr_act_by if lr_act_by else "Manager"
                else:
                    fmt_lr_act_on = "NA"
                    act_by_clean = "NA"

                try:
                    cur_d = datetime.strptime(from_d_str, "%Y-%m-%d").date()
                    end_d = datetime.strptime(to_d_str, "%Y-%m-%d").date()
                    while cur_d <= end_d:
                        final_act_on = fmt_lr_act_on if (fmt_lr_act_on and fmt_lr_act_on != "NA") else (_fmt_audit_date(cur_d.strftime("%Y-%m-%d")) if st_text == "Approved" else "NA")
                        leave_lookup[(emp_num, cur_d.strftime("%Y-%m-%d"))] = {
                            "name": lt_name,
                            "status_code": st_code,
                            "status": st_text,
                            "count": count,
                            "is_half": is_half,
                            "requested_by": lr_req_by,
                            "requested_on": fmt_lr_req_on,
                            "requested_on_raw": lr_req_on,
                            "approved_by": act_by_clean,
                            "approved_on": final_act_on,
                            "approved_on_raw": lr_act_on,
                        }
                        cur_d += timedelta(days=1)
                except Exception:
                    pass

        # 4. Build WFH / OD lookups by (employeeNumber, YYYY-MM-DD)
        # Cancelled, rejected, or revoked WFH/OD requests are strictly ignored
        wfh_lookup = {}
        od_lookup = {}
        if wfh_df is not None and not wfh_df.empty:
            for _, wr in wfh_df.iterrows():
                req_status = str(wr.get("Request Status", "")).strip()
                if self._is_cancelled_or_invalid_status(req_status, wr.to_dict()):
                    continue
                emp_num = str(wr.get("Employee Number", "")).strip()
                req_type = str(wr.get("Request Type", "")).strip().upper()
                f_str = str(wr.get("From Date", "")).strip()
                t_str = str(wr.get("To Date", "")).strip()
                wr_dur = float(wr.get("Duration", 1.0) or 1.0)
                wr_sess = str(wr.get("Session", "Full Day"))
                is_half_w = (wr_dur <= 0.5) or ("half" in wr_sess.lower()) or ("half" in str(wr.get("Request Type", "")).lower())
                wr_req_by = str(wr.get("Requested By") or wr.get("Requester") or "").strip()
                wr_req_on = _fmt_audit_date(wr.get("Requested On"))
                wr_act_by = str(wr.get("Action Taken By") or wr.get("Approver") or "").strip()
                wr_act_on = _fmt_audit_date(wr.get("Action Taken On"))
                if str(req_status).lower() == "approved" and (not wr_act_on or wr_act_on == "NA"):
                    wr_act_on = wr_req_on if (wr_req_on and wr_req_on != "NA") else ""

                d_start = None
                d_end = None
                for fmt in ["%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"]:
                    try:
                        if not d_start and f_str:
                            d_start = datetime.strptime(f_str, fmt).date()
                        if not d_end and t_str:
                            d_end = datetime.strptime(t_str, fmt).date()
                    except Exception:
                        pass
                if d_start and d_end:
                    cur = d_start
                    while cur <= d_end:
                        k = (emp_num, cur.strftime("%Y-%m-%d"))
                        cur_act_on = wr_act_on if (wr_act_on and wr_act_on != "NA") else (_fmt_audit_date(cur.strftime("%Y-%m-%d")) if str(req_status).lower() == "approved" else "NA")
                        info_dict = {
                            "status": req_status,
                            "is_half": is_half_w,
                            "duration": 0.5 if is_half_w else 1.0,
                            "session": wr_sess,
                            "requested_by": wr_req_by,
                            "requested_on": wr_req_on,
                            "requested_on_raw": wr.get("Requested On"),
                            "approved_by": wr_act_by if str(req_status).lower() == "approved" else "NA",
                            "approved_on": cur_act_on,
                            "approved_on_raw": wr.get("Action Taken On"),
                        }
                        if req_type == "WFH":
                            wfh_lookup[k] = info_dict
                        elif req_type == "OD":
                            od_lookup[k] = info_dict
                        cur += timedelta(days=1)

        # 5. Build full 24-column Daily Performance rows
        perf_rows = []
        for att in att_records:
            emp_num = str(att.get("employeeNumber") or "").strip()
            emp_info = emp_map.get(emp_num, {})
            emp_name = emp_info.get("Employee Name", "")
            job_title = emp_info.get("Job Title", "")
            dept = emp_info.get("Department", "")
            sub_dept = emp_info.get("Sub Department", "")
            location = emp_info.get("Location", "")
            bu = emp_info.get("Business Unit", "Moshpit Technologies")
            rm_name = emp_info.get("Reporting Manager", "")

            att_date_str = (att.get("attendanceDate") or "")[:10]
            if not att_date_str:
                continue
            try:
                dt_obj = datetime.strptime(att_date_str, "%Y-%m-%d").date()
                first_of_month = dt_obj.replace(day=1).strftime("%Y-%m-%d")
            except Exception:
                first_of_month = ""
                dt_obj = None

            # Filter out records where attendanceDate is after Last Working Day
            lwd_val = emp_info.get("Last Working Day") or emp_info.get("LWD") or emp_info.get("exitDate") or emp_info.get("relievingDate") or emp_info.get("resignationDate") or ""
            if dt_obj and lwd_val:
                try:
                    lwd_str = str(lwd_val).strip()
                    if len(lwd_str) >= 10 and lwd_str[4] == '-' and lwd_str[7] == '-':
                        lwd_dt = pd.to_datetime(lwd_str[:10], format="%Y-%m-%d", errors="coerce")
                    else:
                        lwd_dt = pd.to_datetime(lwd_val, dayfirst=True, errors="coerce")
                    if pd.notna(lwd_dt) and dt_obj > lwd_dt.date():
                        continue  # Exclude any attendance generated after Last Working Day
                except Exception:
                    pass

            # Filter out records before Date of Joining
            doj_val = emp_info.get("Date of Joining") or emp_info.get("DOJ") or emp_info.get("joiningDate") or ""
            if dt_obj and doj_val:
                try:
                    doj_str = str(doj_val).strip()
                    if len(doj_str) >= 10 and doj_str[4] == '-' and doj_str[7] == '-':
                        doj_dt = pd.to_datetime(doj_str[:10], format="%Y-%m-%d", errors="coerce")
                    else:
                        doj_dt = pd.to_datetime(doj_val, dayfirst=True, errors="coerce")
                    if pd.notna(doj_dt) and dt_obj < doj_dt.date():
                        continue  # Exclude any attendance before Date of Joining
                except Exception:
                    pass

            day_type = att.get("dayType", 0)
            work_secs = att.get("totalWorkDurationInSeconds", 0.0) or 0.0
            eff_hours = att.get("totalEffectiveHours", 0.0) or (float(work_secs) / 3600.0)
            gross_hours = att.get("totalGrossHours", 0.0) or eff_hours
            break_duration = att.get("totalBreakDuration", 0.0) or 0.0

            in_time = self._format_punch_time(att.get("firstInOfTheDay") or att.get("firstIn"))
            out_time = self._format_punch_time(att.get("lastOutOfTheDay") or att.get("lastOut"))
            has_punch = bool(in_time or out_time)

            lookup_key = (emp_num, att_date_str)
            if lookup_key in leave_lookup:
                l_info = leave_lookup[lookup_key]
                st_code = l_info.get("status_code", "CL/SL")
                lt_name = l_info["name"]
                app_status = l_info["status"]
                is_half = l_info.get("is_half", False)
                applied_by = self._compute_applied_by(
                    l_info.get("requested_by"),
                    emp_name,
                    leave_name=lt_name,
                    requested_on=l_info.get("requested_on_raw"),
                    action_taken_on=l_info.get("approved_on_raw")
                )
                applied_on = l_info.get("requested_on") or "NA"
                if str(app_status).strip().lower() == "approved":
                    approved_by = self._compute_approved_by(l_info.get("approved_by"), rm_name, is_admin_applied=(applied_by == "Admin"))
                    approved_on = l_info.get("approved_on") or applied_on or _fmt_audit_date(att_date_str)
                else:
                    approved_by = "NA"
                    approved_on = "NA"

                if is_half:
                    # Half day leave -> TWO line items of 0.5 quantity each:
                    # Line item 1: Leave
                    perf_rows.append({
                        "Employee Number": emp_num,
                        "Employee Name": emp_name,
                        "Job Title": job_title,
                        "Business Unit": bu,
                        "Department": dept,
                        "Sub Department": sub_dept,
                        "Location": location,
                        "Reporting Manager": rm_name,
                        "Date": att_date_str,
                        "Month": first_of_month,
                        "Last Working Day": lwd_val,
                        "In Time": in_time,
                        "Out Time": out_time,
                        "Status": st_code,
                        "Attendance Type": "Leave",
                        "Leave Name": lt_name,
                        "Quantity": 0.5,
                        "Applied By": applied_by,
                        "Applied On": applied_on,
                        "Approval Status": app_status,
                        "Approved By": approved_by,
                        "Approved On": approved_on,
                        "Total Hours": self._format_hours_hhmm(gross_hours),
                        "Break Duration": self._format_hours_hhmm(break_duration),
                        "Effective Hours": self._format_hours_hhmm(eff_hours)
                    })
                    # Line item 2: Other half (Absent or Present)
                    if eff_hours >= 4.0 or has_punch:
                        other_st, other_type = "P", "Present"
                    else:
                        other_st, other_type = "A", "Absent"
                    perf_rows.append({
                        "Employee Number": emp_num,
                        "Employee Name": emp_name,
                        "Job Title": job_title,
                        "Business Unit": bu,
                        "Department": dept,
                        "Sub Department": sub_dept,
                        "Location": location,
                        "Reporting Manager": rm_name,
                        "Date": att_date_str,
                        "Month": first_of_month,
                        "Last Working Day": lwd_val,
                        "In Time": in_time if other_st == "P" else "",
                        "Out Time": out_time if other_st == "P" else "",
                        "Status": other_st,
                        "Attendance Type": other_type,
                        "Leave Name": "-",
                        "Quantity": 0.5,
                        "Applied By": "NA",
                        "Applied On": "NA",
                        "Approval Status": "NA",
                        "Approved By": "NA",
                        "Approved On": "NA",
                        "Total Hours": self._format_hours_hhmm(gross_hours) if other_st == "P" else "00:00",
                        "Break Duration": self._format_hours_hhmm(break_duration) if other_st == "P" else "00:00",
                        "Effective Hours": self._format_hours_hhmm(eff_hours) if other_st == "P" else "00:00"
                    })
                else:
                    # Full day leave
                    perf_rows.append({
                        "Employee Number": emp_num,
                        "Employee Name": emp_name,
                        "Job Title": job_title,
                        "Business Unit": bu,
                        "Department": dept,
                        "Sub Department": sub_dept,
                        "Location": location,
                        "Reporting Manager": rm_name,
                        "Date": att_date_str,
                        "Month": first_of_month,
                        "Last Working Day": lwd_val,
                        "In Time": in_time,
                        "Out Time": out_time,
                        "Status": st_code,
                        "Attendance Type": "Leave",
                        "Leave Name": lt_name,
                        "Quantity": 1.0,
                        "Applied By": applied_by,
                        "Applied On": applied_on,
                        "Approval Status": app_status,
                        "Approved By": approved_by,
                        "Approved On": approved_on,
                        "Total Hours": self._format_hours_hhmm(gross_hours),
                        "Break Duration": self._format_hours_hhmm(break_duration),
                        "Effective Hours": self._format_hours_hhmm(eff_hours)
                    })

            elif lookup_key in wfh_lookup:
                w_info = wfh_lookup[lookup_key]
                is_half_w = w_info.get("is_half", False)
                app_status = w_info.get("status", "Approved")
                applied_by = self._compute_applied_by(
                    w_info.get("requested_by"),
                    emp_name,
                    leave_name="WFH",
                    requested_on=w_info.get("requested_on_raw"),
                    action_taken_on=w_info.get("approved_on_raw")
                )
                applied_on = w_info.get("requested_on") or "NA"
                if str(app_status).strip().lower() == "approved":
                    approved_by = self._compute_approved_by(w_info.get("approved_by"), rm_name, is_admin_applied=(applied_by == "Admin"))
                    approved_on = w_info.get("approved_on") or applied_on or _fmt_audit_date(att_date_str)
                else:
                    approved_by = "NA"
                    approved_on = "NA"

                if is_half_w:
                    # Half day WFH -> TWO line items of 0.5 quantity each:
                    # Line item 1: WFH
                    perf_rows.append({
                        "Employee Number": emp_num,
                        "Employee Name": emp_name,
                        "Job Title": job_title,
                        "Business Unit": bu,
                        "Department": dept,
                        "Sub Department": sub_dept,
                        "Location": location,
                        "Reporting Manager": rm_name,
                        "Date": att_date_str,
                        "Month": first_of_month,
                        "Last Working Day": lwd_val,
                        "In Time": in_time,
                        "Out Time": out_time,
                        "Status": "WFH",
                        "Attendance Type": "Work From Home",
                        "Leave Name": "-",
                        "Quantity": 0.5,
                        "Applied By": applied_by,
                        "Applied On": applied_on,
                        "Approval Status": app_status,
                        "Approved By": approved_by,
                        "Approved On": approved_on,
                        "Total Hours": self._format_hours_hhmm(gross_hours),
                        "Break Duration": self._format_hours_hhmm(break_duration),
                        "Effective Hours": self._format_hours_hhmm(eff_hours)
                    })
                    # Line item 2: Other half (Absent or Present)
                    if eff_hours >= 4.0 or has_punch:
                        other_st, other_type = "P", "Present"
                    else:
                        other_st, other_type = "A", "Absent"
                    perf_rows.append({
                        "Employee Number": emp_num,
                        "Employee Name": emp_name,
                        "Job Title": job_title,
                        "Business Unit": bu,
                        "Department": dept,
                        "Sub Department": sub_dept,
                        "Location": location,
                        "Reporting Manager": rm_name,
                        "Date": att_date_str,
                        "Month": first_of_month,
                        "Last Working Day": lwd_val,
                        "In Time": in_time if other_st == "P" else "",
                        "Out Time": out_time if other_st == "P" else "",
                        "Status": other_st,
                        "Attendance Type": other_type,
                        "Leave Name": "-",
                        "Quantity": 0.5,
                        "Applied By": "NA",
                        "Applied On": "NA",
                        "Approval Status": "NA",
                        "Approved By": "NA",
                        "Approved On": "NA",
                        "Total Hours": self._format_hours_hhmm(gross_hours) if other_st == "P" else "00:00",
                        "Break Duration": self._format_hours_hhmm(break_duration) if other_st == "P" else "00:00",
                        "Effective Hours": self._format_hours_hhmm(eff_hours) if other_st == "P" else "00:00"
                    })
                else:
                    # Full day WFH
                    perf_rows.append({
                        "Employee Number": emp_num,
                        "Employee Name": emp_name,
                        "Job Title": job_title,
                        "Business Unit": bu,
                        "Department": dept,
                        "Sub Department": sub_dept,
                        "Location": location,
                        "Reporting Manager": rm_name,
                        "Date": att_date_str,
                        "Month": first_of_month,
                        "Last Working Day": lwd_val,
                        "In Time": in_time,
                        "Out Time": out_time,
                        "Status": "WFH",
                        "Attendance Type": "Work From Home",
                        "Leave Name": "-",
                        "Quantity": 1.0,
                        "Applied By": applied_by,
                        "Applied On": applied_on,
                        "Approval Status": app_status,
                        "Approved By": approved_by,
                        "Approved On": approved_on,
                        "Total Hours": self._format_hours_hhmm(gross_hours),
                        "Break Duration": self._format_hours_hhmm(break_duration),
                        "Effective Hours": self._format_hours_hhmm(eff_hours)
                    })

            elif lookup_key in od_lookup:
                o_info = od_lookup[lookup_key]
                app_status = o_info.get("status", "Approved")
                applied_by = self._compute_applied_by(
                    o_info.get("requested_by"),
                    emp_name,
                    leave_name="OD",
                    requested_on=o_info.get("requested_on_raw"),
                    action_taken_on=o_info.get("approved_on_raw")
                )
                applied_on = o_info.get("requested_on") or "NA"
                if str(app_status).strip().lower() == "approved":
                    approved_by = self._compute_approved_by(o_info.get("approved_by"), rm_name, is_admin_applied=(applied_by == "Admin"))
                    approved_on = o_info.get("approved_on") or applied_on or _fmt_audit_date(att_date_str)
                else:
                    approved_by = "NA"
                    approved_on = "NA"

                perf_rows.append({
                    "Employee Number": emp_num,
                    "Employee Name": emp_name,
                    "Job Title": job_title,
                    "Business Unit": bu,
                    "Department": dept,
                    "Sub Department": sub_dept,
                    "Location": location,
                    "Reporting Manager": rm_name,
                    "Date": att_date_str,
                    "Month": first_of_month,
                    "Last Working Day": lwd_val,
                    "In Time": in_time,
                    "Out Time": out_time,
                    "Status": "OD",
                    "Attendance Type": "Onduty",
                    "Leave Name": "-",
                    "Quantity": 1.0,
                    "Applied By": applied_by,
                    "Applied On": applied_on,
                    "Approval Status": app_status,
                    "Approved By": approved_by,
                    "Approved On": approved_on,
                    "Total Hours": self._format_hours_hhmm(gross_hours),
                    "Break Duration": self._format_hours_hhmm(break_duration),
                    "Effective Hours": self._format_hours_hhmm(eff_hours)
                })
            else:
                if day_type == 2:
                    if eff_hours > 0 or has_punch:
                        status = "WOW"
                        att_type = "Worked on Week off"
                    else:
                        status = "WO"
                        att_type = "Week Off"
                elif day_type == 1:
                    if eff_hours > 0 or has_punch:
                        status = "WOH"
                        att_type = "Worked on Holiday"
                    else:
                        status = "H"
                        att_type = "Holiday"
                else:  # day_type == 0 (Working Day)
                    has_in  = bool(in_time)
                    has_out = bool(out_time)
                    has_both_punches = has_in and has_out
                    # A complete swipe pair (In + Out) means the employee was genuinely Present,
                    # even if totalEffectiveHours is under-reported by Keka.
                    # P(MS) = truly missing swipe, i.e. only one side recorded.
                    if eff_hours >= 4.0 or has_both_punches:
                        status = "P"
                        att_type = "Present"
                    elif has_punch:  # Only one of In or Out recorded
                        status = "P(MS)"
                        att_type = "Missing Swipes"
                    else:
                        status = "A"
                        att_type = "Absent"

                perf_rows.append({
                    "Employee Number": emp_num,
                    "Employee Name": emp_name,
                    "Job Title": job_title,
                    "Business Unit": bu,
                    "Department": dept,
                    "Sub Department": sub_dept,
                    "Location": location,
                    "Reporting Manager": rm_name,
                    "Date": att_date_str,
                    "Month": first_of_month,
                    "Last Working Day": lwd_val,
                    "In Time": in_time,
                    "Out Time": out_time,
                    "Status": status,
                    "Attendance Type": att_type,
                    "Leave Name": "-",
                    "Quantity": 1.0,
                    "Applied By": "NA",
                    "Applied On": "NA",
                    "Approval Status": "NA",
                    "Approved By": "NA",
                    "Approved On": "NA",
                    "Total Hours": self._format_hours_hhmm(gross_hours),
                    "Break Duration": self._format_hours_hhmm(break_duration),
                    "Effective Hours": self._format_hours_hhmm(eff_hours)
                })

        df_perf = pd.DataFrame(perf_rows)
        if df_perf.empty:
            df_perf = pd.DataFrame(columns=[
                "Employee Number", "Employee Name", "Job Title", "Business Unit",
                "Department", "Sub Department", "Location", "Reporting Manager",
                "Date", "Month", "Last Working Day", "In Time", "Out Time", "Status", "Attendance Type",
                "Leave Name", "Quantity", "Applied By", "Applied On", "Approval Status",
                "Approved By", "Approved On", "Total Hours", "Break Duration", "Effective Hours"
            ])
        logger.info(f"Attendance Report: {len(df_perf)} records generated via REST API")
        return df_perf, None

    def fetch_attendance_report(
        self,
        from_date: str = None,
        to_date: str = None,
        emp_df: Optional[pd.DataFrame] = None,
        wfh_df: Optional[pd.DataFrame] = None,
        use_api: bool = True,
        download_dir: str = None,
        headless: bool = True,
        timeout: int = 120,
        otp_callback: Optional[Callable[[str], Optional[str]]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """
        Unified Attendance Report fetcher.
        1. Tries fast Keka REST API (GET /time/attendance) first.
        2. Automatically falls back to Selenium portal automation whenever:
           - REST API encounters Keka's 3-month rolling window limit (HTTP 400), OR
           - REST API is unavailable, OR
           - User has credentials configured to export full Daily Performance report.
        """
        api_err = None
        if use_api:
            try:
                df, err = self.fetch_attendance_records_api(
                    from_date=from_date,
                    to_date=to_date,
                    emp_df=emp_df,
                    wfh_df=wfh_df,
                    progress_callback=progress_callback
                )
                if df is not None and not df.empty:
                    return df, None
                api_err = err
                logger.info(f"REST API attendance fetch could not complete ({err}). Triggering Keka Portal fallback...")
            except Exception as e:
                api_err = str(e)
                logger.warning(f"Attendance API exception ({e}), triggering Keka Portal fallback...")

        # If user has Keka portal credentials or saved browser session, run Selenium portal export
        has_creds = bool(self.keka_email and self.keka_password)
        has_profile = (Path.home() / ".keka_chrome_profile").exists()
        if has_creds or has_profile:
            if progress_callback:
                progress_callback(0.65, f"Pulling {from_date} to {to_date} via Keka Web Portal exporter...")
            df_sel, sel_err = self.fetch_attendance_report_selenium(
                from_date=from_date,
                to_date=to_date,
                download_dir=download_dir,
                headless=headless,
                timeout=timeout,
                otp_callback=otp_callback,
                progress_callback=progress_callback
            )
            if df_sel is not None and not df_sel.empty:
                return df_sel, None
            if sel_err:
                return None, f"REST API: {api_err}\nPortal Export: {sel_err}"

        # If Selenium could not run or no credentials, return informative message
        if api_err:
            if "last three months only" in str(api_err).lower() or "3-month" in str(api_err).lower():
                return None, (
                    f"Keka API only allows attendance queries for the last 3 months via REST API ({api_err}).\n\n"
                    "To pull older historical months directly from Keka, enter your Keka login email/password in Settings "
                    "to enable automated portal export, or use 'Import Historical File'."
                )
            return None, api_err
        return None, "No attendance records returned from Keka."

    # ──────────────────────────────────────────────────────────────────────────
    # REPORT 2 FALLBACK: ATTENDANCE REPORT (via Selenium — portal export)
    # ──────────────────────────────────────────────────────────────────────────
    def fetch_attendance_report_selenium(
        self,
        from_date: str = None,
        to_date: str = None,
        download_dir: str = None,
        headless: bool = True,
        timeout: int = 120,
        otp_callback: Optional[Callable[[str], Optional[str]]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """
        Downloads the Daily Performance report from Keka's portal using Selenium.
        Target URL: https://{subdomain}.keka.com/#/timeattendance/reports/attendance/dailyperformance

        Steps:
          1. Login to https://{subdomain}.keka.com (reusing profile session)
          2. Navigate directly to #/timeattendance/reports/attendance/dailyperformance
          3. Check 'Recently downloaded reports' table for matching date range
          4. If not found in table, set Date Range and click 'View Report'
          5. Click 'Download report' -> Excel, or download newly generated row
          6. Parse downloaded Excel into a DataFrame
        """
        if not self.keka_email or not self.keka_password:
            return None, (
                "Keka portal login credentials required for Attendance Report.\n"
                "Set KEKA_LOGIN_EMAIL and KEKA_LOGIN_PASSWORD in .env file or Settings."
            )

        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service as ChromeService
            from selenium.webdriver.chrome.options import Options as ChromeOptions
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.common.exceptions import TimeoutException
        except ImportError:
            return None, (
                "Selenium not installed. Run:\n"
                "  pip install selenium webdriver-manager ddddocr\n"
                "Then retry."
            )

        try:
            from webdriver_manager.chrome import ChromeDriverManager
        except ImportError:
            return None, "webdriver-manager not installed. Run: pip install webdriver-manager"

        # Setup download directory
        if not download_dir:
            download_dir = str(Path.home() / "Downloads" / "keka_reports")
        Path(download_dir).mkdir(parents=True, exist_ok=True)

        # Default dates
        if not from_date or not to_date:
            today = datetime.now()
            first_day = today.replace(day=1)
            from_date = first_day.strftime("%d-%m-%Y")
            to_date = today.strftime("%d-%m-%Y")

        # Parse requested date objects for smart matching
        from_dt = None
        to_dt = None
        for fmt in ["%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"]:
            try:
                if not from_dt and from_date:
                    from_dt = datetime.strptime(from_date.strip(), fmt)
                if not to_dt and to_date:
                    to_dt = datetime.strptime(to_date.strip(), fmt)
            except Exception:
                pass
        if not from_dt:
            from_dt = datetime.now().replace(day=1)
        if not to_dt:
            to_dt = datetime.now()

        profile_dir = Path.home() / ".keka_chrome_profile"
        driver = None
        try:
            if progress_callback:
                progress_callback(0.68, "Launching Chrome and authenticating with Keka portal...")

            driver = _create_chrome_driver(profile_dir, headless=headless, download_dir=download_dir)
            wait = WebDriverWait(driver, timeout)

            # ── Step 1: Login ──
            login_ok, login_msg, details = self._perform_portal_login(
                driver, wait, timeout=min(timeout, 30), otp_callback=otp_callback
            )
            if not login_ok:
                return None, f"Keka portal login failed: {login_msg}"

            if details.get("status") == "2fa_required":
                return None, (
                    "Keka 2FA (OTP identity verification) is active on this account.\n"
                    "Please authorize your session once via 'Authorize in Browser 🌐' in Settings\n"
                    "or provide the 6-digit OTP code when prompted."
                )

            # ── Step 2: Navigate directly to Daily Performance report ──
            if progress_callback:
                progress_callback(0.74, "Navigating to Daily Performance report...")

            daily_perf_url = f"https://{self.subdomain}.keka.com/#/timeattendance/reports/attendance/dailyperformance"
            logger.info(f"Navigating to Daily Performance report: {daily_perf_url}")
            driver.get(daily_perf_url)
            time.sleep(5)

            cur_url = (driver.current_url or "").lower()
            if "dailyperformance" not in cur_url:
                try:
                    driver.execute_script("window.location.hash = '/timeattendance/reports/attendance/dailyperformance';")
                    time.sleep(4)
                except Exception:
                    pass

            # Snapshot existing files in download directory
            existing_files = set(Path(download_dir).glob("*.xlsx")) | set(Path(download_dir).glob("*.xls"))

            # ── Step 3: Check 'Recently downloaded reports' table for quick match ──
            date_str_exact = f"{from_dt.strftime('%d %b %Y')} - {to_dt.strftime('%d %b %Y')}".lower()
            month_year = from_dt.strftime("%b %Y").lower()

            download_triggered = False
            table_rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr, .ag-center-cols-container .ag-row")
            logger.info(f"Checking {len(table_rows)} recently downloaded reports for date match ({date_str_exact})...")

            for row in table_rows:
                try:
                    row_text = row.text.lower()
                    if date_str_exact in row_text or (month_year in row_text and str(from_dt.day) in row_text and str(to_dt.day) in row_text):
                        dl_btn = row.find_elements(By.XPATH, ".//button[contains(., 'Download')] | .//a[contains(., 'Download')]")
                        if dl_btn:
                            logger.info(f"Found existing generated report in table: '{row.text.replace(chr(10), ' | ')[:60]}'")
                            if progress_callback:
                                progress_callback(0.88, f"Found existing {from_date} to {to_date} report in Keka. Downloading...")
                            driver.execute_script("arguments[0].click();", dl_btn[0])
                            download_triggered = True
                            time.sleep(2)
                            break
                except Exception:
                    continue

            # ── Step 4: If not matched in table, generate new report ──
            if not download_triggered:
                if progress_callback:
                    progress_callback(0.80, f"Selecting Date Range ({from_date} to {to_date})...")

                # Open Date Range dropdown
                cal_triggers = driver.find_elements(
                    By.CSS_SELECTOR,
                    "#bsdrp, a[id*='dateRange'], a[dropdowntoggle], .filter.dropdown, span.ki-calendar"
                )
                for ct in cal_triggers:
                    if ct.is_displayed():
                        try:
                            driver.execute_script("arguments[0].click();", ct)
                            time.sleep(1)
                            break
                        except Exception:
                            pass

                # Choose best range option
                days_diff = (to_dt - from_dt).days
                now = datetime.now()
                is_recent = abs((now - to_dt).days) <= 2

                if days_diff <= 7 and is_recent:
                    target_opt_name = "Last 7 days"
                elif days_diff <= 14 and is_recent:
                    target_opt_name = "Last 14 days"
                elif days_diff <= 31 and is_recent:
                    target_opt_name = "Last 30 days"
                else:
                    target_opt_name = "Custom Range"

                option_clicked = False
                opts = driver.find_elements(
                    By.XPATH,
                    f"//a[contains(text(), '{target_opt_name}')] | //button[contains(text(), '{target_opt_name}')] | //li[contains(., '{target_opt_name}')]"
                )
                for op in opts:
                    if op.is_displayed():
                        driver.execute_script("arguments[0].click();", op)
                        logger.info(f"Selected date range preset: {target_opt_name}")
                        option_clicked = True
                        time.sleep(1.5)
                        break

                if not option_clicked:
                    any_opts = driver.find_elements(By.CSS_SELECTOR, ".dropdown-menu a.dropdown-item, .dropdown-menu li a")
                    for ao in any_opts:
                        if ao.is_displayed() and ("30" in ao.text or "custom" in ao.text.lower()):
                            driver.execute_script("arguments[0].click();", ao)
                            time.sleep(1.5)
                            break

                # Step 4b: Click 'View Report' to generate view and enable download
                if progress_callback:
                    progress_callback(0.85, "Generating report preview ('View Report')...")
                view_btns = driver.find_elements(
                    By.XPATH,
                    "//a[contains(., 'View Report')] | //button[contains(., 'View Report')] | //*[contains(@class, 'text-link') and contains(., 'View Report')]"
                )
                for vb in view_btns:
                    if vb.is_displayed():
                        try:
                            driver.execute_script("arguments[0].click();", vb)
                            logger.info("Clicked 'View Report'")
                            time.sleep(4)
                            break
                        except Exception:
                            pass

                # Step 4c: Click 'Download report' button
                if progress_callback:
                    progress_callback(0.90, "Exporting Daily Performance report to Excel...")

                dl_btns = driver.find_elements(
                    By.XPATH,
                    "//button[contains(., 'Download report')] | //button[@id='dropdown-menu'] | //div[contains(@class, 'buttons-container')]//button"
                )
                for db in dl_btns:
                    if db.is_displayed():
                        try:
                            driver.execute_script("arguments[0].click();", db)
                            logger.info("Clicked 'Download report' dropdown button")
                            time.sleep(2)
                            break
                        except Exception:
                            pass

                # Step 4d: Click Excel option in dropdown
                excel_opts = driver.find_elements(
                    By.XPATH,
                    "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'excel')] | //button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'excel')] | //a[contains(., '.xlsx')] | //a[contains(@class, 'dropdown-item')]"
                )
                for eo in excel_opts:
                    if eo.is_displayed():
                        try:
                            driver.execute_script("arguments[0].click();", eo)
                            logger.info(f"Clicked Excel export option: {eo.text.strip()}")
                            download_triggered = True
                            time.sleep(3)
                            break
                        except Exception:
                            pass

                # Fallback: check if row was generated in table and has Download button
                if not download_triggered:
                    time.sleep(3)
                    new_table_rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr, .ag-center-cols-container .ag-row")
                    if new_table_rows:
                        top_dl = new_table_rows[0].find_elements(By.XPATH, ".//button[contains(., 'Download')] | .//a[contains(., 'Download')]")
                        if top_dl:
                            logger.info("Clicking Download on top row of recently generated reports...")
                            driver.execute_script("arguments[0].click();", top_dl[0])
                            download_triggered = True

            # ── Step 5: Wait for download to finish ──
            if progress_callback:
                progress_callback(0.94, "Awaiting Excel file download...")
            new_file = self._wait_for_download(download_dir, existing_files, timeout=60)
            if not new_file:
                # If no new file detected, check if any recently downloaded file matches
                recent_files = sorted(
                    Path(download_dir).glob("Daily Performance*.xlsx"),
                    key=os.path.getmtime,
                    reverse=True
                )
                if recent_files and (time.time() - os.path.getmtime(recent_files[0])) < 180:
                    new_file = recent_files[0]
                else:
                    return None, "Download timed out. No new Excel file detected in download directory."

            # ── Step 6: Parse downloaded Excel ──
            if progress_callback:
                progress_callback(0.98, f"Parsing downloaded file: {Path(new_file).name}...")
            logger.info(f"Parsing downloaded file: {new_file}")
            df = pd.read_excel(str(new_file))
            df = self._normalize_attendance_df(df)
            return df, None

        except TimeoutException:
            return None, "Keka portal interaction timed out. Check your credentials and network."
        except Exception as e:
            return None, f"Selenium error: {e}"
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    @staticmethod
    def _normalize_attendance_df(df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalizes attendance DataFrames:
          1. Drops records where Date is after Last Working Day (LWD).
          2. Splits composite half-day entries (e.g. 'CL/SL:A', 'A:CL/SL', 'WFH:A')
             into two separate rows with 0.5 quantity each.
          3. Replaces any Quantity 0 with 1.0 (or 0.5 for half days).
          4. Maps any hardcoded 'CLSL' to proper leave code using leave name.
          5. Ensures approved records always have Approved On populated.
        """
        if df is None or df.empty:
            return df

        # 1. Filter out rows where Date is after Last Working Day
        date_col = next((c for c in df.columns if str(c).strip().lower() in ("date", "attendance date")), None)
        lwd_col = next((c for c in df.columns if str(c).strip().lower() in ("last working day", "lwd", "last working date", "relieving date", "exit date")), None)

        if date_col and lwd_col:
            def is_after_lwd(r):
                d_val = r.get(date_col)
                l_val = r.get(lwd_col)
                if pd.isna(d_val) or pd.isna(l_val) or not str(l_val).strip() or str(l_val).strip().lower() in ("nan", "nat", "none", "na", "-", "#n/a"):
                    return False
                try:
                    d_dt = pd.to_datetime(d_val, dayfirst=True, errors="coerce")
                    l_dt = pd.to_datetime(l_val, dayfirst=True, errors="coerce")
                    if pd.notna(d_dt) and pd.notna(l_dt) and d_dt.date() > l_dt.date():
                        return True
                except Exception:
                    pass
                return False
            valid_mask = ~df.apply(is_after_lwd, axis=1)
            df = df[valid_mask].copy()

        # 2. Split composite colon rows (e.g. 'CL/SL:A') into two line items of 0.5 quantity each
        status_col = next((c for c in df.columns if str(c).strip().lower() in ("status", "attendance status")), None)
        if not status_col:
            return df

        rows = []
        for _, row in df.iterrows():
            st_val = str(row.get(status_col) or "").strip()
            if ":" in st_val:
                parts = [p.strip() for p in st_val.split(":", 1)]
                p1, p2 = parts[0], parts[1]

                # Row 1
                r1 = row.to_dict()
                r1[status_col] = p1
                r1["Quantity"] = 0.5
                if p1 == "A":
                    if "Attendance Type" in r1:
                        r1["Attendance Type"] = "Absent"
                    r1["Leave Name"] = "-"
                    r1["Applied By"] = "NA"
                    r1["Applied On"] = "NA"
                    r1["Approval Status"] = "NA"
                    r1["Approved By"] = "NA"
                    r1["Approved On"] = "NA"
                elif p1 in ("P", "P(MS)", "MS"):
                    if "Attendance Type" in r1:
                        r1["Attendance Type"] = "Present" if p1 == "P" else "Missing Swipes"
                    r1["Leave Name"] = "-"
                elif p1 == "WFH":
                    if "Attendance Type" in r1:
                        r1["Attendance Type"] = "Work From Home"
                    r1["Leave Name"] = "-"
                else:
                    if "Attendance Type" in r1:
                        r1["Attendance Type"] = "Leave"
                    if str(r1.get("Leave Name", "")).strip() in ("-", ""):
                        r1["Leave Name"] = p1
                    r1[status_col] = KekaDataFetcher._get_leave_status_code(r1.get("Leave Name", p1))

                # Row 2
                r2 = row.to_dict()
                r2[status_col] = p2
                r2["Quantity"] = 0.5
                if p2 == "A":
                    if "Attendance Type" in r2:
                        r2["Attendance Type"] = "Absent"
                    r2["Leave Name"] = "-"
                    r2["Applied By"] = "NA"
                    r2["Applied On"] = "NA"
                    r2["Approval Status"] = "NA"
                    r2["Approved By"] = "NA"
                    r2["Approved On"] = "NA"
                elif p2 in ("P", "P(MS)", "MS"):
                    if "Attendance Type" in r2:
                        r2["Attendance Type"] = "Present" if p2 == "P" else "Missing Swipes"
                    r2["Leave Name"] = "-"
                    r2["Applied By"] = "NA"
                    r2["Applied On"] = "NA"
                    r2["Approval Status"] = "NA"
                    r2["Approved By"] = "NA"
                    r2["Approved On"] = "NA"
                elif p2 == "WFH":
                    if "Attendance Type" in r2:
                        r2["Attendance Type"] = "Work From Home"
                    r2["Leave Name"] = "-"
                else:
                    if "Attendance Type" in r2:
                        r2["Attendance Type"] = "Leave"
                    if str(r2.get("Leave Name", "")).strip() in ("-", ""):
                        r2["Leave Name"] = p2
                    r2[status_col] = KekaDataFetcher._get_leave_status_code(r2.get("Leave Name", p2))

                rows.extend([r1, r2])
            else:
                r = row.to_dict()
                # Check status CLSL -> map to proper leave code
                if r.get(status_col) == "CLSL":
                    r[status_col] = KekaDataFetcher._get_leave_status_code(r.get("Leave Name", ""))
                # Ensure no quantity 0!
                try:
                    q = float(r.get("Quantity", 1.0) or 0.0)
                    if 0 < q <= 0.5:
                        r["Quantity"] = 0.5
                    else:
                        r["Quantity"] = 1.0
                except (ValueError, TypeError):
                    r["Quantity"] = 1.0

                # Ensure Approved rows have Approved On
                app_st = str(r.get("Approval Status", "")).strip().lower()
                if app_st == "approved":
                    if str(r.get("Approved By", "")).strip() not in ("NA", "") and str(r.get("Approved On", "")).strip() in ("NA", ""):
                        r["Approved On"] = r.get("Applied On") or r.get("Date") or "NA"
                rows.append(r)

        return pd.DataFrame(rows)

    @staticmethod
    def _to_excel_date(val: Any) -> Any:
        """Parses string or datetime value into Python date object for Excel date format."""
        if val is None or pd.isna(val):
            return None
        if isinstance(val, datetime):
            return val.date()
        if isinstance(val, date):
            return val
        s = str(val).strip()
        if not s or s.upper() in ("NA", "N/A", "NONE", "NULL", "-", "NAN"):
            return s
        for fmt in (
            "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d",
            "%d-%b-%y", "%d-%b-%Y", "%d-%B-%Y", "%d-%m-%y",
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
            "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"
        ):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                pass
        try:
            dt = pd.to_datetime(s, errors="coerce")
            if pd.notna(dt):
                return dt.date()
        except Exception:
            pass
        return s

    @staticmethod
    def _save_styled_excel(df: pd.DataFrame, file_path: Union[str, Path], sheet_name: str = "Sheet1"):
        """Saves DataFrame as Excel with #00FF99 bold header fill, Calibri font, and no borders."""
        from openpyxl.styles import Font, PatternFill, Border
        font_header = Font(name="Calibri", size=11, bold=True)
        font_data = Font(name="Calibri", size=10, bold=False)
        fill_header = PatternFill(start_color="00FF99", end_color="00FF99", fill_type="solid")
        no_border = Border()

        out_file = Path(file_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(str(out_file), engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
            ws = writer.sheets[sheet_name]
            date_col_indices = set()
            for col_idx in range(1, ws.max_column + 1):
                h_val = str(ws.cell(row=1, column=col_idx).value or "").strip().lower()
                if any(term in h_val for term in ["date", "last working day", "applied on", "approved on", "requested on", "action taken on", "exit date"]):
                    date_col_indices.add(col_idx)

            for row in ws.iter_rows():
                for cell in row:
                    cell.border = no_border
                    if cell.row == 1:
                        cell.font = font_header
                        cell.fill = fill_header
                    else:
                        cell.font = font_data
                        if cell.column in date_col_indices or isinstance(cell.value, (datetime, date)):
                            d_obj = KekaDataFetcher._to_excel_date(cell.value)
                            if isinstance(d_obj, (datetime, date)):
                                cell.value = d_obj if isinstance(d_obj, date) else d_obj.date()
                                cell.number_format = "dd-mmm-yy"

    @staticmethod
    def _save_unified_workbook(df_perf: pd.DataFrame, df_mailer: pd.DataFrame, file_path: Union[str, Path]):
        """Saves unified multi-sheet workbook (Daily Performance + Absent Mailer) with #00FF99 bold header fill, Calibri font, and no borders."""
        from openpyxl.styles import Font, PatternFill, Border
        font_header = Font(name="Calibri", size=10, bold=True)
        font_data = Font(name="Calibri", size=10, bold=False)
        fill_header = PatternFill(start_color="00FF99", end_color="00FF99", fill_type="solid")
        no_border = Border()

        out_file = Path(file_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(str(out_file), engine="openpyxl") as writer:
            df_perf.to_excel(writer, index=False, sheet_name="Daily Performance")
            df_mailer.to_excel(writer, index=False, sheet_name="Absent Mailer")

            for sheetname in writer.sheets:
                ws = writer.sheets[sheetname]
                date_col_indices = set()
                for col_idx in range(1, ws.max_column + 1):
                    h_val = str(ws.cell(row=1, column=col_idx).value or "").strip().lower()
                    if any(term in h_val for term in ["date", "last working day", "applied on", "approved on", "requested on", "action taken on", "exit date"]):
                        date_col_indices.add(col_idx)

                for row in ws.iter_rows():
                    for cell in row:
                        cell.border = no_border
                        if cell.row == 1:
                            cell.font = font_header
                            cell.fill = fill_header
                        else:
                            cell.font = font_data
                            if cell.column in date_col_indices or isinstance(cell.value, (datetime, date)):
                                d_obj = KekaDataFetcher._to_excel_date(cell.value)
                                if isinstance(d_obj, (datetime, date)):
                                    cell.value = d_obj if isinstance(d_obj, date) else d_obj.date()
                                    cell.number_format = "dd-mmm-yy"

    def fetch_unified_time_leave_reports(
        self,
        from_date: str = None,
        to_date: str = None,
        output_file_path: str = None,
        progress_callback: Optional[Callable[[float, str, str], None]] = None
    ) -> dict:
        """
        Unified Time & Leave Master API sync:
        Pulls Employee Master, OD/WFH Requests, and Attendance Logs via API,
        reconciles all managers and admin roles, and writes the consolidated
        multi-sheet workbook (Daily Performance + Absent Mailer).
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not output_file_path:
            output_file_path = str(Path(self._get_default_output_dir()) / f"Time_and_Leave_Master_Unified_{timestamp}.xlsx")

        def _notify(pct: float, step: str, detail: str):
            if progress_callback:
                progress_callback(pct, step, detail)

        _notify(0.05, "[1/3] Fetching Employee Master...", "Querying /hris/employees...")
        emp_df, emp_err = self.fetch_employee_master()
        if emp_err and (emp_df is None or emp_df.empty):
            raise RuntimeError(f"Employee Master fetch failed: {emp_err}")

        _notify(0.35, "[2/3] Fetching OD/WFH Requests...", "Querying /time/wfh and /time/od...")
        wfh_df, wfh_err = self.fetch_od_wfh_requests(from_date=from_date, to_date=to_date)

        _notify(0.60, "[3/3] Fetching Attendance & Leaves...", "Querying /time/attendance and /time/leaverequests...")
        att_df, att_err = self.fetch_attendance_records_api(
            from_date=from_date,
            to_date=to_date,
            emp_df=emp_df,
            wfh_df=wfh_df,
            progress_callback=lambda p, m: _notify(0.60 + p * 0.30, "[3/3] Attendance & Leaves", m)
        )
        if att_err and (att_df is None or att_df.empty):
            raise RuntimeError(f"Attendance fetch failed: {att_err}")

        # Build email_map and rm_email_map from emp_df
        email_map = {}
        rm_email_map = {}
        if not emp_df.empty:
            for _, er in emp_df.iterrows():
                eno = str(er.get("Employee Number", "")).strip()
                if eno:
                    email_map[eno] = str(er.get("Work Email", "")).strip()
                    rm_email_map[eno] = str(er.get("Reporting Manager Email", "") or er.get("RM Mail ID", "")).strip()

        # Safeguard: if Approval Status is Pending or not Approved,
        # Approved By and Approved On MUST be "NA"
        if "Approval Status" in att_df.columns:
            not_appr = att_df["Approval Status"].astype(str).str.strip().str.lower() != "approved"
            if "Approved By" in att_df.columns:
                att_df.loc[not_appr, "Approved By"] = "NA"
            if "Approved On" in att_df.columns:
                att_df.loc[not_appr, "Approved On"] = "NA"

        # Build Absent Mailer sheet from att_df
        absent_mask = (
            att_df["Status"].astype(str).str.strip().str.upper().isin(["A", "P(MS)", "MS"]) |
            att_df["Status"].astype(str).str.contains(r'(?:^|:)A(?::|$)|P\(MS\)', regex=True) |
            att_df["Attendance Type"].astype(str).str.strip().str.lower().isin(["absent", "missing swipes"])
        )
        df_mailer_src = att_df[absent_mask].copy() if absent_mask.any() else pd.DataFrame(columns=att_df.columns)

        df_mailer = pd.DataFrame()
        df_mailer["Employee Number"] = df_mailer_src["Employee Number"]
        df_mailer["Employee Name"] = df_mailer_src["Employee Name"]
        df_mailer["Date"] = df_mailer_src["Date"]
        df_mailer["Status"] = df_mailer_src["Status"]
        df_mailer["Quantity"] = df_mailer_src["Quantity"].apply(
            lambda q: 0.5 if (float(q) > 0 and float(q) <= 0.5) else 1.0
        )
        df_mailer["Employee Mail ID"] = df_mailer_src["Employee Number"].map(email_map).fillna("")
        df_mailer["Reporting Manager"] = df_mailer_src["Reporting Manager"]
        df_mailer["RM Mail ID"] = df_mailer_src["Employee Number"].map(rm_email_map).fillna("")
        df_mailer["Location"] = df_mailer_src["Location"]
        df_mailer["Month"] = df_mailer_src["Month"]
        df_mailer["Last Working Day"] = df_mailer_src["Last Working Day"]

        _notify(0.95, "Saving Unified Workbook...", f"Writing {len(att_df)} rows to {Path(output_file_path).name}")
        self._save_unified_workbook(att_df, df_mailer, output_file_path)
        _notify(1.0, "Complete! ⚡", f"Unified workbook saved successfully with Daily Performance & Absent Mailer sheets")

        return {
            "output_path": output_file_path,
            "total_attendance_rows": len(att_df),
            "absent_mailer_rows": len(df_mailer),
            "total_employees": len(emp_df),
            "total_wfh_requests": len(wfh_df),
            "errors": [e for e in [emp_err, wfh_err, att_err] if e]
        }

    # ──────────────────────────────────────────────────────────────────────────
    # CONVENIENCE: Fetch all 3 reports and save to Excel files
    # ──────────────────────────────────────────────────────────────────────────
    def fetch_all_reports(
        self,
        from_date: str = None,
        to_date: str = None,
        output_dir: str = None,
        attendance_excel_path: str = None,
        headless: bool = True
    ) -> dict:
        """
        Fetches all 3 reports needed for Absent Management.

        Args:
            from_date: Start date (YYYY-MM-DD for API, DD-MM-YYYY for portal)
            to_date: End date
            output_dir: Where to save the Excel files
            attendance_excel_path: If provided, use this pre-downloaded Excel
                                   instead of Selenium (for manual fallback)
            headless: Run Selenium in headless mode

        Returns dict with keys: emp_master_path, attendance_path, od_wfh_path, errors
        """
        if not output_dir:
            output_dir = str(Path.cwd() / "local_data" / "keka_exports")
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        result = {
            "emp_master_path": None,
            "attendance_path": None,
            "od_wfh_path": None,
            "errors": []
        }

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # ── Report 1: Employee Master (API) ──
        logger.info("Fetching Employee Master via API...")
        emp_df, emp_err = self.fetch_employee_master()
        if emp_err:
            result["errors"].append(f"Employee Master: {emp_err}")
        if not emp_df.empty:
            emp_path = Path(output_dir) / f"Employee_Master_{timestamp}.xlsx"
            self._save_styled_excel(emp_df, emp_path, "Employee Master")
            result["emp_master_path"] = str(emp_path)
            logger.info(f"✅ Employee Master saved: {emp_path} ({len(emp_df)} employees)")

        # ── Report 3: OD/WFH Requests (API) ──
        logger.info("Fetching OD/WFH Requests via API...")
        wfh_df, wfh_err = self.fetch_od_wfh_requests(from_date=from_date, to_date=to_date)
        if wfh_err:
            result["errors"].append(f"OD/WFH: {wfh_err}")
        if not wfh_df.empty:
            wfh_path = Path(output_dir) / f"OD_WFH_Requests_{timestamp}.xlsx"
            self._save_styled_excel(wfh_df, wfh_path, "OD WFH Requests")
            result["od_wfh_path"] = str(wfh_path)
            logger.info(f"✅ OD/WFH Requests saved: {wfh_path} ({len(wfh_df)} records)")

        # ── Report 2: Attendance (API first, with portal fallback) ──
        if attendance_excel_path and Path(attendance_excel_path).is_file():
            # Manual fallback: use pre-downloaded file
            result["attendance_path"] = attendance_excel_path
            logger.info(f"✅ Attendance Report: using pre-downloaded file → {attendance_excel_path}")
        else:
            logger.info("Fetching Attendance Report via REST API...")
            att_df, att_err = self.fetch_attendance_report(
                from_date=from_date,
                to_date=to_date,
                emp_df=emp_df,
                wfh_df=wfh_df,
                use_api=True,
                headless=headless
            )
            if att_err:
                result["errors"].append(f"Attendance: {att_err}")
            if att_df is not None and not att_df.empty:
                att_path = Path(output_dir) / f"Daily_Performance_Report_{timestamp}.xlsx"
                self._save_styled_excel(att_df, att_path, "Daily Performance")
                result["attendance_path"] = str(att_path)
                logger.info(f"✅ Attendance Report saved: {att_path} ({len(att_df)} records)")
            else:
                result["errors"].append(
                    "Attendance report could not be fetched automatically. "
                    "Download it manually from Keka portal: "
                    f"https://{self.subdomain}.keka.com → Time & Attend → Reports → Daily Performance"
                )

        return result

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _format_date(date_val) -> str:
        """Converts ISO date string to DD-MM-YYYY format."""
        if not date_val:
            return ""
        try:
            if isinstance(date_val, str):
                dt = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
            else:
                dt = pd.to_datetime(date_val)
            return dt.strftime("%d-%m-%Y")
        except Exception:
            return str(date_val)

    @staticmethod
    def _wait_for_download(download_dir: str, existing_files: set, timeout: int = 60) -> Optional[Path]:
        """Waits for a new .xlsx/.xls file to appear in download_dir."""
        start = time.time()
        while time.time() - start < timeout:
            current_files = set(Path(download_dir).glob("*.xlsx")) | set(Path(download_dir).glob("*.xls"))
            new_files = current_files - existing_files
            # Filter out partial downloads (.crdownload, .tmp)
            complete = [f for f in new_files if not str(f).endswith((".crdownload", ".tmp", ".part"))]
            if complete:
                # Wait a moment for file to finish writing
                time.sleep(2)
                return complete[0]
            time.sleep(1)
        return None


def check_keka_portal_status(
    email: str = None,
    password: str = None,
    subdomain: str = None,
    headless: bool = True,
    otp_callback: Optional[Callable[[str], Optional[str]]] = None
) -> Tuple[bool, str, dict]:
    """
    Public helper to test Keka web portal login connectivity.
    Validates portal credentials, visual captcha solving, and optional 2FA OTP callback.
    """
    fetcher = KekaDataFetcher(
        subdomain=subdomain,
        keka_email=email,
        keka_password=password
    )
    return fetcher.test_portal_login(headless=headless, otp_callback=otp_callback)


def launch_interactive_browser_session(
    subdomain: str = None,
    keka_email: str = None,
    keka_password: str = None,
    timeout: int = 180,
    on_status_update: Optional[Callable[[str], None]] = None
) -> Tuple[bool, str, dict]:
    """
    Launches an interactive (visible) Chrome window using the persistent profile
    (~/.keka_chrome_profile).

    This provides a seamless way to complete 2FA or Single Sign-On (SSO):
      1. Single Sign-On (SSO): Click 'Office 365' or 'Google' in the browser to sign in
         via your corporate work account (often 1-click if signed into Windows).
      2. 2FA Verification: Log in with Keka password, enter OTP, and tick 'Remember this browser'.

    As soon as the user logs in and lands on the Keka dashboard, this function detects
    the active session, allows cookies to flush to disk, closes the browser, and returns success.
    All future automated headless runs will use this remembered session without prompting for 2FA or SSO!
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service as ChromeService
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from webdriver_manager.chrome import ChromeDriverManager
        from selenium.common.exceptions import WebDriverException, NoSuchWindowException
    except ImportError as e:
        return False, f"Selenium or Chrome driver missing: {e}", {"status": "missing_dependencies"}

    sub = clean_keka_subdomain(subdomain)
    profile_dir = Path.home() / ".keka_chrome_profile"

    driver = None
    try:
        if on_status_update:
            on_status_update("Preparing browser environment...")
        driver = _create_chrome_driver(profile_dir, headless=False, interactive=True)

        start_url = f"https://{sub}.keka.com"
        if on_status_update:
            on_status_update(f"Opened browser window at {start_url}")
        logger.info(f"Opening interactive browser window: {start_url}")
        driver.get(start_url)
        time.sleep(2)

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # If user closed the window manually
                if not driver.window_handles:
                    break
            except Exception:
                # Browser was closed
                break

            try:
                raw_url = driver.current_url
                cur_url = (raw_url or "").lower().strip()
            except Exception as e:
                logger.debug(f"Transient error querying current_url: {e}")
                cur_url = ""

            if not cur_url or cur_url in ("data:,", "about:blank"):
                time.sleep(1)
                continue

            if "tenant-not-found" in cur_url or "tenantnotfound" in cur_url:
                return False, f"Keka tenant '{sub}' not found at {cur_url}. Please ensure your subdomain is set to 'moshpit' (https://moshpit.keka.com).", {"status": "tenant_not_found"}

            # Check if user reached dashboard / authenticated state
            # When authenticated, Keka navigates to SPA routes: /ui/#/..., /#/home, /#/me, /dashboard, etc.
            is_login_page = any(k in cur_url for k in [
                "/account/login", "/account/kekalogin", "/account/sendcode",
                "/account/verifycode", "login.microsoftonline.com", "accounts.google.com",
                "login.live.com", "login.windows.net", "oauth", "tenant-not-found"
            ])
            is_authenticated_page = any(k in cur_url for k in [
                "/ui/#", "/#/home", "/#/me", "/#/dashboard", "/#/timeattendance", "/home", "/me", "/dashboard", "/timeattendance"
            ]) and not any(k in cur_url for k in ["tenant-not-found", "tenantnotfound"])

            if is_authenticated_page and not is_login_page:
                if on_status_update:
                    on_status_update("Authenticated! Saving persistent session...")
                logger.info(f"Interactive browser reached authenticated URL: {cur_url}")
                time.sleep(3)  # Allow cookies to flush to disk
                return True, "Keka session successfully authorized & saved! 2FA and SSO cookies are now active in your profile.", {"status": "authenticated"}

            time.sleep(1.5)

        return False, "Browser window closed or authorization timed out before completing login.", {"status": "cancelled"}
    except Exception as e:
        err_msg = str(e)
        _clean_chrome_profile_locks(profile_dir)
        if "user data directory is already in use" in err_msg.lower() or "devtoolsactiveport" in err_msg.lower() or "crashed" in err_msg.lower():
            return False, "Chrome profile was locked by a previous process. Locks have now been cleared—please click 'Authorize in Browser 🌐' again to launch.", {"status": "profile_locked"}
        return False, f"Failed to launch interactive browser: {err_msg[:120]}", {"status": "driver_error"}
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ==============================================================================
# CLI Entry Point
# ==============================================================================
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Keka Data Fetcher for Absent Management")
    parser.add_argument("--subdomain", default=None, help="Keka subdomain (default: from .env)")
    parser.add_argument("--from-date", default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to-date", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output-dir", default=None, help="Output directory for Excel files")
    parser.add_argument("--attendance-file", default=None, help="Path to manually downloaded attendance Excel")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window (debug mode)")
    parser.add_argument("--api-only", action="store_true", help="Skip Selenium, fetch only API reports (Emp Master + OD/WFH)")
    args = parser.parse_args()

    fetcher = KekaDataFetcher(subdomain=args.subdomain)

    if args.api_only:
        print("\n📡 Fetching API-only reports (Employee Master + OD/WFH)...\n")
        emp_df, emp_err = fetcher.fetch_employee_master()
        if emp_err:
            print(f"  ⚠️  Employee Master error: {emp_err}")
        print(f"  ✅ Employee Master: {len(emp_df)} employees")

        wfh_df, wfh_err = fetcher.fetch_od_wfh_requests(from_date=args.from_date, to_date=args.to_date)
        if wfh_err:
            print(f"  ⚠️  OD/WFH error: {wfh_err}")
        print(f"  ✅ OD/WFH Requests: {len(wfh_df)} records")
    else:
        result = fetcher.fetch_all_reports(
            from_date=args.from_date,
            to_date=args.to_date,
            output_dir=args.output_dir,
            attendance_excel_path=args.attendance_file,
            headless=not args.no_headless
        )

        print("\n" + "="*60)
        print("  KEKA DATA FETCH RESULTS")
        print("="*60)
        for key in ["emp_master_path", "attendance_path", "od_wfh_path"]:
            label = key.replace("_path", "").replace("_", " ").title()
            val = result[key]
            print(f"  {'✅' if val else '❌'} {label}: {val or 'NOT FETCHED'}")

        if result["errors"]:
            print(f"\n  ⚠️  Errors:")
            for e in result["errors"]:
                print(f"     • {e}")
        print("="*60 + "\n")
