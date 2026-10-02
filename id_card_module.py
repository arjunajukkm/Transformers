"""
id_card_module.py
─────────────────
Backend integration module connecting the FinBox ID Card Generator
to the Transformers CustomTkinter desktop application.
Provides thread-safe preview and bulk generation with real-time log streaming.
"""

import os
import sys
import io
import time
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

import generate_id_cards as gen


def clean_keka_subdomain(subdomain=None):
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


class ConsoleStreamRedirector:
    """Redirects stdout writes to a GUI callback function in real-time."""
    def __init__(self, callback, original_stdout=None):
        self.callback = callback
        self.original_stdout = original_stdout or sys.stdout
        self._in_write = False

    def write(self, text):
        if self._in_write:
            if self.original_stdout:
                try:
                    self.original_stdout.write(text)
                except Exception:
                    pass
            return

        self._in_write = True
        try:
            if self.original_stdout:
                try:
                    self.original_stdout.write(text)
                except Exception:
                    pass
            if text and self.callback:
                try:
                    self.callback(text)
                except Exception:
                    pass
        finally:
            self._in_write = False

    def flush(self):
        if self.original_stdout:
            try:
                self.original_stdout.flush()
            except Exception:
                pass


def save_env_variable(key: str, value: str, env_path: str = ".env"):
    """
    Saves or updates a key-value pair in the .env file and os.environ.
    Preserves comments and existing formatting.
    """
    try:
        import dotenv
        env_file = Path(env_path)
        if not env_file.exists():
            env_file.touch()
        dotenv.set_key(str(env_file.resolve()), key, value)
    except Exception as e:
        print(f"Warning: Could not save {key} to {env_path}: {e}")
    os.environ[key] = value


def check_slack_status(token_or_id: str = None):
    """
    Checks if Slack connection is active using provided token or Bot ID, or .env.
    Accepts:
      - Slack Bot User OAuth Token (xoxb-...)
      - Slack Bot ID (B... or U...) if token exists in .env
    Persists valid token and Bot ID to .env and os.environ.
    Returns: (is_connected: bool, status_msg: str, user_name: str, bot_id: str)
    """
    load_dotenv(override=True)
    candidate = (token_or_id or "").strip()
    token = ""
    target_bot_id = ""

    if candidate.startswith("xoxb-"):
        token = candidate
    elif candidate.startswith("B") or candidate.startswith("U"):
        target_bot_id = candidate
        token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    elif candidate:
        token = candidate
    else:
        token = os.getenv("SLACK_BOT_TOKEN", "").strip()

    if not token:
        if target_bot_id:
            return False, f"Bot ID '{target_bot_id}' given, but SLACK_BOT_TOKEN missing in .env", "", target_bot_id
        return False, "Slack token missing. Enter Bot Token (xoxb-...) & Connect.", "", ""

    try:
        from slack_sdk import WebClient
        client = WebClient(token=token, timeout=8)
        auth = client.auth_test()
        team = auth.get("team", "Slack Workspace")
        bot_user = auth.get("user", "Bot")
        bot_id = auth.get("bot_id", "")

        if target_bot_id and bot_id and target_bot_id != bot_id:
            return False, f"Connected to token, but Bot ID mismatch (expected {target_bot_id}, got {bot_id})", bot_user, bot_id

        # Persist valid token and bot_id
        save_env_variable("SLACK_BOT_TOKEN", token)
        if bot_id:
            save_env_variable("SLACK_BOT_ID", bot_id)

        msg = f"Connected to {team} as @{bot_user}"
        if bot_id:
            msg += f" ({bot_id})"
        return True, msg, bot_user, bot_id
    except Exception as e:
        err = str(e)
        if "invalid_auth" in err:
            return False, "Slack Auth Failed: Invalid Bot Token", "", ""
        if "not_authed" in err:
            return False, "Slack Auth Failed: No authentication token provided", "", ""
        return False, f"Slack connection error: {err[:60]}", "", ""


def get_keka_access_token(api_key: str = None, client_id: str = None, client_secret: str = None, subdomain: str = None):
    """Wrapper to obtain a valid Keka Bearer access token."""
    return gen.get_keka_access_token(api_key=api_key, client_id=client_id, client_secret=client_secret, subdomain=subdomain)


def check_keka_status(api_key: str = None, client_id: str = None, client_secret: str = None, subdomain: str = None):
    """
    Checks if Keka HRMS API connection is valid using provided credentials.
    Supports:
      - (client_id, client_secret, api_key) -> OAuth token generation
      - direct api_key / Bearer token
    Saves valid credentials to .env and os.environ.
    Returns: (is_connected: bool, status_msg: str, details: dict)
    """
    load_dotenv(override=True)

    cid = (client_id or "").strip() or os.getenv("KEKA_CLIENT_ID", "").strip()
    csec = (client_secret or "").strip() or os.getenv("KEKA_CLIENT_SECRET", "").strip()
    key = (api_key or "").strip() or os.getenv("KEKA_API_KEY", "").strip()

    sub = clean_keka_subdomain(subdomain)

    if not key and not (cid and csec):
        return False, "Keka credentials missing. Enter Client ID, Client Secret & API Key.", {}

    # 1. Obtain Bearer Token (auto-exchanges OAuth credentials if client_id + client_secret are provided)
    token, err = get_keka_access_token(api_key=key, client_id=cid, client_secret=csec, subdomain=sub)
    if not token or err:
        return False, f"Keka Auth Failed: {err}", {"error": err}

    # 2. Test API Access
    try:
        import requests
        url = f"https://{sub}.keka.com/api/v1/hris/employees?pageSize=1"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla"
        }
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code in (200, 204):
            if cid:
                save_env_variable("KEKA_CLIENT_ID", cid)
            if csec:
                save_env_variable("KEKA_CLIENT_SECRET", csec)
            if key:
                save_env_variable("KEKA_API_KEY", key)
            save_env_variable("KEKA_SUBDOMAIN", sub)
            return True, f"Connected to Keka ({sub}.keka.com)", {"subdomain": sub, "status": res.status_code}
        elif res.status_code in (401, 403):
            return False, f"Keka API Auth Failed: Invalid credentials (HTTP {res.status_code})", {"status": res.status_code}
        elif res.status_code == 404:
            return False, f"Keka error: Subdomain '{sub}' or endpoint not found (HTTP 404)", {"status": 404}
        else:
            return False, f"Keka API error: HTTP {res.status_code}", {"status": res.status_code}
    except Exception as e:
        err = str(e)
        return False, f"Keka connection error: {err[:60]}", {}


def check_keka_portal_status(email=None, password=None, subdomain=None, headless=True, otp_callback=None):
    """Tests Keka Web Portal login connectivity (Email, Password, Captcha & optional 2FA)."""
    import keka_data_fetcher
    return keka_data_fetcher.check_keka_portal_status(
        email=email, password=password, subdomain=clean_keka_subdomain(subdomain), headless=headless, otp_callback=otp_callback
    )


def authorize_keka_portal_in_browser(subdomain=None, email=None, password=None, timeout=180, on_status_update=None):
    """Launches an interactive Chrome window to authorize Keka session via SSO or 2FA."""
    import keka_data_fetcher
    return keka_data_fetcher.launch_interactive_browser_session(
        subdomain=clean_keka_subdomain(subdomain),
        keka_email=email,
        keka_password=password,
        timeout=timeout,
        on_status_update=on_status_update
    )


def fetch_keka_profile_photo(email, emp_no=None, api_key=None, client_id=None, client_secret=None, subdomain=None, max_retries=2):
    """Wrapper to fetch employee profile photo from Keka HRMS API."""
    return gen.fetch_keka_profile_photo(
        email, emp_no=emp_no, api_key=api_key, client_id=client_id, client_secret=client_secret,
        subdomain=subdomain, max_retries=max_retries
    )


def fetch_slack_profile_photo(client, email, token, max_retries=3):
    """Wrapper to fetch employee profile photo from Slack."""
    return gen.fetch_slack_profile_photo(client, email, token, max_retries=max_retries)


def fetch_profile_photo_with_fallback(
    email,
    emp_no=None,
    slack_client=None,
    slack_token=None,
    keka_api_key=None,
    keka_client_id=None,
    keka_client_secret=None,
    keka_subdomain=None
):
    """
    Unified multi-source photo fetcher: Keka HRMS 1st, Slack fallback.
    Returns (image_bytes, error_message, photo_status_label, photo_source).
    """
    return gen.fetch_profile_photo_with_fallback(
        email, emp_no=emp_no, slack_client=slack_client, slack_token=slack_token,
        keka_api_key=keka_api_key, keka_client_id=keka_client_id,
        keka_client_secret=keka_client_secret, keka_subdomain=keka_subdomain
    )


def get_default_excel_file():
    """Returns path to ID card generation.xlsx if found in working directory."""
    f = gen.find_excel_file()
    return str(f.resolve()) if f else ""


def get_latest_output_dir():
    """Finds the most recent ID_Cards_* directory in Downloads, or falls back to Downloads."""
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        candidates = sorted(
            [d for d in downloads.iterdir() if d.is_dir() and d.name.startswith("ID_Cards")],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        if candidates:
            return str(candidates[0].resolve())
    return str(downloads.resolve())


def get_office_addresses():
    """Retrieves office address mapping from disk or defaults."""
    return gen.get_office_addresses()


def save_office_addresses(mapping):
    """Saves office address mapping to disk."""
    return gen.save_office_addresses(mapping)


def run_preview_job(
    preview_email,
    design_name="modern",
    excel_path=None,
    photos_dir=None,
    photo_match_mode="auto",
    log_callback=None,
    output_dir=None,
    address_mapping=None
):
    """
    Executes preview generation for a single employee email.
    Sourcing employee details from Excel or directly from Keka HRMS.
    Sourcing photo from local folder (if provided) -> Keka -> Slack.
    Captures stdout in real-time and reports back results.
    Returns: (success: bool, pdf_path: str, msg: str, output_folder: str)
    """
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    if log_callback:
        redirector = ConsoleStreamRedirector(log_callback, old_stdout)
        sys.stdout = redirector
        sys.stderr = redirector

    design_clean = str(design_name).strip().lower()
    out_name = "Modern" if design_clean == "modern" else "Classic"

    if output_dir:
        target_output_dir = Path(output_dir)
    else:
        target_output_dir = gen.create_new_output_dir(prefix=f"ID_Cards_Preview_{out_name}")
    target_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # If custom excel path provided, ensure generate_id_cards uses it
        if excel_path and Path(excel_path).exists():
            orig_find = gen.find_excel_file
            gen.find_excel_file = lambda project_dir=".": Path(excel_path)
        else:
            orig_find = None

        res_code = gen.run_preview_mode(
            preview_email.strip(),
            design=design_clean,
            output_dir=target_output_dir,
            photos_dir=photos_dir,
            photo_match_mode=photo_match_mode,
            address_mapping=address_mapping
        )

        if orig_find:
            gen.find_excel_file = orig_find

        pdf_path = target_output_dir / out_name / f"IDCard_Preview_{out_name}.pdf"

        if res_code == 0 and pdf_path.exists():
            return True, str(pdf_path.resolve()), f"Preview generated successfully: {pdf_path.name}", str(target_output_dir.resolve())
        else:
            return False, "", "Preview generation failed or was skipped due to validation rules.", str(target_output_dir.resolve())

    except Exception as e:
        import traceback
        err_trace = traceback.format_exc()
        if log_callback:
            log_callback(f"\n[!] Unexpected Error during preview: {e}\n{err_trace}\n")
        return False, "", str(e), str(target_output_dir.resolve())
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def run_bulk_job(
    design_name="modern",
    excel_path=None,
    photos_dir=None,
    photo_match_mode="auto",
    log_callback=None,
    progress_callback=None,
    output_dir=None,
    address_mapping=None
):
    """
    Executes bulk generation for all employees in Excel.
    Captures stdout in real-time and reports back results.
    Returns: (success: bool, report_path: str, summary_dict: dict, msg: str, output_folder: str)
    """
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    if log_callback:
        redirector = ConsoleStreamRedirector(log_callback, old_stdout)
        sys.stdout = redirector
        sys.stderr = redirector

    design_clean = str(design_name).strip().lower()
    out_name = "Modern" if design_clean == "modern" else "Classic"

    if output_dir:
        target_output_dir = Path(output_dir)
    else:
        target_output_dir = gen.create_new_output_dir(prefix=f"ID_Cards_{out_name}")
    target_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if excel_path and Path(excel_path).exists():
            orig_find = gen.find_excel_file
            gen.find_excel_file = lambda project_dir=".": Path(excel_path)
        else:
            orig_find = None

        res_code = gen.run_bulk_generation(
            design=design_clean,
            output_dir=target_output_dir,
            photos_dir=photos_dir,
            photo_match_mode=photo_match_mode,
            address_mapping=address_mapping
        )

        if orig_find:
            gen.find_excel_file = orig_find

        report_file = target_output_dir / "Reports" / f"{out_name}_Generation_Report.xlsx"
        if not report_file.exists():
            # Fallback older path check
            report_file = target_output_dir / out_name / "IDCard_Generation_Report.xlsx"

        report_path_str = str(report_file.resolve()) if report_file.exists() else ""

        if res_code == 0:
            return True, report_path_str, {}, "Bulk generation completed successfully.", str(target_output_dir.resolve())
        else:
            return False, report_path_str, {}, f"Bulk generation finished with status code {res_code}.", str(target_output_dir.resolve())

    except Exception as e:
        import traceback
        err_trace = traceback.format_exc()
        if log_callback:
            log_callback(f"\n[!] Unexpected Error during bulk generation: {e}\n{err_trace}\n")
        return False, "", {}, str(e), str(target_output_dir.resolve())
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def run_email_batch_job(
    emails_input,
    design_name="modern",
    photos_dir=None,
    photo_match_mode="auto",
    log_callback=None,
    output_dir=None,
    address_mapping=None
):
    """
    Executes Method 1: Instant Email Sync ID Card Generation.
    Fetches employee details from Keka, photo from Local Folder -> Keka -> Slack,
    and maps office addresses dynamically based on employee location.
    Returns: (success: bool, report_path: str, msg: str, output_folder: str)
    """
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    if log_callback:
        redirector = ConsoleStreamRedirector(log_callback, old_stdout)
        sys.stdout = redirector
        sys.stderr = redirector

    design_clean = str(design_name).strip().lower()
    out_name = "Modern" if design_clean == "modern" else "Classic"

    if output_dir:
        target_output_dir = Path(output_dir)
    else:
        target_output_dir = gen.create_new_output_dir(prefix=f"ID_Cards_{out_name}_InstantSync")
    target_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        res_code = gen.run_email_batch_mode(
            emails_input=emails_input,
            design=design_clean,
            output_dir=target_output_dir,
            address_mapping=address_mapping,
            photos_dir=photos_dir,
            photo_match_mode=photo_match_mode
        )

        report_file = target_output_dir / "Reports" / f"{out_name}_Generation_Report.xlsx"
        report_path_str = str(report_file.resolve()) if report_file.exists() else ""

        if res_code == 0:
            return True, report_path_str, "Email batch ID card generation finished successfully.", str(target_output_dir.resolve())
        else:
            return False, report_path_str, f"Email batch finished with return code {res_code}.", str(target_output_dir.resolve())

    except Exception as e:
        import traceback
        err_trace = traceback.format_exc()
        if log_callback:
            log_callback(f"\n[!] Unexpected Error during email batch: {e}\n{err_trace}\n")
        return False, "", str(e), str(target_output_dir.resolve())
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def open_system_path(path_str):
    """Opens a file or folder using the default OS application."""
    if not path_str:
        return False, "Path is empty"
    p = Path(path_str)
    if not p.exists():
        return False, f"Path does not exist: {path_str}"
    try:
        os.startfile(str(p.resolve()))
        return True, "Opened successfully"
    except Exception as e:
        return False, str(e)
