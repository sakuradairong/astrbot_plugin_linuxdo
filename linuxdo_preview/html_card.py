import html as html_mod
import re

from .card_styles import PREVIEW_CARD_CSS
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
    topic_meta_html = _topic_meta_html(topic_data)

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
{PREVIEW_CARD_CSS}
</style>
</head>
<body>
	  <div class="card">
	    <div class="header">
	      <p class="eyebrow">LINUX.DO TOPIC</p>
	      <h1 class="title">{fancy_title}</h1>
	      <div class="meta">
	        <div class="avatar-wrap">
	          {avatar_img_html}
	          <div class="avatar-fallback">{html_mod.escape(author_initial)}</div>
	        </div>
	        <span class="name">{author_name}</span>
	        <span class="dot">·</span>
	        <span>{html_mod.escape(created_text)}</span>
	      </div>
	    </div>
	    <div class="stats">
	      <div class="stat"><span class="stat-label">Views</span><span class="stat-value">{views_text}</span></div>
	      <div class="stat"><span class="stat-label">Replies</span><span class="stat-value">{posts_text}</span></div>
	      <div class="stat"><span class="stat-label">Likes</span><span class="stat-value">{likes_text}</span></div>
	    </div>
	    {topic_meta_html}
	    {('<div class="tags">' + tags_html + '</div>') if tags else ''}
	    <div class="content">
	      {cooked_html}
	    </div>
	    <div class="footer">
	      <span class="footer-label">Source</span>
	      <a href="{html_mod.escape(url)}">{html_mod.escape(url)}</a>
	    </div>
	  </div>
</body>
	</html>"""


def _topic_meta_html(topic_data: LinuxDoTopicData) -> str:
    chips: list[str] = []
    category_name = topic_data.get("category_name", "") or ""
    category_id = topic_data.get("category_id")
    if category_name:
        chips.append("Category: " + html_mod.escape(category_name))
    elif category_id is not None:
        chips.append("Category: " + html_mod.escape(str(category_id)))

    last_posted_at = topic_data.get("last_posted_at", "") or ""
    if last_posted_at:
        chips.append("Last: " + html_mod.escape(_date_text(last_posted_at)))

    if topic_data.get("pinned"):
        chips.append("Pinned")
    if topic_data.get("closed"):
        chips.append("Closed")
    if topic_data.get("archived"):
        chips.append("Archived")

    if not chips:
        return ""
    chip_html = "".join(f'<span class="meta-chip">{chip}</span>' for chip in chips)
    return f'<div class="topic-meta">{chip_html}</div>'


def _date_text(value: str) -> str:
    return value.split("T", 1)[0] if "T" in value else value


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
