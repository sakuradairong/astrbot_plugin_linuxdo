from collections.abc import Mapping
import json
from pathlib import Path
from typing import TypedDict


class CookieStoreError(Exception): pass


class CookieNotFoundError(CookieStoreError): pass


class CookieEncryptionError(CookieStoreError): pass


class CookieRecord(TypedDict):
    name: str
    value: str
    host: str


class SessionMetadata(TypedDict):
    encrypted_cookie: str
    cookie_count: int
    names: list[str]
    updated_at: str | None
    source: str | None
    verified: bool
    verified_at: str | None
    verification_url: str | None
    last_error: str | None


def _invalid_metadata() -> CookieStoreError:
    return CookieStoreError("session.json has invalid metadata")


def _string_value(session: Mapping[str, object], key: str) -> str:
    value = session.get(key)
    if isinstance(value, str):
        return value
    raise _invalid_metadata()


def _optional_string_value(session: Mapping[str, object], key: str) -> str | None:
    value = session.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise _invalid_metadata()


def _int_value(session: Mapping[str, object], key: str) -> int:
    value = session.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise _invalid_metadata()


def _bool_value(session: Mapping[str, object], key: str) -> bool:
    value = session.get(key)
    if isinstance(value, bool):
        return value
    raise _invalid_metadata()


def _string_list_value(session: Mapping[str, object], key: str) -> list[str]:
    value = session.get(key)
    if not isinstance(value, list):
        raise _invalid_metadata()
    names: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise _invalid_metadata()
        names.append(item)
    return names


def _json_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    return {key: value for key, value in pairs}


def _loads_json_object(text: str) -> object:
    return json.loads(text, object_pairs_hook=_json_object_pairs)


def _session_from_json(text: str) -> SessionMetadata:
    loaded = _loads_json_object(text)
    if not isinstance(loaded, dict):
        raise _invalid_metadata()
    session: dict[str, object] = {}
    for key, value in loaded.items():
        if not isinstance(key, str):
            raise _invalid_metadata()
        session[key] = value
    return {
        "encrypted_cookie": _string_value(session, "encrypted_cookie"),
        "cookie_count": _int_value(session, "cookie_count"),
        "names": _string_list_value(session, "names"),
        "updated_at": _optional_string_value(session, "updated_at"),
        "source": _optional_string_value(session, "source"),
        "verified": _bool_value(session, "verified"),
        "verified_at": _optional_string_value(session, "verified_at"),
        "verification_url": _optional_string_value(session, "verification_url"),
        "last_error": _optional_string_value(session, "last_error"),
    }


def load_session(data_dir: Path) -> SessionMetadata | None:
    session_path = data_dir / "session.json"
    if not session_path.exists():
        return None
    try:
        with session_path.open("r", encoding="utf-8") as f:
            session = _session_from_json(f.read())
    except OSError as exc:
        raise CookieStoreError("failed to read session.json") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise CookieStoreError("failed to parse session.json") from exc
    return session


def write_session(data_dir: Path, session: SessionMetadata) -> None:
    _ = data_dir.mkdir(parents=True, exist_ok=True)
    session_path = data_dir / "session.json"
    with session_path.open("w", encoding="utf-8") as f:
        _ = json.dump(session, f, ensure_ascii=False, indent=2)
