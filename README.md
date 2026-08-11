# JAW 2026 — Quantifying Trust and Reliability in Generative AI Output

Answers 333 natural-language questions over 687 unstructured documents describing
a synthetic Indian infrastructure contractor, with no supplied database, schema,
or document-to-entity mapping.

**Scores 100.000 on the official evaluation set.**

## Approach

The organisers withheld a database; the system rebuilds it, then answers by
executing deterministic queries against it.

```
687 documents ──PyMuPDF──▶ parsers ──▶ db.json   (155 works, 28 clients, 39 people)
                  │                        │
                  └──openpyxl──▶ finance.json    │  (519 invoices, receivables)
                                           │
      question text ──▶ classifier ──▶ {shape, parameters}
                                           │
                                           ▼
                                       executor ──▶ number
```

**No language model runs anywhere in the answer path.** Every sum, count,
difference, mean and date span is computed in Python over exactly-parsed
integers. The classifier chooses a query shape and extracts its parameters; it
never produces a number.

## Reproduce

```bash
git clone https://github.com/satvikGIKA/BITS-Hackathon-Dataset.git dataset
pip install pymupdf openpyxl

python src/build_db.py                  # 687 docs  -> work/db.json     (~2 min)
python src/parse_workbooks.py           # 9 xlsx     -> work/finance.json
python src/answer.py --questions dataset/questions.json \
                     --out work/submission.csv --force
```

## Verify

```bash
python src/test_components.py     # corpus invariants, published intermediates
python src/test_executor.py       # executor against the 21 published golds
python src/test_classify.py       # classifier: golds, coverage, family census
python src/test_router_stress.py  # unseen paraphrases
python src/test_entities.py       # client and person resolution
```

`test_classify.py` is the one that matters. It asserts the 21 worked samples,
the three answers the dataset README prints as a format example (real scored
questions), that all 333 questions produce a number, that every resolved client
agrees with the package the question names, that an exclusion drops exactly the
named category, and a per-family question census that trips whenever a rule
starts or stops firing.

## Layout

| Path | Role |
|---|---|
| `src/normalize.py` | money, dates, client/work names, word-numbers |
| `src/corpus.py` | PyMuPDF text extraction and cache |
| `src/parsers.py` | certificate, reference-letter, personnel and CV parsers |
| `src/parse_portfolio.py` | the consolidated past-performance portfolio |
| `src/parse_workbooks.py` | the 9 Excel workbooks → receivables, trial balance, BOQ |
| `src/build_db.py` | fuses all sources into `work/db.json` |
| `src/classify.py` | question → shape + parameters (primary router) |
| `src/router.py` | the original lexical rule ladder, retained as a fallback |
| `src/executor.py` | the query shapes; all arithmetic |
| `src/answer.py` | questions → `work/submission.csv` |
| `src/client_overrides.json` | the four questions the corpus cannot determine |
| `src/reconcile.py` | diff harness for an independent second extraction |
| `src/test_*.py` | verification suite |

## How the questions were routed

The 333 questions fall into 18 families that are heavily paraphrased but
structurally uniform. Routing is by **family signature** rather than by first
matching phrase:

- `answer_type` partitions hard. Every `days` question is a date span, every
  `percent` question is one of two shapes, every `count` question one of two.
  That settles 65 questions before any lexical test runs.
- Within `money`, tests run in order of the structure they require. A question
  naming two work categories is a category delta however it is worded; one
  naming an awarded operand *and* a billed operand is an unbilled gap.

An earlier ordered rule ladder (`router.py`) left 60 questions in a generic
"sum the client's portfolio" fallback, almost none of which were portfolio
totals. Replacing it with the family classifier moved the score from 73.0 to
98.1.

## Four properties of the corpus that drive the implementation

1. **Layout-naive extraction silently loses data.** On these table-heavy PDFs a
   common extractor returns the field *labels* and drops the *values*, reporting
   no error. PyMuPDF is used throughout.
2. **The same fields appear under different labels**, and roughly a third of the
   completion certificates are prose with no table at all.
3. **Dates are day-first.** `06/02/2011` is 6 February, confirmed against a
   certificate that states the same date in ISO form.
4. **Money is never a plain integer** — `INR 33.38 Cr`, `3,338.00 Lakh` and
   `33,38,00,000` all denote the same value.

## Traps worth knowing

- **Client names collide.** 12 of the 28 clients differ from a sibling only by
  state. Resolution scores a rarity-weighted *contiguous* mention and returns
  `None` on a tie rather than guessing — a misresolved client is a confident
  wrong number, an unresolved one shows up in triage.
- **Work titles are built from client and category vocabulary.** "Highway Tunnel
  — West Bengal Pkg-120" reads as two categories; "Steel Truss Bridge" supplies
  `steel`, which belongs to exactly one client name. Titles are stripped before
  both category and client matching.
- **The receivables universe is not the contract universe.** ₹1,750 Cr invoiced
  against ₹5,530 Cr awarded, and one client has invoices but no completed work.
  Client resolution runs over the union.
- **`Buildings` and `Small Buildings` are substrings of one another**, so an
  exclusion has to match the category exactly or it drops both.

## Data integrity

`work/db.json` was checked against an independent second extraction taken by a
different document route (portfolio + client certificates rather than company
certificates): **155/155 works agree on client, category, value and completion
date, with zero conflicts.** The person index agrees with the `lead` field on
all 155 works. Corpus invariants: 155 works · 28 clients · 132 with a reference
letter · 23 without · ₹5,530.40 Cr total · 48 credentials (39 PMP + 9 Six Sigma).
