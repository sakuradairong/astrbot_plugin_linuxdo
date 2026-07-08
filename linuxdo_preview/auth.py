from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from types import TracebackType
from typing import Protocol

from . import cookie_store


@dataclass(slots=True)
class AuthState:
    auth_check_done: bool = False
    logged_in: bool = False


@dataclass(frozen=True, slots=True)
class _ResolvedCookie:
    value: str
    source: str


class _Logger(Protocol):
    def info(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...


class _CookieContext(Protocol):
    def add_cookies(self, cookies: list[dict[str, str | bool]]) -> None: ...


class _FetchResponse(Protocol):
    status: int


class _CookieSession(Protocol):
    @property
    def context(self) -> _CookieContext | None: ...


class _FetchSession(Protocol):
    @property
    def context(self) -> _CookieContext | None: ...

    def fetch(self, url: str, timeout: int) -> _FetchResponse: ...


class _AuthLock(Protocol):
    def __enter__(self) -> bool | None: ...

    def __exit__(
        self,
        type: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


_COOKIE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_KNOWN_COOKIE_NAMES = {
    "_t", "_forum_session", "cf_clearance", "_bypass_cache", "dosp",
    "_pf", "_bblean", "theme_ids", "previousVisitAt", "messages-last-modified",
    "_ga", "_gid", "_gcl_au",
}


def _manual_session_cookie(config: Mapping[str, str]) -> str:
    return (config.get("linuxdo_session_cookie", "") or "").strip()


def _resolve_session_cookie(config: Mapping[str, str], data_dir: Path | None = None) -> _ResolvedCookie:
    if data_dir is not None:
        encryption_key = config.get("linuxdo_cookie_encryption_key", "") or None
        try:
            stored_cookie = cookie_store.get_cookie_header_from_session(data_dir, encryption_key)
        except cookie_store.CookieStoreError:
            stored_cookie = None
        if stored_cookie and stored_cookie.strip():
            return _ResolvedCookie(stored_cookie.strip(), "已保存会话")
    manual_cookie = _manual_session_cookie(config)
    if manual_cookie:
        return _ResolvedCookie(manual_cookie, "手动配置")
    return _ResolvedCookie("", "无")


def _has_session_cookie(config: Mapping[str, str], data_dir: Path | None = None) -> bool:
    return bool(_resolve_session_cookie(config, data_dir).value)


def _has_auto_login(config: Mapping[str, str]) -> bool:
    u = config.get("linuxdo_username", "") or ""
    p = config.get("linuxdo_password", "") or ""
    return bool(u.strip() and p.strip())


def _parse_cookie_pairs(cookie_str: str) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    s = (cookie_str or "").strip()
    if not s:
        return pairs
    if ";" in s:
        for part in s.split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name = name.strip()
            if _COOKIE_NAME_RE.match(name):
                pairs.append({"name": name, "value": value.strip()})
    elif "=" in s:
        name, value = s.split("=", 1)
        name = name.strip()
        if name in _KNOWN_COOKIE_NAMES and _COOKIE_NAME_RE.match(name):
            pairs.append({"name": name, "value": value.strip()})
    if not pairs:
        pairs.append({"name": "_forum_session", "value": s})
    return pairs


def _auth_status_text(
    config: Mapping[str, str],
    auth_state: AuthState,
    data_dir: Path | None = None,
) -> str:
    resolved_cookie = _resolve_session_cookie(config, data_dir)
    cookie_pairs = _parse_cookie_pairs(resolved_cookie.value)
    cookie_names = ", ".join(pair["name"] for pair in cookie_pairs) if cookie_pairs else "无"
    if not cookie_pairs:
        login_status = "匿名"
    elif not auth_state.auth_check_done:
        login_status = "未验证"
    elif auth_state.logged_in:
        login_status = "已验证"
    else:
        login_status = "无效或已过期"
    return (
        "🔐 LinuxDo Preview 认证状态\n"
        f"  Cookie: {'已配置' if cookie_pairs else '未配置'}\n"
        f"  Cookie 来源: {resolved_cookie.source}\n"
        f"  Cookie 名称: {cookie_names}\n"
        f"  登录状态: {login_status}\n"
        "  提示: 若失效，请重新复制 linux.do 请求里的完整 Cookie 值"
    )


def _inject_session_cookie(
    session: _CookieSession,
    config: Mapping[str, str],
    logger: _Logger,
    cookie_value: str = "",
    data_dir: Path | None = None,
) -> bool:
    if not cookie_value:
        cookie_value = _resolve_session_cookie(config, data_dir).value
    if not cookie_value:
        return False

    ctx = session.context
    if not ctx:
        return False

    pairs = _parse_cookie_pairs(cookie_value)
    if not pairs:
        return False

    cookies: list[dict[str, str | bool]] = []
    for p in pairs:
        http_only = p["name"] in ("_t", "_forum_session")
        cookies.append({
            "name": p["name"],
            "value": p["value"],
            "domain": "linux.do",
            "path": "/",
            "httpOnly": http_only,
            "secure": True,
            "sameSite": "Lax",
        })

    try:
        ctx.add_cookies(cookies)
        logger.info(
            f"[LinuxDoPreview] 已注入会话 cookie: {[c['name'] for c in cookies]}"
        )
        return True
    except Exception as e:
        logger.warning(f"[LinuxDoPreview] Cookie 注入失败: {type(e).__name__}")
        return False


def _check_login_state(session: _FetchSession) -> bool:
    try:
        resp = session.fetch("https://linux.do/notifications.json", timeout=30000)
        return resp.status == 200
    except Exception:
        return False


def _ensure_authenticated(
    session: _FetchSession,
    config: Mapping[str, str],
    auth_state: AuthState,
    auth_lock: _AuthLock,
    logger: _Logger,
    data_dir: Path | None = None,
) -> bool:
    with auth_lock:
        if _has_session_cookie(config, data_dir):
            if not _inject_session_cookie(session, config, logger, data_dir=data_dir):
                auth_state.auth_check_done = True
                auth_state.logged_in = False
                return False
            if not auth_state.auth_check_done:
                auth_state.logged_in = _check_login_state(session)
                auth_state.auth_check_done = True
                if auth_state.logged_in:
                    logger.info("[LinuxDoPreview] Cookie 登录验证成功")
                else:
                    logger.warning(
                        "[LinuxDoPreview] 会话 Cookie 无效或已过期，将匿名访问。"
                        + "请在浏览器重新复制 linux.do 的完整 Cookie 请求头后填入配置。"
                    )
            return auth_state.logged_in

        if _has_auto_login(config) and not auth_state.auth_check_done:
            auth_state.auth_check_done = True
            logger.warning(
                "[LinuxDoPreview] linux.do 登录启用了 hCaptcha 人机验证，账号密码"
                + "自动登录不可用。请在浏览器登录 linux.do 后，F12 → Network → "
                + "刷新页面 → 复制 linux.do 请求里的完整 Cookie 值，填入 "
                + "linuxdo_session_cookie 配置项。本次降级为匿名访问。"
            )

        auth_state.logged_in = False
        return False
