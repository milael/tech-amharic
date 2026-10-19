"""Text normalization for Amharic (Ge'ez script) and English terms.

Two separate things happen here, and the difference matters:

* ``clean`` produces the *stored* form of a term: Unicode NFC, trimmed, single
  spaces. It never changes which letters someone chose.
* ``norm_key`` produces a *search key*. It folds the Ge'ez letters that
  Amharic writers use interchangeably (the "homophone" letters), strips
  spaces and punctuation, and casefolds Latin script. Two spellings of the same
  word get the same key, so a search with the "wrong" letter still finds the
  entry. The key is never shown to users.

Ethiopic syllables are laid out in rows of eight code points: one row per
consonant, one column per vowel order. That lets us fold a whole consonant row
with arithmetic instead of a long lookup table.
"""

from __future__ import annotations

import unicodedata

# Consonant rows that are pronounced identically in modern Amharic.
# Key: first code point of the variant row. Value: first code point of the
# canonical row it folds into.
_ROW_FOLDS: dict[int, int] = {
    0x1210: 0x1200,  # ሐ row -> ሀ row
    0x1280: 0x1200,  # ኀ row -> ሀ row
    0x1220: 0x1230,  # ሠ row -> ሰ row
    0x12D0: 0x12A0,  # ዐ row -> አ row
    0x1340: 0x1338,  # ፀ row -> ጸ row
}

# For the glottal and h- consonants, the 1st and 4th vowel orders sound the
# same (ሀ / ሃ, አ / ኣ), and writers mix them freely.
_ORDER_FOLDS: dict[int, int] = {
    0x1203: 0x1200,  # ሃ -> ሀ
    0x12A3: 0x12A0,  # ኣ -> አ
}

_ETHIOPIC_RANGES: tuple[tuple[int, int], ...] = (
    (0x1200, 0x137F),  # Ethiopic
    (0x1380, 0x139F),  # Ethiopic Supplement
    (0x2D80, 0x2DDF),  # Ethiopic Extended
    (0xAB00, 0xAB2F),  # Ethiopic Extended-A
)


def is_ethiopic_char(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _ETHIOPIC_RANGES)


def _fold_codepoint(cp: int) -> int:
    row_start = cp & ~0x7
    if row_start in _ROW_FOLDS:
        cp = _ROW_FOLDS[row_start] + (cp - row_start)
    return _ORDER_FOLDS.get(cp, cp)


def clean(text: str) -> str:
    """Return the stored form of a term: NFC, trimmed, single-spaced."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def norm_key(text: str) -> str:
    """Return the search key for a term. See the module docstring."""
    out: list[str] = []
    for ch in unicodedata.normalize("NFC", text).casefold():
        category = unicodedata.category(ch)
        # Drop punctuation (incl. ። ፣ and hyphens), separators and format
        # characters such as zero-width joiners.
        if category[0] in {"P", "Z", "C"} or category in {"Sk", "Sm"}:
            continue
        out.append(chr(_fold_codepoint(ord(ch))) if is_ethiopic_char(ch) else ch)
    return "".join(out)


def ethiopic_ratio(text: str) -> float:
    """Share of letters in ``text`` that are Ge'ez script (0.0 to 1.0).

    Used by the eval harness to catch "script drift", where a model starts an
    Amharic answer and slides into Latin or another script.
    """
    letters = [ch for ch in text if unicodedata.category(ch)[0] == "L"]
    if not letters:
        return 0.0
    return sum(is_ethiopic_char(ch) for ch in letters) / len(letters)


def detect_lang(text: str) -> str:
    """Best-effort ``"am"`` / ``"en"`` guess for a short term."""
    return "am" if ethiopic_ratio(text) >= 0.5 else "en"
