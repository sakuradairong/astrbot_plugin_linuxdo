# astrbot_plugin_linuxdo - LinuxDo 链接预览插件 🚀

自动检测聊天消息中的 `linux.do` 链接，绕过 Cloudflare Turnstile 防护，
**截图并提取内容摘要**发送预览。

## ✨ 功能

- 🔗 **自动检测** — 聊天中出现 `linux.do` 链接立即触发
- 🛡️ **绕过 Cloudflare** — 使用 [Scrapling](https://github.com/D4Vinci/Scrapling) 的 StealthySession 自动解 Turnstile
- 📸 **智能截图** — 视口截图显示主帖，自动隐藏导航栏/侧边栏，可选全页模式
- 📝 **内容摘要** — 提取标题 + 正文前 400 字
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

## ⚠️ 注意事项

- 首次使用需要安装 Scrapling 和浏览器：`pip install scrapling[fetchers] && scrapling install`
- Cloudflare 绕过每次约 **20-40 秒**，请耐心等待
- 截图保存路径：`data/plugin_data/astrbot_plugin_linuxdo/screenshots/`
- 截图缓存 30 分钟自动过期，也可手动 `/linuxdo_clean`

## 📄 许可证

MIT
