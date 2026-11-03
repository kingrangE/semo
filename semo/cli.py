"""Compose concrete adapters for the command line and Airflow task."""

import argparse
import json
import os
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from semo.adapters.http import SnapshotReader, multisite_reader, network_reader
from semo.adapters.programs import ProgramSource, ROOTS as PROGRAM_ROOTS
from semo.adapters.sejong import ROOT, AcademicGuideSource, CalendarSource, NoticeSource
from semo.adapters.storage import PostgresDocumentRepository
from semo.application import collect
from semo.domain import upcoming


def main():
    parser = argparse.ArgumentParser(
        description="Collect public Sejong calendars, academic guides and notices."
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/daily"))
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument(
        "--program-sources", default=os.environ.get("SEMO_PROGRAM_SOURCES", ""),
        help="Comma-separated optional public sources: do,udream (robots enforced)",
    )
    parser.add_argument(
        "--sample-dir", type=Path, help="Replay saved HTML; missing samples are skipped"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--academic-guides", action="store_true",
        help="Manually collect standing academic guides only; excluded from daily runs",
    )
    mode.add_argument(
        "--inspect", action="store_true",
        help="Show PostgreSQL document counts and titles without crawling or AI calls",
    )
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
    program_sites = list(dict.fromkeys(s.strip() for s in args.program_sources.split(",") if s.strip()))
    if any(site not in PROGRAM_ROOTS for site in program_sites):
        parser.error("--program-sources accepts do,udream only")
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
    if args.inspect:
        documents = repository.load()
        print(json.dumps({
            "documents_by_kind": dict(Counter(doc["kind"] for doc in documents)),
            "documents": [
                {key: doc[key] for key in (
                    "id", "kind", "title", "url", "start_date", "end_date", "checked_at"
                ) if key in doc}
                for doc in documents
            ],
        }, ensure_ascii=False, indent=2))
        return
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
    if args.academic_guides:
        sources = [AcademicGuideSource(sample_only)]
        program_sites = []
    else:
        sources = [CalendarSource(), NoticeSource(args.pages, sample_only)]
        sources.extend(ProgramSource(site, args.pages, sample_only) for site in program_sites)
    if sample_only:
        reader = SnapshotReader(args.sample_dir)
    elif program_sites:
        reader = multisite_reader(
            [ROOT] + [PROGRAM_ROOTS[s] for s in program_sites], args.output / "raw"
        )
    else:
        reader = network_reader(ROOT, args.output / "raw")
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
                "documents_by_kind": dict(Counter(doc["kind"] for doc in result["documents"])),
                "changed": result["changed"],
                "sample_only": sample_only,
                "skipped": len(result["skipped_sample_urls"]),
                "source_status": result["source_status"],
            },
            ensure_ascii=False,
        )
    )
