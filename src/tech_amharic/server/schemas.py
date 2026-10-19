"""Request and response bodies. Pydantic validates every write at the edge."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from ..domain import Decision, Formation, Lang, Role, SourceKind, TermStatus

SLUG = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class SourceIn(BaseModel):
    kind: SourceKind
    citation: str = Field(min_length=3, max_length=1000)
    url: HttpUrl | None = None


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    kind: SourceKind
    citation: str
    url: str | None


class TermIn(BaseModel):
    lang: Lang
    text: str = Field(min_length=1, max_length=255)
    formation: Formation | None = None
    pos: str | None = Field(default=None, max_length=24)
    transliteration: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    sources: list[SourceIn] = Field(default_factory=list, max_length=10)


class TermOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lang: Lang
    text: str
    status: TermStatus
    formation: Formation | None
    pos: str | None
    transliteration: str | None
    note: str | None
    score: int
    sources: list[SourceOut]


class ConceptIn(BaseModel):
    slug: str = Field(pattern=SLUG, max_length=96)
    domain: str
    subdomain: str | None = Field(default=None, max_length=96)
    definition_en: str | None = Field(default=None, max_length=4000)
    definition_am: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=4000)
    # The English headword is required; Amharic proposals can come later.
    terms: list[TermIn] = Field(min_length=1, max_length=20)


class ConceptPatch(BaseModel):
    """Reviewers can edit definitions and notes; terms change through review."""

    subdomain: str | None = Field(default=None, max_length=96)
    definition_en: str | None = Field(default=None, max_length=4000)
    definition_am: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=4000)


class ConceptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    slug: str
    domain: str
    subdomain: str | None
    definition_en: str | None
    definition_am: str | None
    note: str | None
    terms: list[TermOut]
    updated_at: datetime


class ConceptSummary(BaseModel):
    slug: str
    domain: str
    en: str
    am_preferred: str | None
    am_candidates: list[str]


class ReviewIn(BaseModel):
    decision: Decision
    comment: str | None = Field(default=None, max_length=2000)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    decision: Decision
    from_status: TermStatus
    to_status: TermStatus
    comment: str | None
    created_at: datetime


class ResubmitIn(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=2000)


class VoteIn(BaseModel):
    value: int = Field(ge=-1, le=1)


class QueueItem(BaseModel):
    term_id: int
    concept_slug: str
    en: str
    text: str
    formation: Formation | None
    score: int
    proposed_by: str | None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    handle: str
    role: Role


class ErrorOut(BaseModel):
    code: str
    detail: str
