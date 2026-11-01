import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from semo.cli import main


class CliTests(unittest.TestCase):
    def test_missing_database_url_fails_before_network(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("sys.argv", ["daily_collect.py"]),
            patch("semo.cli.network_reader") as reader,
            patch("sys.stderr"),
        ):
            with self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, 2)
            reader.assert_not_called()

    def test_existing_export_can_be_imported_without_fetching(self):
        with tempfile.TemporaryDirectory() as folder:
            export = Path(folder) / "documents.json"
            document = {
                "id": "notice:1",
                "kind": "notice",
                "content_hash": "hash",
                "content": "원문",
            }
            export.write_text(
                json.dumps(
                    {
                        "sample_only": False,
                        "checked_at": "original-time",
                        "documents": [document],
                    }
                )
            )
            with (
                patch.dict(os.environ, {"DATABASE_URL": "postgresql://test"}),
                patch("sys.argv", ["daily_collect.py", "--import-json", str(export)]),
                patch("semo.cli.PostgresDocumentRepository") as repository,
                patch("semo.cli.network_reader") as reader,
                patch("builtins.print"),
            ):
                repository.return_value.save.return_value = {
                    "documents": [document],
                    "changed": 1,
                }
                main()
                batch, checked_at, sample_only = (
                    repository.return_value.save.call_args.args
                )
                self.assertEqual(batch.documents, [document])
                self.assertEqual(batch.replace_kinds, set())
                self.assertEqual(checked_at, "original-time")
                self.assertFalse(sample_only)
                reader.assert_not_called()

    def test_invalid_import_is_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            export = Path(folder) / "bad.json"
            export.write_text(
                json.dumps(
                    {
                        "sample_only": False,
                        "checked_at": "now",
                        "documents": [{"id": "incomplete"}],
                    }
                )
            )
            with (
                patch.dict(os.environ, {"DATABASE_URL": "postgresql://test"}),
                patch("sys.argv", ["daily_collect.py", "--import-json", str(export)]),
                patch("semo.cli.PostgresDocumentRepository") as repository,
                patch("sys.stderr"),
            ):
                with self.assertRaises(SystemExit):
                    main()
                repository.return_value.save.assert_not_called()
