from pathlib import Path

from tech_amharic import suggestions as sug
from tech_amharic.records import read_dir, validate

DATA = Path(__file__).resolve().parents[1] / "data" / "concepts"

# A made-up term, so the tests keep working as real suggestions are imported.
KUBE = {
    "term": "Exampletron",
    "domain": "cloud-devops",
    "definition_en": "A system that runs and manages containers across many machines.",
    "definition_am": "ኮንቴይነሮችን በብዙ ማሽኖች ላይ የሚያስተዳድር ሥርዓት ነው።",
    "terms": [{"text": "ኩበርኔትስ", "formation": "loan"}],
    "model": "@cf/google/gemma-4-26b-a4b-it",
    "created_at": "2026-10-28T01:00:00Z",
}


def test_new_suggestion_becomes_a_proposed_concept_with_ai_source() -> None:
    result = sug.merge(read_dir(DATA), [KUBE])
    assert result.added == ["exampletron"]
    record = next(r for r in result.records if r["id"] == "exampletron")
    assert validate(dict(record)) == []
    en = [t for t in record["terms"] if t["lang"] == "en"]
    am = [t for t in record["terms"] if t["lang"] == "am"]
    assert en == [{"lang": "en", "text": "Exampletron", "status": "preferred"}]
    assert [t["status"] for t in am] == ["proposed"]
    assert am[0]["sources"][0]["citation"].startswith(
        "AI suggestion (@cf/google/gemma-4-26b-a4b-it), 2026-10-28"
    )
    assert record["note"] == sug.AI_NOTE


def test_merge_is_idempotent_and_skips_known_terms() -> None:
    once = sug.merge(read_dir(DATA), [KUBE])
    twice = sug.merge(once.records, [KUBE])
    assert twice.added == []
    assert twice.skipped == ["Exampletron: already in the glossary"]
    existing = sug.merge(read_dir(DATA), [{**KUBE, "term": "Encryption"}])
    assert existing.added == []


def test_bad_or_non_technical_suggestions_are_skipped() -> None:
    bad_script = {**KUBE, "term": "Helm", "terms": [{"text": "helm"}]}
    junk = {"term": "banana bread", "notTechTerm": True}
    result = sug.merge(read_dir(DATA), [bad_script, junk])
    assert result.added == []
    assert any(s.startswith("Helm:") for s in result.skipped)


def test_slugs_stay_unique_and_acronyms_are_marked() -> None:
    records = read_dir(DATA)
    a = sug.merge(records, [{**KUBE, "term": "LLM ops"}])
    assert a.added == ["llm-ops"]
    b = sug.merge(a.records, [{**KUBE, "term": "llm-ops!", "terms": [{"text": "ሀለመ"}]}])
    assert b.added == []  # same folded term as "LLM ops"
    c = sug.merge(records, [{**KUBE, "term": "RAG"}])
    rag = next(r for r in c.records if r["id"] == "rag")
    assert rag["terms"][0]["formation"] == "abbreviation"


def test_every_ai_draft_names_its_source() -> None:
    seed = "Seed draft by AI (Claude, Anthropic), 2026-10-20; awaiting native-speaker review"
    for r in read_dir(DATA):
        for t in r["terms"]:
            for src in t.get("sources", []):
                if src["kind"] == "draft":
                    assert src["citation"] == seed or src["citation"].startswith(
                        "AI suggestion ("
                    ), src
