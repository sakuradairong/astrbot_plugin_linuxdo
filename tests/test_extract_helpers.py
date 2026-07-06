import unittest
from unittest.mock import patch

from linuxdo_preview.extract import _build_summary
from linuxdo_preview.extract import _extract_content
from linuxdo_preview.extract import _extract_title
from linuxdo_preview.extract import _safe_title
from linuxdo_preview.extract import _topic_json_url
from linuxdo_preview.utils import _clean_text


class TestTopicJsonUrl(unittest.TestCase):
    def test_plain_topic_url(self):
        self.assertEqual(
            _topic_json_url("https://linux.do/t/topic-slug/12345"),
            "https://linux.do/t/topic-slug/12345.json",
        )

    def test_topic_url_with_reply_offset(self):
        self.assertEqual(
            _topic_json_url("https://linux.do/t/topic-slug/12345/5"),
            "https://linux.do/t/topic-slug/12345.json",
        )

    def test_already_json_url(self):
        self.assertEqual(
            _topic_json_url("https://linux.do/t/topic-slug/12345.json"),
            "https://linux.do/t/topic-slug/12345.json",
        )

    def test_query_and_fragment_are_ignored(self):
        self.assertEqual(
            _topic_json_url("https://linux.do/t/topic-slug/12345/7?foo=bar.json#reply"),
            "https://linux.do/t/topic-slug/12345.json",
        )

    def test_already_json_url_with_query_and_fragment(self):
        self.assertEqual(
            _topic_json_url("https://linux.do/t/topic-slug/12345.json?foo=bar#frag"),
            "https://linux.do/t/topic-slug/12345.json",
        )


class TestExtractContent(unittest.TestCase):
    def test_regex_fallback_runs_when_lxml_returns_empty(self):
        html = (
            '<article id="post_1"><div class="cooked">'
            '<p>This is long enough fallback text.</p>'
            '</div></article>'
        )
        with patch("linuxdo_preview.extract._extract_via_lxml", return_value=""):
            self.assertEqual(_extract_content(html), "This is long enough fallback text.")

    def test_regex_fallback_runs_when_lxml_is_unavailable(self):
        html = (
            '<article id="post_1"><div class="cooked">'
            '<p>This is long enough without lxml.</p>'
            '</div></article>'
        )
        with patch("linuxdo_preview.extract._lh", None):
            self.assertEqual(_extract_content(html), "This is long enough without lxml.")


class TestCleanText(unittest.TestCase):
    def test_strip_tags_and_whitespace(self):
        self.assertEqual(
            _clean_text("<p>Hello   world</p>"),
            "Hello world",
        )

    def test_decode_html_entities(self):
        self.assertEqual(
            _clean_text("Tom &amp; Jerry"),
            "Tom & Jerry",
        )


class TestExtractTitle(unittest.TestCase):
    def test_extract_title(self):
        self.assertEqual(
            _extract_title("<title>Hello World</title>"),
            "Hello World",
        )

    def test_strip_site_suffix(self):
        self.assertEqual(
            _extract_title("<title>Hello World - LINUX DO</title>"),
            "Hello World",
        )

    def test_no_title(self):
        self.assertEqual(_extract_title("<html></html>"), "无标题")


class TestSafeTitle(unittest.TestCase):
    def test_title_priority(self):
        self.assertEqual(
            _safe_title({"title": "Real Title", "fancy_title": "Fancy Title"}),
            "Real Title",
        )

    def test_fancy_title_fallback(self):
        self.assertEqual(
            _safe_title({"fancy_title": "Fancy Title"}),
            "Fancy Title",
        )

    def test_strips_suffix(self):
        self.assertEqual(
            _safe_title({"title": "Topic - LinuxDo"}),
            "Topic",
        )

    def test_empty(self):
        self.assertEqual(_safe_title(None), "无标题")
        self.assertEqual(_safe_title({}), "无标题")


class TestBuildSummary(unittest.TestCase):
    def test_basic_summary(self):
        out = _build_summary("Title", "Body text", "https://linux.do/t/1", 100)
        self.assertIn("📌 Title", out)
        self.assertIn("Body text", out)
        self.assertIn("https://linux.do/t/1", out)

    def test_truncation(self):
        long_text = "a" * 500
        out = _build_summary("Title", long_text, "https://linux.do/t/1", 100)
        self.assertIn("a" * 100 + "…", out)
        self.assertNotIn("a" * 101, out)


if __name__ == "__main__":
    unittest.main()
