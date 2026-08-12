# Brainstorm request — a document-QA system that has hit a wall

You have no access to our repository and you should not ask for it. Think fresh. We want
approaches we have not considered, not a review of ours.

## The task

687 unstructured documents describe one synthetic Indian infrastructure contractor
(National Infrastructure Corp. Ltd.). No database, no schema, no document-to-entity map is
supplied. A grader feeds us a JSON file of natural-language questions and reads back a CSV
of `question_id,answer`. Answers are plain numbers: rupees, counts, percentages out of 100,
or day counts.

Scoring is **proportional, per question, then averaged**:

```
score = max(0, 1 - |got - gold| / |gold|)     blank or missing = 0
```

So a confident wrong answer scores 0, while a number of roughly the right magnitude keeps
most of its credit. There is no penalty for answering; never leaving a blank is strictly
correct.

The 20 document types: completion certificates (155) and company copies (155), reference
letters (132), performance bonds (60), personnel certificates (48), compliance matrices
(40), CVs (39), bank statements (8), general ledgers (8), financial statements (7), tender
dossiers (6), RA bills (6), final RA bills (6), BOQ workbooks (6), ISO certificates (5),
annual reports (2), plus four Excel workbooks (receivables ageing, trial balance, asset
register, BOQ). Roughly 155 completed works, 29 clients, 39 key personnel, 519 invoices,
211 plant items, 7 years of accounts.

Questions look like these (real examples, verbatim):

- "Two of our clients are called Public Works Department — I do NOT mean the Gujarat one.
  I mean Maharashtra. Total delivered value for them please."
- "rahul das mp pkg-49 rigid pavement pmp issued march 10 2021, days to completion?"
- "Per the FY 2025-26 Annual Report's Financial Highlights table, what was 'Profit for the
  year', in rupees?"
- "Bond BND-00082 guarantees 5% of the contract value, at INR 21,802,000. What contract
  value does that imply?"
- "I have about 14 crore in my head for this, but I doubt it — what's the average size of
  all work we've finished for them?"

Registers vary deliberately: formal audit memos, hurried all-lowercase messages before a
deadline, transcribed speech with false starts, Slack messages, long paragraphs with the
question buried at the end. Hard cases include a client named by shorthand, a work named
without its package number, a person by first name only, a figure stated in the question
that is **wrong**, category names that contain one another (`Buildings` / `Small
Buildings`), and two clients differing only by state — including phrasing that says which
one is *not* meant.

## What we built

Two stages, both deterministic, **no language model anywhere in the answer path**:

1. **Extraction.** PyMuPDF over every PDF, openpyxl over the workbooks, into typed entity
   tables (~23 tables, ~4,400 rows): works, people, clients, invoices, assets, accounts,
   bonds, compliance rows, audits, dossiers, business units, P&L lines, RA bills, BOQ
   lines, bank transactions, ledger lines, directors. This part we trust — it is validated
   against identities the documents themselves assert (an RA bill's net claimed = value of
   work + GST − retention; a bank statement's running balance = previous + deposit −
   withdrawal; a P&L's total expenses = the sum of its five expense lines).

2. **Routing.** Question → a query. Two mechanisms:
   - **23 hand-written "shapes"** (client portfolio total, exclusion aggregate, threshold
     aggregate, gap to a credential bar, mean-minus-median, year delta, unbilled gap,
     receivable balance, date span, …). A classifier picks one by *family signature*:
     `answer_type` partitions hard, then tests ordered by how much structure they require
     (a question naming two categories is a category delta however it is worded).
   - **A compositional query** for everything the shapes cannot reach:
     `select(entity) → filter(predicates) → reduce(sum|count|mean|median|min|max|distinct)`,
     plus two compositions (a delta between two years, a ratio of two lines).

## Where we stand — honestly

- The 333-question released evaluation set: **100.000%**, confirmed by the leaderboard.
- A paraphrase harness that rewrites those 333 questions 21 ways without changing what
  they ask (synonyms, registers, punctuation, typos, a person by first name, a stated wrong
  figure, three rewrites composed): **~100%**, ~4,500 rewrites.
- A **fresh 600-question set**, written blind by another party against all 20 document
  types, run once cold: **47.3%**. By area: annual reports 13%, financial statements 21%,
  CVs 31%, tender dossiers 34%, bonds 37%, ISO certificates 42%, and — the alarming one —
  **completion certificates 60%**, which is the *same family* the released set scores 100%
  on. Hard-tier questions: 30%.

**The diagnosis we believe.** Extraction is not the bottleneck; routing is. Both mechanisms
choose a table, a column, a filter and a reduction using hand-written regular expressions.
That works exactly as far as the patterns have been extended and no further. Every question
type nobody anticipated needs new vocabulary — so improvement is memorisation, and the gap
between 100% on the set we tuned against and 47% on a set we did not is the measure of it.

**What we have already tried and what it bought:**

- Ordered first-match rule ladder → replaced by a family-signature classifier. Large win on
  the tuned set (73 → 98), no evidence it generalises.
- A compositional query layer for entities no shape covers. Real capability gain, but its
  entity/column choice is still regex-driven.
- Reading corpus facts out of the corpus (client names, categories, gradings, roles,
  credential dates) rather than hard-coding them. Genuinely helps.
- Refusing rather than guessing when a client mention is ambiguous, so the fallback earns
  partial credit instead of a confident zero.
- A fallback ladder: routed shape → nearest shape of the same unit → corpus-typical median
  of that unit. Never blank.
- Currently mid-flight: routing by matching the question against the **schema itself** —
  index the table names, column names and categorical values, weight each term by 1/(number
  of tables containing it), and let the question pick its own table and column. Early signs
  are promising but it is still bag-of-words matching.

## What we want from you

Ignore our architecture where it is convenient. We are asking for ideas, ranked by what you
think would move a cold, unseen question set the most:

1. **Fundamentally different ways to map a natural-language question onto a query over
   known typed tables**, given no training data, no labelled question→query pairs, and a
   hard requirement that the mapping generalise to question types nobody has read. What
   would you do that is not a pattern list?
2. **Self-verification.** Under proportional scoring, a confident wrong answer costs
   everything and a rough answer costs little. What cheap checks could a system run on its
   own answer — magnitude, unit, cross-source agreement, arithmetic identity — to decide
   whether to trust it or to fall back to something safer? How would you calibrate
   "am I sure?" without labels?
3. **Answering under uncertainty.** If several readings of a question are plausible, is
   there something better than picking one? Given the scoring function, what is the optimal
   thing to emit when the system is torn between two candidate answers?
4. **Making the estate self-describing.** Is there a representation of these documents —
   a graph, a semantic layer, a set of derived views, something else — that would make
   question routing easier than it is over 23 flat tables? What would you index, and how
   would you make a question find it?
5. **Ways to find our own blind spots without a labelled test set.** We can generate
   unlimited paraphrases of questions we already answer, but that only measures robustness
   within families we already handle. How would you discover the *families* we cannot
   answer at all, from the documents alone?
6. **Anything we appear not to have considered.** Including: whether the no-language-model
   constraint is worth keeping. Assume the grader runs our code offline on their machine
   with no guaranteed network access — but tell us what we lose by that choice, and whether
   there is a hybrid worth having.

Be concrete. Where you propose a mechanism, say what it indexes, what it computes, what it
would cost to build, and how it would fail. We would rather have three ideas we can test
tomorrow than twenty we cannot.
