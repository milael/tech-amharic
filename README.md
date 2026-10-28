# Tech-Amharic

An open, reviewed, concept-oriented termbase for computing and technology terms in Amharic, with an API, a contributor web app, a CLI, a Hugging Face dataset and an evaluation harness for language models.

> **Status: v0.1, pre-review.** `data/concepts/` holds about 2,900 concepts: 121 AI-drafted seed concepts, the 2,828-entry ELRC ICT dictionary, and AI and visitor suggestions. Every Amharic term is *proposed* and names its source. Nothing is published until a reviewer approves it.

**Live demo:** https://milael.github.io/tech-amharic/ (search and browse the termbase in the browser; rebuilt from `data/concepts/` on every push).

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

### Build the static demo

```bash
uv run python scripts/build_site.py --out _site
python -m http.server -d _site 8000                 # http://127.0.0.1:8000
```

The `pages.yml` workflow publishes the same build to GitHub Pages.

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

## Data sources

| Source | Terms | How it got here | Label on the demo |
| --- | --- | --- | --- |
| ELRC ICT dictionary: *Translation of ICT Terms into three major Ethiopian Languages* (ICT Development Office & Ethiopian Languages Research Center, 2011) | 2,828 entries, Office/OS-era vocabulary | `scripts/elrc_extract.py` (PDF → `data/sources/elrc-ict-glossary-2011.jsonl`, all three languages kept) then `scripts/import_elrc.py` | **ELRC**, with the entry number |
| Microsoft Digital Literacy Curriculum, Amharic edition (© 2007 Microsoft): Computer Basics, Computer Security and Privacy, Digital Lifestyles, The Internet and the World Wide Web, Productivity Programs | 201 terms: 153 from the five book glossaries, 48 "Amharic (English)" pairs from the course text | Curated in `data/sources/microsoft-dlc-amharic-2007.jsonl` (glossary English paired by AI from the English edition's order; the Productivity Programs glossary read from page images because its text layer is garbled), then `scripts/import_dlc.py`. Terms only; definitions are not copied | **Microsoft** |
| Seed drafts by AI (Claude) | 121 modern concepts (AI, security, cloud) | Written by hand-prompted AI | **AI draft** |
| AI suggestions (Gemma 4) | Grows from demo searches | Weekly import PR | **AI draft** |
| Demo visitors | Grows from "Suggest a better term" | Weekly import PR | **Visitor** |

The ELRC import adds an entry's Amharic term to an existing concept when the English matches, and creates a new concept otherwise (domain assigned by keywords, so expect some misfiled concepts). A few English words mean something else in ELRC (token, prompt, model, filter, function, framework, display, library) and are kept as separate concepts. Re-running the import changes nothing.

## Ask questions in Amharic (termbase-grounded chat)

The chat finds the concepts a question mentions, puts their reviewed Amharic terms and definitions into the prompt, and asks a model to answer in Amharic using them (retrieval-augmented generation). Every answer lists the termbase entries it relied on.

```bash
ollama pull gemma4:e4b                      # free, local
uv run tam ask "ምስጠራ እንዴት ይሰራል?"
uv run tam ask "How does a firewall work?" --show-prompt   # inspect the prompt only
```

- **API:** `POST /api/v1/chat` in the FastAPI app (`TAM_LLM_BASE_URL`, `TAM_LLM_MODEL`, `TAM_LLM_API_KEY`; any OpenAI-compatible endpoint).
- **Public demo:** a Cloudflare Worker running Gemma 4 26B on the Workers AI free tier. Setup: [worker/README.md](worker/README.md).
- **Shared logic:** the prompt lives in `src/tech_amharic/chat_prompt.txt`; `tests/fixtures/retrieval_cases.json` keeps the Python and JavaScript retrieval identical.

## AI term suggestions

When a glossary search finds nothing, the demo offers **Suggest an Amharic term with AI**. Gemma 4 proposes 1–3 Amharic options with a domain and definitions, using the glossary's *approved* terms as examples, so suggestions follow reviewers' decisions more closely as approvals grow. Suggestions are stored in Cloudflare KV and are clearly labelled as unreviewed AI drafts.

```bash
uv run tam admin pull-suggestions --dry-run   # see what would be added
uv run tam admin pull-suggestions             # add them to data/concepts as proposed terms
```

Every concept card also has **Suggest a better term**, where anyone can send an Amharic alternative with an optional note and name. Proposals are checked (Ge'ez script, not already listed, rate-limited), stored next to the AI suggestions, and imported as `proposed` terms whose source reads "Proposed on the demo by … (unverified)". Repeats of the same term are counted, which shows reviewers which alternatives have support.

The `suggestions.yml` workflow imports both weekly and opens a pull request. Every imported term is `proposed`, with a source naming the model and date; nothing reaches the published dataset until a reviewer approves it.

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
