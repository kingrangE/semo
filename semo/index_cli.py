"""Index PostgreSQL documents and search source chunks in ChromaDB."""

import argparse
import json
import os
from pathlib import Path
from datetime import date, datetime
from zoneinfo import ZoneInfo

from semo.adapters.storage import PostgresDocumentRepository
from semo.domain import normalize
from semo.indexing import synchronize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", help="Search source chunks instead of indexing")
    parser.add_argument("--on", type=date.fromisoformat, help="Reference date; defaults to today in Asia/Seoul")
    parser.add_argument("--history", action="store_true", help="Include past calendar events")
    args = parser.parse_args()
    if (args.on or args.history) and args.query is None:
        parser.error("--on/--history requires --query")
    if args.query is not None and not normalize(args.query):
        parser.error("Question must not be empty")
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY in your local .env before indexing or searching")
    if args.query is None and not os.environ.get("DATABASE_URL"):
        parser.error("DATABASE_URL is required for PostgreSQL indexing")
    from semo.adapters.chroma import ChromaVectorIndex
    from semo.adapters.embeddings import OpenAIEmbedder

    embed = OpenAIEmbedder()
    index = ChromaVectorIndex(os.environ.get("CHROMA_HOST", "localhost"), int(os.environ.get("CHROMA_PORT", "8000")))
    if args.query is not None:
        reference = args.on or datetime.now(ZoneInfo("Asia/Seoul")).date()
        result = index.search(embed([normalize(args.query)])[0], reference_date=None if args.history else reference)
    else:
        repository = PostgresDocumentRepository(os.environ["DATABASE_URL"], Path(os.environ.get("SEMO_DATA_DIR", "artifacts/daily")))
        result = synchronize(repository.load(), index, embed)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
