# 更新日志

本项目所有显著变更都记录在此文件中。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 安全
- **自定义 HTML 预览改为白名单清洗**：渲染 Discourse cooked HTML 前移除脚本、事件属性、表单、iframe、SVG、外站媒体与 `javascript:` / `data:` / `file:` 等危险 URL，避免主题正文携带主动内容影响截图渲染上下文
- **HTML 清洗失败时 fail-closed**：若清洗器异常，预览内容降级为纯文本，不再回退到原始 cooked HTML
- **补充共享 Cookie 风险提示**：文档明确说明配置 Cookie 后，群聊中任意可触发插件的链接都会使用该账号读取 linux.do 内容，建议仅在可信会话或专用 Bot 中启用

### 修复
- 修复 `linux.do` 链接识别误接受相似域名的问题，仅处理真实 `linux.do` 域名
- 修复 Discourse 主题 JSON URL 构造会受回复楼层、查询参数或 fragment 干扰的问题
- 修复 lxml 提取为空时不会回退正则提取的问题
- 修复 API 渲染生成无效/过小截图时不会自动回退页面截图的问题
- 修正 `screenshot_full_page` 文档与配置提示，明确它只影响元素级卡片截图失败后的页面截图回退

### 测试
- 新增 URL 识别、截图回退、HTML 清洗、清洗异常降级、lightbox/meta 剥离与 JSON URL 构造回归测试

## [1.2.1] - 2026-06-16

### 修复
- **修复登录始终“假成功”问题**：linux.do 登录表单启用了 hCaptcha 人机验证，自动化浏览器无法通过，原自动登录永远不可能成功；而旧代码抓取的是匿名会话本就存在的 `_forum_session` cookie 并误报“自动登录成功”，导致受限主题一直返回 404。现在改为明确提示自动登录不可用，降级为匿名访问
- **修复 Cookie 注入跨请求丢失**：StealthySession 每次请求都是新建的浏览器上下文，旧代码首次校验后缓存了登录态却不再向新会话注入 Cookie，导致只有插件加载后第一条消息能登录、之后全部匿名。现在改为【每个会话都重新注入】配置的 Cookie
- **更换可靠的登录校验端点**：`/session/current_user.json` 对匿名用户也返回 404，无法区分登录与否；改用 `/notifications.json`（匿名 403、登录 200）
- **Cookie 配置支持多格式**：`linuxdo_session_cookie` 现支持完整 Cookie 头（`_t=xxx; _forum_session=yyy`）、单个 `name=value`（已知 cookie 名）、以及裸值（向后兼容当作 `_forum_session`）。Discourse 会话值是 base64 常带 `=` 填充，解析器已正确区分裸值与 name=value

### 变更
- 移除无效的账号密码自动登录代码（`_auto_login_and_capture`）；`linuxdo_username` / `linuxdo_password` 配置项保留仅为兼容，不再生效
- 推荐改用长效的 `_t` cookie（约 1 年有效期）而非短效 `_forum_session`（约 2 周）
- 配置项 hint、README 登录说明同步更新

## [1.2.0] - 2026-06-16

### 新增
- **会话 Cookie 注入访问受限内容**：配置 `linuxdo_session_cookie` 后，插件自动将 cookie 注入 StealthySession 的浏览器上下文，可访问受限分类、私信等非公开内容。留空则保持匿名访问
- **自动登录获取 Cookie**：配置 `linuxdo_username` + `linuxdo_password` 后，插件通过 Playwright 自动登录并抓取 `_forum_session` cookie，无需手动复制
- 获取方式（手动）：浏览器登录 linux.do → F12 → Application → Cookies → linux.do → `_forum_session` → 复制 Value
- Cookie 注入后自动验证登录态，无效/过期时降级为匿名访问

### 变更
- 替换原有的 Playwright 表单登录方案（依赖 SPA 渲染、CSRF 处理，不够稳定）为双模式认证：手动 Cookie 注入 + 自动登录抓取

### 配置
- 新增 `linuxdo_session_cookie`（string，可选）：手动 Cookie 值
- 新增 `linuxdo_username`（string，可选）：自动登录用户名
- 新增 `linuxdo_password`（string，可选）：自动登录密码
- 优先级：手动 Cookie > 自动登录 > 匿名访问

## [1.1.3] - 2026-06-16

### 修复
- **截图完全脱离 `screenshot_full_page` 配置影响**：之前 `.card` 元素截图门控在 `if full_page` 后面，当用户配置 `full_page=false` 时回退到 `page.screenshot()` 的 viewport 模式，导致短帖留下 2000+px 空白、长帖被截断。现在元素截图成为唯一默认路径，`full_page` 仅作后备。短帖 (a3a7a0d) 从 1640×2400 缩到 1520×698，长帖 (3e6e0454) 从 1640×2400 截断的变成 1520×2596 完整，两种配置下结果完全一致

## [1.1.2] - 2026-06-16

### 修复
- **截图自适应尺寸，消除巨大空白**：`_render_html_screenshot` 改用 `page.locator('.card').screenshot()` 元素级截图，避免 `full_page=True` 捕获 `document.body.scrollHeight` 时因 viewport 撑高带来的大量空白区域。短帖从 1640×2400 缩减为 1520×678（-72%），长帖从 1640×4164 缩减为 1520×2874（-31%），零截断、零空白。元素截图失败时回退到全页模式

## [1.1.1] - 2026-06-16

### 修复
- **截图渲染清理 Discourse meta 残留**：`_normalize_cooked_urls` 剥离 `<div class="lightbox-wrapper">` 时改为仅保留 `<img>`，丢弃内嵌的 `<div class="meta">`（文件名、尺寸、下载按钮等），避免加载失败后出现 "image 988×703 46.8 KB" 这类文字
- **Broken image 不再占据巨大空白**：`_render_html_screenshot` 在图片加载完成后用 JS 检测 `naturalWidth==0` 的图并 `img.remove()`，消除 988×703 像素的预留空白
- **代码块 toolbar 不再泄露**：剥离 `<div class="codeblock-buttons">` 与 `<pre>` 内的 `<div class="pre-actions">`
- **Download 装饰链接剥离**：移除 Discourse 主题包渲染的 `<a class="...download...">` 装饰
- **头像占位符处理**：仅当 `avatar_template` 含 `{size}` 时才替换，避免字面量 `{size}` 被当作 URL 一部分去请求导致 404
- **头像优雅 fallback**：未提供 URL 或加载失败时，自动渲染带首字母的渐变圆形（onerror + CSS fallback）

## [1.1.0] - 2026-06-16

### 新增
- **API + 自定义 HTML 渲染流水线**：复用 StealthySession 调 Discourse `/t/{id}.json` 拿完整数据，再用 `page.set_content()` 渲染干净的预览卡片 HTML。完全摆脱对 Discourse 页面 DOM 状态、JS 截断、懒加载的依赖
- 新增配置项 `use_api_render`（默认开启），可通过配置切换新旧渲染方案
- 配置界面中文化（`description` / `hint` 全部译为中文）
- 新增辅助方法：
  - `_fetch_topic_data` — 拉取完整 topic JSON
  - `_safe_title` — 从 JSON 安全提取标题
  - `_extract_content_from_topic_data` — 从已拉取的 JSON 抽纯文本
  - `_build_preview_html` — 生成内联 CSS 卡片
  - `_normalize_cooked_urls` — 相对资源 URL 补全 + 剥 lightbox 包裹
  - `_format_count` — 1k/1w 友好计数
  - `_render_html_screenshot` — 纯本地 HTML 渲染截图

### 变更
- `metadata.yaml` 中 `short_desc` / `desc` 改写为描述双渲染方案
- `metadata.yaml` 版本号 `1.0.0` → `1.1.0`

### 修复
- 自定义 HTML 渲染时正确处理 Discourse tags 字段（数组中元素为 `dict` 而非 `str`）

### 兼容
- 旧路径（访问原页 + JS 隐藏 + 截图）仍保留；将 `use_api_render` 设为 `false` 即可切回

---

## [1.0.0] - 2025-06-15

### 新增
- 首次发布
- 自动检测聊天消息中的 `linux.do` 链接
- 使用 [Scrapling](https://github.com/D4Vinci/Scrapling) 的 `StealthySession` 绕过 Cloudflare Turnstile
- 两步法：先 `fetch` 拿 HTML/cookies，再新建标签页截图（复用 `cf_clearance`，不重复触发验证）
- 截图时通过 JS 隐藏非楼主内容（导航栏、侧边栏、回复帖），只保留第一篇帖子
- 提取标题与正文前 400 字作为文本摘要
- 截图缓存（30 分钟 TTL），相同链接 50KB 以上才视为有效
- 异步非阻塞（`ThreadPoolExecutor` + `run_in_executor`）
- 管理指令 `/linuxdo_stats`、`/linuxdo_clean`
- 4 个可配置项：`cache_ttl`、`max_content_length`、`screenshot_timeout`、`screenshot_full_page`

### 修复（首版累积）
- 修复 `scrapling` 版本约束（`requirements.txt`）
- 修复黑屏问题与文本提取 bug
- 截图缓存加入最小尺寸校验（> 50KB 才视为有效）
- 补全 `metadata.yaml` 中缺失的 `repo` 字段（用于插件市场）
- 集成配置项、线程安全、清理逻辑（Code Review 整改）
- 截图默认恢复为 `full_page=True`，确保完整捕获
- 截图时只截取首楼（隐藏所有回复帖）
- 通过展开 Discourse 截断的内容 + 滚动触发懒加载，确保完整捕获楼主贴

[1.2.0]: https://github.com/sakuradairong/astrbot_plugin_linuxdo/compare/7f3831f...HEAD
[1.1.3]: https://github.com/sakuradairong/astrbot_plugin_linuxdo/compare/0496d68...6aae30e
[1.1.2]: https://github.com/sakuradairong/astrbot_plugin_linuxdo/compare/7dda0e5...0496d68
[1.1.1]: https://github.com/sakuradairong/astrbot_plugin_linuxdo/compare/f17dd28...26336b7
[1.1.0]: https://github.com/sakuradairong/astrbot_plugin_linuxdo/compare/da9ad4d...6de4c31
[1.0.0]: https://github.com/sakuradairong/astrbot_plugin_linuxdo/releases/tag/5f41aa7
