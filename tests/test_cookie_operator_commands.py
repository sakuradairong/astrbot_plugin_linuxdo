import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_main_preview import _install_astrbot_stubs


_install_astrbot_stubs()

from astrbot_plugin_linuxdo.main import LinuxDoPreviewPlugin
from astrbot_plugin_linuxdo.linuxdo_preview import AuthState
from astrbot_plugin_linuxdo.linuxdo_preview.cookie_session import CookieEncryptionError
from astrbot_plugin_linuxdo.linuxdo_preview.cookie_session import CookieNotFoundError


class _Event:
    def plain_result(self, text):
        return text


async def _collect_async(async_iterable):
    return [item async for item in async_iterable]


def _plugin(config, data_dir: Path):
    plugin = LinuxDoPreviewPlugin.__new__(LinuxDoPreviewPlugin)
    plugin.config = config
    plugin.data_dir = data_dir
    plugin._auth_state = AuthState(auth_check_done=True, logged_in=True)
    return plugin


class TestCookieOperatorCommands(unittest.TestCase):
    def test_cookie_status_reports_metadata_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            plugin = _plugin(
                {
                    "linuxdo_session_cookie": "_t=manual-secret; _forum_session=manual-session",
                    "linuxdo_cookie_encryption_key": "secret-key",
                },
                data_dir,
            )
            metadata = {
                "encrypted_cookie": "encrypted-payload-secret",
                "cookie_count": 3,
                "names": ["_forum_session", "_t", "cf_clearance"],
                "updated_at": "2026-07-07T10:11:12Z",
                "source": "/private/profile/cookies.sqlite",
                "verified": False,
                "verified_at": None,
                "verification_url": "https://linux.do/t/restricted/1",
                "last_error": "cookie decryption failed: manual-secret",
            }

            async def _collect():
                with patch(
                    "astrbot_plugin_linuxdo.linuxdo_preview.cookie_commands.cookie_store.load_session",
                    return_value=metadata,
                ):
                    return [item async for item in plugin.show_cookie_status(_Event())]

            results = asyncio.run(_collect())

        self.assertEqual(len(results), 1)
        output = results[0]
        self.assertIn("已保存加密会话: 已存在", output)
        self.assertIn("Cookie 数量: 3", output)
        self.assertIn("Cookie 名称: _forum_session, _t, cf_clearance", output)
        self.assertIn("更新时间: 2026-07-07T10:11:12Z", output)
        self.assertIn("验证状态: 未通过", output)
        self.assertIn("错误类别: 解密失败", output)
        self.assertIn("手动 Cookie 兜底: 已配置", output)
        self.assertNotIn("manual-secret", output)
        self.assertNotIn("manual-session", output)
        self.assertNotIn("encrypted-payload-secret", output)
        self.assertNotIn("secret-key", output)
        self.assertNotIn("/private/profile", output)

    def test_cookie_status_reports_unverified_when_verification_was_not_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            plugin = _plugin(
                {"linuxdo_cookie_encryption_key": "secret-key"},
                data_dir,
            )
            metadata = {
                "encrypted_cookie": "encrypted-payload-secret",
                "cookie_count": 2,
                "names": ["_t", "cf_clearance"],
                "updated_at": "2026-07-07T10:11:12Z",
                "source": "firefox-cookies-sqlite",
                "verified": False,
                "verified_at": None,
                "verification_url": None,
                "last_error": None,
            }

            async def _collect():
                with patch(
                    "astrbot_plugin_linuxdo.linuxdo_preview.cookie_commands.cookie_store.load_session",
                    return_value=metadata,
                ):
                    return [item async for item in plugin.show_cookie_status(_Event())]

            results = asyncio.run(_collect())

        self.assertEqual(len(results), 1)
        output = results[0]
        self.assertIn("验证状态: 未验证", output)
        self.assertNotIn("验证状态: 未通过", output)
        self.assertNotIn("encrypted-payload-secret", output)
        self.assertNotIn("secret-key", output)

    def test_cookie_pull_extracts_configured_profile_and_resets_auth_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            plugin = _plugin(
                {
                    "linuxdo_firefox_profile_path": "/local/firefox/profile",
                    "linuxdo_cookie_encryption_key": "secret-key",
                },
                data_dir,
            )

            async def _collect():
                with patch(
                    "astrbot_plugin_linuxdo.linuxdo_preview.cookie_commands.cookie_store.extract_cookie_header",
                    return_value="_t=pulled-secret; _forum_session=pulled-session",
                ) as extract, patch(
                    "astrbot_plugin_linuxdo.linuxdo_preview.cookie_commands.cookie_store.update_session_metadata",
                ) as update_metadata, patch(
                    "astrbot_plugin_linuxdo.linuxdo_preview.cookie_commands._iso_now",
                    return_value="2026-07-07T10:11:12+00:00",
                ):
                    result = [item async for item in plugin.pull_cookie_session(_Event())]
                return result, extract, update_metadata

            results, extract, update_metadata = asyncio.run(_collect())

        extract.assert_called_once_with("/local/firefox/profile", data_dir, "secret-key")
        update_metadata.assert_called_once_with(
            data_dir,
            updated_at="2026-07-07T10:11:12+00:00",
        )
        self.assertFalse(plugin._auth_state.auth_check_done)
        self.assertEqual(len(results), 1)
        self.assertIn("Cookie 拉取成功", results[0])
        self.assertIn("_t", results[0])
        self.assertIn("_forum_session", results[0])
        self.assertNotIn("pulled-secret", results[0])
        self.assertNotIn("pulled-session", results[0])
        self.assertNotIn("secret-key", results[0])

    def test_cookie_pull_reports_missing_profile_path_without_secret_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _plugin({"linuxdo_cookie_encryption_key": "secret-key"}, Path(tmp))

            results = asyncio.run(_collect_async(plugin.pull_cookie_session(_Event())))

        self.assertEqual(len(results), 1)
        self.assertIn("linuxdo_firefox_profile_path", results[0])
        self.assertNotIn("secret-key", results[0])

    def test_cookie_pull_reports_missing_encryption_key_without_profile_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _plugin(
                {"linuxdo_firefox_profile_path": "/local/firefox/profile"},
                Path(tmp),
            )

            results = asyncio.run(_collect_async(plugin.pull_cookie_session(_Event())))

        self.assertEqual(len(results), 1)
        self.assertIn("linuxdo_cookie_encryption_key", results[0])
        self.assertNotIn("/local/firefox/profile", results[0])

    def test_cookie_pull_reports_missing_cookies_and_dependency_errors_redacted(self):
        cases = [
            (CookieNotFoundError("no linux.do cookies found: _t=secret"), "未找到"),
            (CookieEncryptionError("cryptography missing for secret-key"), "加密依赖"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                plugin = _plugin(
                    {
                        "linuxdo_firefox_profile_path": "/local/firefox/profile",
                        "linuxdo_cookie_encryption_key": "secret-key",
                    },
                    Path(tmp),
                )

                async def _collect():
                    with patch(
                        "astrbot_plugin_linuxdo.linuxdo_preview.cookie_commands.cookie_store.extract_cookie_header",
                        side_effect=error,
                    ):
                        return [item async for item in plugin.pull_cookie_session(_Event())]

                results = asyncio.run(_collect())

            self.assertEqual(len(results), 1)
            self.assertIn(expected, results[0])
            self.assertTrue(plugin._auth_state.auth_check_done)
            self.assertNotIn("secret", results[0])
            self.assertNotIn("/local/firefox/profile", results[0])

    def test_cookie_pull_reports_unexpected_local_error_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _plugin(
                {
                    "linuxdo_firefox_profile_path": "/local/firefox/profile",
                    "linuxdo_cookie_encryption_key": "secret-key",
                },
                Path(tmp),
            )

            async def _collect():
                with patch(
                    "astrbot_plugin_linuxdo.linuxdo_preview.cookie_commands.cookie_store.extract_cookie_header",
                    side_effect=OSError("/local/firefox/profile contains _t=secret"),
                ):
                    return [item async for item in plugin.pull_cookie_session(_Event())]

            results = asyncio.run(_collect())

        self.assertEqual(len(results), 1)
        self.assertIn("本地 Cookie 拉取发生意外错误", results[0])
        self.assertIn("OSError", results[0])
        self.assertTrue(plugin._auth_state.auth_check_done)
        self.assertNotIn("secret", results[0])
        self.assertNotIn("/local/firefox/profile", results[0])


class TestConfigSchemaCookieSync(unittest.TestCase):
    def test_cookie_sync_keys_and_manual_cookie_hint_are_present(self):
        schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        expected = {
            "linuxdo_cookie_sync_enabled": ("bool", False),
            "linuxdo_firefox_profile_path": ("string", ""),
            "linuxdo_cookie_encryption_key": ("string", ""),
            "linuxdo_cookie_sync_interval_seconds": ("int", 7200),
            "linuxdo_restricted_topic_url": ("string", ""),
        }
        for key, (type_name, default) in expected.items():
            with self.subTest(key=key):
                self.assertEqual(schema[key]["type"], type_name)
                self.assertEqual(schema[key]["default"], default)

        manual_hint = schema["linuxdo_session_cookie"]["hint"]
        self.assertIn("加密保存的 Cookie", manual_hint)
        self.assertIn("手动 Cookie", manual_hint)
        self.assertIn("兜底", manual_hint)
        self.assertIn("受限主题摘要/截图发送到群里", manual_hint)
        self.assertIn("cookies.sqlite", schema["linuxdo_firefox_profile_path"]["hint"])
        self.assertIn("不管理", schema["linuxdo_firefox_profile_path"]["hint"])
        self.assertIn("容器", schema["linuxdo_firefox_profile_path"]["hint"])


if __name__ == "__main__":
    unittest.main()
