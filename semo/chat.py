"""Shared question-to-answer use case for the CLI and HTTP interface."""

from collections.abc import Callable
from datetime import date, datetime, time
from typing import Protocol

from semo.answering import answer
from semo.domain import normalize
from semo.telemetry import no_observation
from semo.programs import KST, ProgramCatalogUnavailable, is_open_program_question, open_programs, program_hits

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
        load_programs: Callable | None = None,
    ):
        self.index = index
        self.embed = embed
        self.generate = generate
        self.model = model
        self.observe = observe
        self.load_programs = load_programs

    def reply(
        self, question: str, reference_date: date, include_history: bool = False
    ) -> dict:
        question = normalize(question)
        if not question or len(question) > MAX_QUESTION_CHARS:
            raise InvalidQuestion(f"질문은 1~{MAX_QUESTION_CHARS}자로 입력해 주세요.")
        program_query = is_open_program_question(question)
        with self.observe(
            name="semo.chat",
            input={
                "question": question,
                "as_of": reference_date.isoformat(),
                "include_history": include_history,
            },
            metadata={"model": self.model},
        ) as request:
            with self.observe(
                name="semo.retrieve", as_type="retriever", input={"question": question}
            ) as retrieval:
                if program_query:
                    if self.load_programs is None:
                        raise ProgramCatalogUnavailable("Program catalog is not configured")
                    now = datetime.now(KST)
                    at = now if reference_date == now.date() else datetime.combine(reference_date, time.min, KST)
                    selection = open_programs(self.load_programs(), at)
                    hits = program_hits(selection)
                    retrieval.update(metadata={"query_type": "open_programs", "at": at.isoformat(), "reason": selection["reason"]})
                else:
                    embedding = self.embed([question])[0]
                    hits = self.index.search(
                        embedding,
                        reference_date=None if include_history else reference_date,
                    )
                retrieval.update(output=hits)
            result = answer(question, hits, reference_date, self.generate)
            if program_query and not hits:
                result["answer"] = "수집한 자료에서 신청 기간과 최신 상태가 확인된 활동을 찾지 못했습니다. 모집이 없다는 뜻은 아니므로 두드림·유드림 원문에서 확인해 주세요."
                result["reason"] = selection["reason"]
            result["model"] = self.model
            request.update(output=result)
            return result
