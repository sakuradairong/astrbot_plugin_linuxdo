import asyncio
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest


def _install_astrbot_stubs():
    if "astrbot.api" in sys.modules:
        return

    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")
    core = types.ModuleType("astrbot.core")
    utils = types.ModuleType("astrbot.core.utils")
    astrbot_path = types.ModuleType("astrbot.core.utils.astrbot_path")

    class _Logger:
        def info(self, *_args, **_kwargs):
            return None

        def warning(self, *_args, **_kwargs):
            return None

        def error(self, *_args, **_kwargs):
            return None

    class _Filter:
        class EventMessageType:
            ALL = "all"

        @staticmethod
        def event_message_type(_message_type):
            def _decorator(func):
                return func

            return _decorator

        @staticmethod
        def command(_name):
            def _decorator(func):
                return func

            return _decorator

    class _Star:
        def __init__(self, _context):
            return None

    setattr(api, "AstrBotConfig", dict)
    setattr(api, "logger", _Logger())
    setattr(event, "AstrMessageEvent", object)
    setattr(event, "filter", _Filter)
    setattr(star, "Context", object)
    setattr(star, "Star", _Star)
    setattr(astrbot_path, "get_astrbot_data_path", lambda: tempfile.gettempdir())

    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api
    sys.modules["astrbot.api.event"] = event
    sys.modules["astrbot.api.star"] = star
    sys.modules["astrbot.core"] = core
    sys.modules["astrbot.core.utils"] = utils
    sys.modules["astrbot.core.utils.astrbot_path"] = astrbot_path


_install_astrbot_stubs()

from main import LinuxDoPreviewPlugin
from main import _extract_linuxdo_urls


class TestMainUrlExtraction(unittest.TestCase):
    def test_accepts_linuxdo_and_real_subdomains(self):
        text = "see https://linux.do/t/a/1, and https://meta.linux.do/t/b/2)."
        self.assertEqual(
            _extract_linuxdo_urls(text),
            ["https://linux.do/t/a/1", "https://meta.linux.do/t/b/2"],
        )

    def test_rejects_lookalike_domains(self):
        text = "bad https://notlinux.do/t/1 and https://evil-linux.do/t/2 ok https://linux.do/t/3"
        self.assertEqual(_extract_linuxdo_urls(text), ["https://linux.do/t/3"])


class TestMainUserFacingErrors(unittest.TestCase):
    def test_on_message_logs_exception_without_sending_detail_to_chat(self):
        class _Event:
            message_str = "https://linux.do/t/topic/123"

            def plain_result(self, text):
                return text

            def image_result(self, text):
                return text

        async def _collect():
            plugin = LinuxDoPreviewPlugin.__new__(LinuxDoPreviewPlugin)
            plugin._stats = {"total": 0, "cache_hit": 0, "error": 0}
            plugin._stats_lock = threading.Lock()
            setattr(plugin, "_fetch_preview", lambda _url: (_ for _ in ()).throw(RuntimeError("secret token 123")))
            return [item async for item in plugin.on_message(_Event())]

        results = asyncio.run(_collect())
        self.assertEqual(results[0], "🔍 正在读取 linux.do 页面…")
        self.assertEqual(results[1], "❌ 预览获取失败，请稍后重试")
        self.assertNotIn("secret", results[1])


class TestApiRenderFallback(unittest.TestCase):
    def test_falls_back_to_page_screenshot_when_render_returns_no_valid_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            screenshot_path = Path(tmpdir) / "preview.png"
            fallback_path = Path(tmpdir) / "fallback.png"
            plugin = LinuxDoPreviewPlugin.__new__(LinuxDoPreviewPlugin)
            setattr(plugin, "_fetch_topic_data", lambda _session, _url: {"title": "Title", "post_stream": {"posts": [{"cooked": "<p>Body</p>"}]}})
            setattr(plugin, "_safe_title", lambda _topic_data: "Title")
            setattr(plugin, "_extract_content_from_topic_data", lambda _topic_data: "Body")
            setattr(plugin, "_build_preview_html", lambda _topic_data, _url: "<html></html>")
            setattr(plugin, "_render_html_screenshot", lambda _session, _html, _path: None)
            calls = []

            def _take_screenshot(_session, url, save_path):
                calls.append((url, save_path))
                fallback_path.write_bytes(b"x" * (51 * 1024))
                return fallback_path

            setattr(plugin, "_take_screenshot", _take_screenshot)
            title, content, rendered_path = plugin._fetch_with_api_render(
                object(), "https://linux.do/t/topic/123", screenshot_path, False
            )
            self.assertEqual((title, content, rendered_path), ("Title", "Body", fallback_path))
            self.assertEqual(calls, [("https://linux.do/t/topic/123", screenshot_path)])

    def test_falls_back_when_rendered_file_is_too_small(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            screenshot_path = Path(tmpdir) / "preview.png"
            fallback_path = Path(tmpdir) / "fallback.png"
            plugin = LinuxDoPreviewPlugin.__new__(LinuxDoPreviewPlugin)
            setattr(plugin, "_fetch_topic_data", lambda _session, _url: {"title": "Title", "post_stream": {"posts": [{"cooked": "<p>Body</p>"}]}})
            setattr(plugin, "_safe_title", lambda _topic_data: "Title")
            setattr(plugin, "_extract_content_from_topic_data", lambda _topic_data: "Body")
            setattr(plugin, "_build_preview_html", lambda _topic_data, _url: "<html></html>")

            def _render(_session, _html, save_path):
                save_path.write_bytes(b"tiny")
                return save_path

            setattr(plugin, "_render_html_screenshot", _render)
            setattr(plugin, "_take_screenshot", lambda _session, _url, _save_path: fallback_path)
            title, content, rendered_path = plugin._fetch_with_api_render(
                object(), "https://linux.do/t/topic/123", screenshot_path, False
            )
            self.assertEqual((title, content, rendered_path), ("Title", "Body", fallback_path))

    def test_keeps_valid_rendered_screenshot_without_page_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            screenshot_path = Path(tmpdir) / "preview.png"
            plugin = LinuxDoPreviewPlugin.__new__(LinuxDoPreviewPlugin)
            setattr(plugin, "_fetch_topic_data", lambda _session, _url: {"title": "Title", "post_stream": {"posts": [{"cooked": "<p>Body</p>"}]}})
            setattr(plugin, "_safe_title", lambda _topic_data: "Title")
            setattr(plugin, "_extract_content_from_topic_data", lambda _topic_data: "Body")
            setattr(plugin, "_build_preview_html", lambda _topic_data, _url: "<html></html>")
            calls = []

            def _render(_session, _html, save_path):
                save_path.write_bytes(b"x" * (51 * 1024))
                return save_path

            setattr(plugin, "_render_html_screenshot", _render)
            setattr(plugin, "_take_screenshot", lambda _session, _url, _save_path: calls.append(_save_path))
            title, content, rendered_path = plugin._fetch_with_api_render(
                object(), "https://linux.do/t/topic/123", screenshot_path, False
            )
            self.assertEqual((title, content, rendered_path), ("Title", "Body", screenshot_path))
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
