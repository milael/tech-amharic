"""Termbase-grounded chat (retrieval-augmented generation).

For each question we find the relevant concepts in the termbase, put their
reviewed Amharic terms and definitions into the prompt, and ask a model to
answer in Amharic using those terms. After generation we check the answer
(script fidelity, which approved terms it used) and return the concepts so
the UI can show its sources.

The same retrieval rules are implemented in worker/src/chat-core.js for the
public demo; tests/fixtures/retrieval_cases.json keeps the two in step.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from .domain import Lang, TermStatus
from .normalize import ethiopic_ratio, is_ethiopic_char, norm_key
from .records import ConceptRecord, headword

SYSTEM_PROMPT = resources.files(__package__).joinpath("chat_prompt.txt").read_text(encoding="utf-8")

MAX_QUESTION_CHARS = 500
MAX_HISTORY_MESSAGES = 6
MAX_HISTORY_CHARS = 1500
DEFAULT_TOP_K = 5

_WORD = re.compile(r"[\wሀ-᎟ⶀ-⷟꬀-꬯]+", re.UNICODE)
_STATUS_RANK = {TermStatus.PREFERRED: 0, TermStatus.ADMITTED: 1, TermStatus.PROPOSED: 2}
# Everyday English words that are glossary entries (UI commands in the ELRC
# dictionary) but should not pull a concept into a chat prompt on their own.
# Keep in step with STOPWORDS in worker/src/chat-core.js.
_STOPWORDS = frozenset(
    {
        "about",
        "answer",
        "ask",
        "back",
        "cancel",
        "close",
        "day",
        "do",
        "done",
        "explain",
        "find",
        "go",
        "help",
        "how",
        "know",
        "like",
        "make",
        "mean",
        "more",
        "need",
        "new",
        "next",
        "no",
        "now",
        "ok",
        "open",
        "question",
        "say",
        "see",
        "show",
        "start",
        "stop",
        "tell",
        "time",
        "today",
        "try",
        "use",
        "want",
        "what",
        "when",
        "where",
        "which",
        "why",
        "year",
        "yes",
    }
)


# ---------------------------------------------------------------- retrieval


def _is_ethiopic_key(key: str) -> bool:
    return any(is_ethiopic_char(ch) for ch in key)


def _singular(key: str) -> str:
    """Very light English stemming: kernels -> kernel, systems -> system."""
    if not _is_ethiopic_key(key) and len(key) > 3 and key.endswith("s") and not key.endswith("ss"):
        return key[:-1]
    return key


def _ngrams(keys: Sequence[str], max_n: int = 4) -> set[str]:
    out: set[str] = set()
    for n in range(1, max_n + 1):
        for i in range(len(keys) - n + 1):
            out.add("".join(keys[i : i + n]))
    return out


def _is_acronym(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return 0 < len(letters) <= 5 and all(ch.isascii() and ch.isupper() for ch in letters)


@dataclass(frozen=True)
class Query:
    grams: frozenset[str]  # folded words and word sequences, plus singular forms
    folded: str  # whole question folded, for Amharic substring matches
    acronyms: frozenset[str]  # uppercase words exactly as typed, e.g. "IT", "GPU"

    @classmethod
    def parse(cls, question: str) -> Query:
        words = _WORD.findall(question)
        keys = [k for k in (norm_key(w) for w in words) if k]
        grams = _ngrams(keys) | _ngrams([_singular(k) for k in keys])
        # "GPUs" and "APIs" count as the acronyms GPU and API.
        bases = [w[:-1] if w.endswith("s") and len(w) > 2 else w for w in words]
        acronyms = frozenset(w for w in [*words, *bases] if _is_acronym(w))
        return cls(frozenset(grams), norm_key(question), acronyms)


def _span(text: str) -> tuple[str, ...]:
    return tuple(k for k in (norm_key(w) for w in _WORD.findall(text)) if k)


def _match(concept: ConceptRecord, query: Query) -> tuple[int, list[tuple[str, ...]]]:
    """Score plus the matched terms as word-key tuples (see score_concept)."""
    score, spans = 0, []
    for term in concept["terms"]:
        text = term["text"]
        key = norm_key(text)
        if not key:
            continue
        if _is_acronym(text):
            if text in query.acronyms:
                score, spans = score + 3, [*spans, (key,)]
        elif key in query.grams or _singular_term(text) in query.grams:
            if key not in _STOPWORDS:
                score, spans = score + 3, [*spans, _span(text)]
        elif _is_ethiopic_key(key) and len(key) >= 2 and key in query.folded:
            score, spans = score + 2, [*spans, _span(text)]
    return score, spans


def _singular_term(text: str) -> str:
    """Singular of a term's last word only: 'Save As' stays 'saveas'."""
    words = _span(text)
    return "".join([*words[:-1], _singular(words[-1])]) if words else ""


def _inside(short: tuple[str, ...], long: tuple[str, ...]) -> bool:
    n = len(short)
    if n < len(long) and any(long[i : i + n] == short for i in range(len(long) - n + 1)):
        return True
    # Ge'ez terms match inside words, so compare letters: ኮም lies inside ኮምፒውተር.
    a, b = "".join(short), "".join(long)
    return _is_ethiopic_key(a) and len(a) < len(b) and a in b


def score_concept(concept: ConceptRecord, query: Query) -> int:
    """How strongly a question mentions a concept.

    * 3 per term that equals a whole word or word sequence in the question
      (English plurals allowed). Acronyms such as IT or OS must appear in
      capitals, so the English word "it" does not match "IT".
    * 2 per Amharic term found inside the question. Amharic attaches
      prefixes and suffixes (የምስጠራ, ምስጠራን), so substring matching is
      right for Ge'ez; for Latin script it would match "it" inside "with".
    """
    return _match(concept, query)[0]


def retrieve(
    concepts: Iterable[ConceptRecord], question: str, k: int = DEFAULT_TOP_K
) -> list[ConceptRecord]:
    """Top-k concepts mentioned in the question, best first (ties by id).

    A concept is dropped when every term it matched lies inside a longer
    matched term of another concept: "load balancer" beats "load".
    """
    query = Query.parse(question)
    matched = [(*_match(c, query), c) for c in concepts]
    hits = [m for m in matched if m[0] > 0]
    all_spans = [s for _, spans, _ in hits for s in spans]
    hits = [m for m in hits if not all(any(_inside(s, o) for o in all_spans) for s in m[1])]
    hits.sort(key=lambda m: (-m[0], m[2]["id"]))
    return [c for _, _, c in hits[:k]]


# ---------------------------------------------------------------- prompting


def _am_terms_ranked(concept: ConceptRecord) -> list[dict[str, Any]]:
    terms = [t for t in concept["terms"] if t["lang"] == Lang.AM and t["status"] in _STATUS_RANK]
    return sorted(terms, key=lambda t: _STATUS_RANK[TermStatus(t["status"])])  # type: ignore[arg-type]


def termbase_block(concepts: Sequence[ConceptRecord]) -> str:
    if not concepts:
        return (
            "TERMBASE\n(no matching entries; answer from general knowledge "
            "and say that no reviewed term was found)"
        )
    lines = ["TERMBASE"]
    for c in concepts:
        terms = (
            ", ".join(f"{t['text']} [{t['status']}]" for t in _am_terms_ranked(c)) or "(none yet)"
        )
        lines.append(f"- {headword(c)}: {terms}")
        if c.get("definition_en"):
            lines.append(f"  definition: {c['definition_en']}")
        if c.get("definition_am"):
            lines.append(f"  ትርጉም: {c['definition_am']}")
    return "\n".join(lines)


def clean_history(history: Sequence[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Keep the last few user/assistant turns, trimmed. Drops anything else."""
    out: list[dict[str, str]] = []
    for msg in (history or [])[-MAX_HISTORY_MESSAGES:]:
        role, content = msg.get("role"), msg.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content.strip()[:MAX_HISTORY_CHARS]})
    return out


def build_messages(
    question: str,
    concepts: Sequence[ConceptRecord],
    history: Sequence[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT.strip()},
        {"role": "system", "content": termbase_block(concepts)},
        *clean_history(history),
        {"role": "user", "content": question.strip()[:MAX_QUESTION_CHARS]},
    ]


# ---------------------------------------------------------------- answers

_THINKING = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def clean_answer(text: str) -> str:
    """Drop any visible reasoning block some models emit before the answer."""
    return _THINKING.sub("", text or "").strip()


@dataclass
class Checks:
    ethiopic_ratio: float
    terms_used: list[str] = field(default_factory=list)  # concept ids whose approved term appears
    terms_missing: list[str] = field(default_factory=list)  # retrieved concepts not mentioned


def check_answer(answer: str, concepts: Sequence[ConceptRecord]) -> Checks:
    folded = norm_key(answer)
    used, missing = [], []
    for c in concepts:
        terms = [norm_key(t["text"]) for t in _am_terms_ranked(c)]
        (used if any(k and k in folded for k in terms) else missing).append(c["id"])
    return Checks(
        ethiopic_ratio=round(ethiopic_ratio(answer), 3), terms_used=used, terms_missing=missing
    )


def concept_summary(c: ConceptRecord) -> dict[str, Any]:
    ranked = _am_terms_ranked(c)
    return {
        "id": c["id"],
        "en": headword(c),
        "am": ranked[0]["text"] if ranked else None,
        "status": ranked[0]["status"] if ranked else None,
    }


def validate_question(question: object) -> str:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Ask a question first.")
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"Keep questions under {MAX_QUESTION_CHARS} characters.")
    return question.strip()


async def ask(
    question: str,
    concepts: Sequence[ConceptRecord],
    *,
    base_url: str,
    model: str,
    api_key: str = "ollama",
    history: Sequence[dict[str, Any]] | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    """Answer one question with any OpenAI-compatible endpoint (Ollama, vLLM, ...)."""
    import httpx

    question = validate_question(question)
    found = retrieve(concepts, question)
    messages = build_messages(question, found, history)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages, "temperature": 0.3, "max_tokens": 700},
        )
        resp.raise_for_status()
        answer = clean_answer(resp.json()["choices"][0]["message"]["content"] or "")
    checks = check_answer(answer, found)
    return {
        "answer": answer,
        "concepts": [concept_summary(c) for c in found],
        "checks": checks.__dict__,
        "model": model,
    }
