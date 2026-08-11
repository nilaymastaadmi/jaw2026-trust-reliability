# Prompt for the SECOND held-out set

The first set has been measured against four times and fixed against three, so it is
no longer held out and its score is optimistic. This second set exists to give one
unbiased number. Two rules make that work:

- Give the generating session **no sight of our repo, and no sight of the first set**.
  If it is the same session that produced the first one, start a **fresh** session.
- When it comes back, we run it **once**, cold, and change nothing on the basis of it.

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
infrastructure contractor: 155 completed works (2010–2025), delivered for government
departments and authorities, 486 employees on record. Read `dataset/README.md`,
`dataset/BRIEFING.md`, and the 21 worked examples in `dataset/sample_questions.json`.

Document types you will need: `completion_certificate` (155 — value, dates, and the
client's written grading), `company_completion_certificate` (155), `reference_letter`
(132 — not every work has one), `personnel_certificate` (48 credentials), `cv` (39
engineers), and 9 `.xlsx` workbooks (receivables ageing, BOQ, trial balance, plant
register).

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
   "topic": "client portfolio total"}
]}
```

`answer_type` ∈ `money` (rupees, plain integer) · `count` · `percent` (out of 100, two
decimals) · `days`. `derivation` is **required** — name the works, values or documents
used, so a disagreement can be settled against the corpus.

## Topics — roughly 13–14 questions each

1. Total value delivered for one client
2. Client total **excluding** one category of work
3. Total of a client's works **at or above** a rupee threshold
4. Shortfall between a client's total and a credential threshold
5. Gap between a client's largest and second-largest work
6. Average work size across a client's portfolio
7. Mean minus median contract value (state explicitly whether a negative should stay
   negative or be reported positive — vary which you ask for)
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

## What I most want from this set

**Variety of register.** The first requirement is that these should not all sound like
they came from one template. Write across:
- a formal audit or prequalification memo
- a hurried internal message before a deadline, lowercase and unpunctuated
- a spoken question transcribed, with a false start or a self-correction
- an email from a non-technical colleague who describes things imprecisely
- a terse one-liner with no context at all
- a long paragraph where the actual question arrives at the end

**Spread across entities.** Use as many different clients and people as the corpus
allows. Do not lean on the same handful.

**Combined constraints** (~20 questions). Two conditions at once — a category *and* a
year, a threshold *and* an exclusion, a role *and* a category. These are legitimate
bid-desk questions and they are where a rigid system breaks.

**Difficulty: 50 easy / 150 medium / 100 hard.** For the hard tier draw on:
- client named by shorthand, abbreviation, or partial name
- a work named without its package number
- a person named by first name only
- the question names a work, then asks about "that client" without naming them
- a figure stated in the question that is **wrong**, where the correct answer
  contradicts the asker
- category names where one contains another
- two clients differing only by state, including cases that say which one is *not*
  meant
- a question that reads like one topic but is actually another

## Rules

- Derive every answer **by writing and running code** over the documents. Do not
  compute totals mentally and do not estimate. A wrong "correct" answer is worse than
  no question, because it sends the other side chasing a bug that does not exist.
- Every question must have exactly **one defensible answer**. If you cannot pin one,
  drop the question.
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
