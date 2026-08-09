# JAW 2026 Hackathon — HANDOFF

**Status as of 9 Aug: Phases 1 and 2 complete. 25/25 (100%) on the samples,
end to end from raw question text, scored by the organizers' own `evaluate.py`.**

## Deadlines

| When | What |
|---|---|
| **10 Aug, 3:00 PM** | Validation set drops |
| **13 Aug, 12:00 PM IST** | Final submission |
| 15 Aug | Winners present, 20 min + slides |

Scoring is the repo's `evaluate.py` bands (1.0 / 0.7 / 0.3 / 0), **not** the
website's linear formula. The cliff at 0.5% relative error is the design
constraint: approximately right is worth almost nothing.

## Submission protocol — read before the drop

The platform requires a **40-char commit SHA** with every submission, recorded so
judges can verify the code afterwards. So **every submission needs its own
commit** — resubmitting a SHA already used is refused.

```bash
python src/answer.py --questions <validation.json> --out work/submission.jsonl --per-question
git add -A && git commit -m "submission N: <what changed>"
git rev-parse HEAD          # paste this 40-char string with the upload
```

Platform rules that shape strategy:

| Rule | Consequence |
|---|---|
| Score = mean over **all** questions, out of 100 | An unanswered question scores 0 **and still counts** — never leave one blank. Already enforced by the fallback ladder. |
| Attempts are limited per team, with cooldowns | Do **not** burn attempts on speculative tweaks. Each one must be a considered improvement. |
| Attempts consumed only by **accepted** files | A rejected/malformed file is free. A duplicate SHA is refused, also free. |
| Repo private during, public after | Keep it private. Hand over the URL once submissions close. |

Because attempts are capped, the earlier "submit early even if imperfect" advice
is **wrong**. Submit once early to prove the mechanism works and get a baseline,
then hold remaining attempts for changes justified by the per-shape breakdown.

## What exists

```
dataset/            cloned, checksum-verified, never modified
src/
  normalize.py      money / dates / client / work-name / word-numbers
  corpus.py         PyMuPDF text cache (work/text_cache/, 678 files)
  parsers.py        CCC, CC, REF, PCERT, CV — all 7 layouts
  parse_portfolio.py DOC-PPP-001 → role (Prime / JV Partner)
  build_db.py       → work/db.json
  router.py         question → {shape, params}; deterministic + optional LLM
  executor.py       the 13 shapes; ALL arithmetic lives here
  answer.py         questions → submission.jsonl, with the fallback ladder
  reconcile.py      teammate diff harness (--selftest proves it works)
  test_executor.py  executor against the 25 golds
  test_components.py invariants, intermediates, the date trap
work/               db.json, text_cache/, submission.jsonl, answer_log.json
```

Rebuild from scratch: `python src/build_db.py && python src/answer.py`

## Verification (all currently pass)

```bash
python src/test_components.py      # invariants + published intermediates
python src/test_executor.py        # 25/25 executor
python src/test_router_stress.py   # 46/46 on unseen paraphrases
python src/test_entities.py        # 33/33 client + person resolution
python src/answer.py --per-question # 25/25 end to end
cd dataset && python evaluate.py --submission ../work/submission.jsonl \
    --questions sample_questions.json
```

**`test_entities.py` guards the most dangerous failure class.** 12 of the 28
clients differ from a sibling only by state name (three *Jal Nigam*, four
*Public Works Department*, three *Irrigation & Waterways*, two *Public Health
Engineering*). The original head-match fallback returned the alphabetically-first
sibling, so `"Jal Nigam in Uttar Pradesh"` silently became `"Jal Nigam, Gujarat"`
at full confidence — 6 of 15 realistic phrasings resolved to the **wrong** client.

Resolution now scores token coverage and **returns `None` on a tie rather than
guessing**. The three outcomes are not equally bad:

| Outcome | Meaning |
|---|---|
| correct | the goal |
| `None` | safe — confidence drops to 0, question lands in the triage log |
| **wrong** | silent — a confident, plausible, entirely incorrect number |

The test asserts **zero wrong**. A `None` on a hard phrasing is acceptable.

Invariants: 155 works · 28 clients · 132 with a reference letter · 23 without ·
total ₹5,530.40 Cr (README says ~5,530) · 48 credentials (39 PMP + 9 Six Sigma).

**`test_router_stress.py` is the one that matters for the hidden set.** The 25
samples only prove one phrasing per shape; the hidden set is "larger and harder"
and "not templated". The stress file holds 37 deliberately-unseen paraphrases —
chatty, synonym-heavy — and asserts shape + parameters + that the executor runs.
It found 3 real routing bugs on first run (all fixed):

| Missed phrasing | Cause |
|---|---|
| `above INR 6 Cr` | unit alternation had `crore` but not the abbreviation `Cr` |
| `runner-up` | rank_value only knew `second` / `2nd` |
| `lacking letters` | absence required the full phrase `letter on file` |

**Add a case here whenever the leaderboard suggests a shape is bleeding** — it is
the cheapest way to find a routing gap without gold answers.

## The four traps, and how they're handled

1. **pdfplumber silently drops table values** — returns field labels, no values,
   no error (15 digits vs PyMuPDF's 129 on `DOC-CC-001`). PyMuPDF everywhere.
2. **Two label vocabularies per doc type** — `Work`/`Executed Value`/`Project Lead`
   vs `Project Name`/`Contract Value`/`Project Manager`, plus 71 completion
   certificates that are pure prose. Synonym map + prose regex fallbacks.
3. **Dates are day-first** — `06/02/2011` is 6 Feb, verified against
   `DOC-CC-001`. Reading it as US format silently breaks every `date_span`.
   Asserted in `test_components.py`.
4. **Client names differ only by case** — `(psu)` vs `(Psu)` splits one client
   into two and corrupts every aggregate. 51 raw strings → 28 real clients.

Two more worth knowing:

- **`hop_aggregate` means the client's ENTIRE portfolio**, even when the question
  says "assignments *he* delivered". The person only identifies the client.
  Scoping it to the person's own works fails HS-IC-0007 and HS-IC-0008.
- **Grading lives only in prose.** `is graded X` (84 table certs), `assessed the
  completed work as X` (59 company certs), and prose certificates whose
  assessment paragraph reads "taken over on **satisfactory** completion" → the
  other two prose paragraphs carry no grade. The universal boilerplate "The
  quality of work has been found satisfactory…" appears on certificates graded
  *Good* — treating it as a grade poisons `doc_filtered_aggregate`.

## Router

Deterministic is **primary**: instant, free, offline, 25/25. The LLM backend is
escalation only, and only overrides where the deterministic router reports
confidence < 1.0.

Deliberate: the `claude` CLI hits a session limit and would consume the
operator's own quota mid-competition. `router.route_llm()` is written against
the Anthropic SDK (`claude-opus-5`, batched, structured output) and activates
only when `ANTHROPIC_API_KEY` is set — `python src/answer.py --llm`.

## Answering policy

Never blank. Blank = 0, wrong guess = 0, rough guess can = 0.3. Ladder:
router → nearest simpler shape on the same client → client total → corpus
median for that answer type. Every fallback is logged to `work/answer_log.json`.

## Teammate brief — independent reconciliation

Write **only** `src/alt_extract.py` → `work/db_alt.json`. Do not touch anything
else; there are then no merge conflicts.

Route: `DOC-PPP-001` (portfolio, 64 pages, all 155 works) + the 155
`completion_certificate` PDFs. Deliberately *not* the company completion
certificates — that is the primary route, and reusing it would prove nothing.

```json
{"works": [{"work": "RCC Bridge — Gujarat Pkg-1", "value": 333800000,
            "client": "National Special Projects Office",
            "completed": "2011-02-06", "lead": "Suresh Desai", "role": "Prime"}]}
```

Then `python src/reconcile.py` → `work/recon_report.md`. Every mismatch is a
real bug in one of the two routes — open the document and read the field.
Prioritise disagreements on the 23 works lacking a reference letter: absence
questions are where a plausible-but-wrong answer is most likely.

`python src/reconcile.py --selftest` proves the harness detects seeded errors
(it currently catches 3/3) — run it before trusting a clean report.

## Open items

- ~~Register on the platform~~ — **done 9 Aug.**
- **Workbooks: data extracted, shapes deliberately NOT built.**
  `python src/parse_workbooks.py` → `work/finance.json`. Kept out of the answer
  path; nothing downstream depends on it.

  *Why extract:* `BRIEFING.md` frames questions as what a bidder must prove about
  "past performance, credentials, **financial standing** and personnel". We cover
  three of those four and none of the financial one — and the workbook values
  genuinely are reachable nowhere else (confirmed: receivables ageing, trial
  balance, plant register and BOQ line items appear in no PDF).

  *Why not build shapes:* the README says the hidden set is "the same kinds of
  question" as the samples; all 25 map to the 13 shapes, and the labelled `shape`
  field looks like a fixed taxonomy. Guessing a financial question's form risks a
  working 100% system for speculative gain.

  **If validation shows financial questions**, the data is already parsed — write
  only the executor shape. ~20 minutes, not two hours.

  Verified linkage:
  - `receivables.by_client` keys on our canonical clients (24 of 28 present;
    ₹1,750 Cr invoiced, ₹263 Cr outstanding across 519 invoices).
  - `Public Health Engineering Dept, West Bengal` appears in receivables but has
    **no completed work** — only a tender dossier and an RA bill mention it. Its
    absence from our 28 is correct, not a parsing miss.
  - BOQ contracts join to works by package number (Contract 71 ↔ `Pkg-71`), but
    only 6 of 155 works have one, and **BOQ totals run ~2× the certificate
    value** — they measure gross measured quantity, not contract value. Do not
    conflate the two.
- One work has no role (154/155). Only matters if a `role_split` question names
  that specific work's client.
- Optional: email organizers re: the website/`evaluate.py` scoring discrepancy.
  Not blocking — exactness wins under either formula.
