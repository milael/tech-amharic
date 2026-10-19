"""Termbase vocabulary and review rules.

This module has no framework imports on purpose. The API, the web UI and the
CLI all call the same functions, and the rules can be unit-tested without a
database.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Lang(StrEnum):
    EN = "en"
    AM = "am"


class TermStatus(StrEnum):
    """Usage status of one written form. Mirrors TBX administrative status."""

    PROPOSED = "proposed"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"
    PREFERRED = "preferred"
    ADMITTED = "admitted"
    DEPRECATED = "deprecated"


# Statuses a reviewer has signed off on. Only these reach exports.
PUBLISHED: frozenset[TermStatus] = frozenset(
    {TermStatus.PREFERRED, TermStatus.ADMITTED, TermStatus.DEPRECATED}
)


class Formation(StrEnum):
    """How an Amharic term was formed. Reviewers argue about this most."""

    NATIVE = "native"  # new coinage from Amharic roots
    EXTENSION = "extension"  # existing word given a technical sense
    LOAN = "loan"  # English sound written in Ge'ez script
    CALQUE = "calque"  # parts translated literally
    ABBREVIATION = "abbreviation"  # kept acronym, e.g. API
    PHRASE = "phrase"  # descriptive multi-word expression


class Role(StrEnum):
    CONTRIBUTOR = "contributor"
    REVIEWER = "reviewer"
    ADMIN = "admin"


class Decision(StrEnum):
    APPROVE_PREFERRED = "approve_preferred"
    APPROVE_ADMITTED = "approve_admitted"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"
    DEPRECATE = "deprecate"


class SourceKind(StrEnum):
    GLOSSARY = "glossary"
    TEXTBOOK = "textbook"
    STANDARD = "standard"
    WEB = "web"
    MEDIA = "media"
    COINED = "coined"
    DRAFT = "draft"  # unreviewed draft, e.g. LLM-assisted seed data


DOMAINS: dict[str, str] = {
    "ai-ml": "AI and machine learning",
    "security": "Cybersecurity",
    "networking": "Networking and the internet",
    "software": "Software engineering",
    "cloud-devops": "Cloud and DevOps",
    "data": "Data and databases",
    "hardware": "Hardware",
    "general": "General computing",
}

# Which decisions are allowed from which status, and the status they lead to.
_TRANSITIONS: dict[TermStatus, dict[Decision, TermStatus]] = {
    TermStatus.PROPOSED: {
        Decision.APPROVE_PREFERRED: TermStatus.PREFERRED,
        Decision.APPROVE_ADMITTED: TermStatus.ADMITTED,
        Decision.REQUEST_CHANGES: TermStatus.CHANGES_REQUESTED,
        Decision.REJECT: TermStatus.REJECTED,
    },
    TermStatus.CHANGES_REQUESTED: {
        Decision.REJECT: TermStatus.REJECTED,
    },
    TermStatus.PREFERRED: {
        Decision.APPROVE_ADMITTED: TermStatus.ADMITTED,  # step down, keep it
        Decision.DEPRECATE: TermStatus.DEPRECATED,
    },
    TermStatus.ADMITTED: {
        Decision.APPROVE_PREFERRED: TermStatus.PREFERRED,  # promote
        Decision.DEPRECATE: TermStatus.DEPRECATED,
    },
    TermStatus.DEPRECATED: {
        Decision.APPROVE_ADMITTED: TermStatus.ADMITTED,  # reinstate
    },
    TermStatus.REJECTED: {},  # terminal: propose again as a new term
}

_COMMENT_REQUIRED: frozenset[Decision] = frozenset(
    {Decision.REJECT, Decision.REQUEST_CHANGES, Decision.DEPRECATE}
)


class RuleViolation(Exception):
    """A request broke a termbase rule. ``code`` is stable for API clients."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TermLike(Protocol):
    """Anything with these attributes: ORM rows, dataclasses, test doubles."""

    @property
    def id(self) -> int: ...
    @property
    def lang(self) -> str: ...
    @property
    def status(self) -> str: ...


@dataclass(frozen=True)
class ReviewOutcome:
    new_status: TermStatus
    demote_ids: tuple[int, ...]  # other terms that lose preferred status


def allowed_decisions(status: TermStatus) -> list[Decision]:
    return list(_TRANSITIONS[status])


def decide(
    *,
    actor_id: int,
    actor_role: Role,
    proposer_id: int | None,
    term: TermLike,
    siblings: Iterable[TermLike],
    decision: Decision,
    comment: str | None,
) -> ReviewOutcome:
    """Validate a review decision and work out its effects.

    ``siblings`` are the other terms of the same concept. Raises
    ``RuleViolation`` when the decision is not allowed.
    """
    if actor_role not in {Role.REVIEWER, Role.ADMIN}:
        raise RuleViolation("not_reviewer", "Only reviewers can record decisions.")
    if proposer_id is not None and proposer_id == actor_id:
        raise RuleViolation("self_review", "You cannot review a term you proposed.")

    current = TermStatus(term.status)
    options = _TRANSITIONS[current]
    if decision not in options:
        allowed = ", ".join(options) or "none"
        raise RuleViolation(
            "invalid_transition",
            f"Cannot '{decision}' a term that is '{current}'. Allowed: {allowed}.",
        )
    if decision in _COMMENT_REQUIRED and not (comment and comment.strip()):
        raise RuleViolation("comment_required", f"A comment is required to '{decision}'.")

    new_status = options[decision]
    demote: tuple[int, ...] = ()
    if new_status is TermStatus.PREFERRED:
        # One preferred term per concept and language. The old one is kept as
        # admitted so lookups still find it.
        demote = tuple(
            s.id
            for s in siblings
            if s.id != term.id and s.lang == term.lang and s.status == TermStatus.PREFERRED
        )
    return ReviewOutcome(new_status=new_status, demote_ids=demote)


def check_resubmit(*, actor_id: int, proposer_id: int | None, status: TermStatus) -> TermStatus:
    """A proposer edits a term after 'changes requested'; it goes back in the queue."""
    if status is not TermStatus.CHANGES_REQUESTED:
        raise RuleViolation(
            "invalid_transition", "Only terms with requested changes can be resubmitted."
        )
    if proposer_id != actor_id:
        raise RuleViolation("not_proposer", "Only the original proposer can resubmit this term.")
    return TermStatus.PROPOSED


def check_domain(domain: str) -> str:
    if domain not in DOMAINS:
        raise RuleViolation(
            "unknown_domain", f"Unknown domain '{domain}'. Use one of: {', '.join(DOMAINS)}."
        )
    return domain
