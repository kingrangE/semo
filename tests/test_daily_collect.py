import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from semo.adapters.sejong import (
    BOARDS,
    CALENDAR,
    CalendarSource,
    NoticeSource,
    calendar_documents,
)
from semo.adapters.storage import SqliteDocumentRepository
from semo.application import collect
from semo.domain import upcoming

CALENDAR_HTML = """<select id="tabYear"><option value="2026" selected>2026</option></select>
<div class="b-calendar-annual"><div class="b-month-wrap"><div class="b-month-title">12월</div>
<div class="b-schedule-item"><div class="b-schedule-date">12.30 ~ 01.02</div>
<div class="b-schedule-content">연말 일정</div></div></div>
<div class="b-month-wrap"><div class="b-month-title">2027년 1월</div>
<div class="b-schedule-item"><div class="b-schedule-date">01.01</div>
<div class="b-schedule-content">신년 일정</div></div></div></div>"""
NOTICE_HTML = """<div class="board"><p class="b-title">안내</p><div class="b-info">
<span class="b-date">2026.10.29</span></div><div class="b-content-box">신청 안내</div></div>"""


class DailyTests(unittest.TestCase):
    def collect(self, output, read_html):
        return collect(
            [CalendarSource(), NoticeSource()],
            read_html,
            SqliteDocumentRepository(output),
            checked_at="2026-10-29T06:00:00+09:00",
        )

    def samples(self):
        result = {CALENDAR: CALENDAR_HTML}
        for board in BOARDS:
            result[board + "?article.offset=0&articleLimit=10"] = (
                '<div class="board"><a href="?mode=view&articleNo=123">공지</a></div>'
            )
            result[board + "?mode=view&articleNo=123"] = NOTICE_HTML
        return result

    def test_calendar_year_rollover_and_invalid_layout(self):
        docs = calendar_documents(CALENDAR_HTML)
        self.assertEqual(docs[0]["end_date"], "2027-01-02")
        self.assertEqual(docs[1]["start_date"], "2027-01-01")
        with self.assertRaises(ValueError):
            calendar_documents(CALENDAR_HTML.replace("12.30 ~ 01.02", "날짜 확인 중"))
        with self.assertRaises(ValueError):
            calendar_documents("<html>로그인</html>")

    def test_daily_replay_is_idempotent_and_updates_changes(self):
        samples = self.samples()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            first = self.collect(output, samples.__getitem__)
            self.assertEqual(len(first["documents"]), 3)
            self.assertEqual(first["changed"], 3)
            self.assertEqual(self.collect(output, samples.__getitem__)["changed"], 0)
            for key in samples:
                if "mode=view" in key:
                    samples[key] = NOTICE_HTML.replace("신청 안내", "수정된 신청 안내")
            self.assertEqual(self.collect(output, samples.__getitem__)["changed"], 1)
            self.assertEqual(
                len(
                    upcoming(SqliteDocumentRepository(output).load(), date(2027, 1, 2))
                ),
                1,
            )
            self.assertEqual(
                upcoming(SqliteDocumentRepository(output).load(), date(2027, 2, 1)), []
            )

    def test_fetch_or_parse_failure_preserves_previous_export(self):
        samples = self.samples()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            self.collect(output, samples.__getitem__)
            before = (output / "documents.json").read_bytes()
            samples[BOARDS[1] + "?mode=view&articleNo=123"] = "<html>오류</html>"
            with self.assertRaises(ValueError):
                self.collect(output, samples.__getitem__)
            self.assertEqual((output / "documents.json").read_bytes(), before)
            self.assertEqual(len(json.loads(before)["documents"]), 3)


if __name__ == "__main__":
    unittest.main()
