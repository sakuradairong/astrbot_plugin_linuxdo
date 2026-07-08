import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from linuxdo_preview.auth import AuthState
from linuxdo_preview.auth import _auth_status_text
from linuxdo_preview.auth import _has_session_cookie
from linuxdo_preview.auth import _inject_session_cookie
from linuxdo_preview.cookie_store import CookieEncryptionError


STORED_COOKIE = "_t=stored-token-synthetic; _forum_session=stored-session-synthetic"
MANUAL_COOKIE = "_t=manual-token-synthetic; _forum_session=manual-session-synthetic"
SESSION_KEY = "synthetic-session-key"


class _CookieContext:
    def __init__(self) -> None:
        self.cookies: list[dict[str, str | bool]] = []

    def add_cookies(self, cookies: list[dict[str, str | bool]]) -> None:
        self.cookies.extend(cookies)


class _FailingCookieContext:
    def add_cookies(self, cookies: list[dict[str, str | bool]]) -> None:
        _ = cookies
        raise RuntimeError("browser rejected stored-token-synthetic")


class _Session:
    context: _CookieContext

    def __init__(self) -> None:
        self.context = _CookieContext()


class _FailingSession:
    context: _FailingCookieContext

    def __init__(self) -> None:
        self.context = _FailingCookieContext()


class _Logger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)

    def warning(self, message: str) -> None:
        self.messages.append(message)


class TestAuthCookieSources(unittest.TestCase):
    def test_inject_session_cookie_prefers_decryptable_stored_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Given: both an encrypted stored session and a manual config cookie exist.
            data_dir = Path(tmp)
            config = {
                "linuxdo_session_cookie": MANUAL_COOKIE,
                "linuxdo_cookie_encryption_key": SESSION_KEY,
            }
            session = _Session()
            logger = _Logger()

            # When: auth injects cookies for linux.do.
            with patch(
                "linuxdo_preview.auth.cookie_store.get_cookie_header_from_session",
                return_value=STORED_COOKIE,
            ) as get_cookie_header:
                injected = _inject_session_cookie(session, config, logger, data_dir=data_dir)

            # Then: the stored cookie is used before the manual fallback.
            self.assertTrue(injected)
            get_cookie_header.assert_called_once_with(data_dir, SESSION_KEY)
            cookie_values = [cookie["value"] for cookie in session.context.cookies]
            self.assertIn("stored-token-synthetic", cookie_values)
            self.assertIn("stored-session-synthetic", cookie_values)
            self.assertNotIn("manual-token-synthetic", cookie_values)
            self.assertNotIn("manual-session-synthetic", cookie_values)
            self.assertFalse(any("stored-token-synthetic" in message for message in logger.messages))

    def test_inject_session_cookie_falls_back_to_manual_when_session_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Given: no stored session is available, but manual config has a cookie.
            data_dir = Path(tmp)
            config = {
                "linuxdo_session_cookie": MANUAL_COOKIE,
                "linuxdo_cookie_encryption_key": SESSION_KEY,
            }
            session = _Session()

            # When: auth resolves the cookie source.
            with patch(
                "linuxdo_preview.auth.cookie_store.get_cookie_header_from_session",
                return_value=None,
            ):
                injected = _inject_session_cookie(session, config, _Logger(), data_dir=data_dir)

            # Then: the manual config cookie is injected.
            self.assertTrue(injected)
            cookie_values = [cookie["value"] for cookie in session.context.cookies]
            self.assertIn("manual-token-synthetic", cookie_values)
            self.assertIn("manual-session-synthetic", cookie_values)

    def test_inject_session_cookie_falls_back_to_manual_when_stored_decrypt_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Given: a stored encrypted session exists but cannot be decrypted.
            data_dir = Path(tmp)
            config = {"linuxdo_session_cookie": MANUAL_COOKIE}
            session = _Session()

            # When: storage raises a sanitized encryption error.
            with patch(
                "linuxdo_preview.auth.cookie_store.get_cookie_header_from_session",
                side_effect=CookieEncryptionError("session is encrypted but no key provided"),
            ):
                injected = _inject_session_cookie(session, config, _Logger(), data_dir=data_dir)

            # Then: the manual cookie remains the safe fallback.
            self.assertTrue(injected)
            cookie_values = [cookie["value"] for cookie in session.context.cookies]
            self.assertIn("manual-token-synthetic", cookie_values)
            self.assertIn("manual-session-synthetic", cookie_values)

    def test_inject_session_cookie_redacts_browser_injection_error_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Given: the browser context raises an exception whose text contains a cookie value.
            data_dir = Path(tmp)
            config = {"linuxdo_session_cookie": MANUAL_COOKIE}
            logger = _Logger()

            # When: cookie injection fails at the browser boundary.
            injected = _inject_session_cookie(
                _FailingSession(),
                config,
                logger,
                data_dir=data_dir,
            )

            # Then: the log contains only a sanitized error class, never the exception text.
            self.assertFalse(injected)
            joined_logs = "\n".join(logger.messages)
            self.assertIn("RuntimeError", joined_logs)
            self.assertNotIn("stored-token-synthetic", joined_logs)
            self.assertNotIn("manual-token-synthetic", joined_logs)

    def test_has_session_cookie_checks_decryptable_stored_session_or_manual_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Given: a plugin data dir and either stored or manual cookie source.
            data_dir = Path(tmp)
            config = {"linuxdo_cookie_encryption_key": SESSION_KEY}

            # When / Then: a decryptable stored session is enough for auth availability.
            with patch(
                "linuxdo_preview.auth.cookie_store.get_cookie_header_from_session",
                return_value=STORED_COOKIE,
            ):
                self.assertTrue(_has_session_cookie(config, data_dir=data_dir))

            # When / Then: manual config is still enough when no stored session exists.
            with patch(
                "linuxdo_preview.auth.cookie_store.get_cookie_header_from_session",
                return_value=None,
            ):
                self.assertTrue(
                    _has_session_cookie(
                        {"linuxdo_session_cookie": MANUAL_COOKIE},
                        data_dir=data_dir,
                    )
                )

    def test_auth_status_text_reports_source_and_redacts_cookie_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Given: a stored cookie wins over a manual config cookie.
            data_dir = Path(tmp)
            config = {
                "linuxdo_session_cookie": MANUAL_COOKIE,
                "linuxdo_cookie_encryption_key": SESSION_KEY,
            }
            auth_state = AuthState(auth_check_done=False, logged_in=False)

            # When: the user asks for auth status.
            with patch(
                "linuxdo_preview.auth.cookie_store.get_cookie_header_from_session",
                return_value=STORED_COOKIE,
            ):
                status = _auth_status_text(config, auth_state, data_dir=data_dir)

            # Then: only cookie names and source are reported, never cookie values.
            self.assertIn("Cookie: 已配置", status)
            self.assertIn("Cookie 来源: 已保存会话", status)
            self.assertIn("_t", status)
            self.assertIn("_forum_session", status)
            self.assertIn("登录状态: 未验证", status)
            self.assertNotIn("stored-token-synthetic", status)
            self.assertNotIn("stored-session-synthetic", status)
            self.assertNotIn("manual-token-synthetic", status)
            self.assertNotIn("manual-session-synthetic", status)


if __name__ == "__main__":
    _ = unittest.main()
