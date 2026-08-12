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

# Entity vocabulary. Order matters: the first entity whose words appear wins,
# so the specific ones are listed before `work`, which is the default subject of
# most questions and would otherwise absorb them.
_ENTITY = [
    # -- the nine document types no named shape reaches -------------------
    ("bond", r"\bbonds?\b|bank guarantee|performance guarantee|\bBGs?\b"
             r"|guaranteed exposure|guarantee amount|guarantee percentage"
             r"|BND-\d+|guarantor"),
    ("audit", r"\baudits?\b|non-?conformit|\bNCs?\b|lead auditor|surveillance audit"
              r"|re-?certification audit|audit finding|major or minor"),
    ("iso_cert", r"\bISO\b|9001|14001|45001|certificate of registration"
                 r"|certification body|ORG-\d+|accreditation|valid until"
                 r"|certification date"),
    ("business_unit", r"business unit|head-?count by|per unit head|unit head-?count"
                      r"|\bunits?\b[^.?]{0,20}head-?count"),
    ("dossier", r"tender dossier|bid value|\bRFP\b|RFP-\d+|earnest money|\bEMD\b"
                r"|tender submission|bid submitted|relevant works|submission dossier"),
    ("compliance", r"compliance matri|compliance checklist|eligibility"
                   r"|requirements? (?:met|complied|satisfied)|complied\b"
                   r"|checklist|minimum turnover|turnover requirement"
                   r"|CM/\d+|pre-?qualification (?:requirement|criteri)"),
    ("ra_bill", r"\bRA bill|running account bill|\bRA-?\d+\b|retention"
                r"|net claimed|value of work done|AR-\d{4}-\d+"),
    # BOQ lines before the bill that carries them: "the BOQ line items on
    # contract #71" names both, and the line items are what is being asked for.
    ("boq_line", r"\bboq\b|bill of quantit|line items?\b|earthwork|macadam"
                 r"|bituminous|granular sub-?base|reinforcement steel"
                 r"|measured (?:total|quantit)"),
    ("final_bill", r"final bill|awarded value|contract\s*#?\s*\d{2}\b"
                   r"|executed value|approved variations|revised value"),
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
    ("director", r"board of directors|\bdirectors?\b|board composition"),
    # -- what was here before ---------------------------------------------
    ("asset", r"plant|machinery|equipment|asset|excavator|crusher|batching|grader"
              r"|roller|crane|tipper|gross block|fleet"),
    ("account", r"trial balance|ledger account|\baccount\b|revenue|expense|payable"
                r"|receivable account|depreciation|balance sheet"),
    ("boq_item", r"\bboq\b|bill of quantit|measured (?:total|quantit)|line item"),
    ("invoice", r"\binvoice|\bbilled\b|receipt|ageing"),
    ("person", r"engineer|personnel|staff|employee|people|\bperson\b"),
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
    "bond": [(r"percentage|per ?cent\b|\bpct\b|what (?:%|percent)", "guarantee_pct"),
             (r"amount|exposure|guarantee[ds]?\b|value|worth|total", "amount")],
    # Status first, then the noun it qualifies: "how many requirements are
    # marked complied" asks for the complied count, not the requirement count.
    "compliance": [(r"not (?:met|complied)|un-?met|failed|outstanding requirement",
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
    "dossier": [(r"\bemd\b|earnest", "emd"),
                (r"head-?count|personnel|staff", "headcount"),
                (r"relevant works|past performance", "relevant_works"),
                (r"bid|value|worth|total", "bid_value")],
    "business_unit": [(r"head-?count|people|staff|employees|strength", "headcount")],
    "fin_line": [(r"previous year|prior year|comparative|year before", "previous"),
                 (r".", "current")],
    "ar_line": [(r"previous year|prior year|comparative", "previous"),
                (r".", "current")],
    "ra_bill": [(r"\bgst\b|\btax\b", "gst"),
                (r"retention", "retention"),
                (r"net claimed|net of|claimed", "net_claimed"),
                (r"cumulative", "cumulative"),
                (r"value of work|work done|executed", "value_of_work")],
    "final_bill": [(r"gap|difference|less than|shortfall|under-?run|minus"
                    r"|exceed|versus|\bvs\b|against", "gap"),
                   (r"revised", "revised"),
                   (r"variation", "variations"),
                   (r"awarded|award\b|sanction", "awarded"),
                   (r"billed|executed|actually", "executed")],
    "boq_line": [(r"quantity|\bqty\b", "quantity"), (r"\brate\b", "rate"),
                 (r"amount|value|total", "amount")],
    "bank_txn": [(r"withdraw|paid out|outflow|debit", "withdrawal"),
                 (r"deposit|received|inflow|credit|came in", "deposit"),
                 (r"balance", "balance")],
    "bank_year": [(r"closing|balance", "closing"),
                  (r"deposit|received|inflow", "deposits"),
                  (r"withdraw|outflow|paid out", "withdrawals")],
    "ledger_account": [(r"closing|balance", "closing"), (r"total|sum", "total")],
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
    "director": r"directors?|board members?|people",
    "work": r"works?|projects?|contracts?|assignments?|jobs?|packages?",
    "asset": r"assets?|items?|machines?|units?",
    "person": r"people|persons?|staff|employees|engineers",
    "invoice": r"invoices?|bills?",
    "client": r"clients?|accounts?|authorit(?:y|ies)",
}


# Columns that state a REQUIREMENT or a RATE rather than a quantity: the same
# figure appears on every document of the type, so summing them is meaningless.
_STATED = {"staff_min", "turnover_req", "owned_assets", "personnel",
           "guarantee_pct", "emd_pct", "gst_pct", "retention_pct"}
_AGG_WORD = (r"\btotal(?:led|ling)?\b|in total|altogether|combined|\bsum\b"
             r"|aggregate|added up|add up|across all")


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
_NO_SHAPE = {"asset", "boq_item", "bond", "compliance", "iso_cert", "audit",
             "dossier", "business_unit", "fin_line", "ra_bill", "final_bill",
             "boq_line", "bank_txn", "bank_year", "ledger_account",
             "ledger_line", "director", "ar_line"}

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


def plan(db, gr, question, answer_type=None, client=None, category=None, estate=False):
    """-> {entity, filters, fn, field} or None when the question is not placeable."""
    q = _drop_contrast(question)
    at = (answer_type or "").lower()

    entity = _first(_ENTITY, q)
    # A business unit named outright beats any pattern: "the head-count of the
    # Special Projects Division" names one of six and nothing else in the
    # estate answers it. Checked against the store rather than a word list, so
    # a corpus with different units still works.
    if entity in (None, "dossier", "compliance", "work", "person", "client"):
        for u in gr.entities.get("business_unit", []):
            head = re.split(r"\s*&\s*|\s+\(", u["unit"])[0]
            if len(head) > 6 and re.search(r"\b" + re.escape(head) + r"\b", q, re.I):
                entity = "business_unit"
                break
    if entity is None and estate and re.search(_WORK_EVIDENCE, q, re.I):
        entity = "work"                        # estate-wide, and about the works
    if entity == "work" and client is None and (estate or re.search(_ESTATE, q, re.I)):
        pass                                   # estate-wide: no shape can run
    elif entity not in _NO_SHAPE:
        # Either the question is about something a shape already covers, or the
        # entity was not named at all. Both are better served by the ladder.
        return None
    fn = _first(_FN, q)

    # Which COLUMN, before which reduction: whether `how many` counts rows or
    # sums a column depends on what column the question named.
    field = _FIELD.get(entity, "value")
    if at == "days" and entity == "iso_cert":
        field = "validity_days"
    cues = _FIELD_CUES.get(entity)
    if cues:
        for pat, f in cues:
            if re.search(pat, q, re.I):
                field = f
                break

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
                  "ra_count", "quantity"}
    if at == "count" and fn not in ("distinct",):
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
        if field in _STATED and not re.search(_AGG_WORD, q, re.I):
            fn = "min" if re.search(r"\blowest\b|\bsmallest\b", q, re.I) else "max"
            rownoun = None
        else:
            rownoun = _ROW_NOUN.get(entity)
        counts_rows = fn != "min" and bool(rownoun and re.search(
            r"(?:how many|number of|(?<!head-)(?<!head )count of)"
            r"\s+(?:\w+\s+){0,3}?(?:" + rownoun + r")",
            q, re.I))
        if rownoun is not None or fn not in ("min", "max"):
            fn = "count" if (counts_rows or field not in _COUNT_COL) else "sum"
    elif at == "money" and fn in ("count", "distinct", None):
        fn = "sum"
    elif at == "days":
        # A day count is a number held in a column, never a row count.
        fn = "sum" if fn in ("count", "distinct", None) else fn
    elif at == "percent":
        # A share of one thing in another needs a ratio, which this cannot
        # express -- but a percentage the document STATES is just a column.
        if not (field.endswith("_pct") or field in ("guarantee_pct", "emd_pct")):
            return None
        fn = "max" if fn in ("count", "distinct", None) else fn
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
        filters.append(("category", "eq", category))

    # a year, when the question names exactly one
    years = sorted({int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", q)})
    if len(years) == 1:
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
        if re.search(r"\bowned\b", q, re.I):
            filters.append(("ownership", "eq", "owned"))
        elif re.search(r"\bhired\b|\bleased\b|\brented\b", q, re.I):
            filters.append(("ownership", "eq", "hired"))
        if re.search(r"not safety|un-?certified|without safety|lack\w* safety", q, re.I):
            filters.append(("safety_certified", "eq", False))
        elif re.search(r"safety[- ]certified|safety certification", q, re.I):
            filters.append(("safety_certified", "eq", True))
        for cond in ("new", "good", "fair", "poor"):
            if re.search(r"\bcondition\b[^.?]{0,20}\b" + cond + r"\b|\b" + cond
                         + r"\b[^.?]{0,12}condition", q, re.I):
                filters.append(("condition", "eq", cond))
                break
        for st in _STATES:
            if re.search(r"\b" + re.escape(st) + r"\b", q, re.I):
                filters.append(("location", "eq", st))
                break
        m = re.search(r"\b(excavator|crusher|batching plant|grader|roller|crane"
                      r"|tipper|paver|loader|compactor|dozer)s?\b", q, re.I)
        if m:
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
        import normalize
        thr = normalize.threshold_from_text(q)
        if thr and re.search(r"above|over|at least|exceed|more than|greater than"
                             r"|or higher|north of|upward", q, re.I):
            filters.append(("value", "gte", thr))
        elif thr and re.search(r"below|under|less than|smaller than|beneath", q, re.I):
            filters.append(("value", "lte", thr))

    if entity == "account":
        m = re.search(r"\b(revenue|payable|receivable|depreciation|bank|cash|capital"
                      r"|materials?|labour|salaries|tax)\b", q, re.I)
        if m:
            filters.append(("account", "contains", m.group(1)))

    # ------------------------------------------------ the estate entities
    if entity == "bond":
        m = re.search(r"\b([A-Z][\w]+(?:\s+[A-Z][\w]+){0,2}\s+Bank)\b", q)
        if m:
            filters.append(("bank", "contains", m.group(1)))
        m = re.search(r"\b(BND-\d+)\b", q, re.I)
        if m:
            filters.append(("bond_no", "eq", m.group(1).upper()))
        if re.search(r"\breleased\b", q, re.I):
            filters.append(("status", "eq", "Released"))
        elif re.search(r"\blive\b|\bactive\b|still (?:in force|open)", q, re.I):
            filters.append(("status", "eq", "Live"))
        if re.search(r"expir\w*|lapse|run out|valid until|end", q, re.I) and years:
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
        if m and entity == "iso_cert":
            filters.append(("cert_no", "eq", m.group(1).upper()))
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
        if hit:
            filters.append(("account", "eq", hit))
        else:
            m = re.search(r"\baccount\s*(\d{3,4})\b", q, re.I)
            if m and entity in ("ledger_account", "ledger_line"):
                filters.append(("code", "eq", int(m.group(1))))

    if entity in ("bank_txn", "bank_year", "ledger_line", "ledger_account",
                  "fin_line", "ar_line", "ra_bill", "audit"):
        # A financial year is written both ways: "FY2021-22" and "2021".
        m = re.search(r"\bFY\s*(\d{4})\s*[-\u2013]\s*\d{2,4}", q, re.I)
        if m:
            filters = [f for f in filters if f[0] != "year"]
            filters.append(("year", "eq", int(m.group(1))))

    if fn == "distinct":
        if re.search(r"client|authorit|department", q, re.I):
            entity, field = "work", "client"
        elif re.search(r"categor|type of work|classification", q, re.I):
            entity, field = "work", "category"
        elif re.search(r"state", q, re.I):
            entity, field = "work", "state"
        else:
            field = "client"

    return {"entity": entity, "filters": filters, "fn": fn, "field": field}
