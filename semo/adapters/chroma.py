"""Chroma HTTP adapter; embeddings are supplied explicitly."""

import chromadb
from datetime import date

from semo.indexing import INDEX_VERSION
from semo.chat import SearchIndexEmpty

COLLECTION = f"semo-text-embedding-3-small-v{INDEX_VERSION}"


class ChromaVectorIndex:
    def __init__(self, host: str, port: int):
        client = chromadb.HttpClient(host=host, port=port)
        self.collection = client.get_or_create_collection(
            name=COLLECTION,
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
        )

    def ids(self) -> set[str]:
        # shortcut: load IDs in one request, paginate when the corpus no longer fits in memory.
        return set(self.collection.get(include=[])["ids"])

    def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        self.collection.upsert(
            ids=[chunk["id"] for chunk in chunks],
            documents=[chunk["text"] for chunk in chunks],
            metadatas=[chunk["metadata"] for chunk in chunks],
            embeddings=embeddings,
        )

    def delete(self, ids: list[str]) -> None:
        self.collection.delete(ids=ids)

    def search(
        self, embedding: list[float], reference_date: date | None = None
    ) -> list[dict]:
        count = self.collection.count()
        if not count:
            raise SearchIndexEmpty(
                "Active Chroma collection is empty; collect and index documents first"
            )
        where = None
        if reference_date is not None:
            where = {
                "$or": [
                    {"kind": "notice"},
                    {
                        "$and": [
                            {"kind": "calendar"},
                            {"end_day": {"$gte": reference_date.toordinal()}},
                        ]
                    },
                ]
            }
        result = self.collection.query(
            query_embeddings=[embedding],
            n_results=min(15, count),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        candidates = [
            {"text": text, "metadata": metadata, "distance": distance}
            for text, metadata, distance in zip(
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
                strict=True,
            )
        ]
        selected, counts = [], {}
        for hit in candidates:
            document_id = hit["metadata"]["document_id"]
            if counts.get(document_id, 0) < 2:
                selected.append(hit)
                counts[document_id] = counts.get(document_id, 0) + 1
            if len(selected) == 5:
                break
        return selected
