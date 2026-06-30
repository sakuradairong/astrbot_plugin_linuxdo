# astrbot_plugin_linuxdo - LinuxDo 链接预览插件 🚀

自动检测聊天消息中的 `linux.do` 链接，绕过 Cloudflare Turnstile 防护，
**截图并提取内容摘要**发送预览。

## ✨ 功能

- 🔗 **自动检测** — 聊天中出现 `linux.do` 链接立即触发
- 🛡️ **绕过 Cloudflare** — 使用 [Scrapling](https://github.com/D4Vinci/Scrapling) 的 StealthySession 自动解 Turnstile
- 📸 **智能截图** — 自适应卡片渲染，完整楼主内容，无空白/截断
- 📝 **内容摘要** — 通过 Discourse JSON API 提取完整楼主内容（无截断）
- 🔒 **登录支持** — 支持浏览器 Cookie 访问受限内容，也可实验性尝试账号密码自动登录
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
1. 回复 `🔍 正在获取 linux.do 预览…`
2. 后台使用 Scrapling 绕过 Cloudflare
3. 发送 **截图 + 标题 + 内容摘要**

**管理指令：**

| 指令 | 说明 |
|------|------|
| `/linuxdo_stats` | 查看统计（请求数/缓存命中/错误/缓存大小） |
| `/linuxdo_cookie_status` | 检测当前 Cookie 是否仍有效，并显示当前会话 ID |
| `/linuxdo_cookie_watch` | 将当前会话临时绑定为 Cookie 失效告警接收目标 |
| `/linuxdo_login` | 打开可见浏览器窗口，手动完成 hCaptcha 和登录，并缓存 Cookie |
| `/linuxdo_cookie <cookie>` | 在无 GUI 服务器上临时导入 Cookie，验证成功后缓存到内存 |
| `/linuxdo_cookie_pull` | 从配置的远程可视浏览器 CDP 端点自动读取 Cookie 并验证缓存 |
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
| `screenshot_full_page` | 全页截图模式（true=完整帖子，false=仅视口） | true |
| `use_api_render` | 使用 API + 自定义 HTML 渲染（推荐） | true |
| `linuxdo_session_cookie` | LinuxDo 会话 Cookie（推荐填 `_t`，访问受限内容必填） | （空） |
| `linuxdo_username` | LinuxDo 用户名（实验性自动登录） | （空） |
| `linuxdo_password` | LinuxDo 密码（实验性自动登录） | （空） |
| `interactive_login_timeout` | `/linuxdo_login` 手动登录窗口等待时间（秒） | 180 |
| `remote_browser_cdp_endpoint` | 远程可视浏览器 CDP 地址，例如 `http://chromium:9222` | （空） |
| `cookie_status_check_interval` | Cookie 状态定时检测间隔，0 为关闭 | 3600 |
| `cookie_status_notify_targets` | Cookie 失效告警目标会话 ID，多个可逗号/分号/换行分隔 | （空） |
| `cookie_status_alert_cooldown` | Cookie 持续失效时重复告警冷却时间（秒） | 21600 |

## 🔑 访问受限内容（可选）

默认以匿名身份访问 linux.do。如需查看受限分类、私信等非公开内容，推荐使用手动 Cookie；也可以配置用户名和密码让插件尝试表单登录。

### 云端 / 无 GUI 部署推荐

如果 AstrBot 运行在云服务器、Docker、后台服务或任何无桌面环境，无法弹出可操作的 hCaptcha 登录窗口。推荐流程：

1. 在你自己的本地浏览器登录 linux.do，并手动完成 hCaptcha
2. 复制 `https://linux.do` 下的 `_t` Cookie
3. 长期使用：填入 AstrBot WebUI 的 `linuxdo_session_cookie`
4. 临时使用：在可信私聊或管理渠道发送 `/linuxdo_cookie _t=xxx`

`/linuxdo_cookie` 只把 Cookie 缓存在插件进程内存里，不写入配置文件；AstrBot 重启或插件重载后需要重新导入。

### Cookie 状态定时检测

1. 在要接收告警的私聊或管理群执行 `/linuxdo_cookie_watch`
2. 保持 `cookie_status_check_interval` 为默认 `3600`，或按需调整；设为 `0` 可关闭
3. 插件会定时验证当前 `linuxdo_session_cookie` 或 `/linuxdo_cookie` 导入的运行时 Cookie
4. 失效时发送告警；若持续失效，会按 `cookie_status_alert_cooldown` 控制重复提醒

长期部署时，也可以执行 `/linuxdo_cookie_status` 查看当前会话 ID，然后填入 `cookie_status_notify_targets`。

### 云端可视化浏览器项目

如果希望在云端直接操作一个可视浏览器完成 hCaptcha，可考虑：

- **linuxserver/chromium**：轻量，浏览器通过 Web 页面访问，适合只需要一个 Chromium 的场景。
- **jlesage/firefox**：轻量 Firefox 容器，支持浏览器访问 GUI 或 VNC。
- **Kasm Workspaces**：完整的浏览器/桌面工作区平台，适合多人、多会话、权限管理更复杂的场景。
- **browserless**：更偏自动化和远程调试的无头浏览器服务，不是主要给人工长期操作用。

任何可视浏览器都不要裸露到公网；至少放到反向代理后面并启用强认证。

### 云端可视浏览器 + 插件自动拉 Cookie

如果 AstrBot 本身运行在 Docker 里，推荐单独部署一个可视 Chromium 容器，并只在 Docker 内网暴露 CDP 端口给 AstrBot 插件。

容器需要满足两个条件：

1. 管理员能通过 Web/VNC/noVNC 看到并操作 Chromium，手动完成 hCaptcha
2. Chromium 启动时启用 CDP，例如 `--remote-debugging-address=0.0.0.0 --remote-debugging-port=9222`

推荐拓扑：

```yaml
services:
  astrbot:
    # 这里保留你现有的 AstrBot 配置
    networks:
      - botnet

  chromium:
    # 换成你选择的可视 Chromium 镜像，例如 linuxserver/chromium、Kasm Chrome
    # 或其它同时支持 noVNC/Web GUI 与 CDP 的镜像。
    image: your-visible-chromium-image
    # 关键：确保 Chromium 带 remote-debugging 参数启动，并监听 9222。
    # 不同镜像的配置方式不同，请按对应镜像文档设置。
    volumes:
      - ./chromium-profile:/data/profile
    expose:
      - "9222"
    networks:
      - botnet
    restart: unless-stopped

networks:
  botnet:
```

然后在插件配置里填：

```text
remote_browser_cdp_endpoint = http://chromium:9222
```

使用流程：

1. 通过可视浏览器项目进入云端 Chromium，打开并登录 linux.do，手动完成 hCaptcha
2. 在 AstrBot 管理私聊执行 `/linuxdo_cookie_pull`
3. 插件通过 CDP 读取远程浏览器里的 linux.do Cookie
4. 插件验证通过后缓存到内存，后续预览自动复用
5. 如果定时检测发现 Cookie 失效，且远程浏览器里已有新登录态，插件会先尝试自动重新拉取，失败后再发送告警

注意：

- CDP 端口权限极高，不要映射到公网端口，只允许 AstrBot 容器在内网访问。
- 如果你使用的是 linuxserver/chromium 或 Kasm，需要确认浏览器启动参数中启用了 `--remote-debugging-address=0.0.0.0 --remote-debugging-port=9222`，并让 AstrBot 容器能访问该端口。
- `/linuxdo_cookie_pull` 读取到的 Cookie 仍然只缓存在插件内存；长期持久化仍建议把 `_t` 填入 `linuxdo_session_cookie`。

### 方式一：手动复制 Cookie（推荐）

1. 在浏览器中登录 linux.do
2. 打开 DevTools（F12）→ Application → Cookies → `https://linux.do`
3. 复制 **`_t`**（推荐，长效约 1 年）或 `_forum_session`（短期）的 Value
4. 在 AstrBot WebUI 插件配置中粘贴到 `linuxdo_session_cookie`

也支持一次粘贴完整 Cookie 头，例如：`_t=xxx; _forum_session=yyy`。

**有效期**：`_t` 约 1 年；`_forum_session` 约 2 周。过期后重新获取即可，无需重启。

### 方式二：账号密码自动登录（实验性）

配置 `linuxdo_username` 和 `linuxdo_password` 后，插件会在首次需要认证时尝试打开 linux.do 登录页、填写表单并提交。登录成功后会把当前浏览器上下文中的 Cookie 缓存在插件内存里，后续请求自动复用。

> ⚠️ 如果 linux.do 登录页要求 hCaptcha 等人机验证，自动登录会失败并降级为匿名访问。此时请改用上方的 Cookie 方式。

### 方式三：弹出窗口手动登录

执行 `/linuxdo_login` 后，插件会在运行 AstrBot 的机器上打开一个可见浏览器窗口。你可以在窗口里手动完成 hCaptcha 和登录；插件会等待 `interactive_login_timeout` 秒，检测登录成功后提取 Cookie 并缓存在内存里。

> ⚠️ 如果 AstrBot 运行在无桌面环境、Docker、远程服务器或后台服务中，窗口通常无法弹出或无法操作。此时请使用 WebUI 配置 `linuxdo_session_cookie`，或用 `/linuxdo_cookie` 临时导入。

## ⚠️ 注意事项

- 首次使用需要安装 Scrapling 和浏览器：`pip install scrapling[fetchers] && scrapling install`
- Cloudflare 绕过每次约 **20-40 秒**，请耐心等待
- 截图保存路径：`data/plugin_data/astrbot_plugin_linuxdo/screenshots/`
- 截图缓存 30 分钟自动过期，也可手动 `/linuxdo_clean`

## 📄 许可证

MIT
