# astrbot_plugin_linuxdo - LinuxDo 链接预览插件 🚀

自动检测聊天消息中的 `linux.do` 链接，绕过 Cloudflare Turnstile 防护，
**截图并提取内容摘要**发送预览。

## ✨ 功能

- 🔗 **自动检测** — 聊天中出现 `linux.do` 链接立即触发
- 🛡️ **绕过 Cloudflare** — 使用 [Scrapling](https://github.com/D4Vinci/Scrapling) 的 StealthySession 自动解 Turnstile
- 📸 **智能截图** — 自适应卡片渲染，完整楼主内容，无空白/截断
- 📝 **内容摘要** — 通过 Discourse JSON API 提取完整楼主内容（无截断）
- 🔒 **会话 Cookie** — 可选配置浏览器 Cookie，访问受限分类、私信等非公开内容（账号密码自动登录因 hCaptcha 已移除）
- ⚡ **异步非阻塞** — Scrapling 在独立线程池运行，不阻塞 AstrBot 主循环
- 💾 **缓存机制** — 30 分钟内相同链接直接返回缓存截图
- 🧹 **缓存管理** — `/linuxdo_stats` 查看统计，`/linuxdo_clean` 清理缓存

## 📦 安装

### 1. 安装插件

将 `astrbot_plugin_linuxdo` 目录放入 AstrBot 的 `data/plugins/` 目录。

### 2. 安装依赖

```bash
# 进入 AstrBot 环境
cd AstrBot

# 安装插件依赖（Scrapling、lxml、Cookie 加密依赖）
pip install -r data/plugins/astrbot_plugin_linuxdo/requirements.txt
scrapling install

# 或者使用 pipx（推荐）
pipx install scrapling[fetchers]
pip install cryptography lxml
scrapling install
```

### 3. 重载插件

在 AstrBot WebUI 插件管理中找到 `LinuxDo Preview`，点击重载。

## 📖 使用方法

**自动触发：** 在聊天中发送或粘贴任何 `linux.do` 链接即可，例如：

```
https://linux.do/t/topic/1378383
```

插件自动：
1. 回复 `🔍 正在读取 linux.do 页面…`
2. 后台使用 Scrapling 绕过 Cloudflare
3. 发送 **截图 + 标题 + 内容摘要**

**管理指令：**

| 指令 | 说明 |
|------|------|
| `/linuxdo_stats` | 查看统计（请求数/缓存命中/错误/缓存大小） |
| `/linuxdo_auth` | 查看 Cookie 配置与最近认证状态（只显示 Cookie 名称，不显示值） |
| `/linuxdo_cookie_status` | 查看加密保存的 Cookie 同步状态（只显示名称/数量/验证状态，不显示值） |
| `/linuxdo_cookie_pull` | 从配置的本地 Firefox profile/cookies.sqlite 手动拉取 Cookie 并加密保存 |
| `/linuxdo_clean` | 清理所有缓存截图 |

## 🔧 技术原理

```
┌─────────────┐   检测链接    ┌──────────────┐
│  用户消息    │ ──────────→   │  Plugin Core  │
│ linux.do/xx  │              │  事件监听器   │
└─────────────┘              └──────┬───────┘
                                    │
                          run_in_executor()
                                    │
                           ┌───────▼────────┐
                           │  Thread Pool    │
                           │  (max_workers=2)│
                           └───────┬────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            ┌──────────────┐ ┌──────────┐ ┌──────────────┐
            │ Stealthy     │ │ 截图保存  │ │ 提取标题&正文 │
            │ Session      │ │ .png     │ │              │
            │ (solves CF)  │ │          │ │              │
            └──────────────┘ └──────────┘ └──────────────┘
                    │               │               │
                    └───────────────┼───────────────┘
                                    ▼
                          ┌──────────────────┐
                          │  返回主线程       │
                          │  yield 图片+文字  │
                          └──────────────────┘
```

## ⚙️ 配置

通过 `_conf_schema.json` 支持以下配置：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `cache_ttl` | 缓存有效期（秒），设为 0 关闭缓存 | 1800 |
| `max_content_length` | 内容摘要最大长度（字符） | 400 |
| `screenshot_timeout` | 截图超时（秒） | 15 |
| `screenshot_full_page` | 页面截图回退模式（元素级卡片截图失败时才生效；true=全页回退，false=仅视口回退） | true |
| `use_api_render` | 使用 API + 自定义 HTML 渲染（推荐） | true |
| `allowed_group_ids` | 自动预览群聊白名单，留空表示所有群聊允许；多个群号用逗号/空格/换行分隔，私聊默认允许 | （空） |
| `linuxdo_session_cookie` | 手动 Cookie 兜底项；推荐复制完整 Cookie 请求头 | （空） |
| `linuxdo_cookie_sync_enabled` | 启用本地 Firefox Cookie 同步；预览前按间隔机会性刷新 | false |
| `linuxdo_firefox_profile_path` | AstrBot 进程可访问的本地 Firefox profile 目录或 `cookies.sqlite` 文件 | （空） |
| `linuxdo_cookie_encryption_key` | 加密保存 Cookie 的密钥；丢失后无法解密已保存会话 | （空） |
| `linuxdo_cookie_sync_interval_seconds` | 自动同步最小间隔；默认 2 小时 | 7200 |
| `linuxdo_restricted_topic_url` | 可选受限主题 URL；同步时用候选 Cookie 请求验证，HTTP 200 记为通过 | （空） |
| `linuxdo_username` | LinuxDo 用户名（已弃用，受 hCaptcha 限制无法自动登录） | （空） |
| `linuxdo_password` | LinuxDo 密码（已弃用，配合用户名自动登录） | （空） |

## 🔑 访问受限内容（可选）

默认以匿名身份访问 linux.do。如需查看受限分类、私信等非公开内容，可使用加密本地 Cookie 同步，或手动填写完整 Cookie 请求头作为兜底。

### 方式一：本地 Firefox Cookie 同步（推荐给 noVNC 常驻浏览器）

适合已经有一个常驻 noVNC/Firefox 浏览器，并且浏览器内已登录 linux.do 的场景。插件不会启动、停止或管理 noVNC/Firefox 容器，也不会执行 Docker copy；它只读取 AstrBot 进程可访问的本地 Firefox profile 目录或 `cookies.sqlite` 文件。

1. 让 noVNC/Firefox 常驻运行，并在其中登录 linux.do
2. 将 Firefox profile 目录或 `cookies.sqlite` 暴露为 AstrBot 进程可访问的本地路径
3. 在配置中设置：
   - `linuxdo_cookie_sync_enabled=true`
   - `linuxdo_firefox_profile_path=/path/to/firefox/profile` 或 `/path/to/cookies.sqlite`
   - `linuxdo_cookie_encryption_key=<随机长字符串>`
   - `linuxdo_cookie_sync_interval_seconds=7200`（默认 2 小时）
   - `linuxdo_restricted_topic_url=<可选受限主题 URL>`
4. 执行 `/linuxdo_cookie_pull` 可立即拉取一次 Cookie
5. 执行 `/linuxdo_cookie_status` 查看已保存会话的 Cookie 名称、数量、更新时间和验证状态

启用后，插件会在预览抓取前机会性检查 `session.json` 是否缺失或超过同步间隔；需要刷新时，从配置的本地 Firefox Cookie 数据库读取 linux.do Cookie，构造成完整 Cookie 请求头，使用 `linuxdo_cookie_encryption_key` 加密保存到：

```text
data/plugin_data/astrbot_plugin_linuxdo/session.json
```

如果配置了 `linuxdo_restricted_topic_url`，同步时会把候选 Cookie 临时注入本次预览 Session 并请求该 URL；HTTP 200 记为验证通过。验证失败只记录脱敏错误，不阻断预览。

**安全提示**：
- `session.json` 内只保存加密 Cookie 和名称/数量/验证状态等元数据，不保存明文 Cookie。
- `linuxdo_cookie_encryption_key` 必须单独妥善保管；丢失后无法解密已保存的 `session.json`。
- `/linuxdo_cookie_status`、`/linuxdo_cookie_pull` 和 `/linuxdo_auth` 只显示 Cookie 名称/数量/状态，不显示 Cookie 值、加密载荷或密钥。
- 同步到的 Cookie 仍代表登录账号权限；Bot 所在会话不可信时，可能把受限主题摘要/截图发送到群里。

### 方式二：手动复制 Cookie（兜底方式）

1. 在浏览器中登录 linux.do
2. 打开 DevTools（F12）→ Network，刷新 linux.do 页面
3. 点开任意发往 `https://linux.do` 的请求，复制 Request Headers 里的完整 `Cookie` 值
4. 在 AstrBot WebUI 插件配置中粘贴到 `linuxdo_session_cookie`

完整 Cookie 头通常比单独复制 `_t` 更接近浏览器实际会话，可同时带上 `_t`、`_forum_session`、`cf_clearance` 等相关 cookie。也支持只粘贴单个 cookie，例如：`_t=xxx`、`_forum_session=yyy`，或只粘贴单个 Value（会按 `_forum_session` 兼容处理）。

**安全提示**：
- 手动 Cookie 会以明文形式保存在 AstrBot 配置中，请妥善保管配置文件，避免泄露。
- 配置 Cookie 后，插件会用该账号读取聊天中触发的 linux.do 链接；如果 Bot 所在群聊不可信，可能把该账号可见的受限主题摘要/截图发送到群里。
- 建议仅在可信会话中启用 Cookie，或使用专门的低权限 linux.do 账号作为 Bot Cookie 来源。
- 只复制发往 `https://linux.do` 的请求里的 Cookie，不要导出或粘贴浏览器中其他站点的 Cookie。
- 若怀疑 Cookie 泄露，请立即在浏览器中退出并重新登录 linux.do，旧的 `_t`/`_forum_session` 将失效。

**有效期**：linux.do/Discourse 的登录 cookie 有效期由站点策略决定，`_t` 和 `_forum_session` 都可能短时失效；过期后重新复制完整 Cookie 头即可，无需重启。

### 关于账号密码自动登录（已不可用）

> ⚠️ linux.do 的登录表单启用了 **hCaptcha 人机验证**，自动化浏览器无法通过，因此账号密码自动登录已被移除。`linuxdo_username` / `linuxdo_password` 配置项保留仅为兼容，不再生效。请改用上方的 Cookie 方式。

## ⚠️ 注意事项

- 首次使用需要安装 Scrapling 和浏览器：`pip install scrapling[fetchers] && scrapling install`
- 启用加密 Cookie 同步还需要 `cryptography`，已列在 `requirements.txt` 中
- Cloudflare 绕过每次约 **20-40 秒**，请耐心等待
- 截图保存路径：`data/plugin_data/astrbot_plugin_linuxdo/screenshots/`
- 加密 Cookie 会话保存路径：`data/plugin_data/astrbot_plugin_linuxdo/session.json`
- 截图缓存 30 分钟自动过期，也可手动 `/linuxdo_clean`

## 📄 许可证

MIT
