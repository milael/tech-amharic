"""Evaluation harness for technical Amharic (design doc: Model work).

Scores a model on the ``eval`` split with three metrics:

* term accuracy  - did the answer use the preferred or an admitted term?
* script fidelity - share of letters in Ge'ez script (catches script drift)
* chrF           - character n-gram F-score against the preferred term

Runs against any OpenAI-compatible chat endpoint: Ollama
(http://localhost:11434/v1), vLLM, or a hosted API. Three prompt settings let
you compare zero-shot, glossary-in-prompt (retrieval) and fine-tuned models
on the same items.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any

from .normalize import ethiopic_ratio, norm_key

SYSTEM_PROMPT = (
    "You are a precise English to Amharic technical translator. Answer with the Amharic term only."
)


# ---------------------------------------------------------------- metrics


def _char_ngrams(text: str, n: int) -> Counter[str]:
    s = "".join(text.split())  # chrF ignores whitespace by default
    return Counter(s[i : i + n] for i in range(len(s) - n + 1))


def chrf(hypothesis: str, reference: str, max_n: int = 6, beta: float = 2.0) -> float:
    """chrF (Popović 2015), 0-100. Averages precision/recall over n = 1..max_n."""
    precisions, recalls = [], []
    for n in range(1, max_n + 1):
        hyp, ref = _char_ngrams(hypothesis, n), _char_ngrams(reference, n)
        if not hyp or not ref:
            continue
        overlap = sum((hyp & ref).values())
        precisions.append(overlap / sum(hyp.values()))
        recalls.append(overlap / sum(ref.values()))
    if not precisions:
        return 0.0
    p, r = mean(precisions), mean(recalls)
    if p == 0 and r == 0:
        return 0.0
    return 100 * (1 + beta**2) * p * r / (beta**2 * p + r)


def term_hit(answer: str, accepted: Iterable[str]) -> bool:
    """True if any accepted term appears in the answer, spelling variants allowed."""
    key = norm_key(answer)
    return any(norm_key(term) and norm_key(term) in key for term in accepted)


# ---------------------------------------------------------------- prompting


def build_messages(
    item: dict[str, Any], setting: str, glossary: Sequence[dict[str, Any]] = ()
) -> list[dict[str, str]]:
    """``setting`` is 'zero_shot' or 'glossary' (approved terms injected as context)."""
    user = f"Translate this technical term into Amharic: {item['en']}"
    if item.get("definition_en"):
        user += f"\nMeaning: {item['definition_en']}"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if setting == "glossary" and glossary:
        lines = "\n".join(f"- {g['en']}: {g['am']}" for g in glossary if g.get("am"))
        messages.append(
            {"role": "system", "content": f"Approved Tech-Amharic terms for reference:\n{lines}"}
        )
    messages.append({"role": "user", "content": user})
    return messages


# ---------------------------------------------------------------- scoring


@dataclass
class ItemResult:
    id: str
    en: str
    expected: str
    answer: str
    hit: bool
    script: float
    chrf: float


def score_item(item: dict[str, Any], answer: str) -> ItemResult:
    accepted = [item["am"], *item.get("am_admitted", [])]
    return ItemResult(
        id=item["id"],
        en=item["en"],
        expected=item["am"],
        answer=answer.strip(),
        hit=term_hit(answer, accepted),
        script=ethiopic_ratio(answer),
        chrf=chrf(answer, item["am"]),
    )


def summarize(results: Sequence[ItemResult]) -> dict[str, float]:
    if not results:
        return {"n": 0, "term_accuracy": 0.0, "script_fidelity": 0.0, "chrf": 0.0}
    return {
        "n": len(results),
        "term_accuracy": round(100 * mean(r.hit for r in results), 1),
        "script_fidelity": round(100 * mean(r.script for r in results), 1),
        "chrf": round(mean(r.chrf for r in results), 1),
    }


def run(
    items: Sequence[dict[str, Any]],
    *,
    base_url: str,
    model: str,
    setting: str = "zero_shot",
    glossary: Sequence[dict[str, Any]] = (),
    api_key: str = "ollama",
    timeout: float = 120,
) -> tuple[dict[str, float], list[ItemResult]]:
    """Query the model for every item and score the answers."""
    import httpx

    results: list[ItemResult] = []
    with httpx.Client(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:
        for item in items:
            if not item.get("am"):
                continue
            resp = client.post(
                "/chat/completions",
                json={
                    "model": model,
                    "messages": build_messages(item, setting, glossary),
                    "temperature": 0,
                },
            )
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"] or ""
            results.append(score_item(item, answer))
    return summarize(results), results


def write_report(
    path: str, summary: dict[str, float], results: Sequence[ItemResult], meta: dict[str, Any]
) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {"meta": meta, "summary": summary, "items": [asdict(r) for r in results]},
            fh,
            ensure_ascii=False,
            indent=2,
        )
