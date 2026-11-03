"""Compose the configured chat adapters for entry points."""

import os
from pathlib import Path

from semo.chat import Chat
from semo.programs import ProgramCatalogUnavailable


def load_programs() -> list[dict]:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise ProgramCatalogUnavailable("DATABASE_URL is required for program queries")
    from semo.adapters.storage import PostgresDocumentRepository

    return PostgresDocumentRepository(
        dsn, Path(os.environ.get("SEMO_DATA_DIR", "artifacts/daily"))
    ).load_programs()


def create_chat() -> Chat:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for chat")
    from semo.adapters.answers import OpenAIAnswerer
    from semo.adapters.chroma import ChromaVectorIndex
    from semo.adapters.embeddings import OpenAIEmbedder
    from semo.adapters.langfuse import observer

    model = os.environ.get("OPENAI_CHAT_MODEL") or "gpt-6-luna"
    observe = observer()
    return Chat(
        ChromaVectorIndex(
            os.environ.get("CHROMA_HOST", "localhost"),
            int(os.environ.get("CHROMA_PORT", "8000")),
        ),
        OpenAIEmbedder(observe),
        OpenAIAnswerer(model, observe),
        model,
        observe,
        load_programs=load_programs,
    )
