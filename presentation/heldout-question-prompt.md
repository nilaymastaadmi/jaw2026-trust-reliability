# Prompt for the question-generating session

Paste everything below the line into a fresh session. Do **not** give that session
access to our repo — the whole value of the exercise is that its wording and its
answers are arrived at independently of our implementation.

---

You are building a held-out test set to stress-test someone else's question-answering
system. I need questions **with correct answers**, derived by you, from the documents.

## The corpus

```bash
git clone https://github.com/satvikGIKA/BITS-Hackathon-Dataset.git dataset
pip install pymupdf openpyxl
```

687 documents about **National Infrastructure Corp. Ltd.**, a synthetic Indian
infrastructure contractor: 155 completed works (2010–2025) for 62 government
departments and authorities, 486 employees on record. `dataset/README.md` and
`dataset/BRIEFING.md` describe it. `dataset/sample_questions.json` holds 21 worked
examples with answers and step-by-step derivations — read those first to calibrate
tone and structure, then **write questions that do not copy their phrasing**.

Key document types: `completion_certificate` (155, the client's sign-off — value,
dates, written grading), `company_completion_certificate` (155, our record of the
same work), `reference_letter` (132 — note not every work has one),
`personnel_certificate` (48 credentials), `cv` (39 engineers), plus ledgers, bank
statements, RA bills, tender dossiers, and 9 `.xlsx` workbooks (receivables ageing,
BOQ, trial balance, plant register).

Two extraction warnings, learned the hard way:
- Use **PyMuPDF**. Some PDF libraries silently return field *labels* and drop field
  *values* on these table-heavy certificates, with no error raised.
- Dates are **day-first**. `06/02/2011` is 6 February.
- Money appears as `INR 33.38 Cr`, `3,338.00 Lakh` and `33,38,00,000` — all the
  same value.

## What to produce

**60 questions**, as one JSON file:

```json
{"questions": [
  {"qid": "HO-0001",
   "question": "…the question, phrased naturally…",
   "answer_type": "money",
   "answer": 2008199999,
   "derivation": "PWD Maharashtra: 6 works — 193299999 + 176600000 + 214200000 + 307300000 + 586900000 + 529900000",
   "difficulty": "medium",
   "topic": "client portfolio total"}
]}
```

- `answer_type` ∈ `money` (rupees, plain integer) · `count` · `percent` (out of 100,
  two decimals) · `days`
- `answer` — a plain number, no units, no commas
- `derivation` — **required**. Name the works, values, or documents you used. This is
  what lets a disagreement be adjudicated instead of argued about.

## Coverage — aim for roughly even spread across all of these

Phrase them as a bid desk would actually ask, not as a schema.

**Past performance**
1. Total value of everything delivered for one client
2. Total for one client **excluding** one category of work
3. Total of a client's works **at or above** a rupee threshold
4. How much more work is needed to reach a credential threshold
5. Gap between a client's largest and second-largest work
6. Average / mean work size across a client's portfolio
7. Difference between the mean and the median contract value (say explicitly whether
   a negative result should stay negative)
8. Difference in total value between **two categories** of work for one client
9. Change in a client's completed-work value **between two calendar years**
10. A single calendar year's completed value for one client

**People and credentials**
11. Days between a credential's issue date and a project's completion
12. Combined value of works a named person led that finished **after** their credential
13. Number of distinct work categories a person has led
14. Total for the client reached **via** a person and one of their projects

**Documents and absence**
15. How many of a client's works have **no** reference letter on file
16. Percentage of a client's works that **do** carry a reference letter
17. Total for works carrying a particular **written grading** (Excellent / Very Good /
    Good / Satisfactory) — read these off the certificates yourself; be careful, a
    boilerplate line about work being "found satisfactory" appears on certificates
    that are graded otherwise
18. Total delivered as **Prime** versus as **JV Partner**

**Financial standing** (from the workbooks)
19. Amount a client still owes — invoiced less received
20. Percentage of a client's billed amount actually collected
21. Total invoiced, or total received, for a client on its own
22. Gap between total contract value awarded and the amount invoiced

## Difficulty mix

- **15 easy** — client named in full, one hop, plain wording
- **30 medium** — realistic bid-desk phrasing, two or three hops, some chat register
- **15 hard** — deliberately awkward. Draw on these:
  - client referred to by a **shorthand or abbreviation** (`mah pwd`, `phed odisha`,
    `subarnarekha valley corp`, `NEDA`)
  - a **work named without its package number** ("the Jharkhand hydro tunnel package")
  - a person referred to by **first name only**
  - the question names a **work**, then asks about "that client" without naming them
  - **lowercase, unpunctuated, hurried** phrasing, as if typed before a deadline
  - a stated figure in the question that is **wrong** — the questioner
    misremembering — where the right answer contradicts them
  - a category pair where one category name is a **substring** of another
    (`Buildings` vs `Small Buildings`, `Roads Highways` vs `Roads Maintenance`)
  - two clients whose names differ **only by state**

**Do not** include a question whose answer is genuinely ambiguous — e.g. asking about
"his client" for an engineer who worked for seven different clients, with no project
named. Every question must have exactly one defensible answer, or it cannot be scored.
If you find yourself unable to pin an answer, drop the question.

## Rules

- Derive every answer **from the documents**. Do not estimate, and do not compute
  totals in your head — write and run code that reads the documents and sums exactly.
- Answers must be exact. Scoring is `max(0, 1 − |given − correct| / correct)`, so a
  wrong "correct" answer is worse than no question at all.
- Vary the phrasing. Two questions on the same topic should not read alike.
- Spread the questions across **many different clients and people**, not the same
  three.

Output the JSON file, plus a short note on anything you found genuinely ambiguous or
underdetermined in the corpus.
