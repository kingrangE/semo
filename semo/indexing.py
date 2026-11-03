"""Build and synchronize search chunks without depending on a vector database SDK."""

import hashlib
import json
from collections.abc import Callable
from collections import Counter, defaultdict
from datetime import date
from typing import Protocol

from semo.content import paragraph_chunks
from semo.domain import normalize

INDEX_VERSION = "2"


class VectorIndex(Protocol):
    def ids(self) -> set[str]: ...

    def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None: ...

    def delete(self, ids: list[str]) -> None: ...


def index_status(entries: list[dict], documents: list[dict] | None = None) -> dict:
    stored_ids = {entry["id"] for entry in entries}
    chunks_by_kind = Counter()
    documents_by_kind = defaultdict(set)
    for entry in entries:
        metadata = entry.get("metadata") or {}
        kind = metadata.get("kind", "unknown")
        chunks_by_kind[kind] += 1
        if metadata.get("document_id"):
            documents_by_kind[kind].add(metadata["document_id"])
    result = {
        "chunks": len(entries),
        "chunks_by_kind": dict(chunks_by_kind),
        "indexed_documents_by_kind": {kind: len(ids) for kind, ids in documents_by_kind.items()},
    }
    if documents is not None:
        expected, expected_counts, missing_counts, skipped = set(), Counter(), Counter(), Counter()
        for doc in documents:
            chunks = document_chunks(doc)
            if not chunks:
                skipped["image_only" if doc.get("body_status") == "image_only" else "empty_content"] += 1
            expected_counts[doc["kind"]] += len(chunks)
            for chunk in chunks:
                expected.add(chunk["id"])
                if chunk["id"] not in stored_ids:
                    missing_counts[doc["kind"]] += 1
        result["postgresql"] = {
            "documents": len(documents),
            "documents_by_kind": dict(Counter(doc["kind"] for doc in documents)),
            "expected_chunks": len(expected),
            "expected_chunks_by_kind": dict(expected_counts),
            "skipped_documents_by_reason": dict(skipped),
            "missing_chunks_by_kind": dict(missing_counts),
            "stale_chunks": len(stored_ids - expected),
            "in_sync": stored_ids == expected,
        }
    return result


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
    if document["kind"] == "program":
        for key in ("source", "body_status", "application_start", "application_end", "target", "category"):
            metadata[key] = document.get(key) or ""
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
