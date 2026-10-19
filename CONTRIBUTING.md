# Contributing

Thank you for helping build reviewed Amharic for technology.

## Ways to contribute

- **Propose a term** for an existing concept in the web app, or with `tam propose <concept> <term>`.
- **Vote** on proposals you have seen in real use.
- **Add a concept** that is missing (`POST /api/v1/concepts`, or a pull request to `data/concepts/`).
- **Review** (reviewers only): record decisions on concept pages.
- **Code**: issues labelled `good first issue`.

## Adding concepts by pull request

Each line in `data/concepts/<domain>.jsonl` is one concept:

```json
{"definition_en": "A database that stores and searches vector embeddings.", "domain": "data", "id": "vector-database", "terms": [{"lang": "en", "status": "preferred", "text": "vector database"}, {"formation": "calque", "lang": "am", "sources": [{"citation": "Proposed by <your handle>", "kind": "coined"}], "status": "proposed", "text": "የቬክተር የውሂብ ጎታ"}]}
```

Don't worry about key order or line order: `uv run tam validate --fix` rewrites the files in canonical form (sorted keys, sorted by `id`), which CI requires.

Rules, all checked by `uv run tam validate`:

- `id` is a lowercase slug and unique across all files.
- One meaning per concept. "kernel" in operating systems and "kernel" in CNNs are two concepts.
- New Amharic terms are always `"status": "proposed"`. Only reviewers change status.
- Say where a term comes from in `sources`: a textbook, course, standard, website, or `coined`.
- English variants (abbreviations, synonyms) may be added as `admitted` directly; they describe existing usage rather than recommend new Amharic.

## Development

```bash
uv sync --all-extras
uv run ruff check . && uv run ruff format .
uv run pytest
```

Business rules live in `src/tech_amharic/domain.py` and have no framework imports; test them there first.

## Sign-off

Add `Signed-off-by: Your Name <email>` to commits (`git commit -s`) to certify the [Developer Certificate of Origin](https://developercertificate.org/): you wrote the contribution or have the right to submit it under the project's licences.
