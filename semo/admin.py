"""Read-only document inventory; source and index adapters are supplied by callers."""

from collections import Counter, defaultdict

from semo.indexing import document_chunks, index_status

LIST_FIELDS = (
    "id", "kind", "title", "url", "source", "published_at", "checked_at",
    "start_date", "end_date", "application_start", "application_end", "body_status",
)
DETAIL_FIELDS = LIST_FIELDS + (
    "content", "tables", "content_hash", "has_images", "assets_collected",
    "event_start", "event_end", "target", "department", "category", "application_closed",
)


def document_inventory(documents: list[dict], entries: list[dict] | None) -> dict:
    by_document = defaultdict(set)
    for entry in entries or []:
        metadata = entry.get("metadata") or {}
        by_document[metadata.get("document_id")].add(entry["id"])
    items = []
    for doc in documents:
        expected = {chunk["id"] for chunk in document_chunks(doc)}
        actual = by_document[doc["id"]]
        state = (
            "skipped" if not expected else "unknown" if entries is None
            else "indexed" if expected == actual else "needs_index"
        )
        items.append({
            **{key: doc.get(key) for key in LIST_FIELDS},
            "index_state": state,
            "expected_chunks": len(expected),
            "indexed_chunks": len(actual) if entries is not None else None,
            "missing_chunks": len(expected - actual) if entries is not None else None,
            "stale_chunks": len(actual - expected) if entries is not None else None,
        })
    items.sort(key=lambda d: (d.get("checked_at") or "", d["id"]), reverse=True)
    return {
        "total": len(documents),
        "documents_by_kind": dict(Counter(doc["kind"] for doc in documents)),
        "index": index_status(entries, documents) if entries is not None else None,
        "items": items,
    }


def document_detail(document: dict) -> dict:
    return {key: document[key] for key in DETAIL_FIELDS if key in document}
