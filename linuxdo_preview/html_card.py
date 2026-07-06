import html as html_mod
import re

from .sanitize import _sanitize_cooked_html
from .topic_types import LinuxDoTag
from .topic_types import LinuxDoTopicData
from .utils import _clean_text
from .utils import _format_count


def _build_preview_html(topic_data: LinuxDoTopicData, url: str) -> str:
    title = html_mod.escape(topic_data.get("title", "无标题") or "无标题")
    fancy_title = html_mod.escape(topic_data.get("fancy_title", title) or title)
    posts_count = topic_data.get("posts_count", 0)
    views = topic_data.get("views", 0)
    like_count = topic_data.get("like_count", 0)
    tags = topic_data.get("tags", []) or []

    post_stream = topic_data.get("post_stream", {}) or {}
    posts = post_stream.get("posts", []) or []
    if not posts:
        return ""
    first = posts[0]
    author_name = html_mod.escape(first.get("name", "") or first.get("username", "") or "")
    author_username = html_mod.escape(first.get("username", "") or "")
    author_initial = (author_name or author_username or "?").strip()[:1].upper()
    author_avatar = _absolute_avatar_url(first.get("avatar_template", "") or "")
    post_created = first.get("created_at", "") or ""
    cooked_html = _normalize_cooked_urls(first.get("cooked", "") or "")

    created_text = ""
    if post_created:
        try:
            created_text = post_created.split("T")[0]
        except Exception:
            created_text = post_created

    tags_html = "".join(
        f'<span class="tag">#{html_mod.escape(_tag_name(tag))}</span>'
        for tag in tags[:6]
    )
    views_text = _format_count(views)
    posts_text = _format_count(posts_count)
    likes_text = _format_count(like_count)
    avatar_img_html = _avatar_img_html(author_avatar)

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
  .header {{ padding: 20px 24px 16px 24px; border-bottom: 1px solid #eef0f3; }}
  .title {{
    font-size: 20px; font-weight: 700; color: #1769c4; margin: 0 0 10px 0;
    line-height: 1.4; word-break: break-word;
  }}
  .meta {{ display: flex; align-items: center; gap: 10px; color: #6a737c; font-size: 13px; }}
  .meta img.avatar {{ width: 28px; height: 28px; border-radius: 50%; object-fit: cover; background: #ddd; }}
  .meta .avatar-wrap {{ position: relative; width: 28px; height: 28px; display: inline-block; }}
  .meta .avatar-wrap img {{ position: absolute; inset: 0; }}
  .meta .avatar-fallback {{
    position: absolute; inset: 0; width: 28px; height: 28px; border-radius: 50%;
    background: linear-gradient(135deg, #1769c4, #5a3ec8); color: #fff;
    font-weight: 600; display: flex; align-items: center; justify-content: center;
    font-size: 13px; text-transform: uppercase;
  }}
  .meta .name {{ color: #1c1c1c; font-weight: 500; }}
  .stats {{
    padding: 10px 24px; display: flex; gap: 18px; color: #6a737c; font-size: 13px;
    border-bottom: 1px solid #eef0f3; background: #fafbfc;
  }}
  .stats span::before {{ margin-right: 4px; }}
  .tags {{ padding: 10px 24px 0 24px; display: flex; gap: 6px; flex-wrap: wrap; }}
  .tag {{ background: #e8f0fe; color: #1769c4; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
  .content {{ padding: 16px 24px 8px 24px; word-break: break-word; }}
  .content p {{ margin: 0 0 10px 0; }}
  .content h1, .content h2, .content h3 {{ margin: 16px 0 8px 0; }}
  .content img {{ max-width: 100%; height: auto; border-radius: 6px; display: block; margin: 8px 0; }}
  .content pre, .content code {{
    background: #f6f8fa; border-radius: 4px; padding: 2px 6px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; font-size: 13px;
  }}
  .content pre {{ padding: 10px 12px; overflow-x: auto; }}
  .content blockquote {{
    border-left: 3px solid #d0d7de; margin: 8px 0; padding: 0 12px;
    color: #57606a; background: #f6f8fa;
  }}
  .content a {{ color: #1769c4; text-decoration: none; }}
  .content ul, .content ol {{ padding-left: 24px; }}
  .footer {{
    padding: 12px 24px 18px 24px; border-top: 1px solid #eef0f3;
    color: #6a737c; font-size: 12px; word-break: break-all;
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


def _tag_name(tag: str | LinuxDoTag) -> str:
    if isinstance(tag, str):
        return tag
    return tag.get("name", "")


def _absolute_avatar_url(author_avatar_raw: str) -> str:
    if author_avatar_raw and author_avatar_raw.startswith("//"):
        author_avatar = "https:" + author_avatar_raw
    elif author_avatar_raw and author_avatar_raw.startswith("/"):
        author_avatar = "https://linux.do" + author_avatar_raw
    else:
        author_avatar = author_avatar_raw
    if "{size}" in author_avatar:
        author_avatar = author_avatar.replace("{size}", "120")
    return author_avatar


def _avatar_img_html(author_avatar: str) -> str:
    if not author_avatar:
        return ""
    return (
        '<img class="avatar" src="'
        + html_mod.escape(author_avatar)
        + '" alt="avatar">'
    )


def _normalize_cooked_urls(cooked_html: str) -> str:
    if not cooked_html:
        return ""
    try:
        cooked_html = re.sub(r'(src|href)="(//[^"]+)"', r'\1="https:\2"', cooked_html)
        cooked_html = re.sub(r'(src|href)="(/uploads/[^"]+)"', r'\1="https://linux.do\2"', cooked_html)

        def _pick_imgs(block: str) -> str:
            imgs = re.findall(r'<img\b[^>]*>', block, flags=re.IGNORECASE)
            return "".join(imgs)

        cooked_html = re.sub(
            r'<div[^>]*class="[^"]*\bmeta\b[^"]*"[^>]*>.*?</div>',
            '',
            cooked_html,
            flags=re.DOTALL,
        )
        cooked_html = re.sub(
            r'<div[^>]*class="[^"]*lightbox-wrapper[^"]*"[^>]*>(.*?)</div>',
            lambda m: _pick_imgs(m.group(1)),
            cooked_html,
            flags=re.DOTALL,
        )
        cooked_html = re.sub(
            r'<a [^>]*class="[^"]*\blightbox\b[^"]*"[^>]*>(.*?)</a>',
            r'\1',
            cooked_html,
            flags=re.DOTALL,
        )
        cooked_html = re.sub(
            r'<div[^>]*class="[^"]*\bmeta\b[^"]*"[^>]*>.*?</div>',
            '',
            cooked_html,
            flags=re.DOTALL,
        )
        cooked_html = re.sub(
            r'<span[^>]*class="[^"]*\bfilename\b[^"]*"[^>]*>.*?</span>',
            '',
            cooked_html,
            flags=re.DOTALL,
        )
        cooked_html = re.sub(
            r'<div[^>]*class="[^"]*\bcodeblock-buttons\b[^"]*"[^>]*>.*?</div>',
            '',
            cooked_html,
            flags=re.DOTALL,
        )
        cooked_html = re.sub(
            r'<pre[^>]*>\s*<div[^>]*class="[^"]*\bpre-actions\b[^"]*"[^>]*>.*?</div>',
            '<pre>',
            cooked_html,
            flags=re.DOTALL,
        )
        cooked_html = re.sub(
            r'<a[^>]*class="[^"]*\bdownload[^"]*"[^>]*>.*?</a>',
            '',
            cooked_html,
            flags=re.DOTALL,
        )
        cooked_html = _sanitize_cooked_html(cooked_html)
    except Exception:
        return html_mod.escape(_clean_text(cooked_html), quote=False)
    return cooked_html
