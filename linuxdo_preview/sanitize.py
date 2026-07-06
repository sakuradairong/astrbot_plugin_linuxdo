import html as html_mod
from html.parser import HTMLParser
from urllib.parse import urlsplit


_ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "div", "em", "h1", "h2", "h3", "h4", "hr",
    "i", "img", "li", "ol", "p", "pre", "s", "span", "strong", "table", "tbody",
    "td", "th", "thead", "tr", "u", "ul",
}
_ALLOWED_ATTRS = {"alt", "class", "height", "href", "src", "title", "width"}
_BLOCKED_CONTAINER_TAGS = {
    "button", "form", "iframe", "math", "object", "option", "script", "select", "style",
    "svg", "textarea",
}
_BLOCKED_VOID_TAGS = {"base", "embed", "input", "link", "meta"}
_VOID_TAGS = {"br", "hr", "img"}
_URL_ATTRS = {"href", "src"}
_SAFE_SCHEMES = {"", "http", "https"}


def _sanitize_cooked_html(cooked_html: str) -> str:
    parser = _CookedHtmlSanitizer()
    parser.feed(cooked_html)
    parser.close()
    return parser.html


class _CookedHtmlSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._parts = []
        self._blocked_depth = 0

    @property
    def html(self) -> str:
        return "".join(self._parts)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _BLOCKED_VOID_TAGS:
            return
        if tag in _BLOCKED_CONTAINER_TAGS:
            self._blocked_depth += 1
            return
        if self._blocked_depth:
            return
        if tag not in _ALLOWED_TAGS:
            return
        safe_attrs = self._safe_attrs(tag, attrs)
        if tag == "img" and safe_attrs is None:
            return
        attr_text = "" if not safe_attrs else " " + " ".join(safe_attrs)
        self._parts.append(f"<{tag}{attr_text}>")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in _BLOCKED_CONTAINER_TAGS or tag in _BLOCKED_VOID_TAGS:
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _BLOCKED_CONTAINER_TAGS:
            if self._blocked_depth:
                self._blocked_depth -= 1
            return
        if self._blocked_depth or tag in _VOID_TAGS or tag not in _ALLOWED_TAGS:
            return
        self._parts.append(f"</{tag}>")

    def handle_data(self, data):
        if not self._blocked_depth:
            self._parts.append(html_mod.escape(data, quote=False))

    def handle_entityref(self, name):
        if not self._blocked_depth:
            self._parts.append(f"&{name};")

    def handle_charref(self, name):
        if not self._blocked_depth:
            self._parts.append(f"&#{name};")

    def _safe_attrs(self, tag, attrs):
        safe_attrs = []
        for name, value in attrs:
            attr_name = name.lower()
            if attr_name.startswith("on") or attr_name not in _ALLOWED_ATTRS or value is None:
                continue
            if attr_name in _URL_ATTRS:
                safe_url = _safe_cooked_url(value, tag)
                if safe_url is None:
                    if tag == "img" and attr_name == "src":
                        return None
                    continue
                value = safe_url
            safe_attrs.append(f'{attr_name}="{html_mod.escape(value, quote=True)}"')
        return safe_attrs


def _safe_cooked_url(raw_url: str, tag: str) -> str | None:
    url = raw_url.strip()
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    if scheme not in _SAFE_SCHEMES:
        return None
    if tag == "img" and not _is_safe_image_url(parsed):
        return None
    if tag != "img" and host and not _is_linuxdo_host(host):
        return None
    return url


def _is_safe_image_url(parsed) -> bool:
    host = parsed.netloc.lower()
    path = parsed.path
    if host:
        return _is_linuxdo_host(host)
    return path.startswith("/uploads/")


def _is_linuxdo_host(host: str) -> bool:
    return host == "linux.do" or host.endswith(".linux.do")
