import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
import re

from . import cookie_store


_COOKIE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


def _manual_cookie(config: Mapping[str, object]) -> str:
    value = config.get("linuxdo_session_cookie", "")
    return value.strip() if isinstance(value, str) else ""


def _config_text(config: Mapping[str, object], key: str) -> str:
    value = config.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def _cookie_names(cookie_header: str) -> list[str]:
    names: list[str] = []
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        name = part.split("=", 1)[0].strip()
        if _COOKIE_NAME_RE.match(name):
            names.append(name)
    return names


def _error_category(error: str | None) -> str:
    if not error:
        return "无"
    lowered = error.lower()
    if "decrypt" in lowered or "decryption" in lowered or "解密" in error:
        return "解密失败"
    if "not found" in lowered or "未找到" in error:
        return "未找到 Cookie"
    if "cryptography" in lowered or "加密" in error:
        return "加密依赖"
    return "其他错误"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _verification_status(session: Mapping[str, object]) -> str:
    if session.get("verified"):
        return "已通过"
    if session.get("verified_at") or session.get("verification_url") or session.get("last_error"):
        return "未通过"
    return "未验证"


def cookie_status_text(config: Mapping[str, object], data_dir: Path) -> str:
    session = cookie_store.load_session(data_dir)
    manual_cookie = _manual_cookie(config)
    if session is None:
        return (
            "🍪 LinuxDo Cookie 状态\n"
            "  已保存加密会话: 不存在\n"
            f"  手动 Cookie 兜底: {'已配置' if manual_cookie else '未配置'}"
        )

    names = session.get("names", [])
    cookie_names = ", ".join(names) if names else "无"
    verified = _verification_status(session)
    return (
        "🍪 LinuxDo Cookie 状态\n"
        "  已保存加密会话: 已存在\n"
        f"  Cookie 数量: {session.get('cookie_count', 0)}\n"
        f"  Cookie 名称: {cookie_names}\n"
        f"  更新时间: {session.get('updated_at') or '未知'}\n"
        f"  验证状态: {verified}\n"
        f"  验证时间: {session.get('verified_at') or '未记录'}\n"
        f"  错误类别: {_error_category(session.get('last_error'))}\n"
        f"  手动 Cookie 兜底: {'已配置' if manual_cookie else '未配置'}"
    )


def pull_cookie_session_text(config: Mapping[str, object], data_dir: Path) -> tuple[bool, str]:
    profile_path = _config_text(config, "linuxdo_firefox_profile_path")
    if not profile_path:
        return False, "❌ 请先配置 linuxdo_firefox_profile_path（本地 Firefox profile 或 cookies.sqlite 路径）"

    encryption_key = _config_text(config, "linuxdo_cookie_encryption_key")
    if not encryption_key:
        return False, "❌ 请先配置 linuxdo_cookie_encryption_key 后再拉取并加密保存 Cookie"

    try:
        header = cookie_store.extract_cookie_header(profile_path, data_dir, encryption_key)
        cookie_store.update_session_metadata(data_dir, updated_at=_iso_now())
    except cookie_store.CookieNotFoundError:
        return False, "❌ Cookie 拉取失败：未找到 linux.do Cookie，请确认本地 profile/cookies.sqlite 已登录 linux.do"
    except cookie_store.CookieEncryptionError:
        return False, "❌ Cookie 拉取失败：加密依赖不可用或密钥无法使用，请安装 cryptography 并检查配置"
    except cookie_store.CookieStoreError:
        return False, "❌ Cookie 拉取失败：本地 Cookie 存储不可读取，请检查路径与文件权限"
    except (OSError, sqlite3.Error) as e:
        return False, f"❌ Cookie 拉取失败：本地 Cookie 拉取发生意外错误（{type(e).__name__}）"

    names_list = _cookie_names(header)
    names = ", ".join(names_list) if names_list else "无"
    return True, (
        "✅ Cookie 拉取成功，已加密保存本地会话\n"
        f"  Cookie 数量: {len(names_list)}\n"
        f"  Cookie 名称: {names}\n"
        "  提示: 已重置登录验证状态，下次预览会重新验证"
    )
