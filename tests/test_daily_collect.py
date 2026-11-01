import unittest

from semo.adapters.sejong import (
    calendar_documents,
)

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
    def test_calendar_year_rollover_and_invalid_layout(self):
        docs = calendar_documents(CALENDAR_HTML)
        self.assertEqual(docs[0]["end_date"], "2027-01-02")
        self.assertEqual(docs[1]["start_date"], "2027-01-01")
        with self.assertRaises(ValueError):
            calendar_documents(CALENDAR_HTML.replace("12.30 ~ 01.02", "날짜 확인 중"))
        with self.assertRaises(ValueError):
            calendar_documents("<html>로그인</html>")


if __name__ == "__main__":
    unittest.main()
