"""PostgreSQL document storage and atomic JSON export."""

import json
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from semo.domain import CollectionBatch


class PostgresDocumentRepository:
    def __init__(self, dsn: str, directory: Path):
        self.dsn = dsn
        self.directory = directory

    @staticmethod
    def _initialize(connection):
        connection.execute(
            "CREATE TABLE IF NOT EXISTS documents ("
            "id TEXT PRIMARY KEY, kind TEXT NOT NULL, hash TEXT NOT NULL, "
            "payload JSONB NOT NULL)"
        )

    def load(self) -> list[dict]:
        with psycopg.connect(self.dsn, connect_timeout=10) as connection:
            self._initialize(connection)
            return [
                row[0]
                for row in connection.execute(
                    "SELECT payload FROM documents ORDER BY id"
                )
            ]

    def save(self, batch: CollectionBatch, checked_at: str, sample_only: bool) -> dict:
        with psycopg.connect(self.dsn, connect_timeout=10) as connection:
            self._initialize(connection)
            # Serialize snapshot writers, including manual CLI runs outside Airflow.
            connection.execute("LOCK TABLE documents IN SHARE ROW EXCLUSIVE MODE")
            previous = dict(connection.execute("SELECT id, hash FROM documents"))
            changed = sum(
                previous.get(doc["id"]) != doc["content_hash"]
                for doc in batch.documents
            )
            for kind in batch.replace_kinds:
                connection.execute("DELETE FROM documents WHERE kind = %s", (kind,))
            for document in batch.documents:
                doc = {**document, "checked_at": checked_at}
                connection.execute(
                    "INSERT INTO documents (id, kind, hash, payload) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, hash=excluded.hash, payload=excluded.payload",
                    (doc["id"], doc["kind"], doc["content_hash"], Jsonb(doc)),
                )
            stored = [
                row[0]
                for row in connection.execute(
                    "SELECT payload FROM documents ORDER BY id"
                )
            ]
        export = {
            "sample_only": sample_only,
            "checked_at": checked_at,
            "changed": changed,
            "documents": stored,
        }
        # shortcut: PostgreSQL commits before JSON export, retry the run if export fails.
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / "documents.json.tmp"
        temporary.write_text(
            json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.directory / "documents.json")
        return export
