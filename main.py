"""
astrbot_plugin_linuxdo - LinuxDo 链接检测 & 预览截图插件

检测聊天消息中的 linux.do 链接，使用 Scrapling 的 StealthySession
绕过 Cloudflare Turnstile，分两步：先 fetch 拿文本 + cookies，
再新建标签页截图（复用 cf_clearance，不重复触发验证）。
"""

import re
import asyncio
import inspect
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

        # 登录状态：跨 fetch 复用在同一 StealthySession 中
        self._auth_check_done = False
        self._logged_in = False
        self._runtime_cookie_value = ""
        self._remote_cookie_pull_done = False
        self._status_task = None
        self._runtime_notify_targets: set[str] = set()
        self._last_cookie_status_ok = None
        self._last_cookie_alert_at = 0.0
        self._start_status_task()

    async def terminate(self):
        if self._status_task:
            self._status_task.cancel()
            try:
                await self._status_task
            except asyncio.CancelledError:
                pass
        _EXECUTOR.shutdown(wait=False)
        logger.info("[LinuxDoPreview] 插件已卸载")

    # ─────────── 消息入口 ───────────

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        self._start_status_task()
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

        use_api_render = self.config.get("use_api_render", True)

        with _StealthySession(  # type: ignore[union-attr]
            headless=True, solve_cloudflare=True
        ) as session:
            # ── 可选：按需登录以访问受限内容 ──
            self._ensure_authenticated(session)
            if use_api_render:
                # ── 方案 A：API + 自定义 HTML 渲染（推荐）──
                topic_data = self._fetch_topic_data(session, url)
                title = self._safe_title(topic_data)
                if topic_data:
                    content = self._extract_content_from_topic_data(topic_data)
                    if not screenshot_is_valid:
                        html = self._build_preview_html(topic_data, url)
                        if html:
                            screenshot_path = self._render_html_screenshot(
                                session, html, screenshot_path
                            )
                else:
                    # API 拉取失败 → 回退原方案
                    resp = session.fetch(url)
                    html_str = resp.body.decode("utf-8", errors="replace")
                    title = self._extract_title(html_str)
                    content = self._extract_content(html_str)
                    if not screenshot_is_valid:
                        screenshot_path = self._take_screenshot(
                            session, url, screenshot_path
                        )
            else:
                # ── 方案 B：传统页面 + JS 隐藏 ──
                resp = session.fetch(url)
                html_str = resp.body.decode("utf-8", errors="replace")
                title = self._extract_title(html_str)
                content = self._extract_content_from_json(session, url)
                if not content:
                    content = self._extract_content(html_str)
                if not screenshot_is_valid:
                    screenshot_path = self._take_screenshot(
                        session, url, screenshot_path
                    )
            if screenshot_is_valid:
                with self._stats_lock:
                    self._stats["cache_hit"] += 1
            logger.info(
                f"[LinuxDoPreview] 标题: {title}, 内容长度: {len(content)}"
            )
            if screenshot_path:
                logger.info(
                    f"[LinuxDoPreview] 使用截图: {screenshot_path.name}"
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
                page.wait_for_selector("#post_1", timeout=min(timeout_ms, 10000))
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
                hide('.post-stream');                   // 隐藏整个帖子流（后面单独显示楼主）

                // 隐藏所有回复帖子，只保留楼主
                const posts = document.querySelectorAll('.topic-post');
                posts.forEach((post, i) => { if (i > 0) post.style.display = 'none'; });

                // 滚动到顶部
                window.scrollTo(0, 0);
            }""")

            # ── 展开 Discourse 截断的长帖 ──
            page.evaluate("""() => {
                // 移除所有展开按钮和截断遮罩
                const removeSelectors = [
                    '.expand-post',
                    '.gap-bottom',
                    '.gap',
                    '.large-post-container .show-more',
                    '.topic-body .show-more',
                    '.cooked .show-more',
                    '.lightbox',
                ];
                removeSelectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => el.remove());
                });

                // 移除所有 max-height / overflow 限制
                const unclampSelectors = [
                    '.cooked',
                    '.topic-body',
                    '#post_1 .cooked',
                    '#post_1 .topic-body',
                    '#post_1 .contents',
                    '.large-post-container',
                ];
                unclampSelectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => {
                        el.style.maxHeight = 'none';
                        el.style.overflow = 'visible';
                        el.style.height = 'auto';
                    });
                });

                // 展开 Discourse 长帖截断（data-* 属性方式）
                document.querySelectorAll('[data-expanded]').forEach(el => {
                    el.setAttribute('data-expanded', 'true');
                });
                // 移除 truncated 标记
                document.querySelectorAll('.truncated').forEach(el => {
                    el.classList.remove('truncated');
                });
            }""")

            # ── 点击可能存在的展开按钮 ──
            try:
                expand_buttons = page.query_selector_all(
                    '#post_1 .expand-post, #post_1 .show-more, '
                    '#post_1 button[class*="expand"], '
                    '#post_1 a[class*="expand"]'
                )
                for btn in expand_buttons:
                    try:
                        btn.click()
                        page.wait_for_timeout(300)
                    except Exception:
                        pass
            except Exception:
                pass

            # ── 再次展开，防止点击按钮后重新截断 ──
            page.evaluate("""() => {
                ['#post_1 .cooked', '#post_1 .topic-body', '#post_1 .contents'].forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => {
                        el.style.maxHeight = 'none';
                        el.style.overflow = 'visible';
                        el.style.height = 'auto';
                    });
                });
                // 确保图片容器也不截断
                document.querySelectorAll('#post_1 .lightbox-wrapper').forEach(el => {
                    el.style.maxHeight = 'none';
                    el.style.overflow = 'visible';
                });
            }""")

            # ── 滚动楼主帖子，触发懒加载图片 ──
            post1_box = page.evaluate("""() => {
                const p1 = document.querySelector('#post_1');
                if (!p1) return null;
                const rect = p1.getBoundingClientRect();
                return { top: rect.top + window.scrollY, height: rect.height };
            }""")
            if post1_box:
                post_top = int(post1_box.get('top', 0))
                post_height = int(post1_box.get('height', 0))
                for y in range(post_top, post_top + post_height, 400):
                    page.evaluate(f"window.scrollTo(0, {y})")
                    page.wait_for_timeout(200)
            else:
                # 回退：滚动整个页面
                total_height = page.evaluate("document.body.scrollHeight")
                for y in range(0, total_height, 400):
                    page.evaluate(f"window.scrollTo(0, {y})")
                    page.wait_for_timeout(200)

            # ── 等待图片加载完成 ──
            page.evaluate("""() => {
                return new Promise(resolve => {
                    const imgs = document.querySelectorAll('#post_1 img');
                    let loaded = 0;
                    const total = imgs.length;
                    if (total === 0) return resolve();
                    imgs.forEach(img => {
                        if (img.complete) {
                            loaded++;
                            if (loaded >= total) resolve();
                        } else {
                            img.onload = img.onerror = () => {
                                loaded++;
                                if (loaded >= total) resolve();
                            };
                        }
                    });
                    // 最多等 3 秒
                    setTimeout(resolve, 3000);
                });
            }""")

            # ── 滚动回顶部 ──
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)

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

    def _extract_content_from_json(self, session, url: str) -> str:
        """通过 Discourse JSON API 获取完整的楼主帖子内容
        
        Discourse 的 .json 端点返回结构化数据，包含完整的 cooked HTML，
        不受页面截断、懒加载或 Cloudflare 渲染问题的影响。
        """
        try:
            # 构造 JSON URL：topic-url.json 或 topic-url/1.json
            json_url = url.rstrip('/')
            if not json_url.endswith('.json'):
                # 对于帖子链接如 /t/topic-slug/12345/5，取前两段
                parts = json_url.split('/')
                # 找到 /t/ 后的部分
                t_idx = -1
                for i, p in enumerate(parts):
                    if p == 't':
                        t_idx = i
                        break
                if t_idx >= 0 and len(parts) > t_idx + 2:
                    # 重建为 /t/slug/id 格式
                    json_url = '/'.join(parts[:t_idx + 3])
                json_url += '.json'
            
            logger.info(f"[LinuxDoPreview] JSON API 请求: {json_url}")
            resp = session.fetch(json_url)
            if resp.status != 200:
                logger.info(f"[LinuxDoPreview] JSON API 返回 {resp.status}")
                return ""
            
            import json
            data = json.loads(resp.body.decode("utf-8", errors="replace"))
            
            # 从 post_stream 中提取第一个帖子（楼主）
            post_stream = data.get("post_stream", {})
            posts = post_stream.get("posts", [])
            if not posts:
                return ""
            
            first_post = posts[0]
            cooked_html = first_post.get("cooked", "")
            if not cooked_html:
                return ""
            
            # 使用 lxml 解析 HTML 并提取纯文本
            if _lh is not None:
                tree = _lh.fromstring(cooked_html)
                return _clean_text(tree.text_content())
            
            # 回退：正则去标签
            text = re.sub(r"<[^>]+>", " ", cooked_html)
            text = re.sub(r"\s+", " ", text).strip()
            return html_mod.unescape(text)

        except Exception as e:
            logger.info(f"[LinuxDoPreview] JSON API 提取失败: {type(e).__name__}: {e}")
            return ""

    # ─────────── 登录支持（Cookie 注入） ───────────

    def _has_session_cookie(self) -> bool:
        """检查是否配置了会话 cookie"""
        cookie = self.config.get("linuxdo_session_cookie", "") or ""
        return bool(cookie.strip())

    def _has_auto_login(self) -> bool:
        """检查是否配置了自动登录凭据"""
        u = self.config.get("linuxdo_username", "") or ""
        p = self.config.get("linuxdo_password", "") or ""
        return bool(u.strip() and p.strip())

    def _has_remote_browser(self) -> bool:
        """检查是否配置了远程可视浏览器 CDP 端点"""
        endpoint = self.config.get("remote_browser_cdp_endpoint", "") or ""
        return bool(endpoint.strip())

    _COOKIE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    # linux.do / Discourse / Cloudflare 可能出现的 cookie 名
    _KNOWN_COOKIE_NAMES = {
        "_t", "_forum_session", "cf_clearance", "_bypass_cache", "dosp",
        "_pf", "_bblean", "theme_ids", "previousVisitAt", "messages-last-modified",
        "_ga", "_gid", "_gcl_au",
    }

    def _parse_cookie_pairs(self, cookie_str: str) -> list[dict]:
        """将用户配置的 cookie 字符串解析为 (name, value) 列表。

        支持三种输入：
        - 完整 Cookie 头（含分号）：'_t=xxx; _forum_session=yyy'
        - 单个 'name=value'（name 须是已知 cookie 名）：'_t=xxx'
        - 单个裸值（直接当作 _forum_session 的值，向后兼容）

        说明：Discourse 的 _forum_session 值是 base64，常带 '=' 填充，因此不能
        仅凭是否含 '=' 判断格式，否则会把裸值误判成 name=value。
        """
        pairs: list[dict] = []
        s = (cookie_str or "").strip()
        if not s:
            return pairs
        if ";" in s:
            # 完整 Cookie 头：按分号拆分
            for part in s.split(";"):
                part = part.strip()
                if "=" not in part:
                    continue
                name, value = part.split("=", 1)
                name = name.strip()
                if self._COOKIE_NAME_RE.match(name):
                    pairs.append({"name": name, "value": value.strip()})
        elif "=" in s:
            # 无分号但含 '='：仅当前缀是已知 cookie 名时才按 name=value 解析
            name, value = s.split("=", 1)
            name = name.strip()
            if name in self._KNOWN_COOKIE_NAMES and self._COOKIE_NAME_RE.match(name):
                pairs.append({"name": name, "value": value.strip()})
        if not pairs:
            # 裸值 → 当作 _forum_session（向后兼容）
            pairs.append({"name": "_forum_session", "value": s})
        return pairs

    def _inject_session_cookie(self, session, cookie_value: str = "") -> bool:
        """将会话 cookie 注入到当前浏览器上下文。

        注意：StealthySession 每次请求都是新建的浏览器上下文，cookie 不会跨
        请求保留，因此【每个会话都必须重新注入】。

        Returns: True 表示注入成功，False 表示失败
        """
        if not cookie_value:
            cookie_value = (self.config.get("linuxdo_session_cookie", "") or "").strip()
        if not cookie_value:
            return False

        ctx = session.context
        if not ctx:
            return False

        pairs = self._parse_cookie_pairs(cookie_value)
        if not pairs:
            return False

        cookies = []
        for p in pairs:
            # _t / _forum_session 是 HttpOnly；其余 cookie 按普通处理
            http_only = p["name"] in ("_t", "_forum_session")
            cookies.append({
                "name": p["name"],
                "value": p["value"],
                "domain": "linux.do",
                "path": "/",
                "httpOnly": http_only,
                "secure": True,
                "sameSite": "Lax",
            })

        try:
            ctx.add_cookies(cookies)
            logger.info(
                f"[LinuxDoPreview] 已注入会话 cookie: {[c['name'] for c in cookies]}"
            )
            return True
        except Exception as e:
            logger.warning(f"[LinuxDoPreview] Cookie 注入失败: {type(e).__name__}: {e}")
            return False

    def _check_login_state(self, session) -> bool:
        """检查当前会话是否已登录。

        使用 /notifications.json：已登录返回 200，匿名返回 403。
        （/session/current_user.json 对匿名用户也返回 404，无法区分，故弃用。）
        """
        try:
            resp = session.fetch(
                "https://linux.do/notifications.json", timeout=30000
            )
            return resp.status == 200
        except Exception:
            return False

    def _capture_context_cookies(self, session) -> str:
        """从当前浏览器上下文提取 linux.do 相关 cookie，序列化为 Cookie 头。"""
        ctx = session.context
        if not ctx:
            return ""
        try:
            cookies = ctx.cookies(["https://linux.do"])
        except Exception as e:
            logger.info(f"[LinuxDoPreview] 读取登录 Cookie 失败: {type(e).__name__}: {e}")
            return ""

        pairs = []
        for cookie in cookies:
            name = cookie.get("name", "")
            value = cookie.get("value", "")
            domain = cookie.get("domain", "")
            if not name or not value:
                continue
            if "linux.do" not in domain:
                continue
            pairs.append(f"{name}={value}")
        return "; ".join(pairs)

    @staticmethod
    def _selector_exists(page, selectors: list[str]) -> bool:
        for selector in selectors:
            try:
                if page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _fill_first(page, selectors: list[str], value: str) -> bool:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if locator.count() <= 0:
                    continue
                locator.first.fill(value)
                return True
            except Exception:
                continue
        return False

    @staticmethod
    def _click_first(page, selectors: list[str]) -> bool:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if locator.count() <= 0:
                    continue
                locator.first.click()
                return True
            except Exception:
                continue
        return False

    def _auto_login_and_capture(self, session) -> bool:
        """尝试使用用户名/密码登录 linux.do，并缓存登录后的 cookie。

        linux.do 当前可能启用 hCaptcha。该方法只做 best-effort 表单登录：
        成功则把上下文 cookie 缓存在内存中，失败则保持匿名访问。
        """
        username = (self.config.get("linuxdo_username", "") or "").strip()
        password = (self.config.get("linuxdo_password", "") or "").strip()
        if not username or not password:
            return False

        ctx = session.context
        if not ctx:
            return False

        timeout_ms = max(self.config.get("screenshot_timeout", 15) * 1000, 30000)
        page = None
        captcha_selectors = [
            "iframe[src*='hcaptcha']",
            "iframe[src*='captcha']",
            ".h-captcha",
            "[data-sitekey]",
            ".cf-turnstile",
            "iframe[src*='turnstile']",
        ]
        username_selectors = [
            "#login-account-name",
            "input[name='login']",
            "input[name='username']",
            "input[name='email']",
            "input[type='email']",
            "input[autocomplete='username']",
        ]
        password_selectors = [
            "#login-account-password",
            "input[name='password']",
            "input[type='password']",
            "input[autocomplete='current-password']",
        ]
        submit_selectors = [
            "#login-button",
            "button#login-button",
            "button[type='submit']",
            "button:has-text('登录')",
            "button:has-text('Log In')",
            "button:has-text('Login')",
            ".btn-primary",
        ]

        try:
            page = ctx.new_page()
            page.set_viewport_size({"width": 1280, "height": 900})
            page.goto("https://linux.do/login", wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1000)

            if self._check_login_state(session):
                cookie_value = self._capture_context_cookies(session)
                if cookie_value:
                    self._runtime_cookie_value = cookie_value
                logger.info("[LinuxDoPreview] 当前会话已处于登录状态")
                return True

            has_user = self._fill_first(page, username_selectors, username)
            has_pass = self._fill_first(page, password_selectors, password)
            if not (has_user and has_pass):
                logger.warning("[LinuxDoPreview] 未找到 linux.do 登录表单，账号登录失败")
                return False

            if self._selector_exists(page, captcha_selectors):
                logger.warning(
                    "[LinuxDoPreview] 检测到登录验证码，仍尝试提交；"
                    "若站点要求人工验证，本次会降级为匿名访问。"
                )

            clicked = self._click_first(page, submit_selectors)
            if not clicked:
                try:
                    page.keyboard.press("Enter")
                except Exception:
                    pass

            try:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except Exception:
                page.wait_for_timeout(3000)

            for _ in range(5):
                if self._check_login_state(session):
                    cookie_value = self._capture_context_cookies(session)
                    if not cookie_value:
                        logger.warning("[LinuxDoPreview] 登录成功但未能提取 Cookie")
                        return False
                    self._runtime_cookie_value = cookie_value
                    logger.info("[LinuxDoPreview] 账号登录成功，已缓存会话 Cookie")
                    return True
                if self._selector_exists(page, captcha_selectors):
                    logger.warning(
                        "[LinuxDoPreview] 账号登录被验证码阻止，"
                        "请改用 linuxdo_session_cookie。"
                    )
                    return False
                page.wait_for_timeout(1500)

            logger.warning("[LinuxDoPreview] 账号登录未通过验证，将匿名访问")
            return False
        except Exception as e:
            logger.warning(f"[LinuxDoPreview] 账号登录失败: {type(e).__name__}: {e}")
            return False
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    def _interactive_login_and_capture(self) -> bool:
        """打开可见浏览器，等待用户手动完成 hCaptcha 和登录。"""
        if not SCRAPLING_AVAILABLE:
            raise RuntimeError("Scrapling 未安装")

        username = (self.config.get("linuxdo_username", "") or "").strip()
        password = (self.config.get("linuxdo_password", "") or "").strip()
        timeout_s = max(int(self.config.get("interactive_login_timeout", 180)), 30)
        deadline = time.time() + timeout_s

        with _StealthySession(  # type: ignore[union-attr]
            headless=False, solve_cloudflare=True
        ) as session:
            ctx = session.context
            if not ctx:
                return False

            page = None
            try:
                page = ctx.new_page()
                page.set_viewport_size({"width": 1280, "height": 900})
                page.goto(
                    "https://linux.do/login",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                page.wait_for_timeout(1000)

                if username:
                    self._fill_first(page, [
                        "#login-account-name",
                        "input[name='login']",
                        "input[name='username']",
                        "input[name='email']",
                        "input[type='email']",
                        "input[autocomplete='username']",
                    ], username)
                if password:
                    self._fill_first(page, [
                        "#login-account-password",
                        "input[name='password']",
                        "input[type='password']",
                        "input[autocomplete='current-password']",
                    ], password)

                logger.info(
                    f"[LinuxDoPreview] 已打开可见登录窗口，等待用户完成登录（{timeout_s}s）"
                )
                while time.time() < deadline:
                    if self._check_login_state(session):
                        cookie_value = self._capture_context_cookies(session)
                        if not cookie_value:
                            logger.warning("[LinuxDoPreview] 手动登录成功但未能提取 Cookie")
                            return False
                        self._runtime_cookie_value = cookie_value
                        self._auth_check_done = True
                        self._logged_in = True
                        logger.info("[LinuxDoPreview] 手动登录成功，已缓存会话 Cookie")
                        return True
                    page.wait_for_timeout(1500)

                logger.warning("[LinuxDoPreview] 手动登录等待超时")
                return False
            except Exception as e:
                logger.warning(f"[LinuxDoPreview] 手动登录失败: {type(e).__name__}: {e}")
                return False
            finally:
                if page:
                    try:
                        page.close()
                    except Exception:
                        pass

    def _verify_and_cache_cookie(self, cookie_value: str) -> bool:
        """验证用户导入的 Cookie，并缓存到当前插件进程内存。"""
        cookie_value = (cookie_value or "").strip()
        if not cookie_value:
            return False
        if not SCRAPLING_AVAILABLE:
            raise RuntimeError("Scrapling 未安装")

        with _StealthySession(  # type: ignore[union-attr]
            headless=True, solve_cloudflare=True
        ) as session:
            if not self._inject_session_cookie(session, cookie_value):
                return False
            if not self._check_login_state(session):
                return False
            self._runtime_cookie_value = cookie_value
            self._auth_check_done = True
            self._logged_in = True
            self._last_cookie_status_ok = True
            self._last_cookie_alert_at = 0.0
            logger.info("[LinuxDoPreview] 运行时 Cookie 验证成功，已缓存到内存")
            return True

    def _pull_cookie_from_remote_browser(self) -> dict:
        """通过 Chrome DevTools Protocol 从远程可视浏览器读取 linux.do Cookie。"""
        endpoint = (self.config.get("remote_browser_cdp_endpoint", "") or "").strip()
        if not endpoint:
            return {
                "ok": False,
                "message": "未配置 remote_browser_cdp_endpoint",
                "cookie": "",
            }

        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as e:
            return {
                "ok": False,
                "message": f"Playwright 不可用: {type(e).__name__}: {e}",
                "cookie": "",
            }

        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(endpoint)
                contexts = browser.contexts
                if not contexts:
                    return {
                        "ok": False,
                        "message": "远程浏览器没有可读取的上下文",
                        "cookie": "",
                    }

                best_cookies = []
                for ctx in contexts:
                    cookies = ctx.cookies(["https://linux.do"])
                    if any(c.get("name") == "_t" for c in cookies):
                        best_cookies = cookies
                        break
                    if cookies and not best_cookies:
                        best_cookies = cookies

                if not best_cookies:
                    return {
                        "ok": False,
                        "message": "远程浏览器中未找到 linux.do Cookie，请先在可视浏览器里登录",
                        "cookie": "",
                    }

                pairs = []
                for cookie in best_cookies:
                    name = cookie.get("name", "")
                    value = cookie.get("value", "")
                    domain = cookie.get("domain", "")
                    if not name or not value:
                        continue
                    if "linux.do" not in domain:
                        continue
                    pairs.append(f"{name}={value}")

                cookie_value = "; ".join(pairs)
                if not cookie_value:
                    return {
                        "ok": False,
                        "message": "远程浏览器 Cookie 为空",
                        "cookie": "",
                    }

                return {
                    "ok": True,
                    "message": f"已从远程浏览器读取 {len(pairs)} 个 linux.do Cookie",
                    "cookie": cookie_value,
                }
        except Exception as e:
            return {
                "ok": False,
                "message": f"连接远程浏览器失败: {type(e).__name__}: {e}",
                "cookie": "",
            }

    def _pull_verify_and_cache_remote_cookie(self) -> dict:
        result = self._pull_cookie_from_remote_browser()
        if not result.get("ok"):
            return result

        cookie_value = result.get("cookie", "")
        if not self._verify_and_cache_cookie(cookie_value):
            return {
                "ok": False,
                "message": "已读取远程浏览器 Cookie，但验证未通过",
                "cookie": "",
            }
        return {
            "ok": True,
            "message": result.get("message", "Cookie 已读取并验证成功"),
            "cookie": "",
        }

    def _get_active_cookie_value(self) -> tuple[str, str]:
        config_cookie = (self.config.get("linuxdo_session_cookie", "") or "").strip()
        if config_cookie:
            return config_cookie, "配置 linuxdo_session_cookie"
        if self._runtime_cookie_value:
            return self._runtime_cookie_value, "运行时导入 Cookie"
        return "", "未配置"

    def _check_cookie_status(self) -> dict:
        """检查当前可用 Cookie 是否仍处于登录状态。"""
        cookie_value, source = self._get_active_cookie_value()
        if not cookie_value:
            return {
                "ok": False,
                "source": source,
                "message": "未配置 LinuxDo Cookie",
            }
        if not SCRAPLING_AVAILABLE:
            return {
                "ok": False,
                "source": source,
                "message": "Scrapling 未安装，无法验证 Cookie",
            }

        try:
            with _StealthySession(  # type: ignore[union-attr]
                headless=True, solve_cloudflare=True
            ) as session:
                if not self._inject_session_cookie(session, cookie_value):
                    return {
                        "ok": False,
                        "source": source,
                        "message": "Cookie 注入失败",
                    }
                ok = self._check_login_state(session)
                if ok:
                    self._auth_check_done = True
                    self._logged_in = True
                    return {
                        "ok": True,
                        "source": source,
                        "message": "Cookie 有效，LinuxDo 当前为已登录状态",
                    }
                self._logged_in = False
                return {
                    "ok": False,
                    "source": source,
                    "message": "Cookie 无效或已过期，LinuxDo 当前未登录",
                }
        except Exception as e:
            self._logged_in = False
            return {
                "ok": False,
                "source": source,
                "message": f"Cookie 检测失败: {type(e).__name__}: {e}",
            }

    def _get_status_notify_targets(self) -> list[str]:
        raw = (self.config.get("cookie_status_notify_targets", "") or "").strip()
        targets = set(self._runtime_notify_targets)
        if raw:
            for item in re.split(r"[\n,;]+", raw):
                item = item.strip()
                if item:
                    targets.add(item)
        return sorted(targets)

    def _start_status_task(self):
        interval = int(self.config.get("cookie_status_check_interval", 3600) or 0)
        if interval <= 0 or self._status_task:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._status_task = loop.create_task(self._cookie_status_loop())

    async def _cookie_status_loop(self):
        while True:
            raw_interval = int(self.config.get("cookie_status_check_interval", 3600) or 0)
            if raw_interval <= 0:
                await asyncio.sleep(60)
                continue
            interval = max(raw_interval, 60)
            await asyncio.sleep(interval)

            targets = self._get_status_notify_targets()
            if not targets:
                continue

            status = await asyncio \
                .get_event_loop() \
                .run_in_executor(_EXECUTOR, self._check_cookie_status)

            if not status.get("ok") and self._has_remote_browser():
                pulled = await asyncio \
                    .get_event_loop() \
                    .run_in_executor(_EXECUTOR, self._pull_verify_and_cache_remote_cookie)
                if pulled.get("ok"):
                    status = {
                        "ok": True,
                        "source": "远程可视浏览器",
                        "message": "Cookie 失效后已从远程可视浏览器自动刷新",
                    }

            ok = bool(status.get("ok"))
            now = time.time()
            cooldown = max(
                int(self.config.get("cookie_status_alert_cooldown", 21600) or 21600),
                300,
            )
            should_alert = (
                not ok
                and (
                    self._last_cookie_status_ok is not False
                    or now - self._last_cookie_alert_at >= cooldown
                )
            )
            self._last_cookie_status_ok = ok
            if not should_alert:
                continue

            self._last_cookie_alert_at = now
            message = (
                "⚠️ LinuxDo Cookie 状态异常\n"
                f"来源: {status.get('source', '未知')}\n"
                f"状态: {status.get('message', '未知错误')}\n"
                "请更新 linuxdo_session_cookie，或使用 /linuxdo_cookie 临时导入新的 _t。"
            )
            for target in targets:
                sent = await self._send_plain_message(target, message)
                if not sent:
                    logger.warning(
                        f"[LinuxDoPreview] Cookie 状态告警发送失败，target={target}"
                    )

    async def _send_plain_message(self, target: str, text: str) -> bool:
        """兼容不同 AstrBot 版本的主动发消息接口。"""
        sender = getattr(self.context, "send_message", None)
        if not sender:
            return False

        candidates = [text]
        try:
            from astrbot.api.message_components import Plain  # type: ignore
            candidates.append([Plain(text)])
        except Exception:
            pass

        for payload in candidates:
            try:
                result = sender(target, payload)
                if inspect.isawaitable(result):
                    await result
                return True
            except TypeError:
                continue
            except Exception as e:
                logger.warning(
                    f"[LinuxDoPreview] 主动发送消息失败: {type(e).__name__}: {e}"
                )
                return False
        return False

    def _ensure_authenticated(self, session) -> bool:
        """在已绕过 CF 的上下文中按需认证。

        重要：StealthySession 每次请求都会新建，浏览器上下文不跨请求保留，因此
        配置的 Cookie 必须【每次都注入】当前会话；而【是否登录】的校验结果可以
        缓存（Cookie 有效性不会在请求间变化）。

        逻辑：
        1) 配置了 linuxdo_session_cookie → 每次注入；首次校验后缓存结果
        2) 账号密码登录成功后 → 后续请求注入内存缓存的登录 Cookie
        3) 仅配置了用户名/密码 → 尝试表单登录一次，失败则匿名访问
        4) 都没配置 → 匿名访问
        """
        # ── 手动 Cookie：每次请求都注入（上下文是新建的） ──
        if self._has_session_cookie():
            cookie_value = (self.config.get("linuxdo_session_cookie", "") or "").strip()
            if not self._inject_session_cookie(session, cookie_value):
                self._auth_check_done = True
                self._logged_in = False
                return False
            # 校验结果只算一次（Cookie 有效性跨请求稳定）
            if not self._auth_check_done:
                self._logged_in = self._check_login_state(session)
                self._auth_check_done = True
                if self._logged_in:
                    logger.info("[LinuxDoPreview] Cookie 登录验证成功")
                else:
                    logger.warning(
                        "[LinuxDoPreview] 会话 Cookie 无效或已过期，将匿名访问。"
                        "请在浏览器重新获取 Cookie（推荐 _t，长效）后填入配置。"
                    )
            return self._logged_in

        # ── 账号密码登录成功后：每次请求都复用内存里的 Cookie ──
        if self._runtime_cookie_value:
            if self._inject_session_cookie(session, self._runtime_cookie_value):
                return self._logged_in

        # ── 远程可视浏览器：管理员已在浏览器里登录时，自动拉取 Cookie ──
        if self._has_remote_browser() and not self._remote_cookie_pull_done:
            self._remote_cookie_pull_done = True
            pulled = self._pull_verify_and_cache_remote_cookie()
            if pulled.get("ok") and self._runtime_cookie_value:
                if self._inject_session_cookie(session, self._runtime_cookie_value):
                    self._logged_in = True
                    return True
            logger.info(
                f"[LinuxDoPreview] 远程浏览器 Cookie 拉取未成功: "
                f"{pulled.get('message', '未知错误')}"
            )

        # ── 仅用户名/密码：尝试一次表单登录，遇到验证码则降级匿名 ──
        if self._has_auto_login() and not self._auth_check_done:
            self._auth_check_done = True
            self._logged_in = self._auto_login_and_capture(session)
            if self._logged_in:
                return True
            logger.warning(
                "[LinuxDoPreview] 账号密码登录未成功，将匿名访问。"
                "如果 linux.do 要求人机验证，请改用 linuxdo_session_cookie。"
            )

        # 都没配置 / 自动登录不可用 → 匿名
        self._logged_in = False
        return False

    def _fetch_topic_data(self, session, url: str) -> dict | None:
        """通过 Discourse JSON API 获取完整的主题数据
        
        返回的 dict 包含帖子原始数据（cooked HTML、作者、标签、统计等），
        可同时供文本提取和自定义 HTML 渲染使用。
        """
        try:
            json_url = url.rstrip('/')
            if not json_url.endswith('.json'):
                parts = json_url.split('/')
                t_idx = -1
                for i, p in enumerate(parts):
                    if p == 't':
                        t_idx = i
                        break
                if t_idx >= 0 and len(parts) > t_idx + 2:
                    json_url = '/'.join(parts[:t_idx + 3])
                json_url += '.json'

            logger.info(f"[LinuxDoPreview] 拉取 topic JSON: {json_url}")
            resp = session.fetch(json_url)
            if resp.status != 200:
                logger.info(f"[LinuxDoPreview] topic JSON 返回 {resp.status}")
                return None
            import json
            return json.loads(resp.body.decode("utf-8", errors="replace"))
        except Exception as e:
            logger.info(f"[LinuxDoPreview] topic JSON 拉取失败: {type(e).__name__}: {e}")
            return None

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
        if _lh is None:
            return ""
        tree = _lh.fromstring(html_str)
        # 使用更精确的选择器：只提取楼主的内容
        # #post_1 是楼主帖子的 ID
        post_1 = tree.cssselect("#post_1")
        if not post_1:
            # 回退：提取第一个 .cooked
            for el in tree.cssselect(".cooked"):
                text = _clean_text(el.text_content())
                if len(text) > 15:
                    return text
            return ""
        # 提取楼主帖子中的 .cooked 内容
        cooked = post_1[0].cssselect(".cooked")
        if cooked:
            return _clean_text(cooked[0].text_content())
        return ""

    def _extract_via_regex(self, html_str: str) -> str:
        # 使用更精确的正则表达式：匹配楼主帖子
        # 先尝试匹配 #post_1 的帖子
        post_1_match = re.search(
            r'<article[^>]*id="post_1"[^>]*>.*?<div\s+class="cooked">(.*?)</div>\s*</article>',
            html_str,
            re.DOTALL
        )
        if post_1_match:
            text = re.sub(r"<[^>]+>", " ", post_1_match.group(1))
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 15:
                return text
        # 回退：提取第一个 .cooked
        for m in re.finditer(
            r'<div\s+class="cooked">(.*?)</div>\s*</article>', html_str, re.DOTALL
        ):
            text = re.sub(r"<[^>]+>", " ", m.group(1))
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 15:
                return text
        return ""

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

    @staticmethod
    def _safe_title(topic_data: dict | None) -> str:
        """从 topic JSON 中安全提取标题（剥除尾部 - Linux DO 后缀）"""
        if not topic_data:
            return "无标题"
        title = topic_data.get("title") or topic_data.get("fancy_title") or "无标题"
        title = re.sub(
            r"\s*[-–—|]\s*(LINUX\s*DO|LINUXDO).*$", "", title, flags=re.IGNORECASE
        )
        return title.strip() or "无标题"

    def _extract_content_from_topic_data(self, topic_data: dict) -> str:
        """从已拉取的 topic JSON 中提取楼主帖子纯文本"""
        try:
            post_stream = topic_data.get("post_stream", {}) or {}
            posts = post_stream.get("posts", []) or []
            if not posts:
                return ""
            cooked_html = posts[0].get("cooked", "") or ""
            if not cooked_html:
                return ""
            if _lh is not None:
                tree = _lh.fromstring(cooked_html)
                return _clean_text(tree.text_content())
            text = re.sub(r"<[^>]+>", " ", cooked_html)
            text = re.sub(r"\s+", " ", text).strip()
            return html_mod.unescape(text)
        except Exception as e:
            logger.info(f"[LinuxDoPreview] topic JSON 文本提取失败: {type(e).__name__}: {e}")
            return ""

    # ─────────── HTML 预览渲染（API + Scrapling 协作） ───────────

    def _build_preview_html(self, topic_data: dict, url: str) -> str:
        """根据 topic JSON 生成自定义预览 HTML
        
        优点：布局干净、包含完整内容（不受 Discourse 页面截断/懒加载影响）、
        可控制样式适配聊天平台预览图。
        """
        # 抽取关键字段
        title = html_mod.escape(topic_data.get("title", "无标题") or "无标题")
        fancy_title = html_mod.escape(topic_data.get("fancy_title", title) or title)
        posts_count = topic_data.get("posts_count", 0)
        views = topic_data.get("views", 0)
        like_count = topic_data.get("like_count", 0)
        created_at = topic_data.get("created_at", "")
        tags = topic_data.get("tags", []) or []

        post_stream = topic_data.get("post_stream", {}) or {}
        posts = post_stream.get("posts", []) or []
        if not posts:
            return ""
        first = posts[0]
        author_name = html_mod.escape(first.get("name", "") or first.get("username", "") or "")
        author_username = html_mod.escape(first.get("username", "") or "")
        author_initial = (author_name or author_username or "?").strip()[:1].upper()
        author_avatar_raw = first.get("avatar_template", "") or ""
        # 绝对化 + 替换 {size}。Discourse 模板形如：
        #   //host/.../avatar.png{size}    → 需保留 {size} 占位
        #   //host/.../avatar.png          → 无占位，原样
        # 任何模板中包含 {size} 都要换为像素数值；否则不强制改动
        if author_avatar_raw and author_avatar_raw.startswith("//"):
            author_avatar = "https:" + author_avatar_raw
        elif author_avatar_raw and author_avatar_raw.startswith("/"):
            author_avatar = "https://linux.do" + author_avatar_raw
        else:
            author_avatar = author_avatar_raw
        if "{size}" in author_avatar:
            author_avatar = author_avatar.replace("{size}", "120")
        post_created = first.get("created_at", "") or ""
        post_like = first.get("like_count", 0)
        cooked_html = first.get("cooked", "") or ""

        # 把 Discourse 相对资源 URL 补全为绝对 URL
        cooked_html = self._normalize_cooked_urls(cooked_html)

        # 发布时间格式化
        created_text = ""
        if post_created:
            try:
                created_text = post_created.split("T")[0]
            except Exception:
                created_text = post_created

        tags_html = "".join(
            f'<span class="tag">#{html_mod.escape(t["name"] if isinstance(t, dict) else str(t))}</span>'
            for t in tags[:6]
        )

        # 头像、统计数字格式化
        views_text = self._format_count(views)
        posts_text = self._format_count(posts_count)
        likes_text = self._format_count(like_count)

        # 头像 img 标签（未提供 URL 时仅渲染 fallback 块）
        if author_avatar:
            avatar_img_html = (
                '<img class="avatar" src="'
                + html_mod.escape(author_avatar)
                + '" alt="avatar" onerror="this.style.display='
                + chr(39) + 'none' + chr(39) + '">'
            )
        else:
            avatar_img_html = ''

        # 完整预览 HTML（含内联 CSS）
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
      "Hiragino Sans GB", "Microsoft YaHei", Arial, sans-serif;
    background: #f5f6f8;
    color: #1c1c1c;
    padding: 24px;
    line-height: 1.6;
  }}
  .card {{
    background: #ffffff;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    max-width: 760px;
    margin: 0 auto;
    overflow: hidden;
  }}
  .header {{
    padding: 20px 24px 16px 24px;
    border-bottom: 1px solid #eef0f3;
  }}
  .title {{
    font-size: 20px;
    font-weight: 700;
    color: #1769c4;
    margin: 0 0 10px 0;
    line-height: 1.4;
    word-break: break-word;
  }}
  .meta {{
    display: flex;
    align-items: center;
    gap: 10px;
    color: #6a737c;
    font-size: 13px;
  }}
  .meta img.avatar {{
    width: 28px; height: 28px; border-radius: 50%;
    object-fit: cover; background: #ddd;
  }}
  .meta .avatar-wrap {{
    position: relative;
    width: 28px; height: 28px;
    display: inline-block;
  }}
  .meta .avatar-wrap img {{
    position: absolute; inset: 0;
  }}
  .meta .avatar-fallback {{
    position: absolute; inset: 0;
    width: 28px; height: 28px;
    border-radius: 50%;
    background: linear-gradient(135deg, #1769c4, #5a3ec8);
    color: #fff; font-weight: 600;
    display: flex; align-items: center; justify-content: center;
    font-size: 13px;
    text-transform: uppercase;
  }}
  .meta .name {{ color: #1c1c1c; font-weight: 500; }}
  .stats {{
    padding: 10px 24px;
    display: flex;
    gap: 18px;
    color: #6a737c;
    font-size: 13px;
    border-bottom: 1px solid #eef0f3;
    background: #fafbfc;
  }}
  .stats span::before {{ margin-right: 4px; }}
  .tags {{
    padding: 10px 24px 0 24px;
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }}
  .tag {{
    background: #e8f0fe;
    color: #1769c4;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
  }}
  .content {{
    padding: 16px 24px 8px 24px;
    word-break: break-word;
  }}
  .content p {{ margin: 0 0 10px 0; }}
  .content h1, .content h2, .content h3 {{ margin: 16px 0 8px 0; }}
  .content img {{
    max-width: 100%;
    height: auto;
    border-radius: 6px;
    display: block;
    margin: 8px 0;
  }}
  .content pre, .content code {{
    background: #f6f8fa;
    border-radius: 4px;
    padding: 2px 6px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 13px;
  }}
  .content pre {{ padding: 10px 12px; overflow-x: auto; }}
  .content blockquote {{
    border-left: 3px solid #d0d7de;
    margin: 8px 0;
    padding: 0 12px;
    color: #57606a;
    background: #f6f8fa;
  }}
  .content a {{ color: #1769c4; text-decoration: none; }}
  .content ul, .content ol {{ padding-left: 24px; }}
  .footer {{
    padding: 12px 24px 18px 24px;
    border-top: 1px solid #eef0f3;
    color: #6a737c;
    font-size: 12px;
    word-break: break-all;
  }}
  .footer a {{ color: #1769c4; text-decoration: none; }}
</style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h1 class="title">{fancy_title}</h1>
      <div class="meta">
        <div class="avatar-wrap">
          {avatar_img_html}
          <div class="avatar-fallback">{html_mod.escape(author_initial)}</div>
        </div>
        <span class="name">{author_name}</span>
        <span>·</span>
        <span>{html_mod.escape(created_text)}</span>
      </div>
    </div>
    <div class="stats">
      <span>👀 {views_text}</span>
      <span>💬 {posts_text}</span>
      <span>❤ {likes_text}</span>
    </div>
    {('<div class="tags">' + tags_html + '</div>') if tags else ''}
    <div class="content">
      {cooked_html}
    </div>
    <div class="footer">
      🔗 <a href="{html_mod.escape(url)}">{html_mod.escape(url)}</a>
    </div>
  </div>
</body>
</html>"""

    @staticmethod
    def _format_count(n: int) -> str:
        try:
            n = int(n)
        except (TypeError, ValueError):
            return str(n)
        if n >= 10000:
            return f"{n/10000:.1f}w"
        if n >= 1000:
            return f"{n/1000:.1f}k"
        return str(n)

    @staticmethod
    def _normalize_cooked_urls(cooked_html: str) -> str:
        """将 cooked 中的相对资源 URL 转绝对 URL，剥离轻臾框包裹与 meta 信息

        Discourse 的话题里图片常被包在多层 div 中：
          <div class="lightbox-wrapper">
            <a class="lightbox" href="...">
              <img src="...">
            </a>
            <div class="meta">
              <span class="filename">image.png</span>
              <span>988×703 46.8 KB</span>
            </div>
          </div>
        只保留 <img>、丢弃 meta 信息，避免图加载失败后占据巨大空白。
        """
        if not cooked_html:
            return ""
        try:
            import re as _re
            # 1) 绝对化 src/href（相对与协议无关 URL）
            cooked_html = _re.sub(
                r'(src|href)="(//[^"]+)"',
                r'\1="https:\2',
                cooked_html,
            )
            cooked_html = _re.sub(
                r'(src|href)="(/uploads/[^"]+)"',
                r'\1="https://linux.do\2',
                cooked_html,
            )

            # 2) 整块剥离 lightbox-wrapper：仅保留内部 <img>，丢弃其余
            def _pick_imgs(block: str) -> str:
                imgs = _re.findall(r'<img\b[^>]*>', block, flags=_re.IGNORECASE)
                return "".join(imgs)

            cooked_html = _re.sub(
                r'<div[^>]*class="[^"]*lightbox-wrapper[^"]*"[^>]*>(.*?)</div>',
                lambda m: _pick_imgs(m.group(1)),
                cooked_html,
                flags=_re.DOTALL,
            )

            # 3) 退路：直接裸的 <a class="lightbox"> 包裹，剥 a、保留 img
            cooked_html = _re.sub(
                r'<a [^>]*class="[^"]*\blightbox\b[^"]*"[^>]*>(.*?)</a>',
                r'\1',
                cooked_html,
                flags=_re.DOTALL,
            )

            # 4) 删除所有残留的 meta 信息块（文件尺寸、文件名、下载按钮等）
            cooked_html = _re.sub(
                r'<div[^>]*class="[^"]*\bmeta\b[^"]*"[^>]*>.*?</div>',
                '',
                cooked_html,
                flags=_re.DOTALL,
            )
            cooked_html = _re.sub(
                r'<span[^>]*class="[^"]*\bfilename\b[^"]*"[^>]*>.*?</span>',
                '',
                cooked_html,
                flags=_re.DOTALL,
            )

            # 5) 删除代码块顶部的工具栏（copy/undo 按钮）防止占位
            cooked_html = _re.sub(
                r'<div[^>]*class="[^"]*\bcodeblock-buttons\b[^"]*"[^>]*>.*?</div>',
                '',
                cooked_html,
                flags=_re.DOTALL,
            )
            cooked_html = _re.sub(
                r'<pre[^>]*>\s*<div[^>]*class="[^"]*\bpre-actions\b[^"]*"[^>]*>.*?</div>',
                '<pre>',
                cooked_html,
                flags=_re.DOTALL,
            )

            # 6) 删除 download 按钮、悬浮提示等装饰
            cooked_html = _re.sub(
                r'<a[^>]*class="[^"]*\bdownload[^"]*"[^>]*>.*?</a>',
                '',
                cooked_html,
                flags=_re.DOTALL,
            )

        except Exception:
            pass
        return cooked_html

    def _render_html_screenshot(self, session, html: str, save_path: Path) -> Path | None:
        """在已破解 CF 的浏览器上下文中渲染自定义 HTML 并截图
        
        page.set_content() 不走网络导航，纯本地渲染：零 Cloudflare、零超时、
        零依赖 Discourse 页面布局。content-length 限制为实际内容大小。
        """
        timeout_ms = self.config.get("screenshot_timeout", 15) * 1000
        if not html:
            return None
        try:
            ctx = session.context
            if not ctx:
                return None
            page = ctx.new_page()
            page.set_viewport_size({"width": 820, "height": 1200})

            # 设置内容，等待图片资源加载
            page.set_content(html, wait_until="domcontentloaded", timeout=timeout_ms)

            # 主动等所有 <img> 加载完成（最多 3s），并剔除加载失败的图
            page.evaluate("""() => new Promise(resolve => {
                const imgs = document.querySelectorAll('img');
                if (!imgs.length) return resolve();
                let done = 0;
                const tick = (img) => {
                    done++;
                    // 图加载失败：移除 <img> 避免占位巨大空白
                    if (img.complete && img.naturalWidth === 0) {
                        img.remove();
                    }
                    if (done >= imgs.length) resolve();
                };
                imgs.forEach(img => {
                    if (img.complete) tick(img);
                    else {
                        img.addEventListener('load', () => tick(img), { once: true });
                        img.addEventListener('error', () => tick(img), { once: true });
                    }
                });
                setTimeout(resolve, 3000);
            })""")

            page.wait_for_timeout(300)

            # ── 自适应截图：总是优先对 .card 元素截图，按内容实际边界拍 ──
            # 元素截图零空白、零截断，不受 viewport 高度限制。
            # `screenshot_full_page` 仅作为后备回退：元素截图失败时才使用。
            card_locator = page.locator(".card")
            full_page = self.config.get("screenshot_full_page", True)
            try:
                if card_locator.count() > 0:
                    card_locator.first.screenshot(
                        path=str(save_path),
                        timeout=timeout_ms,
                    )
                else:
                    page.screenshot(
                        path=str(save_path),
                        full_page=full_page,
                        timeout=timeout_ms,
                    )
            except Exception:
                # 回退：若元素截图失败（少见），退到全页截图
                page.screenshot(
                    path=str(save_path),
                    full_page=full_page,
                    timeout=timeout_ms,
                )
            sz = save_path.stat().st_size
            logger.info(
                f"[LinuxDoPreview] 渲染截图: {save_path.name} ({sz / 1024:.1f} KB)"
            )
            page.close()
            return save_path
        except Exception as e:
            logger.warning(f"[LinuxDoPreview] HTML 渲染失败: {type(e).__name__}: {e}")
            return None

    # ─────────── 管理指令 ───────────

    @filter.command("linuxdo_stats")
    async def show_stats(self, event: AstrMessageEvent):
        self._start_status_task()
        screenshots = list(self.screenshot_dir.glob("*.png"))
        cache_size = sum(f.stat().st_size for f in screenshots) / 1024
        yield event.plain_result(
            f"📊 LinuxDo Preview 统计\n"
            f"  请求总数: {self._stats['total']}\n"
            f"  缓存命中: {self._stats['cache_hit']}\n"
            f"  错误次数: {self._stats['error']}\n"
            f"  缓存截图: {len(screenshots)} ({cache_size:.1f} KB)"
        )

    @filter.command("linuxdo_cookie_status")
    async def cookie_status(self, event: AstrMessageEvent):
        self._start_status_task()
        yield event.plain_result("🔐 正在检测 LinuxDo Cookie 状态…")
        try:
            status = await asyncio \
                .get_event_loop() \
                .run_in_executor(_EXECUTOR, self._check_cookie_status)
            icon = "✅" if status.get("ok") else "⚠️"
            targets = self._get_status_notify_targets()
            current_origin = getattr(event, "unified_msg_origin", "") or ""
            extra = ""
            if current_origin:
                extra = f"\n当前会话 ID: {current_origin}"
            yield event.plain_result(
                f"{icon} LinuxDo Cookie 状态\n"
                f"来源: {status.get('source', '未知')}\n"
                f"状态: {status.get('message', '未知')}\n"
                f"定时通知目标数: {len(targets)}"
                f"{extra}"
            )
        except Exception as e:
            logger.error(f"[LinuxDoPreview] Cookie 状态检测失败: {type(e).__name__}: {e}")
            yield event.plain_result(f"❌ Cookie 状态检测失败: {str(e)[:200]}")

    @filter.command("linuxdo_cookie_watch")
    async def watch_cookie_status(self, event: AstrMessageEvent):
        self._start_status_task()
        origin = getattr(event, "unified_msg_origin", "") or ""
        if not origin:
            yield event.plain_result(
                "⚠️ 无法读取当前会话 ID。请在配置项 cookie_status_notify_targets "
                "中手动填写通知目标。"
            )
            return
        self._runtime_notify_targets.add(origin)
        yield event.plain_result(
            "✅ 已将当前会话加入 LinuxDo Cookie 状态告警目标。\n"
            "这是运行时设置，插件重载或 AstrBot 重启后失效；长期使用请写入 "
            "cookie_status_notify_targets 配置。"
        )

    @filter.command("linuxdo_login")
    async def interactive_login(self, event: AstrMessageEvent):
        self._start_status_task()
        timeout_s = max(int(self.config.get("interactive_login_timeout", 180)), 30)
        yield event.plain_result(
            f"🔐 正在打开 linux.do 登录窗口，请在 {timeout_s} 秒内手动完成 hCaptcha 和登录…\n"
            "窗口会出现在运行 AstrBot 的那台机器上。"
        )
        try:
            ok = await asyncio \
                .get_event_loop() \
                .run_in_executor(_EXECUTOR, self._interactive_login_and_capture)
            if ok:
                yield event.plain_result("✅ LinuxDo 手动登录成功，已缓存会话 Cookie。")
            else:
                yield event.plain_result(
                    "⚠️ LinuxDo 手动登录未成功或已超时。"
                    "如果窗口没有弹出，请确认 AstrBot 运行环境支持桌面 GUI。"
                )
        except Exception as e:
            logger.error(f"[LinuxDoPreview] 手动登录命令失败: {type(e).__name__}: {e}")
            yield event.plain_result(f"❌ 手动登录失败: {str(e)[:200]}")

    @filter.command("linuxdo_cookie")
    async def import_cookie(self, event: AstrMessageEvent):
        self._start_status_task()
        message = event.message_str or ""
        cookie_value = re.sub(
            r"^\s*/?linuxdo_cookie(?:\s+)?",
            "",
            message,
            count=1,
            flags=re.IGNORECASE,
        ).strip()
        if not cookie_value or cookie_value == message.strip():
            yield event.plain_result(
                "用法：/linuxdo_cookie _t=你的值\n"
                "也支持完整 Cookie 头。请只在私聊或可信管理渠道使用；"
                "该 Cookie 只缓存在内存，重启或重载后失效。"
            )
            return

        yield event.plain_result("🔐 正在验证 LinuxDo Cookie…")
        try:
            ok = await asyncio \
                .get_event_loop() \
                .run_in_executor(_EXECUTOR, self._verify_and_cache_cookie, cookie_value)
            if ok:
                yield event.plain_result(
                    "✅ LinuxDo Cookie 验证成功，已缓存到当前插件进程内存。"
                )
            else:
                yield event.plain_result(
                    "⚠️ LinuxDo Cookie 验证失败。请确认复制的是登录后的 `_t` "
                    "或完整 Cookie 头，且没有多余空格。"
                )
        except Exception as e:
            logger.error(f"[LinuxDoPreview] Cookie 导入失败: {type(e).__name__}: {e}")
            yield event.plain_result(f"❌ Cookie 导入失败: {str(e)[:200]}")

    @filter.command("linuxdo_cookie_pull")
    async def pull_cookie(self, event: AstrMessageEvent):
        self._start_status_task()
        endpoint = (self.config.get("remote_browser_cdp_endpoint", "") or "").strip()
        if not endpoint:
            yield event.plain_result(
                "⚠️ 未配置 remote_browser_cdp_endpoint。\n"
                "请先部署带 CDP 的可视浏览器，并把端点填入配置，"
                "例如 http://chromium:9222。"
            )
            return

        yield event.plain_result("🔐 正在从远程可视浏览器读取 LinuxDo Cookie…")
        try:
            result = await asyncio \
                .get_event_loop() \
                .run_in_executor(_EXECUTOR, self._pull_verify_and_cache_remote_cookie)
            if result.get("ok"):
                yield event.plain_result(
                    f"✅ {result.get('message', 'Cookie 已读取并验证成功')}，"
                    "已缓存到当前插件进程内存。"
                )
            else:
                yield event.plain_result(
                    f"⚠️ 远程浏览器 Cookie 获取失败: {result.get('message', '未知错误')}"
                )
        except Exception as e:
            logger.error(f"[LinuxDoPreview] 远程 Cookie 拉取失败: {type(e).__name__}: {e}")
            yield event.plain_result(f"❌ 远程 Cookie 拉取失败: {str(e)[:200]}")

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
