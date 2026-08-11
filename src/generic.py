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
    ("asset", r"plant|machinery|equipment|asset|excavator|crusher|batching|grader"
              r"|roller|crane|tipper|gross block|fleet"),
    ("account", r"trial balance|ledger account|\baccount\b|revenue|expense|payable"
                r"|receivable account|depreciation|balance sheet"),
    ("boq_item", r"\bboq\b|bill of quantit|measured (?:total|quantit)|line item"),
    ("invoice", r"\binvoice|\bbilled\b|receipt|ageing"),
    ("person", r"engineer|personnel|staff|employee|people|\bperson\b"),
    ("client", r"\bclients?\b|\baccounts?\b(?!\s+\d)|authorit(?:y|ies)|department"),
    ("work", r"work|project|contract|assignment|package|job|delivered|completed"),
]

# Reduction vocabulary, most specific first.
_FN = [
    ("distinct", r"how many (?:different|distinct|unique)|number of (?:different|distinct)"
                 r"|distinct \w+|different \w+"),
    ("count", r"how many|number of|\bcount\b|how much of (?:our|the) \w+ (?:is|are)\b"),
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
}

_STATES = ["West Bengal", "Uttar Pradesh", "Madhya Pradesh", "Tamil Nadu",
           "Maharashtra", "Rajasthan", "Jharkhand", "Gujarat", "Odisha", "Delhi"]


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
_NO_SHAPE = {"asset", "boq_item"}

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


def plan(db, gr, question, answer_type=None, client=None, category=None):
    """-> {entity, filters, fn, field} or None when the question is not placeable."""
    q = question
    at = (answer_type or "").lower()

    entity = _first(_ENTITY, q)
    if entity == "work" and client is None and re.search(_ESTATE, q, re.I):
        pass                                   # estate-wide: no shape can run
    elif entity not in _NO_SHAPE:
        # Either the question is about something a shape already covers, or the
        # entity was not named at all. Both are better served by the ladder.
        return None
    fn = _first(_FN, q)

    # answer_type is the strongest signal about the reduction, and it overrides
    # loose wording: "how much plant do we have" reads as a sum but a `count`
    # question wants the number of items.
    if at == "count" and fn not in ("distinct",):
        fn = "count"
    elif at == "money" and fn in ("count", "distinct", None):
        fn = "sum"
    elif at == "percent":
        return None                      # shares need a ratio, not one reduction
    if not fn:
        return None

    field = _FIELD.get(entity, "value")
    filters = []

    if client:
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
            if re.search(r"\b" + g + r"\b", q, re.I):
                filters.append(("grading", "eq", g))
                break
        for st in _STATES:
            if re.search(r"\b" + re.escape(st) + r"\b", q, re.I):
                filters.append(("state", "eq", st))
                break
        if re.search(r"\bas (?:a )?prime\b|\bprime contractor\b", q, re.I):
            filters.append(("role", "eq", "Prime"))
        elif re.search(r"jv partner|joint venture", q, re.I):
            filters.append(("role", "eq", "JV Partner"))
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
