# 更新日志

本项目所有显著变更都记录在此文件中。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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

[1.1.0]: https://github.com/sakuradairong/astrbot_plugin_linuxdo/compare/da9ad4d...6de4c31
[1.0.0]: https://github.com/sakuradairong/astrbot_plugin_linuxdo/releases/tag/5f41aa7
