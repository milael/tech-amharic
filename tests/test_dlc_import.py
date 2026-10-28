import json
import sys
from pathlib import Path

from tech_amharic.records import read_dir

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import import_dlc as dlc  # noqa: E402

ROWS = [json.loads(line) for line in dlc.SOURCE.read_text(encoding="utf-8").splitlines()]


def test_committed_data_is_already_imported() -> None:
    records = [dict(r) for r in read_dir(ROOT / "data" / "concepts")]
    before = json.dumps(records, sort_keys=True, ensure_ascii=False)
    after, stats = dlc.run(records, ROWS)
    assert not stats
    assert json.dumps(after, sort_keys=True, ensure_ascii=False) == before


def test_every_row_is_cited_and_no_definitions_copied() -> None:
    cites = {
        s["citation"]
        for r in read_dir(ROOT / "data" / "concepts")
        for t in r["terms"]
        for s in t.get("sources", [])
        if s["citation"].startswith("Microsoft Digital Literacy")
    }
    assert {dlc.citation(row) for row in ROWS} <= cites
    for r in read_dir(ROOT / "data" / "concepts"):
        if r.get("note") == dlc.NOTE:
            assert "definition_am" not in r and "definition_en" not in r


def test_glossary_rows_say_english_was_paired_by_ai() -> None:
    for row in ROWS:
        assert row["english_by"] == ("ai" if row["where"] == "glossary" else "source")
        assert ("English pairing by AI" in dlc.citation(row)) == (row["where"] == "glossary")
