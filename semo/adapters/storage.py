"""SQLite document storage and atomic JSON export, compatible with existing files."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from semo.domain import CollectionBatch


class SqliteDocumentRepository:
    def __init__(self, directory: Path):
        self.directory = directory
        self.database = directory / "documents.sqlite3"

    def load(self) -> list[dict]:
        if not self.database.exists():
            return []
        with closing(sqlite3.connect(self.database)) as db:
            return [
                json.loads(row[0])
                for row in db.execute("SELECT payload FROM documents ORDER BY id")
            ]

    def save(self, batch: CollectionBatch, checked_at: str, sample_only: bool) -> dict:
        self.directory.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, kind TEXT, hash TEXT, payload TEXT)"
            )
            previous = dict(db.execute("SELECT id, hash FROM documents"))
            changed = sum(
                previous.get(doc["id"]) != doc["content_hash"]
                for doc in batch.documents
            )
            for kind in batch.replace_kinds:
                db.execute("DELETE FROM documents WHERE kind = ?", (kind,))
            for document in batch.documents:
                doc = {**document, "checked_at": checked_at}
                db.execute(
                    "INSERT INTO documents VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, hash=excluded.hash, payload=excluded.payload",
                    (
                        doc["id"],
                        doc["kind"],
                        doc["content_hash"],
                        json.dumps(doc, ensure_ascii=False),
                    ),
                )
            stored = [
                json.loads(row[0])
                for row in db.execute("SELECT payload FROM documents ORDER BY id")
            ]
        export = {
            "sample_only": sample_only,
            "checked_at": checked_at,
            "changed": changed,
            "documents": stored,
        }
        # shortcut: SQLite commits before JSON export, retry the run if export fails.
        temporary = self.directory / "documents.json.tmp"
        temporary.write_text(
            json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.directory / "documents.json")
        return export
