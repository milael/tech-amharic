"""Application factory. Run locally with:

uv run tam admin serve --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..domain import RuleViolation
from . import api, chat_api, web
from .config import Settings, get_settings
from .db import Database, create_tables
from .security import RateLimiter

# RuleViolation code -> HTTP status
_STATUS_FOR = {
    "not_reviewer": 403,
    "self_review": 403,
    "not_proposer": 403,
    "invalid_transition": 409,
    "duplicate_term": 409,
    "duplicate_concept": 409,
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.auto_create_tables:
            create_tables(db.engine)
        yield
        db.engine.dispose()

    app = FastAPI(
        title="Tech-Amharic",
        summary="Open, reviewed termbase for computing terms in Amharic.",
        version=settings.release_version,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.limiter = RateLimiter(settings.write_rate_per_minute)
    app.state.chat_limiter = RateLimiter(settings.chat_rate_per_minute)
    app.state.ask = chat_api.default_ask

    @app.exception_handler(RuleViolation)
    async def rule_violation(_: Request, exc: RuleViolation) -> JSONResponse:
        return JSONResponse(
            {"code": exc.code, "detail": exc.message}, status_code=_STATUS_FOR.get(exc.code, 422)
        )

    @app.middleware("http")
    async def limits_and_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_body_bytes:
            return JSONResponse(
                {"code": "too_large", "detail": "Request body too large."}, status_code=413
            )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api.router)
    app.include_router(chat_api.router)
    app.include_router(web.router)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    return app
