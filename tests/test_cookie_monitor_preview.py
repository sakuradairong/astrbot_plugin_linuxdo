from pathlib import Path
import sys
import tempfile
import threading
import unittest

from tests import test_main_preview


LinuxDoPreviewPlugin = test_main_preview.LinuxDoPreviewPlugin
plugin_main = sys.modules["astrbot_plugin_linuxdo.main"]


class TestPreviewCookieSyncWiring(unittest.TestCase):
    def test_fetch_preview_syncs_cookie_before_authentication(self):
        calls: list[str] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = LinuxDoPreviewPlugin.__new__(LinuxDoPreviewPlugin)
            plugin.config = {"use_api_render": True, "cache_ttl": 0}
            plugin.screenshot_dir = Path(tmpdir)
            plugin._stats = {"total": 0, "cache_hit": 0, "error": 0}
            plugin._stats_lock = threading.Lock()

            def _sync_cookie_if_due(_session: _Session | None = None) -> None:
                calls.append("sync")

            def _ensure_authenticated(_session: _Session) -> bool:
                calls.append("auth")
                return True

            def _fetch_with_api_render(
                _session: _Session,
                _url: str,
                path: Path,
                _is_valid: bool,
            ) -> tuple[str, str, Path]:
                calls.append("fetch")
                return "Title", "Body", path

            setattr(plugin, "_sync_cookie_if_due", _sync_cookie_if_due)
            setattr(plugin, "_ensure_authenticated", _ensure_authenticated)
            setattr(plugin, "_fetch_with_api_render", _fetch_with_api_render)
            setattr(plugin, "_build_summary", lambda title, content, url: f"{title}|{content}|{url}")

            original_available = getattr(plugin_main, "_scrapling_available")
            original_get_session = getattr(plugin_main, "_get_stealthy_session")
            setattr(plugin_main, "_scrapling_available", True)
            setattr(plugin_main, "_get_stealthy_session", lambda: _Session)
            try:
                _path, summary = plugin._fetch_preview("https://linux.do/t/topic/123")
            finally:
                setattr(plugin_main, "_scrapling_available", original_available)
                setattr(plugin_main, "_get_stealthy_session", original_get_session)

        self.assertEqual(calls, ["sync", "auth", "fetch"])
        self.assertEqual(summary, "Title|Body|https://linux.do/t/topic/123")


class _Session:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        return None

    def __enter__(self) -> "_Session":
        return self

    def __exit__(
        self,
        _type: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: object,
    ) -> None:
        return None


if __name__ == "__main__":
    _ = unittest.main()
