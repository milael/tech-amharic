from tech_amharic.evaluate import build_messages, chrf, score_item, summarize, term_hit

ITEM = {
    "id": "encryption",
    "en": "encryption",
    "am": "ምስጠራ",
    "am_admitted": ["ኢንክሪፕሽን"],
    "definition_en": "Transforming data so only key holders can read it.",
}


def test_chrf_bounds() -> None:
    assert chrf("ምስጠራ", "ምስጠራ") == 100.0
    assert chrf("abc", "xyz") == 0.0
    assert 0 < chrf("ምስጠራዎች", "ምስጠራ") < 100
    assert chrf("", "ምስጠራ") == 0.0


def test_term_hit_accepts_admitted_and_spelling_variants() -> None:
    assert term_hit("ምሥጠራ", ["ምስጠራ"])  # ሠ / ሰ variant
    assert term_hit("መልሱ፦ ኢንክሪፕሽን ነው።", ["ምስጠራ", "ኢንክሪፕሽን"])
    assert not term_hit("encryption", ["ምስጠራ"])


def test_score_flags_script_drift() -> None:
    good = score_item(ITEM, "ምስጠራ")
    drift = score_item(ITEM, "ምስጠራ (encryption)")
    assert good.hit and good.script == 1.0
    assert drift.hit and drift.script < 0.5
    summary = summarize([good, drift])
    assert summary["n"] == 2 and summary["term_accuracy"] == 100.0


def test_glossary_setting_adds_reference_terms() -> None:
    zero = build_messages(ITEM, "zero_shot")
    with_glossary = build_messages(ITEM, "glossary", [{"en": "decryption", "am": "ምስጠራ መፍታት"}])
    assert len(with_glossary) == len(zero) + 1
    assert "ምስጠራ መፍታት" in with_glossary[1]["content"]
