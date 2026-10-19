"""Server-rendered pages. HTMX swaps in search results and review actions
without a JavaScript build step; every page also works without JavaScript."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from ..domain import (
    DOMAINS,
    Decision,
    Formation,
    Lang,
    RuleViolation,
    TermStatus,
    allowed_decisions,
)
from . import services
from .api import summarize
from .deps import DbSession, OptionalUser
from .models import User
from .schemas import SourceIn, TermIn
from .security import COOKIE_NAME, find_user, is_reviewer

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals.update(DOMAINS=DOMAINS, Formation=Formation, TermStatus=TermStatus)

STATUS_LABELS = {
    "preferred": "Preferred",
    "admitted": "Admitted",
    "deprecated": "Deprecated",
    "proposed": "Proposed",
    "changes_requested": "Changes requested",
    "rejected": "Rejected",
}
templates.env.globals["STATUS_LABELS"] = STATUS_LABELS


def _same_origin(request: Request) -> None:
    """CSRF defence for cookie-authenticated form posts.

    The session cookie is SameSite=Strict, and on top of that we reject
    cross-site posts by comparing the Origin (or Referer) host to our own.
    """
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin and urlsplit(origin).netloc != request.url.netloc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Cross-site form post rejected.")


def _render(request: Request, name: str, user: User | None, **ctx: Any) -> HTMLResponse:
    return templates.TemplateResponse(
        request, name, {"user": user, "is_reviewer": is_reviewer(user), **ctx}
    )


def _back(slug: str, message: str | None = None) -> RedirectResponse:
    url = f"/c/{quote(slug)}" + (f"?msg={quote(message)}" if message else "")
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------- browse


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request, session: DbSession, user: OptionalUser, q: str = "", domain: str = ""
) -> Response:
    concepts = services.search(session, q or None, domain_filter=domain or None, limit=60)
    ctx = {
        "q": q,
        "domain": domain,
        "results": [summarize(c) for c in concepts],
        "stats": services.counts(session),
    }
    # HTMX live search swaps only the results list.
    if request.headers.get("hx-request") and request.headers.get("hx-target") == "results":
        return _render(request, "_results.html", user, **ctx)
    return _render(request, "home.html", user, **ctx)


@router.get("/c/{slug}", response_class=HTMLResponse)
def concept_page(
    request: Request, slug: str, session: DbSession, user: OptionalUser, msg: str = ""
) -> Response:
    concept = services.get_concept(session, slug)
    if concept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    terms_by_lang = {
        lang: [t for t in concept.terms if t.lang == lang] for lang in (Lang.EN, Lang.AM)
    }
    return _render(
        request,
        "concept.html",
        user,
        concept=concept,
        terms_by_lang=terms_by_lang,
        allowed=lambda t: [d.value for d in allowed_decisions(TermStatus(t.status))],
        msg=msg,
    )


@router.get("/review", response_class=HTMLResponse)
def review_page(
    request: Request, session: DbSession, user: OptionalUser, domain: str = ""
) -> Response:
    queue = services.review_queue(session, domain_filter=domain or None, limit=100)
    return _render(request, "review.html", user, queue=queue, domain=domain)


# ---------------------------------------------------------------- session


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: OptionalUser, error: str = "") -> Response:
    return _render(request, "login.html", user, error=error)


@router.post("/login")
def login(
    request: Request, session: DbSession, token: Annotated[str, Form(max_length=200)]
) -> Response:
    _same_origin(request)
    token = token.strip()
    if find_user(session, token) is None:
        return RedirectResponse("/login?error=1", status_code=status.HTTP_303_SEE_OTHER)
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        secure=request.app.state.settings.secure_cookies,
        max_age=60 * 60 * 24 * 30,
    )
    return response


@router.post("/logout")
def logout(request: Request) -> Response:
    _same_origin(request)
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(COOKIE_NAME)
    return response


# ---------------------------------------------------------------- actions


def _signed_in(request: Request, user: User | None) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Sign in first.")
    if not request.app.state.limiter.allow(user.id):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests; slow down."
        )
    return user


@router.post("/c/{slug}/propose")
def propose(
    request: Request,
    slug: str,
    session: DbSession,
    user: OptionalUser,
    text: Annotated[str, Form(max_length=255)],
    formation: Annotated[str, Form()] = "",
    note: Annotated[str, Form(max_length=2000)] = "",
    citation: Annotated[str, Form(max_length=1000)] = "",
) -> Response:
    _same_origin(request)
    actor = _signed_in(request, user)
    concept = services.get_concept(session, slug)
    if concept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    try:
        data = TermIn(
            lang=Lang.AM,
            text=text,
            formation=Formation(formation) if formation else None,
            note=note or None,
            sources=[SourceIn(kind="coined", citation=citation)] if citation else [],  # type: ignore[arg-type]
        )
        services.propose_term(session, actor, concept, data)
    except (RuleViolation, ValidationError, ValueError) as exc:
        session.rollback()
        return _back(slug, getattr(exc, "message", "That proposal was not valid."))
    return _back(slug, "Proposal added to the review queue.")


@router.post("/terms/{term_id}/review")
def review(
    request: Request,
    term_id: int,
    session: DbSession,
    user: OptionalUser,
    decision: Annotated[str, Form()],
    comment: Annotated[str, Form(max_length=2000)] = "",
) -> Response:
    _same_origin(request)
    actor = _signed_in(request, user)
    term = services.get_term(session, term_id)
    if term is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    slug = term.concept.slug
    try:
        services.review_term(session, actor, term, Decision(decision), comment or None)
    except (RuleViolation, ValueError) as exc:
        session.rollback()
        return _back(slug, getattr(exc, "message", "Unknown decision."))
    return _back(slug, "Decision recorded.")


@router.post("/terms/{term_id}/vote")
def vote(
    request: Request,
    term_id: int,
    session: DbSession,
    user: OptionalUser,
    value: Annotated[int, Form(ge=-1, le=1)],
) -> Response:
    _same_origin(request)
    actor = _signed_in(request, user)
    term = services.get_term(session, term_id)
    if term is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    score = services.vote(session, actor, term, value)
    if request.headers.get("hx-request"):
        return HTMLResponse(f'<span class="score" id="score-{term.id}">{score:+d}</span>')
    return _back(term.concept.slug)
