# Tech-Amharic

An open, reviewed, concept-oriented termbase for computing and technology terms in Amharic, with an API, a contributor web app, a CLI, a Hugging Face dataset and an evaluation harness for language models.

> **Status: v0.1, pre-review.** The 121 seed concepts in `data/concepts/` carry *proposed* Amharic terms only. They are a starting draft for human reviewers, not a recommendation. Nothing is published until a reviewer approves it.

## Why

Older Amharic ICT glossaries cover the Office era (save, file, menu). Engineers and students today meet vector embeddings, zero trust, containers and prompt injection with no reviewed Amharic. Open language models also read Amharic far better than they write it. A small, carefully reviewed termbase helps both people and models.

## What is in the box

| Part | What it does |
| --- | --- |
| `data/concepts/*.jsonl` | The termbase as plain JSONL, one file per domain. The reviewed source of record; every change is a readable git diff. |
| `src/tech_amharic/normalize.py` | Ge'ez-aware search keys: folds interchangeable letters (ሀ/ሐ/ኀ, ሰ/ሠ, አ/ዐ, ጸ/ፀ) without altering stored spelling. |
| `src/tech_amharic/domain.py` | Review rules: statuses, allowed decisions, no self-approval, one preferred term per language. |
| `src/tech_amharic/server/` | FastAPI + SQLAlchemy API, HTMX web app, token auth, audit log. |
| `src/tech_amharic/records.py` | Exports to JSONL, CSV, TBX-Basic (ISO 30042) and the release bundle. |
| `src/tech_amharic/dataset.py` | Builds the `terms`, `instructions` and held-out `eval` dataset configs. |
| `src/tech_amharic/evaluate.py` | Scores models on term accuracy, Ge'ez script fidelity and chrF. |
| `tam` CLI | Offline lookup, search, export, proposals, admin and evaluation. |

## Quick start

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-extras          # Python deps (creates uv.lock on first run)
uv run pytest                 # full test suite, including API tests

# Look terms up straight from the data files, unreviewed ones included
uv run tam lookup encryption --data data/concepts -u
uv run tam search ምስጠራ --data data/concepts -u
uv run tam validate data/concepts
```

### Run the web app locally (SQLite)

```bash
cp .env.example .env
uv run tam admin init-db
uv run tam admin import data/concepts
uv run tam admin create-user mili --role admin     # prints a token once
uv run tam admin create-user reviewer1 --role reviewer
uv run tam admin serve --reload                    # http://127.0.0.1:8000
```

Sign in at `/login` with a token. API docs are at `/docs`.

### Run with PostgreSQL (Docker)

```bash
docker compose up --build
docker compose exec app tam admin import data/concepts
docker compose exec app tam admin create-user mili --role admin
```

The container applies Alembic migrations on start. PostgreSQL adds a trigram index for fast fuzzy search.

## Workflow

1. A contributor proposes an Amharic term (web, CLI `tam propose`, or `POST /api/v1/concepts/{slug}/terms`).
2. Contributors vote; votes order the review queue but never change status.
3. A reviewer (never the proposer) approves as **preferred** or **admitted**, requests changes, or rejects with a reason.
4. `tam admin build` exports the database back to `data/concepts/`, a release bundle, TBX/CSV and the dataset. Commit the data diff; tag `v*` to publish a GitHub release.

See [CONTRIBUTING.md](CONTRIBUTING.md) and the reviewer [style guide](docs/STYLE_GUIDE.md).

## Evaluating a model

```bash
uv run tam admin build --out dist/release
ollama pull gemma4:e4b
uv run tam eval --model gemma4:e4b --setting zero_shot
uv run tam eval --model gemma4:e4b --setting glossary --glossary dist/release/dataset/terms.jsonl
```

Each run writes `eval-report.json` with per-item answers. Any OpenAI-compatible endpoint works via `--base-url`.

## Licences

Code: Apache-2.0. Data in `data/` and released datasets: CC BY-SA 4.0. Contributions are signed off under the [DCO](https://developercertificate.org/).

## Related work

- [ELRC ICT Terms Dictionary](https://pypi.org/project/tech-mezgeb-qalat/) (about 2,800 ICT terms) and the `tech-mezgeb-qalat` packages built on it
- [EthioNLP](https://huggingface.co/EthioNLP) datasets and models
- [IrokoBench](https://arxiv.org/abs/2406.03368), [AfroBench](https://mcgill-nlp.github.io/AfroBench/) and [amharic-llm-bench](https://github.com/Beki-hck/amharic-llm-bench)
