"""`tam`: look up Amharic technology terms from the terminal.

Lookups read a local bundle and work offline. ``tam admin ...`` commands run
the server side and need the ``server`` extra.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer

from . import records as rec
from .bundle import Bundle, Hit
from .domain import DOMAINS, Formation, Lang, Role, TermStatus

app = typer.Typer(
    help="Tech-Amharic: Amharic technology terms in your terminal.", no_args_is_help=True
)
admin = typer.Typer(
    help="Server and data maintenance (needs the 'server' extra).", no_args_is_help=True
)
app.add_typer(admin, name="admin")

DEFAULT_BUNDLE_URL = os.environ.get(
    "TAM_BUNDLE_URL",
    "https://github.com/milael/tech-amharic/releases/latest/download/bundle.json",
)
DEFAULT_API = os.environ.get("TAM_API_URL", "http://127.0.0.1:8000")


def bundle_path() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "tech-amharic" / "bundle.json"


DataDir = Annotated[
    Path | None,
    typer.Option(
        "--data", help="Read records from a data/concepts directory instead of the bundle."
    ),
]
Unreviewed = Annotated[
    bool, typer.Option("--include-unreviewed", "-u", help="With --data: include proposed terms.")
]


def load(data: Path | None, include_unreviewed: bool) -> Bundle:
    if data is not None:
        records = rec.select(rec.read_dir(data), published_only=not include_unreviewed)
        return Bundle(rec.to_bundle(records, version="local", generated_at=""))
    path = bundle_path()
    if not path.exists():
        typer.secho(
            "No local bundle yet. Run `tam update`, or pass --data data/concepts.", fg="yellow"
        )
        raise typer.Exit(1)
    return Bundle.load(path)


_STATUS_COLOR = {
    TermStatus.PREFERRED: "green",
    TermStatus.ADMITTED: "cyan",
    TermStatus.DEPRECATED: "red",
    TermStatus.PROPOSED: "yellow",
}


def show(hit: Hit, *, full: bool) -> None:
    c = hit.concept
    typer.secho(f"{rec.headword(c)}  ", bold=True, nl=False)
    typer.secho(f"[{DOMAINS.get(c['domain'], c['domain'])}]", dim=True)
    for t in c["terms"]:
        if t["lang"] != Lang.AM:
            continue
        status = TermStatus(t["status"])
        typer.echo("  ", nl=False)
        typer.secho(t["text"], bold=status is TermStatus.PREFERRED, nl=False)
        typer.secho(f"  {status.value}", fg=_STATUS_COLOR.get(status, "white"), nl=False)
        typer.secho(f"  {t['formation']}" if t.get("formation") else "", dim=True)
    if full:
        for key in ("definition_en", "definition_am", "note"):
            if c.get(key):
                typer.secho(f"  {c[key]}", dim=key == "note")  # type: ignore[literal-required]
    typer.echo("")


@app.command()
def lookup(
    term: str,
    data: DataDir = None,
    include_unreviewed: Unreviewed = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print raw records.")] = False,
) -> None:
    """Exact lookup in English or Amharic (spelling variants are tolerated)."""
    hits = load(data, include_unreviewed).lookup(term)
    if as_json:
        typer.echo(json.dumps([h.concept for h in hits], ensure_ascii=False, indent=2))
        return
    if not hits:
        typer.secho(f"No exact match for '{term}'. Try `tam search {term}`.", fg="yellow")
        raise typer.Exit(1)
    for h in hits:
        show(h, full=True)


@app.command()
def search(
    query: str,
    data: DataDir = None,
    include_unreviewed: Unreviewed = False,
    limit: Annotated[int, typer.Option(min=1, max=200)] = 20,
) -> None:
    """Substring search across both languages."""
    hits = load(data, include_unreviewed).search(query, limit=limit)
    if not hits:
        typer.secho(f"Nothing found for '{query}'.", fg="yellow")
        raise typer.Exit(1)
    for h in hits:
        show(h, full=False)


@app.command()
def export(
    fmt: Annotated[str, typer.Option("--format", "-f", help="tbx, csv or jsonl")] = "tbx",
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
    data: DataDir = None,
    include_unreviewed: Unreviewed = False,
) -> None:
    """Write the local bundle (or a data directory) in an exchange format."""
    concepts = load(data, include_unreviewed).concepts
    writers = {"tbx": rec.to_tbx, "csv": rec.to_csv, "jsonl": rec.to_jsonl}
    if fmt not in writers:
        raise typer.BadParameter("Use tbx, csv or jsonl.")
    text = writers[fmt](concepts)
    if out:
        out.write_text(text, encoding="utf-8")
        typer.secho(f"Wrote {len(concepts)} concepts to {out}", fg="green")
    else:
        typer.echo(text, nl=False)


@app.command()
def update(url: Annotated[str, typer.Option(help="Bundle URL")] = DEFAULT_BUNDLE_URL) -> None:
    """Download the latest released bundle for offline lookups."""
    resp = httpx.get(url, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    bundle = Bundle(resp.json())  # validates the schema before we save it
    path = bundle_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(resp.text, encoding="utf-8")
    typer.secho(
        f"Saved bundle {bundle.version} ({len(bundle.concepts)} concepts) to {path}", fg="green"
    )


@app.command()
def propose(
    concept: Annotated[str, typer.Argument(help="Concept slug, e.g. vector-embedding")],
    text: Annotated[str, typer.Argument(help="Proposed Amharic term")],
    formation: Annotated[Formation | None, typer.Option()] = None,
    citation: Annotated[str | None, typer.Option(help="Where the term is used")] = None,
    note: Annotated[str | None, typer.Option()] = None,
    api: Annotated[str, typer.Option(envvar="TAM_API_URL")] = DEFAULT_API,
    token: Annotated[str, typer.Option(envvar="TAM_TOKEN", help="Contributor token")] = "",
) -> None:
    """Propose an Amharic term for a concept (needs a contributor token)."""
    if not token:
        raise typer.BadParameter("Set TAM_TOKEN or pass --token.")
    body: dict[str, object] = {"lang": "am", "text": text}
    if formation:
        body["formation"] = formation.value
    if note:
        body["note"] = note
    if citation:
        body["sources"] = [
            {"kind": "web" if citation.startswith("http") else "coined", "citation": citation}
        ]
    resp = httpx.post(
        f"{api.rstrip('/')}/api/v1/concepts/{concept}/terms",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if resp.is_success:
        typer.secho(f"Proposed '{text}' for {concept}; it is now in the review queue.", fg="green")
    else:
        detail = (
            resp.json().get("detail", resp.text)
            if resp.headers.get("content-type", "").startswith("application/json")
            else resp.text
        )
        typer.secho(f"Rejected ({resp.status_code}): {detail}", fg="red")
        raise typer.Exit(1)


@app.command()
def validate(
    data: Annotated[Path, typer.Argument()] = Path("data/concepts"),
    fix: Annotated[bool, typer.Option("--fix", help="Rewrite files in canonical form.")] = False,
) -> None:
    """Check every record in a data directory (used in CI)."""
    records = rec.read_dir(data)
    problems = [p for r in records for p in rec.validate(dict(r))]
    ids = [r["id"] for r in records]
    problems += [f"{i}: duplicate id" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for path in sorted(data.glob("*.jsonl")):
        items = list(rec.read_jsonl(path))
        wrong_domain = [r["id"] for r in items if r.get("domain") != path.stem]
        if wrong_domain:
            problems.append(f"{path.name}: records from another domain: {', '.join(wrong_domain)}")
        canonical = rec.to_jsonl(items)
        if path.read_text(encoding="utf-8") != canonical:
            if fix:
                path.write_text(canonical, encoding="utf-8")
                typer.secho(f"Rewrote {path.name} in canonical form", fg="cyan")
            else:
                problems.append(f"{path.name}: not in canonical form (run `tam validate --fix`)")
    for p in problems:
        typer.secho(p, fg="red")
    if problems:
        raise typer.Exit(1)
    typer.secho(f"{len(records)} records OK", fg="green")


@app.command()
def ask(
    question: str,
    data: DataDir = Path("data/concepts"),
    include_unreviewed: Unreviewed = True,
    model: Annotated[str, typer.Option(envvar="TAM_LLM_MODEL")] = "gemma4:e4b",
    base_url: Annotated[
        str, typer.Option(envvar="TAM_LLM_BASE_URL", help="OpenAI-compatible endpoint")
    ] = "http://localhost:11434/v1",
    api_key: Annotated[str, typer.Option(envvar="TAM_LLM_API_KEY")] = "ollama",
    show_prompt: Annotated[
        bool, typer.Option("--show-prompt", help="Print the prompt only.")
    ] = False,
) -> None:
    """Ask a technology question; the answer comes in Amharic, grounded in the termbase."""
    import asyncio

    from . import chat

    records = rec.select(
        rec.read_dir(data or Path("data/concepts")), published_only=not include_unreviewed
    )
    if show_prompt:
        found = chat.retrieve(records, question)
        for m in chat.build_messages(question, found):
            typer.secho(f"[{m['role']}]", bold=True)
            typer.echo(m["content"] + "\n")
        return
    result = asyncio.run(
        chat.ask(question, records, base_url=base_url, model=model, api_key=api_key)
    )
    typer.echo(result["answer"] + "\n")
    used = set(result["checks"]["terms_used"])
    for c in result["concepts"]:
        mark = "used" if c["id"] in used else "not used"
        typer.secho(f"  {c['en']} -> {c['am']} [{c['status']}, {mark}]", dim=True)
    typer.secho(f"  Ge'ez script share: {result['checks']['ethiopic_ratio']:.0%}", dim=True)


@app.command("eval")
def evaluate_model(
    model: Annotated[str, typer.Option(help="Model name, e.g. gemma4:e4b")],
    items: Annotated[Path, typer.Option(help="eval.jsonl from `tam admin build`")] = Path(
        "dist/release/dataset/eval.jsonl"
    ),
    base_url: Annotated[
        str, typer.Option(help="OpenAI-compatible endpoint")
    ] = "http://localhost:11434/v1",
    setting: Annotated[str, typer.Option(help="zero_shot or glossary")] = "zero_shot",
    glossary: Annotated[
        Path | None, typer.Option(help="terms.jsonl to inject (glossary setting)")
    ] = None,
    report: Annotated[Path, typer.Option()] = Path("eval-report.json"),
    api_key: Annotated[str, typer.Option(envvar="TAM_EVAL_API_KEY")] = "ollama",
) -> None:
    """Score a model on the held-out eval split (term accuracy, script fidelity, chrF)."""
    from . import evaluate

    def read(path: Path) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    gloss = read(glossary) if glossary else []
    summary, results = evaluate.run(
        read(items),
        base_url=base_url,
        model=model,
        setting=setting,
        glossary=gloss,
        api_key=api_key,
    )
    evaluate.write_report(str(report), summary, results, {"model": model, "setting": setting})
    typer.secho(json.dumps(summary), fg="green")


# ---------------------------------------------------------------- admin


def _database():  # type: ignore[no-untyped-def]
    try:
        from .server.config import get_settings
        from .server.db import Database
    except ImportError as exc:  # pragma: no cover
        typer.secho("Server extras missing. Run: uv sync --extra server", fg="red")
        raise typer.Exit(1) from exc
    return Database(get_settings().database_url)


@admin.command("pull-suggestions")
def pull_suggestions(
    url: Annotated[str, typer.Option(help="Worker /suggestions URL")] = (
        "https://tech-amharic-chat.milael.workers.dev/suggestions"
    ),
    data: Annotated[Path, typer.Option(help="Glossary data directory")] = Path("data/concepts"),
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would change.")] = False,
) -> None:
    """Add stored AI suggestions to the glossary data as proposed terms."""
    from . import suggestions as sug

    resp = httpx.get(url, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    result = sug.merge(rec.read_dir(data), resp.json().get("suggestions", []))
    for item in result.skipped:
        typer.secho(f"  skipped {item}", dim=True)
    if not result.added:
        typer.secho("No new suggestions.", fg="green")
        return
    for cid in result.added:
        typer.secho(f"  + {cid}", fg="cyan")
    if dry_run:
        typer.secho(f"Dry run: {len(result.added)} concepts would be added.", fg="yellow")
        return
    rec.write_domain_files(result.records, data)
    typer.secho(
        f"Added {len(result.added)} concepts as proposed AI suggestions to {data}/", fg="green"
    )


@admin.command("init-db")
def init_db() -> None:
    """Create tables directly (development). Production: `alembic upgrade head`."""
    from .server.db import create_tables

    db = _database()
    create_tables(db.engine)
    typer.secho("Tables created.", fg="green")


@admin.command("import")
def import_data(data: Annotated[Path, typer.Argument()] = Path("data/concepts")) -> None:
    """Load data/concepts/*.jsonl into the database (idempotent upsert)."""
    from .server.services import import_records

    records = rec.read_dir(data)
    db = _database()
    with db.sessions() as session:
        result = import_records(session, records)
    typer.secho(f"Imported: {result}", fg="green")


@admin.command("create-user")
def create_user(handle: str, role: Annotated[Role, typer.Option()] = Role.CONTRIBUTOR) -> None:
    """Create a user and print their token once."""
    from .server.security import create_user as make_user

    db = _database()
    with db.sessions() as session:
        user, token = make_user(session, handle, role)
        session.commit()
    typer.secho(f"Created {user.handle} ({role.value}). Token, shown only now:", fg="green")
    typer.echo(token)


@admin.command("build")
def build(
    out: Annotated[Path, typer.Option(help="Release output directory")] = Path("dist/release"),
    data: Annotated[Path, typer.Option(help="Where to write canonical JSONL")] = Path(
        "data/concepts"
    ),
    version: Annotated[str, typer.Option()] = "0.1.0-dev",
) -> None:
    """Export the database to git data, a release bundle, TBX/CSV and the dataset."""
    from . import dataset
    from .server.services import export_records

    db = _database()
    with db.sessions() as session:
        everything = export_records(session, published_only=False)
    published = rec.select(everything, published_only=True)

    rec.write_domain_files(everything, data)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    (out / "bundle.json").write_text(
        json.dumps(rec.to_bundle(published, version=version, generated_at=now), ensure_ascii=False),
        encoding="utf-8",
    )
    (out / "tech-amharic.tbx").write_text(rec.to_tbx(published), encoding="utf-8")
    (out / "tech-amharic.csv").write_text(rec.to_csv(published), encoding="utf-8")
    written = dataset.write(dataset.build(published), out / "dataset")
    typer.secho(
        f"{len(everything)} concepts to {data}/; {len(published)} published to {out}/ "
        f"(+ {', '.join(p.name for p in written)})",
        fg="green",
    )


@admin.command("serve")
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: Annotated[bool, typer.Option("--reload")] = False,
) -> None:
    """Run the API and web UI with uvicorn."""
    import uvicorn

    uvicorn.run(
        "tech_amharic.server.main:create_app", factory=True, host=host, port=port, reload=reload
    )


if __name__ == "__main__":
    app()
