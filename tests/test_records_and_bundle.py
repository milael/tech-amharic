import csv
import io
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tech_amharic import dataset
from tech_amharic.bundle import Bundle
from tech_amharic.records import (
    TBX_NS,
    ConceptRecord,
    read_dir,
    select,
    to_bundle,
    to_csv,
    to_jsonl,
    to_tbx,
    validate,
    write_domain_files,
)

DATA = Path(__file__).resolve().parents[1] / "data" / "concepts"


def make(cid: str = "encryption", **over: object) -> ConceptRecord:
    r: dict[str, object] = {
        "id": cid,
        "domain": "security",
        "definition_en": "Transforming data so only key holders can read it.",
        "terms": [
            {"lang": "en", "text": "encryption", "status": "preferred"},
            {"lang": "am", "text": "ምስጠራ", "status": "preferred", "formation": "native"},
            {"lang": "am", "text": "ኢንክሪፕሽን", "status": "admitted", "formation": "loan"},
            {"lang": "am", "text": "መመስጠር", "status": "proposed"},
        ],
    }
    r.update(over)
    return r  # type: ignore[return-value]


# ------------------------------------------------------------- seed data


def test_every_seed_record_is_valid() -> None:
    records = read_dir(DATA)
    assert len(records) >= 100
    problems = [p for r in records for p in validate(dict(r))]
    assert problems == []


def test_seed_ids_are_unique_and_amharic_is_unreviewed() -> None:
    records = read_dir(DATA)
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))
    # Seed Amharic is a draft: nothing ships as published until reviewed.
    am_statuses = {t["status"] for r in records for t in r["terms"] if t["lang"] == "am"}
    assert am_statuses == {"proposed"}
    assert select(records, published_only=True) == []


def test_data_files_are_in_canonical_form() -> None:
    # The release job re-exports the database to data/ and fails on any diff,
    # so the files must already be exactly what the writer produces.
    for path in DATA.glob("*.jsonl"):
        assert to_jsonl(read_dir_file(path)) == path.read_text(encoding="utf-8"), path.name


def read_dir_file(path: Path) -> list[ConceptRecord]:
    from tech_amharic.records import read_jsonl

    return list(read_jsonl(path))


def test_three_kernel_concepts_stay_separate() -> None:
    ids = {r["id"] for r in read_dir(DATA)}
    assert {"kernel-os", "kernel-convolution", "kernel-method"} <= ids


# ------------------------------------------------------------- validation


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"id": "Not A Slug"}, "slug"),
        ({"domain": "blockchain"}, "domain"),
        ({"terms": []}, "at least one term"),
        ({"terms": [{"lang": "am", "text": "encryption", "status": "proposed"}]}, "script"),
        (
            {
                "terms": [
                    {"lang": "am", "text": "ምስጠራ", "status": "preferred"},
                    {"lang": "am", "text": "ኢንክሪፕሽን", "status": "preferred"},
                ]
            },
            "preferred",
        ),
    ],
)
def test_validation_catches_problems(override: dict[str, object], fragment: str) -> None:
    problems = validate(dict(make(**override)))
    assert any(fragment in p for p in problems), problems


def test_abbreviation_may_use_latin_script_in_amharic() -> None:
    r = make(
        terms=[{"lang": "am", "text": "API", "status": "proposed", "formation": "abbreviation"}]
    )
    assert validate(dict(r)) == []


# ------------------------------------------------------------- selection + writers


def test_published_view_drops_unreviewed_terms_and_empty_concepts() -> None:
    kept = select([make()], published_only=True)
    assert [t["text"] for t in kept[0]["terms"]] == ["encryption", "ምስጠራ", "ኢንክሪፕሽን"]
    only_proposed = make(
        "x",
        terms=[
            {"lang": "en", "text": "x", "status": "preferred"},
            {"lang": "am", "text": "ሀ", "status": "proposed"},
        ],
    )
    assert select([only_proposed], published_only=True) == []


def test_jsonl_is_sorted_and_round_trips(tmp_path: Path) -> None:
    text = to_jsonl([make("zeta"), make("alpha")])
    lines = text.strip().split("\n")
    assert [json.loads(line)["id"] for line in lines] == ["alpha", "zeta"]
    paths = write_domain_files([make()], tmp_path)
    assert paths == [tmp_path / "security.jsonl"]
    assert read_dir(tmp_path) == [make()]


def test_csv_has_one_row_per_concept() -> None:
    rows = list(csv.DictReader(io.StringIO(to_csv([make()]))))
    assert rows[0]["am_preferred"] == "ምስጠራ"
    assert rows[0]["am_admitted"] == "ኢንክሪፕሽን"
    assert rows[0]["am_proposed"] == "መመስጠር"


def test_tbx_is_well_formed_with_admin_status() -> None:
    root = ET.fromstring(to_tbx([make()]).encode())
    ns = {"t": TBX_NS}
    assert root.get("type") == "TBX-Basic"
    entry = root.find(".//t:conceptEntry", ns)
    assert entry is not None and entry.get("id") == "encryption"
    statuses = [n.text for n in root.iterfind(".//t:termNote[@type='administrativeStatus']", ns)]
    # en preferred, am preferred, am admitted; the proposed term has none.
    assert statuses == ["preferredTerm-admn-sts", "preferredTerm-admn-sts", "admittedTerm-admn-sts"]


# ------------------------------------------------------------- bundle lookup


@pytest.fixture
def bundle() -> Bundle:
    data = to_bundle([make()], version="0.1.0", generated_at="2026-10-20T00:00:00Z")
    return Bundle(json.loads(json.dumps(data)))


def test_lookup_works_in_both_languages(bundle: Bundle) -> None:
    assert bundle.lookup("Encryption")[0].concept["id"] == "encryption"
    assert bundle.lookup("ምስጠራ")[0].matched == "ምስጠራ"


def test_lookup_tolerates_homophone_letters(bundle: Bundle) -> None:
    # ሠ for ሰ is a common alternate spelling.
    assert bundle.lookup("ምሥጠራ")[0].concept["id"] == "encryption"


def test_search_finds_substrings_after_exact(bundle: Bundle) -> None:
    hits = bundle.search("crypt")
    assert hits and not hits[0].exact
    assert bundle.search("") == []


def test_bundle_rejects_unknown_schema() -> None:
    with pytest.raises(ValueError):
        Bundle({"schema": "other/9", "version": "x", "concepts": []})


# ------------------------------------------------------------- dataset


def test_dataset_split_is_stable_and_disjoint() -> None:
    records = [make(f"concept-{i}") for i in range(200)]
    tables = dataset.build(records)
    train_ids = {r["id"] for r in tables["terms"]}
    eval_ids = {r["id"] for r in tables["eval"]}
    assert train_ids.isdisjoint(eval_ids)
    assert train_ids | eval_ids == {r["id"] for r in records}
    assert 5 <= len(eval_ids) <= 40  # ~10% of 200
    # No instruction row comes from an eval concept.
    assert {r["concept_id"] for r in tables["instructions"]}.isdisjoint(eval_ids)
    assert dataset.build(records) == tables  # deterministic


def test_instruction_rows_use_preferred_and_mention_admitted() -> None:
    rows = dataset.instruction_rows(make())
    en_am = next(r for r in rows if r["task"] == "term_en_am")
    assert en_am["output"].startswith("ምስጠራ")
    assert "ኢንክሪፕሽን" in en_am["output"]
    assert all(r["origin"] == "template" for r in rows)


def test_dataset_writes_jsonl_without_pyarrow(tmp_path: Path) -> None:
    paths = dataset.write(dataset.build([make()]), tmp_path, fmt="jsonl")
    assert sorted(p.name for p in paths) == ["eval.jsonl", "instructions.jsonl", "terms.jsonl"]
