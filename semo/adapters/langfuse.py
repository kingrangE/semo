"""Explicitly enabled Langfuse export with basic PII redaction."""

import atexit
import json
import os
import re
from functools import lru_cache

from semo.telemetry import no_observation

PII = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
    r"|(?<!\d)(?:\+82[- ]?|0)1[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)"
    r"|(?<!\d)\d{6}[- ]?[1-4]\d{6}(?!\d)"
    r"|(?<!\d)\d{8,10}(?!\d)"
    r"|\b(?:sk|pk)-(?:proj-)?[A-Za-z0-9_-]{16,}"
)


def redact(value):
    if isinstance(value, str):
        return PII.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def mask_spans(*, params):
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    patches = {}
    for identifier, span in params.spans.items():
        replacements = {}
        for key, value in span.attributes.items():
            if isinstance(value, str):
                try:
                    decoded = json.loads(value)
                except ValueError:
                    masked = redact(value)
                else:
                    cleaned = redact(decoded)
                    masked = (
                        json.dumps(cleaned, ensure_ascii=False)
                        if cleaned != decoded else value
                    )
                if masked != value:
                    replacements[key] = masked
        if replacements:
            patches[identifier] = OtelSpanPatch(set_attributes=replacements)
    # shortcut: pattern masking cannot detect names or all PII; use curated questions
    # until a reviewed privacy policy permits recording real student conversations.
    return MaskOtelSpansResult(span_patches=patches)


@lru_cache(maxsize=1)
def get_langfuse():
    if os.environ.get("LANGFUSE_ENABLED", "false").lower() != "true":
        return None
    required = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")
    if not all(os.environ.get(key) for key in required):
        raise RuntimeError("Langfuse requires PUBLIC_KEY, SECRET_KEY and BASE_URL")
    from langfuse import Langfuse

    client = Langfuse(mask_otel_spans=mask_spans)
    atexit.register(client.flush)
    return client


def observer():
    client = get_langfuse()
    return client.start_as_current_observation if client else no_observation
