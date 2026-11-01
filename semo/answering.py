"""Ground answers in retrieved sources and construct citations from stored URLs."""

import re
from collections.abc import Callable
from datetime import date

NO_ANSWER = "수집한 공식 자료에서 질문에 답할 근거를 확인하지 못했습니다. 학교 공식 공지나 담당 부서에서 확인해 주세요."


def answer(
    question: str, hits: list[dict], reference_date: date, generate: Callable
) -> dict:
    grouped = {}
    for hit in hits:
        metadata = hit["metadata"]
        identifier = metadata["document_id"]
        if identifier not in grouped:
            grouped[identifier] = {
                "id": len(grouped) + 1,
                "title": metadata["title"],
                "url": metadata["url"],
                "published_at": metadata.get("published_at", ""),
                "text": "",
            }
        grouped[identifier]["text"] += hit["text"] + "\n\n"
    sources = list(grouped.values())
    if not sources:
        return {
            "answer": NO_ANSWER,
            "sources": [],
            "as_of": reference_date.isoformat(),
        }
    draft = generate(question, sources, reference_date)
    if not draft["supported"]:
        return {
            "answer": NO_ANSWER,
            "sources": [],
            "as_of": reference_date.isoformat(),
        }
    paragraphs, used = [], set()
    for sentence in draft["sentences"]:
        text, ids = sentence["text"].strip(), sentence["source_ids"]
        if (
            not text
            or not ids
            or any(
                type(identifier) is not int or not 1 <= identifier <= len(sources)
                for identifier in ids
            )
        ):
            raise ValueError("Answer contains missing or invalid citations")
        if re.search(r"https?://|www\.|\[\d+\]", text):
            raise ValueError("Answer text must not invent links or citation markers")
        used.update(ids)
        paragraphs.append(
            text + " " + "".join(f"[{identifier}]" for identifier in dict.fromkeys(ids))
        )
    if not paragraphs:
        raise ValueError("Answer is empty")
    citations = [
        {key: source[key] for key in ("id", "title", "url", "published_at")}
        for source in sources
        if source["id"] in used
    ]
    return {
        "answer": "\n\n".join(paragraphs),
        "sources": citations,
        "as_of": reference_date.isoformat(),
    }
