import importlib.util
import json
from pathlib import Path

from tech_amharic.records import read_dir

ROOT = Path(__file__).resolve().parents[1]


def load():  # scripts/ is not a package
    path = ROOT / "scripts" / "import_elrc.py"
    spec = importlib.util.spec_from_file_location("import_elrc", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


elrc = load()
ROWS = [json.loads(line) for line in elrc.SOURCE.read_text(encoding="utf-8").splitlines()]


def test_source_has_every_entry_with_amharic() -> None:
    assert [r["no"] for r in ROWS] == list(range(1, 2829))
    assert all(r["en"] and r["am"] for r in ROWS)
    assert not any("vD" in r["am"] for r in ROWS)  # font glyph fixed to ቧ


def test_committed_data_is_already_imported() -> None:
    # Re-running the import on the committed data changes nothing.
    records = [dict(r) for r in read_dir(ROOT / "data" / "concepts")]
    before = json.dumps(records, sort_keys=True, ensure_ascii=False)
    after, stats = elrc.run(records, ROWS)
    assert not stats
    assert json.dumps(after, sort_keys=True, ensure_ascii=False) == before


def test_every_elrc_term_is_proposed_and_cites_its_entry() -> None:
    cited = set()
    for r in read_dir(ROOT / "data" / "concepts"):
        for t in r["terms"]:
            for s in t.get("sources", []):
                if s["citation"].startswith("ELRC dictionary"):
                    assert s["kind"] == "glossary"
                    cited.add(int(s["citation"].rsplit(" ", 1)[1]))
    assert len(cited) >= 2800


def test_term_splitting_and_sense_split() -> None:
    assert elrc.split_term("ኸርዝ(ኤችዜድ)") == ("ኸርዝ", "(ኤችዜድ)")
    isp = "በመአ (የበይነመረብ አገልግሎት አቅራቢ) - Internet Service Provider ይመልከቱ"
    assert elrc.split_term(isp)[0] == "በመአ"
    assert elrc.split_term("ሀገር/ክልል") == ("ሀገር/ክልል", "")
    records = {r["id"]: r for r in read_dir(ROOT / "data" / "concepts")}
    # ELRC "token" (an alias name) is not our NLP token.
    assert "ተለዋጭ ሥም" not in [t["text"] for t in records["token-nlp"]["terms"]]
    assert "ኬላ" in [t["text"] for t in records["firewall"]["terms"]]
