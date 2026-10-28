"""Import the ELRC ICT glossary into data/concepts as *proposed* Amharic terms.

Reads data/sources/elrc-ict-glossary-2011.jsonl (made by elrc_extract.py).
Every Amharic term gets a source whose citation starts with "ELRC dictionary"
and names the entry number, so reviewers can check it against the PDF.

- An entry whose English word matches an existing concept adds its Amharic
  term there (or adds the ELRC source to the same term if we already have it),
  unless the ELRC entry means something else (SENSE_SPLIT).
- Other entries become new concepts with an automatically assigned domain.
- Nothing is approved. Running it again changes nothing.

    uv run python scripts/import_elrc.py            # writes data/concepts
    uv run python scripts/import_elrc.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from tech_amharic.normalize import clean, detect_lang, norm_key
from tech_amharic.records import read_dir, validate, write_domain_files
from tech_amharic.suggestions import slugify

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "sources" / "elrc-ict-glossary-2011.jsonl"
CITATION = (
    "ELRC dictionary: Translation of ICT Terms into Amharic, Oromo and Tigrigna "
    "(ICT Development Office & Ethiopian Languages Research Center, 2011), entry {no}"
)
NOTE = "Imported from the ELRC ICT glossary (2011); domain assigned automatically."

# ELRC entries whose English word is spelled like one of our concepts but
# means something else; they become separate concepts.
SENSE_SPLIT = {"prompt", "token", "model", "filter", "function", "framework", "display", "library"}

DOMAIN_WORDS = {
    "security": r"password|encrypt|decrypt|virus|malware|security|secure|firewall|authenticat|"
    r"permission|access control|hacker|spam|certificate|signature|privacy|attack|intrud",
    "networking": r"network|internet|protocol|router|tcp|\bip\b|\blan\b|\bwan\b|\bweb|http|url|"
    r"e-?mail|modem|ethernet|packet|bandwidth|browser|dns|server|online|wireless|telecom|"
    r"communications",
    "hardware": r"disk|\bcpu\b|processor|\bchip|printer|keyboard|monitor|circuit|\bport\b|cable|"
    r"\bdrive\b|mouse|hardware|\bram\b|\brom\b|peripheral|device|\bboard\b|scanner|battery|"
    r"\bbus\b|register",
    "data": r"database|\btable|\brecord|\bfield|query|spreadsheet|worksheet|\bcell\b|chart|"
    r"\bcolumn|\brow\b|pivot|\bsql\b|\bdata\b",
    "software": r"program|application|software|compiler|\bcode\b|function|variable|\bbug\b|debug|"
    r"script|operating system|\bfile|folder|director|menu|dialog|button|toolbar|window|"
    r"command|click|document|format|font|\bstyle|\btext|icon|install",
}
PRIORITY = list(DOMAIN_WORDS)  # tie-break order
SKIP_DEFINITION = re.compile(r"^(see\b|translation depends|$)", re.I)


def citation(no: int) -> str:
    return CITATION.format(no=no)


def split_term(am: str) -> tuple[str, str]:
    """'ኸርዝ(ኤችዜድ)' -> ('ኸርዝ', '(ኤችዜድ)'); explanations move to a note."""
    am = clean(am)
    m = re.match(r"^(.*?[ሀ-᎟][^(]*?)\s*(\(.*|-\s.*ይመልከቱ.*)$", am)
    if m and m.group(1).strip():
        return clean(m.group(1)), clean(m.group(2))
    return am, ""


def classify(en: str, definition: str) -> str:
    text = f"{en} {definition}".lower()
    hits = Counter({d: len(re.findall(rx, text)) for d, rx in DOMAIN_WORDS.items()})
    best = max(PRIORITY, key=lambda d: (hits[d], -PRIORITY.index(d)))
    return best if hits[best] else "general"


def am_term(row: dict[str, Any]) -> dict[str, Any] | None:
    text, gloss = split_term(row["am"])
    if not text or detect_lang(text) != "am":
        return None
    term: dict[str, Any] = {
        "lang": "am",
        "text": text,
        "status": "proposed",
        "sources": [{"kind": "glossary", "citation": citation(row["no"])}],
    }
    if gloss:
        term["note"] = f"ELRC note: {gloss}"
    return term


def add_term(concept: dict[str, Any], term: dict[str, Any], stats: Counter) -> None:
    for t in concept["terms"]:
        if t["lang"] == "am" and norm_key(t["text"]) == norm_key(term["text"]):
            cites = {s["citation"] for s in t.get("sources", [])}
            new = [s for s in term["sources"] if s["citation"] not in cites]
            if new:
                t.setdefault("sources", []).extend(new)
                stats["source added to an existing term"] += 1
            return
    concept["terms"].append(term)
    stats["term added"] += 1


def suffixes(rows: list[dict[str, Any]]) -> list[str]:
    defs = {clean(r["definition"]).lower() for r in rows}
    if len(rows) == 1 or len(defs) == 1:
        return [""] * len(rows)  # same meaning: one concept, several terms
    out, seen = [], Counter()
    for i, r in enumerate(rows):
        pos = re.match(r"^(verb|noun|adjective)\b", r["definition"].strip(), re.I)
        s = f"-{pos.group(1).lower()}" if pos else ("" if i == 0 else f"-{i + 1}")
        seen[s] += 1
        out.append(s if seen[s] == 1 else f"{s}-{seen[s]}")
    return out


def run(records: list[dict[str, Any]], rows: list[dict[str, Any]]) -> tuple[list, Counter]:
    stats: Counter = Counter()
    by_en: dict[str, dict[str, Any]] = {}
    for r in records:
        for t in r["terms"]:
            if t["lang"] == "en":
                by_en.setdefault(norm_key(t["text"]), r)
    by_id = {r["id"]: r for r in records}
    elrc_ids = {  # concepts this script made earlier, by ELRC entry number
        int(m.group(1)): r["id"]
        for r in records
        if r.get("note") == NOTE
        for t in r["terms"]
        for s in t.get("sources", [])
        if (m := re.search(r"^ELRC dictionary.*entry (\d+)$", s["citation"]))
    }

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[norm_key(row["en"])].append(row)

    for key, group in groups.items():
        terms = [(row, am_term(row)) for row in group]
        for _row, term in terms:
            if term is None:
                stats["skipped: not Amharic script"] += 1
        existing = by_en.get(key)
        if existing is not None and key not in SENSE_SPLIT and existing.get("note") != NOTE:
            for _, term in terms:
                if term:
                    add_term(existing, term, stats)
            continue
        for (row, term), suffix in zip(terms, suffixes(group), strict=True):
            if term is None:
                continue
            target_id = elrc_ids.get(row["no"])
            if target_id is None:
                base = slugify(row["en"]) + suffix
                target_id = base
                n = 2
                while target_id in by_id and by_id[target_id].get("note") != NOTE:
                    target_id, n = f"{base}-{n}", n + 1
            concept = by_id.get(target_id)
            if concept is None:
                en: dict[str, Any] = {"lang": "en", "text": clean(row["en"]), "status": "preferred"}
                concept = {
                    "id": target_id,
                    "domain": classify(row["en"], row["definition"]),
                    "terms": [en],
                    "note": NOTE,
                }
                definition = clean(row["definition"])
                if not SKIP_DEFINITION.match(definition):
                    concept["definition_en"] = definition
                records.append(concept)
                by_id[target_id] = concept
                stats["concept created"] += 1
            add_term(concept, term, stats)
            elrc_ids[row["no"]] = target_id

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
    records = [dict(r) for r in read_dir(args.data)]
    records, stats = run(records, rows)
    for k, v in sorted(stats.items()):
        print(f"{v:5d}  {k}")
    domains = Counter(r["domain"] for r in records)
    print("concepts per domain:", dict(sorted(domains.items())))
    if not args.dry_run:
        write_domain_files(records, args.data)  # type: ignore[arg-type]
        print(f"{len(records)} concepts written to {args.data}")


if __name__ == "__main__":
    main()
