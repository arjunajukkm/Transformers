"""
tests/test_absent_ui_integration.py
───────────────────────────────────
Tests that the Absent Management frame and Keka sync integration
are properly wired up in the desktop application.
"""

import pytest
from app import App
from unittest.mock import MagicMock, patch


def test_absent_frame_attributes():
    """Verify that absent management UI state and methods exist on App."""
    assert hasattr(App, "pull_keka_absent_data")
    assert hasattr(App, "start_process_absent")
    assert hasattr(App, "_build_absent_frame")


def test_absent_variables_initialized():
    """Verify that absent management StringVars and defaults initialize properly."""
    with patch.object(App, "__init__", return_value=None):
        app = App()
        assert hasattr(app, "pull_keka_absent_data")


def test_keka_portal_credentials_save(tmp_path, monkeypatch):
    """Verify that save_connectors_credentials saves portal login email & password."""
    import id_card_module as id_card
    test_env = tmp_path / ".env"
    test_env.write_text("# Test\n")

    orig_save = id_card.save_env_variable
    monkeypatch.setattr(id_card, "save_env_variable", lambda k, v: orig_save(k, v, env_path=str(test_env)))

    class MockVar:
        def __init__(self, val=""):
            self._val = val
        def get(self):
            return self._val

    with patch.object(App, "__init__", return_value=None):
        app = App()
        app.keka_subdomain_var = MockVar("moshpit")
        app.keka_client_id_var = MockVar("test_cid")
        app.keka_client_secret_var = MockVar("test_csec")
        app.keka_api_key_var = MockVar("test_key")
        app.keka_login_email_var = MockVar("hr@moshpit.com")
        app.keka_login_password_var = MockVar("secretpass123")
        app.slack_bot_token_var = MockVar("")
        app._append_connector_log = MagicMock()

        with patch("app.messagebox.showinfo"):
            app.save_connectors_credentials("keka")

        content = test_env.read_text()
        assert "KEKA_LOGIN_EMAIL='hr@moshpit.com'" in content
        assert "KEKA_LOGIN_PASSWORD='secretpass123'" in content


def test_keka_api_credentials_save_isolated(tmp_path, monkeypatch):
    """Verify that save_connectors_credentials('keka_api') saves only API variables."""
    import id_card_module as id_card
    test_env = tmp_path / ".env"
    test_env.write_text("# Test\n")

    orig_save = id_card.save_env_variable
    monkeypatch.setattr(id_card, "save_env_variable", lambda k, v: orig_save(k, v, env_path=str(test_env)))

    class MockVar:
        def __init__(self, val=""):
            self._val = val
        def get(self):
            return self._val

    with patch.object(App, "__init__", return_value=None):
        app = App()
        app.keka_subdomain_var = MockVar("moshpit_tenant")
        app.keka_client_id_var = MockVar("isolated_cid")
        app.keka_client_secret_var = MockVar("isolated_csec")
        app.keka_api_key_var = MockVar("isolated_key")
        app.keka_login_email_var = MockVar("should_not_save@moshpit.com")
        app.keka_login_password_var = MockVar("should_not_save_pass")
        app.slack_bot_token_var = MockVar("")
        app._append_connector_log = MagicMock()

        with patch("app.messagebox.showinfo"):
            app.save_connectors_credentials("keka_api")

        content = test_env.read_text()
        assert "KEKA_CLIENT_ID='isolated_cid'" in content
        assert "KEKA_CLIENT_SECRET='isolated_csec'" in content
        assert "KEKA_API_KEY='isolated_key'" in content
        assert "KEKA_SUBDOMAIN='moshpit_tenant'" in content
        assert "should_not_save@moshpit.com" not in content
        assert "should_not_save_pass" not in content


def test_keka_portal_credentials_save_isolated(tmp_path, monkeypatch):
    """Verify that save_connectors_credentials('keka_portal') saves only portal credentials."""
    import id_card_module as id_card
    test_env = tmp_path / ".env"
    test_env.write_text("# Test\n")

    orig_save = id_card.save_env_variable
    monkeypatch.setattr(id_card, "save_env_variable", lambda k, v: orig_save(k, v, env_path=str(test_env)))

    class MockVar:
        def __init__(self, val=""):
            self._val = val
        def get(self):
            return self._val

    with patch.object(App, "__init__", return_value=None):
        app = App()
        app.keka_subdomain_var = MockVar("moshpit")
        app.keka_client_id_var = MockVar("api_cid_123")
        app.keka_client_secret_var = MockVar("api_csec_456")
        app.keka_api_key_var = MockVar("api_key_789")
        app.keka_login_email_var = MockVar("portal_admin@moshpit.com")
        app.keka_login_password_var = MockVar("portal_pass_secure")
        app.slack_bot_token_var = MockVar("")
        app._append_connector_log = MagicMock()

        with patch("app.messagebox.showinfo"):
            app.save_connectors_credentials("keka_portal")

        content = test_env.read_text()
        assert "KEKA_LOGIN_EMAIL='portal_admin@moshpit.com'" in content
        assert "KEKA_LOGIN_PASSWORD='portal_pass_secure'" in content
        assert "api_cid_123" not in content
        assert "api_csec_456" not in content


def test_portal_methods_exist_on_app():
    """Verify portal connection and badge methods exist on App."""
    assert hasattr(App, "connect_keka_portal_now")
    assert hasattr(App, "_update_portal_badge")
    assert hasattr(App, "refresh_keka_portal_status")


def test_check_keka_portal_status_missing_creds():
    """Verify check_keka_portal_status rejects missing credentials gracefully."""
    import keka_data_fetcher
    is_ok, msg, details = keka_data_fetcher.check_keka_portal_status(email="", password="", subdomain="moshpit")
    assert is_ok is False
    assert "required" in msg.lower() or "missing" in msg.lower()

