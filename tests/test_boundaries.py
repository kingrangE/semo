import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from semo.adapters.http import SnapshotReader, network_reader
from semo.adapters.sejong import NoticeSource
from semo.adapters.storage import SqliteDocumentRepository
from semo.application import DocumentRepository, MissingSnapshot, collect
from semo.domain import CollectionBatch


class BoundaryTests(unittest.TestCase):
    def test_use_case_combines_sources_without_storage_or_html_dependencies(self):
        repository = Mock(spec=DocumentRepository)
        repository.load.return_value = []
        repository.save.return_value = {"documents": []}
        calendar = Mock()
        calendar.read.return_value = CollectionBatch(
            documents=[{"id": "calendar:1"}], replace_kinds={"calendar"}
        )
        other = Mock()
        other.read.return_value = CollectionBatch(
            documents=[{"id": "another-source:1"}], skipped_urls=["missing"]
        )
        reader = Mock()
        result = collect([calendar, other], reader, repository, checked_at="now")
        batch = repository.save.call_args.args[0]
        self.assertEqual(len(batch.documents), 2)
        self.assertEqual(batch.replace_kinds, {"calendar"})
        self.assertEqual(result["skipped_sample_urls"], ["missing"])
        calendar.read.assert_called_once_with(reader, [])

    def test_source_failure_never_calls_save(self):
        repository = Mock(spec=DocumentRepository)
        repository.load.return_value = []
        source = Mock()
        source.read.side_effect = RuntimeError("source unavailable")
        with self.assertRaises(RuntimeError):
            collect([source], Mock(), repository, checked_at="now")
        repository.save.assert_not_called()

    def test_snapshot_reader_reports_missing_files_and_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "manifest.json").write_text(
                json.dumps({"bad": "../outside.html"})
            )
            reader = SnapshotReader(directory)
            with self.assertRaises(MissingSnapshot):
                reader("unknown")
            with self.assertRaises(ValueError):
                reader("bad")

    def test_network_reader_applies_policy_and_rejects_external_hosts(self):
        def fetch(url, destination):
            destination.write_text(
                "User-agent: *\nDisallow: /private\nCrawl-delay: 10"
                if url.endswith("robots.txt")
                else "<p>ok</p>"
            )
            return {"ok": True, "content_type": "text/html"}

        with tempfile.TemporaryDirectory() as folder:
            with (
                patch("semo.adapters.http.fetch", side_effect=fetch) as request,
                patch("semo.adapters.http.time.sleep") as sleep,
                patch("semo.adapters.http.time.monotonic", return_value=0),
            ):
                reader = network_reader("https://example.org", Path(folder))
                for url in [
                    "https://example.org/private/page",
                    "https://elsewhere.org/",
                ]:
                    with self.assertRaises(ValueError):
                        reader(url)
                self.assertEqual(request.call_count, 1)
                self.assertEqual(reader("https://example.org/public"), "<p>ok</p>")
                sleep.assert_called_once_with(10)

    def test_notice_source_skips_only_missing_snapshots(self):
        def missing(url):
            if "mode=view" in url:
                raise MissingSnapshot(url)
            return (
                '<div class="board"><a href="?mode=view&articleNo=123">공지</a></div>'
            )

        result = NoticeSource(sample_only=True).read(missing, [])
        self.assertEqual(len(result.skipped_urls), 1)
        self.assertEqual(result.documents, [])

        def broken(url):
            if "mode=view" in url:
                raise KeyError("unexpected parser bug")
            return missing(url)

        with self.assertRaises(KeyError):
            NoticeSource(sample_only=True).read(broken, [])

    def test_repository_rolls_back_failed_snapshot_replacement(self):
        document = {"id": "calendar:1", "kind": "calendar", "content_hash": "original"}
        with tempfile.TemporaryDirectory() as folder:
            repository = SqliteDocumentRepository(Path(folder))
            repository.save(
                CollectionBatch([document], replace_kinds={"calendar"}), "before", False
            )
            before = (Path(folder) / "documents.json").read_bytes()
            with self.assertRaises(KeyError):
                repository.save(
                    CollectionBatch([{"id": "invalid"}], replace_kinds={"calendar"}),
                    "after",
                    False,
                )
            self.assertEqual(repository.load()[0]["content_hash"], "original")
            self.assertEqual((Path(folder) / "documents.json").read_bytes(), before)
            self.assertNotIn("checked_at", document)


if __name__ == "__main__":
    unittest.main()
