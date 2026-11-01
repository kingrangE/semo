"""HTTP adapter and local chat page. No conversation content is persisted."""

import logging
import os
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from threading import BoundedSemaphore
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import APITimeoutError, RateLimitError
from pydantic import BaseModel, ConfigDict, StringConstraints

from semo.chat import MAX_QUESTION_CHARS, InvalidQuestion, SearchIndexEmpty
from semo.runtime import create_chat

app = FastAPI(title="세모 API", version="0.1.0")
web = Path(__file__).with_name("web")
app.mount("/static", StaticFiles(directory=web), name="static")
get_chat = lru_cache(maxsize=1)(create_chat)
# shortcut: per-process concurrency limit, add shared quotas before public deployment.
requests = BoundedSemaphore(2)
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS
        ),
    ]
    include_history: bool = False


class Source(BaseModel):
    id: int
    title: str
    url: str
    published_at: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    as_of: date
    reason: str | None
    generation_used: bool
    model: str


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(web / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(
            503, "답변 서비스를 준비하고 있습니다. 잠시 후 다시 이용해 주세요."
        )
    if not requests.acquire(blocking=False):
        raise HTTPException(
            429,
            "답변 요청이 많습니다. 잠시 후 다시 질문해 주세요.",
            headers={"Retry-After": "5"},
        )
    try:
        reference = datetime.now(ZoneInfo("Asia/Seoul")).date()
        return get_chat().reply(request.question, reference, request.include_history)
    except InvalidQuestion as error:
        raise HTTPException(400, str(error)) from error
    except SearchIndexEmpty as error:
        raise HTTPException(
            503, "검색 자료를 준비하고 있습니다. 잠시 후 다시 이용해 주세요."
        ) from error
    except (APITimeoutError, RateLimitError) as error:
        raise HTTPException(
            503, "답변 서비스가 지연되고 있습니다. 잠시 후 다시 질문해 주세요."
        ) from error
    except Exception as error:
        logger.exception("Chat request failed")
        raise HTTPException(
            502, "답변을 가져오지 못했습니다. 잠시 후 다시 질문해 주세요."
        ) from error
    finally:
        requests.release()
