# Prompt for the SECOND held-out set

The first set has been measured against four times and fixed against three, so it is
no longer held out and its score is optimistic. This second set exists to give one
unbiased number. Two rules make that work:

- Give the generating session **no sight of our repo, and no sight of the first set**.
  If it is the same session that produced the first one, start a **fresh** session.
- When it comes back, we run it **once**, cold, and change nothing on the basis of it.

The important change from the first prompt: it no longer hands over a closed list of
question types. A list of the things we already handle can only measure how well we
handle them. Half of this set is deliberately left to the generator to invent from the
corpus, and every question is tagged so the two halves can be scored separately.

Paste everything below the line.

---

You are writing a test set to measure someone else's document question-answering
system. I need questions **with correct answers** that you derive yourself, from the
documents. Write them fresh — do not reuse or adapt any question set you may have
written before, and do not try to guess how the system under test works.

## The corpus

```bash
git clone https://github.com/satvikGIKA/BITS-Hackathon-Dataset.git dataset
pip install pymupdf openpyxl
```

687 documents about **National Infrastructure Corp. Ltd.**, a synthetic Indian
infrastructure contractor: 155 completed works (2010–2025), 486 employees on record,
6 business units. Read `dataset/README.md`, `dataset/BRIEFING.md`, and the 21 worked
examples in `dataset/sample_questions.json`.

**The whole estate is in scope.** Counts by type:

| Type | N | | Type | N |
|---|---|---|---|---|
| `completion_certificate` | 155 | | `compliance_matrix` | 40 |
| `company_completion_certificate` | 155 | | `general_ledger_book` | 8 |
| `reference_letter` | 132 | | `bank_statement` | 8 |
| `performance_bond` | 60 | | `financial_statement` | 7 |
| `personnel_certificate` | 48 | | `tender_dossier` | 6 |
| `cv` | 39 | | `ra_bill` / `final_ra_bill` | 12 |
| `iso_certificate` | 5 | | `annual_report` | 2 |
| `past_performance_portfolio` | 1 | | workbooks (`.xlsx`) | 9 |

The workbooks hold receivables ageing, a plant and machinery register, a trial balance
by year, and BOQ/measurement detail.

Three extraction warnings:
- Use **PyMuPDF**. Some PDF libraries silently return field *labels* and drop field
  *values* on these table-heavy certificates, raising no error.
- Dates are **day-first**: `06/02/2011` is 6 February.
- `INR 33.38 Cr`, `3,338.00 Lakh` and `33,38,00,000` are the same number.

## Output

**300 questions** in one JSON file:

```json
{"questions": [
  {"qid": "H2-0001",
   "question": "…",
   "answer_type": "money",
   "answer": 2008199999,
   "derivation": "PWD Maharashtra, 6 works: 193299999 + 176600000 + … = 2008199999",
   "difficulty": "medium",
   "topic": "client portfolio total",
   "family": "listed"}
]}
```

`answer_type` ∈ `money` (rupees, plain integer) · `count` · `percent` (out of 100, two
decimals) · `days`. `derivation` is **required** — name the works, values or documents
used, so a disagreement can be settled against the corpus. `family` is `"listed"` or
`"invented"`, per the two sections below.

## Section A — 150 questions, `"family": "listed"`

Roughly 7 each. These make the set comparable to an earlier one.

1. Total value delivered for one client
2. Client total **excluding** one category of work
3. Total of a client's works **at or above** a rupee threshold
4. Shortfall between a client's total and a credential threshold
5. Gap between a client's largest and second-largest work
6. Average work size across a client's portfolio
7. Mean minus median contract value (say explicitly whether a negative stays negative
   or is reported positive — vary which you ask for)
8. Value difference between **two categories** for one client
9. Change in a client's completed value **between two calendar years**
10. A **single** calendar year's completed value for one client
11. Days between a credential's issue date and a project's completion
12. Value of works a person led that completed **after** their credential date
13. Number of distinct work categories a person has led
14. Client total reached **via** a person and one of their projects
15. Count of a client's works with **no** reference letter
16. Percentage of a client's works that **carry** a reference letter
17. Total for works carrying a particular **written grading** — read these off the
    certificates; a boilerplate line about work being "found satisfactory" appears on
    certificates graded otherwise, so do not trust that phrase
18. Total delivered as **Prime**, or as **JV Partner**
19. Amount a client still owes — invoiced less received
20. Percentage of a client's billed amount actually collected
21. Total invoiced, or total received, for a client on its own
22. Gap between total contract value awarded and total invoiced

## Section B — 150 questions, `"family": "invented"`

**This is the more important half. Do not reuse Section A's topics.**

Go through the corpus and ask what else a bid desk, an auditor, or a prequalification
panel would legitimately want a number for. Deliberately cover the document types
Section A never touches — performance bonds, compliance matrices, ISO certificates,
tender dossiers, RA bills, bank statements, financial statements, ledgers, annual
reports, the plant and machinery register, the trial balance, and BOQ detail.

Some directions, to start you off rather than to limit you:

- **Bonds and guarantees** — value outstanding, bonds against one client, expiry
  spans, guarantee as a proportion of contract value
- **Plant and machinery** — gross block, count by type or location, value of what is
  owned versus hired, how much is safety-certified, average age
- **Accounts** — a line item in a given year's trial balance, movement between years,
  a figure from a financial statement, ledger totals, receipts in a bank statement
- **Tendering** — number of bids submitted, their aggregate value, compliance-matrix
  pass rates
- **Accreditation** — ISO certificates held, their validity spans
- **Workforce** — headcount, credentials held across staff, how many hold more than
  one, designation mix
- **Portfolio shapes nobody asked for yet** — counts rather than sums (how many works
  above a value, how many clients, how many works in a year); the whole estate rather
  than one client; a category across all clients; the *smallest* rather than the
  largest; a span between two completion dates; a duration of one work start to finish
- **Cross-cutting** — combine two constraints, or two data sources: a category *and* a
  year, a role *and* a threshold, works in one state, plant at one location against
  works in that state

Invent freely beyond these. If a number is readable from the documents and a
reasonable person might ask for it, it belongs in Section B — **especially if it feels
unlike anything in Section A.** Some of these are expected to be unanswerable by the
system under test; that is exactly what the section is for.

## Difficulty and register (both sections)

**50 easy / 150 medium / 100 hard.** Hard tier should draw on: client named by
shorthand or partial name; a work named without its package number; a person named by
first name only; the question naming a work then asking about "that client"; a figure
stated in the question that is **wrong**, where the correct answer contradicts the
asker; category names where one contains another; two clients differing only by state,
including phrasing that says which one is *not* meant; a question that reads like one
topic but is actually another.

**Vary the register.** These should not sound like one template. Write across a formal
audit memo; a hurried lowercase message before a deadline; transcribed speech with a
false start or self-correction; an email from a non-technical colleague who describes
things imprecisely; a bare one-liner; and a long paragraph where the question arrives
at the end.

**Spread across entities.** Use as many different clients, people, categories and
years as the corpus allows. Do not lean on the same handful.

## Rules

- Derive every answer **by writing and running code** over the documents. Do not
  compute totals mentally and do not estimate. A wrong "correct" answer is worse than
  no question, because it sends the other side chasing a bug that does not exist.
- Every question must have exactly **one defensible answer**. If you cannot pin one,
  drop it.
- Do not include the same question twice in different words.

## One extra section

Separately from the 300, list up to 10 questions under `"ambiguous_probes"` that the
corpus genuinely **cannot** determine — for example asking about "his client" for an
engineer who worked for seven different clients with no project named. Give these no
answer, just the question and one line on why it is underdetermined. They are not
scored; they test whether the system degrades gracefully or answers confidently and
wrongly.

Finally, note anything in the corpus you found genuinely ambiguous, inconsistent, or
impossible to read reliably.
