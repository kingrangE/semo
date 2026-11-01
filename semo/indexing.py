"""Build and synchronize search chunks without depending on a vector database SDK."""

import hashlib
import json
from collections.abc import Callable
from datetime import date
from typing import Protocol

from semo.content import paragraph_chunks
from semo.domain import normalize

INDEX_VERSION = "2"


class VectorIndex(Protocol):
    def ids(self) -> set[str]: ...

    def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None: ...

    def delete(self, ids: list[str]) -> None: ...


def document_chunks(document: dict) -> list[dict]:
    content = document["content"].strip()
    if not content or document.get("body_status") == "image_only":
        return []
    metadata = {
        "document_id": document["id"],
        "content_hash": document["content_hash"],
        "title": document["title"],
        "url": document["url"],
        "kind": document["kind"],
        "published_at": document.get("published_at") or "",
        "index_version": INDEX_VERSION,
    }
    if document["kind"] == "calendar":
        metadata["start_day"] = date.fromisoformat(document["start_date"]).toordinal()
        metadata["end_day"] = date.fromisoformat(document["end_date"]).toordinal()
    header = f"제목: {document['title'][:256]}\n작성일: {str(document.get('published_at') or '')[:40]}\n"
    # Legacy exports lack block boundaries; recollect once for proper table rows.
    blocks = document.get("content_blocks") or [normalize(content)]
    texts = [header + text for text in paragraph_chunks(blocks)]
    fingerprint = hashlib.sha256(
        json.dumps([metadata, texts], ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return [
        {
            "id": f"{fingerprint}:{number}",
            "text": text,
            "metadata": {**metadata, "chunk_index": number},
        }
        for number, text in enumerate(texts)
    ]


def synchronize(
    documents: list[dict],
    index: VectorIndex,
    embed: Callable[[list[str]], list[list[float]]],
) -> dict:
    if not documents:
        raise ValueError(
            "PostgreSQL has no documents. Collect or import documents before indexing."
        )
    existing = index.ids()
    expected = set()
    pending = []
    result = {
        "indexed_documents": 0,
        "unchanged_documents": 0,
        "skipped_documents": 0,
        "chunks": 0,
        "deleted_chunks": 0,
    }
    for document in documents:
        chunks = document_chunks(document)
        if not chunks:
            result["skipped_documents"] += 1
            continue
        expected.update(chunk["id"] for chunk in chunks)
        missing = [chunk for chunk in chunks if chunk["id"] not in existing]
        result["indexed_documents" if missing else "unchanged_documents"] += 1
        pending.extend(missing)
    for start in range(0, len(pending), 32):
        batch = pending[start : start + 32]
        vectors = embed([chunk["text"] for chunk in batch])
        if len(vectors) != len(batch):
            raise ValueError("Embedding response count does not match the chunk count")
        index.upsert(batch, vectors)
    # Preserve old chunks until all new embeddings and writes have succeeded.
    stale = sorted(existing - expected)
    for start in range(0, len(stale), 256):
        index.delete(stale[start : start + 256])
    result["chunks"] = len(expected)
    result["deleted_chunks"] = len(stale)
    return result
