# Prompt for the THIRD held-out set

Sets 1 and 2 are both spent — every failure in them has been read and fixed against,
so their scores are no longer measurements. This set is the only clean number we will
have, and it is being generated *before* the code it will judge is finished.

Two rules make it work:

- Generate it in a **fresh session** with **no sight of our repo** and no sight of
  either previous set.
- When it comes back we run it **once**, cold, and report whatever it says.

Paste everything below the line.

---

You are writing a test set to measure someone else's document question-answering
system. I need questions **with correct answers that you derive yourself, by running
code over the documents**. Write them fresh — do not reuse or adapt any question set
you may have written before, and do not try to guess how the system under test works.

## The corpus

```bash
git clone https://github.com/satvikGIKA/BITS-Hackathon-Dataset.git dataset
pip install pymupdf openpyxl
```

687 documents about **National Infrastructure Corp. Ltd.**, a synthetic Indian
infrastructure contractor: 155 completed works (2010–2025), 486 employees on rolls,
6 business units. Read `dataset/README.md`, `dataset/BRIEFING.md`, and the 21 worked
examples in `dataset/sample_questions.json`.

Three extraction warnings:
- Use **PyMuPDF**. Some PDF libraries silently return field *labels* and drop field
  *values* on these table-heavy documents, raising no error.
- Dates are **day-first**: `06/02/2011` is 6 February.
- `INR 33.38 Cr`, `3,338.00 Lakh` and `33,38,00,000` are the same number. Financial
  statements and annual reports are stated **in lakhs**.

## Output

**600 questions** in one JSON file:

```json
{"questions": [
  {"qid": "H3-0001",
   "question": "…",
   "answer_type": "money",
   "answer": 2008199999,
   "derivation": "PWD Maharashtra, 6 works: 193299999 + 176600000 + … = 2008199999",
   "difficulty": "medium",
   "area": "completion certificates",
   "topic": "client portfolio total"}]}
```

`answer_type` ∈ `money` (rupees, plain integer) · `count` · `percent` (out of 100, two
decimals) · `days`. `derivation` is **required** — name the documents, rows or values
used, so a disagreement can be settled against the corpus rather than argued about.
`area` names the document type the answer comes from, so the two sides score separately.

## Coverage — spread these across ALL twenty document types

The index at `dataset/document_index.csv` lists every document and its type. Aim for
roughly proportional coverage, with a floor of **fifteen questions per type that has
at least five documents**, and cover the four Excel workbooks too. Approximately:

| area | docs | ~questions |
|---|---|---|
| completion certificates (incl. company copies) | 310 | 150 |
| reference letters | 132 | 45 |
| performance bonds | 60 | 55 |
| personnel certificates + CVs | 87 | 45 |
| compliance matrices | 40 | 50 |
| bank statements + general ledgers | 16 | 45 |
| financial statements | 7 | 45 |
| RA bills + final RA bills | 12 | 45 |
| tender dossiers | 6 | 30 |
| ISO certificates | 5 | 25 |
| annual reports | 2 | 20 |
| the four workbooks (ageing · trial balance · asset register · BOQ) | 4 | 45 |

**Do not hand over a list of question shapes.** Read each document type, decide what a
prequalification panel or an auditor would actually ask of it, and ask that. Some
suggestions per area, to be departed from freely:

- **Bonds** — total guaranteed exposure; bonds by issuing bank; the guarantee
  percentage; bonds issued or expiring in a year; how many are released against live;
  the guarantee against the contract value it secures.
- **Compliance matrices** — requirements met and not met across tenders; the minimum
  turnover, staff count or owned-asset count quoted; which tender quotes the highest bar.
- **ISO certificates** — validity spans in days; major and minor non-conformities
  across audits and across certificates; audits by lead auditor; which standard.
- **Tender dossiers** — aggregate bid value; bids by year; head-count by business unit
  and in total; earnest money; relevant-works counts.
- **Financial statements** — a line in a given year; year-on-year movement; margins as
  a percentage; the previous-year comparative against the following year's current.
- **Trial balance / general ledgers** — an account balance in a year; movement between
  years; contract revenue split by work category; a ledger account's closing position.
- **Bank statements** — closing balance; deposits or withdrawals in a year; the
  largest single transaction; receipts against invoices.
- **RA bills** — a bill's value of work, GST, retention, net claimed; a BOQ line item;
  the cumulative position; awarded value less value actually billed.
- **Asset register** — gross block; value or count by type, location, ownership or
  condition; how much is safety-certified; average acquisition age.
- **Annual reports** — board composition; headline figures and their comparatives.
- **The works, cut in ways nobody has asked for** — counts rather than sums; the whole
  estate rather than one client; one category across all clients; one state; the
  smallest rather than the largest; the median alone; a person's entire delivered
  value; the span in days between two completions; earliest and latest completion.

**Cross-cutting — about 60 of the 600.** Combine two sources or two constraints: a
category *and* a year; a role *and* a threshold; plant at one location against works in
that state; bonds against the contracts they secure; invoiced against work done on RA
bills; the compliance matrix's staff minimum against actual head-count.

## Difficulty and register

**100 easy / 300 medium / 200 hard.** The hard tier should draw on all of:
client named by shorthand or partial name; a work named without its package number; a
person named by first name only; the question naming a work then asking about "that
client"; **a figure stated in the question that is wrong**, where the correct answer
contradicts the asker; category names where one contains another (`Buildings` vs
`Small Buildings`); two clients differing only by state, **including phrasing that says
which one is *not* meant**; a question that reads like one topic but is actually
another; an instruction about the **sign** or the **unit** of the answer.

**Vary the register.** These must not sound like one template. Write across a formal
audit memo; a hurried lowercase message before a deadline; transcribed speech with a
false start and a self-correction; an email from a non-technical colleague who
describes things imprecisely; a bare one-liner; a bulleted request; a message with the
question buried at the end of a long paragraph; and a Slack message with an @mention.

**Spread across entities.** Use as many different clients, people, categories, years,
banks, locations, accounts and document instances as the corpus allows. Do not lean on
a handful — if a client or a person appears more than about eight times, redistribute.

## Rules

- Derive every answer **by writing and running code** over the documents. Do not
  compute totals mentally and do not estimate. A wrong "correct" answer is worse than
  no question: it sends the other side chasing a bug that does not exist.
- Every question must have exactly **one defensible answer**. If you cannot pin one,
  drop it.
- Watch the units. Financial statements and annual reports are in lakhs; certificates
  use crore, lakh and Indian digit grouping interchangeably. State answers in
  **rupees**, except `percent` (out of 100) and `days`.
- Do not include the same question twice in different words.
- Where a document type has a **short and a long template** (the bonds do), draw
  questions from both.

## Two extra sections, listed separately from the 600

1. `"ambiguous_probes"` — up to 15 questions the corpus genuinely **cannot** determine
   (asking about "his client" for an engineer who served seven, with no project named).
   Give these no answer, just the question and one line on why it is underdetermined.
   They test whether the system degrades gracefully or answers confidently and wrongly.

2. `"unit_traps"` — up to 15 questions where the naive reading gets the unit or the
   scale wrong: a financial-statement line asked for in rupees, a percentage asked for
   as a fraction, a figure that appears in two documents at two scales. Give these
   normal answers; they are scored.

Finally, note anything in the corpus you found genuinely ambiguous, inconsistent, or
impossible to read reliably.
