"""ORM models. Each table maps to a TBX element (see the design doc)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..domain import Decision, Formation, Role, SourceKind, TermStatus


def _enum(e: type[StrEnum]) -> Enum:
    # Stored as VARCHAR + CHECK (not a native PG enum) so adding a value is a
    # one-line migration.
    return Enum(e, native_enum=False, values_callable=lambda cls: [m.value for m in cls], length=24)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: DateTime(timezone=True)}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    handle: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[Role] = mapped_column(_enum(Role), default=Role.CONTRIBUTOR)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Concept(TimestampMixin, Base):
    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(96), unique=True)
    domain: Mapped[str] = mapped_column(String(32), index=True)
    subdomain: Mapped[str | None] = mapped_column(String(96))
    definition_en: Mapped[str | None] = mapped_column(Text)
    definition_am: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)

    terms: Mapped[list[Term]] = relationship(
        back_populates="concept", cascade="all, delete-orphan", order_by="Term.id"
    )


class Term(TimestampMixin, Base):
    __tablename__ = "terms"
    __table_args__ = (
        UniqueConstraint("concept_id", "lang", "norm_key", name="uq_term_per_concept"),
        CheckConstraint("lang IN ('en', 'am')", name="ck_term_lang"),
        # Fuzzy search. On PostgreSQL this is a trigram GIN index; other
        # databases get a plain index.
        Index(
            "ix_terms_norm_key_trgm",
            "norm_key",
            postgresql_using="gin",
            postgresql_ops={"norm_key": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    concept_id: Mapped[int] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), index=True
    )
    lang: Mapped[str] = mapped_column(String(2))
    text: Mapped[str] = mapped_column(String(255))
    norm_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[TermStatus] = mapped_column(
        _enum(TermStatus), default=TermStatus.PROPOSED, index=True
    )
    formation: Mapped[Formation | None] = mapped_column(_enum(Formation))
    pos: Mapped[str | None] = mapped_column(String(24))
    transliteration: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    proposed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    concept: Mapped[Concept] = relationship(back_populates="terms")
    proposed_by: Mapped[User | None] = relationship()
    sources: Mapped[list[Source]] = relationship(cascade="all, delete-orphan", order_by="Source.id")
    reviews: Mapped[list[Review]] = relationship(
        cascade="all, delete-orphan", order_by="Review.id", back_populates="term"
    )
    votes: Mapped[list[Vote]] = relationship(cascade="all, delete-orphan")

    @property
    def score(self) -> int:
        return sum(v.value for v in self.votes)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id", ondelete="CASCADE"), index=True)
    kind: Mapped[SourceKind] = mapped_column(_enum(SourceKind))
    citation: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(2048))


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decision: Mapped[Decision] = mapped_column(_enum(Decision))
    from_status: Mapped[TermStatus] = mapped_column(_enum(TermStatus))
    to_status: Mapped[TermStatus] = mapped_column(_enum(TermStatus))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    term: Mapped[Term] = relationship(back_populates="reviews")
    reviewer: Mapped[User | None] = relationship()


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("term_id", "user_id", name="uq_vote_per_user"),
        CheckConstraint("value IN (-1, 1)", name="ck_vote_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    value: Mapped[int] = mapped_column(SmallInteger)


class AuditEvent(Base):
    """Append-only log of every write: who, what, before, after."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(48), index=True)
    entity: Mapped[str] = mapped_column(String(24))
    entity_id: Mapped[int] = mapped_column()
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
