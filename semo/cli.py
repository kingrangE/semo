"""Compose concrete adapters for the command line and Airflow task."""

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from semo.adapters.http import SnapshotReader, network_reader
from semo.adapters.sejong import ROOT, CalendarSource, NoticeSource
from semo.adapters.storage import SqliteDocumentRepository
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
    parser.add_argument(
        "--on",
        type=date.fromisoformat,
        help="Show calendar events within 30 days; no network",
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
        SqliteDocumentRepository(args.output),
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
