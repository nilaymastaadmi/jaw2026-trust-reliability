# JAW 2026 Hackathon — Quantifying Trust and Reliability in Generative AI Output

Answers precise numerical questions over 687 unstructured documents describing a
synthetic Indian infrastructure contractor, with no supplied database, schema, or
document-to-entity mapping.

## Approach

The organisers withheld a database; the system rebuilds it, then answers by
executing deterministic queries against it.

```
687 documents ──PyMuPDF──▶ parsers ──▶ db.json   (155 works, 28 clients, 39 people)
                                          │
question text ──▶ router ──▶ {shape, parameters}
                                          │
                                          ▼
                                     executor ──▶ number
```

The language model's role is confined to classification and parameter extraction.
**It never performs arithmetic.** Every sum, count, difference, mean and date span
is computed in Python over exactly-parsed integers.

This is a direct consequence of the scoring bands: full credit requires ≤0.5%
relative error, and a 3% error scores the same as a 9% one. An LLM asked to add
forty contract values lands within a few percent — which is worth almost nothing.
Parsing exactly and computing in code is worth full marks.

## Reproduce

```bash
git clone https://github.com/satvikGIKA/BITS-Hackathon-Dataset.git dataset
pip install pymupdf openpyxl
python src/build_db.py                      # 687 docs -> work/db.json  (~2 min)
python src/answer.py --questions <file>.json --out work/submission.jsonl
```

## Verify

```bash
python src/test_components.py       # corpus invariants + published intermediates
python src/test_executor.py         # executor against the 25 golds
python src/test_router_stress.py    # unseen paraphrases
python src/answer.py --per-question # end to end
cd dataset && python evaluate.py --submission ../work/submission.jsonl \
    --questions sample_questions.json
```

Scores 25/25 (100%) on the released sample set under the organisers' own
`evaluate.py`.

## Layout

| Path | Role |
|---|---|
| `src/normalize.py` | money, dates, client/work names, word-numbers |
| `src/corpus.py` | PyMuPDF text extraction and cache |
| `src/parsers.py` | certificate, reference-letter, personnel and CV parsers |
| `src/parse_portfolio.py` | the consolidated past-performance portfolio |
| `src/build_db.py` | fuses all sources into `work/db.json` |
| `src/router.py` | question text → shape + parameters |
| `src/executor.py` | the query shapes; all arithmetic |
| `src/answer.py` | questions → `submission.jsonl` |
| `src/reconcile.py` | diff harness for an independent second extraction |
| `src/test_*.py` | verification suite |

## Notes on the corpus

Four properties of the document estate drive most of the implementation:

1. **Layout-naive extraction silently loses data.** On these table-heavy PDFs a
   common extractor returns the field *labels* and drops the *values*, reporting
   no error. PyMuPDF is used throughout.
2. **The same fields appear under different labels**, and roughly a third of the
   completion certificates are prose with no table at all.
3. **Dates are day-first.** `06/02/2011` is 6 February, confirmed against a
   certificate that states the same date in ISO form.
4. **Money is never a plain integer** — `INR 33.38 Cr`, `3,338.00 Lakh` and
   `33,38,00,000` all denote the same value.
