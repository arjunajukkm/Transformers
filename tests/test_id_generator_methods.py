import os
import io
import json
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generate_id_cards as gen
import id_card_module as id_card


def test_office_address_resolution():
    mapping = {
        "Bengaluru": "FinBox HQ, Bengaluru, Karnataka - 560103",
        "Mumbai": "FinBox Mumbai, Maharashtra - 400059",
        "Gurugram": "FinBox Gurgaon, Haryana - 122002",
        "Default": "FinBox Default Address, Bengaluru - 560103"
    }

    # Exact match
    assert gen.resolve_office_address("Bengaluru", mapping) == "FinBox HQ, Bengaluru, Karnataka - 560103"
    assert gen.resolve_office_address("mumbai", mapping) == "FinBox Mumbai, Maharashtra - 400059"

    # Substring match (e.g. "Gurugram Office" or "DLF Gurgaon")
    assert gen.resolve_office_address("Gurugram Office", mapping) == "FinBox Gurgaon, Haryana - 122002"

    # Unknown location fallback
    assert gen.resolve_office_address("Singapore", mapping) == "FinBox Default Address, Bengaluru - 560103"
    assert gen.resolve_office_address("", mapping) == "FinBox Default Address, Bengaluru - 560103"
    assert gen.resolve_office_address(None, mapping) == "FinBox Default Address, Bengaluru - 560103"


def test_get_and_save_office_addresses(tmp_path):
    test_json = tmp_path / "office_addresses.json"
    custom_map = {
        "Chennai": "Tidel Park, Chennai - 600113",
        "Default": "Default HQ"
    }

    with patch.object(gen, "Path") as mock_path:
        # Patch local_data path inside get_office_addresses
        test_file = tmp_path / "office_addresses.json"
        test_file.write_text(json.dumps(custom_map), encoding="utf-8")

        # Read directly
        loaded = json.loads(test_file.read_text(encoding="utf-8"))
        assert loaded["Chennai"] == "Tidel Park, Chennai - 600113"


def test_find_local_photo_by_emp_no(tmp_path):
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()

    # Create dummy images
    (photos_dir / "FINBP200.jpg").write_bytes(b"dummy_bytes_emp200")
    (photos_dir / "arjun.s@finbox.in.png").write_bytes(b"dummy_bytes_arjun")
    (photos_dir / "vinoth_kumar.jpeg").write_bytes(b"dummy_bytes_vinoth")

    # Match by emp_no
    res = gen.find_local_photo(str(photos_dir), emp_no="FINBP200", email="someone@finbox.in", match_mode="emp_no")
    assert res == b"dummy_bytes_emp200"

    # Match by emp_no case-insensitive
    res2 = gen.find_local_photo(str(photos_dir), emp_no="finbp200", match_mode="auto")
    assert res2 == b"dummy_bytes_emp200"

    # Match by email
    res3 = gen.find_local_photo(str(photos_dir), emp_no="FINBP999", email="arjun.s@finbox.in", match_mode="email")
    assert res3 == b"dummy_bytes_arjun"

    # Match by email username
    res4 = gen.find_local_photo(str(photos_dir), email="vinoth_kumar@finbox.in", match_mode="auto")
    assert res4 == b"dummy_bytes_vinoth"

    # Not found
    res5 = gen.find_local_photo(str(photos_dir), emp_no="UNKNOWN", email="unknown@finbox.in", match_mode="auto")
    assert res5 is None


def test_email_parsing_multi_format():
    input_str = "kanupriya.rathore@finbox.in; vinoth.kumar@finbox.in, arjun.s@finbox.in\nteam@finbox.in\r\nkanupriya.rathore@finbox.in"
    raw_candidates = gen.re.split(r'[;,\n\r\t]+', input_str)

    email_list = []
    for item in raw_candidates:
        clean = str(item or "").strip().lower()
        if clean and "@" in clean and clean not in email_list:
            email_list.append(clean)

    assert email_list == [
        "kanupriya.rathore@finbox.in",
        "vinoth.kumar@finbox.in",
        "arjun.s@finbox.in",
        "team@finbox.in"
    ]
    # Check deduplication worked
    assert len(email_list) == 4


def test_fetch_profile_photo_with_fallback_priority_local(tmp_path):
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    (photos_dir / "FINBP101.png").write_bytes(b"local_photo_101")

    # Priority 0 should return local photo directly without calling Keka or Slack
    bytes_out, err, status, src = gen.fetch_profile_photo_with_fallback(
        email="test@finbox.in",
        emp_no="FINBP101",
        photos_dir=str(photos_dir),
        photo_match_mode="auto"
    )

    assert bytes_out == b"local_photo_101"
    assert err is None
    assert src == "Local Folder"
    assert status == "Valid Local Photo"
