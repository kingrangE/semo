"""Shared question-to-answer use case for the CLI and HTTP interface."""

from collections.abc import Callable
from datetime import date, datetime, time
from typing import Protocol

from semo.answering import answer
from semo.domain import normalize
from semo.telemetry import no_observation
from semo.programs import KST, ProgramCatalogUnavailable, is_open_program_question, open_programs, program_hits

MAX_QUESTION_CHARS = 1000
MAX_CONVERSATION_TURNS = 5
MAX_CONTEXT_ANSWER_CHARS = 6000


class InvalidQuestion(ValueError):
    pass


class SearchIndexEmpty(RuntimeError):
    pass


def validate_conversation(conversation: list[dict] | None) -> list[dict]:
    conversation = [] if conversation is None else conversation
    if not isinstance(conversation, list) or len(conversation) > MAX_CONVERSATION_TURNS:
        raise InvalidQuestion("최근 대화는 최대 5회까지 전달할 수 있습니다.")
    for turn in conversation:
        if not isinstance(turn, dict) or set(turn) != {"question", "answer"}:
            raise InvalidQuestion("대화에는 질문과 답변만 포함해야 합니다.")
        for key, limit in (("question", MAX_QUESTION_CHARS), ("answer", MAX_CONTEXT_ANSWER_CHARS)):
            if not isinstance(turn[key], str) or not 1 <= len(turn[key].strip()) <= limit:
                raise InvalidQuestion("대화의 질문 또는 답변 길이가 올바르지 않습니다.")
    return conversation


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
        rewrite: Callable | None = None,
    ):
        self.index = index
        self.embed = embed
        self.generate = generate
        self.model = model
        self.observe = observe
        self.load_programs = load_programs
        self.rewrite = rewrite

    def reply(
        self, question: str, reference_date: date, include_history: bool = False,
        *, conversation: list[dict] | None = None,
    ) -> dict:
        question = normalize(question)
        if not question or len(question) > MAX_QUESTION_CHARS:
            raise InvalidQuestion(f"질문은 1~{MAX_QUESTION_CHARS}자로 입력해 주세요.")
        conversation = validate_conversation(conversation)
        with self.observe(
            name="semo.chat",
            input={
                "question": question,
                "as_of": reference_date.isoformat(),
                "include_history": include_history,
                "conversation": conversation,
            },
            metadata={"model": self.model},
        ) as request:
            resolved_question = question
            if conversation:
                if self.rewrite is None:
                    raise RuntimeError("Conversation rewriting is not configured")
                context = self.rewrite(question, conversation)
                resolved_question = normalize(context["question"])
                clarification = context["clarification"].strip()
                if clarification:
                    result = {
                        "answer": clarification, "sources": [],
                        "as_of": reference_date.isoformat(),
                        "reason": "ambiguous_followup", "generation_used": True,
                        "model": self.model,
                    }
                    request.update(output=result)
                    return result
                if not resolved_question or len(resolved_question) > MAX_QUESTION_CHARS:
                    raise ValueError("Invalid rewritten question")
            program_query = is_open_program_question(resolved_question)
            with self.observe(
                name="semo.retrieve", as_type="retriever",
                input={"question": resolved_question, "original_question": question}
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
                    embedding = self.embed([resolved_question])[0]
                    hits = self.index.search(
                        embedding,
                        reference_date=None if include_history else reference_date,
                    )
                retrieval.update(output=hits)
            result = answer(resolved_question, hits, reference_date, self.generate)
            if program_query and not hits:
                result["answer"] = "수집한 자료에서 신청 기간과 최신 상태가 확인된 활동을 찾지 못했습니다. 모집이 없다는 뜻은 아니므로 두드림·유드림 원문에서 확인해 주세요."
                result["reason"] = selection["reason"]
            result["model"] = self.model
            request.update(output=result)
            return result
