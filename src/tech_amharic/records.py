"""The canonical concept record and everything that reads or writes it.

A *record* is one concept as a plain dict. It is the format of the files in
``data/``, of the release bundle, and of the API's export endpoint. Keeping it
framework-free means the git data, the CLI and the dataset builder never need
a database.

Shape::

    {
      "id": "kernel-os",                    # stable slug
      "domain": "software",
      "subdomain": "operating systems",     # optional
      "definition_en": "...",               # optional
      "definition_am": "...",               # optional
      "note": "...",                        # optional
      "terms": [
        {"lang": "en", "text": "kernel", "status": "preferred"},
        {"lang": "am", "text": "ከርነል", "status": "proposed",
         "formation": "loan", "pos": "noun",
         "sources": [{"kind": "draft", "citation": "..."}]}
      ]
    }
"""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from .domain import DOMAINS, PUBLISHED, Formation, Lang, SourceKind, TermStatus
from .normalize import clean, detect_lang

BUNDLE_SCHEMA = "tech-amharic-bundle/1"
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SourceRecord(TypedDict):
    kind: str
    citation: str
    url: NotRequired[str]


class TermRecord(TypedDict):
    lang: str
    text: str
    status: str
    formation: NotRequired[str]
    pos: NotRequired[str]
    transliteration: NotRequired[str]
    note: NotRequired[str]
    sources: NotRequired[list[SourceRecord]]


class ConceptRecord(TypedDict):
    id: str
    domain: str
    terms: list[TermRecord]
    subdomain: NotRequired[str]
    definition_en: NotRequired[str]
    definition_am: NotRequired[str]
    note: NotRequired[str]


# ---------------------------------------------------------------- validation


def validate(record: dict[str, Any]) -> list[str]:
    """Return human-readable problems with a record; empty list means valid."""
    problems: list[str] = []
    cid = record.get("id", "<no id>")

    def bad(msg: str) -> None:
        problems.append(f"{cid}: {msg}")

    if not isinstance(record.get("id"), str) or not _SLUG.match(record["id"]):
        bad("id must be a lowercase slug like 'vector-embedding'")
    if record.get("domain") not in DOMAINS:
        bad(f"domain must be one of {sorted(DOMAINS)}")
    terms = record.get("terms")
    if not isinstance(terms, list) or not terms:
        bad("needs at least one term")
        return problems

    preferred_per_lang: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    for t in terms:
        text = t.get("text", "")
        if not isinstance(text, str) or not text.strip():
            bad("term with empty text")
            continue
        if t.get("lang") not in set(Lang):
            bad(f"'{text}': lang must be 'en' or 'am'")
        elif detect_lang(text) != t["lang"] and t.get("formation") != Formation.ABBREVIATION:
            bad(f"'{text}': script does not match lang '{t['lang']}'")
        if t.get("status") not in set(TermStatus):
            bad(f"'{text}': unknown status '{t.get('status')}'")
        if "formation" in t and t["formation"] not in set(Formation):
            bad(f"'{text}': unknown formation '{t['formation']}'")
        for s in t.get("sources", []):
            if s.get("kind") not in set(SourceKind) or not s.get("citation"):
                bad(f"'{text}': each source needs a known kind and a citation")
        key = (t.get("lang", ""), clean(text))
        if key in seen:
            bad(f"'{text}': duplicate term")
        seen.add(key)
        if t.get("status") == TermStatus.PREFERRED:
            preferred_per_lang[t["lang"]] = preferred_per_lang.get(t["lang"], 0) + 1

    for lang, n in preferred_per_lang.items():
        if n > 1:
            bad(f"{n} preferred terms for lang '{lang}'; at most one allowed")
    return problems


# ---------------------------------------------------------------- reading


def read_jsonl(path: Path) -> Iterator[ConceptRecord]:
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON ({exc.msg})") from exc


def read_dir(directory: Path) -> list[ConceptRecord]:
    records: list[ConceptRecord] = []
    for path in sorted(directory.glob("*.jsonl")):
        records.extend(read_jsonl(path))
    return records


# ---------------------------------------------------------------- selection


def published_view(record: ConceptRecord) -> ConceptRecord | None:
    """Keep only reviewed terms. Drop the concept if no Amharic term survives."""
    terms = [t for t in record["terms"] if t["status"] in PUBLISHED]
    if not any(t["lang"] == Lang.AM for t in terms):
        return None
    out: ConceptRecord = {**record, "terms": terms}
    return out


def select(records: Iterable[ConceptRecord], *, published_only: bool) -> list[ConceptRecord]:
    if not published_only:
        return list(records)
    return [r for r in (published_view(rec) for rec in records) if r is not None]


def preferred(record: ConceptRecord, lang: str) -> str | None:
    for t in record["terms"]:
        if t["lang"] == lang and t["status"] == TermStatus.PREFERRED:
            return t["text"]
    return None


def by_status(record: ConceptRecord, lang: str, *statuses: str) -> list[str]:
    return [t["text"] for t in record["terms"] if t["lang"] == lang and t["status"] in statuses]


def headword(record: ConceptRecord) -> str:
    """The English label for a concept, even if nothing is preferred yet."""
    return preferred(record, Lang.EN) or next(
        (t["text"] for t in record["terms"] if t["lang"] == Lang.EN), record["id"]
    )


# ---------------------------------------------------------------- writers


def to_jsonl(records: Iterable[ConceptRecord]) -> str:
    return "".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
        for r in sorted(records, key=lambda r: r["id"])
    )


def write_domain_files(records: Iterable[ConceptRecord], directory: Path) -> list[Path]:
    """Write one JSONL file per domain, sorted, so git diffs stay readable."""
    directory.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[ConceptRecord]] = {}
    for r in records:
        grouped.setdefault(r["domain"], []).append(r)
    written: list[Path] = []
    for domain, items in sorted(grouped.items()):
        path = directory / f"{domain}.jsonl"
        path.write_text(to_jsonl(items), encoding="utf-8")
        written.append(path)
    return written


CSV_COLUMNS = [
    "id",
    "domain",
    "en",
    "am_preferred",
    "am_admitted",
    "am_deprecated",
    "am_proposed",
    "definition_en",
    "definition_am",
]


def to_csv(records: Iterable[ConceptRecord]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for r in sorted(records, key=lambda r: r["id"]):
        writer.writerow(
            {
                "id": r["id"],
                "domain": r["domain"],
                "en": headword(r),
                "am_preferred": preferred(r, Lang.AM) or "",
                "am_admitted": "; ".join(by_status(r, Lang.AM, TermStatus.ADMITTED)),
                "am_deprecated": "; ".join(by_status(r, Lang.AM, TermStatus.DEPRECATED)),
                "am_proposed": "; ".join(by_status(r, Lang.AM, TermStatus.PROPOSED)),
                "definition_en": r.get("definition_en", ""),
                "definition_am": r.get("definition_am", ""),
            }
        )
    return buf.getvalue()


# TBX-Basic administrative status values (ISO 30042 data categories).
_TBX_STATUS = {
    TermStatus.PREFERRED: "preferredTerm-admn-sts",
    TermStatus.ADMITTED: "admittedTerm-admn-sts",
    TermStatus.DEPRECATED: "deprecatedTerm-admn-sts",
}
TBX_NS = "urn:iso:std:iso:30042:ed-2"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _q(tag: str) -> str:
    return f"{{{TBX_NS}}}{tag}"


def to_tbx(records: Iterable[ConceptRecord], *, title: str = "Tech-Amharic termbase") -> str:
    """Export as TBX-Basic (DCA style), importable by Trados, memoQ and others.

    Unreviewed terms carry no administrative status, so tools treat them as
    plain candidates.
    """
    ET.register_namespace("", TBX_NS)
    root = ET.Element(
        _q("tbx"),
        {"type": "TBX-Basic", "style": "dca", _XML_LANG: "en"},
    )
    header = ET.SubElement(root, _q("tbxHeader"))
    file_desc = ET.SubElement(header, _q("fileDesc"))
    source_desc = ET.SubElement(file_desc, _q("sourceDesc"))
    ET.SubElement(source_desc, _q("p")).text = title
    body = ET.SubElement(ET.SubElement(root, _q("text")), _q("body"))

    for r in sorted(records, key=lambda r: r["id"]):
        entry = ET.SubElement(body, _q("conceptEntry"), {"id": r["id"]})
        ET.SubElement(entry, _q("descrip"), {"type": "subjectField"}).text = DOMAINS.get(
            r["domain"], r["domain"]
        )
        if r.get("note"):
            ET.SubElement(entry, _q("note")).text = r["note"]
        for lang in (Lang.EN, Lang.AM):
            terms = [t for t in r["terms"] if t["lang"] == lang]
            if not terms:
                continue
            lang_sec = ET.SubElement(entry, _q("langSec"), {_XML_LANG: lang})
            definition = r.get("definition_en") if lang == Lang.EN else r.get("definition_am")
            if definition:
                ET.SubElement(lang_sec, _q("descrip"), {"type": "definition"}).text = definition
            for t in terms:
                sec = ET.SubElement(lang_sec, _q("termSec"))
                ET.SubElement(sec, _q("term")).text = t["text"]
                status = _TBX_STATUS.get(TermStatus(t["status"]))
                if status:
                    ET.SubElement(
                        sec, _q("termNote"), {"type": "administrativeStatus"}
                    ).text = status
                if t.get("pos"):
                    ET.SubElement(sec, _q("termNote"), {"type": "partOfSpeech"}).text = t["pos"]
                for s in t.get("sources", []):
                    ET.SubElement(sec, _q("admin"), {"type": "source"}).text = s["citation"]

    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def to_bundle(
    records: Iterable[ConceptRecord], *, version: str, generated_at: str
) -> dict[str, Any]:
    """The static file the CLI, VS Code extension and MCP server read."""
    items = sorted(records, key=lambda r: r["id"])
    return {
        "schema": BUNDLE_SCHEMA,
        "version": version,
        "generated_at": generated_at,
        "license": "CC-BY-SA-4.0",
        "count": len(items),
        "concepts": items,
    }
