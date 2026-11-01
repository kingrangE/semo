"""Shared question-to-answer use case for the CLI and HTTP interface."""

from collections.abc import Callable
from datetime import date
from typing import Protocol

from semo.answering import answer
from semo.domain import normalize

MAX_QUESTION_CHARS = 1000


class InvalidQuestion(ValueError):
    pass


class SearchIndexEmpty(RuntimeError):
    pass


class SearchIndex(Protocol):
    def search(
        self, embedding: list[float], reference_date: date | None = None
    ) -> list[dict]: ...


class Chat:
    def __init__(
        self, index: SearchIndex, embed: Callable, generate: Callable, model: str
    ):
        self.index = index
        self.embed = embed
        self.generate = generate
        self.model = model

    def reply(
        self, question: str, reference_date: date, include_history: bool = False
    ) -> dict:
        question = normalize(question)
        if not question or len(question) > MAX_QUESTION_CHARS:
            raise InvalidQuestion(f"질문은 1~{MAX_QUESTION_CHARS}자로 입력해 주세요.")
        hits = self.index.search(
            self.embed([question])[0],
            reference_date=None if include_history else reference_date,
        )
        result = answer(question, hits, reference_date, self.generate)
        result["model"] = self.model
        return result
