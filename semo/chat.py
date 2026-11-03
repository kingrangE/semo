"""Shared question-to-answer use case for the CLI and HTTP interface."""

from collections.abc import Callable
from datetime import date
from typing import Protocol

from semo.answering import answer
from semo.domain import normalize
from semo.telemetry import no_observation

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
        self,
        index: SearchIndex,
        embed: Callable,
        generate: Callable,
        model: str,
        observe: Callable = no_observation,
    ):
        self.index = index
        self.embed = embed
        self.generate = generate
        self.model = model
        self.observe = observe

    def reply(
        self, question: str, reference_date: date, include_history: bool = False
    ) -> dict:
        question = normalize(question)
        if not question or len(question) > MAX_QUESTION_CHARS:
            raise InvalidQuestion(f"질문은 1~{MAX_QUESTION_CHARS}자로 입력해 주세요.")
        with self.observe(
            name="semo.chat",
            input={
                "question": question,
                "as_of": reference_date.isoformat(),
                "include_history": include_history,
            },
            metadata={"model": self.model},
        ) as request:
            embedding = self.embed([question])[0]
            with self.observe(
                name="semo.retrieve", as_type="retriever", input={"question": question}
            ) as retrieval:
                hits = self.index.search(
                    embedding,
                    reference_date=None if include_history else reference_date,
                )
                retrieval.update(output=hits)
            result = answer(question, hits, reference_date, self.generate)
            result["model"] = self.model
            request.update(output=result)
            return result
