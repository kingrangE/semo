"""Real PostgreSQL integration tests; each test uses its own temporary schema."""

import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from semo.adapters.sejong import BOARDS, CALENDAR, CalendarSource, NoticeSource
from semo.adapters.storage import PostgresDocumentRepository
from semo.application import collect
from semo.domain import CollectionBatch, upcoming
from test_daily_collect import CALENDAR_HTML, NOTICE_HTML


@unittest.skipUnless(
    os.environ.get("TEST_DATABASE_URL"),
    "TEST_DATABASE_URL is required for real PostgreSQL tests",
)
class PostgresTests(unittest.TestCase):
    def setUp(self):
        self.base_dsn = os.environ["TEST_DATABASE_URL"]
        self.schema = "semo_test_" + uuid4().hex
        with psycopg.connect(self.base_dsn) as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema))
            )
        self.dsn = make_conninfo(self.base_dsn, options=f"-csearch_path={self.schema}")
        self.directory = tempfile.TemporaryDirectory()
        self.output = Path(self.directory.name)
        self.repository = PostgresDocumentRepository(self.dsn, self.output)

    def tearDown(self):
        with psycopg.connect(self.base_dsn) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
            )
        self.directory.cleanup()

    def samples(self):
        result = {CALENDAR: CALENDAR_HTML}
        for board in BOARDS:
            result[board + "?article.offset=0&articleLimit=10"] = (
                '<div class="board"><a href="?mode=view&articleNo=123">공지</a></div>'
            )
            result[board + "?mode=view&articleNo=123"] = NOTICE_HTML
        return result

    def collect(self, samples):
        return collect(
            [CalendarSource(), NoticeSource()],
            samples.__getitem__,
            self.repository,
            checked_at="2026-10-30T06:00:00+09:00",
        )

    def test_collection_round_trip_idempotence_and_update(self):
        samples = self.samples()
        self.assertEqual(self.repository.load(), [])
        first = self.collect(samples)
        self.assertEqual(len(first["documents"]), 3)
        self.assertEqual(first["changed"], 3)
        self.assertEqual(self.collect(samples)["changed"], 0)
        for key in samples:
            if "mode=view" in key:
                samples[key] = NOTICE_HTML.replace("신청 안내", "수정된 신청 안내")
        self.assertEqual(self.collect(samples)["changed"], 1)
        self.assertEqual(len(upcoming(self.repository.load(), date(2027, 1, 2))), 1)
        self.assertEqual(upcoming(self.repository.load(), date(2027, 2, 1)), [])

    def test_parse_failure_preserves_database_and_export(self):
        samples = self.samples()
        self.collect(samples)
        before = (self.output / "documents.json").read_bytes()
        samples[BOARDS[1] + "?mode=view&articleNo=123"] = "<html>오류</html>"
        with self.assertRaises(ValueError):
            self.collect(samples)
        self.assertEqual((self.output / "documents.json").read_bytes(), before)
        self.assertEqual(self.repository.load(), json.loads(before)["documents"])

    def test_failed_snapshot_replacement_rolls_back(self):
        document = {"id": "calendar:1", "kind": "calendar", "content_hash": "original"}
        self.repository.save(
            CollectionBatch([document], replace_kinds={"calendar"}), "before", False
        )
        before = (self.output / "documents.json").read_bytes()
        with self.assertRaises(KeyError):
            self.repository.save(
                CollectionBatch(
                    [{"id": "invalid", "content_hash": "bad"}],
                    replace_kinds={"calendar"},
                ),
                "after",
                False,
            )
        self.assertEqual(self.repository.load()[0]["content_hash"], "original")
        self.assertEqual((self.output / "documents.json").read_bytes(), before)
        self.assertNotIn("checked_at", document)

    def test_calendar_snapshot_preserves_notices_and_jsonb_content(self):
        self.collect(self.samples())
        documents = self.repository.load()
        calendar = next(doc for doc in documents if doc["kind"] == "calendar")
        result = self.repository.save(
            CollectionBatch([calendar], replace_kinds={"calendar"}), "after", False
        )
        self.assertEqual(len(result["documents"]), 2)
        notice = next(doc for doc in result["documents"] if doc["kind"] == "notice")
        self.assertEqual(notice["content"], "신청 안내")
