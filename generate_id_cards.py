"""
Employee ID Card Generator (Dual-Design: Classic & Modern)
==========================================================
A Python HR utility to generate employee ID cards in bulk or preview from an Excel file,
fetching profile photos automatically from Slack using employee email IDs.

Supported Designs:
  1. Classic: Approved FinBox ID card layout matching reference_id_card.pdf.
  2. Modern:  Modern FinBox branding layout matching ID card.pdf (geometric blue header,
              large portrait area, QR code encoding Employee Number, emergency contact details).

Modes:
  1. Single-employee preview mode:
     python generate_id_cards.py --preview-email arjun.s@finbox.in --design classic
     Outputs: output/Classic/IDCard_Preview_Classic.pdf (2 pages: Front & Back)

     python generate_id_cards.py --preview-email arjun.s@finbox.in --design modern
     Outputs: output/Modern/IDCard_Preview_Modern.pdf (2 pages: Front & Back)

  2. Temporary Slack connection test mode:
     python generate_id_cards.py --test-email arjun.s@finbox.in
     Outputs: output/slack_test_photo.jpg (No ID card generated)

  3. Bulk generation mode:
     python generate_id_cards.py
     Prompts for design selection (1. Classic, 2. Modern)
     Outputs: output/<Design>/<Employee Number>_<Employee Name>_IDCard.pdf (per employee)
              output/<Design>/IDCard_Generation_Report.xlsx (audit report)
"""

import os
import sys
import re
import io
import math
import time
import hashlib
import argparse
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np
import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageOps
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import reportlab
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.utils import ImageReader
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# ==============================================================================
# CONFIGURATION & CONSTANTS
# ==============================================================================
# Page size: Standard A4
PAGE_WIDTH, PAGE_HEIGHT = A4

# Card Dimensions (Matching reference_id_card.pdf & ID card.pdf)
CARD_WIDTH = 271.5
CARD_HEIGHT = 406.5
CARD_X = (PAGE_WIDTH - CARD_WIDTH) / 2      # Centered horizontally (~161.75 pt)
CARD_Y = 415.5                               # Positioned matching reference (~415.5 pt)
CENTER_X = CARD_X + CARD_WIDTH / 2          # 295.75 pt

def get_downloads_dir() -> Path:
    """Returns the user's Downloads directory."""
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads

def create_new_output_dir(prefix="ID_Cards") -> Path:
    """
    Creates and returns a new timestamped folder inside Downloads every time.
    Example: C:/Users/<User>/Downloads/ID_Cards_20260927_173510
    """
    downloads = get_downloads_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{prefix}_{ts}"
    out_dir = downloads / base_name
    counter = 1
    while out_dir.exists():
        out_dir = downloads / f"{base_name}_{counter}"
        counter += 1
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir

OUTPUT_DIR = get_downloads_dir()
ASSETS_DIR = Path("assets")

# Classic Color Palette
COLOR_KEKA_BLUE = colors.HexColor("#2986CE")  # Header Blue
COLOR_CARD_BORDER = colors.HexColor("#E4E6E9")
COLOR_CONTAINER_BG = colors.HexColor("#F8F8FA")
COLOR_CONTAINER_BORDER = colors.HexColor("#EAEAEF")
COLOR_TEXT_DARK = colors.HexColor("#212121")   # Darker charcoal/black values
COLOR_TEXT_LABEL = colors.HexColor("#757575")  # Medium/light grey labels
COLOR_TEXT_GRAY = colors.HexColor("#747474")   # Footers & subtext

# Modern Color Palette
MODERN_DARK_NAVY = colors.HexColor("#0A1931")
MODERN_BLUE_ACCENT = colors.HexColor("#0052FF")
MODERN_MUTED_TEXT = colors.HexColor("#475569")
MODERN_DIVIDER = colors.HexColor("#E2E8F0")
MODERN_BG_LIGHT = colors.HexColor("#F8FAFC")

# Modern Card Dimensions (Matching ID card 2.pdf exact 141.75 : 240.75 ratio)
MODERN_CARD_HEIGHT = 406.5
MODERN_CARD_WIDTH = 239.34                   # 406.5 * (141.75 / 240.75)
MODERN_CARD_X = (PAGE_WIDTH - MODERN_CARD_WIDTH) / 2   # Centered horizontally on A4 (~177.97 pt)
MODERN_CARD_Y = CARD_Y                       # 415.5 pt
MODERN_CENTER_X = MODERN_CARD_X + MODERN_CARD_WIDTH / 2 # 297.64 pt
# ==============================================================================
# PERFORMANCE OPTIMISATION: ASSET CACHE & BATCH IMAGE CACHE
# ==============================================================================
class AssetCache:
    """
    In-memory cache for ReportLab ImageReader instances of static template assets.
    Eliminates redundant disk reads and image decodings across employee cards.
    """
    _cache = {}

    @classmethod
    def get_image(cls, path_or_str):
        if not path_or_str:
            return None
        p = Path(path_or_str)
        key = str(p.resolve())
        if key not in cls._cache:
            if p.exists():
                try:
                    cls._cache[key] = ImageReader(str(p))
                except Exception:
                    return None
            else:
                return None
        return cls._cache[key]

    @classmethod
    def clear(cls):
        cls._cache.clear()


class BatchImageCache:
    """
    Thread-safe, temporary batch-scoped image cache.
    Stores raw downloaded Slack photos keyed strictly by employee email, and
    processed card portraits keyed strictly by (emp_no, source_sha256, design).
    Guarantees no cross-employee photo sharing and is cleared at batch completion.
    """
    def __init__(self):
        self._raw_by_email = {}       # email -> (raw_bytes, error_msg, status_label, source)
        self._processed = {}          # (emp_no, sha256_hash, design) -> bytes

    def put_raw(self, email, raw_bytes, err_msg, status_label, source="Slack"):
        if email:
            self._raw_by_email[str(email).strip().lower()] = (raw_bytes, err_msg, status_label, source)

    def get_raw(self, email):
        if not email:
            return None
        return self._raw_by_email.get(str(email).strip().lower())

    def put_processed(self, emp_no, raw_bytes, design, photo_io):
        if not raw_bytes or not photo_io:
            return
        h = hashlib.sha256(raw_bytes).hexdigest()
        key = (str(emp_no).strip(), h, str(design).lower())
        photo_io.seek(0)
        self._processed[key] = photo_io.getvalue()
        photo_io.seek(0)

    def get_processed(self, emp_no, raw_bytes, design):
        if not raw_bytes:
            return None
        h = hashlib.sha256(raw_bytes).hexdigest()
        key = (str(emp_no).strip(), h, str(design).lower())
        data = self._processed.get(key)
        if data is not None:
            return io.BytesIO(data)
        return None

    def clear(self):
        self._raw_by_email.clear()
        self._processed.clear()


def format_duration(seconds):
    """Format duration in seconds into HH:MM:SS or MM:SS."""
    if seconds is None or seconds < 0 or math.isnan(seconds):
        return "00:00"
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


# ==============================================================================
# ERROR FORMATTER (SIMPLE LANGUAGE)
# ==============================================================================
def explain_slack_error(err_code, response_data=None):
    """
    Translates technical Slack API errors into simple, clear language.
    Does NOT expose or print the Slack token.
    """
    if response_data is None:
        response_data = {}

    explanations = {
        "missing_scope": (
            "The Slack bot token is missing required OAuth permissions.\n"
            "    Required scopes: 'users:read' and 'users:read.email'.\n"
            f"    (Scopes needed by Slack: {response_data.get('needed', 'users:read, users:read.email')})"
        ),
        "invalid_auth": (
            "The Slack bot token is invalid or malformed.\n"
            "    Please verify the SLACK_BOT_TOKEN value inside your .env file."
        ),
        "users_not_found": (
            "No Slack user was found with that email address in this workspace.\n"
            "    Please confirm that the user has joined this Slack workspace."
        ),
        "token_revoked": (
            "The Slack bot token has been revoked or the app was uninstalled.\n"
            "    Please reinstall your Slack app and update SLACK_BOT_TOKEN in .env."
        ),
        "account_inactive": (
            "The Slack account for this email has been deactivated."
        ),
        "not_authed": (
            "No authorization token was provided.\n"
            "    Please define SLACK_BOT_TOKEN in .env."
        ),
        "ratelimited": (
            "Slack rate limit reached. Please wait a moment before trying again."
        ),
    }

    return explanations.get(
        err_code,
        f"Slack API error: '{err_code}'."
    )


# ==============================================================================
# SLACK LOOKUP & PROFILE PHOTO PROCESSING
# ==============================================================================
def fetch_slack_profile_photo(client, email, token, max_retries=3):
    """
    Query Slack users.lookupByEmail and download the highest-resolution custom profile photo.
    Detects and rejects:
      - Missing Slack client/token
      - Missing or invalid email
      - Slack user not found
      - Missing profile photo
      - Default Slack avatar (is_custom_image == False or default avatar URL)
      - Network download failure / HTTP error
      - Empty or truncated image bytes
      - Corrupted or unreadable image file (PIL verification)
    Handles:
      - Slack rate limits (HTTP 429) by checking Retry-After header and waiting.
      - Transient network errors with exponential backoff retries.
    Returns:
        (image_bytes, error_message, photo_status_label)
    """
    if not client:
        return None, "Slack token not configured in .env", "Auth Failed"

    if not email:
        return None, "Email is missing", "Missing Email"

    clean_email = str(email).strip().lower()
    if clean_email in ["", "nan", "none", "null", "n/a", "not available", "-"]:
        return None, "Email is missing or invalid", "Missing Email"

    attempt = 0
    backoff = 1.0
    while attempt < max_retries:
        attempt += 1
        try:
            response = client.users_lookupByEmail(email=clean_email)
            if not response.get("ok", False):
                err_code = response.get("error", "unknown_error")
                return None, explain_slack_error(err_code), "Slack Lookup Failed"

            user = response.get("user", {})
            profile = user.get("profile", {})

            # Check for default Slack avatar
            is_custom = profile.get("is_custom_image")
            if is_custom is False:
                return None, "Default Slack avatar detected (custom profile photo required)", "Default Avatar Detected"

            photo_keys = [
                "image_original",
                "image_1024",
                "image_512",
                "image_192",
                "image_72",
                "image_48",
                "image_32"
            ]

            photo_url = None
            for key in photo_keys:
                url = profile.get(key)
                if url and isinstance(url, str) and url.startswith("http"):
                    photo_url = url
                    break

            if not photo_url:
                return None, "Slack profile photo unavailable", "Photo Unavailable"

            # Additional default avatar pattern check
            if "/avatars/default" in photo_url or "default_avatar" in photo_url or "d=https" in photo_url:
                return None, "Default Slack avatar detected (custom profile photo required)", "Default Avatar Detected"

            headers = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            # Download photo with retry on temporary network failure
            dl_attempt = 0
            dl_backoff = 1.0
            req = None
            while dl_attempt < 3:
                dl_attempt += 1
                try:
                    req = requests.get(photo_url, headers=headers, timeout=15)
                    if req.status_code != 200:
                        req = requests.get(photo_url, timeout=15)
                    if req.status_code == 200:
                        break
                except requests.RequestException:
                    if dl_attempt < 3:
                        time.sleep(dl_backoff)
                        dl_backoff *= 2.0
                    else:
                        raise

            if not req or req.status_code != 200:
                return None, f"Failed to download Slack photo (HTTP {req.status_code if req else 'Error'})", "Download Failed"

            if not req.content or len(req.content) < 100:
                return None, "Slack profile photo unavailable (empty or truncated image)", "Photo Unavailable"

            # Verify image using PIL
            try:
                test_img = Image.open(io.BytesIO(req.content))
                test_img.verify()
            except Exception as img_err:
                return None, f"Corrupted or unreadable image file: {img_err}", "Corrupted Image"

            return req.content, None, "Valid Custom Photo"

        except SlackApiError as e:
            err = e.response.get("error", str(e)) if hasattr(e.response, "get") else str(e)
            if err == "ratelimited":
                # Slack rate limit: Check Retry-After header
                retry_after = 5
                try:
                    resp_headers = getattr(e.response, "headers", {})
                    if "Retry-After" in resp_headers:
                        retry_after = int(resp_headers["Retry-After"])
                    elif "retry-after" in resp_headers:
                        retry_after = int(resp_headers["retry-after"])
                except Exception:
                    pass
                if attempt < max_retries:
                    time.sleep(retry_after + 1.0)
                    continue
                return None, "Slack rate limit reached (Retry-After exceeded)", "Slack Rate Limited"
            elif err == "users_not_found":
                return None, "Slack user not found", "Slack User Not Found"
            resp_dict = getattr(e.response, "data", e.response) if isinstance(e.response, dict) or hasattr(e.response, "data") else {}
            return None, f"Slack error: {err} ({explain_slack_error(err, resp_dict)})", "Slack API Error"
        except requests.RequestException as e:
            if attempt < max_retries:
                time.sleep(backoff)
                backoff *= 2.0
                continue
            return None, f"Network error downloading photo: {e}", "Network Error"
        except Exception as e:
            return None, f"Slack lookup error: {e}", "Lookup Error"


# ==============================================================================
# KEKA HRMS LOOKUP & PROFILE PHOTO PROCESSING
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
      1. OAuth Client Credentials Flow: If client_id, client_secret, and api_key are provided
         (or configured in .env), exchanges them via POST https://login.keka.com/connect/token.
         Caches the token until near expiry (auto-refresh).
      2. Direct Token Flow: If api_key is already a Bearer token or client_id/secret not provided,
         uses api_key directly.
    Returns: (access_token: str or None, error_msg: str or None)
    """
    # If caller explicitly provided an api_key without client_id/client_secret,
    # treat it as a direct bearer token (Flow 2)
    if api_key is not None and client_id is None and client_secret is None:
        key = api_key.strip()
        if key:
            return key, None

    cid = (client_id if client_id is not None else os.getenv("KEKA_CLIENT_ID", "")).strip()
    csec = (client_secret if client_secret is not None else os.getenv("KEKA_CLIENT_SECRET", "")).strip()
    key = (api_key if api_key is not None else os.getenv("KEKA_API_KEY", "")).strip()

    # If client_id, client_secret, and api_key are all present, perform OAuth2 token exchange
    if cid and csec and key:
        cache_id = f"{cid}:{key}"
        now = time.time()
        if _KEKA_TOKEN_CACHE["access_token"] and _KEKA_TOKEN_CACHE["cache_key"] == cache_id and _KEKA_TOKEN_CACHE["expires_at"] > now + 60:
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

    # If key is provided alone (direct bearer token)
    if key:
        return key, None

    if cid and not csec:
        return None, "KEKA_CLIENT_SECRET missing"
    if csec and not cid:
        return None, "KEKA_CLIENT_ID missing"

    return None, "Keka credentials missing (need Client ID, Client Secret & API Key, or Bearer Token)"


def fetch_keka_profile_photo(
    email,
    emp_no=None,
    api_key=None,
    client_id=None,
    client_secret=None,
    subdomain=None,
    max_retries=2
):
    """
    Query Keka HRMS API for employee profile photo.
    Hierarchy:
      1. Authenticates using Bearer token (obtained via OAuth Client Credentials or direct token).
      2. Searches employee via POST /api/v1/hris/employees/search (workEmail).
         Fallback A: GET /api/v1/hris/employees?searchKey={email}&pageSize=5.
         Fallback B: GET /api/v1/hris/employees?employeeNumbers={emp_no}&pageSize=5.
      3. Extracts photo from employee profile's `image` -> `thumbs` (large/original/medium).
      4. Downloads and verifies image bytes using PIL.
    Returns:
        (image_bytes, error_message, photo_status_label)
    """
    clean_email = str(email or "").strip().lower()
    clean_emp_no = str(emp_no or "").strip()

    if clean_email in ["", "nan", "none", "null", "n/a", "not available", "-"]:
        clean_email = ""

    if not clean_email and not clean_emp_no:
        return None, "Email and Employee Number are missing", "Missing Identifier"

    token, tok_err = get_keka_access_token(
        api_key=api_key, client_id=client_id, client_secret=client_secret, subdomain=subdomain
    )
    if not token or tok_err:
        return None, tok_err or "KEKA credentials missing in .env", "Keka Not Configured"

    sub = (subdomain or os.getenv("KEKA_SUBDOMAIN", "finbox")).strip()
    sub = sub.replace("https://", "").replace("http://", "").split(".")[0].strip() or "finbox"
    base_url = f"https://{sub}.keka.com/api/v1"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla"
    }

    emp_profile = None

    # Step 1: Search via POST /hris/employees/search (workEmail)
    if clean_email:
        try:
            res = requests.post(
                f"{base_url}/hris/employees/search",
                headers=headers,
                json={"workEmail": clean_email},
                timeout=10
            )
            if res.status_code == 200:
                payload = res.json()
                if isinstance(payload, dict):
                    if payload.get("succeeded") is not False:
                        emp_profile = payload.get("data")
                    if not emp_profile and isinstance(payload.get("data"), list) and payload["data"]:
                        emp_profile = payload["data"][0]
            elif res.status_code in (401, 403):
                return None, f"Keka Auth Failed: Invalid API key (HTTP {res.status_code})", "Keka Auth Failed"
        except Exception:
            pass

    # Step 2: Fallback search via GET /hris/employees?searchKey={email}
    if not emp_profile and clean_email:
        try:
            res = requests.get(
                f"{base_url}/hris/employees",
                headers=headers,
                params={"searchKey": clean_email, "pageSize": 5},
                timeout=10
            )
            if res.status_code == 200:
                payload = res.json()
                items = payload.get("data", []) if isinstance(payload, dict) else []
                if isinstance(items, list):
                    for item in items:
                        if str(item.get("email") or "").strip().lower() == clean_email:
                            emp_profile = item
                            break
                    if not emp_profile and items:
                        emp_profile = items[0]
            elif res.status_code in (401, 403):
                return None, f"Keka Auth Failed: Invalid API key (HTTP {res.status_code})", "Keka Auth Failed"
        except Exception:
            pass

    # Step 3: Fallback search via GET /hris/employees?employeeNumbers={emp_no}
    if not emp_profile and clean_emp_no:
        try:
            res = requests.get(
                f"{base_url}/hris/employees",
                headers=headers,
                params={"employeeNumbers": clean_emp_no, "pageSize": 5},
                timeout=10
            )
            if res.status_code == 200:
                payload = res.json()
                items = payload.get("data", []) if isinstance(payload, dict) else []
                if isinstance(items, list) and items:
                    emp_profile = items[0]
            elif res.status_code in (401, 403):
                return None, f"Keka Auth Failed: Invalid API key (HTTP {res.status_code})", "Keka Auth Failed"
        except Exception:
            pass

    if not emp_profile:
        return None, "Employee record not found in Keka HRMS", "Keka User Not Found"

    # Step 4: Extract photo URL from employee profile
    image_obj = emp_profile.get("image")
    if not image_obj:
        return None, "No profile photo uploaded in Keka HRMS", "No Keka Photo"

    photo_url = None
    if isinstance(image_obj, dict):
        thumbs = image_obj.get("thumbs")
        if isinstance(thumbs, dict):
            # Prefer highest available resolution dimensions first
            priority_order = [
                "original", "1024x1024", "800x800", "600x600", "500x500", "400x400",
                "300x300", "200x200", "large", "medium", "small", "thumb"
            ]
            for k in priority_order:
                if k in thumbs and isinstance(thumbs[k], str) and thumbs[k].startswith("http"):
                    photo_url = thumbs[k]
                    break
            if not photo_url:
                for v in thumbs.values():
                    if isinstance(v, str) and v.startswith("http"):
                        photo_url = v
                        break
        if not photo_url:
            for k in ["url", "downloadUrl", "imageUrl", "fileName"]:
                v = image_obj.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    photo_url = v
                    break
    elif isinstance(image_obj, str) and image_obj.startswith("http"):
        photo_url = image_obj

    if not photo_url:
        return None, "No valid profile photo URL found in Keka profile", "No Keka Photo"

    # Step 5: High-Clarity Photo Resolution Probing & Download
    # Keka HRMS API JSON usually only advertises [200x200, 50x50, 33x33] in the thumbs payload.
    # However, Keka's file storage server generates and hosts a 400x400 (4x pixel density, 110KB+)
    # version at /400x400/ that dramatically improves ID card print clarity.
    candidate_urls = []
    if re.search(r'/\d+x\d+/', photo_url):
        for high_dim in ["800x800", "600x600", "500x500", "400x400"]:
            candidate_urls.append(re.sub(r'/\d+x\d+/', f'/{high_dim}/', photo_url))
    if photo_url not in candidate_urls:
        candidate_urls.append(photo_url)

    req = None
    for cand_url in candidate_urls:
        dl_attempt = 0
        while dl_attempt < max_retries:
            dl_attempt += 1
            try:
                # Presigned S3 / storage URLs often fail if Authorization header is sent
                req = requests.get(cand_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                if req.status_code != 200 and token:
                    req = requests.get(cand_url, headers={"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}, timeout=10)
                if req.status_code == 200 and req.content and len(req.content) > 500:
                    break
            except requests.RequestException:
                if dl_attempt < max_retries:
                    time.sleep(0.3)
        if req and req.status_code == 200 and req.content and len(req.content) > 500:
            break

    if not req or req.status_code != 200:
        return None, f"Failed to download photo from Keka (HTTP {req.status_code if req else 'Error'})", "Download Failed"

    if not req.content or len(req.content) < 100:
        return None, "Keka profile photo is empty or truncated", "No Keka Photo"

    # Step 6: Verify image bytes with PIL
    try:
        test_img = Image.open(io.BytesIO(req.content))
        test_img.verify()
    except Exception as img_err:
        return None, f"Corrupted Keka image file: {img_err}", "Corrupted Image"

    return req.content, None, "Valid Keka Photo"


# ==============================================================================
# OFFICE LOCATIONS & ADDRESSES CONFIGURATION
# ==============================================================================
DEFAULT_OFFICE_ADDRESSES = {
    "Bengaluru": "3rd Floor, Vaishnavi Sovereign, Green Glen Layout, Bellandur, Bengaluru, Karnataka, India - 560103",
    "Bangalore": "3rd Floor, Vaishnavi Sovereign, Green Glen Layout, Bellandur, Bengaluru, Karnataka, India - 560103",
    "Gurgaon": "Unit 201, 2nd Floor, DLF Cyber City, Sector 24, Gurugram, Haryana - 122002",
    "Gurugram": "Unit 201, 2nd Floor, DLF Cyber City, Sector 24, Gurugram, Haryana - 122002",
    "Mumbai": "Level 4, Dynasty Business Park, Andheri Kurla Road, Andheri East, Mumbai, Maharashtra - 400059",
    "Delhi": "A-14, Connaught Place, New Delhi, Delhi - 110001",
    "Hyderabad": "Plot No. 12, Hitec City, Madhapur, Hyderabad, Telangana - 500081",
    "Default": "3rd Floor, Vaishnavi Sovereign, Green Glen Layout, Bellandur, Bengaluru, Karnataka, India - 560103"
}

def get_office_addresses():
    """Loads configured office addresses from local_data/office_addresses.json, or returns defaults."""
    p = Path(__file__).resolve().parent / "local_data" / "office_addresses.json"
    if p.exists():
        try:
            import json
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except Exception:
            pass
    return dict(DEFAULT_OFFICE_ADDRESSES)

def save_office_addresses(mapping):
    """Saves configured office addresses dictionary to local_data/office_addresses.json."""
    p = Path(__file__).resolve().parent / "local_data" / "office_addresses.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    import json
    p.write_text(json.dumps(mapping, indent=2), encoding="utf-8")

def resolve_office_address(location_name, mapping=None):
    """
    Matches employee location (e.g. from Keka or Excel) to the configured office address.
    Supports case-insensitive exact and substring matches, falling back to 'Default'.
    """
    if not mapping:
        mapping = get_office_addresses()
    loc = str(location_name or "").strip().lower()
    if not loc:
        return mapping.get("Default", mapping.get("Bengaluru", list(mapping.values())[0] if mapping else ""))

    for k, addr in mapping.items():
        if k.lower() == loc:
            return addr

    for k, addr in mapping.items():
        if k.lower() != "default" and (k.lower() in loc or loc in k.lower()):
            return addr

    return mapping.get("Default", mapping.get("Bengaluru", list(mapping.values())[0] if mapping else ""))


def find_local_photo(photos_dir, emp_no=None, email=None, match_mode="auto"):
    """
    Finds and reads an employee photo from a local folder matching by Employee ID or Email.
    Returns: raw bytes or None
    """
    if not photos_dir:
        return None
    p_dir = Path(photos_dir)
    if not p_dir.is_dir():
        return None

    clean_emp = str(emp_no or "").strip().lower()
    clean_email = str(email or "").strip().lower()
    email_user = clean_email.split("@")[0] if "@" in clean_email else clean_email

    valid_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    candidates = []

    m = str(match_mode or "auto").strip().lower()
    if m in ("emp_no", "auto") and clean_emp:
        candidates.extend([clean_emp, f"{clean_emp}_photo", f"photo_{clean_emp}"])
    if m in ("email", "auto") and clean_email:
        candidates.extend([clean_email, email_user])

    try:
        for file in p_dir.iterdir():
            if file.is_file() and file.suffix.lower() in valid_exts:
                stem = file.stem.lower()
                for c in candidates:
                    if stem == c or stem.replace(" ", "") == c.replace(" ", "") or stem.replace("_", "") == c.replace("_", ""):
                        return file.read_bytes()
    except Exception:
        pass

    return None


def fetch_keka_employee_full_details(
    email,
    api_key=None,
    client_id=None,
    client_secret=None,
    subdomain=None,
    address_mapping=None
):
    """
    Fetches full employee record from Keka HRMS API by email:
      - Display Name, Designation, Employee Number (EMP ID)
      - Mobile Phone, Date of Birth, Blood Group
      - Emergency Contact Person & Phone
      - Location & resolved Office Address
    Returns: (emp_data_dict or None, error_message or None)
    """
    clean_email = str(email or "").strip().lower()
    if not clean_email:
        return None, "Email address is required"

    token, tok_err = get_keka_access_token(
        api_key=api_key, client_id=client_id, client_secret=client_secret, subdomain=subdomain
    )
    if not token or tok_err:
        return None, tok_err or "Keka credentials not configured in Settings/.env"

    sub = (subdomain or os.getenv("KEKA_SUBDOMAIN", "finbox")).strip()
    sub = sub.replace("https://", "").replace("http://", "").split(".")[0].strip() or "finbox"
    base_url = f"https://{sub}.keka.com/api/v1"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    # Step 1: Search employee
    emp_summary = None
    try:
        res = requests.post(
            f"{base_url}/hris/employees/search",
            headers=headers,
            json={"workEmail": clean_email},
            timeout=10
        )
        if res.status_code == 200:
            payload = res.json()
            if isinstance(payload, dict):
                emp_summary = payload.get("data")
                if isinstance(emp_summary, list) and emp_summary:
                    emp_summary = emp_summary[0]
        elif res.status_code in (401, 403):
            return None, f"Keka Auth Failed: Invalid credentials (HTTP {res.status_code})"
    except Exception as e:
        return None, f"Keka search connection error: {e}"

    if not emp_summary or not isinstance(emp_summary, dict) or not emp_summary.get("id"):
        # Fallback search by searchKey
        try:
            res = requests.get(
                f"{base_url}/hris/employees",
                headers=headers,
                params={"searchKey": clean_email, "pageSize": 5},
                timeout=10
            )
            if res.status_code == 200:
                items = res.json().get("data", [])
                if isinstance(items, list):
                    for it in items:
                        if str(it.get("email") or "").strip().lower() == clean_email:
                            emp_summary = it
                            break
                    if not emp_summary and items:
                        emp_summary = items[0]
        except Exception:
            pass

    if not emp_summary or not isinstance(emp_summary, dict) or not emp_summary.get("id"):
        return None, f"Employee '{clean_email}' not found in Keka HRMS"

    emp_id = emp_summary.get("id")

    # Step 2: Fetch complete employee profile
    try:
        res_full = requests.get(f"{base_url}/hris/employees/{emp_id}", headers=headers, timeout=10)
        if res_full.status_code != 200:
            return None, f"Failed to retrieve employee profile (HTTP {res_full.status_code})"
        full = res_full.json().get("data", {})
    except Exception as e:
        return None, f"Error fetching employee profile from Keka: {e}"

    name = (full.get("displayName") or "").strip()
    emp_no = (full.get("employeeNumber") or "").strip()
    if not name:
        fn = (full.get("firstName") or "").strip()
        ln = (full.get("lastName") or "").strip()
        name = f"{fn} {ln}".strip() or "Employee"

    jt = full.get("jobTitle")
    if isinstance(jt, dict):
        designation = str(jt.get("title") or "").strip()
    else:
        designation = str(jt or "").strip()
    if not designation:
        designation = str(full.get("secondaryJobTitle") or "").strip()

    phone = str(full.get("mobilePhone") or full.get("workPhone") or "").strip()

    raw_dob = full.get("dateOfBirth")
    dob_formatted = ""
    if raw_dob:
        try:
            from datetime import datetime
            cleaned_dob = str(raw_dob).replace("Z", "+00:00").split("T")[0]
            dob_dt = datetime.strptime(cleaned_dob, "%Y-%m-%d")
            dob_formatted = dob_dt.strftime("%d %b, %Y")
        except Exception:
            dob_formatted = str(raw_dob)

    bg_val = full.get("bloodGroup")
    bg_map = {0: "N/A", 1: "A+", 2: "A-", 3: "B+", 4: "B-", 5: "O+", 6: "AB+", 7: "AB-", 8: "O-"}
    if isinstance(bg_val, int):
        blood_group = bg_map.get(bg_val, "N/A")
    else:
        blood_group = str(bg_val or "N/A").strip()

    em_name = ""
    em_phone = ""
    for cf in full.get("customFields", []):
        t = str(cf.get("title") or "").strip().lower()
        if "emergency contact person" in t or "emergency contact name" in t:
            em_name = str(cf.get("value") or "").strip()
        elif "emergency contact number" in t or "emergency contact phone" in t:
            em_phone = str(cf.get("value") or "").strip()

    loc_val = full.get("city") or full.get("location")
    if isinstance(loc_val, dict):
        loc_val = loc_val.get("title") or loc_val.get("name")
    location_name = str(loc_val or "Bengaluru").strip()

    resolved_addr = resolve_office_address(location_name, mapping=address_mapping)

    emp_data = {
        "name": name,
        "emp_no": emp_no,
        "designation": designation,
        "email": clean_email,
        "phone": phone,
        "dob": dob_formatted,
        "blood_group": blood_group,
        "location": location_name,
        "address": resolved_addr,
        "emergency_contact_name": em_name,
        "emergency_contact_phone": em_phone,
    }

    return emp_data, None


def validate_keka_employee_record(emp_data):
    """
    Strict completeness validation for an employee record fetched from Keka HRMS.
    Ensures ALL mandatory fields required for the ID card are present and valid:
      1. Employee Number (emp_no)
      2. Display Name / Employee Name (name)
      3. Designation / Job Title (designation)
      4. Work Email (email)
      5. Phone Number (phone)
      6. Date Of Birth (dob)
      7. Blood Group (blood_group - must not be N/A, blank, 0, or Unknown)
      8. Emergency Contact Name (emergency_contact_name)
      9. Emergency Contact Phone (emergency_contact_phone)
      10. Location City (location)
      11. Office Address (address)

    Returns:
        dict with keys:
            is_valid (bool): True ONLY if all required fields are present
            missing_fields (list of str): Human-readable list of missing fields
            issues (list of str): Detailed descriptions of validation failures
            hr_actions (list of str): Recommended HR remediation steps
    """
    if not emp_data or not isinstance(emp_data, dict):
        return {
            "is_valid": False,
            "missing_fields": ["Employee Record"],
            "issues": ["No employee record returned from Keka HRMS"],
            "hr_actions": ["Verify employee is registered and active in Keka HRMS"]
        }

    missing_fields = []
    issues = []
    hr_actions = []

    # 1. Employee Number
    emp_no = str(emp_data.get("emp_no") or "").strip()
    if not emp_no or is_field_blank(emp_no) or emp_no.lower() in ("n/a", "none", "null", "-"):
        missing_fields.append("Employee Number (EMP ID)")

    # 2. Name
    name = str(emp_data.get("name") or "").strip()
    if not name or is_field_blank(name) or name.lower() in ("n/a", "none", "null", "employee", "-"):
        missing_fields.append("Employee Name")

    # 3. Designation
    designation = str(emp_data.get("designation") or "").strip()
    if not designation or is_field_blank(designation) or designation.lower() in ("n/a", "none", "null", "-"):
        missing_fields.append("Designation")

    # 4. Email
    email = str(emp_data.get("email") or "").strip()
    if not email or is_field_blank(email) or "@" not in email:
        missing_fields.append("Official Email")

    # 5. Phone
    phone = str(emp_data.get("phone") or "").strip()
    phone_digits = re.sub(r"\D", "", phone)
    if not phone or is_field_blank(phone) or len(phone_digits) < 7:
        missing_fields.append("Mobile / Phone Number")

    # 6. Date Of Birth
    dob = str(emp_data.get("dob") or "").strip()
    if not dob or is_field_blank(dob) or dob.lower() in ("n/a", "none", "null", "-"):
        missing_fields.append("Date Of Birth")

    # 7. Blood Group
    bg = str(emp_data.get("blood_group") or "").strip()
    if not bg or is_field_blank(bg) or bg.upper() in ("N/A", "UNKNOWN", "NONE", "NULL", "0", "-", "NA"):
        missing_fields.append("Blood Group")

    # 8. Emergency Contact Name
    ec_name = str(emp_data.get("emergency_contact_name") or "").strip()
    if not ec_name or is_field_blank(ec_name) or ec_name.lower() in ("n/a", "none", "null", "-"):
        missing_fields.append("Emergency Contact Name")

    # 9. Emergency Contact Phone
    ec_phone = str(emp_data.get("emergency_contact_phone") or "").strip()
    ec_digits = re.sub(r"\D", "", ec_phone)
    if not ec_phone or is_field_blank(ec_phone) or len(ec_digits) < 7:
        missing_fields.append("Emergency Contact Phone")

    # 10. Location
    loc = str(emp_data.get("location") or "").strip()
    if not loc or is_field_blank(loc) or loc.lower() in ("n/a", "none", "null", "unknown", "-"):
        missing_fields.append("Location City")

    # 11. Office Address
    addr = str(emp_data.get("address") or "").strip()
    if not addr or is_field_blank(addr) or addr.lower() in ("n/a", "none", "null", "-"):
        missing_fields.append("Office Address")

    # Cross-check warnings
    if ec_name and name and ec_name.strip().lower() == name.strip().lower():
        issues.append("Emergency Contact Name matches employee's own name (Flagged for HR review)")
        hr_actions.append("Obtain an external emergency contact name in Keka HRMS")

    if len(phone_digits) >= 7 and len(ec_digits) >= 7 and phone_digits == ec_digits:
        issues.append("Emergency Contact Phone matches employee's personal phone (Flagged for HR review)")
        hr_actions.append("Obtain an alternate emergency contact phone number in Keka HRMS")

    if missing_fields:
        missing_str = ", ".join(missing_fields)
        issues.insert(0, f"Missing required Keka profile information: {missing_str}")
        hr_actions.insert(0, f"Update missing fields in Keka HRMS: {missing_str}")

    is_valid = (len(missing_fields) == 0)

    return {
        "is_valid": is_valid,
        "missing_fields": missing_fields,
        "issues": issues,
        "hr_actions": hr_actions,
    }


# ==============================================================================
# MULTI-SOURCE PROFILE PHOTO FETCHER WITH AUTOMATIC FALLBACK
# ==============================================================================
def fetch_profile_photo_with_fallback(
    email,
    emp_no=None,
    slack_client=None,
    slack_token=None,
    keka_api_key=None,
    keka_client_id=None,
    keka_client_secret=None,
    keka_subdomain=None,
    photos_dir=None,
    photo_match_mode="auto"
):
    """
    Hierarchical Multi-Source Profile Photo Fetcher:
      1. Tries Keka HRMS first (using OAuth Client Credentials or direct token).
      2. If Keka has no photo / employee not found / fails / key missing,
         falls back seamlessly to Slack.
      3. If both sources fail, returns detailed diagnostic message.

    Returns:
        (image_bytes, error_message, photo_status_label, photo_source)
        where photo_source is 'Keka', 'Slack', or 'None'.
    """
    clean_email = str(email or "").strip().lower()
    clean_emp_no = str(emp_no or "").strip()

    # Priority 0: Local Photos Folder (if provided)
    if photos_dir and Path(photos_dir).is_dir():
        local_bytes = find_local_photo(photos_dir, emp_no=clean_emp_no, email=clean_email, match_mode=photo_match_mode)
        if local_bytes:
            return local_bytes, None, "Valid Local Photo", "Local Folder"

    k_key = (keka_api_key or os.getenv("KEKA_API_KEY", "")).strip()
    k_cid = (keka_client_id or os.getenv("KEKA_CLIENT_ID", "")).strip()
    k_csec = (keka_client_secret or os.getenv("KEKA_CLIENT_SECRET", "")).strip()
    k_sub = (keka_subdomain or os.getenv("KEKA_SUBDOMAIN", "finbox")).strip()

    keka_attempted = False
    keka_err_msg = ""
    keka_stat = ""

    # Priority 1: Keka HRMS (requires key or cid+csec)
    if k_key or (k_cid and k_csec):
        keka_attempted = True
        k_bytes, k_err, k_status = fetch_keka_profile_photo(
            clean_email, emp_no=clean_emp_no, api_key=k_key,
            client_id=k_cid, client_secret=k_csec, subdomain=k_sub
        )
        if k_bytes and not k_err:
            return k_bytes, None, "Valid Keka Photo", "Keka"
        keka_err_msg = k_err or "No photo"
        keka_stat = k_status

    # Priority 2: Slack Fallback
    s_token = (slack_token or os.getenv("SLACK_BOT_TOKEN", "")).strip()
    s_client = slack_client
    if not s_client and s_token and not s_token.startswith("xoxb-your-"):
        try:
            s_client = WebClient(token=s_token)
        except Exception:
            s_client = None

    slack_attempted = False
    slack_err_msg = ""
    slack_stat = ""

    if s_client and s_token:
        slack_attempted = True
        s_bytes, s_err, s_status = fetch_slack_profile_photo(
            s_client, clean_email, s_token
        )
        if s_bytes and not s_err:
            return s_bytes, None, s_status, "Slack"
        slack_err_msg = s_err or "No photo"
        slack_stat = s_status

    # Phase 3: Both Failed or None Available
    reasons = []
    if keka_attempted:
        reasons.append(f"Keka: {keka_err_msg}")
    elif not k_key and not (k_cid and k_csec):
        reasons.append("Keka: not configured")

    if slack_attempted:
        reasons.append(f"Slack: {slack_err_msg}")
    elif not s_token:
        reasons.append("Slack: not configured")

    combined_reason = " | ".join(reasons)
    primary_status = slack_stat if slack_attempted else (keka_stat if keka_attempted else "No Connector Configured")

    return None, combined_reason, primary_status, "None"


def prefetch_photos_concurrent(
    valid_employees,
    slack_client=None,
    slack_token=None,
    cache=None,
    keka_api_key=None,
    keka_client_id=None,
    keka_client_secret=None,
    keka_subdomain=None,
    photos_dir=None,
    photo_match_mode="auto",
    max_workers=4
):
    """
    Pre-fetches profile photos concurrently for validated employees using a controlled thread pool.
    - Sourcing hierarchy: Local Folder (if provided) -> Keka HRMS 1st -> Slack fallback.
    - Matches strictly by employee clean email (and emp_no).
    - Caches original photos safely in BatchImageCache.
    """
    if not valid_employees or cache is None:
        return

    has_local = bool(photos_dir and Path(photos_dir).is_dir())
    has_keka = bool((keka_api_key or os.getenv("KEKA_API_KEY", "")).strip() or ((keka_client_id or os.getenv("KEKA_CLIENT_ID", "")).strip() and (keka_client_secret or os.getenv("KEKA_CLIENT_SECRET", "")).strip()))
    has_slack = bool(slack_client or (slack_token or os.getenv("SLACK_BOT_TOKEN", "")).strip())

    if not has_local and not has_keka and not has_slack:
        return

    # Gather unique employees while preserving order
    unique_candidates = []
    seen = set()
    for emp in valid_employees:
        clean_email = str(emp.get("email") or "").strip().lower()
        if clean_email and clean_email not in seen and clean_email not in ["", "nan", "none", "null", "n/a", "-"]:
            seen.add(clean_email)
            unique_candidates.append(emp)

    total_to_fetch = len(unique_candidates)
    if total_to_fetch == 0:
        return

    src_labels = []
    if has_local:
        src_labels.append("Local Folder")
    if has_keka:
        src_labels.append("Keka HRMS")
    if has_slack:
        src_labels.append("Slack")
    src_label = " -> ".join(src_labels)
    print(f"[+] Prefetching profile photos for {total_to_fetch} employee(s) via {src_label} (worker pool: {max_workers})...")

    def _worker(emp):
        clean_email = str(emp.get("email") or "").strip().lower()
        emp_no = str(emp.get("emp_no") or "").strip()
        raw_bytes, err_msg, status_label, source = fetch_profile_photo_with_fallback(
            clean_email,
            emp_no=emp_no,
            slack_client=slack_client,
            slack_token=slack_token,
            keka_api_key=keka_api_key,
            keka_client_id=keka_client_id,
            keka_client_secret=keka_client_secret,
            keka_subdomain=keka_subdomain,
            photos_dir=photos_dir,
            photo_match_mode=photo_match_mode
        )
        return clean_email, raw_bytes, err_msg, status_label, source

    local_count = 0
    keka_count = 0
    slack_count = 0
    failed_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_worker, emp): emp for emp in unique_candidates}
        fetched_count = 0
        for future in as_completed(futures):
            try:
                clean_email, raw_bytes, err_msg, status_label, source = future.result()
                cache.put_raw(clean_email, raw_bytes, err_msg, status_label, source)
                if raw_bytes:
                    if source == "Local Folder":
                        local_count += 1
                    elif source == "Keka":
                        keka_count += 1
                    else:
                        slack_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                emp = futures[future]
                clean_email = str(emp.get("email") or "").strip().lower()
                cache.put_raw(clean_email, None, f"Fetch error: {e}", "Lookup Error", "None")
                failed_count += 1
            fetched_count += 1
            if fetched_count % 10 == 0 or fetched_count == total_to_fetch:
                print(f"    - Prefetched {fetched_count}/{total_to_fetch} profile photos (Local: {local_count}, Keka: {keka_count}, Slack: {slack_count})...")

    print(f"[+] Profile photo prefetch complete ({total_to_fetch} queried: {local_count} Local, {keka_count} Keka, {slack_count} Slack, {failed_count} skipped/missing).\n")


def prefetch_slack_photos_concurrent(valid_employees, slack_client, slack_token, cache, max_workers=4):
    """Backwards-compatible wrapper calling prefetch_photos_concurrent."""
    return prefetch_photos_concurrent(
        valid_employees,
        slack_client=slack_client,
        slack_token=slack_token,
        cache=cache,
        max_workers=max_workers
    )


def process_photo_circular(image_bytes, target_dim=300):
    """
    Classic Design Photo: Centrally crops an image to a square,
    applies detail sharpening, and an anti-aliased circular mask.
    Returns: BytesIO object containing PNG image.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    w, h = img.size
    dim = min(w, h)
    left = (w - dim) // 2
    top = (h - dim) // 2
    cropped = img.crop((left, top, left + dim, top + dim))

    resized = cropped.resize((target_dim, target_dim), Image.Resampling.LANCZOS)
    try:
        from PIL import ImageFilter, ImageEnhance
        resized = resized.filter(ImageFilter.UnsharpMask(radius=1.4, percent=125, threshold=2))
        resized = ImageEnhance.Sharpness(resized).enhance(1.12)
    except Exception:
        pass

    mask_scale = 4
    mask_dim = target_dim * mask_scale
    mask = Image.new("L", (mask_dim, mask_dim), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, mask_dim - 1, mask_dim - 1), fill=255)
    mask = mask.resize((target_dim, target_dim), Image.Resampling.LANCZOS)

    output = Image.new("RGBA", (target_dim, target_dim), (0, 0, 0, 0))
    output.paste(resized, (0, 0), mask=mask)

    out_buf = io.BytesIO()
    output.save(out_buf, format="PNG")
    out_buf.seek(0)
    return out_buf


def process_photo_modern_circular(image_bytes, target_dim=800, session=None, **kwargs):
    """
    Modern Design Photo:
    Displays the employee's original profile photograph inside a large circular placeholder,
    preserving the source photograph and its original background intact.
    Automatically centre-crops the photograph to a 1:1 square preserving original aspect ratio,
    applies adaptive unsharp masking and micro-contrast enhancement for maximum print clarity,
    and applies a high-quality 4x antialiased circular clipping mask.
    Returns: BytesIO object containing PNG image with equal width and height.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    w, h = img.size

    # Aspect-ratio-preserving centre cropping to fill a 1:1 square
    dim = min(w, h)
    left = (w - dim) // 2
    top = (h - dim) // 2
    cropped = img.crop((left, top, left + dim, top + dim))

    # Resize to high-resolution square using high-order Lanczos filter
    resized = cropped.resize((target_dim, target_dim), Image.Resampling.LANCZOS)

    # Professional Clarity & Detail Enhancement for ID Card Printing
    # Portrait photos scaled up from HRMS portals often suffer from softness and compression artifacts.
    # Adaptive unsharp masking sharpens facial features, eyes, and hair edges crisply.
    try:
        from PIL import ImageFilter, ImageEnhance
        # Gentle UnsharpMask tailored for portrait photography
        enhanced = resized.filter(ImageFilter.UnsharpMask(radius=1.5, percent=130, threshold=2))
        # Micro-contrast and sharpness adjustment for vivid, crisp printing
        enhanced = ImageEnhance.Sharpness(enhanced).enhance(1.15)
        enhanced = ImageEnhance.Contrast(enhanced).enhance(1.04)
        resized = enhanced
    except Exception:
        pass

    # High-quality 4x antialiased circular clipping mask
    mask_scale = 4
    mask_dim = target_dim * mask_scale
    mask = Image.new("L", (mask_dim, mask_dim), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, mask_dim - 1, mask_dim - 1), fill=255)
    mask = mask.resize((target_dim, target_dim), Image.Resampling.LANCZOS)

    # Composite photo onto transparent background with circular mask
    output = Image.new("RGBA", (target_dim, target_dim), (0, 0, 0, 0))
    output.paste(resized, (0, 0), mask=mask)

    out_buf = io.BytesIO()
    output.save(out_buf, format="PNG")
    out_buf.seek(0)
    return out_buf


# Aliases for backward compatibility
process_photo_modern_portrait = process_photo_modern_circular
process_photo_modern_cutout = process_photo_modern_circular



# ==============================================================================
# SLACK CONNECTION TEST MODE (--test-email)
# ==============================================================================
def run_slack_test(test_email):
    """
    Temporary Slack connection test mode.
    - Connects to Slack using SLACK_BOT_TOKEN from .env
    - Calls users.lookupByEmail with test_email
    - Prints display name
    - Prints whether a custom profile photo was found
    - Prints which Slack image size was selected
    - Downloads profile photo and saves it as output/slack_test_photo.jpg
    - Never exposes or prints the token
    - Does NOT generate an ID card
    """
    print("=" * 60)
    print("              Slack Connection Test Mode                    ")
    print("=" * 60)
    print(f"Target Email: {test_email}")

    load_dotenv()
    slack_token = os.getenv("SLACK_BOT_TOKEN", "").strip()

    if not slack_token:
        print("\n[X] Slack Error: not_authed")
        print("    SLACK_BOT_TOKEN is not defined in .env.")
        print("    Please create a .env file containing:")
        print("    SLACK_BOT_TOKEN=xoxb-your-token-here")
        print("=" * 60 + "\n")
        return 1

    try:
        client = WebClient(token=slack_token)
    except Exception as e:
        print(f"\n[X] Error initializing Slack client: {e}")
        print("=" * 60 + "\n")
        return 1

    print("\n[+] Querying Slack users.lookupByEmail...")
    try:
        response = client.users_lookupByEmail(email=test_email.strip())
    except SlackApiError as e:
        err = e.response.get("error", "unknown_error") if hasattr(e.response, "get") else str(e)
        resp_dict = getattr(e.response, "data", e.response) if isinstance(e.response, dict) or hasattr(e.response, "data") else {}
        explanation = explain_slack_error(err, resp_dict)
        print(f"\n[X] Slack Error: {err}")
        print(f"    {explanation}")
        print("=" * 60 + "\n")
        return 1
    except requests.RequestException as e:
        print(f"\n[X] Network Error connecting to Slack: {e}")
        print("=" * 60 + "\n")
        return 1
    except Exception as e:
        print(f"\n[X] Unexpected error during Slack lookup: {e}")
        print("=" * 60 + "\n")
        return 1

    if not response.get("ok", False):
        err = response.get("error", "unknown_error")
        explanation = explain_slack_error(err, response)
        print(f"\n[X] Slack Error: {err}")
        print(f"    {explanation}")
        print("=" * 60 + "\n")
        return 1

    user = response.get("user", {})
    profile = user.get("profile", {})

    display_name = (
        profile.get("display_name")
        or profile.get("real_name")
        or user.get("real_name")
        or user.get("name")
        or "N/A"
    )
    print(f"[+] Slack User Found:         {display_name}")

    is_custom_photo = profile.get("is_custom_image", None)
    if is_custom_photo is True:
        custom_str = "Yes (User has uploaded a custom profile photo)"
    elif is_custom_photo is False:
        custom_str = "No (Default Slack avatar in use)"
    else:
        custom_str = "Unknown / Not specified by Slack"
    print(f"[+] Custom Profile Photo:     {custom_str}")

    photo_resolution_keys = [
        "image_original",
        "image_1024",
        "image_512",
        "image_192",
        "image_72",
        "image_48",
        "image_32"
    ]

    selected_key = None
    photo_url = None
    for key in photo_resolution_keys:
        url = profile.get(key)
        if url and isinstance(url, str) and url.startswith("http"):
            selected_key = key
            photo_url = url
            break

    if not photo_url:
        print("[-] Selected Image Size:      None (No profile photo URL found)")
        print("\n[X] Error: Could not find any profile photo for this user.")
        print("=" * 60 + "\n")
        return 1

    print(f"[+] Selected Image Size:      {selected_key}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    test_photo_path = OUTPUT_DIR / "slack_test_photo.jpg"

    try:
        headers = {"Authorization": f"Bearer {slack_token}"}
        req = requests.get(photo_url, headers=headers, timeout=15)
        if req.status_code != 200:
            req = requests.get(photo_url, timeout=15)

        if req.status_code != 200:
            print(f"[X] Error downloading photo: HTTP {req.status_code}")
            print("=" * 60 + "\n")
            return 1

        img = Image.open(io.BytesIO(req.content)).convert("RGB")
        img.save(test_photo_path, format="JPEG", quality=95)
        print(f"[+] Profile Photo Saved As:   {test_photo_path}")
        print("\n[+] Slack test connection successful! (No ID cards generated)")
        print("=" * 60 + "\n")
        return 0

    except Exception as e:
        print(f"[X] Error saving photo: {e}")
        print("=" * 60 + "\n")
        return 1


def run_keka_test(test_email, test_emp_no=None):
    """
    Keka HRMS profile photo connection test mode.
    - Connects to Keka API using KEKA_API_KEY and KEKA_SUBDOMAIN from .env
    - Looks up employee by workEmail (and emp_no fallback)
    - Extracts custom profile photo URL
    - Downloads profile photo and saves it as output/keka_test_photo.jpg
    - Does NOT generate an ID card
    """
    print("=" * 60)
    print("           Keka HRMS Profile Photo Test Mode                 ")
    print("=" * 60)
    print(f"Target Email: {test_email}")

    load_dotenv(override=True)
    api_key = os.getenv("KEKA_API_KEY", "").strip()
    subdomain = os.getenv("KEKA_SUBDOMAIN", "finbox").strip()

    if not api_key:
        print("\n[X] Keka Error: KEKA_API_KEY is not defined in .env.")
        print("    Add KEKA_API_KEY=... in your .env file or Connectors tab.")
        print("=" * 60 + "\n")
        return 1

    print(f"Subdomain:    {subdomain}.keka.com")
    raw_bytes, err_msg, status_label = fetch_keka_profile_photo(
        test_email, emp_no=test_emp_no, api_key=api_key, subdomain=subdomain
    )

    if err_msg or not raw_bytes:
        print(f"\n[X] Keka Photo Test Failed: {err_msg} ({status_label})")
        print("=" * 60 + "\n")
        return 1

    try:
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        test_photo_path = out_dir / "keka_test_photo.jpg"
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        img.save(test_photo_path, format="JPEG", quality=95)
        print(f"[+] Profile Photo Saved As:   {test_photo_path}")
        print(f"\n[+] Keka HRMS test successful ({status_label})! (No ID cards generated)")
        print("=" * 60 + "\n")
        return 0
    except Exception as e:
        print(f"[X] Error saving photo: {e}")
        print("=" * 60 + "\n")
        return 1


# ==============================================================================
# FILE ACCESS & EXCEL UTILITIES
# ==============================================================================
def find_excel_file(project_dir="."):
    """
    Search for the source Excel file in the project folder.
    Prioritizes 'ID card generation.xlsx'.
    """
    base_path = Path(project_dir).resolve()

    preferred = base_path / "ID card generation.xlsx"
    if preferred.exists() and not preferred.name.startswith("~$"):
        return preferred

    for f in base_path.glob("*.xls*"):
        if f.name.startswith("~$"):
            continue
        if "report" in f.name.lower():
            continue
        if f.is_file():
            return f

    return None


def read_excel_safely(file_path):
    """
    Read an Excel file into a pandas DataFrame.
    Includes a Windows-specific fallback for PermissionError [Errno 13],
    which occurs when Microsoft Excel has the file open with a write lock.
    """
    try:
        return pd.read_excel(file_path)
    except PermissionError:
        if sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                GENERIC_READ = 0x80000000
                FILE_SHARE_READ = 0x00000001
                FILE_SHARE_WRITE = 0x00000002
                FILE_SHARE_DELETE = 0x00000004
                OPEN_EXISTING = 3
                FILE_ATTRIBUTE_NORMAL = 0x80

                handle = kernel32.CreateFileW(
                    str(file_path),
                    GENERIC_READ,
                    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                    None,
                    OPEN_EXISTING,
                    FILE_ATTRIBUTE_NORMAL,
                    None,
                )
                if handle != -1 and handle != 0:
                    file_size = kernel32.GetFileSize(handle, None)
                    buf = ctypes.create_string_buffer(file_size)
                    bytes_read = ctypes.c_ulong(0)
                    kernel32.ReadFile(handle, buf, file_size, ctypes.byref(bytes_read), None)
                    kernel32.CloseHandle(handle)
                    return pd.read_excel(io.BytesIO(buf.raw[: bytes_read.value]))
            except Exception as ex:
                print(f"[!] Warning: Windows shared handle read attempt failed: {ex}")
        raise


def normalize_string(val):
    """Normalize string for fuzzy header comparison."""
    if val is None:
        return ""
    return re.sub(r"[\s_]+", " ", str(val).strip().lower())


def map_columns(df):
    """
    Detect and map Excel column headers to standard employee attributes:
    1. Employee Number
    2. Name
    3. Designation
    4. Email
    5. Phone
    6. Location
    7. Blood Group
    8. Date Of Birth
    9. Address
    10. Emergency Contact Name
    11. Emergency Contact Phone
    """
    column_aliases = {
        "emp_no": [
            "employee number", "employee no", "employee id", "emp number",
            "emp no", "emp id", "empid", "emp_number", "emp_id", "id"
        ],
        "name": [
            "name", "employee name", "emp name", "full name", "employee_name", "emp_name"
        ],
        "designation": [
            "designation", "role", "title", "job title", "position"
        ],
        "email": [
            "email", "email id", "official email", "work email", "email address", "mail"
        ],
        "phone": [
            "phone", "phone number", "mobile", "mobile number", "contact", "contact number", "phone no"
        ],
        "location": [
            "location", "city", "office location", "work location", "base location", "branch"
        ],
        "blood_group": [
            "blood group", "bloodgroup", "blood type", "blood"
        ],
        "dob": [
            "date of birth", "dob", "birth date", "birthdate", "d.o.b", "d.o.b."
        ],
        "address": [
            "address", "residential address", "home address", "permanent address"
        ],
        "emergency_contact_name": [
            "emergency contact name", "emergency_contact_name"
        ],
        "emergency_contact_phone": [
            "emergency contact phone", "emergency_contact_phone"
        ],
    }

    norm_cols = {col: normalize_string(col) for col in df.columns}
    mapped = {}

    for standard_key, aliases in column_aliases.items():
        for original_col, norm_col in norm_cols.items():
            if norm_col in aliases:
                mapped[standard_key] = original_col
                break

    return mapped


def is_field_blank(val):
    """
    Returns True if value is None, NaN, empty string, whitespace only,
    or contains placeholder markers like 'N/A', 'null', 'none', '-', 'nil'.
    """
    if val is None or pd.isna(val):
        return True
    s = str(val).strip()
    if not s:
        return True
    if s.lower() in ["", "nan", "none", "nat", "null", "n/a", "not available", "-", "nil", "na"]:
        return True
    return False


def format_name_casing(val):
    """
    Format name using proper name casing.
    Preserves the casing entered in Excel wherever possible.
    If the Excel value is entirely uppercase (e.g. 'POORNIMA'), converts to readable name casing ('Poornima').
    Examples:
        POORNIMA -> Poornima
        RAHUL SHARMA -> Rahul Sharma
        Nishita Dutta Chowdhury -> Nishita Dutta Chowdhury
    """
    if is_field_blank(val):
        return "N/A"
    s = re.sub(r"\s+", " ", str(val)).strip()
    if s.isupper() or s.islower():
        return s.title()
    return s


def clean_field_value(val, field_type="text"):
    """
    Clean and format Excel cell values.
    Returns 'N/A' if the field is blank or missing.
    """
    if is_field_blank(val):
        return "N/A"

    if isinstance(val, (datetime, pd.Timestamp)):
        return val.strftime("%d %b, %Y")

    if isinstance(val, float) and val.is_integer():
        return str(int(val))

    text = str(val).strip()

    if field_type == "email":
        return text.lower()

    if field_type == "emp_no":
        if text.endswith(".0"):
            return text[:-2]

    if field_type == "blood_group":
        # Retain original spacing, brackets, capitalisation and formatting from Excel.
        # Normalise only unnecessary leading/trailing or repeated whitespace.
        bg = re.sub(r"\s+", " ", text).strip()
        if is_field_blank(bg):
            return "N/A"
        return bg

    if field_type == "emergency_contact_name":
        return format_name_casing(text)

    return text


def sanitize_location(val):
    r"""
    Sanitize location name for directory creation and reporting.
    - Strips whitespace.
    - Removes Windows illegal characters: \ / : * ? " < > |
    - Normalizes casing consistently with Title Case (e.g. 'mumbai' -> 'Mumbai').
    - Does NOT merge distinct city names (e.g. Bangalore and Bengaluru remain distinct).
    - Returns None if empty or invalid.
    """
    if is_field_blank(val):
        return None
    cleaned = re.sub(r'[\\/*?:"<>|]', "", str(val)).strip()
    if not cleaned or cleaned.lower() in ["", "nan", "none", "null", "n/a", "unknown", "-"]:
        return None
    return cleaned.title()


REQUIRED_EMPLOYEE_FIELDS = [
    ("emp_no", "Employee Number"),
    ("name", "Name"),
    ("designation", "Designation"),
    ("email", "Email"),
    ("phone", "Phone"),
    ("location", "Location"),
    ("blood_group", "Blood Group"),
    ("dob", "Date Of Birth"),
    ("address", "Address"),
    ("emergency_contact_name", "Emergency Contact Name"),
    ("emergency_contact_phone", "Emergency Contact Phone"),
]


def validate_employee_record(row, col_map, seen_emp_nums=None):
    """
    Strict completeness validation across all 11 columns.
    Checks:
      - Completeness of all 11 fields (no blank, NaN, null, N/A, whitespace)
      - Duplicate Employee Number detection
      - Emergency Contact Name != Employee Name
      - Emergency Contact Phone != Personal Phone
      - Valid sanitized Location
    Returns:
        dict with keys:
            is_valid (bool)
            emp_data (dict)
            missing_fields (list of str)
            issues (list of str)
            hr_actions (list of str)
    """
    if seen_emp_nums is None:
        seen_emp_nums = set()

    missing_fields = []
    issues = []
    hr_actions = []

    # 1. Strict completeness across all 11 columns
    for field_key, display_name in REQUIRED_EMPLOYEE_FIELDS:
        orig_col = col_map.get(field_key)
        if not orig_col:
            missing_fields.append(display_name)
            continue
        raw_val = row.get(orig_col)
        if is_field_blank(raw_val):
            missing_fields.append(display_name)

    # 2. Extract cleaned values
    emp_no = clean_field_value(row.get(col_map.get("emp_no")), "emp_no")
    name = clean_field_value(row.get(col_map.get("name")), "text")
    designation = clean_field_value(row.get(col_map.get("designation")), "text")
    email = clean_field_value(row.get(col_map.get("email")), "email")
    phone = clean_field_value(row.get(col_map.get("phone")), "text")
    raw_location = clean_field_value(row.get(col_map.get("location")), "text")
    clean_location = sanitize_location(row.get(col_map.get("location")))
    blood_group = clean_field_value(row.get(col_map.get("blood_group")), "blood_group")
    dob = clean_field_value(row.get(col_map.get("dob")), "text")
    address = clean_field_value(row.get(col_map.get("address")), "text")
    ec_name = clean_field_value(row.get(col_map.get("emergency_contact_name")), "emergency_contact_name")
    ec_phone = clean_field_value(row.get(col_map.get("emergency_contact_phone")), "text")

    # If location is invalid after sanitization, add to missing fields if not present
    if not clean_location and "Location" not in missing_fields:
        missing_fields.append("Location")

    emp_data = {
        "emp_no": emp_no,
        "name": name,
        "designation": designation,
        "email": email,
        "phone": phone,
        "location": clean_location or raw_location,
        "blood_group": blood_group,
        "dob": dob,
        "address": address,
        "emergency_contact_name": ec_name,
        "emergency_contact_phone": ec_phone,
    }

    # 3. Duplicate Employee Number check
    if emp_no and emp_no != "N/A":
        if emp_no in seen_emp_nums:
            issues.append(f"Duplicate Employee Number detected ('{emp_no}')")
            hr_actions.append("Resolve duplicate Employee Number with HR records")
        else:
            seen_emp_nums.add(emp_no)

    # 4. Emergency Contact self-match checks (Requirement 4)
    if ec_name != "N/A" and name != "N/A" and ec_name.strip().lower() == name.strip().lower():
        issues.append("Emergency Contact Name matches employee's own name (Flagged for HR review)")
        hr_actions.append("Obtain an external emergency contact name from employee")

    emp_digits = re.sub(r"\D", "", phone or "")
    ec_digits = re.sub(r"\D", "", ec_phone or "")
    if len(emp_digits) >= 7 and emp_digits == ec_digits:
        issues.append("Emergency Contact Phone matches employee's personal phone (Flagged for HR review)")
        hr_actions.append("Obtain an alternate emergency contact phone number from employee")

    # 5. Missing Fields issue formatting (Requirement 1)
    if missing_fields:
        missing_str = ", ".join(missing_fields)
        issues.insert(0, f"Missing required employee information: {missing_str}")
        hr_actions.insert(0, f"Collect missing fields from employee: {missing_str}")

    is_valid = (len(missing_fields) == 0 and len(issues) == 0)

    return {
        "is_valid": is_valid,
        "emp_data": emp_data,
        "missing_fields": missing_fields,
        "issues": issues,
        "hr_actions": hr_actions,
    }



def validate_emergency_contact(emp_name, emp_phone, raw_ec_name, raw_ec_phone):
    """
    Validates emergency contact data:
    - Emergency Contact Name must come ONLY from Emergency Contact Name column.
    - Emergency Contact Phone must come ONLY from Emergency Contact Phone column.
    - Never automatically substitute the employee's own name or personal phone number.
    - If missing or matching employee's own details, returns 'N/A' and flags for review.
    Returns:
        (validated_ec_name, validated_ec_phone, flagged_reasons)
    """
    flagged = []

    # 1. Emergency Contact Name: Must come ONLY from Emergency Contact Name
    if not raw_ec_name or raw_ec_name == "N/A":
        final_ec_name = "N/A"
        flagged.append("Emergency Contact Name is missing")
    elif emp_name and emp_name != "N/A" and raw_ec_name.strip().lower() == emp_name.strip().lower():
        final_ec_name = "N/A"
        flagged.append(f"Emergency Contact Name matches employee's own name ('{raw_ec_name}')")
    else:
        final_ec_name = raw_ec_name

    # 2. Emergency Contact Phone: Must come ONLY from Emergency Contact Phone
    emp_digits = re.sub(r"\D", "", str(emp_phone or ""))
    ec_digits = re.sub(r"\D", "", str(raw_ec_phone or ""))
    if not raw_ec_phone or raw_ec_phone == "N/A":
        final_ec_phone = "N/A"
        flagged.append("Emergency Contact Phone is missing")
    elif emp_digits and ec_digits and emp_digits == ec_digits:
        final_ec_phone = "N/A"
        flagged.append(f"Emergency Contact Phone matches employee's personal phone ('{raw_ec_phone}')")
    else:
        final_ec_phone = raw_ec_phone

    return final_ec_name, final_ec_phone, flagged


def sanitize_filename(name):
    """Sanitize string for safe cross-platform filesystem path."""
    clean = re.sub(r'[\\/*?:"<>|]', "_", str(name)).strip()
    return clean or "unknown"


# ==============================================================================
# REPORTLAB TEXT SCALING & WRAPPING HELPERS
# ==============================================================================
def fit_text_single_line(text, font_name, base_size, min_size, max_width):
    """
    Find the highest font size between base_size and min_size (stepping down by 0.5 pt)
    where text width <= max_width. Returns None if text cannot fit even at min_size.
    """
    if not text:
        return base_size
    s = base_size
    while s >= min_size:
        if stringWidth(text, font_name, s) <= max_width:
            return round(s, 2)
        s -= 0.5
    return None


def fit_text_multiline(text, font_name, base_size, min_size, max_width, max_lines=2, single_line_min_size=None):
    """
    Fit text either on a single line or wrapped into balanced lines (up to max_lines).
    - First attempts a single line from base_size down to single_line_min_size.
    - If single line cannot fit, wraps into balanced lines from base_size down to min_size,
      minimizing difference in line lengths to avoid orphan words.
    Returns:
        (list_of_lines, font_size) or (None, None) if text cannot fit within thresholds.
    """
    if not text:
        return [""], base_size
    if single_line_min_size is None:
        single_line_min_size = base_size

    # 1. Try single line first
    s = base_size
    while s >= single_line_min_size:
        if stringWidth(text, font_name, s) <= max_width:
            return [text], round(s, 2)
        s -= 0.5

    words = text.split()
    if len(words) <= 1:
        s = base_size
        while s >= min_size:
            if stringWidth(text, font_name, s) <= max_width:
                return [text], round(s, 2)
            s -= 0.5
        return None, None

    # 2. Try 2 balanced lines
    s = base_size
    while s >= min_size:
        best_split = None
        min_diff = float("inf")
        for i in range(1, len(words)):
            l1 = " ".join(words[:i])
            l2 = " ".join(words[i:])
            w1 = stringWidth(l1, font_name, s)
            w2 = stringWidth(l2, font_name, s)
            if w1 <= max_width and w2 <= max_width:
                diff = abs(w1 - w2)
                if diff < min_diff:
                    min_diff = diff
                    best_split = [l1, l2]
        if best_split:
            return best_split, round(s, 2)
        s -= 0.5

    return None, None


def fit_address_multiline(text, font_name, base_size, min_size, max_width, max_lines=3):
    """
    Wrap long addresses across up to max_lines, scaling down font size if needed.
    Returns:
        (list_of_lines, font_size) or (None, None) if address cannot fit within max_lines.
    """
    if not text:
        return [""], base_size
    words = text.split()
    s = base_size
    while s >= min_size:
        lines = []
        cur = []
        for w in words:
            t = " ".join(cur + [w])
            if stringWidth(t, font_name, s) <= max_width:
                cur.append(w)
            else:
                if cur:
                    lines.append(" ".join(cur))
                cur = [w]
        if cur:
            lines.append(" ".join(cur))
        if len(lines) <= max_lines:
            return lines, round(s, 2)
        s -= 0.2
    return None, None


def draw_scaled_centred_text(c, text, center_x, y, max_width, base_font_size, font_name="Helvetica-Bold", min_font_size=7):
    """Dynamically reduce font size so text never overflows max_width."""
    font_size = base_font_size
    while font_size > min_font_size and stringWidth(text, font_name, font_size) > max_width:
        font_size -= 0.5
    c.setFont(font_name, font_size)
    c.drawCentredString(center_x, y, text)


def draw_scaled_left_text(c, text, x, y, max_width, base_font_size, font_name="Helvetica", min_font_size=6):
    """Dynamically reduce font size so left-aligned text never overflows max_width."""
    font_size = base_font_size
    while font_size > min_font_size and stringWidth(text, font_name, font_size) > max_width:
        font_size -= 0.5
    c.setFont(font_name, font_size)
    c.drawString(x, y, text)


def draw_wrapped_centred_text(c, text, center_x, start_y, max_width, line_height, base_font_size=10, font_name="Helvetica", min_font_size=7.5):
    """
    Wrap text across multiple lines and center each line horizontally.
    """
    lines, font_size = fit_address_multiline(text, font_name, base_font_size, min_font_size, max_width, max_lines=3)
    if not lines:
        lines = [text]
        font_size = min_font_size

    c.setFont(font_name, font_size)
    cur_y = start_y
    for line in lines:
        c.drawCentredString(center_x, cur_y, line)
        cur_y -= line_height


def validate_employee_text_fitting(emp_data, design_name="Classic"):
    """
    Strict verification of automatic text fitting for all dynamic fields.
    Checks whether fields can fit legibly without text clipping or overflow
    according to minimum readable font size thresholds:
      1. Employee Name:
         - Classic: max_width = 243.5 pt, min_size = 8.5 pt (Helvetica-Bold)
         - Modern:  max_width = 203.34 pt, min_size = 8.5 pt (Helvetica-Bold)
      2. Designation:
         - Classic: max_width = 243.5 pt, max_lines = 2, min_size = 6.0 pt (Helvetica)
         - Modern:  max_width = 203.34 pt, max_lines = 2, min_size = 6.0 pt (Helvetica)
      3. Other dynamic fields:
         - Classic Details: max_width = 115.5 pt, min_size = 6.0 pt (Helvetica)
         - Modern Employee Number: max_width = 203.34 pt, min_size = 6.0 pt (Helvetica)
         - Modern Emergency Contact Name: max_width = 144.34 pt, min_size = 6.0 pt (Helvetica-Bold)
         - Modern Emergency Contact Phone: max_width = 144.34 pt, min_size = 7.0 pt (Helvetica-Bold)
         - Classic Address: max_width = 220.0 pt, max_lines = 3, min_size = 6.5 pt (Helvetica)
         - Modern Address: max_width = 209.34 pt, max_lines = 3, min_size = 4.2 pt (Helvetica-Bold)

    Returns:
        (is_valid: bool, issue_description: str)
    """
    is_modern = (str(design_name or "").lower() == "modern")
    name = str(emp_data.get("name") or "").strip()
    desig = str(emp_data.get("designation") or "").strip()
    addr = str(emp_data.get("address") or "").strip()

    if is_modern:
        # 1. Employee Name (Modern uppercase, base 18.0 pt, min 8.5 pt, max_w 203.34 pt)
        name_s = fit_text_single_line(name.upper(), "Helvetica-Bold", 18.0, 8.5, 203.34)
        if name_s is None:
            return False, "Text fitting failed: Employee Name exceeds printable area at minimum 8.5pt"

        # 2. Designation (Modern uppercase, base 7.5 pt, min 6.0 pt, max_lines 2, max_w 203.34 pt)
        d_lines, d_s = fit_text_multiline(desig.upper(), "Helvetica", 7.5, 6.0, 203.34, max_lines=2, single_line_min_size=7.0)
        if not d_lines:
            return False, "Text fitting failed: Designation exceeds printable area at minimum 6.0pt across 2 lines"

        # 3. Employee Number (Modern, base 8.5 pt, min 6.0 pt, max_w 203.34 pt)
        emp_no = str(emp_data.get("emp_no") or "").strip()
        eno_s = fit_text_single_line(emp_no, "Helvetica", 8.5, 6.0, 203.34)
        if eno_s is None:
            return False, "Text fitting failed: Employee Number exceeds printable area at minimum 6.0pt"

        # 4. Emergency Contact Name (Proper name casing, base 10.5 pt, min 6.0 pt, max_w 144.34 pt)
        ec_name = format_name_casing(str(emp_data.get("emergency_contact_name") or ""))
        ecn_s = fit_text_single_line(ec_name, "Helvetica-Bold", 10.5, 6.0, 144.34)
        if ecn_s is None:
            return False, "Text fitting failed: Emergency Contact Name exceeds printable area at minimum 6.0pt"

        # 5. Emergency Contact Phone (Modern, base 10.5 pt, min 7.0 pt, max_w 144.34 pt)
        ec_phone = str(emp_data.get("emergency_contact_phone") or "").strip()
        ecp_s = fit_text_single_line(ec_phone, "Helvetica-Bold", 10.5, 7.0, 144.34)
        if ecp_s is None:
            return False, "Text fitting failed: Emergency Contact Phone exceeds printable area at minimum 7.0pt"

        # 6. Blood Group (Retain original formatting, base 10.5 pt, min 7.0 pt, max_w 144.34 pt)
        raw_bg = str(emp_data.get("blood_group") or "")
        bg_norm = re.sub(r"\s+", " ", raw_bg).strip()
        bg_s = fit_text_single_line(bg_norm, "Helvetica-Bold", 10.5, 7.0, 144.34)
        if bg_s is None:
            return False, "Text fitting failed: Blood Group exceeds printable area at minimum 7.0pt"

        # 7. Address (Modern uppercase, base 5.6 pt, min 4.2 pt, max_w 209.34 pt, max_lines 3)
        a_lines, a_s = fit_address_multiline(addr.upper(), "Helvetica-Bold", 5.6, 4.2, 209.34, max_lines=3)
        if not a_lines:
            return False, "Text fitting failed: Address exceeds printable area across 3 lines at minimum 4.2pt"
    else:
        # 1. Employee Name (Classic, base 15.0 pt, min 8.5 pt, max_w 243.5 pt)
        name_s = fit_text_single_line(name, "Helvetica-Bold", 15.0, 8.5, 243.5)
        if name_s is None:
            return False, "Text fitting failed: Employee Name exceeds printable area at minimum 8.5pt"

        # 2. Designation (Classic, base 9.0 pt, min 6.0 pt, max_lines 2, max_w 243.5 pt)
        d_lines, d_s = fit_text_multiline(desig, "Helvetica", 9.0, 6.0, 243.5, max_lines=2, single_line_min_size=8.0)
        if not d_lines:
            return False, "Text fitting failed: Designation exceeds printable area at minimum 6.0pt across 2 lines"

        # 3. Classic Details (base 8.25 pt, min 6.0 pt, max_w 115.5 pt)
        details_to_check = [
            ("Employee Number", "emp_no"),
            ("Phone", "phone"),
            ("Email", "email"),
            ("Location", "location"),
            ("Blood Group", "blood_group")
        ]
        for f_label, f_key in details_to_check:
            val = str(emp_data.get(f_key) or "")
            f_s = fit_text_single_line(val, "Helvetica", 8.25, 6.0, 115.5)
            if f_s is None:
                return False, f"Text fitting failed: {f_label} ('{val}') exceeds detail area at minimum 6.0pt"

        # 4. Address (Classic, base 10.0 pt, min 6.5 pt, max_w 220.0 pt, max_lines 3)
        a_lines, a_s = fit_address_multiline(addr, "Helvetica", 10.0, 6.5, 220.0, max_lines=3)
        if not a_lines:
            return False, "Text fitting failed: Address exceeds printable area across 3 lines at minimum 6.5pt"

    return True, None


# ==============================================================================
# DESIGN 1: CLASSIC ID CARD GENERATION (reference_id_card.pdf)
# ==============================================================================
def generate_classic_id_card_pdf(emp_data, photo_bytes_io, output_path):
    """
    Render the approved 2-page Classic FinBox ID card design:
      - Page 1 = Front:
          * Blue top header (#2986CE)
          * Circular profile photo in white frame (diameter 97.5 pt)
          * Employee Name (White bold, 15 pt)
          * Designation (White, 9 pt)
          * 5 detail rows: Employee Number, Phone, Email, Location, Blood Group
          * FinBox logo at bottom
          * Powered by Keka
      - Page 2 = Back:
          * Multi-line Address
          * Details container box (#F8F8FA): Organization Name (FinBox), Date Of Birth
          * FinBox logo
          * Powered by Keka
    """
    c = canvas.Canvas(str(output_path), pagesize=A4)

    card_x = CARD_X
    card_y = CARD_Y
    card_w = CARD_WIDTH
    card_h = CARD_HEIGHT
    center_x = CENTER_X

    # -------------------------------------------------------------------------
    # PAGE 1: FRONT SIDE
    # -------------------------------------------------------------------------
    # 1. Base card background
    c.setFillColor(colors.white)
    c.rect(card_x, card_y, card_w, card_h, fill=1, stroke=0)
    c.setStrokeColor(COLOR_CARD_BORDER)
    c.setLineWidth(1)
    c.rect(card_x, card_y, card_w, card_h, fill=0, stroke=1)

    # 2. Blue Header Background (matching reference #2986CE, height 180 pt)
    header_h = 180.0
    header_y = card_y + card_h - header_h
    c.setFillColor(COLOR_KEKA_BLUE)
    c.rect(card_x + 1, header_y, card_w - 2, header_h - 1, fill=1, stroke=0)

    # 3. Profile Photo Circular Frame
    photo_diam = 97.5
    outer_ring_radius = 51.75
    photo_center_y = card_y + card_h - 70.25

    # Outer white ring
    c.setFillColor(colors.white)
    c.circle(center_x, photo_center_y, outer_ring_radius, fill=1, stroke=0)

    # Circular Photo
    if photo_bytes_io:
        c.drawImage(
            ImageReader(photo_bytes_io),
            center_x - photo_diam / 2,
            photo_center_y - photo_diam / 2,
            photo_diam,
            photo_diam,
            mask="auto"
        )

    # 4 & 5. Employee Name & Designation with automatic scaling & 2-line balanced wrapping
    name_str = emp_data.get("name", "").strip() or "Employee Name"
    desig_str = emp_data.get("designation", "").strip() or "Employee"
    max_text_w = card_w - 28.0

    name_size = fit_text_single_line(
        name_str,
        "Helvetica-Bold",
        base_size=15.0,
        min_size=8.5,
        max_width=max_text_w
    )
    if name_size is None:
        name_size = 8.5

    desig_lines, desig_size = fit_text_multiline(
        desig_str,
        "Helvetica",
        base_size=9.0,
        min_size=6.0,
        max_width=max_text_w,
        max_lines=2,
        single_line_min_size=8.0
    )
    if not desig_lines:
        desig_lines = [desig_str]
        desig_size = 6.0

    c.setFillColor(colors.white)
    if len(desig_lines) <= 1:
        name_y = card_y + card_h - 144.22
        desig_y = card_y + card_h - 164.48
        c.setFont("Helvetica-Bold", name_size)
        c.drawCentredString(center_x, name_y, name_str)
        c.setFont("Helvetica", desig_size)
        c.drawCentredString(center_x, desig_y, desig_lines[0])
    else:
        name_y = card_y + card_h - 138.0
        desig_y1 = card_y + card_h - 153.5
        desig_y2 = card_y + card_h - 165.5
        c.setFont("Helvetica-Bold", name_size)
        c.drawCentredString(center_x, name_y, name_str)
        c.setFont("Helvetica", desig_size)
        c.drawCentredString(center_x, desig_y1, desig_lines[0])
        c.drawCentredString(center_x, desig_y2, desig_lines[1])

    # 6. Employee Details Section (on white lower body of card)
    details = [
        ("Employee Number", emp_data.get("emp_no") or "N/A"),
        ("Phone", emp_data.get("phone") or "N/A"),
        ("Email", emp_data.get("email") or "N/A"),
        ("Location", emp_data.get("location") or "N/A"),
        ("Blood Group", emp_data.get("blood_group") or "N/A")
    ]

    row_y = card_y + card_h - 199.17
    row_step = 15.0
    label_x = card_x + 38.0
    value_x = card_x + 152.0
    value_max_w = card_w - 156.0

    for label, val in details:
        # Label (Medium/light grey, 8.25 pt - lighter than values)
        c.setFillColor(COLOR_TEXT_LABEL)
        c.setFont("Helvetica", 8.25)
        c.drawString(label_x, row_y, label)

        # Value (Darker charcoal/black, 8.25 pt with auto-scaling for long email/location)
        c.setFillColor(COLOR_TEXT_DARK)
        draw_scaled_left_text(
            c,
            str(val),
            value_x,
            row_y,
            value_max_w,
            base_font_size=8.25,
            font_name="Helvetica",
            min_font_size=6.0
        )
        row_y -= row_step

    # 7. Bottom Logo
    logo_y = card_y + 26.25
    logo_w, logo_h = 38.92, 41.25
    logo_drawn = False
    for logo_candidate in ["finbox_logo.png", "assets/finbox_logo.png", "logo.png"]:
        logo_img = AssetCache.get_image(logo_candidate)
        if logo_img:
            try:
                c.drawImage(
                    logo_img,
                    center_x - logo_w / 2,
                    logo_y,
                    logo_w,
                    logo_h,
                    mask="auto",
                    preserveAspectRatio=True
                )
                logo_drawn = True
                break
            except Exception:
                pass

    if not logo_drawn:
        c.setFillColor(COLOR_KEKA_BLUE)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(center_x, logo_y + 12, "FinBox")

    # 8. Bottom Footer Text
    c.setFillColor(COLOR_TEXT_GRAY)
    c.setFont("Helvetica", 8.25)
    c.drawCentredString(center_x, card_y + 13.5, "Powered by Keka")

    c.showPage()

    # -------------------------------------------------------------------------
    # PAGE 2: BACK SIDE
    # -------------------------------------------------------------------------
    # 1. Base card background
    c.setFillColor(colors.white)
    c.rect(card_x, card_y, card_w, card_h, fill=1, stroke=0)
    c.setStrokeColor(COLOR_CARD_BORDER)
    c.setLineWidth(1)
    c.rect(card_x, card_y, card_w, card_h, fill=0, stroke=1)

    # 2. Multi-line Address (Centered, 10 pt base down to 6.5 pt, max 3 lines)
    addr_str = emp_data.get("address", "").strip() or "N/A"
    c.setFillColor(COLOR_TEXT_DARK)
    draw_wrapped_centred_text(
        c,
        addr_str,
        center_x,
        card_y + card_h - 85.0,
        max_width=220.0,
        line_height=14.0,
        base_font_size=10.0,
        font_name="Helvetica",
        min_font_size=6.5
    )

    # 3. Details Container Box (Subtle very light grey background, light border, rounded corners)
    box_x = card_x + 16.5
    box_w = 238.5
    box_y = card_y + 214.68
    box_h = 55.5
    c.setFillColor(COLOR_CONTAINER_BG)
    c.setStrokeColor(COLOR_CONTAINER_BORDER)
    c.setLineWidth(0.4)
    c.roundRect(box_x, box_y, box_w, box_h, 3.5, fill=1, stroke=1)

    # Row 1: Organization Name -> FinBox
    c.setFillColor(COLOR_TEXT_LABEL)
    c.setFont("Helvetica", 8.25)
    c.drawString(card_x + 28.5, card_y + 247.26, "Organization Name")

    c.setFillColor(COLOR_TEXT_DARK)
    c.setFont("Helvetica", 8.25)
    c.drawString(card_x + 151.8, card_y + 247.26, "FinBox")

    # Row 2: Date Of Birth
    dob_str = emp_data.get("dob") or "N/A"
    c.setFillColor(COLOR_TEXT_LABEL)
    c.setFont("Helvetica", 8.25)
    c.drawString(card_x + 28.5, card_y + 230.76, "Date Of Birth")

    c.setFillColor(COLOR_TEXT_DARK)
    c.setFont("Helvetica", 8.25)
    c.drawString(card_x + 151.8, card_y + 230.76, str(dob_str))

    # 4. Logo on Back
    back_logo_y = card_y + 150.18
    back_logo_img = AssetCache.get_image("finbox_logo.png")
    if logo_drawn and back_logo_img:
        c.drawImage(
            back_logo_img,
            center_x - logo_w / 2,
            back_logo_y,
            logo_w,
            logo_h,
            mask="auto",
            preserveAspectRatio=True
        )

    # 5. Bottom Footer Text on Back
    c.setFillColor(COLOR_TEXT_GRAY)
    c.setFont("Helvetica", 8.25)
    c.drawCentredString(center_x, card_y + 13.5, "Powered by Keka")

    c.showPage()
    c.save()


# Backward-compatible alias
generate_id_card_pdf = generate_classic_id_card_pdf


def ensure_modern_templates(force_recreate=False):
    """
    Ensure modern template assets exist in assets/ directory.
    If missing or force_recreate is True, automatically generates them from ID card 2.pdf.
    Removes background chevron (/X10) so upper photo background remains clean deep blue with wave lines.
    """
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    front_path = ASSETS_DIR / "modern_front_template_v2.png"
    back_path = ASSETS_DIR / "modern_back_template_v2.png"

    if not force_recreate and front_path.exists() and back_path.exists():
        return True

    ref_pdf = Path("ID card 2.pdf")
    if not ref_pdf.exists():
        return False

    try:
        import pypdf
        import pypdfium2 as pdfium

        reader = pypdf.PdfReader(str(ref_pdf))
        # 1. Front template (remove background chevron /X10, sample photo /X13 and sample text /X16, /X18, /X20)
        writer1 = pypdf.PdfWriter()
        writer1.add_page(reader.pages[0])
        x21 = writer1.pages[0]['/Resources']['/XObject']['/X21']
        data1 = x21.get_data().decode('latin-1')
        for x in ['/X10', '/X13', '/X16', '/X18', '/X20']:
            data1 = data1.replace(f'{x} Do', '% removed')
        x21.set_data(data1.encode('latin-1'))

        buf1 = io.BytesIO()
        writer1.write(buf1)
        buf1.seek(0)
        doc1 = pdfium.PdfDocument(buf1.getvalue())
        doc1[0].render(scale=4).to_pil().save(front_path)

        # 2. Back template (remove sample QR /X48, sample text /X26, /X35, /X44, /X47)
        if not back_path.exists() or force_recreate:
            writer2 = pypdf.PdfWriter()
            writer2.add_page(reader.pages[1])
            x51 = writer2.pages[0]['/Resources']['/XObject']['/X51']
            data2 = x51.get_data().decode('latin-1')
            for x in ['/X48', '/X26', '/X35', '/X44', '/X47']:
                data2 = data2.replace(f'{x} Do', '% removed')
            x51.set_data(data2.encode('latin-1'))

            buf2 = io.BytesIO()
            writer2.write(buf2)
            buf2.seek(0)
            doc2 = pdfium.PdfDocument(buf2.getvalue())
            doc2[0].render(scale=4).to_pil().save(back_path)
        return True
    except Exception as e:
        print(f"[!] Warning generating modern templates from ID card 2.pdf: {e}")
        return False


# ==============================================================================
# DESIGN 2: MODERN ID CARD GENERATION (ID card 2.pdf)
# ==============================================================================
def generate_modern_id_card_pdf(emp_data, portrait_bytes_io, output_path):
    """
    Render the 2-page Modern FinBox ID card design matching ID card 2.pdf:
      - Page 1 = Front:
          * Deep blue background with abstract geometric FinBox shapes & curved wave lines
          * Large employee portrait cutout in designated photo area (no border, no frame)
          * Terminating cleanly at the lower info boundary line (immediately above name)
          * Employee Name (Large, Bold White)
          * Designation (Uppercase, light slate blue-grey)
          * Employee Number (Light grey/white)
          * White FinBox logo at bottom center
          * Strictly NO phone, email, blood group, location, or DOB on front
      - Page 2 = Back:
          * Clean white card with upper-right blue geometric accent
          * FinBox logo near top
          * Dynamic QR code centered below logo (Employee Number ONLY)
          * EMERGENCY CONTACT heading with blue accent bar
          * 3 Rounded Information Cards with circular badges:
              - Row 1: Person icon | NAME | Emergency Contact Name
              - Row 2: Phone icon  | PHONE NUMBER | Emergency Contact Phone (never personal phone)
              - Row 3: Blood icon  | BLOOD GROUP | Blood Group
          * Thin horizontal divider line
          * Blue map pin icon & cleanly wrapped 2-line address below
    """
    ensure_modern_templates()

    c = canvas.Canvas(str(output_path), pagesize=A4)

    card_x = MODERN_CARD_X
    card_y = MODERN_CARD_Y
    card_w = MODERN_CARD_WIDTH
    card_h = MODERN_CARD_HEIGHT
    center_x = MODERN_CENTER_X

    # -------------------------------------------------------------------------
    # PAGE 1: FRONT SIDE
    # -------------------------------------------------------------------------
    # Clip drawing inside the rounded card boundary (radius 10 pt)
    c.saveState()
    clip_p = c.beginPath()
    clip_p.roundRect(card_x, card_y, card_w, card_h, 10.0)
    c.clipPath(clip_p, stroke=0, fill=0)

    # 1. Base Front Template: Deep blue background with wave lines, geometric chevrons,
    # dark navy lower card container, and white FinBox logo
    front_template_path = ASSETS_DIR / "modern_front_template_v2.png"
    front_img = AssetCache.get_image(front_template_path)
    if front_img:
        c.drawImage(front_img, card_x, card_y, card_w, card_h, mask="auto")
    else:
        # Fallback procedural vector background
        c.setFillColor(colors.HexColor("#09184B"))
        c.rect(card_x, card_y, card_w, card_h, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#060644"))
        c.rect(card_x, card_y, card_w, 137.0, fill=1, stroke=0)

    # 2. Employee Portrait: Fixed circular placeholder centrally positioned in upper blue section
    photo_diam = 195.0
    upper_center_y = card_y + 137.0 + (card_h - 137.0) / 2.0
    px = center_x - photo_diam / 2.0
    py = upper_center_y - photo_diam / 2.0

    if portrait_bytes_io:
        portrait_bytes_io.seek(0)
        c.saveState()
        clip_photo = c.beginPath()
        clip_photo.circle(center_x, upper_center_y, photo_diam / 2.0)
        c.clipPath(clip_photo, stroke=0, fill=0)
        c.drawImage(ImageReader(portrait_bytes_io), px, py, photo_diam, photo_diam, mask="auto")
        c.restoreState()
    else:
        # Fallback icon inside circle if no Slack photo
        icon_person_path = ASSETS_DIR / "icon_person.png"
        icon_img = AssetCache.get_image(icon_person_path)
        if icon_img:
            c.saveState()
            clip_photo = c.beginPath()
            clip_photo.circle(center_x, upper_center_y, photo_diam / 2.0)
            c.clipPath(clip_photo, stroke=0, fill=0)
            c.drawImage(icon_img, center_x - 35.0, upper_center_y - 35.0, 70.0, 70.0, mask="auto")
            c.restoreState()

    # 3. Dynamic Lower Text Section (Pure white / light slate, strictly matching ID card 2.pdf)
    name_str = (emp_data.get("name") or "Employee Name").strip().upper()
    desig_str = (emp_data.get("designation") or "").strip().upper()
    emp_no_str = (emp_data.get("emp_no") or "N/A").strip()
    name_max_w = card_w - 36.0

    name_size = fit_text_single_line(name_str, "Helvetica-Bold", base_size=18.0, min_size=8.5, max_width=name_max_w)
    if name_size is None:
        name_size = 8.5

    desig_lines, desig_size = fit_text_multiline(
        desig_str,
        "Helvetica",
        base_size=7.5,
        min_size=6.0,
        max_width=name_max_w,
        max_lines=2,
        single_line_min_size=7.0
    )
    if not desig_lines:
        desig_lines = [desig_str]
        desig_size = 6.0

    emp_no_size = fit_text_single_line(emp_no_str, "Helvetica", base_size=8.5, min_size=6.0, max_width=name_max_w)
    if emp_no_size is None:
        emp_no_size = 6.0

    text_start_x = card_x + 18.0

    if len(desig_lines) <= 1:
        # Standard 1-line layout (preserves exact approved coordinates)
        name_y = card_y + 98.0
        desig_y = card_y + 82.0
        emp_no_y = card_y + 64.0

        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", name_size)
        c.drawString(text_start_x, name_y, name_str)

        c.setFillColor(colors.HexColor("#8E9BB5"))
        c.setFont("Helvetica", desig_size)
        c.drawString(text_start_x, desig_y, desig_lines[0])

        c.setFillColor(colors.HexColor("#CBD5E1"))
        c.setFont("Helvetica", emp_no_size)
        c.drawString(text_start_x, emp_no_y, emp_no_str)
    else:
        # Balanced 2-line layout (preserves clean spacing to photo boundary above & logo below)
        name_y = card_y + 103.0
        desig_y1 = card_y + 88.0
        desig_y2 = card_y + 77.0
        emp_no_y = card_y + 61.0

        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", name_size)
        c.drawString(text_start_x, name_y, name_str)

        c.setFillColor(colors.HexColor("#8E9BB5"))
        c.setFont("Helvetica", desig_size)
        c.drawString(text_start_x, desig_y1, desig_lines[0])
        c.drawString(text_start_x, desig_y2, desig_lines[1])

        c.setFillColor(colors.HexColor("#CBD5E1"))
        c.setFont("Helvetica", emp_no_size)
        c.drawString(text_start_x, emp_no_y, emp_no_str)

    c.restoreState()

    # Outer card border (crisp rounded border)
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.setLineWidth(0.5)
    c.roundRect(card_x, card_y, card_w, card_h, 10.0, fill=0, stroke=1)

    c.showPage()

    # -------------------------------------------------------------------------
    # PAGE 2: BACK SIDE
    # -------------------------------------------------------------------------
    c.saveState()
    clip_p2 = c.beginPath()
    clip_p2.roundRect(card_x, card_y, card_w, card_h, 10.0)
    c.clipPath(clip_p2, stroke=0, fill=0)

    # 1. Base Back Template: Clean white card, top-right blue accent, FinBox logo,
    # "EMERGENCY CONTACT" heading + blue accent bar, 3 rounded info cards with icons
    # and labels, horizontal divider line, and blue map pin icon
    back_template_path = ASSETS_DIR / "modern_back_template_v2.png"
    back_img = AssetCache.get_image(back_template_path)
    if back_img:
        c.drawImage(back_img, card_x, card_y, card_w, card_h, mask="auto")
    else:
        c.setFillColor(colors.white)
        c.rect(card_x, card_y, card_w, card_h, fill=1, stroke=0)

    # 2. Dynamic QR Code (Encodes Employee Number ONLY)
    emp_no_qr = str(emp_data.get("emp_no") or "N/A").strip()
    qr_size = 67.0
    qr_x = center_x - qr_size / 2
    qr_y = card_y + 292.0

    qr_widget = qr.QrCodeWidget(emp_no_qr)
    bounds = qr_widget.getBounds()
    qw = bounds[2] - bounds[0]
    qh = bounds[3] - bounds[1]
    d = Drawing(qr_size, qr_size, transform=[qr_size / qw, 0, 0, qr_size / qh, 0, 0])
    d.add(qr_widget)
    d.drawOn(c, qr_x, qr_y)

    # 3. Three Emergency Contact Values (Bold Dark Navy #081232, auto-scaled)
    c.setFillColor(colors.HexColor("#081232"))
    text_x = card_x + 80.0
    val_max_w = card_w - 95.0

    # Row 1: Emergency Contact Name (Proper name casing, base 10.5 pt down to 6.0 pt)
    raw_em_name = str(emp_data.get("emergency_contact_name") or "N/A")
    em_name = format_name_casing(raw_em_name)
    em_name_size = fit_text_single_line(em_name, "Helvetica-Bold", base_size=10.5, min_size=6.0, max_width=val_max_w)
    if em_name_size is None:
        em_name_size = 6.0
    c.setFont("Helvetica-Bold", em_name_size)
    c.drawString(text_x, card_y + 218.0, em_name)

    # Row 2: Emergency Contact Phone (NEVER personal phone, base 10.5 pt down to 7.0 pt)
    em_phone = (emp_data.get("emergency_contact_phone") or "N/A").strip()
    em_phone_size = fit_text_single_line(em_phone, "Helvetica-Bold", base_size=10.5, min_size=7.0, max_width=val_max_w)
    if em_phone_size is None:
        em_phone_size = 7.0
    c.setFont("Helvetica-Bold", em_phone_size)
    c.drawString(text_x, card_y + 172.0, em_phone)

    # Row 3: Blood Group (Retain original spacing, brackets, capitalisation, base 10.5 pt down to 7.0 pt)
    raw_bg = str(emp_data.get("blood_group") or "N/A")
    b_group = re.sub(r"\s+", " ", raw_bg).strip()
    b_group_size = fit_text_single_line(b_group, "Helvetica-Bold", base_size=10.5, min_size=7.0, max_width=val_max_w)
    if b_group_size is None:
        b_group_size = 7.0
    c.setFont("Helvetica-Bold", b_group_size)
    c.drawString(text_x, card_y + 125.0, b_group)

    # 4. Address (Centered below map pin, auto-wrapped cleanly up to 3 lines)
    addr_str = (emp_data.get("address") or "N/A").strip().upper()
    addr_max_w = card_w - 30.0
    addr_lines, addr_size = fit_address_multiline(
        addr_str,
        font_name="Helvetica-Bold",
        base_size=5.6,
        min_size=4.2,
        max_width=addr_max_w,
        max_lines=3
    )
    if not addr_lines:
        addr_lines = [addr_str]
        addr_size = 4.2

    c.setFont("Helvetica-Bold", addr_size)
    if len(addr_lines) == 1:
        c.drawCentredString(center_x, card_y + 32.0, addr_lines[0])
    elif len(addr_lines) == 2:
        c.drawCentredString(center_x, card_y + 36.0, addr_lines[0])
        c.drawCentredString(center_x, card_y + 27.5, addr_lines[1])
    else:
        c.drawCentredString(center_x, card_y + 39.5, addr_lines[0])
        c.drawCentredString(center_x, card_y + 32.0, addr_lines[1])
        c.drawCentredString(center_x, card_y + 24.5, addr_lines[2])

    c.restoreState()

    # Outer card border
    c.setStrokeColor(colors.HexColor("#E2E8F0"))
    c.setLineWidth(0.5)
    c.roundRect(card_x, card_y, card_w, card_h, 10.0, fill=0, stroke=1)

    c.showPage()
    c.save()



# ==============================================================================
# SINGLE-EMPLOYEE PREVIEW MODE (--preview-email)
# ==============================================================================
def run_preview_mode(
    preview_email,
    design="classic",
    output_dir=None,
    photos_dir=None,
    photo_match_mode="auto",
    custom_df=None,
    address_mapping=None
):
    """
    Generate a 2-page ID card preview (Page 1 = Front, Page 2 = Back)
    for a single employee matched by email.
    Supports sourcing employee data from Excel (if available) or falling back
    directly to Keka HRMS API.
    Sourcing profile photo from Local Folder (if provided) -> Keka HRMS -> Slack.
    """
    global OUTPUT_DIR
    design_lower = str(design or "classic").strip().lower()
    design_name = "Modern" if design_lower == "modern" else "Classic"

    if output_dir is not None:
        OUTPUT_DIR = Path(output_dir)
    else:
        OUTPUT_DIR = create_new_output_dir(prefix=f"ID_Cards_Preview_{design_name}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"      Single-Employee ID Card Preview ({design_name} Design)      ")
    print("=" * 60)
    print(f"Target Email:    {preview_email}")
    print(f"Design Selected: {design_name}")
    print(f"Output Folder:   {OUTPUT_DIR.resolve()}")
    if photos_dir:
        print(f"Photos Folder:   {photos_dir} (Match: {photo_match_mode})")

    design_out_dir = OUTPUT_DIR / design_name
    design_out_dir.mkdir(parents=True, exist_ok=True)

    target_clean = preview_email.strip().lower()
    emp_data = None

    # Step A: Check Custom DF or Excel file first
    df = None
    if custom_df is not None:
        df = custom_df
        print(f"[+] Searching for '{target_clean}' in custom dataset...")
    else:
        excel_file = find_excel_file()
        if excel_file:
            try:
                df = read_excel_safely(excel_file)
                print(f"[+] Loaded Excel file '{excel_file.name}' to find '{target_clean}'...")
            except Exception:
                df = None

    if df is not None:
        col_map = map_columns(df)
        email_col = col_map.get("email")
        if email_col:
            for idx, row in df.iterrows():
                cell_email = str(row.get(email_col) or "").strip().lower()
                if cell_email == target_clean:
                    val_res = validate_employee_record(row, col_map, set())
                    if not val_res["is_valid"]:
                        print("\n" + "=" * 60)
                        print("          EMPLOYEE DATA VALIDATION FAILED (PREVIEW)")
                        print("=" * 60)
                        print(f"Employee Number: {val_res['emp_data'].get('emp_no', 'N/A')}")
                        print(f"Employee Name:   {val_res['emp_data'].get('name', 'N/A')}")
                        print(f"Email:           {preview_email}")
                        print("")
                        if val_res["missing_fields"]:
                            print("Missing Required Fields:")
                            for mf in val_res["missing_fields"]:
                                print(f"  - {mf}")
                        if val_res["issues"]:
                            print("Validation Issues:")
                            for iss in val_res["issues"]:
                                print(f"  - {iss}")
                        print("\nStatus: SKIPPED\n")
                        return 1
                    emp_data = val_res["emp_data"]
                    if address_mapping and emp_data.get("location"):
                        # If address mapping is active, resolve address dynamically
                        emp_data["address"] = resolve_office_address(emp_data["location"], mapping=address_mapping)
                    break

    # Step B: If not found in Excel, look up live in Keka HRMS API
    if not emp_data:
        load_dotenv()
        keka_key = os.getenv("KEKA_API_KEY", "").strip()
        keka_cid = os.getenv("KEKA_CLIENT_ID", "").strip()
        keka_csec = os.getenv("KEKA_CLIENT_SECRET", "").strip()
        keka_sub = os.getenv("KEKA_SUBDOMAIN", "finbox").strip()

        if keka_key or (keka_cid and keka_csec):
            print(f"[*] Employee '{preview_email}' not in Excel. Querying Keka HRMS API...")
            emp_data, keka_err = fetch_keka_employee_full_details(
                target_clean,
                api_key=keka_key,
                client_id=keka_cid,
                client_secret=keka_csec,
                subdomain=keka_sub,
                address_mapping=address_mapping
            )
            if keka_err or not emp_data:
                print(f"\n[X] Error: Employee '{preview_email}' not found in Excel or Keka HRMS ({keka_err or 'User not found'}).")
                print("=" * 60 + "\n")
                return 1
            print(f"[+] Found employee '{emp_data.get('name')}' in Keka HRMS API.")

            # Strict completeness validation: Don't generate if any required Keka data is missing
            val_res = validate_keka_employee_record(emp_data)
            if not val_res["is_valid"]:
                print("\n" + "=" * 60)
                print("          KEKA EMPLOYEE DATA INCOMPLETE (PREVIEW SKIPPED)")
                print("=" * 60)
                print(f"Employee Number: {emp_data.get('emp_no', 'N/A')}")
                print(f"Employee Name:   {emp_data.get('name', 'N/A')}")
                print(f"Email:           {preview_email}")
                print("")
                print("Missing Required Fields in Keka HRMS:")
                for mf in val_res["missing_fields"]:
                    print(f"  - {mf}")
                if val_res["issues"]:
                    print("\nValidation Details:")
                    for iss in val_res["issues"]:
                        print(f"  - {iss}")
                print("\nStatus: SKIPPED (ID card not generated due to incomplete Keka data)\n")
                return 1
        else:
            print(f"\n[X] Error: Employee '{preview_email}' not found in Excel, and Keka is not configured in .env.")
            print("=" * 60 + "\n")
            return 1

    # Step C: Automatic Text Fitting Validation
    fit_ok, fit_err = validate_employee_text_fitting(emp_data, design_name)
    if not fit_ok:
        print("\n" + "=" * 60)
        print("          TEXT FITTING VALIDATION FAILED (PREVIEW)")
        print("=" * 60)
        print(f"Employee Number: {emp_data.get('emp_no', 'N/A')}")
        print(f"Employee Name:   {emp_data.get('name', 'N/A')}")
        print(f"Email:           {preview_email}")
        print(f"Design Selected: {design_name}")
        print(f"Failure Reason:  {fit_err}")
        print("\nStatus: SKIPPED\n")
        return 1

    print("\n[+] Employee Validated:")
    print(f"    - Employee Number:          {emp_data['emp_no']}")
    print(f"    - Name:                     {emp_data['name']}")
    print(f"    - Designation:              {emp_data['designation']}")
    print(f"    - Email:                    {emp_data['email']}")
    print(f"    - Phone:                    {emp_data['phone']}")
    print(f"    - Location:                 {emp_data['location']}")
    print(f"    - Blood Group:              {emp_data['blood_group']}")
    print(f"    - Date Of Birth:            {emp_data['dob']}")
    print(f"    - Address:                  {emp_data['address']}")
    print(f"    - Emergency Contact Name:   {emp_data['emergency_contact_name']}")
    print(f"    - Emergency Contact Phone:  {emp_data['emergency_contact_phone']}")

    # Step D: Profile Photo Retrieval (Local Folder -> Keka HRMS -> Slack)
    load_dotenv()
    slack_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    keka_key = os.getenv("KEKA_API_KEY", "").strip()
    keka_cid = os.getenv("KEKA_CLIENT_ID", "").strip()
    keka_csec = os.getenv("KEKA_CLIENT_SECRET", "").strip()
    keka_sub = os.getenv("KEKA_SUBDOMAIN", "finbox").strip()

    slack_client = None
    if slack_token and not slack_token.startswith("xoxb-your-"):
        try:
            slack_client = WebClient(token=slack_token)
        except Exception:
            slack_client = None

    print("\n[+] Sourcing profile photo (Local Folder -> Keka HRMS -> Slack)...")
    raw_photo_bytes, photo_err, photo_status, photo_source = fetch_profile_photo_with_fallback(
        emp_data["email"],
        emp_no=emp_data.get("emp_no"),
        slack_client=slack_client,
        slack_token=slack_token,
        keka_api_key=keka_key,
        keka_client_id=keka_cid,
        keka_client_secret=keka_csec,
        keka_subdomain=keka_sub,
        photos_dir=photos_dir,
        photo_match_mode=photo_match_mode
    )

    if photo_err or not raw_photo_bytes:
        print("\n" + "=" * 60)
        print("          PROFILE PHOTO VALIDATION FAILED (PREVIEW)")
        print("=" * 60)
        print(f"Employee:        {emp_data['name']} ({emp_data['email']})")
        print(f"Photo Status:    {photo_status}")
        print(f"Failure Reason:  {photo_err}")
        print("\nStatus: SKIPPED\n")
        return 1

    print(f"[+] Profile photo retrieved successfully from {photo_source} ({photo_status}).")
    if design_name == "Modern":
        photo_io = process_photo_modern_circular(raw_photo_bytes, target_dim=800)
    else:
        photo_io = process_photo_circular(raw_photo_bytes, target_dim=300)

    # 3. GENERATE 2-PAGE PDF PREVIEW
    preview_filename = f"IDCard_Preview_{design_name}.pdf"
    preview_pdf_path = design_out_dir / preview_filename

    try:
        if design_name == "Modern":
            generate_modern_id_card_pdf(emp_data, photo_io, preview_pdf_path)
        else:
            generate_classic_id_card_pdf(emp_data, photo_io, preview_pdf_path)
            try:
                import shutil
                shutil.copy(preview_pdf_path, OUTPUT_DIR / "IDCard_Preview.pdf")
            except Exception:
                pass

        print(f"\n[+] PDF generated successfully: {preview_pdf_path}")
    except Exception as e:
        print(f"\n[X] PDF generation error: {e}")
        print("=" * 60 + "\n")
        return 1

    # 4. Verify exactly 2 pages
    try:
        import pypdf
        reader = pypdf.PdfReader(str(preview_pdf_path))
        num_pages = len(reader.pages)
        print(f"[+] Verified page count: {num_pages} pages (Page 1 = Front, Page 2 = Back)")
        if num_pages != 2:
            print(f"[!] Warning: Expected exactly 2 pages, found {num_pages}")
    except Exception as e:
        print(f"[!] Warning checking page count: {e}")

    print("\n" + "=" * 60)
    print("              Preview Generated Successfully                ")
    print("=" * 60)
    print(f"Preview PDF Path: {preview_pdf_path.resolve()}")
    print("=" * 60 + "\n")
    return 0


# ==============================================================================
# AUDIT & GENERATION REPORT (3-SHEET HR-FRIENDLY EXCEL)
# ==============================================================================
def write_generation_report(report_data, output_file, design_name):
    """
    Generate comprehensive 3-sheet Excel report:
      - Sheet 1: Employee Generation Status
      - Sheet 2: Location-wise Summary
      - Sheet 3: Exceptions Requiring HR Action
    """
    wb = openpyxl.Workbook()

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="0B1B3D", end_color="0B1B3D", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1")
    )

    success_fill = PatternFill(start_color="D1E7DD", end_color="D1E7DD", fill_type="solid")
    success_font = Font(name="Calibri", size=10, bold=True, color="0F5132")

    fail_fill = PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid")
    fail_font = Font(name="Calibri", size=10, bold=True, color="842029")

    missing_fill = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
    missing_font = Font(name="Calibri", size=10, color="664D03")

    regular_font = Font(name="Calibri", size=10, color="0F172A")
    total_font = Font(name="Calibri", size=10, bold=True, color="0F172A")
    total_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")

    # -------------------------------------------------------------
    # SHEET 1: Employee Generation Status
    # -------------------------------------------------------------
    ws1 = wb.active
    ws1.title = "Employee Generation Status"
    ws1.views.sheetView[0].showGridLines = True

    sheet1_headers = [
        "Employee Number",
        "Employee Name",
        "Email",
        "Location",
        "Selected Design",
        "Data Validation",
        "Slack Photo Status",
        "Generation Status",
        "Missing Fields",
        "Issue / Reason",
        "Output PDF Path"
    ]
    ws1.append(sheet1_headers)
    ws1.row_dimensions[1].height = 26

    for col_idx in range(1, len(sheet1_headers) + 1):
        cell = ws1.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    for row_idx, rec in enumerate(report_data, start=2):
        ws1.row_dimensions[row_idx].height = 22

        row_vals = [
            rec.get("emp_no", ""),
            rec.get("emp_name", ""),
            rec.get("email", ""),
            rec.get("location", ""),
            rec.get("design", design_name),
            rec.get("data_validation", ""),
            rec.get("slack_photo_status", ""),
            rec.get("generation_status", ""),
            rec.get("missing_fields", ""),
            rec.get("issues", ""),
            rec.get("output_pdf_path", "")
        ]

        gen_status = rec.get("generation_status", "")
        photo_status = rec.get("slack_photo_status", "")
        missing_val = rec.get("missing_fields", "")

        for col_idx, val in enumerate(row_vals, start=1):
            cell = ws1.cell(row=row_idx, column=col_idx, value=val)
            cell.border = thin_border
            cell.font = regular_font

            if sheet1_headers[col_idx - 1] in ["Employee Number", "Location", "Selected Design", "Data Validation", "Slack Photo Status", "Generation Status"]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif sheet1_headers[col_idx - 1] in ["Missing Fields", "Issue / Reason"]:
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

            if sheet1_headers[col_idx - 1] == "Generation Status":
                if gen_status == "GENERATED":
                    cell.fill = success_fill
                    cell.font = success_font
                else:
                    cell.fill = fail_fill
                    cell.font = fail_font

            elif sheet1_headers[col_idx - 1] == "Missing Fields" and missing_val:
                cell.fill = missing_fill
                cell.font = missing_font

            elif sheet1_headers[col_idx - 1] == "Slack Photo Status" and photo_status != "Valid Custom Photo":
                cell.fill = fail_fill
                cell.font = fail_font

    ws1.freeze_panes = "A2"
    if len(report_data) > 0:
        ws1.auto_filter.ref = ws1.dimensions

    for col in ws1.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            for line in val_str.split("\n"):
                if len(line) > max_len:
                    max_len = len(line)
        ws1.column_dimensions[col_letter].width = max(min(max_len + 4, 45), 14)

    # -------------------------------------------------------------
    # SHEET 2: Location-wise Summary
    # -------------------------------------------------------------
    ws2 = wb.create_sheet(title="Location-wise Summary")
    ws2.views.sheetView[0].showGridLines = True

    sheet2_headers = [
        "Location",
        "Total Employees",
        "Successfully Generated",
        "Skipped",
        "Success Percentage"
    ]
    ws2.append(sheet2_headers)
    ws2.row_dimensions[1].height = 26

    for col_idx in range(1, len(sheet2_headers) + 1):
        cell = ws2.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    loc_agg = {}
    for rec in report_data:
        loc = rec.get("location") or "[Missing Location]"
        if loc not in loc_agg:
            loc_agg[loc] = {"total": 0, "generated": 0, "skipped": 0}
        loc_agg[loc]["total"] += 1
        if rec.get("generation_status") == "GENERATED":
            loc_agg[loc]["generated"] += 1
        else:
            loc_agg[loc]["skipped"] += 1

    total_all = 0
    gen_all = 0
    skip_all = 0

    cur_row = 2
    for loc, counts in sorted(loc_agg.items()):
        tot = counts["total"]
        gen = counts["generated"]
        skp = counts["skipped"]
        pct = (gen / tot * 100) if tot > 0 else 0.0

        total_all += tot
        gen_all += gen
        skip_all += skp

        row_vals = [loc, tot, gen, skp, f"{pct:.2f}%"]
        ws2.row_dimensions[cur_row].height = 22

        for col_idx, val in enumerate(row_vals, start=1):
            cell = ws2.cell(row=cur_row, column=col_idx, value=val)
            cell.border = thin_border
            cell.font = regular_font
            if col_idx == 1:
                cell.alignment = Alignment(horizontal="left", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="center", vertical="center")
        cur_row += 1

    overall_pct = (gen_all / total_all * 100) if total_all > 0 else 0.0
    tot_row_vals = ["Total", total_all, gen_all, skip_all, f"{overall_pct:.2f}%"]
    ws2.row_dimensions[cur_row].height = 24

    for col_idx, val in enumerate(tot_row_vals, start=1):
        cell = ws2.cell(row=cur_row, column=col_idx, value=val)
        cell.border = thin_border
        cell.font = total_font
        cell.fill = total_fill
        if col_idx == 1:
            cell.alignment = Alignment(horizontal="left", vertical="center")
        else:
            cell.alignment = Alignment(horizontal="center", vertical="center")

    ws2.freeze_panes = "A2"
    for col in ws2.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws2.column_dimensions[col_letter].width = max(max_len + 5, 16)

    # -------------------------------------------------------------
    # SHEET 3: Exceptions Requiring HR Action
    # -------------------------------------------------------------
    ws3 = wb.create_sheet(title="Exceptions Requiring HR Action")
    ws3.views.sheetView[0].showGridLines = True

    sheet3_headers = [
        "Employee Number",
        "Employee Name",
        "Email",
        "Location",
        "Missing Fields",
        "Photo Status",
        "Reason for Skipping",
        "Required HR Action"
    ]
    ws3.append(sheet3_headers)
    ws3.row_dimensions[1].height = 26

    for col_idx in range(1, len(sheet3_headers) + 1):
        cell = ws3.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    skipped_recs = [r for r in report_data if r.get("generation_status") == "SKIPPED"]
    for row_idx, rec in enumerate(skipped_recs, start=2):
        ws3.row_dimensions[row_idx].height = 24

        row_vals = [
            rec.get("emp_no", ""),
            rec.get("emp_name", ""),
            rec.get("email", ""),
            rec.get("location", ""),
            rec.get("missing_fields", ""),
            rec.get("slack_photo_status", ""),
            rec.get("issues", ""),
            rec.get("hr_action", "")
        ]

        missing_val = rec.get("missing_fields", "")
        photo_status = rec.get("slack_photo_status", "")

        for col_idx, val in enumerate(row_vals, start=1):
            cell = ws3.cell(row=row_idx, column=col_idx, value=val)
            cell.border = thin_border
            cell.font = regular_font

            if sheet3_headers[col_idx - 1] in ["Employee Number", "Location", "Photo Status"]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif sheet3_headers[col_idx - 1] in ["Missing Fields", "Reason for Skipping", "Required HR Action"]:
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

            if sheet3_headers[col_idx - 1] == "Missing Fields" and missing_val:
                cell.fill = missing_fill
                cell.font = missing_font
            elif sheet3_headers[col_idx - 1] == "Photo Status" and photo_status != "Valid Custom Photo":
                cell.fill = fail_fill
                cell.font = fail_font

    ws3.freeze_panes = "A2"
    if len(skipped_recs) > 0:
        ws3.auto_filter.ref = ws3.dimensions

    for col in ws3.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            for line in val_str.split("\n"):
                if len(line) > max_len:
                    max_len = len(line)
        ws3.column_dimensions[col_letter].width = max(min(max_len + 4, 45), 14)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_file)


# Backward-compatibility alias
write_audit_report = write_generation_report


# ==============================================================================
# PROGRESS INDICATOR
# ==============================================================================
def print_bulk_progress(design_name, total_employees, current_idx, generated_count, skipped_count, current_emp_id, start_time):
    """
    Dynamic terminal progress indicator matching Section 6 specification.
    """
    remaining = max(0, total_employees - current_idx)
    elapsed = time.time() - start_time
    avg_per_emp = (elapsed / current_idx) if current_idx > 0 else 0.0
    eta = avg_per_emp * remaining

    elapsed_str = format_duration(elapsed)
    avg_str = f"{avg_per_emp:.2f}s" if avg_per_emp > 0 else "0.00s"
    eta_str = format_duration(eta)

    print("\n" + "-" * 50)
    print("FINBOX ID CARD GENERATOR\n")
    print(f"Selected Design: {design_name}\n")
    print(f"Total Employees: {total_employees}\n")
    print(f"Processing: {current_idx} / {total_employees}\n")
    print(f"Generated: {generated_count}")
    print(f"Skipped: {skipped_count}")
    print(f"Remaining: {remaining}\n")
    print(f"Current Employee: {current_emp_id}\n")
    print(f"Elapsed Time: {elapsed_str}")
    print(f"Average Time Per Employee: {avg_str}")
    print(f"Estimated Time Remaining: {eta_str}")
    print("-" * 50)


# ==============================================================================
# BULK GENERATION MODE
# ==============================================================================
def run_bulk_generation(
    design="classic",
    custom_df=None,
    output_dir=None,
    photos_dir=None,
    photo_match_mode="auto",
    address_mapping=None
):
    global OUTPUT_DIR
    design_lower = str(design or "classic").strip().lower()
    design_name = "Modern" if design_lower == "modern" else "Classic"

    if output_dir is not None:
        OUTPUT_DIR = Path(output_dir)
    else:
        OUTPUT_DIR = create_new_output_dir(prefix=f"ID_Cards_{design_name}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    base_design_dir = OUTPUT_DIR / design_name
    base_design_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = OUTPUT_DIR / "Reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"{design_name}_Generation_Report.xlsx"

    print("=" * 60)
    print(f"      FinBox Employee ID Card Bulk Generator ({design_name})      ")
    print("=" * 60)
    print(f"[+] Output Directory: {OUTPUT_DIR.resolve()}")
    if photos_dir:
        print(f"[+] Local Photos Folder: {photos_dir} (Match: {photo_match_mode})")

    load_dotenv()
    slack_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    keka_api_key = os.getenv("KEKA_API_KEY", "").strip()
    keka_client_id = os.getenv("KEKA_CLIENT_ID", "").strip()
    keka_client_secret = os.getenv("KEKA_CLIENT_SECRET", "").strip()
    keka_subdomain = os.getenv("KEKA_SUBDOMAIN", "finbox").strip()

    if keka_api_key or (keka_client_id and keka_client_secret):
        print(f"[+] Keka HRMS connector enabled ({keka_subdomain}.keka.com - Primary Photo Source).")
    else:
        print("[!] Notice: KEKA credentials not configured in .env (will use Slack if available).")

    slack_client = None
    if slack_token and not slack_token.startswith("xoxb-your-"):
        try:
            slack_client = WebClient(token=slack_token)
            print("[+] Slack client initialized successfully (Secondary/Fallback Photo Source).")
        except Exception as e:
            print(f"[!] Error initializing Slack client: {e}")
    else:
        print("[!] Notice: SLACK_BOT_TOKEN is not configured in .env.")

    if custom_df is not None:
        df = custom_df
        print(f"[+] Loaded {len(df)} row(s) from custom dataset.")
    else:
        excel_file = find_excel_file()
        if not excel_file:
            print("\n[X] Error: No Excel file found in current folder.")
            print("    Please place 'ID card generation.xlsx' in this directory.")
            return 1
        print(f"[+] Found Excel file: {excel_file.name}")
        try:
            df = read_excel_safely(excel_file)
            print(f"[+] Loaded {len(df)} row(s) from Excel.")
        except Exception as e:
            print(f"[X] Error reading Excel file: {e}")
            return 1

    col_map = map_columns(df)
    print("[+] Detected Column Mappings:")
    display_names = {
        "emp_no": "Employee Number",
        "name": "Name",
        "designation": "Designation",
        "email": "Email",
        "phone": "Phone",
        "location": "Location",
        "blood_group": "Blood Group",
        "dob": "Date Of Birth",
        "address": "Address",
        "emergency_contact_name": "Emergency Contact Name",
        "emergency_contact_phone": "Emergency Contact Phone",
    }
    for std_field, original_col in col_map.items():
        label = display_names.get(std_field, std_field)
        print(f"    - {label.ljust(25)} <- '{original_col}'")

    total_records = len(df)
    generated_count = 0
    skipped_count = 0
    missing_data_count = 0
    missing_photos_count = 0
    missing_slack_users_count = 0
    other_errors_count = 0

    seen_emp_nums = set()
    report_records = []
    location_stats = {}

    if total_records == 0:
        print("\n[i] The Excel file contains 0 employee rows. Ready for data input.")
        return 0

    # =========================================================================
    # PHASE 1: PRE-VALIDATION (Strict 11-column completeness & text fitting)
    # =========================================================================
    print(f"\n[+] Pre-validating {total_records} employee record(s) before photo retrieval...")
    valid_candidates = []  # list of (idx, emp_data, loc_display)
    pre_skipped_dict = {}  # idx -> skip_info dict

    for idx, row in df.iterrows():
        val_res = validate_employee_record(row, col_map, seen_emp_nums)
        emp_data = val_res["emp_data"]
        missing_fields = val_res["missing_fields"]
        issues = val_res["issues"]
        hr_actions = val_res["hr_actions"]

        # If custom address mapping is active, resolve address based on location
        if address_mapping and emp_data.get("location"):
            emp_data["address"] = resolve_office_address(emp_data["location"], mapping=address_mapping)

        loc_display = emp_data["location"] if emp_data["location"] and emp_data["location"] != "N/A" else "[Missing Location]"
        if loc_display not in location_stats:
            location_stats[loc_display] = {"total": 0, "generated": 0, "skipped": 0}
        location_stats[loc_display]["total"] += 1

        if not val_res["is_valid"]:
            pre_skipped_dict[idx] = {
                "emp_data": emp_data,
                "loc_display": loc_display,
                "missing_fields": missing_fields,
                "issues": issues,
                "hr_actions": hr_actions,
                "reason_type": "missing_data" if missing_fields else "other_error",
                "photo_status": "Not Checked (Data Incomplete)",
                "issues_str": "; ".join(issues),
                "hr_action_str": "; ".join(hr_actions),
            }
            continue

        # Automatic Text Fitting Validation
        fit_ok, fit_err = validate_employee_text_fitting(emp_data, design_name)
        if not fit_ok:
            pre_skipped_dict[idx] = {
                "emp_data": emp_data,
                "loc_display": loc_display,
                "missing_fields": [],
                "issues": [fit_err],
                "hr_actions": ["Shorten text or update employee details to fit ID card layout"],
                "reason_type": "other_error",
                "photo_status": "Not Checked (Text Fitting Failed)",
                "issues_str": fit_err,
                "hr_action_str": "Shorten text or update employee details to fit ID card layout",
            }
            continue

        valid_candidates.append((idx, emp_data, loc_display))

    print(f"[+] Pre-validation complete: {len(valid_candidates)} passed, {len(pre_skipped_dict)} skipped.\n")

    # =========================================================================
    # PHASE 2: INITIALIZE BATCH CACHE (Modern & Classic)
    # =========================================================================
    batch_cache = BatchImageCache()

    if design_name == "Modern" and len(valid_candidates) > 0:
        ensure_modern_templates()

    # =========================================================================
    # PHASE 3: CONTROLLED CONCURRENT PHOTO PREFETCH (Local -> Keka -> Slack)
    # =========================================================================
    if (photos_dir or keka_api_key or (keka_client_id and keka_client_secret) or slack_client) and len(valid_candidates) > 0:
        prefetch_photos_concurrent(
            [c[1] for c in valid_candidates],
            slack_client=slack_client,
            slack_token=slack_token,
            cache=batch_cache,
            keka_api_key=keka_api_key,
            keka_client_id=keka_client_id,
            keka_client_secret=keka_client_secret,
            keka_subdomain=keka_subdomain,
            photos_dir=photos_dir,
            photo_match_mode=photo_match_mode,
            max_workers=4
        )

    # =========================================================================
    # PHASE 4: CARD GENERATION LOOP WITH DYNAMIC TERMINAL PROGRESS
    # =========================================================================
    start_time = time.time()
    valid_map = {idx: (emp_data, loc_disp) for idx, emp_data, loc_disp in valid_candidates}

    try:
        for idx in range(total_records):
            current_num = idx + 1

            # Case A: Record was skipped during pre-validation
            if idx in pre_skipped_dict:
                skip_info = pre_skipped_dict[idx]
                emp_data = skip_info["emp_data"]
                loc_display = skip_info["loc_display"]
                skipped_count += 1
                location_stats[loc_display]["skipped"] += 1
                if skip_info["reason_type"] == "missing_data":
                    missing_data_count += 1
                else:
                    other_errors_count += 1

                report_records.append({
                    "emp_no": emp_data["emp_no"] if emp_data["emp_no"] != "N/A" else "",
                    "emp_name": emp_data["name"] if emp_data["name"] != "N/A" else "",
                    "email": emp_data["email"] if emp_data["email"] != "N/A" else "",
                    "location": loc_display,
                    "design": design_name,
                    "data_validation": "FAILED",
                    "slack_photo_status": skip_info["photo_status"],
                    "generation_status": "SKIPPED",
                    "missing_fields": ", ".join(skip_info["missing_fields"]),
                    "issues": skip_info["issues_str"],
                    "hr_action": skip_info["hr_action_str"],
                    "output_pdf_path": "",
                })

                curr_emp_label = f"{emp_data.get('emp_no') or 'Unknown'} ({emp_data.get('name') or 'N/A'})"
                print_bulk_progress(design_name, total_records, current_num, generated_count, skipped_count, curr_emp_label, start_time)
                print(f"[-] [{current_num}/{total_records}] Skipped: {emp_data['name'] or emp_data['emp_no'] or 'Unknown'} ({skip_info['issues_str']})")
                continue

            # Case B: Valid employee record
            emp_data, loc_display = valid_map[idx]
            curr_emp_label = f"{emp_data['emp_no']} ({emp_data['name']})"
            print_bulk_progress(design_name, total_records, current_num, generated_count, skipped_count, curr_emp_label, start_time)

            # Retrieve profile photo (from batch cache first, fallback to direct fetch)
            clean_email = str(emp_data["email"]).strip().lower()
            cached_photo = batch_cache.get_raw(clean_email)
            if cached_photo:
                raw_photo_bytes, photo_err, photo_status, *rest = cached_photo
                photo_source = rest[0] if rest else "Slack"
            else:
                raw_photo_bytes, photo_err, photo_status, photo_source = fetch_profile_photo_with_fallback(
                    emp_data["email"],
                    emp_no=emp_data.get("emp_no"),
                    slack_client=slack_client,
                    slack_token=slack_token,
                    keka_api_key=keka_api_key,
                    keka_client_id=keka_client_id,
                    keka_client_secret=keka_client_secret,
                    keka_subdomain=keka_subdomain,
                    photos_dir=photos_dir,
                    photo_match_mode=photo_match_mode
                )
                batch_cache.put_raw(clean_email, raw_photo_bytes, photo_err, photo_status, photo_source)

            if photo_err or not raw_photo_bytes:
                skipped_count += 1
                location_stats[loc_display]["skipped"] += 1
                if "Not Found" in photo_status:
                    missing_slack_users_count += 1
                    hr_act = "Verify official email and confirm profile exists in Keka HRMS or Slack"
                elif "Default Avatar" in photo_status:
                    missing_photos_count += 1
                    hr_act = "Ask employee to upload custom profile photo in Keka HRMS or Slack"
                elif photo_status in ["Photo Unavailable", "Download Failed", "Corrupted Image", "No Keka Photo"]:
                    missing_photos_count += 1
                    hr_act = "Ask employee to upload a valid profile photograph in Keka HRMS or Slack"
                else:
                    other_errors_count += 1
                    hr_act = f"Check Keka and Slack connector connectivity ({photo_err})"

                report_records.append({
                    "emp_no": emp_data["emp_no"],
                    "emp_name": emp_data["name"],
                    "email": emp_data["email"],
                    "location": loc_display,
                    "design": design_name,
                    "data_validation": "PASSED",
                    "slack_photo_status": photo_status,
                    "generation_status": "SKIPPED",
                    "missing_fields": "",
                    "issues": photo_err,
                    "hr_action": hr_act,
                    "output_pdf_path": "",
                })
                print(f"[-] [{current_num}/{total_records}] Skipped: {emp_data['name']} ({photo_err})")
                continue

            # Process Photo (cached by emp_no + source_hash + design)
            photo_io = batch_cache.get_processed(emp_data["emp_no"], raw_photo_bytes, design_name)
            if not photo_io:
                try:
                    if design_name == "Modern":
                        photo_io = process_photo_modern_circular(raw_photo_bytes, target_dim=800)
                    else:
                        photo_io = process_photo_circular(raw_photo_bytes, target_dim=300)
                    batch_cache.put_processed(emp_data["emp_no"], raw_photo_bytes, design_name, photo_io)
                except Exception as proc_err:
                    skipped_count += 1
                    missing_photos_count += 1
                    location_stats[loc_display]["skipped"] += 1
                    report_records.append({
                        "emp_no": emp_data["emp_no"],
                        "emp_name": emp_data["name"],
                        "email": emp_data["email"],
                        "location": loc_display,
                        "design": design_name,
                        "data_validation": "PASSED",
                        "slack_photo_status": f"Processing Failed ({proc_err})",
                        "generation_status": "SKIPPED",
                        "missing_fields": "",
                        "issues": f"Photo processing error: {proc_err}",
                        "hr_action": "Check image format and re-upload valid photo",
                        "output_pdf_path": "",
                    })
                    print(f"[-] [{current_num}/{total_records}] Skipped: {emp_data['name']} (Photo processing error: {proc_err})")
                    continue

            # Location-Wise Directory Segregation
            loc_clean = sanitize_location(emp_data["location"])
            loc_dir = base_design_dir / loc_clean
            loc_dir.mkdir(parents=True, exist_ok=True)

            safe_num = sanitize_filename(emp_data["emp_no"])
            safe_name = sanitize_filename(emp_data["name"])
            pdf_filename = f"{safe_num}_{safe_name}_IDCard.pdf"
            pdf_path = loc_dir / pdf_filename

            # Generate Individual PDF
            try:
                if design_name == "Modern":
                    generate_modern_id_card_pdf(emp_data, photo_io, pdf_path)
                else:
                    generate_classic_id_card_pdf(emp_data, photo_io, pdf_path)

                generated_count += 1
                location_stats[loc_display]["generated"] += 1
                rel_pdf_path = str(pdf_path.resolve())
                report_records.append({
                    "emp_no": emp_data["emp_no"],
                    "emp_name": emp_data["name"],
                    "email": emp_data["email"],
                    "location": loc_display,
                    "design": design_name,
                    "data_validation": "PASSED",
                    "slack_photo_status": f"Valid {photo_source} Photo" if photo_source in ("Keka", "Slack") else "Valid Custom Photo",
                    "generation_status": "GENERATED",
                    "missing_fields": "",
                    "issues": "",
                    "hr_action": "",
                    "output_pdf_path": rel_pdf_path,
                })
                print(f"[+] [{current_num}/{total_records}] Generated: {rel_pdf_path}")
            except Exception as pdf_err:
                skipped_count += 1
                other_errors_count += 1
                location_stats[loc_display]["skipped"] += 1
                report_records.append({
                    "emp_no": emp_data["emp_no"],
                    "emp_name": emp_data["name"],
                    "email": emp_data["email"],
                    "location": loc_display,
                    "design": design_name,
                    "data_validation": "PASSED",
                    "slack_photo_status": "Valid Custom Photo",
                    "generation_status": "SKIPPED",
                    "missing_fields": "",
                    "issues": f"PDF generation error: {pdf_err}",
                    "hr_action": "Check employee special characters or formatting in ReportLab",
                    "output_pdf_path": "",
                })
                print(f"[-] [{current_num}/{total_records}] Failed: {emp_data['name']} (PDF error: {pdf_err})")

    finally:
        # Phase 5: Clean temporary batch image cache safely
        batch_cache.clear()

    # Phase 6: Save Comprehensive 3-Sheet Audit Report
    try:
        write_generation_report(report_records, report_file, design_name)
        print(f"\n[+] Comprehensive 3-sheet audit report written to: {report_file}")
    except Exception as e:
        print(f"\n[!] Error saving audit report: {e}")

    # Phase 7: Print Terminal Summary (Section 8 Format)
    print("\n" + "=" * 60)
    print("             FINBOX ID CARD GENERATION SUMMARY")
    print("=" * 60)
    print("")
    print(f"Selected Design: {design_name}")
    print("")
    print(f"Total Employees:          {total_records}")
    print(f"Successfully Generated:   {generated_count}")
    print(f"Skipped:                  {skipped_count}")
    print(f"Missing Employee Data:    {missing_data_count}")
    print(f"Missing Slack Photos:     {missing_photos_count}")
    print(f"Slack Users Not Found:    {missing_slack_users_count}")
    print(f"Other Errors:             {other_errors_count}")
    print("")
    print("LOCATION-WISE SUMMARY")
    print("")
    for loc, stats in sorted(location_stats.items()):
        tot = stats["total"]
        gen = stats["generated"]
        pct = (gen / tot * 100) if tot > 0 else 0.0
        print(f"{loc.ljust(22)}: {gen} generated / {tot} total ({pct:.2f}%)")
    print("")
    print("Generated Cards Folder:")
    print(f"{base_design_dir.resolve()}\n")
    print("Generation Report:")
    print(f"{report_file.resolve()}")
    print("=" * 60 + "\n")
    return 0 if generated_count > 0 or total_records == 0 else 1


# ==============================================================================
# INSTANT EMAIL SYNC BATCH MODE (Method 1)
# ==============================================================================
def run_email_batch_mode(
    emails_input,
    design="modern",
    output_dir=None,
    address_mapping=None,
    photos_dir=None,
    photo_match_mode="auto"
):
    """
    Method 1: Instant Email Sync ID Card Generation.
    Takes a semicolon/comma/newline separated string or list of emails.
    For each email:
      1. Fetches employee details (Name, Designation, EMP ID, Phone, DOB, Blood Group,
         Emergency Contact, Office Address based on location) from Keka HRMS.
      2. Slices photo from Local Folder (if provided) -> Keka HRMS -> Slack.
      3. Generates high-res ID Card PDF in output/<Design>/<Location>/<EmpNo>_<Name>_IDCard.pdf.
      4. Writes a full 3-sheet audit report in output/Reports/<Design>_Generation_Report.xlsx.
    """
    global OUTPUT_DIR
    design_lower = str(design or "modern").strip().lower()
    design_name = "Modern" if design_lower == "modern" else "Classic"

    if output_dir is not None:
        OUTPUT_DIR = Path(output_dir)
    else:
        OUTPUT_DIR = create_new_output_dir(prefix=f"ID_Cards_{design_name}_InstantSync")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    base_design_dir = OUTPUT_DIR / design_name
    base_design_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = OUTPUT_DIR / "Reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"{design_name}_Generation_Report.xlsx"

    print("=" * 60)
    print(f"      FinBox ID Card Generator: Instant Email Sync ({design_name})      ")
    print("=" * 60)
    print(f"[+] Output Directory: {OUTPUT_DIR.resolve()}")
    if photos_dir:
        print(f"[+] Local Photos Folder: {photos_dir} (Match: {photo_match_mode})")

    # Parse and sanitize emails
    if isinstance(emails_input, (list, tuple, set)):
        raw_candidates = list(emails_input)
    else:
        raw_candidates = re.split(r'[;,\n\r\t]+', str(emails_input or ""))

    email_list = []
    for item in raw_candidates:
        clean_item = str(item or "").strip().lower()
        if clean_item and "@" in clean_item and clean_item not in email_list:
            email_list.append(clean_item)

    if not email_list:
        print("\n[X] Error: No valid email addresses found in input.")
        print("    Please enter at least one valid email (e.g. employee@finbox.in).")
        print("=" * 60 + "\n")
        return 1

    print(f"[+] Received {len(email_list)} target email address(es):")
    for em in email_list:
        print(f"    - {em}")

    load_dotenv()
    keka_api_key = os.getenv("KEKA_API_KEY", "").strip()
    keka_client_id = os.getenv("KEKA_CLIENT_ID", "").strip()
    keka_client_secret = os.getenv("KEKA_CLIENT_SECRET", "").strip()
    keka_subdomain = os.getenv("KEKA_SUBDOMAIN", "finbox").strip()
    slack_token = os.getenv("SLACK_BOT_TOKEN", "").strip()

    if not keka_api_key and not (keka_client_id and keka_client_secret):
        print("\n[X] Error: Keka HRMS credentials are not configured in Settings/.env.")
        print("    Instant Email Sync requires Keka API access to retrieve employee details.")
        print("=" * 60 + "\n")
        return 1

    slack_client = None
    if slack_token and not slack_token.startswith("xoxb-your-"):
        try:
            slack_client = WebClient(token=slack_token)
        except Exception:
            slack_client = None

    if address_mapping is None:
        address_mapping = get_office_addresses()

    if design_name == "Modern":
        ensure_modern_templates()

    batch_cache = BatchImageCache()
    start_time = time.time()

    total_records = len(email_list)
    generated_count = 0
    skipped_count = 0
    missing_data_count = 0
    missing_photos_count = 0
    other_errors_count = 0
    location_stats = {}
    report_records = []

    try:
        for idx, email in enumerate(email_list, start=1):
            curr_emp_label = email
            print_bulk_progress(design_name, total_records, idx, generated_count, skipped_count, curr_emp_label, start_time)

            # 1. Fetch details from Keka
            print(f"\n[+] [{idx}/{total_records}] Fetching profile for {email} from Keka HRMS...")
            emp_data, keka_err = fetch_keka_employee_full_details(
                email,
                api_key=keka_api_key,
                client_id=keka_client_id,
                client_secret=keka_client_secret,
                subdomain=keka_subdomain,
                address_mapping=address_mapping
            )

            if keka_err or not emp_data:
                skipped_count += 1
                missing_data_count += 1
                loc_disp = "Unknown"
                if loc_disp not in location_stats:
                    location_stats[loc_disp] = {"total": 0, "generated": 0, "skipped": 0}
                location_stats[loc_disp]["total"] += 1
                location_stats[loc_disp]["skipped"] += 1

                report_records.append({
                    "emp_no": "",
                    "emp_name": "",
                    "email": email,
                    "location": loc_disp,
                    "design": design_name,
                    "data_validation": "FAILED",
                    "slack_photo_status": "Not Checked",
                    "generation_status": "SKIPPED",
                    "missing_fields": "Employee Record",
                    "issues": keka_err or "Failed to retrieve from Keka",
                    "hr_action": "Check if email is active and registered in Keka HRMS",
                    "output_pdf_path": "",
                })
                print(f"[-] Skipped {email}: {keka_err}")
                continue

            loc_disp = emp_data.get("location") or "Bengaluru"
            if loc_disp not in location_stats:
                location_stats[loc_disp] = {"total": 0, "generated": 0, "skipped": 0}
            location_stats[loc_disp]["total"] += 1

            # 1b. Strict completeness validation: Don't generate if any required Keka data is missing
            val_res = validate_keka_employee_record(emp_data)
            if not val_res["is_valid"]:
                skipped_count += 1
                missing_data_count += 1
                location_stats[loc_disp]["skipped"] += 1
                missing_str = ", ".join(val_res["missing_fields"])
                issues_str = "; ".join(val_res["issues"])
                hr_action_str = "; ".join(val_res["hr_actions"])
                report_records.append({
                    "emp_no": emp_data.get("emp_no", ""),
                    "emp_name": emp_data.get("name", ""),
                    "email": email,
                    "location": loc_disp,
                    "design": design_name,
                    "data_validation": "FAILED",
                    "slack_photo_status": "Not Checked",
                    "generation_status": "SKIPPED",
                    "missing_fields": missing_str,
                    "issues": issues_str,
                    "hr_action": hr_action_str,
                    "output_pdf_path": "",
                })
                print(f"[-] Skipped {emp_data.get('name') or email}: Incomplete data in Keka HRMS. Missing: {missing_str}")
                continue

            # 2. Text fitting validation
            fit_ok, fit_err = validate_employee_text_fitting(emp_data, design_name)
            if not fit_ok:
                skipped_count += 1
                other_errors_count += 1
                location_stats[loc_disp]["skipped"] += 1
                report_records.append({
                    "emp_no": emp_data.get("emp_no", ""),
                    "emp_name": emp_data.get("name", ""),
                    "email": email,
                    "location": loc_disp,
                    "design": design_name,
                    "data_validation": "FAILED",
                    "slack_photo_status": "Not Checked",
                    "generation_status": "SKIPPED",
                    "missing_fields": "",
                    "issues": fit_err,
                    "hr_action": "Shorten text or update employee details to fit ID card layout",
                    "output_pdf_path": "",
                })
                print(f"[-] Skipped {emp_data.get('name')}: {fit_err}")
                continue

            # 3. Retrieve Photo (Local Folder -> Keka -> Slack)
            print(f"[+] Sourcing photo for {emp_data.get('name')} (Local -> Keka -> Slack)...")
            raw_photo_bytes, photo_err, photo_status, photo_source = fetch_profile_photo_with_fallback(
                email,
                emp_no=emp_data.get("emp_no"),
                slack_client=slack_client,
                slack_token=slack_token,
                keka_api_key=keka_api_key,
                keka_client_id=keka_client_id,
                keka_client_secret=keka_client_secret,
                keka_subdomain=keka_subdomain,
                photos_dir=photos_dir,
                photo_match_mode=photo_match_mode
            )

            if photo_err or not raw_photo_bytes:
                skipped_count += 1
                missing_photos_count += 1
                location_stats[loc_disp]["skipped"] += 1
                report_records.append({
                    "emp_no": emp_data["emp_no"],
                    "emp_name": emp_data["name"],
                    "email": email,
                    "location": loc_disp,
                    "design": design_name,
                    "data_validation": "PASSED",
                    "slack_photo_status": photo_status,
                    "generation_status": "SKIPPED",
                    "missing_fields": "",
                    "issues": photo_err,
                    "hr_action": "Upload photo to Keka HRMS, Slack, or local folder",
                    "output_pdf_path": "",
                })
                print(f"[-] Skipped {emp_data['name']}: {photo_err}")
                continue

            # 4. Process Photo
            try:
                if design_name == "Modern":
                    photo_io = process_photo_modern_circular(raw_photo_bytes, target_dim=800)
                else:
                    photo_io = process_photo_circular(raw_photo_bytes, target_dim=300)
            except Exception as proc_err:
                skipped_count += 1
                missing_photos_count += 1
                location_stats[loc_disp]["skipped"] += 1
                report_records.append({
                    "emp_no": emp_data["emp_no"],
                    "emp_name": emp_data["name"],
                    "email": email,
                    "location": loc_disp,
                    "design": design_name,
                    "data_validation": "PASSED",
                    "slack_photo_status": f"Processing Failed ({proc_err})",
                    "generation_status": "SKIPPED",
                    "missing_fields": "",
                    "issues": f"Photo processing error: {proc_err}",
                    "hr_action": "Check image format and re-upload valid photo",
                    "output_pdf_path": "",
                })
                print(f"[-] Skipped {emp_data['name']}: Photo processing failed ({proc_err})")
                continue

            # 5. Output PDF Generation
            loc_clean = sanitize_location(emp_data["location"])
            loc_dir = base_design_dir / loc_clean
            loc_dir.mkdir(parents=True, exist_ok=True)

            safe_num = sanitize_filename(emp_data["emp_no"])
            safe_name = sanitize_filename(emp_data["name"])
            pdf_filename = f"{safe_num}_{safe_name}_IDCard.pdf"
            pdf_path = loc_dir / pdf_filename

            try:
                if design_name == "Modern":
                    generate_modern_id_card_pdf(emp_data, photo_io, pdf_path)
                else:
                    generate_classic_id_card_pdf(emp_data, photo_io, pdf_path)

                generated_count += 1
                location_stats[loc_disp]["generated"] += 1
                rel_pdf_path = str(pdf_path.resolve())
                report_records.append({
                    "emp_no": emp_data["emp_no"],
                    "emp_name": emp_data["name"],
                    "email": email,
                    "location": loc_disp,
                    "design": design_name,
                    "data_validation": "PASSED",
                    "slack_photo_status": f"Valid {photo_source} Photo",
                    "generation_status": "GENERATED",
                    "missing_fields": "",
                    "issues": "",
                    "hr_action": "",
                    "output_pdf_path": rel_pdf_path,
                })
                print(f"[+] [{idx}/{total_records}] Generated: {rel_pdf_path}")
            except Exception as pdf_err:
                skipped_count += 1
                other_errors_count += 1
                location_stats[loc_disp]["skipped"] += 1
                report_records.append({
                    "emp_no": emp_data["emp_no"],
                    "emp_name": emp_data["name"],
                    "email": email,
                    "location": loc_disp,
                    "design": design_name,
                    "data_validation": "PASSED",
                    "slack_photo_status": f"Valid {photo_source} Photo",
                    "generation_status": "SKIPPED",
                    "missing_fields": "",
                    "issues": f"PDF generation error: {pdf_err}",
                    "hr_action": "Check ReportLab special character rendering",
                    "output_pdf_path": "",
                })
                print(f"[-] Failed {emp_data['name']}: {pdf_err}")

    finally:
        batch_cache.clear()

    # Write Audit Report
    try:
        write_generation_report(report_records, report_file, design_name)
        print(f"\n[+] 3-Sheet Audit report written to: {report_file}")
    except Exception as e:
        print(f"\n[!] Error saving audit report: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("      FINBOX ID CARD GENERATION SUMMARY (INSTANT EMAIL SYNC)      ")
    print("=" * 60)
    print(f"Selected Design:         {design_name}")
    print(f"Total Emails Processed:  {total_records}")
    print(f"Successfully Generated:  {generated_count}")
    print(f"Skipped:                 {skipped_count}")
    print(f"Incomplete Data / Missing: {missing_data_count}")
    print(f"Missing Photos:          {missing_photos_count}")
    print(f"Other Errors:            {other_errors_count}")
    print("\nLOCATION-WISE SUMMARY:")
    for loc, stats in sorted(location_stats.items()):
        tot = stats["total"]
        gen = stats["generated"]
        pct = (gen / tot * 100) if tot > 0 else 0.0
        print(f"  - {loc.ljust(22)}: {gen} generated / {tot} total ({pct:.2f}%)")
    print(f"\nGenerated Cards Folder:\n{base_design_dir.resolve()}")
    print(f"\nGeneration Report:\n{report_file.resolve()}")
    print("=" * 60 + "\n")

    return 0 if generated_count > 0 or total_records == 0 else 1


# ==============================================================================
# INTERACTIVE DESIGN SELECTION
# ==============================================================================
def prompt_design_selection():
    """
    Displays the design selection menu:
    ====================================
          FINBOX ID CARD GENERATOR
    ====================================

    Select ID Card Design:

    1. Classic
    2. Modern

    Enter your choice (1 or 2):
    """
    print("========================================")
    print("       FINBOX ID CARD GENERATOR         ")
    print("========================================")
    print("")
    print("Select the ID Card Design:")
    print("")
    print("1. Classic")
    print("2. Modern")
    print("")

    while True:
        try:
            choice = input("Enter your choice (1 or 2): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nOperation cancelled.")
            sys.exit(0)

        if choice in ["1", "classic", "Classic", "c", "C"]:
            return "classic"
        elif choice in ["2", "modern", "Modern", "m", "M"]:
            return "modern"
        else:
            print("\n[!] Invalid choice. Please enter 1 for Classic or 2 for Modern.\n")



# ==============================================================================
# ENTRY POINT
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="FinBox Employee ID Card Generator (Classic & Modern Designs)"
    )
    parser.add_argument(
        "--test-email",
        type=str,
        default=None,
        help="Test Slack connection and download profile photo for a given email without generating ID cards."
    )
    parser.add_argument(
        "--preview-email",
        type=str,
        default=None,
        help="Generate a 2-page ID card preview (Page 1 = Front, Page 2 = Back) for a single employee matched by email."
    )
    parser.add_argument(
        "--design",
        type=str,
        choices=["classic", "modern"],
        default=None,
        help="Choose design: 'classic' or 'modern'. If omitted in bulk mode, prompts interactively."
    )
    parser.add_argument(
        "--test-keka-email",
        type=str,
        default=None,
        help="Test Keka HRMS connection and download profile photo for a given email without generating ID cards."
    )
    args = parser.parse_args()

    if args.preview_email:
        design = args.design or "classic"
        sys.exit(run_preview_mode(args.preview_email, design=design))
    elif args.test_email:
        sys.exit(run_slack_test(args.test_email))
    elif args.test_keka_email:
        sys.exit(run_keka_test(args.test_keka_email))
    else:
        # Bulk generation mode
        if args.design:
            selected_design = args.design
        else:
            selected_design = prompt_design_selection()
        run_bulk_generation(design=selected_design)


if __name__ == "__main__":
    main()
