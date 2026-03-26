"""
tests/test_web_monitor.py
Unit tests for web_monitor.py
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, call

# Make src/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import web_monitor as wm


# ─────────────────────────────────────────────────────────────
# compute_hash
# ─────────────────────────────────────────────────────────────

class TestComputeHash:
    def test_same_input_same_hash(self):
        assert wm.compute_hash("hello") == wm.compute_hash("hello")

    def test_different_input_different_hash(self):
        assert wm.compute_hash("hello") != wm.compute_hash("world")

    def test_returns_hex_string(self):
        result = wm.compute_hash("test")
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex digest


# ─────────────────────────────────────────────────────────────
# fetch_content
# ─────────────────────────────────────────────────────────────

def _make_response(html: str, status_code: int = 200, url: str = "http://example.com"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = html
    resp.url = url
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import requests
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


def _patch_session(response):
    """Patch requests.Session so session.get() returns the given response."""
    mock_session = MagicMock()
    mock_session.get.return_value = response
    return patch("requests.Session", return_value=mock_session)


SIMPLE_HTML = "<html><body><p>Hello World</p></body></html>"
SELECTOR_HTML = '<html><body><div class="price">1000</div><div class="price">2000</div></body></html>'
NO_BODY_HTML = "<html><head><title>No body</title></head></html>"


class TestFetchContent:
    def test_returns_body_text_without_selector(self):
        with _patch_session(_make_response(SIMPLE_HTML)):
            result = wm.fetch_content("http://example.com", None, 15, {})
        assert result == "Hello World"

    def test_selector_returns_matching_elements(self):
        with _patch_session(_make_response(SELECTOR_HTML)):
            result = wm.fetch_content("http://example.com", ".price", 15, {})
        assert result == "1000\n2000"

    def test_selector_not_found_returns_none(self):
        with _patch_session(_make_response(SIMPLE_HTML)):
            result = wm.fetch_content("http://example.com", "#missing", 15, {})
        assert result is None

    def test_http_error_returns_none(self):
        with _patch_session(_make_response("", 404)):
            result = wm.fetch_content("http://example.com", None, 15, {})
        assert result is None

    def test_request_exception_returns_none(self):
        import requests
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.ConnectionError("timeout")
        with patch("requests.Session", return_value=mock_session):
            result = wm.fetch_content("http://example.com", None, 15, {})
        assert result is None

    def test_no_body_tag_falls_back_to_full_text(self):
        with _patch_session(_make_response(NO_BODY_HTML)):
            result = wm.fetch_content("http://example.com", None, 15, {})
        assert result is not None
        assert "No body" in result

    def test_cookies_loaded_into_session(self):
        mock_session = MagicMock()
        mock_session.get.return_value = _make_response(SIMPLE_HTML)
        with patch("requests.Session", return_value=mock_session):
            wm.fetch_content("http://example.com", None, 15, {}, cookies={"sid": "abc123"})
        mock_session.cookies.update.assert_called_once_with({"sid": "abc123"})

    def test_no_cookies_update_when_none(self):
        mock_session = MagicMock()
        mock_session.get.return_value = _make_response(SIMPLE_HTML)
        with patch("requests.Session", return_value=mock_session):
            wm.fetch_content("http://example.com", None, 15, {}, cookies=None)
        mock_session.cookies.update.assert_not_called()

    def test_warns_on_login_redirect_with_cookies(self):
        resp = _make_response(SIMPLE_HTML, url="http://example.com/login.php")
        mock_session = MagicMock()
        mock_session.get.return_value = resp
        with patch("requests.Session", return_value=mock_session), \
             patch.object(wm.log, "warning") as mock_warn:
            wm.fetch_content("http://example.com", None, 15, {}, cookies={"sid": "x"})
        mock_warn.assert_called_once()
        assert "로그인" in mock_warn.call_args[0][0]


# ─────────────────────────────────────────────────────────────
# load_cookies
# ─────────────────────────────────────────────────────────────

class TestLoadCookies:
    def test_parses_edit_this_cookie_format(self, tmp_path):
        import json
        cookie_file = tmp_path / "cookies.json"
        cookie_file.write_text(json.dumps([
            {"name": "session_id", "value": "abc123", "domain": "example.com"},
            {"name": "user_pref", "value": "dark", "domain": "example.com"},
        ]), encoding="utf-8")
        result = wm.load_cookies(str(cookie_file))
        assert result == {"session_id": "abc123", "user_pref": "dark"}

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            wm.load_cookies(str(tmp_path / "nonexistent.json"))

    def test_raises_on_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json", encoding="utf-8")
        with pytest.raises(Exception):
            wm.load_cookies(str(bad_file))


# ─────────────────────────────────────────────────────────────
# save_snapshot
# ─────────────────────────────────────────────────────────────

class TestSaveSnapshot:
    def test_creates_file_with_url_and_content(self, tmp_path):
        wm.save_snapshot("page content here", "http://example.com", out_dir=str(tmp_path))
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        text = files[0].read_text(encoding="utf-8")
        assert "http://example.com" in text
        assert "page content here" in text

    def test_filename_contains_timestamp(self, tmp_path):
        wm.save_snapshot("content", "http://example.com", out_dir=str(tmp_path))
        filename = list(tmp_path.iterdir())[0].name
        # Timestamp format: YYYYMMDD_HHMMSS
        import re
        assert re.match(r"\d{8}_\d{6}_", filename)

    def test_creates_directory_if_not_exists(self, tmp_path):
        out_dir = str(tmp_path / "new_snapshots")
        wm.save_snapshot("content", "http://example.com", out_dir=out_dir)
        assert os.path.isdir(out_dir)


# ─────────────────────────────────────────────────────────────
# send_notification
# ─────────────────────────────────────────────────────────────

class TestSendNotification:
    def test_uses_plyer_when_available(self):
        mock_notify = MagicMock()
        with patch.object(wm, "PLYER_AVAILABLE", True), \
             patch.object(wm.plyer_notification, "notify", mock_notify):
            wm.send_notification("Title", "Message", "http://example.com")
        mock_notify.assert_called_once()
        _, kwargs = mock_notify.call_args
        assert kwargs["title"] == "Title"
        assert kwargs["message"] == "Message"

    def test_falls_back_to_os_system_on_plyer_failure(self):
        with patch.object(wm, "PLYER_AVAILABLE", True), \
             patch.object(wm.plyer_notification, "notify", side_effect=Exception("fail")), \
             patch.object(sys, "platform", "linux"), \
             patch("os.system") as mock_os:
            wm.send_notification("Title", "Message", "http://example.com")
        mock_os.assert_called_once()
        assert "notify-send" in mock_os.call_args[0][0]

    def test_linux_notify_send_when_plyer_unavailable(self):
        with patch.object(wm, "PLYER_AVAILABLE", False), \
             patch.object(sys, "platform", "linux"), \
             patch("os.system") as mock_os:
            wm.send_notification("Title", "Message", "http://example.com")
        mock_os.assert_called_once()
        assert "notify-send" in mock_os.call_args[0][0]

    def test_macos_osascript_when_plyer_unavailable(self):
        with patch.object(wm, "PLYER_AVAILABLE", False), \
             patch.object(sys, "platform", "darwin"), \
             patch("os.system") as mock_os:
            wm.send_notification("Title", "Message", "http://example.com")
        mock_os.assert_called_once()
        assert "osascript" in mock_os.call_args[0][0]


# ─────────────────────────────────────────────────────────────
# WebMonitor.run
# ─────────────────────────────────────────────────────────────

class TestWebMonitorRun:
    """Patches time.sleep and fetch_content; breaks the infinite loop via side_effect."""

    def _make_monitor(self, **kwargs):
        defaults = dict(url="http://example.com", interval=5, selector=None)
        defaults.update(kwargs)
        return wm.WebMonitor(**defaults)

    def _run_with_contents(self, monitor, contents):
        """
        Run monitor.run() where fetch_content returns each item in `contents` in order,
        then raises StopIteration to exit the loop.
        """
        side_effects = contents + [StopIteration]

        call_iter = iter(side_effects)

        def fake_fetch(*args, **kwargs):
            val = next(call_iter)
            if val is StopIteration:
                raise StopIteration
            return val

        with patch("web_monitor.fetch_content", side_effect=fake_fetch), \
             patch("web_monitor.send_notification") as mock_notify, \
             patch("web_monitor.save_snapshot") as mock_snap, \
             patch("time.sleep"):
            try:
                monitor.run()
            except StopIteration:
                pass

        return mock_notify, mock_snap

    def test_first_run_sets_baseline_no_notification(self):
        monitor = self._make_monitor()
        mock_notify, _ = self._run_with_contents(monitor, ["page content"])
        mock_notify.assert_not_called()

    def test_no_change_no_notification(self):
        monitor = self._make_monitor()
        mock_notify, _ = self._run_with_contents(monitor, ["content", "content"])
        mock_notify.assert_not_called()

    def test_change_triggers_notification(self):
        monitor = self._make_monitor()
        mock_notify, _ = self._run_with_contents(monitor, ["old content", "new content"])
        mock_notify.assert_called_once()

    def test_change_triggers_snapshot(self):
        monitor = self._make_monitor(save_snapshots=True)
        _, mock_snap = self._run_with_contents(monitor, ["old content", "new content"])
        mock_snap.assert_called_once()

    def test_no_snapshot_when_disabled(self):
        monitor = self._make_monitor(save_snapshots=False)
        _, mock_snap = self._run_with_contents(monitor, ["old content", "new content"])
        mock_snap.assert_not_called()

    def test_fetch_failure_retries_without_crash(self):
        monitor = self._make_monitor()
        # None → fetch failed, then real content, then stop
        mock_notify, _ = self._run_with_contents(monitor, [None, "content"])
        mock_notify.assert_not_called()

    def test_multiple_changes_tracked_correctly(self):
        monitor = self._make_monitor()
        mock_notify, _ = self._run_with_contents(
            monitor, ["v1", "v2", "v2", "v3"]
        )
        assert mock_notify.call_count == 2  # v1→v2 and v2→v3

    def test_email_sent_on_change_when_configured(self):
        monitor = self._make_monitor(
            smtp_host="smtp.example.com", smtp_user="u",
            smtp_password="p", email_from="f@x.com", email_to="t@x.com"
        )
        with patch("web_monitor.fetch_content", side_effect=["old", "new", StopIteration]), \
             patch("web_monitor.send_notification"), \
             patch("web_monitor.send_email_notification") as mock_email, \
             patch("web_monitor.save_snapshot"), \
             patch("time.sleep"):
            try:
                monitor.run()
            except StopIteration:
                pass
        mock_email.assert_called_once()

    def test_no_email_when_not_configured(self):
        monitor = self._make_monitor()  # no smtp params
        with patch("web_monitor.fetch_content", side_effect=["old", "new", StopIteration]), \
             patch("web_monitor.send_notification"), \
             patch("web_monitor.send_email_notification") as mock_email, \
             patch("web_monitor.save_snapshot"), \
             patch("time.sleep"):
            try:
                monitor.run()
            except StopIteration:
                pass
        mock_email.assert_not_called()

    def test_sms_sent_on_change_when_configured(self):
        monitor = self._make_monitor(
            twilio_account_sid="AC123", twilio_auth_token="token",
            sms_from="+10000000000", sms_to="+821012345678"
        )
        with patch("web_monitor.fetch_content", side_effect=["old", "new", StopIteration]), \
             patch("web_monitor.send_notification"), \
             patch("web_monitor.send_sms_notification") as mock_sms, \
             patch("web_monitor.save_snapshot"), \
             patch("time.sleep"):
            try:
                monitor.run()
            except StopIteration:
                pass
        mock_sms.assert_called_once()

    def test_no_sms_when_not_configured(self):
        monitor = self._make_monitor()
        with patch("web_monitor.fetch_content", side_effect=["old", "new", StopIteration]), \
             patch("web_monitor.send_notification"), \
             patch("web_monitor.send_sms_notification") as mock_sms, \
             patch("web_monitor.save_snapshot"), \
             patch("time.sleep"):
            try:
                monitor.run()
            except StopIteration:
                pass
        mock_sms.assert_not_called()


# ─────────────────────────────────────────────────────────────
# send_email_notification
# ─────────────────────────────────────────────────────────────

class TestSendEmailNotification:
    def _base_kwargs(self):
        return dict(
            subject="Alert", body="body text",
            smtp_host="smtp.example.com", smtp_port=587,
            smtp_user="user@example.com", smtp_password="secret",
            email_from="user@example.com", email_to="dest@example.com",
        )

    def test_sends_email_successfully(self):
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = wm.send_email_notification(**self._base_kwargs())
        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user@example.com", "secret")
        mock_server.sendmail.assert_called_once()

    def test_returns_false_on_smtp_error(self):
        with patch("smtplib.SMTP", side_effect=Exception("connection refused")):
            result = wm.send_email_notification(**self._base_kwargs())
        assert result is False

    def test_skips_tls_when_use_tls_false(self):
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            wm.send_email_notification(**{**self._base_kwargs(), "use_tls": False})
        mock_server.starttls.assert_not_called()


# ─────────────────────────────────────────────────────────────
# send_sms_notification
# ─────────────────────────────────────────────────────────────

class TestSendSmsNotification:
    def _base_kwargs(self):
        return dict(
            body="변경 감지됨",
            twilio_account_sid="ACxxxxxxxxxxxxx",
            twilio_auth_token="auth_token_here",
            sms_from="+10000000000",
            sms_to="+821012345678",
        )

    def test_sends_sms_successfully(self):
        mock_client = MagicMock()
        with patch.object(wm, "TWILIO_AVAILABLE", True), \
             patch("web_monitor.TwilioClient", return_value=mock_client):
            result = wm.send_sms_notification(**self._base_kwargs())
        assert result is True
        mock_client.messages.create.assert_called_once_with(
            body="변경 감지됨", from_="+10000000000", to="+821012345678"
        )

    def test_returns_false_when_twilio_not_installed(self):
        with patch.object(wm, "TWILIO_AVAILABLE", False):
            result = wm.send_sms_notification(**self._base_kwargs())
        assert result is False

    def test_returns_false_on_twilio_error(self):
        with patch.object(wm, "TWILIO_AVAILABLE", True), \
             patch("web_monitor.TwilioClient", side_effect=Exception("auth failed")):
            result = wm.send_sms_notification(**self._base_kwargs())
        assert result is False


# ─────────────────────────────────────────────────────────────
# load_state / save_state
# ─────────────────────────────────────────────────────────────

class TestLoadSaveState:
    def test_load_returns_empty_dict_when_no_file(self, tmp_path):
        result = wm.load_state(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "state.json")
        data = {"hash": "abc123", "url": "http://example.com"}
        wm.save_state(path, data)
        loaded = wm.load_state(path)
        assert loaded == data


# ─────────────────────────────────────────────────────────────
# WebMonitor.run_once
# ─────────────────────────────────────────────────────────────

class TestWebMonitorRunOnce:
    def _make_monitor(self, **kwargs):
        defaults = dict(url="http://example.com", selector=None)
        defaults.update(kwargs)
        return wm.WebMonitor(**defaults)

    def _run(self, monitor, prev_hash, content, state_file="state.json"):
        state = {"hash": prev_hash} if prev_hash else {}
        with patch("web_monitor.load_state", return_value=state), \
             patch("web_monitor.save_state") as mock_save, \
             patch("web_monitor.fetch_content", return_value=content), \
             patch("web_monitor.send_notification") as mock_notify, \
             patch("web_monitor.send_email_notification") as mock_email, \
             patch("web_monitor.send_sms_notification") as mock_sms, \
             patch("web_monitor.save_snapshot") as mock_snap:
            monitor.run_once(state_file=state_file)
        return mock_save, mock_notify, mock_email, mock_snap, mock_sms

    def test_first_run_no_notification(self):
        monitor = self._make_monitor()
        _, mock_notify, mock_email, _, mock_sms = self._run(monitor, None, "content")
        mock_notify.assert_not_called()
        mock_email.assert_not_called()
        mock_sms.assert_not_called()

    def test_no_change_no_notification(self):
        monitor = self._make_monitor()
        content = "same content"
        prev_hash = wm.compute_hash(content)
        _, mock_notify, _, _, _ = self._run(monitor, prev_hash, content)
        mock_notify.assert_not_called()

    def test_change_triggers_desktop_notification(self):
        monitor = self._make_monitor()
        prev_hash = wm.compute_hash("old")
        _, mock_notify, _, _, _ = self._run(monitor, prev_hash, "new content")
        mock_notify.assert_called_once()

    def test_change_triggers_email_when_configured(self):
        monitor = self._make_monitor(
            smtp_host="smtp.example.com", smtp_user="u", smtp_password="p",
            email_from="f@x.com", email_to="t@x.com"
        )
        prev_hash = wm.compute_hash("old")
        _, _, mock_email, _, _ = self._run(monitor, prev_hash, "new content")
        mock_email.assert_called_once()

    def test_no_email_when_not_configured(self):
        monitor = self._make_monitor()
        prev_hash = wm.compute_hash("old")
        _, _, mock_email, _, _ = self._run(monitor, prev_hash, "new content")
        mock_email.assert_not_called()

    def test_change_triggers_sms_when_configured(self):
        monitor = self._make_monitor(
            twilio_account_sid="AC123", twilio_auth_token="token",
            sms_from="+10000000000", sms_to="+821012345678"
        )
        prev_hash = wm.compute_hash("old")
        _, _, _, _, mock_sms = self._run(monitor, prev_hash, "new content")
        mock_sms.assert_called_once()

    def test_no_sms_when_not_configured(self):
        monitor = self._make_monitor()
        prev_hash = wm.compute_hash("old")
        _, _, _, _, mock_sms = self._run(monitor, prev_hash, "new content")
        mock_sms.assert_not_called()

    def test_state_saved_after_run(self):
        monitor = self._make_monitor()
        mock_save, _, _, _, _ = self._run(monitor, None, "content")
        mock_save.assert_called_once()
        saved_data = mock_save.call_args[0][1]
        assert "hash" in saved_data
        assert saved_data["hash"] == wm.compute_hash("content")

    def test_exits_on_fetch_failure(self):
        monitor = self._make_monitor()
        with patch("web_monitor.load_state", return_value={}), \
             patch("web_monitor.fetch_content", return_value=None), \
             patch("web_monitor.save_state"):
            with pytest.raises(SystemExit):
                monitor.run_once()

    def test_snapshot_saved_on_change(self):
        monitor = self._make_monitor(save_snapshots=True)
        prev_hash = wm.compute_hash("old")
        _, _, _, mock_snap, _ = self._run(monitor, prev_hash, "new content")
        mock_snap.assert_called_once()
