"""Compose PostgreSQL, OpenAI and Chroma for indexing and source search."""

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from semo.adapters.storage import PostgresDocumentRepository
from semo.indexing import synchronize
from semo.domain import normalize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--query", help="Search source chunks instead of indexing")
    mode.add_argument("--answer", help="Answer a question with source citations")
    mode.add_argument(
        "--status",
        action="store_true",
        help="Show active collection and chunk count without calling OpenAI",
    )
    parser.add_argument(
        "--on",
        type=date.fromisoformat,
        help="Reference date for search/answers; defaults to today in Asia/Seoul",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Include past calendar events for historical questions",
    )
    args = parser.parse_args()
    question = args.query if args.query is not None else args.answer
    if (args.on or args.history) and question is None:
        parser.error("--on/--history requires --query or --answer")
    if question is not None and not normalize(question):
        parser.error("Question must not be empty")
    if not args.status and not os.environ.get("OPENAI_API_KEY"):
        parser.error(
            "Set OPENAI_API_KEY in your local .env before indexing or searching"
        )
    if question is None and not args.status and not os.environ.get("DATABASE_URL"):
        parser.error("DATABASE_URL is required for PostgreSQL indexing")

    from semo.adapters.chroma import COLLECTION, ChromaVectorIndex

    index = ChromaVectorIndex(
        os.environ.get("CHROMA_HOST", "localhost"),
        int(os.environ.get("CHROMA_PORT", "8000")),
    )
    if args.status:
        print(
            json.dumps(
                {"collection": COLLECTION, "chunks": len(index.ids())},
                ensure_ascii=False,
            )
        )
        return
    from semo.adapters.embeddings import OpenAIEmbedder

    embed = OpenAIEmbedder()
    if question is not None:
        reference = args.on or datetime.now(ZoneInfo("Asia/Seoul")).date()
        hits = index.search(
            embed([normalize(question)])[0],
            reference_date=None if args.history else reference,
        )
        if args.answer is not None:
            from semo.answering import answer
            from semo.adapters.answers import OpenAIAnswerer

            model = os.environ.get("OPENAI_CHAT_MODEL") or "gpt-6-luna"
            result = answer(question, hits, reference, OpenAIAnswerer(model))
            result["model"] = model
        else:
            result = hits
    else:
        repository = PostgresDocumentRepository(
            os.environ["DATABASE_URL"],
            Path(os.environ.get("SEMO_DATA_DIR", "artifacts/daily")),
        )
        result = synchronize(repository.load(), index, embed)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
