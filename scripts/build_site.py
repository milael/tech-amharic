"""Build the static GitHub Pages demo.

    uv run python scripts/build_site.py --out _site

Copies site/ and writes data/bundle.json, TBX and CSV from data/concepts.
The demo includes unreviewed (proposed) terms so visitors can see the work in
progress; the page labels them clearly. Pass --published-only to show only
reviewed terms once enough exist.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from tech_amharic import records as rec

ROOT = Path(__file__).resolve().parents[1]


def git_version() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "local"


def build(out: Path, data: Path, published_only: bool) -> int:
    records = rec.select(rec.read_dir(data), published_only=published_only)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    (out / ".nojekyll").touch()  # serve files as-is

    data_dir = out / "data"
    data_dir.mkdir()
    now = datetime.now(UTC).isoformat(timespec="seconds")
    bundle = rec.to_bundle(records, version=git_version(), generated_at=now)
    (data_dir / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    (data_dir / "tech-amharic.tbx").write_text(rec.to_tbx(records), encoding="utf-8")
    (data_dir / "tech-amharic.csv").write_text(rec.to_csv(records), encoding="utf-8")
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "_site")
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "concepts")
    parser.add_argument("--published-only", action="store_true")
    args = parser.parse_args()
    n = build(args.out, args.data, args.published_only)
    print(f"Built demo with {n} concepts in {args.out}")


if __name__ == "__main__":
    main()
