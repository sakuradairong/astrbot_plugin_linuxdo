import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from linuxdo_preview.cookie_store import CookieEncryptionError
from linuxdo_preview.cookie_store import CookieStoreError
from linuxdo_preview.cookie_store import CookieRecord
from linuxdo_preview.cookie_store import build_cookie_header
from linuxdo_preview.cookie_store import extract_cookie_header
from linuxdo_preview.cookie_store import get_cookie_header_from_session
from linuxdo_preview.cookie_store import load_session
from linuxdo_preview.cookie_store import parse_cookies_from_sqlite
from linuxdo_preview.cookie_store import save_session
from linuxdo_preview.cookie_store import update_session_metadata


SYNTHETIC_FORUM_COOKIE = "forum-session-synthetic"
SYNTHETIC_TOKEN_COOKIE = "token-synthetic"
SYNTHETIC_CF_COOKIE = "cf-synthetic"
SYNTHETIC_IGNORED_COOKIE = "ignored-synthetic"
SESSION_KEY = "unit-test-key"
WRONG_SESSION_KEY = "wrong-unit-test-key"


class _FakeAESGCM:
    def __init__(self, key: bytes) -> None:
        self._key: bytes = key

    def encrypt(self, nonce: bytes, data: bytes, associated_data: None) -> bytes:
        _ = nonce
        _ = associated_data
        return self._key[:4] + data

    def decrypt(self, nonce: bytes, data: bytes, associated_data: None) -> bytes:
        _ = nonce
        _ = associated_data
        prefix = self._key[:4]
        if not data.startswith(prefix):
            raise ValueError("bad key")
        return data[len(prefix) :]


def _create_cookie_db(db_path: Path) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        _ = conn.execute(
            """
            CREATE TABLE moz_cookies (
                name TEXT,
                value TEXT,
                host TEXT,
                path TEXT,
                expiry INTEGER,
                isSecure INTEGER,
                isHttpOnly INTEGER,
                sameSite INTEGER
            )
            """
        )
        _ = conn.executemany(
            """
            INSERT INTO moz_cookies
            (name, value, host, path, expiry, isSecure, isHttpOnly, sameSite)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("_t", SYNTHETIC_TOKEN_COOKIE, "linux.do", "/", 200, 1, 1, 0),
                ("_forum_session", SYNTHETIC_FORUM_COOKIE, ".linux.do", "/", 100, 1, 1, 0),
                ("cf_clearance", SYNTHETIC_CF_COOKIE, "meta.linux.do", "/", 300, 1, 1, 0),
                ("_t", SYNTHETIC_IGNORED_COOKIE, "linux.do.evil.example", "/", 400, 1, 1, 0),
                ("_t", SYNTHETIC_IGNORED_COOKIE, "notlinux.do", "/", 500, 1, 1, 0),
            ],
        )


class TestFirefoxCookieExtraction(unittest.TestCase):
    def test_parse_cookies_from_sqlite_filters_linuxdo_hosts(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Given: a Firefox cookies.sqlite with linux.do, subdomain, and lookalike hosts.
            db_path = Path(tmp) / "cookies.sqlite"
            _create_cookie_db(db_path)

            # When: linux.do cookies are parsed from the database.
            cookies = parse_cookies_from_sqlite(db_path)

            # Then: only linux.do and true subdomains are returned in deterministic order.
            self.assertEqual(
                [(cookie["host"], cookie["name"]) for cookie in cookies],
                [
                    (".linux.do", "_forum_session"),
                    ("linux.do", "_t"),
                    ("meta.linux.do", "cf_clearance"),
                ],
            )
            self.assertNotIn(SYNTHETIC_IGNORED_COOKIE, [cookie["value"] for cookie in cookies])

    def test_build_cookie_header_orders_records_by_host_and_name(self):
        # Given: synthetic cookie records out of order.
        cookies: list[CookieRecord] = [
            {"host": "meta.linux.do", "name": "cf_clearance", "value": SYNTHETIC_CF_COOKIE},
            {"host": "linux.do", "name": "_t", "value": SYNTHETIC_TOKEN_COOKIE},
            {"host": ".linux.do", "name": "_forum_session", "value": SYNTHETIC_FORUM_COOKIE},
        ]

        # When: a Cookie request header is built.
        header = build_cookie_header(cookies)

        # Then: output is deterministic and contains only name=value pairs.
        self.assertEqual(
            header,
            "_forum_session=forum-session-synthetic; _t=token-synthetic; cf_clearance=cf-synthetic",
        )


class TestEncryptedCookieSession(unittest.TestCase):
    def test_save_and_load_encrypted_session_uses_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Given: a synthetic Cookie header and temp plugin data directory.
            data_dir = Path(tmp)
            header = "_t=token-synthetic; _forum_session=forum-session-synthetic"
            cookies: list[CookieRecord] = [
                {"host": "linux.do", "name": "_t", "value": SYNTHETIC_TOKEN_COOKIE},
                {"host": ".linux.do", "name": "_forum_session", "value": SYNTHETIC_FORUM_COOKIE},
            ]

            # When: the session is saved and loaded.
            with patch("linuxdo_preview.cookie_store._aesgcm_class", return_value=_FakeAESGCM):
                save_session(data_dir, header, cookies, SESSION_KEY, source="unit-test")
                session = load_session(data_dir)

            # Then: only encrypted cookie metadata is persisted, and it can be decrypted by public API.
            self.assertIsNotNone(session)
            assert session is not None
            self.assertEqual(
                set(session),
                {
                    "encrypted_cookie",
                    "cookie_count",
                    "names",
                    "updated_at",
                    "source",
                    "verified",
                    "verified_at",
                    "verification_url",
                    "last_error",
                },
            )
            self.assertEqual(session["cookie_count"], 2)
            self.assertEqual(session["names"], ["_forum_session", "_t"])
            serialized = json.dumps(session, ensure_ascii=False)
            self.assertNotIn(SYNTHETIC_TOKEN_COOKIE, serialized)
            self.assertNotIn(SYNTHETIC_FORUM_COOKIE, serialized)
            with patch("linuxdo_preview.cookie_store._aesgcm_class", return_value=_FakeAESGCM), patch(
                "linuxdo_preview.cookie_store._invalid_tag_error",
                return_value=ValueError,
            ):
                self.assertEqual(get_cookie_header_from_session(data_dir, SESSION_KEY), header)

    def test_get_cookie_header_from_session_returns_none_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Given: a temp plugin data directory with no session.json.
            data_dir = Path(tmp)

            # When / Then: loading a cookie header has no hidden fallback.
            self.assertIsNone(get_cookie_header_from_session(data_dir, SESSION_KEY))

    def test_load_session_rejects_invalid_json_with_valid_looking_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Given: a corrupted session.json that contains all expected fields.
            data_dir = Path(tmp)
            _ = data_dir.mkdir(parents=True, exist_ok=True)
            _ = (data_dir / "session.json").write_text(
                json.dumps(
                    {
                        "encrypted_cookie": "encrypted",
                        "cookie_count": 1,
                        "names": ["_t"],
                        "updated_at": None,
                        "source": "unit-test",
                        "verified": False,
                        "verified_at": None,
                        "verification_url": None,
                        "last_error": None,
                    },
                )
                + " trailing-corruption",
                encoding="utf-8",
            )

            # When / Then: the loader rejects the file instead of regex-parsing snippets.
            with self.assertRaises(CookieStoreError):
                _ = load_session(data_dir)

    def test_wrong_key_raises_without_cookie_value_in_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Given: an encrypted session containing synthetic cookie values.
            data_dir = Path(tmp)
            header = "_t=token-synthetic"
            cookies: list[CookieRecord] = [
                {"host": "linux.do", "name": "_t", "value": SYNTHETIC_TOKEN_COOKIE}
            ]
            with patch("linuxdo_preview.cookie_store._aesgcm_class", return_value=_FakeAESGCM):
                save_session(data_dir, header, cookies, SESSION_KEY, source="unit-test")

            # When / Then: decrypting with the wrong key raises a sanitized error.
            with self.assertRaises(CookieEncryptionError) as raised:
                with patch("linuxdo_preview.cookie_store._aesgcm_class", return_value=_FakeAESGCM), patch(
                    "linuxdo_preview.cookie_store._invalid_tag_error",
                    return_value=ValueError,
                ):
                    _ = get_cookie_header_from_session(data_dir, WRONG_SESSION_KEY)

            self.assertNotIn(SYNTHETIC_TOKEN_COOKIE, str(raised.exception))

    def test_extract_cookie_header_copies_local_sqlite_then_deletes_temp_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Given: a direct local cookies.sqlite path and a separate data directory.
            root = Path(tmp)
            source_db = root / "cookies.sqlite"
            data_dir = root / "plugin-data"
            _ = data_dir.mkdir()
            sentinel_tmp = data_dir / "cookies_tmp.sqlite"
            _ = sentinel_tmp.write_text("do-not-touch", encoding="utf-8")
            _create_cookie_db(source_db)

            # When: the cookie header is extracted and encrypted into session.json.
            with patch("linuxdo_preview.cookie_store._aesgcm_class", return_value=_FakeAESGCM):
                header = extract_cookie_header(str(source_db), data_dir, SESSION_KEY)

            # Then: the temp database copy is removed and unrelated lookalike cookies are not persisted.
            self.assertEqual(
                header,
                "_forum_session=forum-session-synthetic; _t=token-synthetic; cf_clearance=cf-synthetic",
            )
            self.assertEqual(sentinel_tmp.read_text(encoding="utf-8"), "do-not-touch")
            self.assertEqual(list(data_dir.glob("cookies_tmp_*.sqlite")), [])
            with patch("linuxdo_preview.cookie_store._aesgcm_class", return_value=_FakeAESGCM), patch(
                "linuxdo_preview.cookie_store._invalid_tag_error",
                return_value=ValueError,
            ):
                self.assertEqual(get_cookie_header_from_session(data_dir, SESSION_KEY), header)

            session = load_session(data_dir)
            self.assertIsNotNone(session)
            assert session is not None
            self.assertEqual(session["source"], "firefox-cookies-sqlite")
            self.assertNotIn(str(source_db), json.dumps(session, ensure_ascii=False))

    def test_update_session_metadata_preserves_encrypted_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Given: an encrypted session with synthetic cookie values.
            data_dir = Path(tmp)
            header = "_t=token-synthetic"
            cookies: list[CookieRecord] = [
                {"host": "linux.do", "name": "_t", "value": SYNTHETIC_TOKEN_COOKIE}
            ]
            with patch("linuxdo_preview.cookie_store._aesgcm_class", return_value=_FakeAESGCM):
                save_session(data_dir, header, cookies, SESSION_KEY, source="unit-test")

            # When: sync metadata is updated after a preview-time pull/verification.
            update_session_metadata(
                data_dir,
                updated_at="1970-01-01T00:16:40+00:00",
                verified=True,
                verified_at="1970-01-01T00:16:40+00:00",
                verification_url="https://linux.do/t/restricted/1",
                last_error=None,
            )

            # Then: metadata changes are persisted without exposing or changing the cookie value.
            session = load_session(data_dir)
            self.assertIsNotNone(session)
            assert session is not None
            self.assertEqual(session["updated_at"], "1970-01-01T00:16:40+00:00")
            self.assertTrue(session["verified"])
            self.assertEqual(session["verification_url"], "https://linux.do/t/restricted/1")
            serialized = json.dumps(session, ensure_ascii=False)
            self.assertNotIn(SYNTHETIC_TOKEN_COOKIE, serialized)
            with patch("linuxdo_preview.cookie_store._aesgcm_class", return_value=_FakeAESGCM), patch(
                "linuxdo_preview.cookie_store._invalid_tag_error",
                return_value=ValueError,
            ):
                self.assertEqual(get_cookie_header_from_session(data_dir, SESSION_KEY), header)


if __name__ == "__main__":
    _ = unittest.main()
