"""Compose concrete adapters for the command line and Airflow task."""

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from semo.adapters.http import SnapshotReader, network_reader
from semo.adapters.sejong import ROOT, CalendarSource, NoticeSource
from semo.adapters.storage import PostgresDocumentRepository
from semo.application import collect
from semo.domain import upcoming


def main():
    parser = argparse.ArgumentParser(
        description="Collect public Sejong calendar and notice HTML."
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/daily"))
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument(
        "--sample-dir", type=Path, help="Replay saved HTML; missing samples are skipped"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--on",
        type=date.fromisoformat,
        help="Show calendar events within 30 days; no network",
    )
    mode.add_argument(
        "--import-json",
        type=Path,
        help="Import an existing document export into PostgreSQL",
    )
    args = parser.parse_args()
    if args.on:
        data = json.loads((args.output / "documents.json").read_text(encoding="utf-8"))
        print(
            json.dumps(
                upcoming(data["documents"], args.on), ensure_ascii=False, indent=2
            )
        )
        return
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.error("DATABASE_URL is required for PostgreSQL collection/import")
    repository = PostgresDocumentRepository(dsn, args.output)
    if args.import_json:
        from semo.domain import CollectionBatch

        data = json.loads(args.import_json.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or type(data.get("sample_only")) is not bool
            or not isinstance(data.get("checked_at"), str)
        ):
            parser.error(
                "Import requires a document export with sample_only and checked_at"
            )
        documents = data.get("documents")
        if not isinstance(documents, list) or not all(
            isinstance(doc, dict)
            and all(
                isinstance(doc.get(key), str) for key in ("id", "kind", "content_hash")
            )
            for doc in documents
        ):
            parser.error(
                "Import documents must have string id, kind and content_hash fields"
            )
        result = repository.save(
            CollectionBatch(documents), data["checked_at"], data["sample_only"]
        )
        print(
            json.dumps(
                {"documents": len(result["documents"]), "changed": result["changed"]}
            )
        )
        return
    sample_only = args.sample_dir is not None
    sources = [CalendarSource(), NoticeSource(args.pages, sample_only)]
    reader = (
        SnapshotReader(args.sample_dir)
        if sample_only
        else network_reader(ROOT, args.output / "raw")
    )
    result = collect(
        sources,
        reader,
        repository,
        checked_at=datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        sample_only=sample_only,
    )
    print(
        json.dumps(
            {
                "documents": len(result["documents"]),
                "changed": result["changed"],
                "sample_only": sample_only,
                "skipped": len(result["skipped_sample_urls"]),
            },
            ensure_ascii=False,
        )
    )
