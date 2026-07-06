import html as html_mod
import json
import re
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from .topic_types import LinuxDoTopicData
from .utils import _clean_text

try:
    from lxml import html as _lh
except ImportError:
    _lh = None


def _topic_json_url(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path.rstrip('/')
    if not path.endswith('.json'):
        parts = path.split('/')
        t_idx = -1
        for i, p in enumerate(parts):
            if p == 't':
                t_idx = i
                break
        if t_idx >= 0 and len(parts) > t_idx + 2:
            path = '/'.join(parts[:t_idx + 3])
        path += '.json'
    return urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))


def _extract_content_from_json(session, url: str, logger) -> str:
    try:
        json_url = _topic_json_url(url)
        logger.info(f"[LinuxDoPreview] JSON API 请求: {json_url}")
        resp = session.fetch(json_url)
        if resp.status != 200:
            logger.info(f"[LinuxDoPreview] JSON API 返回 {resp.status}")
            return ""
        data = json.loads(resp.body.decode("utf-8", errors="replace"))
        return _extract_content_from_topic_data(data, logger)
    except Exception as e:
        logger.info(f"[LinuxDoPreview] JSON API 提取失败: {type(e).__name__}: {e}")
        return ""


def _fetch_topic_data(session, url: str, logger) -> LinuxDoTopicData | None:
    try:
        json_url = _topic_json_url(url)
        logger.info(f"[LinuxDoPreview] 拉取 topic JSON: {json_url}")
        resp = session.fetch(json_url)
        if resp.status != 200:
            logger.info(f"[LinuxDoPreview] topic JSON 返回 {resp.status}")
            return None
        return json.loads(resp.body.decode("utf-8", errors="replace"))
    except Exception as e:
        logger.info(f"[LinuxDoPreview] topic JSON 拉取失败: {type(e).__name__}: {e}")
        return None


def _extract_title(html_str: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html_str, re.DOTALL | re.IGNORECASE)
    if m:
        t = m.group(1).strip()
        t = re.sub(
            r"\s*[-–—|]\s*(LINUX\s*DO|LINUXDO).*$", "", t, flags=re.IGNORECASE
        )
        return t.strip()
    return "无标题"


def _extract_content(html_str: str) -> str:
    try:
        content = _extract_via_lxml(html_str)
    except Exception:
        content = ""
    if content:
        return content
    return _extract_content_with_regex_fallback(html_str)


def _extract_content_with_regex_fallback(html_str: str) -> str:
    try:
        return _extract_via_regex(html_str)
    except Exception:
        return ""


def _extract_via_lxml(html_str: str) -> str:
    if _lh is None:
        return ""
    tree = _lh.fromstring(html_str)
    post_1 = tree.cssselect("#post_1")
    if not post_1:
        for el in tree.cssselect(".cooked"):
            text = _clean_text(el.text_content())
            if len(text) > 15:
                return text
        return ""
    cooked = post_1[0].cssselect(".cooked")
    if cooked:
        return _clean_text(cooked[0].text_content())
    return ""


def _extract_via_regex(html_str: str) -> str:
    post_1_match = re.search(
        r'<article[^>]*id="post_1"[^>]*>.*?<div\s+class="cooked">(.*?)</div>\s*</article>',
        html_str,
        re.DOTALL,
    )
    if post_1_match:
        text = re.sub(r"<[^>]+>", " ", post_1_match.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 15:
            return text
    for m in re.finditer(
        r'<div\s+class="cooked">(.*?)</div>\s*</article>', html_str, re.DOTALL
    ):
        text = re.sub(r"<[^>]+>", " ", m.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 15:
            return text
    return ""


def _build_summary(title: str, content: str, url: str, max_content_length: int) -> str:
    lines = [f"📌 {title}"]
    if content:
        lines.append("")
        lines.append(content[:max_content_length])
        if len(content) > max_content_length:
            lines[-1] += "…"
    lines.append("")
    lines.append(f"🔗 {url}")
    return "\n".join(lines)


def _safe_title(topic_data: LinuxDoTopicData | None) -> str:
    if not topic_data:
        return "无标题"
    title = topic_data.get("title") or topic_data.get("fancy_title") or "无标题"
    title = re.sub(
        r"\s*[-–—|]\s*(LINUX\s*DO|LINUXDO).*$", "", title, flags=re.IGNORECASE
    )
    return title.strip() or "无标题"


def _extract_content_from_topic_data(topic_data: LinuxDoTopicData, logger) -> str:
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
