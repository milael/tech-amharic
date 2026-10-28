"""Bring AI term suggestions into the glossary data as proposed terms.

The chat Worker stores suggestions made when a glossary search finds nothing
(see worker/src/suggest-core.js). This module turns them into concept
records: the English term becomes the headword, the Amharic options become
*proposed* terms, and every one carries a source saying which model made it
and when. Nothing here approves anything; reviewers do that.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from .domain import DOMAINS, Formation, Lang, SourceKind, TermStatus
from .normalize import clean, norm_key
from .records import ConceptRecord, SourceRecord, TermRecord, validate

AI_NOTE = "AI-generated suggestion; every Amharic term needs native-speaker review."


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "term"


def _unique_slug(base: str, taken: set[str]) -> str:
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def _is_acronym(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return 0 < len(letters) <= 5 and all(ch.isascii() and ch.isupper() for ch in letters)


def citation(suggestion: dict[str, Any]) -> str:
    model = suggestion.get("model") or "unknown model"
    day = str(suggestion.get("created_at") or "")[:10] or "unknown date"
    return f"AI suggestion ({model}), {day}; awaiting native-speaker review"


def to_record(suggestion: dict[str, Any], slug: str) -> ConceptRecord:
    term = clean(str(suggestion["term"]))
    en: TermRecord = {"lang": Lang.EN.value, "text": term, "status": TermStatus.PREFERRED.value}
    if _is_acronym(term):
        en["formation"] = Formation.ABBREVIATION.value
    source: SourceRecord = {"kind": SourceKind.DRAFT.value, "citation": citation(suggestion)}
    terms: list[TermRecord] = [en]
    for option in suggestion.get("terms", []):
        am: TermRecord = {
            "lang": Lang.AM.value,
            "text": clean(str(option.get("text", ""))),
            "status": TermStatus.PROPOSED.value,
            "sources": [source],
        }
        if option.get("formation") in set(Formation):
            am["formation"] = option["formation"]
        terms.append(am)
    record: ConceptRecord = {
        "id": slug,
        "domain": suggestion.get("domain") if suggestion.get("domain") in DOMAINS else "general",
        "terms": terms,
        "note": AI_NOTE,
    }
    if suggestion.get("definition_en"):
        record["definition_en"] = clean(str(suggestion["definition_en"]))
    if suggestion.get("definition_am"):
        record["definition_am"] = clean(str(suggestion["definition_am"]))
    return record


@dataclass
class MergeResult:
    records: list[ConceptRecord]
    added: list[str] = field(default_factory=list)  # new concept ids
    skipped: list[str] = field(default_factory=list)  # "term: reason"


def merge(records: Sequence[ConceptRecord], suggestions: Iterable[dict[str, Any]]) -> MergeResult:
    """Add suggestions whose term is not in the glossary yet. Idempotent."""
    out = list(records)
    taken = {r["id"] for r in out}
    known = {norm_key(t["text"]) for r in out for t in r["terms"]}
    result = MergeResult(records=out)
    for s in suggestions:
        term = str(s.get("term", "")).strip()
        if not term or s.get("notTechTerm"):
            continue
        if norm_key(term) in known:
            result.skipped.append(f"{term}: already in the glossary")
            continue
        record = to_record(s, _unique_slug(slugify(term), taken))
        problems = validate(dict(record))
        if problems:
            result.skipped.append(f"{term}: {'; '.join(problems)}")
            continue
        out.append(record)
        taken.add(record["id"])
        known.update(norm_key(t["text"]) for t in record["terms"])
        result.added.append(record["id"])
    return result


# ---------------------------------------------------------------- visitor proposals


def proposal_citation(proposal: dict[str, Any]) -> str:
    who = clean(str(proposal.get("name") or "")) or "an anonymous visitor"
    day = str(proposal.get("created_at") or "")[:10] or "unknown date"
    count = int(proposal.get("count") or 1)
    times = f"; submitted {count} times" if count > 1 else ""
    return f"Proposed on the demo by {who} (unverified), {day}{times}; awaiting review"


def merge_proposals(
    records: Sequence[ConceptRecord], proposals: Iterable[dict[str, Any]]
) -> MergeResult:
    """Add visitor proposals as *proposed* Amharic terms on their concepts. Idempotent.

    A proposal names a concept id, or the English term of an AI suggestion
    (which ``merge`` has turned into a concept by then).
    """
    out = [cast(ConceptRecord, dict(r)) for r in records]
    by_id = {r["id"]: r for r in out}
    by_term = {
        norm_key(t["text"]): r for r in out for t in r["terms"] if t["lang"] == Lang.EN.value
    }
    result = MergeResult(records=out)
    for p in proposals:
        text = clean(str(p.get("text", "")))
        if not text:
            continue
        concept = by_id.get(str(p.get("concept_id") or "")) or by_term.get(
            norm_key(str(p.get("term") or "-"))
        )
        label = f"{text} → {p.get('concept_id') or p.get('term')}"
        if concept is None:
            result.skipped.append(f"{label}: concept not found")
            continue
        if any(norm_key(t["text"]) == norm_key(text) for t in concept["terms"]):
            result.skipped.append(f"{label}: already listed")
            continue
        term: TermRecord = {
            "lang": Lang.AM.value,
            "text": text,
            "status": TermStatus.PROPOSED.value,
            "sources": [{"kind": SourceKind.COINED.value, "citation": proposal_citation(p)}],
        }
        if p.get("formation") in set(Formation):
            term["formation"] = p["formation"]
        if p.get("note"):
            term["note"] = f"Visitor note: {clean(str(p['note']))[:280]}"
        new_terms = [*concept["terms"], term]
        candidate: dict[str, Any] = {**concept, "terms": new_terms}
        problems = validate(candidate)
        if problems:
            result.skipped.append(f"{label}: {'; '.join(problems)}")
            continue
        concept["terms"] = new_terms
        result.added.append(label)
    return result
