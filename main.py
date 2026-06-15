"""
astrbot_plugin_linuxdo - LinuxDo 链接检测 & 预览截图插件

检测聊天消息中的 linux.do 链接，使用 Scrapling 的 StealthyFetcher
绕过 Cloudflare Turnstile，自动截图并提取内容摘要发送预览。
"""

import re
import os
import asyncio
import time
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star
from astrbot.api import logger
from astrbot.api import AstrBotConfig
import astrbot.api.message_components as Comp

try:
    from scrapling.fetchers import StealthyFetcher, StealthySession as _StealthySession
    SCRAPLING_AVAILABLE = True
except ImportError:
    SCRAPLING_AVAILABLE = False
    StealthyFetcher = None  # type: ignore[assignment]
    _StealthySession = None  # type: ignore[assignment]

# 全局线程池，避免阻塞 AstrBot 事件循环
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="linuxdo")


class LinuxDoPreviewPlugin(Star):
    """LinuxDo 链接预览插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        # 插件数据目录 data/plugin_data/astrbot_plugin_linuxdo/
        self.data_dir = Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_linuxdo"
        self.screenshot_dir = self.data_dir / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"[LinuxDoPreview] 插件已加载，截图目录: {self.screenshot_dir}"
        )
        if not SCRAPLING_AVAILABLE:
            logger.warning(
                "[LinuxDoPreview] scrapling 未安装！请执行: "
                "pip install scrapling[fetchers] && scrapling install"
            )

        # 缓存统计
        self._stats = {"total": 0, "cache_hit": 0, "error": 0}

    async def terminate(self):
        """插件卸载时清理"""
        _EXECUTOR.shutdown(wait=False)
        logger.info("[LinuxDoPreview] 插件已卸载")

    # ─────────── 消息入口 ───────────

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """检测消息中的 linux.do 链接并触发预览"""
        text = event.message_str
        if not text:
            return

        # 提取所有 linux.do 链接
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

        # 检查是否在忽略列表中（如首页等不需要预览的链接）
        if self._should_skip(target_url):
            return

        # 发送等待提示
        yield event.plain_result(f"🔍 正在获取 linux.do 预览，请稍候…")

        try:
            screenshot_path, summary = await asyncio.get_event_loop().run_in_executor(
                _EXECUTOR,
                self._fetch_preview,
                target_url,
            )

            if screenshot_path and screenshot_path.exists():
                yield event.image_result(str(screenshot_path.absolute()))

            yield event.plain_result(summary)

            self._stats["total"] += 1

        except Exception as e:
            self._stats["error"] += 1
            logger.error(f"[LinuxDoPreview] 预览失败: {type(e).__name__}: {e}")
            yield event.plain_result(f"❌ 预览获取失败: {str(e)[:200]}")

    # ─────────── 核心逻辑 ───────────

    def _should_skip(self, url: str) -> bool:
        """跳过不需要预览的链接"""
        skip_patterns = [
            r"linux\.do/?$",
            r"linux\.do/latest",
            r"linux\.do/categories",
            r"linux\.do/tag/",
            r"linux\.do/u/",
            r"linux\.do/my/",
        ]
        for pat in skip_patterns:
            if re.search(pat, url, re.IGNORECASE):
                return True
        return False

    def _fetch_preview(self, url: str):
        """同步获取页面截图和摘要（在子线程中执行）"""
        if not SCRAPLING_AVAILABLE:
            raise RuntimeError(
                "Scrapling 未安装，请执行: pip install scrapling[fetchers] && scrapling install"
            )

        url_hash = hashlib.md5(url.encode()).hexdigest()
        screenshot_path: Path | None = self.screenshot_dir / f"{url_hash}.png"
        cache_ttl = self.config.get("cache_ttl", 1800)
        cache_valid = (
            screenshot_path.exists()
            and cache_ttl > 0
            and time.time() - screenshot_path.stat().st_mtime < cache_ttl
        )

        StealthyFetcher.adaptive = True  # type: ignore[union-attr]

        with _StealthySession(headless=True, solve_cloudflare=True) as session:  # type: ignore[union-attr]
            page = session.fetch(url)

            # 提取标题
            title = page.css("title::text").get()
            if not title:
                title = page.css("h1::text, .fancy-title::text").get()
            title = (title or "无标题").strip()
            logger.info(f"[LinuxDoPreview] 标题: {title}")

            # 截图（如果缓存已过期或无缓存）
            if not cache_valid:
                try:
                    ctx = session.context
                    if ctx and ctx.pages:
                        ctx.pages[0].screenshot(
                            path=str(screenshot_path),
                            full_page=True,
                            timeout=self.config.get("screenshot_timeout", 15) * 1000,
                        )
                        logger.info(
                            f"[LinuxDoPreview] 截图保存: {screenshot_path.name}"
                        )
                except Exception as e:
                    logger.warning(f"[LinuxDoPreview] 截图失败: {e}")
                    screenshot_path = None
            else:
                self._stats["cache_hit"] += 1
                logger.info(f"[LinuxDoPreview] 使用缓存截图: {screenshot_path.name}")

            # 提取内容摘要
            content = self._extract_page_text(page)

        # 组装回复文本
        summary = self._build_summary(title, content, url)
        return screenshot_path, summary

    def _extract_page_text(self, page) -> str:
        """从页面中提取可读的文字摘要"""
        # 尝试常见的 Discourse 内容选择器
        selectors = [
            ".post .cooked p::text",
            ".topic-body .cooked p::text",
            ".regular.contents .cooked p::text",
            "article .post-content p::text",
            ".topic-post .post-content p::text",
            '[itemprop="articleBody"] p::text',
            "p::text",
            "body::text",
        ]

        collected = []
        for sel in selectors:
            parts = page.css(sel).getall()
            if parts:
                for p in parts:
                    t = p.strip()
                    if t and len(t) > 10:
                        collected.append(t)
                if len(collected) >= 5:
                    break

        max_len = self.config.get("max_content_length", 400)
        text = " ".join(collected)[:max_len + 200]
        return text.strip()[:max_len]

    def _build_summary(self, title: str, content: str, url: str) -> str:
        """组装预览文本"""
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

    # ─────────── 调试指令 ───────────

    @filter.command("linuxdo_stats")
    async def show_stats(self, event: AstrMessageEvent):
        """查看插件统计信息"""
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
        """清理截图缓存"""
        count = 0
        for f in self.screenshot_dir.glob("*.png"):
            f.unlink()
            count += 1
        yield event.plain_result(f"🧹 已清理 {count} 个缓存截图")
