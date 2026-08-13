"""Question -> a compositional graph query, for questions no named shape covers.

classify.py picks one of 23 hand-written shapes. Each answers a single kind of
question over the works or the receivables. This module answers a different way:
it works out WHICH ENTITY the question is about, WHICH ROWS of it, and WHAT
REDUCTION to apply, and hands that to graph.Graph.

    "gross block of our plant"        asset  · []                      · sum(cost)
    "how many works above 50 Cr"      work   · [value >= 5e8]          · count
    "owned excavators in Odisha"      asset  · [ownership=owned,
                                                 type~excavator,
                                                 location=Odisha]      · count
    "roads highways delivered in 2018" work  · [category=Roads Highways,
                                                 year=2018]            · sum(value)

The same three primitives cover all of those, so a question nobody anticipated
needs new parameters rather than new code. That is the whole point: the shape
list could only grow one question-type at a time.

This runs ONLY where the named shapes produce nothing, so it can add coverage
but cannot change an answer the tested path already produces.
"""
import re

import normalize
import schema

# Entity vocabulary. Order matters: the first entity whose words appear wins,
# so the specific ones are listed before `work`, which is the default subject of
# most questions and would otherwise absorb them.
_ENTITY = [
    # -- the nine document types no named shape reaches -------------------
    ("bond", r"\bbonds?\b|bank guarantee|performance guarantee|\bBGs?\b|guarante\w*"
             r"|guaranteed exposure|guarantee amount|guarantee percentage"
             r"|BND-\d+|guarantor"),
    # The annual report's OWN tables, ahead of the financial statement's. The
    # report prints a full balance sheet, a profit and loss, a quarterly split
    # and four annexures, all in rupees; the statement prints an EXTRACT of a
    # balance sheet, in lakhs, with different lines. A question saying "the
    # balance sheet" means the whole one; one saying "the balance-sheet
    # extract" means the statement, which is what the guard below reads.
    # "Balance-sheet EXTRACT" is the financial statement's, not the report's.
    ("fin_line", r"balance[- ]sheet extract|extract of the balance sheet"),
    ("ar_line", r"financial highlights"),
    ("ar_balance", r"balance[- ]sheet(?![- ]extract)(?![^.?]{0,24}\bextract\b)"
                   r"(?<!statement's balance sheet)"),
    # SINGULAR only, and the plural is the giveaway: "Residential Quarters -
    # Uttar Pradesh Pkg-25" is a completed work, not a period, and matching it
    # sent every reference letter about one to the quarterly revenue table.
    ("quarter", r"\bquarterly\b|\bQ[1-4]\s*FY|\bquarter\b(?!s)"),
    ("order_line", r"order[- ]book annexure|contracts? in force|awarded plus variations"
                   r"|order book[^.?]{0,30}\bcontracts?\b"),
    ("variation", r"variation orders?[^.?]{0,40}annexure|annexure[^.?]{0,40}variation order"
                  r"|\bamdt\b|value delta|variation order\b"),
    ("credit_note", r"credit notes? (?:issued|listed|table|annexure)|\bCN-\d{4}-\d+"),
    # "Highest net revenue" on its own is not the seven-year summary: "which
    # work-category SEGMENT posted the highest net revenue that year" is the
    # segment table. The summary is the one indexed BY FISCAL YEAR.
    ("seven_year", r"seven-?year|7-?year|financial summary|by fiscal year"
                   r"|which (?:fiscal|financial) year"),
    ("audit", r"\baudits?\b(?!\s+(?:committee|file|pack|trail|checklist|memo))"
              r"|non-?conformit|\bNCs?\b|lead auditor|surveillance audit"
              r"|re-?certification audit|audit finding|major or minor"),
    ("iso_cert", r"\bISO\b|9001|14001|45001|certificate of registration"
                 r"|certification bod(?:y|ies)|ORG-\d+|accreditation|valid until"
                 r"|certification date|organisational certificates?"
                 r"|issued by (?:a|the|another) body|accredited bod(?:y|ies)"),
    # Ahead of the business unit: "among the 39 key-personnel CVs on file, how
    # many staff belong to the X business unit" counts CVs, and names the unit
    # only to filter them.
    ("cv", r"curriculum vitae|\bCVs?\b|date of joining|joined the company|wage group"
           r"|total experience|years of (?:total )?experience|highest qualification"
           r"|been with (?:the company|us)|tenure"),
    ("business_unit", r"business unit|head-?count by|per unit head|unit head-?count"
                      r"|\bunits?\b[^.?]{0,20}head-?count"),
    ("segment", r"\bsegments?\b|segment revenue|revenue by (?:work )?categor|segmental"
                r"|by segment|segment(?:al)? (?:analysis|performance|commentary)"),
    # The ageing ANNEXURE is the annual report's, one row per client with three
    # buckets. The ageing WORKBOOK is the spreadsheet, one row per invoice.
    # They share a name and answer different questions, so a question naming
    # the workbook or an invoice belongs to the other table.
    ("ageing", r"(?!.*\b(?:workbook|invoices?)\b)"
               r"(?:receivables ageing|ageing annexure|ageing (?:table|bucket)"
               r"|(?:more|greater|older) than 12 months|6\s*(?:-|to|\u2013)\s*12 months"
               r"|largest (?:total )?outstanding|outstanding by client)"),
    ("principal_client", r"principal clients?|clients? by billings|largest share of billings"
                         r"|top clients? by"),
    ("dossier_standing", r"financial[- ]standing|annexure c\b|net turnover"
                         r"|gross billings[^.?]{0,30}dossier|dossier[^.?]{0,30}gross billings"),
    ("compliance", r"\bmatri(?:x|ces)\b|compliance checklist|eligibility"
                   r"|requirements? (?:met|complied|satisfied)|complied\b"
                   r"|checklist|minimum turnover|turnover requirement"
                   r"|CM/\d+|pre-?qualification (?:requirement|criteri)"),
    ("dossier", r"tender dossier|bid value|\bRFP\b|RFP-\d+|earnest money|\bEMD\b"
                r"|tender submission|bid submitted|relevant works|submission dossier"),
    ("final_bill", r"final (?:RA )?bill|per the final|on the final bill"),
    ("ra_bill", r"\bRA bill|running account bill|\bRA-?\d+\b|retention"
                r"|net claimed|value of work done|AR-\d{4}-\d+"),
    # BOQ lines before the bill that carries them: "the BOQ line items on
    # contract #71" names both, and the line items are what is being asked for.
    ("boq_line", r"\bboq\b|bill of quantit|line items?\b|earthwork|macadam"
                 r"|bituminous (?!overlay)|granular sub-?base|reinforcement steel"
                 r"|measured (?:total|quantit)"),
    ("final_bill", r"final bill|awarded value|contract\s*#?\s*\d{2}\b"
                   r"|executed value|approved variations|revised value"),
    # A BOOK named outright beats any line-item vocabulary. "In the FY 2019
    # general ledger, what is the closing balance of account 4003 (Contract
    # Revenue - Water Treatment)" names the ledger, the account and its number,
    # and was answered from the financial statement because "contract revenue"
    # appears in both and the statement was tested first. Same for the trial
    # balance, which lost to the bank statement on the words "closing balance".
    ("ledger_account", r"\baccount\s*\d{3,4}\b|in the (?:FY\s*\d{4}\s*)?ledger"
                       r"|ledger account|general ledger|chart of accounts"),
    ("account", r"trial balance|\bTB\b account|per the trial balance"),
    ("fin_line", r"profit (?:before|after) tax|\bPBT\b|\bPAT\b|profit and loss"
                 r"|profit & loss|financial statement|contract revenue"
                 r"|cost of materials|sub-?contracting|employee benefit"
                 r"|other operating revenue|total expenses|net margin"
                 r"|total revenue|revenue from operations|profit for the year"
                 r"|depreciation (?:and|&) amorti|amorti[sz]ation"
                 r"|operating margin|reserves|paid-?up capital|trade receivable"
                 r"|trade payable|shareholders"),
    # A whole year of a bank statement, as against its individual lines. The
    # closing balance is the year's last balance, not a sum of balances, and
    # "deposits in 2021" is the year's total -- both are held per year already.
    ("bank_year", r"closing\s+(?:\w+\s+)?balance|balance at (?:the )?(?:year|end)"
                  r"|(?:total |all )?(?:deposits?|withdrawals?)\s*(?:in|during|for|across)"
                  r"|total (?:deposits?|withdrawals?)|year-end balance"),
    ("bank_txn", r"bank statement|withdrawal|deposit|running balance"
                 r"|current account|statement of account|single transaction"),
    ("ledger_account", r"general ledger|ledger account|\bledger\b|posted line"
                       r"|chart of accounts|voucher"),
    ("order_book", r"order book|contracts? (?:remained |still )?in execution"
                   r"|how many credit notes|credit notes?[^.?]{0,30}"
                   r"(?:absorbed|annual report|aggregating)"
                   r"|variation orders?|awarded value at year"),
    ("director", r"board of directors|\bdirectors?\b|board composition"),
    # A credential named by its ID, or asked about as a document rather than
    # as the bar a portfolio is measured against -- which is what the released
    # set means by the word, so the pattern requires more than `credential`.
    ("credential", r"PMI-\d+|6S-\d+|ASQ-\d+"
                   r"|credential[^.?]{0,30}(?:valid|expir|issue to|how long)"
                   r"|(?:valid|expir)\w*[^.?]{0,30}credential"),
    ("reference_letter", r"reference letters?[^.?]{0,24}"
                         r"(?:on file|states?|records?|we hold|do we hold|carry)"
                         r"|according to the (?:client )?reference letter"
                         r"|(?:value|amount) (?:stated|recorded) (?:in|on|by) the"
                         r"[^.?]{0,20}(?:reference|letter)"),
    # -- what was here before ---------------------------------------------
    # "Plant" alone is not the register: "Water Treatment Plant - Rajasthan
    # Pkg-58" and "Material Handling Plant - Uttar Pradesh Pkg-47" are
    # completed works, and there are twenty of them. The register is named as a
    # register, or by a machine that only it holds.
    ("asset", r"plant (?:&|and|\u0026) machinery|plant register|machinery register"
              r"|\bmachinery\b|\bequipment\b|\basset\b|excavator|crusher"
              r"|batching|grader|roller|crane|tipper|gross block|fleet"
              r"|\bplant\b(?!\s*[\u2014\u2013-])"),
    ("account", r"trial balance|ledger account|\baccount\b|revenue|expense|payable"
                r"|receivable account|depreciation|balance sheet"),
    ("boq_item", r"\bboq\b|bill of quantit|measured (?:total|quantit)|line item"),
    ("invoice", r"\binvoices?\b|ageing workbook|receivables[- ]ageing"
                r"|\bbilled\b|receipts?\b|ageing"),
    # Word-bounded, or "Lakshya ENGINEERing & Construction" -- a client, on
    # four completed works -- reads as a question about our own engineers.
    ("person", r"\bengineers?\b|\bpersonnel\b|\bstaff\b|\bemployees?\b"
               r"|\bpeople\b|\bperson\b"),
    # `client` as the UNIT BEING COUNTED, not as a scope phrase. "across all
    # clients", "our clients graded Very Good" and "forget one client" are all
    # questions about works, and a loose `\bclients?\b` claimed every one of
    # them before `work` was ever reached.
    ("client", r"how many (?:different |distinct |unique )?(?:clients|authorit(?:y|ies)"
               r"|departments)|number of (?:clients|authorit(?:y|ies)|departments)"
               r"|count of clients|how many .{0,20}accounts\b"),
    ("work", r"work|project|contract|assignment|package|job|delivered|completed"),
]

# Reduction vocabulary, most specific first.
_FN = [
    ("distinct", r"how many (?:different|distinct|unique)|number of (?:different|distinct)"
                 r"|distinct \w+|different \w+"),
    ("count", r"how many|number of|(?<!head-)(?<!head )\bcount\b"
              r"|how much of (?:our|the) \w+ (?:is|are)\b"),
    ("mean", r"\baverage\b|\bmean\b|typical|per[- ]\w+ value"),
    ("median", r"\bmedian\b|middle value"),
    ("max", r"largest|biggest|highest|greatest|most valuable|maximum"),
    ("min", r"smallest|lowest|least valuable|minimum|cheapest"),
    ("sum", r"total|sum|combined|aggregate|gross|altogether|worth|value of|how much"),
]

# The numeric field each entity is normally reduced over.
_FIELD = {
    "asset": "cost", "work": "value", "invoice": "invoiced",
    "account": "balance", "boq_item": "amount", "client": "value",
    "person": "value_led",
    "bond": "amount", "compliance": "complied", "iso_cert": "validity_days",
    "invoice": "invoiced",
    "segment": "current", "ageing": "total", "principal_client": "billings",
    "ar_balance": "amount", "ar_pl": "amount", "quarter": "net_revenue",
    "variation": "value_delta", "credit_note": "amount",
    "order_line": "current_value",
    "seven_year": "net_revenue", "order_book": "contracts_in_execution",
    "dossier_standing": "net_profit",
    "credential": "validity_days", "cv": "tenure_days",
    "company_cert": "value", "reference_letter": "value",
    "audit": "minor", "dossier": "bid_value", "business_unit": "headcount",
    "fin_line": "current", "ra_bill": "net_claimed", "final_bill": "gap",
    "boq_line": "amount", "bank_txn": "deposit", "bank_year": "closing",
    "ledger_account": "closing", "ledger_line": "amount", "ar_line": "current",
}

_STATES = ["West Bengal", "Uttar Pradesh", "Madhya Pradesh", "Tamil Nadu",
           "Maharashtra", "Rajasthan", "Jharkhand", "Gujarat", "Odisha", "Delhi"]


def _neg_before(term, q):
    """Every mention of `term` is there only to rule it out."""
    hits = list(re.finditer(r"\b" + re.escape(term) + r"\b", q, re.I))
    if not hits:
        return False
    return all(re.search(r"\b(?:not|other than|rather than|excluding|except)\b[\s\w]{0,12}$",
                         q[max(0, m.start() - 40):m.start()], re.I) for m in hits)

# A contrast clause names the thing being EXCLUDED, and reading it as a filter
# inverts the question: "delivered as JV Partner rather than as Prime" is a
# JV question that a first-match role test answers with the Prime total.
_CONTRAST = re.compile(r"\s+(?:rather than|as opposed to|instead of|not as|and not"
                       r"|as against|but not)\b[^,.;?]*", re.I)


def _drop_contrast(q):
    return _CONTRAST.sub(" ", q)


# Positive evidence that an estate-wide question is about the completed works
# rather than about a document type nothing here parses. Without it, "total
# guaranteed exposure across our performance bonds" would be answered with a
# works figure -- a confident wrong number where the fallback ladder's
# corpus-typical guess still earns partial credit.
_WORK_EVIDENCE = (r"\bworks?\b|\bprojects?\b|\bcontracts?\b|\bassignments?\b"
                  r"|\bpackages?\b|\bjobs?\b|deliver\w*|complet\w*|grad\w*"
                  r"|reference letter|jv partner|joint venture|\bprime\b"
                  r"|portfolio|estate|past[- ]performance")


# Which COLUMN of an entity a question is asking for. The entity says which
# table; this says which number in it. Ordered, first match wins.
_FIELD_CUES = {
    "credential": [(r"\bdays?\b|valid(?:ity)? (?:for|span|period)|how long|expiry"
                    r"|issue to expiry", "validity_days"),
                   (r"experience", "experience_years")],
    "invoice": [(r"outstanding|still owed|unpaid|balance", "outstanding"),
                (r"received|collected|actually (?:paid|came)", "received"),
                (r"invoiced|billed|raised", "invoiced")],
    "cv": [(r"wage group", "wage_group"),
           (r"experience|years? in the (?:industry|business)", "experience_years"),
           (r"tenure|been with|since joining|days.{0,20}(?:with|at) (?:the |us)?"
            r"|date of joining|how long", "tenure_days")],
    "reference_letter": [(r"\bvalue\b|worth|contract value|amount", "value")],
    # A question can ask for the YEAR of a row rather than a quantity on it:
    # "which work was first completed, and in what year".
    "work": [(r"in what year|which year|what year|year (?:was|did|it)", "year"),
             (r"defect liability", "defect_liability_days")],
    "company_cert": [(r"defect liability|liability period|\bDLP\b",
                      "defect_liability_days"),
                     (r"in what year|which year", "year"),
                     (r"\bvalue\b|worth|contract", "value")],
    "segment": [(r"previous year|prior year|comparative", "previous"), (r".", "current")],
    "seven_year": [(r"gross billing", "gross_billings"), (r"margin", "margin"),
                   (r"profit", "profit"), (r"revenue|net revenue", "net_revenue"),
                   (r"which (?:fiscal )?year", "year")],
    "ageing": [(r"(?:more|greater|older) than 12|over 12|> ?12|beyond a year", "gt12"),
               (r"6\s*(?:-|to|\u2013)\s*12", "m6_12"),
               (r"(?:less|under|within) (?:than )?6|< ?6", "lt6"), (r".", "total")],
    "principal_client": [(r".", "billings")],
    "dossier_standing": [(r"gross billing", "gross_billings"),
                         (r"turnover", "net_turnover"), (r".", "net_profit")],
    "order_line": [(r"current value|awarded plus|including variations", "current_value"),
                   (r"variation", "variations"),
                   (r"awarded", "awarded"), (r".", "current_value")],
    "variation": [(r".", "value_delta")],
    "credit_note": [(r".", "amount")],
    "quarter": [(r".", "net_revenue")],
    "ar_balance": [(r".", "amount")],
    "ar_pl": [(r".", "amount")],
    "order_book": [(r"credit note", "credit_notes"),
                   (r"variation", "variation_orders"),
                   (r"contracts? (?:remained|still|in execution)|how many contracts",
                    "contracts_in_execution"),
                   (r"awarded|aggregate awarded", "order_book_awarded"),
                   (r"contract", "contracts_in_execution")],
    "bond": [(r"contract value|implied|secures|5% of", "contract_value"),
             (r"\bdays?\b|validity|valid for|how long|in force|expiry", "validity_days"),
             (r"stamp", "stamp_value"),
             (r"percentage|per ?cent\b|\bpct\b|what (?:%|percent)", "guarantee_pct"),
             (r"amount|exposure|guarantee[ds]?\b|value|worth|total", "amount")],
    # Status first, then the noun it qualifies: "how many requirements are
    # marked complied" asks for the complied count, not the requirement count.
    "compliance": [(r"(?:emd|earnest)[^.?]{0,30}(?:percent|%|share|ratio)"
                    r"|percent\w*[^.?]{0,30}(?:emd|earnest)", "emd_pct"),
                   (r"not (?:met|complied)|un-?met|failed|outstanding requirement",
                    "not_complied"),
                   (r"turnover", "turnover_req"),
                   # The matrices carry two people-numbers: the minimum the
                   # tender demands, and the number actually on rolls.
                   (r"on rolls|personnel on|engineers available|actually have"
                    r"|do we (?:have|employ)|our (?:personnel|head-?count)", "personnel"),
                   (r"minimum|at least|required|demand|bar\b|key technical staff"
                    r"|site engineers", "staff_min"),
                   (r"staff|personnel|engineers|head-?count", "staff_min"),
                   (r"owned asset|asset count|equipment count", "owned_assets"),
                   (r"\bemd\b|earnest", "emd_amount"),
                   (r"bid value", "bid_value"),
                   (r"complied|\bmet\b|satisfied", "complied"),
                   (r"requirements?\b|conditions?\b|clauses?\b", "requirements")],
    "iso_cert": [(r"major", "major_ncs"), (r"minor", "minor_ncs"),
                 (r"\bdays?\b|validity|valid for|span|how long", "validity_days")],
    "audit": [(r"major", "major"), (r"minor", "minor")],
    # Bid SECURITY before bid value: the instrument lodged in Annexure H and
    # the offer on the covering letter are different numbers, and the catch-all
    # below matches the word "bid" in either.
    "dossier": [(r"bid security|security (?:amount|lodged|instrument)"
                 r"|instrument lodged", "bid_security"),
                (r"true cop(?:y|ies)|certificate cop(?:y|ies)"
                 r"|annexure b\b|registration/certification", "cert_copies"),
                (r"registrations? (?:table|listed|held)|how many registrations",
                 "registrations"),
                (r"how many annexures?|annexures? (?:are|does|form)", "annexures"),
                (r"\bemd\b|earnest", "emd"),
                (r"head-?count|personnel|staff", "headcount"),
                (r"relevant works|past performance", "relevant_works"),
                (r"bid|value|worth|total", "bid_value")],
    "business_unit": [(r"head-?count|people|staff|employees|strength", "headcount")],
    "fin_line": [(r"previous year|prior year|comparative|year before", "previous"),
                 (r".", "current")],
    "ar_line": [(r"previous year|prior year|comparative", "previous"),
                (r".", "current")],
    "ra_bill": [(r"retention[^.?]{0,24}(?:percent|%|rate|out of 100)"
                 r"|percent\w*[^.?]{0,24}retention", "retention_pct"),
                (r"\bgst\b[^.?]{0,24}(?:percent|%|rate)|percent\w*[^.?]{0,16}gst",
                 "gst_pct"),
                (r"\bgst\b|\btax\b", "gst"),
                (r"retention", "retention"),
                (r"net claimed|net of|claimed", "net_claimed"),
                (r"cumulative", "cumulative"),
                (r"value of work|work done|executed", "value_of_work")],
    "final_bill": [(r"how many RA|RA bills?[^.?]{0,20}(?:raised|against|total)"
                    r"|number of RA", "ra_count"),
                   # The gap against the REVISED value is a different column
                   # from the gap against the awarded value, and a question
                   # that says to IGNORE the revised figure wants neither.
                   (r"(?<!ignore )(?<!ignore the )revised[^.?]{0,30}"
                    r"(?:gap|difference|versus|against|and the value)"
                    r"|(?:gap|difference)[^.?]{0,30}revised", "revised_gap"),
                   # "awarded value LESS the total billed" is the same
                   # question as "the gap between awarded and billed"; the
                   # subtraction can be written as a preposition.
                   (r"gap|difference|less than|shortfall|under-?run|minus"
                    r"|exceed|versus|\bvs\b|against"
                    r"|awarded[^.?]{0,30}\bless\b|\bless\b\s+the\s+(?:total\s+)?bill",
                    "gap"),
                   (r"(?<!ignore )(?<!ignore the )\brevised\b", "revised"),
                   (r"variation", "variations"),
                   (r"awarded|award\b|sanction", "awarded"),
                   (r"billed|executed|actually", "executed")],
    "boq_line": [(r"quantity|\bqty\b", "quantity"), (r"\brate\b", "rate"),
                 (r"amount|value|total", "amount")],
    "bank_txn": [(r"single largest|largest transaction|biggest transaction"
                  r"|deposit or withdrawal|either direction", "amount"),
                 (r"withdraw|paid out|outflow|debit", "withdrawal"),
                 (r"deposit|received|inflow|credit|came in", "deposit"),
                 (r"balance", "balance")],
    "bank_year": [(r"net (?:movement|figure|change|cash)|movement in cash"
                   r"|deposits? (?:less|minus)|subtract[^.?]{0,30}withdraw", "net_movement"),
                  (r"\bopening\b", "opening"),
                  (r"closing|balance", "closing"),
                  (r"deposit|received|inflow", "deposits"),
                  (r"withdraw|outflow|paid out", "withdrawals")],
    "ledger_account": [(r"signed|negative if|which side|debit or credit",
                        "closing_signed"),
                       (r"closing|balance", "closing"), (r"total|sum", "total")],
    "ledger_line": [(r"balance", "balance"), (r".", "amount")],
}


# The words that mean ONE ROW of each table, so "how many X" can be told apart
# from "how many <thing counted in a column of X>".
_ROW_NOUN = {
    "bond": r"bonds?|guarantees?|\bbgs?\b",
    "compliance": r"matri(?:x|ces)|checklists?|tenders?",
    "iso_cert": r"certificates?|certifications?|registrations?",
    "audit": r"audits?",
    "dossier": r"dossiers?|bids?|submissions?|tenders?",
    "business_unit": r"units?|divisions?",
    "fin_line": r"lines?|items?",
    "ra_bill": r"bills?|invoices?",
    "final_bill": r"bills?|contracts?",
    "boq_line": r"items?|lines?",
    "bank_txn": r"transactions?|entries|lines?|payments?",
    "ledger_line": r"entries|lines?|postings?|vouchers?",
    "ledger_account": r"accounts?",
    "director": r"directors?|board members?",
    "cv": r"personnel|people|staff|employees|engineers|managers|key personnel",
    "reference_letter": r"letters?|references?|testimonials?",
    "variation": r"variation orders?|variations?|amendments?",
    "credit_note": r"credit notes?",
    "order_line": r"contracts?|order book (?:lines?|entries)",
    "quarter": r"quarters?",
    "ar_balance": r"lines?|items?",
    "ar_pl": r"lines?|items?",
    "company_cert": r"certificates?|copies|records",
    "credential": r"credentials?|certificates?",
    "work": r"works?|projects?|contracts?|assignments?|jobs?|packages?",
    "asset": r"assets?|items?|machines?|units?",
    "person": r"people|persons?|staff|employees|engineers",
    "invoice": r"invoices?|bills?|receipts?|entries|lines?",
    "client": r"clients?|accounts?|authorit(?:y|ies)",
}


# Columns that state a REQUIREMENT or a RATE rather than a quantity: the same
# figure appears on every document of the type, so summing them is meaningless.
_STATED = {"staff_min", "turnover_req", "owned_assets", "personnel",
           "guarantee_pct", "emd_pct", "gst_pct", "retention_pct",
           "relevant_works", "stamp_value"}
_AGG_WORD = (r"\btotal(?:led|ling)?\b|in total|altogether|combined"
             r"|\bsum(?:s|med|ming)?\b"
             r"|aggregate|added up|add up|across all|across every|for every")


# Columns whose VALUES a question quotes verbatim: an issuing bank, a work
# description, an asset make, a certification body, a business unit. Rather than
# a regex per column, the values are read out of the store and matched against
# the question -- so a corpus with different banks, makes or units still works,
# and a question naming one nobody anticipated is still filtered.
_CATEGORICAL = {
    "bond": ("bank", "work", "status"),
    "dossier": ("work", "client"),
    "compliance": ("work",),
    "iso_cert": ("body", "standard"),
    "audit": ("auditor", "type", "standard"),
    "asset": ("make", "type", "location", "ownership", "condition"),
    "invoice": ("client", "status"),
    "cv": ("qualification", "designation", "business_unit", "wage_group"),
    "reference_letter": ("client", "validity", "category", "role"),
    "company_cert": ("client", "category"),
    "business_unit": ("unit", "scale"),
    "ledger_account": ("account",),
    "final_bill": ("client",),
    "ra_bill": ("client",),
}


def _match_values(gr, entity, q, taken):
    """Filters for every categorical column whose value the question quotes.

    Longest value first, so "Kalinga National Bank" is not matched as "Bank",
    and case-insensitively, because half these questions are typed in a hurry.
    """
    out = []
    for col in _CATEGORICAL.get(entity, ()):
        if col in taken:
            continue
        vals = {r.get(col) for r in gr.entities.get(entity, []) if r.get(col)}
        best = None
        for v in sorted((str(x) for x in vals), key=len, reverse=True):
            if len(v) < 3:
                continue
            m = re.search(r"(?<![\w])" + re.escape(v) + r"(?![\w])", q, re.I)
            if m:
                best = (v, m.start())
                break
        if best is None:
            continue
        # "issued by a body OTHER THAN TUV India" names the value in order to
        # exclude it. Read as an equality that inverts the question.
        before = q[max(0, best[1] - 30):best[1]]
        neg = re.search(r"\b(?:other than|apart from|besides|excluding|except"
                        r"|not|rather than|aside from)\b[\s\w]{0,12}$", before, re.I)
        out.append((col, "ne" if neg else "eq", best[0]))
    return out


# Entities whose rows are stamped with a year, so a movement between two of
# them is meaningful.
# Which tables a year-on-year movement can be asked of used to be a written
# list, and it left out dossier_standing and segment -- both of which hold one
# row per financial year and are asked about exactly that way. The store knows:
# a table carries a year or it does not.


def _named_work(gr, q):
    """The completed work the question names, by package number or by title.

    Package numbers are the one globally unique join key in this corpus -- work
    TITLES are not, with four different "RCC Bridge" works across four states --
    so the number is tried first and the title only where it identifies one row.
    """
    m = re.search(r"\bPkg[\s\-_]*(\d{1,3})\b", q, re.I)
    if m:
        want = int(m.group(1))
        for r in gr.entities.get("work", []):
            mm = re.search(r"Pkg[\s\-_]*(\d{1,3})", r.get("work") or "", re.I)
            if mm and int(mm.group(1)) == want:
                return r["work"]
    # Title plus state, where the package number is deliberately withheld:
    # "the RCC Bridge project in Gujarat, never mind the package number". Four
    # works are called RCC Bridge and the state separates them.
    for r in gr.entities.get("work", []):
        t = r.get("work") or ""
        base = re.sub(r"\s*[\u2014\u2013-]\s*[A-Za-z ]+Pkg[\s\-_]*\d+\s*$", "", t).strip()
        st = r.get("state")
        if not (len(base) > 6 and st):
            continue
        if re.search(r"(?<![\w])" + re.escape(base) + r"(?![\w])", q, re.I) and \
                re.search(r"(?<![\w])" + re.escape(st) + r"(?![\w])", q, re.I):
            same = [o for o in gr.entities.get("work", [])
                    if (o.get("work") or "").startswith(base) and o.get("state") == st]
            if len(same) == 1:
                return same[0]["work"]
    best = None
    for r in gr.entities.get("work", []):
        t = r.get("work") or ""
        base = re.sub(r"\s*[\u2014\u2013-]\s*[A-Za-z ]+Pkg[\s\-_]*\d+\s*$", "", t).strip()
        for cand in (t, base):
            if len(cand) > 8 and re.search(r"(?<![\w])" + re.escape(cand) + r"(?![\w])",
                                           q, re.I):
                if best is None or len(cand) > len(best[0]):
                    best = (cand, t)
    if not best:
        return None
    # A title that matches more than one work identifies none of them.
    hits = [r["work"] for r in gr.entities.get("work", [])
            if (r.get("work") or "").startswith(best[0])]
    return best[1] if len(hits) == 1 else None


def _named_works(gr, q):
    """Every completed work the question names, in the order they appear.

    Package numbers are globally unique and work titles are not -- four "RCC
    Bridge" works exist across four states -- so a title only counts where it
    resolves to exactly one row.
    """
    found = []
    for m in re.finditer(r"\bPkg[\s\-_]*(\d{1,3})\b", q, re.I):
        want = int(m.group(1))
        for r in gr.entities.get("work", []):
            mm = re.search(r"Pkg[\s\-_]*(\d{1,3})", r.get("work") or "", re.I)
            if mm and int(mm.group(1)) == want and r["work"] not in found:
                found.append(r["work"])
                break
    return found


def _named_person(gr, q):
    """A person named in full, or by a part-name unique among the 39."""
    names = [r.get("name") for r in gr.entities.get("person", []) if r.get("name")]
    for nm in sorted(names, key=len, reverse=True):
        if re.search(r"(?<![\w])" + re.escape(nm) + r"(?![\w])", q, re.I):
            return nm
    for part in (0, -1):
        owners = {}
        for nm in names:
            bits = nm.split()
            if len(bits) > 1:
                owners.setdefault(bits[part].lower(), []).append(nm)
        found = [v[0] for k, v in owners.items()
                 if len(v) == 1 and len(k) > 3
                 and re.search(r"(?<![\w])" + re.escape(k) + r"(?![\w])", q, re.I)]
        if len(found) == 1:
            return found[0]
    return None


_SENT_END = re.compile(r"[.?!](?:\s|$)")


def _same_sentence(q, a, b):
    """Whether two character positions fall in one sentence of the question."""
    lo, hi = (a, b) if a <= b else (b, a)
    return not _SENT_END.search(q, lo, hi)


def _store_value(gr, entity, col, *words):
    """The value this column ACTUALLY holds that one of `words` names.

    A synonym written into a rule -- "hired" for equipment not owned -- is a
    guess about the corpus's vocabulary. The register says "leased", and
    filtering on the guess emptied the table, which reads as a confident zero
    rather than as a miss. Asking the store which of the synonyms it uses costs
    nothing and cannot be wrong about its own data.
    """
    vals = {str(r.get(col)) for r in gr.entities.get(entity, ())
            if r.get(col) is not None}
    for w in words:
        for v in vals:
            if w.lower() == v.lower() or w.lower() in v.lower().split():
                return v
    return None


def _named_category(gr, q):
    """A work category named in the question, in either rendering.

    The corpus writes "Bridges & Flyovers" in the annual report and the
    workbooks and "Bridges Flyovers" on the completion certificates; questions
    use both, and either spelling has to reach the same rows.
    """
    cats = {r.get("category") for r in gr.entities.get("work", []) if r.get("category")}
    for c in sorted(cats, key=len, reverse=True):
        parts = [re.escape(w) for w in c.split()]
        pat = r"(?<![\w])" + r"\s*(?:&|and)?\s*".join(parts) + r"(?![\w])"
        if re.search(pat, q, re.I):
            return c
    return None


def _first(pairs, text):
    for name, pat in pairs:
        if re.search(pat, text, re.I):
            return name
    return None


# Entities no named shape can reach. The graph answers ONLY for these.
#
# Measured, and this is the load-bearing constraint: letting the graph answer
# for `work` cost 2.1 question-equivalents and for `account` 1.9, because it
# competed with tested shapes and with the fallback ladder and lost both times.
# A confident wrong number scores zero; the ladder's corpus-typical guess earns
# partial credit. So the graph is worth having exactly where the alternative is
# nothing at all -- never where something already answers.
# No named shape reaches any of these -- all 23 are scoped to a client and read
# from the works or the receivables. Here the graph is not competing with a
# tested path, it is the only path.
# `account` is the trial balance. It was left out of this set, so a question
# that resolved to it was refused before any plan was built -- the graph is
# only consulted where no shape ran, and no shape reads the trial balance at
# all, so those questions had no path to an answer.
_NO_SHAPE = {"account",
             "asset", "boq_item", "bond", "compliance", "iso_cert", "audit",
             "dossier", "business_unit", "fin_line", "ra_bill", "final_bill",
             "boq_line", "bank_txn", "bank_year", "ledger_account",
             "ledger_line", "director", "ar_line",
             "company_cert", "cv", "credential", "reference_letter",
             "dossier_standing", "invoice",
             "segment", "seven_year", "ageing", "principal_client", "order_book",
             "ar_balance", "ar_pl", "quarter", "variation", "credit_note",
             "order_line"}

# Works are covered by 23 shapes -- but every one of them is scoped to a single
# client. A question about the WHOLE estate ("across the completed-works record,
# how many have no reference letter", "combined value of everything graded
# Good", "our total as JV Partner") has no client to resolve, so no shape can
# run and the ladder can only guess. That is a no-shape case too, and the only
# one where letting the graph answer for `work` is not competing with anything.
_ESTATE = (r"across (?:the|our|all)|whole (?:completed|estate|record|portfolio|book)"
           r"|entire (?:completed|estate|record|portfolio|book)|every completed work"
           r"|all (?:our |of our )?(?:completed )?works|company-?wide|in total across"
           r"|overall(?: total)?|forget one client|any client|all clients")


def plan(db, gr, question, answer_type=None, client=None, category=None,
         estate=False, sch=None):
    """-> {entity, filters, fn, field} or None when the question is not placeable."""
    q = _drop_contrast(normalize.fiscal_years(question))
    at = (answer_type or "").lower()

    # WHICH TABLE. Two independent votes, because neither source is reliable
    # alone. The schema matcher reads the question against the DATA MODEL --
    # table names, column names, and the values the categorical columns
    # actually hold -- so it needs no vocabulary written down and reaches
    # questions nobody anticipated. The pattern list below encodes wording that
    # names a table without using any of its own words ("gross block", "ageing
    # register"), which the schema cannot know. Summing the two lets either
    # carry a question the other misses, and agreement settles the rest.
    entity = _first(_ENTITY, q)
    if sch is not None:
        allowed = set(_NO_SHAPE) | {"work"}
        ranked = sch.rank(q, allowed=allowed)
        scored = [(s + (1.0 if e == entity else 0.0), e) for s, e in ranked]
        if entity in allowed and not any(e == entity for _, e in ranked):
            scored.append((1.0, entity))
        # Only where the pattern list has nothing: the two disagree often
        # enough that overriding a positive match measurably loses ground.
        if scored and entity is None:
            entity = max(scored)[1]
    # A business unit named outright beats any pattern: "the head-count of the
    # Special Projects Division" names one of six and nothing else in the
    # estate answers it. Checked against the store rather than a word list, so
    # a corpus with different units still works.
    # A ledger account named outright, checked against the chart of accounts
    # rather than a word list: "the closing balance of the Output Gst Payable
    # account" names one of 28 and nothing else in the estate answers it.
    if entity in (None, "bank_year", "bank_txn", "account", "work", "client"):
        for r in gr.entities.get("ledger_account", []):
            nm = re.sub(r"\s*\((?:ASSET|LIABILITY|INCOME|EXPENSE|EQUITY)\)\s*$", "",
                        str(r.get("account") or ""), flags=re.I).strip()
            if len(nm) > 6 and re.search(
                    r"(?<![\w])" + re.escape(nm).replace(r"\ ", r"\s+") + r"(?![\w])",
                    q, re.I):
                entity = "ledger_account"
                break

    if entity in (None, "dossier", "compliance", "work", "person", "client"):
        for u in gr.entities.get("business_unit", []):
            head = re.split(r"\s*&\s*|\s+\(", u["unit"])[0]
            if len(head) > 6 and re.search(r"\b" + re.escape(head) + r"\b", q, re.I):
                entity = "business_unit"
                break
    if entity is None and estate and re.search(_WORK_EVIDENCE, q, re.I):
        entity = "work"                        # estate-wide, and about the works
    if entity == "work":
        # The 23 shapes are all scoped to a client and all sum a portfolio, so
        # a question about ONE work, or about a category, a year, a state or a
        # person's own deliveries, has nothing that can run -- which is why
        # this is reached at all: the graph is only consulted after every named
        # shape has returned nothing.
        #
        # The condition is that the query be SPECIFIC. A plan with no filter at
        # all is "every work we have ever done", which is almost never what an
        # unplaceable question wanted, and answering it confidently costs more
        # than the fallback ladder's corpus-typical guess. So `work` is allowed
        # through here and checked for a real filter at the end.
        pass
    elif entity not in _NO_SHAPE:
        # Either the question is about something a shape already covers, or the
        # entity was not named at all. Both are better served by the ladder.
        return None
    fn = _first(_FN, q)

    # Which COLUMN, before which reduction: whether `how many` counts rows or
    # sums a column depends on what column the question named.
    # WHICH COLUMN. The column whose NAME the question matches is the strongest
    # evidence available and needs nothing written down. The cue list is kept
    # only for what a column name cannot express -- "how many are NOT met" is
    # the `not_complied` column, and no amount of reading `complied` gets there.
    # The columns this question is using to SELECT rows. Computed here, ahead of
    # the filters themselves, because the column being asked for is never one of
    # them and excluding them is what makes the match usable at all.
    selecting = set()
    if sch is not None:
        selecting = {h[0] for h in sch.value_hits(entity, q)}
    if client:
        selecting.add("client")
    if category:
        selecting.add("category")
    if re.search(r"(?:\b|FY\s*)(?:19|20)\d{2}", q):
        selecting |= {"year", "expiry_year", "acquired"}
    # Cues first, because where one applies it encodes a distinction a column
    # name cannot ("how many are NOT met"). The schema matcher then covers the
    # columns nobody wrote a cue for -- measured net-neutral on a held-out set,
    # which is the right trade for a mechanism whose whole purpose is the
    # questions nobody anticipated.
    # Whether the question asks for a PART OF A WHOLE, which the ratio below
    # can express for any table. Computed here because the answer-type guard
    # runs before the filters that define the part exist.
    share_q = bool(re.search(
        r"(?:share|percentage|proportion|fraction) of\s+(?:our |the |your |all )?"
        r"(?:\d[\d,]*\s+)?(?:total|overall|entire|combined|whole|aggregate|all\b"
        r"|\w+\s+(?:on|in|at)\b|\w+\b)"
        r"|out of (?:the |our )?total"
        r"|accounted for by[^.?]{0,60}\b(?:total|across all)\b"
        r"|\b(?:total|across all)\b[^.?]{0,60}accounted for by", q, re.I))
    field, cued, cue_at = None, False, 0
    for pat, f in _FIELD_CUES.get(entity, ()):
        m = re.search(pat, q, re.I)
        if m:
            field, cued, cue_at = f, True, m.start()
            break
    if field is None and sch is not None:
        field = sch.best_column(entity, q, exclude=selecting)
    if field is None:
        field = _FIELD.get(entity, "value")
    if at == "days" and entity == "iso_cert":
        field = "validity_days"

    # answer_type is the strongest signal about the reduction, and it overrides
    # loose wording: "how much plant do we have" reads as a sum but a `count`
    # question wants the number of items.
    # `count` normally means count the ROWS -- "how many bonds do we hold". But
    # several of these tables carry a count IN a column: minor non-conformities
    # per audit, head-count per business unit, requirements complied per matrix.
    # "How many minor NCs were raised in total" counted 20 audits instead of
    # summing 15 NCs. Where the question named a column and asked for a total,
    # the answer is the sum of that column.
    _COUNT_COL = {"minor", "major", "minor_ncs", "major_ncs", "headcount",
                  "complied", "not_complied", "requirements", "relevant_works",
                  "staff_min", "owned_assets", "personnel", "validity_days",
                  "ra_count", "quantity", "experience_years", "tenure_days",
                  "defect_liability_days", "works_led", "credentials",
                  "categories_led", "clients_served", "audits_done",
                  "director_count", "contracts_in_execution", "credit_notes",
                  "variation_orders", "cert_copies", "registrations",
                  "annexures", "requirements", "complied", "not_complied"}
    # "HIGHEST qualification" is the name of a column, not an instruction to
    # take a maximum. A superlative directly in front of a word the filtered
    # column is called is part of that column's name.
    _sup_m = re.search(r"\bsmallest\b|\blowest\b|\bfewest\b|\bleast\b"
                       r"|\blargest\b|\bbiggest\b|\bhighest\b|\bmost\b"
                       r"|\bmaximum\b|\bminimum\b", q, re.I)
    if _sup_m:
        # `selecting` is the set of columns this question uses to pick rows,
        # computed above; `filters` does not exist yet at this point.
        after = q[_sup_m.end():_sup_m.end() + 24].lower()
        for col in selecting:
            if any(w and w in after for w in re.split(r"[_\s]+", col) if len(w) > 3):
                _sup_m = None
                break
    counts_rows = False
    if at == "count" and _sup_m and field in _COUNT_COL:
        # "smallest business unit by head-count -- how many people" says both
        # "how many" and "smallest". The superlative is the reduction; the
        # "how many" only says the answer is a count.
        fn = ("min" if re.search(r"smallest|lowest|fewest|least|minimum", q, re.I)
              else "max")
    elif at == "count" and fn in ("min", "max", "median", "mean"):
        pass                    # "smallest business unit by head-count" is a min
    elif at == "count" and fn not in ("distinct",):
        # "How many BONDS do we hold" counts rows; "how many MINOR NCS were
        # raised" sums a column. What separates them is whether the noun being
        # counted is the table's own row -- so each table declares the words
        # that mean one of its rows, and anything else that resolves to a count
        # column is a sum.
        # A bar the document STATES, repeated identically on every copy --
        # the minimum staff count, the turnover requirement, the guarantee
        # percentage. Forty matrices quoting a ten-person minimum do not add up
        # to four hundred; the answer is the bar. Only an explicit aggregating
        # word overrides that.
        rownoun = _ROW_NOUN.get(entity)
        # A column named EXPLICITLY beats the row noun. "How many RA bills were
        # raised against contract 73, per the final bill" says "bills" twice and
        # means the `ra_count` column of one final bill, not a count of final
        # bills.
        #
        # But only where the column is named in the SAME SENTENCE as the "how
        # many". "Only ONE of our two formats states the EMD amount together
        # with a percentage figure. How many of our 40 matrices use that
        # format?" describes the column in one sentence and asks for a count of
        # documents in the next; the column name there is background, not the
        # thing being counted.
        _rn = rownoun and re.search(
            r"(?:how many|number of|(?<!head-)(?<!head )count of)"
            r"\s+(?:\w+\s+){0,6}?(?:" + rownoun + r")", q, re.I)
        counts_rows = fn != "min" and bool(_rn) and not (
            cued and _same_sentence(q, cue_at, _rn.start()))
        if rownoun is not None or fn not in ("min", "max"):
            fn = "count" if (counts_rows or field not in _COUNT_COL) else "sum"
    elif at == "money" and fn in ("count", "distinct", None):
        fn = "sum"
    elif at == "days":
        # A day count is a number held in a column, never a row count.
        fn = "sum" if fn in ("count", "distinct", None) else fn
    elif at == "percent":
        # A share of one thing in another needs a ratio -- built below, where
        # the two lines have been identified. A percentage the document STATES
        # is just a column. Anything else this cannot express.
        if not field.endswith("_pct") and field not in ("guarantee_pct", "emd_pct"):
            # The UNIT of the answer says which table can hold it. "For tender
            # RFP-132004559, what does the EMD amount work out to as a
            # percentage of the bid value" reads as a tender dossier, and the
            # dossiers do not record a percentage at all -- the compliance
            # matrix for the same tender states it outright. Where a
            # better-scoring table has a percentage column its own cue list
            # picks for this question, that table answers it.
            for _sc, _e in (ranked if sch is not None else ()):
                if _e == entity:
                    break
                _cols_e = set(gr.entities.get(_e, [{}])[0] or ())
                for _pat, _f in _FIELD_CUES.get(_e, ()):
                    if _f in _cols_e and _f.endswith("_pct") \
                            and re.search(_pat, q, re.I):
                        entity, field, cued = _e, _f, True
                        break
                if field.endswith("_pct"):
                    break
        if field.endswith("_pct") or field in ("guarantee_pct", "emd_pct"):
            fn = "max" if fn in ("count", "distinct", None) else fn
        elif share_q:
            # A share of the whole, which the part-over-whole ratio below can
            # express for any table. Without this the guard refused every one
            # of them before the filters that define the part had been built.
            fn = "sum"
        elif entity not in ("fin_line", "ar_line", "account"):
            return None
        else:
            fn = "sum"
    if not fn:
        return None

    filters = []

    # Only where the entity actually carries a client. A business unit does
    # not, and filtering on a column that is not there empties the table --
    # "the head-count of the Special Projects Division" resolved `National
    # Special Projects Office` as a client and returned nothing at all.
    if client and any(client_key in (r or {}) for r in
                      gr.entities.get(entity, [])[:1] for client_key in ("client",)):
        filters.append(("client", "eq", client))
    if category and entity == "work":
        # classify mines the category without regard to whether the question is
        # selecting it or ruling it out. "Every completed work across the whole
        # estate EXCEPT the Small Buildings category" names one and wants the
        # other 154 works.
        at_char = q.lower().find(category.split()[0].lower())
        before = q[max(0, at_char - 30):max(0, at_char)] if at_char > 0 else ""
        neg = re.search(r"\b(?:except|excluding|other than|apart from|besides"
                        r"|not|aside from|leaving out|bar)\b[\s\w]{0,14}$",
                        before, re.I)
        filters.append(("category", "ne" if neg else "eq", category))

    # a year, when the question names exactly one
    # "FY2022-23" carries no word boundary before the digits, so a plain year
    # pattern finds nothing in exactly the questions that name two of them.
    # Not four digits sitting inside an identifier: `PMI-200025` contains
    # `2000`, and reading it as a year filtered a credential table that has no
    # year column down to nothing.
    # Not the edition year of a management standard either: "ISO 14001:2015"
    # names the standard, and read as a date it emptied the audit table.
    years = sorted({int(y) for y in
                    re.findall(r"(?<![\d-])(?:\b|FY\s*)((?:19|20)\d{2})(?!\d)",
                               normalize.mask_epoch(
                                   normalize.mask_refs(
                                       normalize.mask_standards(q))))})
    # Whether this table is even dated. Filtering a CV on a year empties it --
    # a person has no year -- and an empty selection is a confident zero.
    _cols = set(gr.entities.get(entity, [{}])[0] or ())
    # The fiscal-year-end convention -- "for the year ended 31 March 2021" is
    # the FY2020-21 statement -- is applied by normalize.fiscal_years on the way
    # in, so `q` already spells it the store's way. Doing it a second time here
    # would put every such question a year EARLY.
    if len(years) == 1 and (_cols & {"year", "expiry_year", "acquired"}):
        if entity == "account":
            fy = [r["year"] for r in gr.entities["account"]
                  if str(years[0]) in str(r.get("year"))]
            if fy:
                filters.append(("year", "eq", fy[0]))
        elif entity == "asset":
            filters.append(("acquired", "eq", years[0]))
        else:
            filters.append(("year", "eq", years[0]))

    if entity == "asset":
        # Every rule below is an APPROXIMATION of a column the question may
        # have named outright. Where the schema matched a value of that column
        # exactly -- `selecting` holds those columns -- the approximation is
        # skipped: "how many 'Hydraulic Crane 50T' units" was being reduced to
        # type contains "Crane" and counted all three crane models.
        if "ownership" not in selecting:
            # Whichever word the register itself uses. Hardcoding "hired"
            # against a store that says "leased" filtered to nothing, and an
            # empty count is a confident zero.
            own = _store_value(gr, "asset", "ownership", "hired", "leased", "rented")
            if re.search(r"\bowned\b", q, re.I):
                filters.append(("ownership", "eq",
                                _store_value(gr, "asset", "ownership", "owned") or "owned"))
            elif own and re.search(r"\bhired\b|\bleased\b|\brented\b|\bon hire\b", q, re.I):
                filters.append(("ownership", "eq", own))
        if re.search(r"not safety|un-?certified|without safety|lack\w* safety", q, re.I):
            filters.append(("safety_certified", "eq", False))
        elif re.search(r"safety[- ]certified|safety certification", q, re.I):
            filters.append(("safety_certified", "eq", True))
        if "condition" not in selecting:
            for cond in ("new", "good", "fair", "poor"):
                if re.search(r"\bcondition\b[^.?]{0,20}\b" + cond + r"\b|\b" + cond
                             + r"\b[^.?]{0,12}condition", q, re.I):
                    filters.append(("condition", "eq", cond))
                    break
        if "location" not in selecting:
            for st in _STATES:
                if re.search(r"\b" + re.escape(st) + r"\b", q, re.I):
                    filters.append(("location", "eq", st))
                    break
        m = re.search(r"\b(excavator|crusher|batching plant|grader|roller|crane"
                      r"|tipper|paver|loader|compactor|dozer)s?\b", q, re.I)
        if m and "type" not in selecting:
            filters.append(("type", "contains", m.group(1)))
        if re.search(r"acquisition year|year acquired|average age|how old", q, re.I):
            field = "acquired"

    if entity == "work":
        for g in ("Very Good", "Excellent", "Satisfactory", "Good"):
            if re.search(r"\b" + g + r"\b", q, re.I) and not _neg_before(g, q):
                filters.append(("grading", "eq", g))
                break
        for st in _STATES:
            if re.search(r"\b" + re.escape(st) + r"\b", q, re.I):
                filters.append(("state", "eq", st))
                break
        if re.search(r"jv partner|joint venture|\bjv\b", q, re.I):
            filters.append(("role", "eq", "JV Partner"))
        elif re.search(r"\bas (?:a )?prime\b|\bprime[- ](?:contractor|role|led)"
                       r"|\bprime\b", q, re.I):
            filters.append(("role", "eq", "Prime"))
        if re.search(r"no reference|without a reference|lack\w* a? ?reference"
                     r"|un-?referenced", q, re.I):
            filters.append(("has_ref", "eq", False))
        elif re.search(r"with a reference|carry a reference|have a reference", q, re.I):
            filters.append(("has_ref", "eq", True))
        # a rupee bar, when the question sets one
        thr = normalize.threshold_from_text(q)
        if thr and re.search(r"above|over|at least|exceed|more than|greater than"
                             r"|or higher|north of|upward", q, re.I):
            filters.append(("value", "gte", thr))
        elif thr and re.search(r"below|under|less than|smaller than|beneath", q, re.I):
            filters.append(("value", "lte", thr))

    # A bar on a numeric column of ANY table, where the question names both the
    # column and the figure: "how many compliance matrices state a bid value
    # exceeding INR 60 Cr", "a dossier with a bid value between INR 120 Cr and
    # INR 130 Cr". The works rule above is the same idea written for one table;
    # this is it for the rest, and only where the question NAMES the column, so
    # a figure quoted for any other reason cannot bind.
    if entity != "work" and sch is not None and not any(
            f[1] in ("gte", "lte") for f in filters):
        bar_col = sch.best_column(entity, q, exclude=set(selecting))
        lo_hi = re.search(
            r"between\s+((?:INR|Rs\.?)?\s*[\d.,]+\s*(?:Cr|Crores?|Lakhs?|Lacs?)?)"
            r"\s+and\s+((?:INR|Rs\.?)?\s*[\d.,]+\s*(?:Cr|Crores?|Lakhs?|Lacs?)?)",
            q, re.I)
        # A bar the question means SEPARATES the rows. One that selects all of
        # them, or none, is a bar against the wrong column: "quote a minimum
        # average turnover requirement of INR 270 Cr" put 2,700,000,000 against
        # `requirements`, which counts 8 or 17, and emptied the table.
        def _separating(col, preds):
            vals = [r.get(col) for r in gr.entities.get(entity, ())]
            vals = [v for v in vals if isinstance(v, (int, float))
                    and not isinstance(v, bool)]
            if not vals:
                return False
            keep = [v for v in vals
                    if all(v >= x if o == "gte" else v <= x for o, x in preds)]
            return 0 < len(keep) < len(vals)

        if bar_col and bar_col in _cols and lo_hi:
            lo, hi = normalize.money(lo_hi.group(1)), normalize.money(lo_hi.group(2))
            if lo is not None and hi is not None and _separating(
                    bar_col, [("gte", min(lo, hi)), ("lte", max(lo, hi))]):
                filters.append((bar_col, "gte", min(lo, hi)))
                filters.append((bar_col, "lte", max(lo, hi)))
        elif bar_col and bar_col in _cols:
            thr = normalize.threshold_from_text(q)
            op = None
            if thr and re.search(r"exceed\w*|above|over|at least|more than"
                                 r"|greater than|or higher|north of", q, re.I):
                op = "gte"
            elif thr and re.search(r"below|under|less than|smaller than|beneath",
                                   q, re.I):
                op = "lte"
            if op and _separating(bar_col, [(op, thr)]):
                filters.append((bar_col, op, thr))

    if entity == "account" and "account" not in selecting:
        # Same rule as the plant register: a one-word approximation of a column
        # stands down where the schema matched a value of it outright. "The
        # 'Contract Revenue - Tunnels' account" names one of 28 accounts, and
        # `contains "Revenue"` reduced it to all twelve revenue lines.
        m = re.search(r"\b(revenue|payable|receivable|depreciation|bank|cash|capital"
                      r"|materials?|labour|salaries|tax)\b", q, re.I)
        if m:
            filters.append(("account", "contains", m.group(1)))

    # ------------------------------------------------ the estate entities
    if entity == "bond":
        m = re.search(r"\b(BND-\d+)\b", q, re.I)
        if m:
            filters.append(("bond_no", "eq", m.group(1).upper()))
        if re.search(r"expir\w*|lapse|runs? out|valid until|\bends?\b"
                     r"|in force (?:un)?til", q, re.I) and years:
            filters = [f for f in filters if f[0] != "year"]
            filters.append(("expiry_year", "eq", years[0]))

    if entity in ("compliance", "dossier", "final_bill", "ra_bill", "boq_line"):
        m = re.search(r"\b(RFP-\d+)\b", q, re.I)
        if m and entity in ("compliance", "dossier"):
            # The matrices key the tender as `tender_ref`, the dossiers as
            # `rfp_ref`; the question calls it the same thing either way.
            filters.append(("tender_ref" if entity == "compliance" else "rfp_ref",
                            "eq", m.group(1).upper()))
        m = re.search(r"contract\s*#?\s*(\d{2,3})\b", q, re.I)
        if m and entity in ("final_bill", "ra_bill", "boq_line"):
            filters.append(("contract", "eq", int(m.group(1))))
        m = re.search(r"\bRA\s*(?:bill\s*)?#?\s*(\d{1,2})\b", q, re.I)
        if m and entity == "ra_bill":
            filters.append(("ra", "eq", int(m.group(1))))
        m = re.search(r"\b(AR-\d{4}-\d+)\b", q, re.I)
        if m and entity == "ra_bill":
            filters.append(("bill_no", "eq", m.group(1).upper()))

    if entity in ("iso_cert", "audit"):
        m = re.search(r"\b(9001|14001|45001)\b", q)
        if m:
            filters.append(("standard", "contains", m.group(1)))
        m = re.search(r"\b(ORG-\d+)\b", q, re.I)
        if m:
            filters.append(("cert_no", "eq", m.group(1).upper()))
        if entity == "audit" and re.search(r"\bcompleted\b|carried out|have (?:been )?"
                                           r"(?:done|held)|so far", q, re.I):
            filters.append(("status", "eq", "completed"))
        elif entity == "audit" and re.search(r"\bscheduled\b|\bupcoming\b|\bdue\b",
                                             q, re.I):
            filters.append(("status", "eq", "scheduled"))
        m = re.search(r"\b((?:Dr|Mr|Ms|Mrs)\.?\s+[A-Z]\.?\s*\w+)", q)
        if m and entity == "audit":
            filters.append(("auditor", "contains", m.group(1).split()[-1]))
        if entity == "audit" and re.search(r"surveillance", q, re.I):
            filters.append(("type", "contains", "Surveillance"))
        elif entity == "audit" and re.search(r"initial", q, re.I):
            filters.append(("type", "contains", "Initial"))

    if entity == "business_unit":
        for u in gr.entities.get("business_unit", []):
            head = u["unit"].split(" &")[0].split(" (")[0]
            if re.search(r"\b" + re.escape(head) + r"\b", q, re.I):
                filters.append(("unit", "eq", u["unit"]))
                break
        m = re.search(r"\b(enterprise|mega|sme)\b", q, re.I)
        if m:
            filters.append(("scale", "eq", m.group(1).lower()))

    if entity in ("fin_line", "ar_line", "ledger_account", "ledger_line"):
        # The account is named in the question almost verbatim; match the
        # longest label that appears, so "Total Expenses" is not read as
        # "Other Expenses".
        # Labels carry punctuation the question does not -- "Contract Revenue
        # (EPC)", "Sub-contracting & Labour", "Profit Before Tax (A - B)". A
        # regex built from the label anchors a \b against a bracket and never
        # matches. Both sides are reduced to word runs instead, and the longest
        # label whose words appear consecutively wins, so "Total Expenses" is
        # not read as "Other Expenses".
        rows = gr.entities.get(entity, [])
        labels = sorted({r.get("account") for r in rows if r.get("account")},
                        key=lambda x: -len(x))
        drop = {"and", "the", "of", "a", "for", "in", "on", "to", "b", "epc"}

        def words(x):
            return [w for w in re.findall(r"[a-z0-9]+", x.lower()) if w not in drop]

        def run_in(hay, needle):
            return bool(needle) and any(hay[i:i + len(needle)] == needle
                                        for i in range(len(hay) - len(needle) + 1))

        qw = words(q)
        hit = next((lab for lab in labels if run_in(qw, words(lab))), None)
        if not hit:
            # No label quoted in full. "contract revenue" identifies "Contract
            # Revenue (EPC)" on its own, so a leading run of two words or more
            # is accepted where it fits exactly one label.
            for k in (4, 3, 2):
                part = [lab for lab in labels
                        if len(words(lab)) >= k and run_in(qw, words(lab)[:k])]
                if len(part) == 1:
                    hit = part[0]
                    break
        # A numbered account identifies a row outright, whether or not its NAME
        # is also quoted: "Account 2100 in the FY 2023 ledger".
        m = re.search(r"\baccount\s*(\d{3,4})\b", q, re.I)
        if m and entity in ("ledger_account", "ledger_line"):
            filters.append(("code", "eq", int(m.group(1))))
        elif hit:
            filters.append(("account", "eq", hit))

    if entity in ("bank_txn", "bank_year", "ledger_line", "ledger_account",
                  "fin_line", "ar_line", "ra_bill", "audit"):
        # A financial year is written both ways: "FY2021-22" and "2021".
        m = re.search(r"\bFY\s*(\d{4})\s*[-\u2013]\s*\d{2,4}", q, re.I)
        if m:
            filters = [f for f in filters if f[0] != "year"]
            filters.append(("year", "eq", int(m.group(1))))

    # A comparison the question states about the measured column: "bonds that
    # carry a NON-ZERO guaranteed amount", "works worth MORE THAN INR 20 Cr".
    # Without it the qualifier is silently dropped and every row is counted.
    # "positive if the account closes Dr, negative if Cr" is telling the answerer
    # how to SIGN the number, not asking for the rows above zero. A conditional
    # around it -- if / when / where / whether -- is the tell, and reading it as
    # a predicate emptied the ledger on every question that spelled the
    # convention out.
    _pos = re.search(r"non-?zero|greater than zero|above zero|positive"
                     r"|actually carr\w+|that state one|which state a", q, re.I)
    _instruction = _pos is not None and (
        # "positive IF the account closes Debit" -- a rule for signing the
        # answer, whose condition follows the word.
        re.match(r".{0,34}?\b(?:if|when|whether)\b", q[_pos.end():], re.I | re.S)
        # "give it as recorded (i.e. positive ...)" -- the rule is introduced.
        or re.search(r"(?:i\.e\.|\bie\b|as recorded|report it|give it|\bsigned\b"
                     r"|\bmeaning\b)[^?]{0,20}$", q[:_pos.start()], re.I))
    if _pos and not _instruction:
        filters.append((field, "gt", 0))
    elif re.search(r"of zero\b|\bzero rupees|equal to zero|amount of nil|\bnil\b", q, re.I):
        filters.append((field, "eq", 0))

    # Categorical values quoted in the question, for every column that has any.
    # Read off the store, so a bank, an asset make or a work category nobody
    # wrote down still filters -- and in either of the two renderings the
    # corpus uses for its own category names.
    taken = {f[0] for f in filters}
    claimed = []          # character spans already explained by another column
    if sch is not None:
        for col, val, lo, hi in sch.value_hits(entity, q):
            if col == "doc":
                continue
            if col in taken:
                # Already filtered on -- by classify, or by a rule above. The
                # text it matched is still SPOKEN FOR: without recording it,
                # the category "Irrigation" sitting inside the client name
                # "Irrigation & Waterways Dept, Govt of Rajasthan" looks like an
                # independent mention and gets its own filter, which empties
                # the table.
                claimed.append((lo, hi))
                continue
            # A value sitting INSIDE a value another column already matched is
            # not an independent mention. The category "Irrigation" lives inside
            # the client "Irrigation & Waterways Dept, Govt of Rajasthan", and
            # filtering on both empties the table.
            if any(not (hi <= a or lo >= b) for a, b in claimed):
                # Claimed by a longer value on another column. Mark it taken so
                # the older matcher below does not put it back.
                taken.add(col)
                continue
            claimed.append((lo, hi))
            at_pos = q.lower().find(str(val).lower())
            before = q[max(0, at_pos - 30):at_pos] if at_pos > 0 else ""
            neg = re.search(r"\b(?:other than|apart from|besides|excluding|except"
                            r"|not|rather than|aside from)\b[\s\w]{0,14}$", before, re.I)
            filters.append((col, "ne" if neg else "eq", val))
            taken.add(col)
    filters += _match_values(gr, entity, q, taken)

    # A bar the document STATES, repeated identically on every copy -- the
    # minimum staff count, the 5% guarantee, the INR 100 stamp paper. Forty
    # matrices quoting a ten-person minimum do not add up to four hundred; the
    # answer is the bar. Only an explicit aggregating word overrides that, and
    # it applies whatever unit the answer is in.
    # ... but "how many of our 40 matrices use that format" counts MATRICES.
    # The row-noun test above already decided that; the stated-bar shortcut has
    # to respect it, or a count of documents comes back as the bar they quote.
    if field in _STATED and not counts_rows and not re.search(_AGG_WORD, q, re.I) \
            and not (at == "count" and normalize.threshold_from_text(q)):
        return {"entity": entity, "filters": filters, "field": field,
                "fn": "min" if re.search(r"\blowest\b|\bsmallest\b", q, re.I) else "max"}

    # "How many of our 40 matrices state the EMD amount with a percentage" --
    # a count of the rows that RECORD the field at all. Only where the column
    # was named by a cue rather than guessed, and where the question names no
    # value for it: with a value the question is asking how many rows match it,
    # which the rule below answers.
    if at == "count" and counts_rows and cued \
            and normalize.threshold_from_text(q) is None \
            and re.search(r"\b(?:states?|stating|quotes?|quoting|carr(?:y|ies|ying)"
                          r"|records?|recording|shows?|showing|gives?|giving"
                          r"|cites?|citing|includ\w+|lists?|listing|specif\w+)\b",
                          q, re.I) \
            and any(r.get(field) is None for r in gr.entities.get(entity, ())):
        return {"entity": entity, "fn": "count", "field": field,
                "filters": filters + [(field, "exists", True)]}

    # "How many of the forty matrices quote a minimum turnover of INR 240 Cr" --
    # a count of the rows whose stated bar EQUALS a figure the question gives.
    # Without this the figure is read as the answer rather than as the filter.
    if at == "count" and field in _STATED:
        bar = normalize.threshold_from_text(q)
        if bar is not None and re.search(r"\bquote|\bstate|\brequire|\bdemand|\bset\b"
                                         r"|\bat\b|\bof\b", q, re.I):
            return {"entity": entity, "fn": "count", "field": field,
                    "filters": filters + [(field, "eq", bar)]}

    # Two numeric COLUMNS of the same rows, subtracted: "subtract total
    # withdrawals from total deposits". Distinct from subtracting two values of
    # one column -- here the rows are the same and the columns differ.
    if re.search(r"\bsubtract\b|\bminus\b|\bnet (?:figure|movement|of)\b|\bless\b",
                 q, re.I):
        # A key is numeric and is not a quantity. "For contract #73 ... awarded
        # value less the value billed" names `contract`, and subtracting a
        # contract NUMBER from an awarded value is not an answer. Columns being
        # used to select rows are excluded, which is the same rule that makes
        # the field chooser work.
        num_cols = [c for c in _cols
                    if c in (sch.numeric.get(entity, ()) if sch else ())
                    and c not in selecting
                    and not re.fullmatch(r"contract|ra|year|code|n|id|\w*_id"
                                         r"|\w*_no|acquired|expiry_year", c)]
        hit = []
        for c in sorted(num_cols, key=len, reverse=True):
            words = [w for w in re.split(r"[_\s]+", c) if len(w) > 3]
            if not words:
                continue
            m = re.search(r"(?<![\w])" + r"\s*".join(re.escape(w) for w in words)
                          + r"s?(?![\w])", q, re.I)
            if m and all(o[1] != c for o in hit):
                hit.append((m.start(), c))
        hit.sort()
        if len(hit) == 2:
            a, b = hit[0][1], hit[1][1]
            if re.search(r"subtract[^.?]{0,40}\bfrom\b", q, re.I):
                a, b = b, a
            signed = re.search(r"negative|signed|net figure|preserve the sign"
                               r"|in that order", q, re.I)
            return {"entity": entity, "fn": "sum", "field": a, "op": "diff",
                    "absolute": not signed, "filters": filters,
                    "subtrahend": filters, "field_b": b}

    # Two values of ONE categorical column, with a subtraction or a movement
    # asked for between them. The columns are read off the store rather than
    # listed: "how much did the minor-NC count change between Initial
    # Certification and Surveillance Audit 2" names two values of the audit
    # table's `type`, and no written list was ever going to have that in it.
    if re.search(r"\bsubtract\b|\bminus\b|\bless\b the|take away|deduct"
                 r"|(?:chang\w+|mov\w+|differ\w+|swing|delta|gap)[^.?]{0,20}between",
                 q, re.I):
        _cat = [c for c in ("category", "segment", "account", "client", "state")
                if c in _cols]
        # `selecting` is NOT excluded here. Everywhere else a column already
        # used to pick rows cannot be the one being asked for; here it is
        # exactly the pairing column, because naming both values is what makes
        # the question a subtraction.
        _cat += [c for c in sorted(sch.values.get(entity, {}) if sch else ())
                 if c not in _cat and c != "doc"]
        for col in _cat:
            if col not in _cols:
                continue
            vals = {r.get(col) for r in gr.entities.get(entity, []) if r.get(col)}
            hit = []
            for v in sorted((str(x) for x in vals), key=len, reverse=True):
                m = re.search(r"(?<![\w])" + re.escape(v).replace(r"\ ", r"\s*(?:&|and)?\s*")
                              + r"(?![\w])", q, re.I)
                if m and all(abs(m.start() - o[0]) > 3 for o in hit):
                    hit.append((m.start(), v))
            hit.sort()
            if len(hit) == 2:
                # "Subtract A from B" is B - A; "B subtract A" is also B - A.
                # But "how much did it CHANGE between A and B" is B - A too:
                # a movement runs from the first named to the second, so the
                # minuend is the one mentioned SECOND.
                a, b = hit[0][1], hit[1][1]
                if re.search(r"subtract[^.?]{0,40}\bfrom\b", q, re.I) or re.search(
                        r"(?:chang\w+|mov\w+|swing|delta|differ\w+|gap)"
                        r"[^.?]{0,20}between", q, re.I):
                    a, b = b, a
                base = [f for f in filters if f[0] != col]
                signed = re.search(r"negative|signed|in that order|net figure"
                                   r"|report it (?:as )?negative|keep the sign"
                                   r"|as a signed|preserve the sign", q, re.I)
                return {"entity": entity, "fn": fn if fn in ("sum", "mean") else "sum",
                        "field": field, "op": "diff", "absolute": not signed,
                        "filters": base + [(col, "eq", a)],
                        "subtrahend": base + [(col, "eq", b)]}
            # No break on a single hit. The columns are read off the store now,
            # so the first one the question touches is often not the pairing
            # one -- "for certificate ORG-1003 ... between Initial Certification
            # and Surveillance Audit 2" hits `cert_no` once before it reaches
            # `type` twice, and stopping there lost the pair.

    # "Which certification body issued the MOST of our 5 certificates, and how
    # many did it issue" -- the answer is the size of the biggest group, not
    # the maximum of any column. What marks it out is a superlative of NUMBER
    # ("the most", "the fewest", "the largest number of") over a categorical
    # column the question names.
    _grp = re.search(r"\bthe most\b|\bthe fewest\b|(?:largest|greatest|highest"
                     r"|smallest|lowest) number of|\bmost of (?:our|the)\b", q, re.I)
    if _grp and at == "count" and sch is not None:
        by = sch.name_column(entity, q, exclude=set(selecting) | {field})
        if by and by in _cols and not isinstance(
                next((r.get(by) for r in gr.entities.get(entity, ())
                      if r.get(by) is not None), None), (int, float)):
            return {"entity": entity, "filters": filters, "op": "groupby",
                    "by": by, "fn": "count", "field": field,
                    "dir": "min" if re.search(r"fewest|smallest|lowest", q, re.I)
                    else "max"}

    # "The completion date of the earliest-completed work, as the number of
    # DAYS AFTER 1 January 2010". The answer is a date, and the question gives
    # the origin to measure it from -- so the reduction picks the date and the
    # subtraction is arithmetic the question itself specifies.
    if at == "days":
        ep = re.search(r"\bdays?\s+(?:after|since|from|following|elapsed since)"
                       r"\s+(?:the\s+)?"
                       r"(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4}"
                       r"|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})", q, re.I)
        if ep is None:
            ep = re.search(r"(?:expressed|stated|given|reported|answer(?:ed)?)"
                           r"[^.?]{0,20}as\s+(?:the\s+)?(?:number of\s+)?days?"
                           r"\s+(?:after|since|from)\s+(?:the\s+)?"
                           r"(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4}"
                           r"|\d{4}-\d{2}-\d{2})", q, re.I)
        origin = normalize.parse_date(ep.group(1)) if ep else None
        dated = next((c for c in ("completed", "joined", "issue_date", "date",
                                  "letter_date", "initial_date", "valid_until")
                      if c in _cols), None)
        if origin and dated:
            late = re.search(r"most recent(?:ly)?|latest|newest|last\b", q, re.I)
            return {"entity": entity, "filters": filters, "op": "epoch",
                    "origin": origin.isoformat(), "field": dated,
                    "fn": "max" if late else "min"}

    # "The MOST RECENTLY issued bond", "the FIRST work to complete". A
    # superlative over a date picks a row; the question then asks for some
    # other column of that row. Which date column is whichever this table has.
    _sup = re.search(r"most recent(?:ly)?|latest|newest|last (?:to|one)"
                     r"|earliest|oldest|\bfirst\b|initial", q, re.I)
    if _sup:
        dated = next((c for c in ("issue_date", "completed", "date", "joined",
                                  "letter_date", "initial_date")
                      if c in _cols), None)
        if dated and field != dated:
            direction = ("min" if re.search(r"earliest|oldest|first|initial",
                                            _sup.group(0), re.I) else "max")
            return {"entity": entity, "filters": filters, "op": "argsel",
                    "by": dated, "dir": direction, "fn": "sum", "field": field}

    # Two works named and an interval asked for between them: "how many days
    # elapsed between the completion of A and the completion of B". Two rows,
    # one date column, one subtraction -- no reduction over a single table can
    # express it.
    if entity == "work" and at == "days":
        pair = _named_works(gr, q)
        if len(pair) == 2:
            return {"entity": "work", "filters": [], "fn": "sum",
                    "field": "completed", "key": "work",
                    "op": "datespan", "subjects": pair}

    # A movement between the CURRENT column and the PREVIOUS-year comparative
    # of the same row. "Per the financial statement for the year ended 31 March
    # 2025, by how much did Total Revenue from Operations change versus the
    # prior year" names one year, not two: the comparative is a column of that
    # year's statement, and the change is a subtraction across columns.
    if at in ("money", "count") and {"current", "previous"} <= _cols \
            and re.search(r"(?:chang\w+|mov\w+|differ\w+|grow\w+|fell|rose"
                          r"|increas\w+|decreas\w+|swing|delta)[^.?]{0,40}"
                          r"(?:versus|vs\.?|against|compared (?:to|with)|over)"
                          r"\s+(?:the\s+)?(?:prior|previous|preceding|comparative"
                          r"|last)\s+year", q, re.I):
        signed = re.search(r"negative|signed|in that order|net figure"
                           r"|keep the sign|preserve the sign", q, re.I)
        return {"entity": entity, "fn": "sum", "field": "current", "op": "diff",
                "absolute": not signed, "filters": filters,
                "subtrahend": filters, "field_b": "previous"}

    # Two financial years named, and a movement asked for between them.
    if len(years) == 2 and "year" in _cols and re.search(
            r"\bmove\w*|\bchange\w*|\bdifference\b|\bgap\b|between|year[- ]on[- ]year"
            r"|\bversus\b|\bvs\b|\bgrow\w*|\bfell?\b|\brose\b|\bincrease\w*"
            r"|\bdecrease\w*|\bswing\b|\bdelta\b", q, re.I):
        return {"entity": entity, "filters": [f for f in filters if f[0] != "year"],
                "fn": fn if fn in ("sum", "mean", "max", "min") else "sum",
                "field": field, "op": "delta", "years": years,
                "absolute": not re.search(r"negative if|signed|keep the sign", q, re.I)}

    # A margin: one stated line over another, in the same year.
    if at == "percent" and entity in ("fin_line", "ar_line", "account"):
        labels = sorted({r.get("account") for r in gr.entities.get(entity, [])
                         if r.get("account")}, key=lambda x: -len(x))
        drop = {"and", "the", "of", "a", "for", "in", "on", "to", "b", "epc"}
        qw = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in drop]

        def pos(lab):
            lw = [w for w in re.findall(r"[a-z0-9]+", lab.lower()) if w not in drop]
            for i in range(len(qw) - len(lw) + 1):
                if lw and qw[i:i + len(lw)] == lw:
                    return i
            return None
        named = sorted(((pos(l), l) for l in labels if pos(l) is not None))
        if len(named) >= 2:
            # WHICH WAY ROUND. Reading order is not the answer: "profit after
            # tax margin ON total revenue" is PAT/revenue, but "what percentage
            # OF total revenue was consumed BY cost of materials" is
            # materials/revenue and names the denominator first. The word in
            # front of a line says which side it is on -- `of` and `out of`
            # introduce the base, everything else introduces the measured part.
            first, second = named[0], named[1]
            # `pos` is a WORD index into the question, so the text before the
            # label has to be found in the question itself, not by slicing the
            # string at a word offset.
            at_char = q.lower().find(first[1].split(" (")[0].lower())
            before = q[max(0, at_char - 40):max(0, at_char)].lower() if at_char > 0 else ""
            base_first = bool(re.search(r"\b(?:of|out of|share of|percentage of"
                                        r"|proportion of|fraction of)\s*(?:the\s+)?$",
                                        before))
            num, den = (second, first) if base_first else (first, second)
            base = [f for f in filters if f[0] != "account"]
            return {"entity": entity, "fn": "sum", "field": field, "op": "ratio",
                    "filters": base + [("account", "eq", num[1])],
                    "denominator": base + [("account", "eq", den[1])]}

    # A SUBSET over the whole: "what share of our total guaranteed bond
    # exposure (across all 60 bonds) is accounted for by Union Trust Bank".
    # The same query twice, once filtered and once not, divided.
    #
    # It runs AFTER the two-line ratio above, and has to: "what share of Total
    # Expenses does 'Employee Benefit Expenses' represent" names two LINES of
    # one table, and the phrase "share of Total ..." is indistinguishable from
    # "share of the total". Tried first it took both of those and answered a
    # part-over-whole where a line-over-line was wanted.
    if at == "percent" and filters and share_q:
        # The measured quantity, never a percentage column: dividing one
        # percentage by another is not what "what share of the total" asks.
        _pcts = {c for c in _cols if str(c).endswith("_pct")}
        whole, named_amount = None, False
        for _pat, _f in _FIELD_CUES.get(entity, ()):
            if _f not in _pcts and re.search(_pat, q, re.I):
                whole, named_amount = _f, True
                break
        if whole is None and sch is not None:
            whole = sch.best_column(entity, q, exclude=set(selecting) | _pcts)
        if whole is None:
            whole = _FIELD.get(entity, "value")
        # Only where the filters really do select a subset. A question whose
        # only filter is the year is asking about that year as a whole.
        base = [f for f in filters if f[0] == "year"]
        # What is being shared out: an AMOUNT, or the rows themselves. "What
        # percentage of the 210 assets on the plant register are leased" counts
        # assets; "what share of our total guaranteed exposure" sums rupees.
        # ... and where the question NAMES the amount, that is what is being
        # shared out, even though the row noun is also there. "What share of
        # our total guaranteed bond EXPOSURE" says "bond", but the head of the
        # phrase is the exposure; counting bonds answered a different question.
        _rn = _ROW_NOUN.get(entity)
        share_of_rows = not named_amount and bool(_rn and re.search(
            r"(?:percentage|share|proportion|fraction) of\s+(?:the\s+|our\s+|all\s+)?"
            r"(?:\d[\d,]*\s+)?(?:\w+\s+){0,3}?(?:" + _rn + r")\b", q, re.I))
        if share_of_rows:
            return {"entity": entity, "fn": "count", "field": whole, "op": "ratio",
                    "filters": filters, "denominator": base}
        if whole not in _pcts and len(base) < len(filters):
            return {"entity": entity, "fn": "sum", "field": whole, "op": "ratio",
                    "filters": filters, "denominator": base}

    # A work named in a question about a document ABOUT that work selects the
    # document's row: "the reference letter on file for the Pipeline Laying
    # project in Delhi -- what value does it state".
    if entity in ("reference_letter", "company_cert") and \
            not any(f[0] == "work" for f in filters):
        w = _named_work(gr, q)
        if w:
            filters.append(("work", "eq", w))

    # A named work, which identifies exactly one row.
    if entity == "work":
        w = _named_work(gr, q)
        if w:
            filters.append(("work", "eq", w))
        lead = _named_person(gr, q)
        if lead and not any(f[0] == "lead" for f in filters) and re.search(
                r"\bled\b|\bhas led\b|\bran\b|\bmanaged\b|\bheaded\b"
                r"|as project manager|\bdelivered\b|\bsigned off\b"
                r"|\bunder\b [A-Z]", q, re.I):
            filters.append(("lead", "eq", lead))
        # A person's own deliveries span clients, so where the question scopes
        # by the PERSON a client inferred from elsewhere is a different
        # question. Applied to whatever put the lead filter there -- the schema
        # value matcher finds a person's name on its own and would otherwise
        # skip the block that drops the client.
        if any(f[0] == "lead" for f in filters) and re.search(
                r"\bhas led\b|\bled\b|as project manager|\bdelivered\b"
                r"|\bran\b|\bheaded\b|\bmanaged\b", q, re.I):
            filters = [f for f in filters if f[0] != "client"]
        if not any(f[0] == "category" for f in filters):
            c = _named_category(gr, q)
            if c:
                filters.append(("category", "eq", c))

    if fn == "distinct":
        # `distinct` needs the column whose VALUES are being counted, and the
        # question always names it -- "how many distinct certification BODIES",
        # "how many different lead AUDITORS". best_column cannot supply it: the
        # column wanted here holds strings, which is exactly what that rules
        # out. Asked of the table already chosen, so a named table keeps its
        # own columns; the works ladder below is what carries the questions
        # that name no table at all.
        named = sch.name_column(entity, q, exclude=selecting) if sch else None
        if named is not None and entity != "work":
            field = named
        elif re.search(r"client|authorit|department", q, re.I):
            entity, field = "work", "client"
        elif re.search(r"categor|type of work|classification", q, re.I):
            entity, field = "work", "category"
        elif re.search(r"state", q, re.I):
            entity, field = "work", "state"
        elif named is not None:
            field = named
        else:
            field = "client"

    seen, dedup = set(), []
    for f in filters:
        if f not in seen:
            seen.add(f)
            dedup.append(f)
    filters = dedup
    # A reduction over an ENTIRE table, with nothing selected, is an answer
    # only when the question asked for exactly that. Otherwise it is a lookup
    # whose subject was not found, and summing all 132 reference letters is a
    # confident wrong number where the ladder would have earned partial credit.
    # `min` and `max` are exempt: they are only chosen when the question
    # carries a superlative, and "which tender's matrix states the single
    # highest bid value" is a whole-table reduction by construction. What the
    # guard is really for is `sum` -- a lookup that found nothing must not come
    # back as the total of every row in the table.
    if not filters and fn not in ("count", "min", "max") \
            and len(gr.entities.get(entity, [])) > 20 \
            and not (estate or re.search(_ESTATE, q, re.I)
                     or re.search(_AGG_WORD, q, re.I)):
        return None
    return {"entity": entity, "filters": filters, "fn": fn, "field": field}
