"""Document rules; standard library only, with no I/O."""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta


def normalize(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def digest(title, published_at, content, asset_hashes=()):
    payload = [normalize(title), published_at, normalize(content), sorted(asset_hashes)]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass
class CollectionBatch:
    documents: list[dict] = field(default_factory=list)
    skipped_urls: list[str] = field(default_factory=list)
    replace_kinds: set[str] = field(default_factory=set)


def upcoming(documents: list[dict], on: date) -> list[dict]:
    until = (on + timedelta(days=30)).isoformat()
    return [
        {
            "title": doc["title"],
            "start_date": doc["start_date"],
            "end_date": doc["end_date"],
            "url": doc["url"],
            "checked_at": doc["checked_at"],
        }
        for doc in sorted(
            (d for d in documents if d["kind"] == "calendar"),
            key=lambda d: d["start_date"],
        )
        if doc["end_date"] >= on.isoformat() and doc["start_date"] <= until
    ]
