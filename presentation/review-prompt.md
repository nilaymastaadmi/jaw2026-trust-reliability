# Follow-up: review the actual repository, then tell us what to tear out

Same conversation as before — you wrote us the verdict on the 47.3% cold set, the
enumerate-and-retrieve architecture, the reranker, the phase 0–6 sequence. This is the
follow-up. Two things have changed: we acted on part of your advice and have new numbers,
and **you can now read the code and the corpus yourself** rather than working from our
description of them.

```bash
# our harness
git clone https://github.com/nilaymastaadmi/jaw2026-trust-reliability
# the corpus (public)
git clone https://github.com/satvikGIKA/BITS-Hackathon-Dataset.git dataset
pip install pymupdf openpyxl
```

If the harness repo is not reachable, say so and we will make it public or paste files.

Read `README.md` first, then `src/answer.py` (the entry point), `src/classify.py` (the
router — 1,537 lines and the thing we most suspect), `src/executor.py` (the 23 named
shapes), `src/graph.py` + `src/generic.py` + `src/schema.py` (the compositional layer),
and `src/parse_*.py` (extraction). ~8,000 lines of Python, no dependencies beyond PyMuPDF
and openpyxl, no network at answer time.

## What happened since your last reply

**Your "get the golds" step was already done.** The 600-question set arrived with `answer`
AND `derivation` per question, plus a corpus-notes document from the generating party
listing the ambiguities they hit. So we have a labelled cold set and a per-question error
log, not one data point. We split it 304/296 by area, fixed only against the dev half, and
report the holdout.

**We tried your instinct that routing was the problem, and it wasn't.** We rebuilt routing
to match the question against the DATA MODEL instead of a word list: index every table
name, column name and categorical value, weight each term by 1/(tables containing it), let
the question pick its own table and column (`src/schema.py`). Then ablated it:

| configuration | dev |
|---|---|
| schema picks entity + field | 40.205 |
| schema picks entity only | 47.188 |
| schema picks field only | 41.264 |
| **no schema at all** | **47.969** |

Net-neutral at best. The field chooser was actively harmful for a reason we think
generalises: **a question states its FILTERS explicitly and leaves the measured quantity
implicit**, so matching column names against the question retrieves precisely the wrong
columns. Restricting it to numeric columns and excluding columns already used to select
rows recovered most of the loss. It now runs only as a fallback.

**The ablation's real value was telling us routing was not the bottleneck.** Re-reading the
failures, most were numbers *not in the store at all*. Five document types had never been
parsed:

- the 155 CONTRACTOR copies of the completion certificates (the client's copy was parsed,
  the contractor's was not) — they carry the defect liability period, and they are an
  independent second reading of all 155 works
- the 39 CVs (joining date, tenure, total experience, qualification — nothing else states
  any of them)
- the 132 reference letters (the contract value as the CLIENT records it; a validity field
  which in 44 of them is the literal word `High` or `Medium`)
- the annual reports' four tables (segment revenue, seven-year summary, receivables ageing
  annexure, principal clients) — the narrative only summarises them
- each tender dossier's Annexure C (gross billings, net turnover, net profit per FY)

Your point about the 155×155 cross-check was correct and paid off immediately: **155/155
works agree on value, completion date, category and lead across the two independent
sources, zero numeric disagreements.**

**Your "conventions, not phrasings" point found a real systematic error.** The Indian
financial year is labelled in this corpus by the year it STARTS in, but a question naming
it by the year it ENDS — "for the year ended 31 March 2021" — means the year before.
Financial statements went 20.78 → 44.61 on that one rule.

## Where we actually are

```
released 333-question evaluation set   100.000   (leaderboard-confirmed; frozen)
4,500 paraphrases of those 333          ~100%    (two banks, one held back)
set 3 dev      (fixed against)   45.248 → 52.626
set 3 holdout  (never read)      49.347 → 52.826
```

Cold-set breakdown now, worst first: annual reports 14, CVs 32, workbooks 32, ISO 38,
dossiers 42, reference letters 44, financial statements 45, bonds 48, bank/ledger 55, RA
bills 64, completion certificates 65, compliance matrices 69. By difficulty: easy 66,
medium 52, hard 30. By unit: percent 28, days 34, money 46, count 55.

Of 600 cold questions: **208 exact, 169 partial, 223 zero.**

## What we are asking

Read the code, read the corpus, and be blunt. We are not looking for encouragement.

1. **Tear-out list.** What in this repository is actively wrong-headed and should be
   deleted rather than improved? We suspect `classify.py` — 1,537 lines, ~40 ordered rules,
   scores 100% on the set it was written against and 65% on the same *family* of question
   in a set it wasn't. Is the named-shape layer worth keeping at all, or is it a local
   optimum we should abandon even at the cost of the 100%?

2. **A better decomposition.** We currently have: parse → 32 typed tables (4,812 rows) →
   two parallel routers → executor. Given what you can now see of the corpus, what is the
   right decomposition? If you would not have built either router, say what you would have
   built instead, concretely enough to implement.

3. **Where our extraction is still wrong or thin**, from reading the documents yourself.
   We validate against identities the documents assert, but you were right that this only
   covers cells that participate in an identity. Tell us which cells are unguarded and
   which of them you would bet are wrong. Point at specific documents.

4. **The percent and days families are our worst (28% and 34%) and they are small
   integers**, where the proportional metric is least forgiving. Is there something
   systematically wrong with how we handle them, or is it just coverage?

5. **What have we still not thought of.** Including things you raised last time that we
   have not done — and specifically: is there a cheap 80% version of your
   enumerate-and-retrieve idea that fits in days rather than weeks? We are more interested
   in a smaller idea we can finish than a larger one we cannot.

6. **Honest ceiling.** Given what the code actually is, not what we described: what score
   on a fresh cold set is reachable in ~2 days of work, and what would it take to reach 80%?
   If the answer is "not much without the multi-week program", say that plainly.

Constraints that are real: the grader runs our code offline on their machine, so no network
at answer time; we cannot rely on shipping large binaries; determinism is required
(same input, same output). Everything else is negotiable, including the 100% on the
released set and any file in the repo.
