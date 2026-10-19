# Reviewer style guide (draft v0.1)

A starting point for the reviewer group to agree, amend and own. Decisions here are defaults, not laws; a reviewer can depart from them with a comment explaining why.

## 1. What a decision means

| Decision | Use when |
| --- | --- |
| Approve as **preferred** | This is the term we recommend in teaching material, documentation and software. One per concept. |
| Approve as **admitted** | Correct and in real use, but not the first choice. Often the loanword practitioners already say. |
| **Request changes** | Close, but spelling, form or scope needs work. Say exactly what. |
| **Reject** | Wrong meaning, misleading, or a duplicate. Always give the reason. |
| **Deprecate** | Previously published, but now discouraged (superseded, confusing, unused). |

## 2. Coin, borrow or both?

Ask in this order:

1. **Is there an established term people already use?** Prefer it, even if it is a loan. Usage beats elegance.
2. **Will non-specialists meet this concept?** (password, download, privacy) A native or extended Amharic word helps comprehension; make it preferred and keep the loan as admitted.
3. **Is it a specialist term mostly used by engineers?** (kernel, container, tokenizer) A loan is often clearer. Admit a native coinage only if it is short and transparent.
4. **Is it an acronym practitioners say as letters?** (API, GPU) Keep the acronym; spell it in Ge'ez only if that form is already common.

Avoid literal calques that mislead. "የእሳት ግድግዳ" for *firewall* reads as a physical wall; prefer the loan or a descriptive term.

## 3. Spelling

- Store exactly the spelling you recommend. Search already tolerates ሀ/ሐ/ኀ, ሰ/ሠ, አ/ዐ and ጸ/ፀ variants, so do not add entries that differ only in these letters.
- For loanwords, follow the most common published spelling; note alternatives in the term's note.
- Write multi-word terms with spaces (ድረ ገጽ), not hyphens, unless the hyphen is standard.

## 4. Definitions

- English definition: one sentence, plain words, no circular use of the term.
- Amharic definition: written fresh in Amharic, not a word-for-word translation. Reviewers should prioritise these; they unlock the `define_am` dataset task.

## 5. Process

- Review in a weekly slot so the queue moves.
- Never review your own proposal (the system enforces this).
- When reviewers disagree, admit both and discuss in the concept note; choose a preferred term at the next sync.
- Seed terms (source kind `draft`) are machine-assisted drafts. Treat them with extra scepticism.
