import base64
import binascii
import hashlib
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from typing import runtime_checkable

from . import cookie_session
from .cookie_session import CookieEncryptionError as CookieEncryptionError
from .cookie_session import CookieNotFoundError as CookieNotFoundError
from .cookie_session import CookieRecord as CookieRecord
from .cookie_session import CookieStoreError as CookieStoreError
from .cookie_session import SessionMetadata as SessionMetadata


@runtime_checkable
class _AesGcm(Protocol):
    def encrypt(self, nonce: bytes, data: bytes, associated_data: None) -> bytes: ...

    def decrypt(self, nonce: bytes, data: bytes, associated_data: None) -> bytes: ...


@dataclass(frozen=True, slots=True)
class _ImportedAesGcmClass:
    constructor: object

    def __call__(self, key: bytes) -> _AesGcm:
        if not callable(self.constructor):
            raise CookieEncryptionError("cryptography AESGCM is unavailable")
        instance = self.constructor(key)
        if not isinstance(instance, _AesGcm):
            raise CookieEncryptionError("cryptography AESGCM is unavailable")
        return instance


def _derive_key(key_input: str) -> bytes:
    if not key_input:
        raise CookieEncryptionError("encryption key is empty")
    return hashlib.sha256(key_input.encode("utf-8")).digest()


def _aesgcm_class() -> _ImportedAesGcmClass:
    namespace: dict[str, object] = {}
    try:
        _ = exec(
            "from cryptography.hazmat.primitives.ciphers.aead import AESGCM\nresult = AESGCM",
            namespace,
        )
    except ImportError as exc:
        raise CookieEncryptionError("cryptography is required for encrypted cookie storage") from exc
    constructor = namespace.get("result")
    if constructor is None:
        raise CookieEncryptionError("cryptography AESGCM is unavailable")
    return _ImportedAesGcmClass(constructor)


def _invalid_tag_error() -> type[Exception]:
    namespace: dict[str, object] = {}
    try:
        _ = exec("from cryptography.exceptions import InvalidTag\nresult = InvalidTag", namespace)
    except ImportError as exc:
        raise CookieEncryptionError("cryptography is required for encrypted cookie storage") from exc
    invalid_tag = namespace.get("result")
    if not isinstance(invalid_tag, type) or not issubclass(invalid_tag, Exception):
        raise CookieEncryptionError("cryptography InvalidTag is unavailable")
    return invalid_tag


def _read_cookie_rows(db_path: Path) -> list[tuple[str, str, str, str, int, int, int, int]]:
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.cursor()
        _ = cursor.execute(
            """
            SELECT name, value, host, path, expiry, isSecure, isHttpOnly, sameSite
            FROM moz_cookies
            ORDER BY host, name
            """
        )
        rows: list[tuple[str, str, str, str, int, int, int, int]] = cursor.fetchall()
    return rows


def encrypt_cookie(value: str, key_input: str) -> str:
    key = _derive_key(key_input)
    aesgcm = _aesgcm_class()(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, value.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_cookie(token: str, key_input: str) -> str:
    key = _derive_key(key_input)
    try:
        raw = base64.b64decode(token)
    except (binascii.Error, ValueError) as exc:
        raise CookieEncryptionError("invalid encrypted cookie encoding") from exc
    if len(raw) < 28:
        raise CookieEncryptionError("encrypted cookie too short")
    nonce = raw[:12]
    ciphertext = raw[12:]
    aesgcm = _aesgcm_class()(key)
    invalid_tag = _invalid_tag_error()
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except (ValueError, invalid_tag) as exc:
        raise CookieEncryptionError("cookie decryption failed") from exc
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CookieEncryptionError("cookie decryption failed") from exc


def _is_linuxdo_host(host: str) -> bool:
    normalized = host.lstrip(".").lower()
    return normalized == "linux.do" or normalized.endswith(".linux.do")


def _cookie_sort_key(cookie: CookieRecord) -> tuple[int, str, str]:
    normalized_host = cookie["host"].lstrip(".").lower()
    host_rank = 0 if normalized_host == "linux.do" else 1
    return (host_rank, normalized_host, cookie["name"])


def _source_cookie_sqlite(source_path: str) -> Path:
    path = Path(source_path).expanduser()
    if path.is_file():
        return path
    candidate = path / "cookies.sqlite"
    if candidate.is_file():
        return candidate
    raise CookieNotFoundError(f"cookies.sqlite not found at {path}")


def _copy_sqlite_to_data_dir(source_path: str, data_dir: Path) -> Path:
    _ = data_dir.mkdir(parents=True, exist_ok=True)
    source = _source_cookie_sqlite(source_path)
    tmp_file = tempfile.NamedTemporaryFile(
        prefix="cookies_tmp_",
        suffix=".sqlite",
        dir=data_dir,
        delete=False,
    )
    tmp_file.close()
    dest = Path(tmp_file.name)
    _ = shutil.copyfile(source, dest)
    return dest


def parse_cookies_from_sqlite(db_path: Path) -> list[CookieRecord]:
    cookies: list[CookieRecord] = []
    for name, value, host, _path, _expiry, _is_secure, _is_httponly, _same_site in _read_cookie_rows(db_path):
        if _is_linuxdo_host(host):
            cookies.append(
                {
                    "name": name,
                    "value": value,
                    "host": host,
                }
            )
    return sorted(cookies, key=_cookie_sort_key)


def build_cookie_header(cookies: Sequence[CookieRecord]) -> str:
    return "; ".join(
        f"{cookie['name']}={cookie['value']}" for cookie in sorted(cookies, key=_cookie_sort_key)
    )


def load_session(data_dir: Path) -> SessionMetadata | None:
    return cookie_session.load_session(data_dir)


def save_session(
    data_dir: Path,
    cookie_header: str,
    cookies: Sequence[CookieRecord],
    encryption_key: str,
    *,
    source: str | None = None,
    verified: bool = False,
    verified_at: str | None = None,
    verification_url: str | None = None,
    last_error: str | None = None,
    updated_at: str | None = None,
) -> None:
    ordered_cookies = sorted(cookies, key=_cookie_sort_key)
    session: SessionMetadata = {
        "encrypted_cookie": encrypt_cookie(cookie_header, encryption_key),
        "cookie_count": len(ordered_cookies),
        "names": [cookie["name"] for cookie in ordered_cookies],
        "updated_at": updated_at,
        "source": source,
        "verified": verified,
        "verified_at": verified_at,
        "verification_url": verification_url,
        "last_error": last_error,
    }
    cookie_session.write_session(data_dir, session)


def update_session_metadata(
    data_dir: Path,
    *,
    updated_at: str | None = None,
    verified: bool | None = None,
    verified_at: str | None = None,
    verification_url: str | None = None,
    last_error: str | None = None,
) -> None:
    session = load_session(data_dir)
    if session is None:
        return
    if updated_at is not None:
        session["updated_at"] = updated_at
    if verified is not None:
        session["verified"] = verified
    session["verified_at"] = verified_at
    session["verification_url"] = verification_url
    session["last_error"] = last_error
    cookie_session.write_session(data_dir, session)


def extract_cookie_header(
    profile_path: str,
    data_dir: Path,
    encryption_key: str | None = None,
) -> str:
    tmp_db: Path | None = None
    try:
        tmp_db = _copy_sqlite_to_data_dir(profile_path, data_dir)
        cookies = parse_cookies_from_sqlite(tmp_db)
        if not cookies:
            raise CookieNotFoundError("no linux.do cookies found in local Firefox profile")
        header = build_cookie_header(cookies)
        if encryption_key:
            save_session(data_dir, header, cookies, encryption_key, source="firefox-cookies-sqlite")
        return header
    finally:
        if tmp_db is not None and tmp_db.exists():
            tmp_db.unlink()


def get_cookie_header_from_session(data_dir: Path, encryption_key: str | None = None) -> str | None:
    session = load_session(data_dir)
    if session is None:
        return None
    encrypted = session.get("encrypted_cookie")
    if not encrypted:
        return None
    if encryption_key is None:
        raise CookieEncryptionError("session is encrypted but no key provided")
    return decrypt_cookie(encrypted, encryption_key)
