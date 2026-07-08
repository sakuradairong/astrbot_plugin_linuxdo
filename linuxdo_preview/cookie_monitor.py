from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from . import cookie_store
from .auth import AuthState

DEFAULT_SYNC_INTERVAL_SECONDS = 7200
_VERIFICATION_TIMEOUT_MS = 30000


@dataclass(frozen=True, slots=True)
class CookieSyncResult:
    attempted: bool
    ok: bool
    category: str
    message: str
    verified: bool | None = None
    verification_url: str | None = None


class _FetchResponse(Protocol):
    status: int


class _CookieContext(Protocol):
    def add_cookies(self, cookies: list[dict[str, str | bool]]) -> None: ...


class _VerificationSession(Protocol):
    @property
    def context(self) -> _CookieContext | None: ...

    def fetch(self, url: str, timeout: int) -> _FetchResponse: ...


def is_cookie_sync_due(config: Mapping[str, object], data_dir: Path, *, now: float | None = None) -> bool:
    if not bool(config.get("linuxdo_cookie_sync_enabled", False)):
        return False
    session = cookie_store.load_session(data_dir)
    if session is None:
        return True
    updated_at = session.get("updated_at")
    if not updated_at:
        return True
    updated_ts = _parse_timestamp(updated_at)
    if updated_ts is None:
        return True
    interval = _sync_interval(config)
    current_ts = now if now is not None else datetime.now(UTC).timestamp()
    return current_ts - updated_ts >= interval


def sync_cookie_if_due(
    config: Mapping[str, object],
    data_dir: Path,
    auth_state: AuthState,
    *,
    session: _VerificationSession | None = None,
    now: float | None = None,
) -> CookieSyncResult:
    if not is_cookie_sync_due(config, data_dir, now=now):
        return CookieSyncResult(False, True, "not_due", "Cookie sync not due")
    profile_path = _config_text(config, "linuxdo_firefox_profile_path")
    encryption_key = _config_text(config, "linuxdo_cookie_encryption_key")
    if not profile_path:
        return CookieSyncResult(True, False, "missing_profile_path", "linuxdo_firefox_profile_path is not configured")
    if not encryption_key:
        return CookieSyncResult(True, False, "missing_encryption_key", "linuxdo_cookie_encryption_key is not configured")

    synced_at = _iso_now(now)
    try:
        cookie_header = cookie_store.extract_cookie_header(profile_path, data_dir, encryption_key)
        verification = _verify_restricted_topic(config, session, cookie_header, synced_at)
        cookie_store.update_session_metadata(
            data_dir,
            updated_at=synced_at,
            verified=verification.verified,
            verified_at=verification.verified_at,
            verification_url=verification.url,
            last_error=verification.last_error,
        )
    except cookie_store.CookieNotFoundError:
        return CookieSyncResult(True, False, "cookie_not_found", "linux.do cookies were not found")
    except cookie_store.CookieEncryptionError:
        return CookieSyncResult(True, False, "encryption_error", "encrypted cookie storage is unavailable")
    except cookie_store.CookieStoreError:
        return CookieSyncResult(True, False, "cookie_store_error", "local cookie storage could not be read")
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - sync is preview-time best effort.
        return CookieSyncResult(True, False, "unexpected_error", f"{type(exc).__name__}: cookie sync failed")

    auth_state.auth_check_done = False
    auth_state.logged_in = False
    return CookieSyncResult(
        True,
        True,
        "synced",
        "Cookie sync completed; values are redacted",
        verification.verified,
        verification.url,
    )


@dataclass(frozen=True, slots=True)
class _VerificationResult:
    verified: bool
    verified_at: str | None
    url: str | None
    last_error: str | None


def _verify_restricted_topic(
    config: Mapping[str, object],
    session: _VerificationSession | None,
    cookie_header: str,
    synced_at: str,
) -> _VerificationResult:
    url = _config_text(config, "linuxdo_restricted_topic_url")
    if not url:
        return _VerificationResult(False, None, None, None)
    if not _is_linuxdo_url(url):
        return _VerificationResult(False, None, url, "verification skipped: non-linux.do URL")
    if session is None:
        return _VerificationResult(False, None, url, "verification skipped: no preview session")
    try:
        if not _inject_cookie_header(session, cookie_header):
            return _VerificationResult(False, None, url, "verification failed: cookie injection")
        response = session.fetch(url, timeout=_VERIFICATION_TIMEOUT_MS)
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - verification is best effort and redacted.
        return _VerificationResult(False, None, url, f"verification failed: {type(exc).__name__}")
    if response.status == 200:
        return _VerificationResult(True, synced_at, url, None)
    return _VerificationResult(False, None, url, f"verification failed: HTTP {response.status}")


def _config_text(config: Mapping[str, object], key: str) -> str:
    value = config.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def _is_linuxdo_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "linux.do" or host.endswith(".linux.do"))


def _inject_cookie_header(session: _VerificationSession, cookie_header: str) -> bool:
    context = session.context
    if context is None:
        return False
    cookies: list[dict[str, str | bool]] = []
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookie_name = name.strip()
        if not cookie_name:
            continue
        cookies.append(
            {
                "name": cookie_name,
                "value": value.strip(),
                "domain": "linux.do",
                "path": "/",
                "httpOnly": cookie_name in ("_t", "_forum_session"),
                "secure": True,
                "sameSite": "Lax",
            }
        )
    if not cookies:
        return False
    context.add_cookies(cookies)
    return True


def _sync_interval(config: Mapping[str, object]) -> int:
    value = config.get("linuxdo_cookie_sync_interval_seconds", DEFAULT_SYNC_INTERVAL_SECONDS)
    if isinstance(value, int) and value > 0:
        return value
    return DEFAULT_SYNC_INTERVAL_SECONDS


def _parse_timestamp(value: str) -> float | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _iso_now(now: float | None) -> str:
    if now is None:
        return datetime.now(UTC).isoformat()
    return datetime.fromtimestamp(now, UTC).isoformat()
