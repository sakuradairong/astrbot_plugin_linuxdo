import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from linuxdo_preview.auth import AuthState
from linuxdo_preview.cookie_session import SessionMetadata


class TestCookieSyncDecision(unittest.TestCase):
    def test_default_interval_is_two_hours(self):
        from linuxdo_preview.cookie_monitor import DEFAULT_SYNC_INTERVAL_SECONDS

        self.assertEqual(DEFAULT_SYNC_INTERVAL_SECONDS, 7200)

    def test_sync_disabled_when_config_flag_is_false(self):
        from linuxdo_preview.cookie_monitor import is_cookie_sync_due

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)

            due = is_cookie_sync_due(
                {"linuxdo_cookie_sync_enabled": False},
                data_dir,
                now=1_000,
            )

        self.assertFalse(due)

    def test_sync_due_when_session_json_is_absent(self):
        from linuxdo_preview.cookie_monitor import is_cookie_sync_due

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)

            due = is_cookie_sync_due(
                {"linuxdo_cookie_sync_enabled": True},
                data_dir,
                now=1_000,
            )

        self.assertTrue(due)

    def test_sync_due_when_updated_at_is_older_than_interval(self):
        from linuxdo_preview.cookie_monitor import is_cookie_sync_due

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_session(data_dir, updated_at="1970-01-01T00:00:00+00:00")

            due = is_cookie_sync_due(
                {
                    "linuxdo_cookie_sync_enabled": True,
                    "linuxdo_cookie_sync_interval_seconds": 7200,
                },
                data_dir,
                now=7201,
            )

        self.assertTrue(due)

    def test_sync_not_due_when_updated_at_is_fresh(self):
        from linuxdo_preview.cookie_monitor import is_cookie_sync_due

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_session(data_dir, updated_at="1970-01-01T01:00:00+00:00")

            due = is_cookie_sync_due(
                {
                    "linuxdo_cookie_sync_enabled": True,
                    "linuxdo_cookie_sync_interval_seconds": 7200,
                },
                data_dir,
                now=7201,
            )

        self.assertFalse(due)


class TestCookieSyncRun(unittest.TestCase):
    def test_sync_failures_are_non_fatal_and_redacted(self):
        from linuxdo_preview.cookie_monitor import sync_cookie_if_due

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            auth_state = AuthState(auth_check_done=True, logged_in=True)

            with patch(
                "linuxdo_preview.cookie_monitor.cookie_store.extract_cookie_header",
                side_effect=RuntimeError("bad cookie secret-token"),
            ):
                result = sync_cookie_if_due(
                    {
                        "linuxdo_cookie_sync_enabled": True,
                        "linuxdo_firefox_profile_path": "/local/profile",
                        "linuxdo_cookie_encryption_key": "test-key",
                    },
                    data_dir,
                    auth_state,
                    now=1_000,
                )

        self.assertTrue(result.attempted)
        self.assertFalse(result.ok)
        self.assertEqual(result.category, "unexpected_error")
        self.assertIn("RuntimeError", result.message)
        self.assertNotIn("secret-token", result.message)
        self.assertTrue(auth_state.auth_check_done)

    def test_successful_sync_pulls_local_cookie_resets_auth_and_keeps_values_secret(self):
        from linuxdo_preview.cookie_monitor import sync_cookie_if_due

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            auth_state = AuthState(auth_check_done=True, logged_in=True)

            with patch(
                "linuxdo_preview.cookie_monitor.cookie_store.extract_cookie_header",
                return_value="_t=secret-token; _forum_session=secret-session",
            ) as extract_cookie_header:
                result = sync_cookie_if_due(
                    {
                        "linuxdo_cookie_sync_enabled": True,
                        "linuxdo_firefox_profile_path": "/local/profile",
                        "linuxdo_cookie_encryption_key": "test-key",
                    },
                    data_dir,
                    auth_state,
                    now=1_000,
                )

        self.assertTrue(result.attempted)
        self.assertTrue(result.ok)
        extract_cookie_header.assert_called_once_with("/local/profile", data_dir, "test-key")
        self.assertFalse(auth_state.auth_check_done)
        self.assertFalse(auth_state.logged_in)
        self.assertNotIn("secret-token", result.message)
        self.assertNotIn("secret-session", result.message)

    def test_restricted_topic_verification_injects_candidate_cookie_and_marks_success(self):
        from linuxdo_preview.cookie_monitor import sync_cookie_if_due

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            auth_state = AuthState(auth_check_done=True, logged_in=True)
            session = _VerificationSession(status=200)

            with patch(
                "linuxdo_preview.cookie_monitor.cookie_store.extract_cookie_header",
                return_value="_t=secret-token",
            ), patch("linuxdo_preview.cookie_monitor.cookie_store.load_session", return_value=_session_metadata()):
                result = sync_cookie_if_due(
                    {
                        "linuxdo_cookie_sync_enabled": True,
                        "linuxdo_firefox_profile_path": "/local/profile",
                        "linuxdo_cookie_encryption_key": "test-key",
                        "linuxdo_restricted_topic_url": "https://linux.do/t/restricted/1",
                    },
                    data_dir,
                    auth_state,
                    session=session,
                    now=1_000,
                )

        self.assertTrue(result.ok)
        self.assertEqual(session.cookie_names, ["_t"])
        self.assertEqual(session.fetched_urls, ["https://linux.do/t/restricted/1"])
        self.assertTrue(result.verified)
        self.assertEqual(result.verification_url, "https://linux.do/t/restricted/1")

    def test_restricted_topic_verification_skips_unsafe_urls(self):
        from linuxdo_preview.cookie_monitor import sync_cookie_if_due

        cases = ["https://example.com/capture", "http://linux.do/t/restricted/1"]
        for url in cases:
            with self.subTest(url=url), tempfile.TemporaryDirectory() as tmp:
                # Given: verification is configured with an unsafe URL.
                data_dir = Path(tmp)
                auth_state = AuthState(auth_check_done=True, logged_in=True)
                session = _VerificationSession(status=200)

                # When: the cookie sync runs with a candidate Cookie header.
                with patch(
                    "linuxdo_preview.cookie_monitor.cookie_store.extract_cookie_header",
                    return_value="_t=secret-token",
                ), patch("linuxdo_preview.cookie_monitor.cookie_store.load_session", return_value=_session_metadata()):
                    result = sync_cookie_if_due(
                        {
                            "linuxdo_cookie_sync_enabled": True,
                            "linuxdo_firefox_profile_path": "/local/profile",
                            "linuxdo_cookie_encryption_key": "test-key",
                            "linuxdo_restricted_topic_url": url,
                        },
                        data_dir,
                        auth_state,
                        session=session,
                        now=1_000,
                    )

                # Then: verification is not attempted against the unsafe URL.
                self.assertTrue(result.ok)
                self.assertFalse(result.verified)
                self.assertEqual(result.verification_url, url)
                self.assertEqual(session.cookie_names, [])
                self.assertEqual(session.fetched_urls, [])


class _VerificationContext:
    def __init__(self) -> None:
        self.cookie_names: list[str] = []

    def add_cookies(self, cookies: list[dict[str, str | bool]]) -> None:
        self.cookie_names.extend(str(cookie["name"]) for cookie in cookies)


class _VerificationResponse:
    status: int

    def __init__(self, status: int) -> None:
        self.status = status


class _VerificationSession:
    context: _VerificationContext
    status: int

    def __init__(self, status: int) -> None:
        self.context = _VerificationContext()
        self.status = status
        self.fetched_urls: list[str] = []
        self.last_timeout: int | None = None

    @property
    def cookie_names(self) -> list[str]:
        return self.context.cookie_names

    def fetch(self, url: str, timeout: int) -> _VerificationResponse:
        self.fetched_urls.append(url)
        self.last_timeout = timeout
        return _VerificationResponse(self.status)


def _session_metadata(updated_at: str | None = None) -> SessionMetadata:
    return {
        "encrypted_cookie": "encrypted",
        "cookie_count": 1,
        "names": ["_t"],
        "updated_at": updated_at,
        "source": "unit-test",
        "verified": False,
        "verified_at": None,
        "verification_url": None,
        "last_error": None,
    }


def _write_session(data_dir: Path, updated_at: str | None) -> None:
    from linuxdo_preview.cookie_session import write_session

    write_session(data_dir, _session_metadata(updated_at))


if __name__ == "__main__":
    _ = unittest.main()
