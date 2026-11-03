"""Compose the configured chat adapters for entry points."""

import os

from semo.chat import Chat


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
    )
