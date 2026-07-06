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

# 安装 Scrapling（含浏览器）
pip install scrapling[fetchers]
scrapling install

# 或者使用 pipx（推荐）
pipx install scrapling[fetchers]
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
| `linuxdo_session_cookie` | LinuxDo 会话 Cookie（推荐填 `_t`，访问受限内容必填） | （空） |
| `linuxdo_username` | LinuxDo 用户名（已弃用，受 hCaptcha 限制无法自动登录） | （空） |
| `linuxdo_password` | LinuxDo 密码（已弃用，配合用户名自动登录） | （空） |

## 🔑 访问受限内容（可选）

默认以匿名身份访问 linux.do。如需查看受限分类、私信等非公开内容，请使用手动 Cookie。

### 方式一：手动复制 Cookie（推荐，唯一可用方式）

1. 在浏览器中登录 linux.do
2. 打开 DevTools（F12）→ Application → Cookies → `https://linux.do`
3. 复制 **`_t`**（推荐，长效约 1 年）或 `_forum_session`（短期）的 Value
4. 在 AstrBot WebUI 插件配置中粘贴到 `linuxdo_session_cookie`

也支持一次粘贴完整 Cookie 头，例如：`_t=xxx; _forum_session=yyy`。

**安全提示**：
- Cookie 以明文形式保存在 AstrBot 配置中，请妥善保管配置文件，避免泄露。
- 配置 Cookie 后，插件会用该账号读取聊天中触发的 linux.do 链接；如果 Bot 所在群聊不可信，可能把该账号可见的受限主题摘要/截图发送到群里。
- 建议仅在可信会话中启用 Cookie，或使用专门的低权限 linux.do 账号作为 Bot Cookie 来源。
- 建议仅复制必要的 `_t` 或 `_forum_session`，不要粘贴完整浏览器 Cookie（避免带入其他站点的追踪/广告 Cookie）。
- 若怀疑 Cookie 泄露，请立即在浏览器中退出并重新登录 linux.do，旧的 `_t`/`_forum_session` 将失效。

**有效期**：`_t` 约 1 年；`_forum_session` 约 2 周。过期后重新获取即可，无需重启。

### 关于账号密码自动登录（已不可用）

> ⚠️ linux.do 的登录表单启用了 **hCaptcha 人机验证**，自动化浏览器无法通过，因此账号密码自动登录已被移除。`linuxdo_username` / `linuxdo_password` 配置项保留仅为兼容，不再生效。请改用上方的 Cookie 方式。

## ⚠️ 注意事项

- 首次使用需要安装 Scrapling 和浏览器：`pip install scrapling[fetchers] && scrapling install`
- Cloudflare 绕过每次约 **20-40 秒**，请耐心等待
- 截图保存路径：`data/plugin_data/astrbot_plugin_linuxdo/screenshots/`
- 截图缓存 30 分钟自动过期，也可手动 `/linuxdo_clean`

## 📄 许可证

MIT
