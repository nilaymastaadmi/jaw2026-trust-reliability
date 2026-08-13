# Corpus notes — ambiguities, inconsistencies, and unreliable reads

Found while building a 600-question test set against the National Infrastructure Corp. corpus
(687 documents, 20 types) by parsing every document with PyMuPDF and cross-validating extracted
figures across independent sources. Everything below was confirmed against the primary documents,
not inferred.

## Genuinely ambiguous or inconsistent

1. **One work's value depends on which rendering you trust.** Road Widening — Maharashtra Pkg-21's
   completion certificate states the raw digits `INR 19,32,99,999/-` = 193,299,999 — but every
   crore-rounded rendering of the same work elsewhere (company_completion_certificate, the
   past-performance portfolio) reads `INR 19.33 Cr` = 193,300,000, a ₹1 difference. This is the one
   completed work (of 155) whose true value isn't a clean multiple of ₹1 lakh, so 2-decimal
   crore-rounding loses precision on it specifically. We used the raw-digit figure as canonical,
   which also matches the corpus's own sample_questions.json worked example (HS-IC-0007, which sums
   to 2,008,199,999 using 193,299,999).

2. **Crore-rounding loses real precision more broadly.** All 6 final RA bills show the same pattern:
   the headline "Total Value of Work Billed" is rounded to 2 decimals of crore (nearest ₹1 lakh),
   while the Part II BOQ-wise summary — and the matching BOQ workbook — carry the exact figure. The
   gap runs from a few hundred rupees up to ~₹47,000 depending on the contract. Any question about
   an "exact" RA-bill total needs to say which precision it wants; we always specified.

3. **32 of 60 performance bonds literally state a guaranteed amount of zero.** Every bond using the
   short "Bank Guarantee Department" template (32 of 60) reads `Rs. 0 (Rupees 0 Only)` / `INR 0`
   verbatim, states no status (Released/Active), and states no guarantee percentage. Only the 28
   long-template bonds carry a real amount, a 5% guarantee clause, and a status. This looks like an
   unfilled template field in the source generation, not a real ₹0 guarantee — but it is what the
   documents say, so "total guaranteed exposure across all 60 bonds" is honestly dominated by (and
   numerically equal to) the 28 long-template bonds alone. We flagged this explicitly wherever a
   question touches it rather than silently omitting the short-template bonds.

4. **"210 owned assets" is repeated everywhere but isn't quite true.** All 40 compliance matrices and
   all 6 tender dossiers state "210 owned assets" as bid evidence. The actual asset-register workbook
   lists 210 total assets, of which only 154 are marked `owned` and 56 are marked `leased`. The bid
   documents use "owned" to mean "on our equipment register," not literal ownership.

5. **The Annual Report's "Profit for the year" row mixes units within itself.** In the Financial
   Highlights table, a negative profit year is rendered in absolute rupees, Indian-grouped (e.g.
   `Rs. -3,90,26,159`), while a positive profit year in the same row is rendered in Lakh (e.g.
   `Rs. 753.38 Lakh`) — same table, same row, two different scales depending on sign. This happens in
   both FY2024-25 and FY2025-26 annual reports. A reader who assumes the whole table is "in Lakh"
   (as the neighbouring Gross Billings / Net Revenue rows genuinely are) will misread any negative
   year by a factor of 100,000.

6. **Two fields are genuinely truncated in the source PDF, not lost to extraction.** The Annual
   Report's Board of Directors table gives "on board since" as `14/1`, `27/0`, etc. — a day/month
   fragment with no year, cut off by a column that's too narrow. The tender dossier's Annexure D2
   "complete register of completed works" truncates its Year column to `Janu`, `Febr`, `Octo`, etc.
   the same way. We confirmed with PyMuPDF's word-level extraction that the underlying PDF content
   stream itself only contains the truncated characters — this is not a text-extraction artifact, and
   no other document in the corpus supplies the missing digits. We did not build any question that
   depends on these fields.

7. **The Annual Report's order-book narrative and annexure are static, not re-measured.** The "State
   of Affairs & Order Book" paragraph (17 contracts, Rs. 56,796.04 Lakh awarded, 75 variation orders)
   and the full 17-row Order Book annexure are byte-for-byte identical between the FY2024-25 and
   FY2025-26 Annual Reports — only the credit-note count and amount differ between the two reports.
   Segment revenue, quarterly revenue, principal clients, variation-order line items, receivables
   ageing, and the trial balance annexure all correctly roll forward year to year; this one section
   apparently does not. We did not build a "how did the order book change year over year" question,
   since the honest answer from these documents is "it didn't, per this annexure."

8. **A reference-letter validity period is a leaked enum, not a duration.** 40 of 132 reference
   letters (the "To Whomsoever It May Concern" template) state "This reference is valid for a period
   of **High**" or "**Medium**" from the date of the letter — literal category labels where a
   duration like "2 years" was clearly intended. No document anywhere converts High/Medium into an
   actual number of days.

9. **The corpus never actually names 62 clients.** The README/Briefing describe "62 government
   departments and authorities" as clients. Scanning every document type that names a client
   (completion certificates, RA bills, final RA bills, the Annual Reports' order book / principal
   clients / ageing tables, the receivables-ageing workbook), only **29** distinct client names
   appear anywhere in the 687 shipped documents. The 155 completed works span 28 of those; the 29th
   (Public Health Engineering Dept, West Bengal) has RA-bill and order-book activity but zero
   completed works on file — a legitimate "0" answer, not a gap in our reading.

10. **Every "paid" invoice in the receivables-ageing workbook shows a *negative* outstanding
    balance.** `Outstanding = Invoiced − Received`, and for all 352 invoices marked `paid`, Received
    exceeds Invoiced, so Outstanding is negative — systematically, not as isolated noise. A system
    that assumes outstanding can't go below zero will get every one of these wrong.

11. **Financial-statement "balance sheet extracts" don't balance.** Assets do not sum to
    Equity + Liabilities on any of the 7 financial statements or in the Annual Reports' balance
    sheets — e.g. DOC-FS-2019: liabilities+equity extract sums to a different figure than the assets
    extract. These are explicitly labelled "extracts," so this isn't necessarily an error, but it
    means a "does the balance sheet balance" question can't assume the answer is zero — we computed
    the actual (non-zero) difference rather than asserting one.

12. **One asset type has a stray leading space in the workbook.** All 14 "Tunnel Boring Machine" rows
    in the asset-register workbook store `Type` as `" Tunnel Boring Machine"` (leading space) —
    the only column/value in either workbook with this defect. An exact-match filter on the clean
    string silently returns zero rows.

## Rendering variety we had to normalize (not inconsistencies, but worth flagging)

- **Category names render two ways.** "Bridges & Flyovers" (Annual Report, trial balance, asset
  register — the canonical form) vs. "Bridges Flyovers" / "Industrial Epc" / "Roads Highways"
  (completion certificates — ampersand dropped, odd title-casing). We normalized on the canonical
  form throughout; a system that string-matches literally will miss every completion-certificate
  category reference unless it also normalizes.
- **Money renders four different ways**, sometimes within the same sentence of the same document:
  `INR 33.38 Cr`, `Rs. 65.46 Lakh`, `33,38,00,000` (Indian grouping), `22,320,149` (international
  grouping), plain integers in workbook cells, and `(2,464,151)` (parentheses-as-negative in RA
  bills). All four/five conventions coexist across completion certificates, reference letters, bonds,
  and RA bills — sometimes two in the same certificate (a Lakh/Cr figure plus a spelled-out
  "Rupees X Crore Only" cross-check).
- **Dates render three ways**: ISO (`2011-02-06`), day-first slash (`06/02/2011`), and spelled-out
  (`06 Feb 2011` / `February 6, 2011` / `6 February 2011`) — sometimes for the same date in the same
  document pair (completion_certificate vs. company_completion_certificate for the same work).
- **Package numbers (Pkg-1..Pkg-155) are the one fully reliable, globally-unique join key** across
  completion certificates, company completion certificates, the past-performance portfolio, and
  reference letters. Work *names* alone are not unique — e.g. four different "RCC Bridge" works exist
  across four states, and "WTP Augmentation — West Bengal" and "Ring Road — Uttar Pradesh" each name
  *two* different works with different package numbers and very different values.
