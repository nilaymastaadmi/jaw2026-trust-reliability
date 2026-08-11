# Prompt for the SECOND held-out set

The first set has been measured against four times and fixed against three, so it is
no longer held out and its score is optimistic. This second set exists to give one
unbiased number, and to find the questions we cannot answer *at all*.

Two rules make that work:

- Give the generating session **no sight of our repo, and no sight of the first set**.
  If it is the same session that produced the first one, start a **fresh** session.
- When it comes back, we run it **once**, cold, and change nothing on the basis of it.

The important change: it no longer hands over a closed list of question types. A list
of the things we already handle can only measure how well we handle them. Half of this
set is left to the generator to build from parts of the corpus our harness has never
touched, and every question is tagged so the two halves score separately.

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
infrastructure contractor: 155 completed works (2010–2025), 486 employees on rolls,
6 business units. Read `dataset/README.md`, `dataset/BRIEFING.md`, and the 21 worked
examples in `dataset/sample_questions.json`.

Three extraction warnings:
- Use **PyMuPDF**. Some PDF libraries silently return field *labels* and drop field
  *values* on these table-heavy documents, raising no error.
- Dates are **day-first**: `06/02/2011` is 6 February.
- `INR 33.38 Cr`, `3,338.00 Lakh` and `33,38,00,000` are the same number. Financial
  statements are stated **in lakhs**.

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
decimals) · `days`. `derivation` is **required** — name the documents, rows or values
used, so a disagreement can be settled against the corpus. `family` is `"listed"` or
`"invented"`, per the two sections below.

## Section A — 150 questions, `"family": "listed"`

Roughly 7 each, over the completion certificates, reference letters, personnel
certificates and the receivables workbook.

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

**This is the more important half.** Section A covers two data sources. The estate has
far more, and a prequalification panel would ask about all of it. Spread these roughly
evenly over the twelve areas below, then invent beyond them.

**1. Performance bonds — 60 documents.** Each carries a bond number, issue date, the
issuing bank, a tender reference, the work description, and a guarantee struck as a
percentage of contract value. Ask about total guaranteed exposure, bonds by bank or by
year, the guarantee percentage, counts.

**2. Compliance matrices — 40 documents.** Each is a tender checklist: numbered
requirements, a Complied/Not status, evidence references, a minimum turnover
requirement, a minimum staff count, an owned-asset count, an EMD reference. Ask about
requirements met, thresholds quoted, counts across tenders.

**3. ISO certificates — 5 documents.** Certificate number, standard (9001 / 14001 /
45001), initial certification date, valid-until date, and a schedule of audits with
major/minor non-conformity counts and lead auditors. Ask about validity spans in days,
NCs across audits, counts.

**4. Tender dossiers — 6 documents.** RFP reference, bid value, submission date,
earnest money, relevant-works count, and a **business unit table with head-counts**.
Ask about aggregate bid value, bids per year, head-count by unit, EMD.

**5. Financial statements — 7 documents.** Full profit-and-loss extracts **in lakhs**,
with a previous-year comparative: contract revenue, other operating revenue, cost of
materials, sub-contracting and labour, employee benefits, depreciation, other
expenses, total expenses, profit before and after tax. Ask about a line in a given
year, year-on-year movement, margins as a percentage.

**6. Trial balance — 7 years in a workbook.** Per-account debit, credit and balance,
including contract revenue split by work category. Ask about an account balance in a
year, movement between years, revenue by category.

**7. Plant and machinery register — 211 items in a workbook.** Each has a type, make,
acquisition year, cost, condition, location, ownership (owned or hired) and a
safety-certification flag. Ask about gross block, value or count by type, location or
ownership, how much is safety-certified, average acquisition age.

**8. RA bills — 12 documents.** Running-account bills with BOQ line items (unit, rate,
quantity, amount), value of work done, GST at 18%, retention at 5%, net claimed, and a
cumulative position. Ask about a bill's value, tax or retention, a line item, the
cumulative figure.

**9. BOQ workbooks — 6 contracts.** Bill-of-quantity totals and measured totals with
per-item quantities and rates. Ask about a contract's BOQ total, an item's amount, the
gap between billed and measured.

**10. Bank statements and general ledgers — 16 documents.** Dated transactions with
withdrawals, deposits and running balances; ledger accounts with debits, credits and
balances. Ask about a closing balance, deposits in a year, an account's total.

**11. Annual reports — 2 documents.** Board composition, financial highlights,
registers. Ask about counts and headline figures.

**12. Portfolio shapes nobody has asked for yet.** Still the completed works, but cut
differently: **counts** rather than sums (how many works above a value, how many in a
year, how many clients, how many categories); the **whole estate** rather than one
client; one category across **all** clients; the **smallest** rather than the largest;
the median on its own; works in one **state** (every work title names one); a person's
**entire** delivered value rather than the post-credential part; how many works one
person led; the span in days between two works' completion dates; the earliest or
latest completion; a percentage share of something other than reference letters.

**Cross-cutting — about 25 of the 150.** Combine two constraints or two sources: a
category *and* a year; a role *and* a threshold; plant at one location against works in
that state; bonds against the contract values they secure; invoiced against work done
on RA bills.

Invent freely beyond all of this. If a number is readable from the documents and a
reasonable person might ask for it, it belongs here — **especially if it feels unlike
anything in Section A.** Several of these are expected to be unanswerable by the
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

**Spread across entities.** Use as many different clients, people, categories, years,
locations and document instances as the corpus allows. Do not lean on a handful.

## Rules

- Derive every answer **by writing and running code** over the documents. Do not
  compute totals mentally and do not estimate. A wrong "correct" answer is worse than
  no question, because it sends the other side chasing a bug that does not exist.
- Every question must have exactly **one defensible answer**. If you cannot pin one,
  drop it.
- Watch the units. Financial statements are in lakhs; certificates use crore, lakh and
  Indian digit grouping interchangeably. State answers in **rupees**.
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
