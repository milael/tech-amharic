---
license: cc-by-sa-4.0
language:
  - am
  - en
pretty_name: Tech-Amharic
task_categories:
  - translation
  - text-generation
tags:
  - amharic
  - terminology
  - ethiopic
  - low-resource
size_categories:
  - n<1K
configs:
  - config_name: terms
    data_files: terms.parquet
  - config_name: instructions
    data_files: instructions.parquet
  - config_name: eval
    data_files: eval.parquet
---

# Tech-Amharic

Human-reviewed English–Amharic terminology for computing and technology, exported from the [Tech-Amharic termbase](https://github.com/milael/tech-amharic).

## Configs

| Config | Row | Intended use |
| --- | --- | --- |
| `terms` | One concept: English headword, preferred Amharic term, admitted and deprecated alternatives, definitions, domain | Lookup, terminology-constrained translation |
| `instructions` | Templated instruction/response pairs (translate term, back-translate, define in Amharic) | Supervised fine-tuning |
| `eval` | Held-out concepts in the `terms` schema | Benchmarking; never train on it |

## How it was made

Every Amharic term in this dataset was approved by a reviewer in the Tech-Amharic workflow. Unreviewed proposals are excluded. Splits are assigned per concept with a stable hash, so all rows from one concept share a split. Instruction rows are generated from templates (`origin: template`).

Candidate terms come from the ELRC ICT dictionary (ICT Development Office & Ethiopian Languages Research Center, 2011), AI drafts (Claude seed set, Gemma 4 suggestions) and visitor proposals. Each term keeps its source, so you can filter by origin.

## Limitations

- Small and growing; domain coverage is uneven early on.
- Preferred terms reflect the reviewer group's judgement and may differ from other glossaries or regional usage.
- No speech data.

## Citation

```bibtex
@misc{techamharic2026,
  title  = {Tech-Amharic: an open, reviewed termbase for computing terms in Amharic},
  author = {Deneke, Milael Mekonnen and contributors},
  year   = {2026},
  url    = {https://github.com/milael/tech-amharic}
}
```
