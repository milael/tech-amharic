"""Build the Tech-Amharic dataset (three configs) from published records.

* ``terms``        one row per concept: lookup and glossary-constrained MT
* ``instructions`` prompt/response rows for supervised fine-tuning
* ``eval``         held-out concepts, never used for training

Splits are made per concept with a stable hash, so every row derived from
one concept lands in the same split and the eval set cannot leak into
training, and re-running the build gives the same split.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .domain import Lang, TermStatus
from .records import ConceptRecord, by_status, headword, preferred

DEFAULT_EVAL_PERCENT = 10


def split_of(concept_id: str, eval_percent: int = DEFAULT_EVAL_PERCENT) -> str:
    bucket = int(hashlib.sha256(concept_id.encode()).hexdigest(), 16) % 100
    return "eval" if bucket < eval_percent else "train"


def term_row(r: ConceptRecord) -> dict[str, Any]:
    return {
        "id": r["id"],
        "domain": r["domain"],
        "en": headword(r),
        "am": preferred(r, Lang.AM),
        "am_admitted": by_status(r, Lang.AM, TermStatus.ADMITTED),
        "am_deprecated": by_status(r, Lang.AM, TermStatus.DEPRECATED),
        "definition_en": r.get("definition_en"),
        "definition_am": r.get("definition_am"),
    }


def instruction_rows(r: ConceptRecord) -> list[dict[str, Any]]:
    """Templated instruction rows. Every row says where it came from."""
    en, am = headword(r), preferred(r, Lang.AM)
    if not am:
        return []
    admitted = by_status(r, Lang.AM, TermStatus.ADMITTED)
    rows: list[dict[str, Any]] = []

    answer = am if not admitted else f"{am} (ተቀባይነት ያላቸው አማራጮች፦ {'፣ '.join(admitted)})"
    rows.append(
        {
            "instruction": "የሚከተለውን የቴክኖሎጂ ቃል ወደ አማርኛ ተርጉም።",
            "input": en,
            "output": answer,
            "task": "term_en_am",
        }
    )
    rows.append(
        {
            "instruction": "የሚከተለውን የአማርኛ የቴክኖሎጂ ቃል የእንግሊዝኛ አቻ ጻፍ።",
            "input": am,
            "output": en,
            "task": "term_am_en",
        }
    )
    if r.get("definition_am"):
        rows.append(
            {
                "instruction": f"«{am}» ምን ማለት ነው? በአማርኛ አብራራ።",
                "input": "",
                "output": r["definition_am"],
                "task": "define_am",
            }
        )
    for row in rows:
        row.update({"concept_id": r["id"], "domain": r["domain"], "origin": "template"})
    return rows


def build(
    records: Iterable[ConceptRecord], eval_percent: int = DEFAULT_EVAL_PERCENT
) -> dict[str, list[dict[str, Any]]]:
    """Return the dataset tables. Expects published records only."""
    tables: dict[str, list[dict[str, Any]]] = {"terms": [], "instructions": [], "eval": []}
    for r in sorted(records, key=lambda r: r["id"]):
        if split_of(r["id"], eval_percent) == "eval":
            tables["eval"].append(term_row(r))
        else:
            tables["terms"].append(term_row(r))
            tables["instructions"].extend(instruction_rows(r))
    return tables


def write(tables: dict[str, list[dict[str, Any]]], out_dir: Path, fmt: str = "auto") -> list[Path]:
    """Write each table as JSONL, plus Parquet when pyarrow is available.

    JSONL is always written because the eval harness and quick inspection use
    it; Parquet is what the Hugging Face dataset uses. ``fmt`` may be
    "auto" (Parquet if possible), "parquet" (required) or "jsonl" (JSONL only).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    use_parquet = fmt == "parquet"
    if fmt == "auto":
        try:
            import pyarrow  # noqa: F401

            use_parquet = True
        except ImportError:
            use_parquet = False

    written: list[Path] = []
    for name, rows in tables.items():
        path = out_dir / f"{name}.jsonl"
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
        written.append(path)
        if use_parquet:
            import pyarrow as pa
            import pyarrow.parquet as pq

            pq_path = out_dir / f"{name}.parquet"
            pq.write_table(pa.Table.from_pylist(rows), pq_path)
            written.append(pq_path)
    return written
