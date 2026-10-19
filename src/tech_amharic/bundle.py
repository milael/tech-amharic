"""Offline lookup over a release bundle. Used by the CLI (and later the
VS Code extension and MCP server, which port the same logic)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .normalize import norm_key
from .records import BUNDLE_SCHEMA, ConceptRecord


@dataclass(frozen=True)
class Hit:
    concept: ConceptRecord
    matched: str  # the term text that matched
    exact: bool


class Bundle:
    def __init__(self, data: dict[str, Any]) -> None:
        if data.get("schema") != BUNDLE_SCHEMA:
            raise ValueError(f"Unsupported bundle schema: {data.get('schema')!r}")
        self.version: str = data["version"]
        self.concepts: list[ConceptRecord] = data["concepts"]
        # norm_key -> [(concept index, term text)]
        self._index: dict[str, list[tuple[int, str]]] = {}
        for i, concept in enumerate(self.concepts):
            for term in concept["terms"]:
                self._index.setdefault(norm_key(term["text"]), []).append((i, term["text"]))

    @classmethod
    def load(cls, path: Path) -> Bundle:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def lookup(self, query: str) -> list[Hit]:
        """Exact match on the folded key, in either language."""
        key = norm_key(query)
        seen: set[int] = set()
        hits: list[Hit] = []
        for idx, text in self._index.get(key, []):
            if idx not in seen:
                seen.add(idx)
                hits.append(Hit(self.concepts[idx], text, exact=True))
        return hits

    def search(self, query: str, limit: int = 20) -> list[Hit]:
        """Exact matches first, then substring matches, de-duplicated by concept."""
        key = norm_key(query)
        if not key:
            return []
        hits = self.lookup(query)
        seen = {id(h.concept) for h in hits}
        for term_key, entries in sorted(self._index.items(), key=lambda kv: (len(kv[0]), kv[0])):
            if key in term_key and term_key != key:
                for idx, text in entries:
                    concept = self.concepts[idx]
                    if id(concept) not in seen:
                        seen.add(id(concept))
                        hits.append(Hit(concept, text, exact=False))
            if len(hits) >= limit:
                break
        return hits[:limit]
