"""Extract the ELRC ICT glossary PDF into JSONL (one row per numbered entry).

Source: "Translation of ICT Terms into three major Ethiopian Languages:
Amharic, Oromo and Tigrigna", ICT Development Office and Ethiopian Languages
Research Center (ELRC), 2011. 240 pages, 2,828 entries.

    uv run --with pdfplumber python scripts/elrc_extract.py glossary.pdf \\
        data/sources/elrc-ict-glossary-2011.jsonl

The PDF is a printed Excel sheet. Words are assigned to columns by their x
position; Ge'ez words that overflow the Amharic column into the Oromo column
are kept with the Amharic. All three languages are kept for later use.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pdfplumber

ETH = re.compile(r"[ሀ-᎟ⶀ-⷟꬀-꬯]")
# Right edge (x, points) of each column on every page.
COLS = [("en", 197), ("definition", 452), ("am", 558), ("om", 648), ("ti", 10_000)]
# The PDF's font maps one Ge'ez letter to two Latin glyphs.
GLYPH_FIXES = {"vD": "ቧ"}


def column(word: dict) -> str:
    name = next(n for n, edge in COLS if word["x0"] < edge)
    if name == "om" and ETH.search(word["text"]):
        return "am"
    return name


def fix(text: str) -> str:
    for bad, good in GLYPH_FIXES.items():
        text = text.replace(bad, good)
    return text


def extract(pdf_path: Path) -> list[dict]:
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            words = [w for w in page.extract_words(x_tolerance=1.5) if 65 < w["top"] < 560]
            anchors = sorted(
                (w for w in words if w["x0"] < 105 and w["text"].isdigit()), key=lambda w: w["top"]
            )
            for i, anchor in enumerate(anchors):
                top = anchor["top"] - 3
                bottom = anchors[i + 1]["top"] - 3 if i + 1 < len(anchors) else 10_000
                cells: dict[str, list[str]] = {name: [] for name, _ in COLS}
                for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
                    if w is not anchor and top <= w["top"] < bottom:
                        cells[column(w)].append(w["text"])
                row = {k: fix(" ".join(v).strip()) for k, v in cells.items()}
                rows.append({"no": int(anchor["text"]), "page": page_no, **row})
    return rows


def main() -> None:
    rows = extract(Path(sys.argv[1]))
    numbers = [r["no"] for r in rows]
    assert numbers == list(range(1, len(rows) + 1)), "entries missing or out of order"
    with Path(sys.argv[2]).open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"{len(rows)} entries written to {sys.argv[2]}")


if __name__ == "__main__":
    main()
