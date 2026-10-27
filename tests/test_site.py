import importlib.util
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_builder():  # scripts/ is not a package
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_site_build_writes_page_and_data(tmp_path: Path) -> None:
    out = tmp_path / "_site"
    n = load_builder().build(out, ROOT / "data" / "concepts", published_only=False)
    assert n >= 100
    for name in ("index.html", "app.js", "style.css", ".nojekyll"):
        assert (out / name).exists(), name
    bundle = json.loads((out / "data" / "bundle.json").read_text(encoding="utf-8"))
    assert bundle["count"] == n == len(bundle["concepts"])
    ET.fromstring((out / "data" / "tech-amharic.tbx").read_bytes())


def test_js_normalization_tables_match_python() -> None:
    # app.js re-implements norm_key; its fold tables must not drift.
    from tech_amharic import normalize

    js = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    def table(name: str) -> dict[int, int]:
        body = re.search(rf"const {name} = \{{([^}}]*)\}}", js)
        assert body, name
        return {
            int(k, 16): int(v, 16)
            for k, v in re.findall(r"(0x[0-9a-f]+):\s*(0x[0-9a-f]+)", body[1])
        }

    assert table("ROW_FOLDS") == normalize._ROW_FOLDS
    assert table("ORDER_FOLDS") == normalize._ORDER_FOLDS
