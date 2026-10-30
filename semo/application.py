"""Collection use case. Callers supply sources, an HTML reader, and storage."""

from collections.abc import Callable, Iterable
from typing import Protocol

from semo.domain import CollectionBatch

HtmlReader = Callable[[str], str]


class MissingSnapshot(KeyError):
    """An offline reader cannot supply a requested page."""


class Source(Protocol):
    def read(self, read_html: HtmlReader, previous: list[dict]) -> CollectionBatch: ...


class DocumentRepository(Protocol):
    def load(self) -> list[dict]: ...

    def save(
        self, batch: CollectionBatch, checked_at: str, sample_only: bool
    ) -> dict: ...


def collect(
    sources: Iterable[Source],
    read_html: HtmlReader,
    repository: DocumentRepository,
    *,
    checked_at: str,
    sample_only: bool = False,
) -> dict:
    previous = repository.load()
    batch = CollectionBatch()
    for source in sources:
        result = source.read(read_html, previous)
        batch.documents.extend(result.documents)
        batch.skipped_urls.extend(result.skipped_urls)
        batch.replace_kinds.update(result.replace_kinds)
    # No writes until every source has completed successfully.
    result = repository.save(batch, checked_at, sample_only)
    result["skipped_sample_urls"] = batch.skipped_urls
    return result
