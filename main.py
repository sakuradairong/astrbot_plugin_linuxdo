"""
astrbot_plugin_linuxdo - LinuxDo 链接检测 & 预览截图插件

检测聊天消息中的 linux.do 链接，使用 Scrapling 的 StealthySession
绕过 Cloudflare Turnstile，分两步：先 fetch 拿文本 + cookies，
再新建标签页截图（复用 cf_clearance，不重复触发验证）。
"""

import re
import asyncio
import time
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import html as html_mod
import threading

from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger
from astrbot.api import AstrBotConfig

try:
    from scrapling.fetchers import StealthySession as _StealthySession
    from lxml import html as _lh
    SCRAPLING_AVAILABLE = True
except ImportError:
    SCRAPLING_AVAILABLE = False
    _StealthySession = None
    _lh = None

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="linuxdo")


class LinuxDoPreviewPlugin(Star):
    """LinuxDo 链接预览插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        self.data_dir = Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_linuxdo"
        self.screenshot_dir = self.data_dir / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[LinuxDoPreview] 插件已加载，截图目录: {self.screenshot_dir}")
        if not SCRAPLING_AVAILABLE:
            logger.warning(
                "[LinuxDoPreview] scrapling 未安装！"
                "执行: pip install scrapling[fetchers] && scrapling install && playwright install-deps chromium"
            )

        self._stats = {"total": 0, "cache_hit": 0, "error": 0}
        self._stats_lock = threading.Lock()

    async def terminate(self):
        _EXECUTOR.shutdown(wait=False)
        logger.info("[LinuxDoPreview] 插件已卸载")

    # ─────────── 消息入口 ───────────

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        text = event.message_str
        if not text:
            return

        urls = re.finditer(
            r"https?://(?:[a-z0-9.\-]+\.)*linux\.do/[^\s\"')>}]+",
            text,
            re.IGNORECASE,
        )
        matched_urls = [m.group(0).rstrip(".,;:!?") for m in urls]
        if not matched_urls:
            return

        target_url = matched_urls[0]
        logger.info(f"[LinuxDoPreview] 检测到链接: {target_url}")

        if self._should_skip(target_url):
            return

        yield event.plain_result("🔍 正在读取 linux.do 页面…")

        try:
            screenshot_path, summary = await asyncio \
                .get_event_loop() \
                .run_in_executor(_EXECUTOR, self._fetch_preview, target_url)

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
            yield event.plain_result(f"❌ 预览获取失败: {str(e)[:200]}")

    # ─────────── 预处理 ───────────

    @staticmethod
    def _should_skip(url: str) -> bool:
        skip = [
            r"linux\.do/?$", r"linux\.do/latest", r"linux\.do/categories",
            r"linux\.do/tag/", r"linux\.do/u/", r"linux\.do/my/",
        ]
        return any(re.search(p, url, re.IGNORECASE) for p in skip)

    # ─────────── 核心：两步法 ───────────

    def _fetch_preview(self, url: str):
        if not SCRAPLING_AVAILABLE:
            raise RuntimeError("Scrapling 未安装")

        url_hash = hashlib.md5(url.encode()).hexdigest()
        screenshot_path = self.screenshot_dir / f"{url_hash}.png"
        cache_ttl = self.config.get("cache_ttl", 1800)
        screenshot_is_valid = False
        if screenshot_path.exists():
            sz = screenshot_path.stat().st_size
            age = time.time() - screenshot_path.stat().st_mtime
            screenshot_is_valid = (
                cache_ttl > 0
                and age < cache_ttl
                and sz > 50 * 1024  # 小于 50KB 的截图视为无效（黑屏/空白）
            )

        with _StealthySession(  # type: ignore[union-attr]
            headless=True, solve_cloudflare=True
        ) as session:
            # ── Step 1: fetch 触发 Cloudflare 解决，拿 HTML ──
            resp = session.fetch(url)
            html_str = resp.body.decode("utf-8", errors="replace")
            title = self._extract_title(html_str)
            content = self._extract_content(html_str)
            logger.info(f"[LinuxDoPreview] 标题: {title}")

            # ── Step 2: 新建标签页（复用 cf_clearance）截图 ──
            if not screenshot_is_valid:
                screenshot_path = self._take_screenshot(
                    session, url, screenshot_path
                )
            else:
                with self._stats_lock:
                    self._stats["cache_hit"] += 1
            logger.info(
                f"[LinuxDoPreview] 使用缓存截图: {screenshot_path.name}"
            )

        summary = self._build_summary(title, content, url)
        return screenshot_path, summary

    # ─────────── 截图（复用 StealthySession 的浏览器上下文） ───────────

    def _take_screenshot(self, session, url: str, save_path: Path) -> Path | None:
        """在已有 cf_clearance 的上下文中新建标签页截图"""
        timeout_ms = self.config.get("screenshot_timeout", 15) * 1000
        try:
            ctx = session.context
            if not ctx:
                return None

            page = ctx.new_page()
            page.set_viewport_size({"width": 1280, "height": 900})

            # ── 导航：等 networkidle 确保 JS 动态内容加载完成 ──
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)

            # ── 等待 Discourse 帖子内容渲染 ──
            try:
                page.wait_for_selector(".cooked", timeout=min(timeout_ms, 10000))
            except Exception:
                page.wait_for_timeout(3000)  # 回退：固定等待

            # ── 隐藏非楼主内容，只保留第一篇帖子完整展示 ──
            page.evaluate("""() => {
                const hide = (sel) => {
                    const el = document.querySelector(sel);
                    if (el) el.style.display = 'none';
                };
                hide('.d-header');                      // 顶部导航栏
                hide('.sidebar-wrapper');               // 左侧边栏
                hide('.topic-navigation-wrapper');      // 帖子导航条
                hide('.footer-nav.visible');            // 底部导航

                // 隐藏所有回复帖子，只保留楼主
                const posts = document.querySelectorAll('.topic-post');
                posts.forEach((post, i) => { if (i > 0) post.style.display = 'none'; });

                // 滚动到顶部
                window.scrollTo(0, 0);
            }""")

            page.wait_for_timeout(1000)  # 等待滚动稳定 + 懒加载图片

            # ── 截图：全页模式，隐藏导航栏后内容干净 ──
            full_page = self.config.get("screenshot_full_page", True)
            page.screenshot(
                path=str(save_path),
                full_page=full_page,
                timeout=timeout_ms,
            )

            sz = save_path.stat().st_size
            logger.info(
                f"[LinuxDoPreview] 截图保存: {save_path.name} ({sz / 1024:.1f} KB)"
            )
            page.close()
            return save_path

        except Exception as e:
            logger.warning(f"[LinuxDoPreview] 截图失败: {type(e).__name__}: {e}")
            return None

    # ─────────── 文本提取 ───────────

    @staticmethod
    def _extract_title(html_str: str) -> str:
        m = re.search(r"<title>(.*?)</title>", html_str, re.DOTALL | re.IGNORECASE)
        if m:
            t = m.group(1).strip()
            t = re.sub(
                r"\s*[-–—|]\s*(LINUX\s*DO|LINUXDO).*$", "", t, flags=re.IGNORECASE
            )
            return t.strip()
        return "无标题"

    def _extract_content(self, html_str: str) -> str:
        try:
            return self._extract_via_lxml(html_str)
        except Exception:
            pass
        try:
            return self._extract_via_regex(html_str)
        except Exception:
            pass
        return ""

    def _extract_via_lxml(self, html_str: str) -> str:
        tree = _lh.fromstring(html_str)
        parts = []
        for el in tree.cssselect(".cooked"):
            text = _clean_text(el.text_content())
            if len(text) > 15:
                parts.append(text)
            if len(parts) >= 3:
                break
        return "\n\n".join(parts)

    def _extract_via_regex(self, html_str: str) -> str:
        parts = []
        for m in re.finditer(
            r'<div\s+class="cooked">(.*?)</div>\s*</article>', html_str, re.DOTALL
        ):
            text = re.sub(r"<[^>]+>", " ", m.group(1))
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 15:
                parts.append(text)
            if len(parts) >= 3:
                break
        return "\n\n".join(parts)

    def _build_summary(self, title: str, content: str, url: str) -> str:
        lines = [f"📌 {title}"]
        if content:
            lines.append("")
            max_len = self.config.get("max_content_length", 400)
            lines.append(content[:max_len])
            if len(content) > max_len:
                lines[-1] += "…"
        lines.append("")
        lines.append(f"🔗 {url}")
        return "\n".join(lines)

    # ─────────── 管理指令 ───────────

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


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = html_mod.unescape(text)
    return text.strip()
