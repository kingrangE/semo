import unittest

from semo.adapters.http import Robots
from semo.adapters.sejong import extract
from semo.domain import digest


class ProbeTests(unittest.TestCase):
    def test_root_only_and_specific_agent_rules(self):
        policy = Robots(
            "User-agent: *\nDisallow: /\nAllow: /$\nUser-agent: OtherBot\nAllow: /"
        )
        self.assertTrue(policy.allowed("https://example.org/"))
        self.assertFalse(policy.allowed("https://example.org/program"))
        self.assertFalse(policy.allowed("https://example.org/?page=1"))

    def test_download_wildcard_and_delay(self):
        policy = Robots(
            "User-agent: *\nCrawl-delay: 10\nDisallow: /_attach/\nDisallow: /*mode=download"
        )
        self.assertTrue(policy.allowed("https://example.org/notice?mode=view"))
        self.assertFalse(
            policy.allowed("https://example.org/notice?id=1&mode=download")
        )
        self.assertFalse(policy.allowed("https://example.org/_attach/poster.png"))
        self.assertEqual(policy.delay, 10)
        self.assertFalse(Robots("<html>error</html>").allowed("https://example.org/"))

    def test_hash_normalization_fields_and_binary_changes(self):
        self.assertEqual(
            digest("Title ", "2026-10-29", "a\n b"),
            digest("Title", "2026-10-29", "a b"),
        )
        self.assertNotEqual(digest("ab", None, "c"), digest("a", None, "bc"))
        self.assertNotEqual(
            digest("a", None, "b", ["file-v1"]), digest("a", None, "b", ["file-v2"])
        )

    def test_extraction_scoping_tables_and_relative_assets(self):
        html = """<nav>excluded</nav><div class="board"><p class="b-title">공지</p>
        <ul class="b-info"><li class="b-date">2026.10.29</li><li>999 views</li></ul>
        <div class="b-content-box"><p>내용</p><table><tr><th>대상</th><th>날짜</th></tr>
        <tr><td rowspan="2">학생</td><td>10월</td></tr></table><img src="/poster.png">
        <script>excluded_script</script></div><a href="?mode=download">안내.pdf</a></div>"""
        doc = extract(html, "https://example.org/notice", "official")
        self.assertEqual(doc["published_at"], "2026.10.29")
        self.assertNotIn("excluded", doc["content"])
        self.assertNotIn("999", doc["content"])
        self.assertEqual(doc["tables"][0][1][0]["rowspan"], "2")
        self.assertEqual(doc["images"][0]["url"], "https://example.org/poster.png")
        self.assertEqual(len(doc["attachments"]), 1)
        self.assertFalse(doc["hash_complete"])
        with self.assertRaises(ValueError):
            extract("<p>로그인이 필요합니다</p>", "https://example.org", "official")

    def test_program_application_time_is_not_publication_time(self):
        doc = extract(
            """<div id="ModuleEcoProgramView"><div class="title"><h4>특강</h4></div>
        <div class="cover" style="background-image:url(/cover.jpg)"></div>
        <time datetime="2026-11-01">신청일</time><div class="description">설명</div></div>""",
            "https://example.org/view/1",
            "program",
        )
        self.assertIsNone(doc["published_at"])
        self.assertEqual(doc["images"][0]["url"], "https://example.org/cover.jpg")


if __name__ == "__main__":
    unittest.main()
