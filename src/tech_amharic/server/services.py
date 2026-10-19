"""Use cases. The API and the web UI both call these; neither touches the ORM
directly for writes, so the rules and the audit log cannot be bypassed."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import domain
from ..domain import Decision, Formation, Lang, Role, RuleViolation, SourceKind, TermStatus
from ..normalize import clean, detect_lang, norm_key
from ..records import ConceptRecord, SourceRecord, TermRecord
from ..records import select as select_records
from .models import AuditEvent, Concept, Review, Source, Term, User, Vote
from .schemas import ConceptIn, ConceptPatch, ResubmitIn, SourceIn, TermIn

# ---------------------------------------------------------------- audit


def _snapshot(obj: Term | Concept) -> dict[str, Any]:
    if isinstance(obj, Term):
        return {"text": obj.text, "status": str(obj.status), "lang": obj.lang}
    return {
        "slug": obj.slug,
        "domain": obj.domain,
        "definition_en": obj.definition_en,
        "definition_am": obj.definition_am,
        "note": obj.note,
    }


def audit(
    session: Session,
    actor: User | None,
    action: str,
    obj: Term | Concept,
    before: dict[str, Any] | None = None,
) -> None:
    session.flush()  # make sure obj.id exists
    session.add(
        AuditEvent(
            actor_id=actor.id if actor else None,
            action=action,
            entity=type(obj).__name__.lower(),
            entity_id=obj.id,
            before=before,
            after=_snapshot(obj),
        )
    )


# ---------------------------------------------------------------- reads


def get_concept(session: Session, slug: str) -> Concept | None:
    return session.scalar(
        select(Concept)
        .where(Concept.slug == slug)
        .options(
            selectinload(Concept.terms).selectinload(Term.sources),
            selectinload(Concept.terms).selectinload(Term.votes),
            selectinload(Concept.terms).selectinload(Term.reviews).selectinload(Review.reviewer),
        )
    )


def get_term(session: Session, term_id: int) -> Term | None:
    return session.get(Term, term_id)


def search(
    session: Session,
    q: str | None = None,
    *,
    domain_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[Concept]:
    """Concepts whose terms match ``q`` on the folded key, exact matches first."""
    stmt = select(Concept).options(selectinload(Concept.terms))
    if domain_filter:
        stmt = stmt.where(Concept.domain == domain_filter)
    if q and (key := norm_key(q)):
        # LIKE '%key%' uses the trigram index on PostgreSQL.
        escaped = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        matching = (
            select(Term.concept_id, func.min(func.length(Term.norm_key)).label("best"))
            .where(or_(Term.norm_key == key, Term.norm_key.like(f"%{escaped}%", escape="\\")))
            .group_by(Term.concept_id)
            .subquery()
        )
        stmt = stmt.join(matching, matching.c.concept_id == Concept.id).order_by(
            matching.c.best, Concept.slug
        )
    else:
        stmt = stmt.order_by(Concept.slug)
    return session.scalars(stmt.limit(limit).offset(offset)).unique().all()


def review_queue(
    session: Session, *, domain_filter: str | None = None, limit: int = 50
) -> Sequence[Term]:
    """Proposed terms, highest community score first, then oldest first."""
    score = (
        select(func.coalesce(func.sum(Vote.value), 0))
        .where(Vote.term_id == Term.id)
        .correlate(Term)
        .scalar_subquery()
    )
    stmt = (
        select(Term)
        .join(Term.concept)
        .where(Term.status == TermStatus.PROPOSED)
        .options(
            selectinload(Term.concept).selectinload(Concept.terms),
            selectinload(Term.proposed_by),
            selectinload(Term.votes),
        )
        .order_by(score.desc(), Term.created_at, Term.id)
    )
    if domain_filter:
        stmt = stmt.where(Concept.domain == domain_filter)
    return session.scalars(stmt.limit(limit)).all()


def counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(Term.status, func.count()).where(Term.lang == Lang.AM).group_by(Term.status)
    )
    by_status = {str(status): n for status, n in rows}
    return {
        "concepts": session.scalar(select(func.count()).select_from(Concept)) or 0,
        "published": sum(by_status.get(s, 0) for s in domain.PUBLISHED),
        "proposed": by_status.get(TermStatus.PROPOSED, 0),
    }


# ---------------------------------------------------------------- writes


def _check_script(text: str, lang: Lang, formation: Formation | None) -> None:
    if formation is not Formation.ABBREVIATION and detect_lang(text) != lang:
        raise RuleViolation(
            "script_mismatch",
            f"'{text}' does not look like {'Amharic' if lang == Lang.AM else 'English'}.",
        )


def _add_term(
    session: Session, concept: Concept, data: TermIn, actor: User | None, status: TermStatus
) -> Term:
    text = clean(data.text)
    _check_script(text, data.lang, data.formation)
    key = norm_key(text)
    if any(t.lang == data.lang and t.norm_key == key for t in concept.terms):
        raise RuleViolation("duplicate_term", f"'{text}' is already listed for this concept.")
    term = Term(
        lang=data.lang.value,
        text=text,
        norm_key=key,
        status=status,
        formation=data.formation,
        pos=data.pos,
        transliteration=data.transliteration,
        note=data.note,
        proposed_by_id=actor.id if actor else None,
        sources=[_source(s) for s in data.sources],
    )
    concept.terms.append(term)
    return term


def _source(s: SourceIn) -> Source:
    return Source(kind=s.kind, citation=s.citation, url=str(s.url) if s.url else None)


def create_concept(session: Session, actor: User, data: ConceptIn) -> Concept:
    domain.check_domain(data.domain)
    if session.scalar(select(Concept.id).where(Concept.slug == data.slug)):
        raise RuleViolation("duplicate_concept", f"Concept '{data.slug}' already exists.")
    if not any(t.lang == Lang.EN for t in data.terms):
        raise RuleViolation("missing_headword", "A concept needs at least one English term.")

    concept = Concept(
        slug=data.slug,
        domain=data.domain,
        subdomain=data.subdomain,
        definition_en=data.definition_en,
        definition_am=data.definition_am,
        note=data.note,
    )
    session.add(concept)
    # The first English term is the headword. Everything else starts as a
    # proposal; English variants still need a reviewer to admit them.
    headword_done = False
    for t in data.terms:
        is_headword = t.lang == Lang.EN and not headword_done
        headword_done = headword_done or is_headword
        _add_term(
            session, concept, t, actor, TermStatus.PREFERRED if is_headword else TermStatus.PROPOSED
        )
    audit(session, actor, "concept.create", concept)
    for term in concept.terms:
        audit(session, actor, "term.propose", term)
    session.commit()
    return concept


def update_concept(session: Session, actor: User, concept: Concept, patch: ConceptPatch) -> Concept:
    if actor.role not in {Role.REVIEWER, Role.ADMIN}:
        raise RuleViolation("not_reviewer", "Only reviewers can edit concept definitions.")
    before = _snapshot(concept)
    for field, value in patch.model_dump(exclude_unset=True).items():
        setattr(concept, field, value)
    audit(session, actor, "concept.update", concept, before)
    session.commit()
    return concept


def propose_term(session: Session, actor: User, concept: Concept, data: TermIn) -> Term:
    term = _add_term(session, concept, data, actor, TermStatus.PROPOSED)
    audit(session, actor, "term.propose", term)
    session.commit()
    return term


def review_term(
    session: Session, actor: User, term: Term, decision: Decision, comment: str | None
) -> Review:
    siblings = term.concept.terms
    outcome = domain.decide(
        actor_id=actor.id,
        actor_role=actor.role,
        proposer_id=term.proposed_by_id,
        term=term,
        siblings=siblings,
        decision=decision,
        comment=comment,
    )
    for sibling in siblings:
        if sibling.id in outcome.demote_ids:
            before = _snapshot(sibling)
            sibling.status = TermStatus.ADMITTED
            audit(session, actor, "term.demote", sibling, before)

    before = _snapshot(term)
    review = Review(
        term=term,
        reviewer_id=actor.id,
        decision=decision,
        from_status=TermStatus(term.status),
        to_status=outcome.new_status,
        comment=(comment or "").strip() or None,
    )
    term.status = outcome.new_status
    session.add(review)
    audit(session, actor, f"term.{decision.value}", term, before)
    session.commit()
    return review


def resubmit_term(session: Session, actor: User, term: Term, data: ResubmitIn) -> Term:
    new_status = domain.check_resubmit(
        actor_id=actor.id, proposer_id=term.proposed_by_id, status=TermStatus(term.status)
    )
    before = _snapshot(term)
    if data.text:
        text = clean(data.text)
        _check_script(text, Lang(term.lang), term.formation)
        key = norm_key(text)
        if any(
            t.id != term.id and t.lang == term.lang and t.norm_key == key
            for t in term.concept.terms
        ):
            raise RuleViolation("duplicate_term", f"'{text}' is already listed for this concept.")
        term.text, term.norm_key = text, key
    if data.note is not None:
        term.note = data.note
    term.status = new_status
    audit(session, actor, "term.resubmit", term, before)
    session.commit()
    return term


def vote(session: Session, actor: User, term: Term, value: int) -> int:
    """Set the actor's vote (+1, -1, or 0 to clear). Returns the new score."""
    existing = session.scalar(select(Vote).where(Vote.term_id == term.id, Vote.user_id == actor.id))
    if value == 0:
        if existing:
            session.delete(existing)
    elif existing:
        existing.value = value
    else:
        session.add(Vote(term_id=term.id, user_id=actor.id, value=value))
    session.commit()
    # Ask the database rather than the (possibly stale) loaded relationship.
    session.expire(term, ["votes"])
    return int(
        session.scalar(
            select(func.coalesce(func.sum(Vote.value), 0)).where(Vote.term_id == term.id)
        )
        or 0
    )


# ---------------------------------------------------------------- records <-> rows


def to_record(concept: Concept) -> ConceptRecord:
    terms: list[TermRecord] = []
    for t in concept.terms:
        tr: TermRecord = {"lang": t.lang, "text": t.text, "status": str(t.status)}
        if t.formation:
            tr["formation"] = str(t.formation)
        if t.pos:
            tr["pos"] = t.pos
        if t.transliteration:
            tr["transliteration"] = t.transliteration
        if t.note:
            tr["note"] = t.note
        if t.sources:
            srcs: list[SourceRecord] = []
            for s in t.sources:
                sr: SourceRecord = {"kind": str(s.kind), "citation": s.citation}
                if s.url:
                    sr["url"] = s.url
                srcs.append(sr)
            tr["sources"] = srcs
        terms.append(tr)
    record: ConceptRecord = {"id": concept.slug, "domain": concept.domain, "terms": terms}
    for key in ("subdomain", "definition_en", "definition_am", "note"):
        value = getattr(concept, key)
        if value:
            record[key] = value  # type: ignore[literal-required]
    return record


def export_records(session: Session, *, published_only: bool) -> list[ConceptRecord]:
    concepts = session.scalars(
        select(Concept)
        .options(selectinload(Concept.terms).selectinload(Term.sources))
        .order_by(Concept.slug)
    ).all()
    return select_records((to_record(c) for c in concepts), published_only=published_only)


@dataclass
class ImportResult:
    concepts_created: int = 0
    concepts_updated: int = 0
    terms_created: int = 0
    terms_updated: int = 0


def import_records(
    session: Session, records: Iterable[ConceptRecord], actor: User | None = None
) -> ImportResult:
    """Upsert records (e.g. from data/concepts/*.jsonl) into the database.

    Matching is by concept slug and by (lang, folded key) for terms, so the
    import is idempotent. Statuses from the files are taken as-is: the git
    files are the reviewed source of record.
    """
    result = ImportResult()
    for rec in records:
        concept = session.scalar(
            select(Concept).where(Concept.slug == rec["id"]).options(selectinload(Concept.terms))
        )
        fields = {k: rec.get(k) for k in ("subdomain", "definition_en", "definition_am", "note")}
        if concept is None:
            concept = Concept(slug=rec["id"], domain=rec["domain"], **fields)
            session.add(concept)
            result.concepts_created += 1
        else:
            concept.domain = rec["domain"]
            for k, v in fields.items():
                setattr(concept, k, v)
            result.concepts_updated += 1

        for tr in rec["terms"]:
            key = norm_key(tr["text"])
            term = next(
                (t for t in concept.terms if t.lang == tr["lang"] and t.norm_key == key), None
            )
            status = TermStatus(tr["status"])
            formation = Formation(tr["formation"]) if tr.get("formation") else None
            if term is None:
                term = Term(lang=tr["lang"], text=clean(tr["text"]), norm_key=key)
                concept.terms.append(term)
                result.terms_created += 1
            else:
                result.terms_updated += 1
            term.status = status
            term.formation = formation
            term.pos = tr.get("pos")
            term.transliteration = tr.get("transliteration")
            term.note = tr.get("note")
            term.sources = [
                Source(kind=SourceKind(s["kind"]), citation=s["citation"], url=s.get("url"))
                for s in tr.get("sources", [])
            ]
        session.flush()
        audit(session, actor, "concept.import", concept)
    session.commit()
    return result
