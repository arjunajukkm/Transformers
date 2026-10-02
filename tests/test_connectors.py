"""
tests/test_connectors.py
────────────────────────
Unit and integration tests for Workspace Connectors (Slack and Keka HRMS).
"""

import os
import pytest
from pathlib import Path
from dotenv import load_dotenv
from unittest.mock import MagicMock

import id_card_module as ic


def test_slack_connector_live_or_env():
    """Tests Slack status check using the environment token."""
    load_dotenv(override=True)
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token or not token.startswith("xoxb-"):
        pytest.skip("SLACK_BOT_TOKEN not configured in .env")

    is_conn, msg, user, *rest = ic.check_slack_status()
    assert is_conn is True
    assert "Connected to" in msg
    assert user != ""
    if rest:
        bot_id = rest[0]
        assert bot_id.startswith("B")


def test_slack_connector_bot_id_matching():
    """Tests passing a Bot ID directly."""
    load_dotenv(override=True)
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token or not token.startswith("xoxb-"):
        pytest.skip("SLACK_BOT_TOKEN not configured in .env")

    # B0BE6TGNB09 is the FinBox bulk_download bot ID
    is_conn, msg, user, *rest = ic.check_slack_status("B0BE6TGNB09")
    assert is_conn is True
    assert "Connected to FinBox" in msg


def test_slack_connector_invalid_token():
    """Tests that an invalid token is rejected gracefully without raising unhandled exceptions."""
    is_conn, msg, user, *rest = ic.check_slack_status("xoxb-invalid-bogus-token-00000")
    assert is_conn is False
    assert "Failed" in msg or "error" in msg


def test_keka_connector_missing_key():
    """Tests Keka connector when credentials are empty."""
    is_conn, msg, details = ic.check_keka_status(api_key="", client_id="", client_secret="", subdomain="finbox")
    if not os.getenv("KEKA_API_KEY") and not (os.getenv("KEKA_CLIENT_ID") and os.getenv("KEKA_CLIENT_SECRET")):
        assert is_conn is False
        assert "credentials missing" in msg.lower() or "missing" in msg.lower()


def test_keka_connector_invalid_key_http_response():
    """Tests that an invalid key returns a structured 401 error gracefully."""
    is_conn, msg, details = ic.check_keka_status(api_key="invalid_test_key", client_id="", client_secret="", subdomain="finbox")
    assert is_conn is False
    assert "Invalid credentials" in msg or "Auth Failed" in msg or "error" in msg.lower()


def test_save_env_variable(tmp_path):
    """Tests saving credentials to a temporary .env file."""
    test_env = tmp_path / ".env"
    test_env.write_text("# Test comment\nEXISTING_VAR=123\n")

    ic.save_env_variable("TEST_TOKEN", "abc-456", env_path=str(test_env))

    content = test_env.read_text()
    assert "# Test comment" in content
    assert "EXISTING_VAR=123" in content
    assert "TEST_TOKEN" in content
    assert os.environ.get("TEST_TOKEN") == "abc-456"


def _make_dummy_image_bytes():
    from PIL import Image
    import io
    img = Image.new("RGB", (100, 100), color=(41, 134, 206))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_keka_fetch_photo_mock_success(monkeypatch):
    """Tests that fetch_keka_profile_photo resolves thumbs and downloads image successfully."""
    dummy_bytes = _make_dummy_image_bytes()

    class MockSearchResponse:
        status_code = 200
        def json(self):
            return {
                "succeeded": True,
                "data": {
                    "id": "keka-emp-001",
                    "displayName": "Test Employee",
                    "email": "test.emp@finbox.in",
                    "image": {
                        "fileName": "photo.jpg",
                        "thumbs": {
                            "large": "https://cdn.keka.com/photos/large.jpg",
                            "medium": "https://cdn.keka.com/photos/medium.jpg"
                        }
                    }
                }
            }

    class MockImageDownloadResponse:
        status_code = 200
        content = dummy_bytes

    import requests
    def mock_post(url, *args, **kwargs):
        return MockSearchResponse()

    def mock_get(url, *args, **kwargs):
        return MockImageDownloadResponse()

    monkeypatch.setattr(requests, "post", mock_post)
    monkeypatch.setattr(requests, "get", mock_get)

    raw_bytes, err_msg, status_label = ic.fetch_keka_profile_photo(
        "test.emp@finbox.in", api_key="mock_keka_token", subdomain="finbox"
    )

    assert err_msg is None
    assert status_label == "Valid Keka Photo"
    assert raw_bytes == dummy_bytes


def test_keka_fetch_photo_missing_key():
    """Tests that missing Keka credentials are reported cleanly."""
    raw_bytes, err_msg, status_label = ic.fetch_keka_profile_photo(
        "test.emp@finbox.in", api_key="", client_id="", client_secret="", subdomain="finbox"
    )
    if not os.getenv("KEKA_API_KEY") and not (os.getenv("KEKA_CLIENT_ID") and os.getenv("KEKA_CLIENT_SECRET")):
        assert raw_bytes is None
        assert "credentials missing" in err_msg.lower() or "keka" in err_msg.lower()


def test_keka_fetch_photo_no_image_in_profile(monkeypatch):
    """Tests handling when employee profile exists in Keka but has no photo uploaded."""
    class MockSearchNoPhotoResponse:
        status_code = 200
        def json(self):
            return {
                "succeeded": True,
                "data": {
                    "id": "keka-emp-002",
                    "displayName": "No Photo User",
                    "email": "nophoto@finbox.in",
                    "image": None
                }
            }

    import requests
    monkeypatch.setattr(requests, "post", lambda url, *args, **kwargs: MockSearchNoPhotoResponse())

    raw_bytes, err_msg, status_label = ic.fetch_keka_profile_photo(
        "nophoto@finbox.in", api_key="mock_key", subdomain="finbox"
    )
    assert raw_bytes is None
    assert status_label == "No Keka Photo"
    assert "No profile photo uploaded" in err_msg


def test_unified_photo_fetch_keka_first_priority(monkeypatch):
    """
    Tests the core requirement: Profile photo should be fetched from Keka 1st!
    When Keka has photo, Slack should NOT be queried.
    """
    keka_dummy_bytes = _make_dummy_image_bytes()
    slack_called = []

    def mock_keka_fetch(email, emp_no=None, api_key=None, subdomain=None, max_retries=2, **kwargs):
        return keka_dummy_bytes, None, "Valid Keka Photo"

    def mock_slack_fetch(client, email, token, max_retries=3, **kwargs):
        slack_called.append(True)
        return None, "Should not be called", "Should Not Call"

    monkeypatch.setattr(ic.gen, "fetch_keka_profile_photo", mock_keka_fetch)
    monkeypatch.setattr(ic.gen, "fetch_slack_profile_photo", mock_slack_fetch)

    raw_bytes, err_msg, status_label, source = ic.fetch_profile_photo_with_fallback(
        "arjun.s@finbox.in",
        keka_api_key="mock_keka_key",
        slack_token="xoxb-mock-token"
    )

    assert source == "Keka"
    assert status_label == "Valid Keka Photo"
    assert raw_bytes == keka_dummy_bytes
    assert err_msg is None
    assert len(slack_called) == 0, "Slack should not be queried when Keka has profile photo"


def test_unified_photo_fetch_keka_empty_falls_back_to_slack(monkeypatch):
    """
    Tests the fallback requirement: If no data / photo in Keka, fallback to Slack!
    """
    slack_dummy_bytes = _make_dummy_image_bytes()

    def mock_keka_fetch(email, emp_no=None, api_key=None, subdomain=None, max_retries=2, **kwargs):
        return None, "No profile photo uploaded in Keka HRMS", "No Keka Photo"

    def mock_slack_fetch(client, email, token, max_retries=3, **kwargs):
        return slack_dummy_bytes, None, "Valid Custom Photo"

    class DummySlackClient:
        pass

    monkeypatch.setattr(ic.gen, "fetch_keka_profile_photo", mock_keka_fetch)
    monkeypatch.setattr(ic.gen, "fetch_slack_profile_photo", mock_slack_fetch)

    raw_bytes, err_msg, status_label, source = ic.fetch_profile_photo_with_fallback(
        "arjun.s@finbox.in",
        slack_client=DummySlackClient(),
        slack_token="xoxb-mock-token",
        keka_api_key="mock_keka_key"
    )

    assert source == "Slack"
    assert status_label == "Valid Custom Photo"
    assert raw_bytes == slack_dummy_bytes
    assert err_msg is None


def test_unified_photo_fetch_both_fail(monkeypatch):
    """Tests clear combined diagnostic reporting when neither Keka nor Slack has a valid photo."""
    def mock_keka_fetch(email, emp_no=None, api_key=None, subdomain=None, max_retries=2, **kwargs):
        return None, "Employee record not found in Keka HRMS", "Keka User Not Found"

    def mock_slack_fetch(client, email, token, max_retries=3, **kwargs):
        return None, "Default Slack avatar detected", "Default Avatar Detected"

    class DummySlackClient:
        pass

    monkeypatch.setattr(ic.gen, "fetch_keka_profile_photo", mock_keka_fetch)
    monkeypatch.setattr(ic.gen, "fetch_slack_profile_photo", mock_slack_fetch)

    raw_bytes, err_msg, status_label, source = ic.fetch_profile_photo_with_fallback(
        "ghost.user@finbox.in",
        slack_client=DummySlackClient(),
        slack_token="xoxb-mock-token",
        keka_api_key="mock_keka_key"
    )

    assert source == "None"
    assert raw_bytes is None
    assert "Keka:" in err_msg
    assert "Slack:" in err_msg


def test_keka_oauth_token_exchange_success(monkeypatch):
    """Tests that Keka OAuth client credentials exchange retrieves and caches the Bearer access token."""
    posted_data = {}

    class MockTokenResponse:
        status_code = 200
        def json(self):
            return {
                "access_token": "mock_jwt_access_token_xyz_999",
                "token_type": "Bearer",
                "expires_in": 86400,
                "scope": "kekaapi"
            }

    import requests
    def mock_post(url, data=None, **kwargs):
        if "connect/token" in url:
            posted_data.update(data or {})
            return MockTokenResponse()
        raise ValueError(f"Unexpected URL: {url}")

    monkeypatch.setattr(requests, "post", mock_post)

    # Invalidate cache
    ic.gen._KEKA_TOKEN_CACHE["access_token"] = None
    ic.gen._KEKA_TOKEN_CACHE["expires_at"] = 0

    token, err = ic.get_keka_access_token(
        client_id="test_cid_123",
        client_secret="test_csec_456",
        api_key="test_api_key_789"
    )

    assert err is None
    assert token == "mock_jwt_access_token_xyz_999"
    assert posted_data["grant_type"] == "kekaapi"
    assert posted_data["scope"] == "kekaapi"
    assert posted_data["client_id"] == "test_cid_123"
    assert posted_data["client_secret"] == "test_csec_456"
    assert posted_data["api_key"] == "test_api_key_789"


def test_keka_oauth_token_exchange_invalid_creds(monkeypatch):
    """Tests handling of 400 Bad Request / Invalid client credentials from Keka OAuth server."""
    class MockErrorResponse:
        status_code = 400
        def json(self):
            return {"error": "invalid_client", "error_description": "Client authentication failed"}

    import requests
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: MockErrorResponse())

    # Invalidate cache
    ic.gen._KEKA_TOKEN_CACHE["access_token"] = None
    ic.gen._KEKA_TOKEN_CACHE["expires_at"] = 0

    token, err = ic.get_keka_access_token(
        client_id="wrong_cid",
        client_secret="wrong_sec",
        api_key="wrong_key"
    )

    assert token is None
    assert "Client authentication failed" in err


def test_keka_direct_bearer_fallback():
    """Tests that a direct Bearer token passed alone without client_id/secret is used directly."""
    token, err = ic.get_keka_access_token(
        api_key="direct_preissued_jwt_token",
        client_id="",
        client_secret=""
    )
    assert err is None
    assert token == "direct_preissued_jwt_token"


def test_keka_portal_2fa_otp_callback_flow(monkeypatch):
    """Tests that _perform_portal_login invokes otp_callback and checks RememberBrowser when 2FA is triggered."""
    from unittest.mock import MagicMock
    import keka_data_fetcher

    mock_driver = MagicMock()
    mock_wait = MagicMock()

    # Sequence of URLs: start -> submit -> verifycode -> dashboard
    url_sequence = [
        "https://finbox.keka.com",
        "https://app.keka.com/Account/VerifyCode",
        "https://finbox.keka.com/ui/#/home"
    ]
    url_index = [0]

    def get_url():
        idx = min(url_index[0], len(url_sequence) - 1)
        return url_sequence[idx]

    type(mock_driver).current_url = property(lambda self: get_url())

    # Mock elements
    mock_code_input = MagicMock()
    mock_remember_box = MagicMock()
    mock_remember_box.is_selected.return_value = False
    mock_verify_btn = MagicMock()

    def advance_url(*args, **kwargs):
        url_index[0] += 1

    mock_verify_btn.click.side_effect = advance_url

    def find_elements(by, val):
        if "Code" in val or "code" in val:
            return [mock_code_input]
        elif "RememberBrowser" in val:
            return [mock_remember_box]
        elif "Verify" in val or "submit" in val:
            return [mock_verify_btn]
        return []

    mock_driver.find_elements.side_effect = find_elements
    mock_driver.find_element.return_value = mock_verify_btn

    fetcher = keka_data_fetcher.KekaDataFetcher(
        subdomain="finbox",
        keka_email="test@finbox.in",
        keka_password="secretpassword"
    )

    otp_called = []
    def mock_otp_cb(provider):
        otp_called.append(provider)
        return "654321"

    # Simulate landing on VerifyCode
    url_index[0] = 1
    ok, msg, details = fetcher._perform_portal_login(
        mock_driver, mock_wait, timeout=10, otp_callback=mock_otp_cb
    )

    assert ok is True
    assert details["status"] == "authenticated"
    assert "2FA verified" in msg
    assert otp_called == ["email"]
    mock_code_input.send_keys.assert_called_with("654321")
    mock_remember_box.click.assert_called_once()


def test_keka_portal_authorize_in_browser_wrapper(monkeypatch):
    """Tests that id_card_module.authorize_keka_portal_in_browser properly routes to keka_data_fetcher."""
    import keka_data_fetcher

    called = {}
    def mock_launch(subdomain=None, keka_email=None, keka_password=None, timeout=180, on_status_update=None):
        called["subdomain"] = subdomain
        called["email"] = keka_email
        called["password"] = keka_password
        called["timeout"] = timeout
        return True, "Mock authorized", {"status": "authenticated"}

    monkeypatch.setattr(keka_data_fetcher, "launch_interactive_browser_session", mock_launch)

    ok, msg, details = ic.authorize_keka_portal_in_browser(
        subdomain="moshpit", email="user@moshpit.com", password="pwd", timeout=60
    )

    assert ok is True
    assert called["subdomain"] == "moshpit"
    assert called["email"] == "user@moshpit.com"
    assert called["password"] == "pwd"
    assert called["timeout"] == 60


def test_launch_interactive_browser_session_handles_none_url_and_authenticates(monkeypatch):
    """Ensures launch_interactive_browser_session gracefully handles None/empty current_url and authenticates."""
    import keka_data_fetcher

    mock_driver = MagicMock()
    mock_driver.window_handles = ["win1"]

    url_states = [None, "data:,", "https://app.keka.com/Account/Login", "https://moshpit.keka.com/#/home"]
    url_idx = [0]

    def get_url():
        idx = min(url_idx[0], len(url_states) - 1)
        val = url_states[idx]
        url_idx[0] += 1
        return val

    type(mock_driver).current_url = property(lambda self: get_url())

    monkeypatch.setattr(keka_data_fetcher, "_create_chrome_driver", lambda *a, **k: mock_driver)

    updates = []
    ok, msg, details = keka_data_fetcher.launch_interactive_browser_session(
        subdomain="moshpit", timeout=10, on_status_update=lambda s: updates.append(s)
    )

    assert ok is True
    assert details["status"] == "authenticated"
    assert "successfully authorized" in msg
    mock_driver.quit.assert_called_once()


def test_launch_interactive_browser_session_window_closed(monkeypatch):
    """Ensures closing the interactive browser returns a clean cancelled status without error."""
    import keka_data_fetcher

    mock_driver = MagicMock()
    mock_driver.window_handles = []  # User closed the window

    monkeypatch.setattr(keka_data_fetcher, "_create_chrome_driver", lambda *a, **k: mock_driver)

    ok, msg, details = keka_data_fetcher.launch_interactive_browser_session(
        subdomain="moshpit", timeout=5
    )

    assert ok is False
    assert details["status"] == "cancelled"
    mock_driver.quit.assert_called_once()




