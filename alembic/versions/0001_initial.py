"""Initial termbase schema.

Revision ID: 0001
Revises:
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = ("contributor", "reviewer", "admin")
STATUS = ("proposed", "changes_requested", "rejected", "preferred", "admitted", "deprecated")
FORMATION = ("native", "extension", "loan", "calque", "abbreviation", "phrase")
DECISION = ("approve_preferred", "approve_admitted", "request_changes", "reject", "deprecate")
SOURCE = ("glossary", "textbook", "standard", "web", "media", "coined", "draft")


def enum(name: str, values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=24, create_constraint=True)


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    if is_pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    now = sa.text("CURRENT_TIMESTAMP")
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("handle", sa.String(64), nullable=False, unique=True),
        sa.Column("role", enum("role", ROLE), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_table(
        "concepts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(96), nullable=False, unique=True),
        sa.Column("domain", sa.String(32), nullable=False, index=True),
        sa.Column("subdomain", sa.String(96)),
        sa.Column("definition_en", sa.Text),
        sa.Column("definition_am", sa.Text),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_table(
        "terms",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "concept_id",
            sa.Integer,
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("lang", sa.String(2), nullable=False),
        sa.Column("text", sa.String(255), nullable=False),
        sa.Column("norm_key", sa.String(255), nullable=False),
        sa.Column("status", enum("termstatus", STATUS), nullable=False, index=True),
        sa.Column("formation", enum("formation", FORMATION)),
        sa.Column("pos", sa.String(24)),
        sa.Column("transliteration", sa.String(255)),
        sa.Column("note", sa.Text),
        sa.Column("proposed_by_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.UniqueConstraint("concept_id", "lang", "norm_key", name="uq_term_per_concept"),
        sa.CheckConstraint("lang IN ('en', 'am')", name="ck_term_lang"),
    )
    if is_pg:
        op.execute("CREATE INDEX ix_terms_norm_key_trgm ON terms USING gin (norm_key gin_trgm_ops)")
    else:
        op.create_index("ix_terms_norm_key_trgm", "terms", ["norm_key"])

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "term_id",
            sa.Integer,
            sa.ForeignKey("terms.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", enum("sourcekind", SOURCE), nullable=False),
        sa.Column("citation", sa.Text, nullable=False),
        sa.Column("url", sa.String(2048)),
    )
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "term_id",
            sa.Integer,
            sa.ForeignKey("terms.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("reviewer_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decision", enum("decision", DECISION), nullable=False),
        sa.Column("from_status", enum("from_status", STATUS), nullable=False),
        sa.Column("to_status", enum("to_status", STATUS), nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_table(
        "votes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "term_id",
            sa.Integer,
            sa.ForeignKey("terms.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("value", sa.SmallInteger, nullable=False),
        sa.UniqueConstraint("term_id", "user_id", name="uq_vote_per_user"),
        sa.CheckConstraint("value IN (-1, 1)", name="ck_vote_value"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(48), nullable=False, index=True),
        sa.Column("entity", sa.String(24), nullable=False),
        sa.Column("entity_id", sa.Integer, nullable=False),
        sa.Column("before", sa.JSON),
        sa.Column("after", sa.JSON),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=now, index=True
        ),
    )


def downgrade() -> None:
    for table in ("audit_events", "votes", "reviews", "sources", "terms", "concepts", "users"):
        op.drop_table(table)
