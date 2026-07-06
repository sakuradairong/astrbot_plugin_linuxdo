"""
astrbot_plugin_linuxdo - LinuxDo 链接检测 & 预览截图插件

检测聊天消息中的 linux.do 链接，使用 Scrapling 的 StealthySession
绕过 Cloudflare Turnstile，分两步：先 fetch 拿文本 + cookies，
再新建标签页截图（复用 cf_clearance，不重复触发验证）。
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import re
import threading
import time

from astrbot.api import AstrBotConfig
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.event import filter
from astrbot.api.star import Context
from astrbot.api.star import Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from linuxdo_preview import AuthState
from linuxdo_preview import LinuxDoTopicData
from linuxdo_preview import _build_preview_html
from linuxdo_preview import _build_summary
from linuxdo_preview import _check_login_state
from linuxdo_preview import _clean_text
from linuxdo_preview import _ensure_authenticated
from linuxdo_preview import _extract_content
from linuxdo_preview import _extract_content_from_json
from linuxdo_preview import _extract_content_from_topic_data
from linuxdo_preview import _extract_title
from linuxdo_preview import _extract_via_lxml
from linuxdo_preview import _extract_via_regex
from linuxdo_preview import _fetch_topic_data
from linuxdo_preview import _format_count
from linuxdo_preview import _has_auto_login
from linuxdo_preview import _has_session_cookie
from linuxdo_preview import _inject_session_cookie
from linuxdo_preview import _normalize_cooked_urls
from linuxdo_preview import _parse_cookie_pairs
from linuxdo_preview import _render_html_screenshot
from linuxdo_preview import _safe_title
from linuxdo_preview import _take_screenshot

try:
    from scrapling.fetchers import StealthySession as _StealthySession
    from lxml import html as _unused_lxml_html

    _scrapling_available = True
except ImportError:
    _scrapling_available = False
    _StealthySession = None

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="linuxdo")


def _extract_linuxdo_urls(text: str) -> list[str]:
    urls = re.finditer(
        r"https?://(?:linux\.do|(?:[a-z0-9-]+\.)+linux\.do)/[^\s\"')>}]+",
        text,
        re.IGNORECASE,
    )
    return [m.group(0).rstrip(".,;:!?") for m in urls]


def _get_stealthy_session():
    if not _scrapling_available or _StealthySession is None:
        raise RuntimeError("Scrapling 未安装")
    return _StealthySession


class LinuxDoPreviewPlugin(Star):
    """LinuxDo 链接预览插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        self.data_dir = Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_linuxdo"
        self.screenshot_dir = self.data_dir / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[LinuxDoPreview] 插件已加载，截图目录: {self.screenshot_dir}")
        if not _scrapling_available:
            logger.warning(
                "[LinuxDoPreview] scrapling 未安装！"
                "执行: pip install scrapling[fetchers] && scrapling install && playwright install-deps chromium"
            )

        self._stats = {"total": 0, "cache_hit": 0, "error": 0}
        self._stats_lock = threading.Lock()
        self._auth_state = AuthState()
        self._auth_lock = threading.Lock()

    async def terminate(self):
        _EXECUTOR.shutdown(wait=False)
        logger.info("[LinuxDoPreview] 插件已卸载")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        text = event.message_str
        if not text:
            return

        matched_urls = _extract_linuxdo_urls(text)
        if not matched_urls:
            return

        target_url = matched_urls[0]
        logger.info(f"[LinuxDoPreview] 检测到链接: {target_url}")

        if self._should_skip(target_url):
            return

        yield event.plain_result("🔍 正在读取 linux.do 页面…")

        try:
            screenshot_path, summary = await asyncio.get_event_loop().run_in_executor(
                _EXECUTOR, self._fetch_preview, target_url
            )

            if screenshot_path and screenshot_path.exists():
                yield event.image_result(str(screenshot_path.absolute()))

            if summary:
                yield event.plain_result(summary)

            with self._stats_lock:
                self._stats["total"] += 1

        except Exception as e:
            with self._stats_lock:
                self._stats["error"] += 1
            logger.error(f"[LinuxDoPreview] 预览失败: {type(e).__name__}: {e}")
            yield event.plain_result("❌ 预览获取失败，请稍后重试")

    @staticmethod
    def _should_skip(url: str) -> bool:
        skip = [
            r"linux\.do/?$", r"linux\.do/latest", r"linux\.do/categories",
            r"linux\.do/tag/", r"linux\.do/u/", r"linux\.do/my/",
        ]
        return any(re.search(p, url, re.IGNORECASE) for p in skip)

    def _fetch_preview(self, url: str) -> tuple[Path | None, str]:
        if not _scrapling_available:
            raise RuntimeError("Scrapling 未安装")

        url_hash = hashlib.md5(url.encode()).hexdigest()
        screenshot_path = self.screenshot_dir / f"{url_hash}.png"
        screenshot_is_valid = self._is_valid_screenshot_cache(screenshot_path)
        use_api_render = self.config.get("use_api_render", True)

        session_cls = _get_stealthy_session()
        with session_cls(headless=True, solve_cloudflare=True) as session:
            self._ensure_authenticated(session)
            if use_api_render:
                title, content, screenshot_path = self._fetch_with_api_render(
                    session, url, screenshot_path, screenshot_is_valid
                )
            else:
                title, content, screenshot_path = self._fetch_with_page_render(
                    session, url, screenshot_path, screenshot_is_valid
                )
            if screenshot_is_valid:
                with self._stats_lock:
                    self._stats["cache_hit"] += 1
            logger.info(f"[LinuxDoPreview] 标题: {title}, 内容长度: {len(content)}")
            if screenshot_path:
                logger.info(f"[LinuxDoPreview] 使用截图: {screenshot_path.name}")

        summary = self._build_summary(title, content, url)
        return screenshot_path, summary

    def _is_valid_screenshot_cache(self, screenshot_path: Path) -> bool:
        if not screenshot_path.exists():
            return False
        sz = screenshot_path.stat().st_size
        age = time.time() - screenshot_path.stat().st_mtime
        cache_ttl = self.config.get("cache_ttl", 1800)
        return cache_ttl > 0 and age < cache_ttl and sz > 50 * 1024

    def _fetch_with_api_render(self, session, url: str, screenshot_path: Path, screenshot_is_valid: bool) -> tuple[str, str, Path | None]:
        topic_data = self._fetch_topic_data(session, url)
        title = self._safe_title(topic_data)
        if topic_data:
            content = self._extract_content_from_topic_data(topic_data)
            result_path: Path | None = screenshot_path
            if not screenshot_is_valid:
                original_screenshot_path = screenshot_path
                result_path = None
                html = self._build_preview_html(topic_data, url)
                if html:
                    result_path = self._render_html_screenshot(session, html, screenshot_path)
                if not self._is_rendered_screenshot_valid(result_path):
                    result_path = self._take_screenshot(session, url, original_screenshot_path)
            return title, content, result_path

        resp = session.fetch(url)
        html_str = resp.body.decode("utf-8", errors="replace")
        title = self._extract_title(html_str)
        content = self._extract_content(html_str)
        result_path: Path | None = screenshot_path
        if not screenshot_is_valid:
            result_path = self._take_screenshot(session, url, screenshot_path)
        return title, content, result_path

    @staticmethod
    def _is_rendered_screenshot_valid(screenshot_path: Path | None) -> bool:
        return bool(
            screenshot_path
            and screenshot_path.exists()
            and screenshot_path.stat().st_size > 50 * 1024
        )

    def _fetch_with_page_render(self, session, url: str, screenshot_path: Path, screenshot_is_valid: bool) -> tuple[str, str, Path | None]:
        resp = session.fetch(url)
        html_str = resp.body.decode("utf-8", errors="replace")
        title = self._extract_title(html_str)
        content = self._extract_content_from_json(session, url)
        if not content:
            content = self._extract_content(html_str)
        result_path: Path | None = screenshot_path
        if not screenshot_is_valid:
            result_path = self._take_screenshot(session, url, screenshot_path)
        return title, content, result_path

    def _has_session_cookie(self) -> bool:
        return _has_session_cookie(self.config)

    def _has_auto_login(self) -> bool:
        return _has_auto_login(self.config)

    def _parse_cookie_pairs(self, cookie_str: str) -> list[dict[str, str]]:
        return _parse_cookie_pairs(cookie_str)

    def _inject_session_cookie(self, session, cookie_value: str = "") -> bool:
        return _inject_session_cookie(session, self.config, logger, cookie_value)

    def _check_login_state(self, session) -> bool:
        return _check_login_state(session)

    def _ensure_authenticated(self, session) -> bool:
        return _ensure_authenticated(session, self.config, self._auth_state, self._auth_lock, logger)

    def _extract_content_from_json(self, session, url: str) -> str:
        return _extract_content_from_json(session, url, logger)

    def _fetch_topic_data(self, session, url: str) -> LinuxDoTopicData | None:
        return _fetch_topic_data(session, url, logger)

    _extract_title = staticmethod(_extract_title)
    _extract_content = staticmethod(_extract_content)
    _extract_via_lxml = staticmethod(_extract_via_lxml)
    _extract_via_regex = staticmethod(_extract_via_regex)
    _safe_title = staticmethod(_safe_title)
    _format_count = staticmethod(_format_count)
    _clean_text = staticmethod(_clean_text)
    _normalize_cooked_urls = staticmethod(_normalize_cooked_urls)

    def _build_summary(self, title: str, content: str, url: str) -> str:
        return _build_summary(title, content, url, self.config.get("max_content_length", 400))

    def _extract_content_from_topic_data(self, topic_data: LinuxDoTopicData) -> str:
        return _extract_content_from_topic_data(topic_data, logger)

    def _build_preview_html(self, topic_data: LinuxDoTopicData, url: str) -> str:
        return _build_preview_html(topic_data, url)

    def _take_screenshot(self, session, url: str, save_path: Path) -> Path | None:
        return _take_screenshot(session, url, save_path, self.config, logger)

    def _render_html_screenshot(self, session, html: str, save_path: Path) -> Path | None:
        return _render_html_screenshot(session, html, save_path, self.config, logger)

    @filter.command("linuxdo_stats")
    async def show_stats(self, event: AstrMessageEvent):
        screenshots = list(self.screenshot_dir.glob("*.png"))
        cache_size = sum(f.stat().st_size for f in screenshots) / 1024
        yield event.plain_result(
            f"📊 LinuxDo Preview 统计\n"
            f"  请求总数: {self._stats['total']}\n"
            f"  缓存命中: {self._stats['cache_hit']}\n"
            f"  错误次数: {self._stats['error']}\n"
            f"  缓存截图: {len(screenshots)} ({cache_size:.1f} KB)"
        )

    @filter.command("linuxdo_clean")
    async def clean_cache(self, event: AstrMessageEvent):
        count = 0
        for f in self.screenshot_dir.glob("*.png"):
            f.unlink()
            count += 1
        yield event.plain_result(f"🧹 已清理 {count} 个缓存截图")
