"""LinuxDo Preview 插件纯函数单元测试

这些测试不依赖 AstrBot 或 Scrapling，仅验证可独立运行的工具函数。
"""

import unittest
from unittest.mock import patch

from linuxdo_preview.auth import _parse_cookie_pairs
from linuxdo_preview.html_card import _normalize_cooked_urls
from linuxdo_preview.utils import _format_count


class TestCookieParsing(unittest.TestCase):
    def test_full_cookie_header(self):
        pairs = _parse_cookie_pairs("_t=abc123; _forum_session=xyz%3D%3D")
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0]["name"], "_t")
        self.assertEqual(pairs[0]["value"], "abc123")
        self.assertEqual(pairs[1]["name"], "_forum_session")
        self.assertEqual(pairs[1]["value"], "xyz%3D%3D")

    def test_single_known_cookie(self):
        pairs = _parse_cookie_pairs("_t=longvalue")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["name"], "_t")
        self.assertEqual(pairs[0]["value"], "longvalue")

    def test_base64_raw_value_treated_as_forum_session(self):
        # Discourse _forum_session 是 base64，常带 '=' 填充，
        # 不应被误判为 name=value。
        raw = "aGVsbG8gd29ybGQ="
        pairs = _parse_cookie_pairs(raw)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["name"], "_forum_session")
        self.assertEqual(pairs[0]["value"], raw)

    def test_unknown_name_value_treated_as_forum_session(self):
        # 未知 name=value 应回退为裸值
        pairs = _parse_cookie_pairs("foo=bar")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["name"], "_forum_session")
        self.assertEqual(pairs[0]["value"], "foo=bar")

    def test_empty_string(self):
        self.assertEqual(_parse_cookie_pairs(""), [])
        self.assertEqual(_parse_cookie_pairs("   "), [])


class TestCookedUrlNormalization(unittest.TestCase):
    def test_protocol_relative_url_becomes_https(self):
        html = '<img src="//linux.do/uploads/default/1.png">'
        out = _normalize_cooked_urls(html)
        self.assertIn('src="https://linux.do/uploads/default/1.png"', out)

    def test_relative_upload_url_becomes_absolute(self):
        html = '<img src="/uploads/default/1.png">'
        out = _normalize_cooked_urls(html)
        self.assertIn('src="https://linux.do/uploads/default/1.png"', out)

    def test_lightbox_wrapper_stripped_to_img_only(self):
        html = (
            '<div class="lightbox-wrapper">'
            '<a class="lightbox" href="/uploads/1.png">'
            '<img src="/uploads/1.png">'
            '</a>'
            '<div class="meta"><span class="filename">1.png</span></div>'
            '</div>'
        )
        out = _normalize_cooked_urls(html)
        self.assertIn('<img', out)
        self.assertNotIn('lightbox-wrapper', out)
        self.assertNotIn('meta', out)
        self.assertNotIn('filename', out)

    def test_codeblock_buttons_stripped(self):
        html = '<div class="codeblock-buttons"><button>copy</button></div><pre>code</pre>'
        out = _normalize_cooked_urls(html)
        self.assertNotIn('codeblock-buttons', out)
        self.assertIn('<pre>code</pre>', out)

    def test_nested_lightbox_meta_removed_without_stray_div(self):
        html = (
            '<div class="lightbox-wrapper">'
            '<a class="lightbox" href="/uploads/default/original/1.png">'
            '<img src="/uploads/default/original/1.png">'
            '</a>'
            '<div class="meta"><span class="filename">1.png</span></div>'
            '</div>'
        )
        out = _normalize_cooked_urls(html)
        self.assertIn('<img src="https://linux.do/uploads/default/original/1.png">', out)
        self.assertNotIn('lightbox-wrapper', out)
        self.assertNotIn('filename', out)
        self.assertNotIn('</div>', out)

    def test_active_content_and_unsafe_urls_are_removed(self):
        html = (
            '<p onclick="alert(1)">Hello</p>'
            '<blockquote>quote</blockquote><pre><code>x</code></pre>'
            '<ul><li>item</li></ul>'
            '<a href="https://linux.do/t/topic/1">same site</a>'
            '<a href="javascript:alert(1)">js</a>'
            '<a href="data:text/html,boom">data</a>'
            '<a href="file:///etc/passwd">file</a>'
            '<img src="/uploads/default/1.png" onerror="alert(1)">'
            '<img src="https://evil.example/track.png">'
            '<script>alert(1)</script><style>body{}</style><iframe src="https://evil.example"></iframe>'
            '<form><input name="x"><button>go</button></form><svg><circle></circle></svg>'
        )
        out = _normalize_cooked_urls(html)
        self.assertIn('<p>Hello</p>', out)
        self.assertIn('<blockquote>quote</blockquote>', out)
        self.assertIn('<pre><code>x</code></pre>', out)
        self.assertIn('<ul><li>item</li></ul>', out)
        self.assertIn('href="https://linux.do/t/topic/1"', out)
        self.assertIn('src="https://linux.do/uploads/default/1.png"', out)
        self.assertNotIn('onclick', out.lower())
        self.assertNotIn('onerror', out.lower())
        self.assertNotIn('<script', out.lower())
        self.assertNotIn('<style', out.lower())
        self.assertNotIn('<iframe', out.lower())
        self.assertNotIn('<form', out.lower())
        self.assertNotIn('<input', out.lower())
        self.assertNotIn('<button', out.lower())
        self.assertNotIn('<svg', out.lower())
        self.assertNotIn('javascript:', out.lower())
        self.assertNotIn('data:', out.lower())
        self.assertNotIn('file:', out.lower())
        self.assertNotIn('evil.example', out)

    def test_blocked_void_tags_do_not_remove_following_content(self):
        html = '<meta name="viewport"><p data-x="1" style="color:red">after</p>'
        out = _normalize_cooked_urls(html)
        self.assertEqual(out, '<p>after</p>')

    def test_unknown_media_tags_do_not_keep_fetching_attributes(self):
        html = (
            '<video poster="https://evil.example/poster.png">caption</video>'
            '<img srcset="https://evil.example/a.png 1x" src="/uploads/default/a.png">'
        )
        out = _normalize_cooked_urls(html)
        self.assertIn('caption', out)
        self.assertIn('src="https://linux.do/uploads/default/a.png"', out)
        self.assertNotIn('<video', out)
        self.assertNotIn('poster', out)
        self.assertNotIn('srcset', out)
        self.assertNotIn('evil.example', out)

    def test_sanitizer_failure_escapes_cooked_html(self):
        html = '<script>alert(1)</script><img src="/uploads/default/a.png" onerror="alert(1)">'
        with patch("linuxdo_preview.html_card._sanitize_cooked_html", side_effect=RuntimeError):
            out = _normalize_cooked_urls(html)

        self.assertEqual(out, 'alert(1)')
        self.assertNotIn('<script', out.lower())
        self.assertNotIn('<img', out.lower())
        self.assertNotIn('onerror=', out.lower())

    def test_malformed_unsafe_markup_is_sanitized(self):
        html = '<p><a href="javascript:alert(1)" onclick="alert(1)">link<img src="javascript:x"'
        out = _normalize_cooked_urls(html)

        self.assertIn('<p><a>link', out)
        self.assertNotIn('javascript:', out.lower())
        self.assertNotIn('onclick', out.lower())
        self.assertNotIn('<img', out.lower())


class TestFormatCount(unittest.TestCase):
    def test_exact_values(self):
        self.assertEqual(_format_count(0), "0")
        self.assertEqual(_format_count(999), "999")
        self.assertEqual(_format_count(1000), "1.0k")
        self.assertEqual(_format_count(1500), "1.5k")
        self.assertEqual(_format_count(9999), "10.0k")
        self.assertEqual(_format_count(10000), "1.0w")
        self.assertEqual(_format_count(10500), "1.1w")

    def test_non_numeric(self):
        self.assertEqual(_format_count("abc"), "abc")
        self.assertEqual(_format_count(None), "None")


if __name__ == "__main__":
    unittest.main()
