"""Import terms from the Amharic Microsoft Digital Literacy Curriculum (2007).

Reads data/sources/microsoft-dlc-amharic-2007.jsonl: terms from the glossaries
of five course books (Computer Basics, Computer Security and Privacy, Digital
Lifestyles, The Internet and the World Wide Web, Productivity Programs) plus
hand-picked "Amharic (English)" pairs from the course text.

The books are © 2007 Microsoft, all rights reserved, so only the terms are
taken (with a citation), never definitions. The glossaries rarely print the
English; it was paired by AI from the English edition's alphabetical
glossary order, and the citation says so.

Every term is added as *proposed*. Running it again changes nothing.

    uv run python scripts/import_dlc.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_elrc as elrc

from tech_amharic.normalize import clean, detect_lang, norm_key
from tech_amharic.records import read_dir, validate, write_domain_files
from tech_amharic.suggestions import slugify

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "sources" / "microsoft-dlc-amharic-2007.jsonl"
PREFIX = "Microsoft Digital Literacy Curriculum (Amharic, © 2007 Microsoft)"
NOTE = (
    "Imported from the Microsoft Digital Literacy Curriculum (Amharic, 2007); "
    "domain assigned automatically."
)
# Course-text entries that are commands (verbs) where the glossary has a
# separate verb concept.
TARGET = {"copy": "copy-verb"}
BOOK_DOMAIN = {
    "Computer Basics": "hardware",
    "Computer Security and Privacy": "security",
    "Digital Lifestyles": "general",
    "The Internet and the World Wide Web": "networking",
    "Productivity Programs": "software",
}


def citation(row: dict[str, Any]) -> str:
    if row["where"] == "glossary":
        return f"{PREFIX}, {row['book']}, glossary: “{row['printed']}”; English pairing by AI"
    return f"{PREFIX}, {row['book']}, course text: “{row['printed']}”"


def term(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "lang": "am",
        "text": clean(row["am"]),
        "status": "proposed",
        "sources": [{"kind": "textbook", "citation": citation(row)}],
    }


def run(records: list[dict[str, Any]], rows: list[dict[str, Any]]) -> tuple[list, Counter]:
    stats: Counter = Counter()
    by_en: dict[str, dict[str, Any]] = {}
    for r in records:
        for t in r["terms"]:
            if t["lang"] == "en":
                by_en.setdefault(norm_key(t["text"]), r)
    taken = {r["id"] for r in records}
    for row in rows:
        new = term(row)
        if detect_lang(new["text"]) != "am":
            stats["skipped: not Amharic script"] += 1
            continue
        by_id = {r["id"]: r for r in records}
        concept = by_id.get(TARGET.get(row["en"], "")) or by_en.get(norm_key(row["en"]))
        if concept is None:
            cid, n = slugify(row["en"]), 2
            while cid in taken:
                cid, n = f"{slugify(row['en'])}-{n}", n + 1
            domain = elrc.classify(row["en"], "")
            concept = {
                "id": cid,
                "domain": domain if domain != "general" else BOOK_DOMAIN[row["book"]],
                "terms": [{"lang": "en", "text": clean(row["en"]), "status": "preferred"}],
                "note": NOTE,
            }
            records.append(concept)
            taken.add(cid)
            by_en[norm_key(row["en"])] = concept
            stats["concept created"] += 1
        elrc.add_term(concept, new, stats)

    problems = [p for r in records for p in validate(r)]
    if problems:
        raise SystemExit("Validation failed:\n" + "\n".join(problems[:30]))
    return records, stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "concepts")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
    records, stats = run([dict(r) for r in read_dir(args.data)], rows)
    for k, v in sorted(stats.items()):
        print(f"{v:5d}  {k}")
    if not args.dry_run:
        write_domain_files(records, args.data)  # type: ignore[arg-type]
        print(f"{len(records)} concepts written to {args.data}")


if __name__ == "__main__":
    main()
