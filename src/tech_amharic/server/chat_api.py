"""POST /api/v1/chat: answer a question in Amharic, grounded in the termbase."""

from __future__ import annotations

from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from .. import chat
from . import services
from .deps import DbSession

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=chat.MAX_HISTORY_CHARS * 2)


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=chat.MAX_QUESTION_CHARS)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


class ConceptRef(BaseModel):
    id: str
    en: str
    am: str | None
    status: str | None


class ChatChecks(BaseModel):
    ethiopic_ratio: float
    terms_used: list[str]
    terms_missing: list[str]


class ChatOut(BaseModel):
    answer: str
    concepts: list[ConceptRef]
    checks: ChatChecks
    model: str


def _client_key(request: Request) -> str:
    # Behind a proxy, uvicorn --proxy-headers fills request.client from
    # X-Forwarded-For.
    return request.client.host if request.client else "unknown"


@router.post("/chat", response_model=ChatOut)
async def ask(body: ChatIn, request: Request, session: DbSession) -> Any:
    settings = request.app.state.settings
    if not settings.chat_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Chat is switched off.")
    # Separate limiter from writes; keyed by client address (hash() keeps the
    # limiter's int keys).
    if not request.app.state.chat_limiter.allow(hash(_client_key(request))):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many questions; wait a minute."
        )

    records = services.export_records(session, published_only=not settings.chat_include_unreviewed)
    try:
        return await request.app.state.ask(
            body.question,
            records,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            history=[m.model_dump() for m in body.history],
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="The language model did not answer. Try again shortly.",
        ) from exc


# Re-exported so tests can swap in a fake model call.
default_ask = chat.ask
