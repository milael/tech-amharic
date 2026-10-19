"""JSON API, versioned under /api/v1. OpenAPI docs are served at /docs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, Response

from .. import records as rec
from ..domain import DOMAINS, Lang, TermStatus
from . import services
from .deps import CurrentUser, DbSession, OptionalUser
from .models import Concept, Term
from .schemas import (
    ConceptIn,
    ConceptOut,
    ConceptPatch,
    ConceptSummary,
    QueueItem,
    ResubmitIn,
    ReviewIn,
    ReviewOut,
    TermIn,
    TermOut,
    UserOut,
    VoteIn,
)

router = APIRouter(prefix="/api/v1", tags=["termbase"])


def _concept_or_404(session: DbSession, slug: str) -> Concept:
    concept = services.get_concept(session, slug)
    if concept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No concept '{slug}'.")
    return concept


def _term_or_404(session: DbSession, term_id: int) -> Term:
    term = services.get_term(session, term_id)
    if term is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No term {term_id}.")
    return term


def summarize(concept: Concept) -> ConceptSummary:
    en = next(
        (t.text for t in concept.terms if t.lang == Lang.EN and t.status == TermStatus.PREFERRED),
        None,
    )
    return ConceptSummary(
        slug=concept.slug,
        domain=concept.domain,
        en=en or concept.slug,
        am_preferred=next(
            (
                t.text
                for t in concept.terms
                if t.lang == Lang.AM and t.status == TermStatus.PREFERRED
            ),
            None,
        ),
        am_candidates=[
            t.text
            for t in concept.terms
            if t.lang == Lang.AM and t.status in {TermStatus.ADMITTED, TermStatus.PROPOSED}
        ],
    )


# ---------------------------------------------------------------- meta


@router.get("/domains")
def list_domains() -> dict[str, str]:
    return DOMAINS


@router.get("/me", response_model=UserOut)
def me(user: OptionalUser) -> Any:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not signed in.")
    return user


@router.get("/stats")
def stats(session: DbSession) -> dict[str, int]:
    return services.counts(session)


# ---------------------------------------------------------------- concepts


@router.get("/concepts", response_model=list[ConceptSummary])
def list_concepts(
    session: DbSession,
    q: Annotated[str | None, Query(max_length=100, description="Search either language")] = None,
    domain: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ConceptSummary]:
    return [
        summarize(c)
        for c in services.search(session, q, domain_filter=domain, limit=limit, offset=offset)
    ]


@router.get("/concepts/{slug}", response_model=ConceptOut)
def read_concept(slug: str, session: DbSession) -> Any:
    return _concept_or_404(session, slug)


@router.post("/concepts", response_model=ConceptOut, status_code=status.HTTP_201_CREATED)
def create_concept(body: ConceptIn, session: DbSession, user: CurrentUser) -> Any:
    concept = services.create_concept(session, user, body)
    return services.get_concept(session, concept.slug)


@router.patch("/concepts/{slug}", response_model=ConceptOut)
def patch_concept(slug: str, body: ConceptPatch, session: DbSession, user: CurrentUser) -> Any:
    services.update_concept(session, user, _concept_or_404(session, slug), body)
    return services.get_concept(session, slug)


@router.post("/concepts/{slug}/terms", response_model=TermOut, status_code=status.HTTP_201_CREATED)
def propose_term(slug: str, body: TermIn, session: DbSession, user: CurrentUser) -> Any:
    return services.propose_term(session, user, _concept_or_404(session, slug), body)


# ---------------------------------------------------------------- review


@router.get("/review-queue", response_model=list[QueueItem])
def review_queue(
    session: DbSession,
    domain: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[QueueItem]:
    items = []
    for t in services.review_queue(session, domain_filter=domain, limit=limit):
        items.append(
            QueueItem(
                term_id=t.id,
                concept_slug=t.concept.slug,
                en=summarize(t.concept).en,
                text=t.text,
                formation=t.formation,
                score=t.score,
                proposed_by=t.proposed_by.handle if t.proposed_by else None,
            )
        )
    return items


@router.post(
    "/terms/{term_id}/reviews", response_model=ReviewOut, status_code=status.HTTP_201_CREATED
)
def review(term_id: int, body: ReviewIn, session: DbSession, user: CurrentUser) -> Any:
    return services.review_term(
        session, user, _term_or_404(session, term_id), body.decision, body.comment
    )


@router.post("/terms/{term_id}/resubmit", response_model=TermOut)
def resubmit(term_id: int, body: ResubmitIn, session: DbSession, user: CurrentUser) -> Any:
    return services.resubmit_term(session, user, _term_or_404(session, term_id), body)


@router.put("/terms/{term_id}/vote")
def put_vote(term_id: int, body: VoteIn, session: DbSession, user: CurrentUser) -> dict[str, int]:
    return {"score": services.vote(session, user, _term_or_404(session, term_id), body.value)}


# ---------------------------------------------------------------- export


@router.get("/export.jsonl", response_class=PlainTextResponse)
def export_jsonl(session: DbSession, published: bool = True) -> Response:
    body = rec.to_jsonl(services.export_records(session, published_only=published))
    return Response(body, media_type="application/x-ndjson; charset=utf-8")


@router.get("/export.csv")
def export_csv(session: DbSession, published: bool = True) -> Response:
    body = rec.to_csv(services.export_records(session, published_only=published))
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="tech-amharic.csv"'},
    )


@router.get("/export.tbx")
def export_tbx(session: DbSession, published: bool = True) -> Response:
    body = rec.to_tbx(services.export_records(session, published_only=published))
    return Response(body, media_type="application/x-tbx; charset=utf-8")


@router.get("/bundle.json")
def bundle(request: Request, session: DbSession) -> dict[str, Any]:
    return rec.to_bundle(
        services.export_records(session, published_only=True),
        version=request.app.state.settings.release_version,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
