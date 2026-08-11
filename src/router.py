"""Question text -> a structured plan the executor can run.

Two backends:

  deterministic  always available, instant, free.  Lexical signals per shape
                 plus the parameter miners.  Validated 25/25 on the samples.
  llm            escalation for questions the deterministic router is unsure
                 about.  Used only when a credential exists -- the `claude`
                 CLI is session-limited and would consume the operator's own
                 quota mid-competition, so it is never the primary path.

The router NEVER computes an answer.  It picks a shape and extracts parameters;
executor.py does every sum, count, difference and date span.
"""
import json
import os
import re

from normalize import threshold_from_text, GRADES

SHAPES = ["absence", "referenced_share", "rank_value", "threshold_aggregate",
          "gap_to_threshold", "exclusion_aggregate", "doc_filtered_aggregate",
          "avg_work_size", "role_split", "hop_aggregate", "temporal_chain",
          "distinct_count", "date_span", "client_total",
          "outstanding_balance", "invoiced_total", "received_total",
          "collection_pct", "category_delta", "unbilled_gap", "mean_median_gap", "year_delta", "year_total"]

# Exclusion wording, shared by the classifier rule and the category miner so the
# two can never drift apart -- a question that classifies as an exclusion but
# whose category cannot be mined sums the WHOLE portfolio, which on a real case
# measured 52.9% error at full confidence.
_EXCL_WORDS = (r"excluding|except(?:\s+for)?|other than|apart from|but not|ignoring"
               r"|leaving out|not including|without counting|besides|excl\.?"
               r"|minus the|less the|net of")
_EXCL_TRIGGER = r"\b(?:" + _EXCL_WORDS + r")\b"

# Ordered most-specific first: the first rule that fires wins.  Each entry is
# (shape, regex, weight) -- weight feeds the confidence score so the caller can
# decide whether to escalate.
# Order matters -- first match wins. Most specific first.
#
# role_split sits ABOVE referenced_share deliberately: "what is our JV Partner
# share of X" contains "share of", which is a referenced_share trigger, and
# would otherwise be answered as a percentage instead of a rupee total.
RULES = [
    # --- set v1.4 additions. These sit at the very top because their wording
    # ("balance", "still owed", "gap between X and Y") otherwise gets captured
    # by gap_to_threshold or rank_value, which answer from the wrong universe.
    ("outstanding_balance", r"\b(?:still owe[sd]?|still owing|remaining balance"
                            r"|outstanding|unpaid|yet to (?:be )?(?:pay|paid|collect)"
                            r"|still (?:pending|outstanding|due)|amount due"
                            r"|not yet (?:been )?(?:paid|collected|received))\b", 3),
    ("outstanding_balance", r"\b(?:balance)\b[^.?]{0,40}\b(?:owed|due|outstanding|end|remaining)\b", 3),
    ("collection_pct", r"\b(?:collection|collected)\b[^.?]{0,30}"
                       r"\b(?:percent|percentage|pct|rate|out of one hundred)\b", 3),
    ("collection_pct", r"\b(?:percent|percentage|pct|share)\b[^.?]{0,30}"
                       r"\b(?:billed|invoiced|collected|received)\b", 3),
    ("invoiced_total", r"\b(?:total|how much)\b[^.?]{0,25}\b(?:invoiced|billed)\b"
                       r"(?![^.?]{0,30}\b(?:still|outstanding|owed|remaining)\b)", 2),
    # Year-over-year delta -- the single largest missing family (24 questions).
    # Must precede category_delta and rank_value, both of which match the same
    # "difference between X and Y" wording. Gated on TWO distinct 4-digit years
    # so a lone credential year ("PMP issued March 10, 2021") cannot trigger it.
    ("year_delta", r"\b(?:19|20)\d{2}\b[^.?]{0,60}\b(?:19|20)\d{2}\b", 3),

    # These two must precede category_delta: its "difference between X and Y"
    # pattern otherwise swallows both. Measured: of 58 category_delta fires,
    # only 21 named two real categories; the rest were these two shapes.
    ("mean_median_gap", r"\b(?:mean|average|avg)\b[^.?]{0,40}\bmedian\b"
                        r"|\bmedian\b[^.?]{0,40}\b(?:mean|average|avg)\b", 3),
    ("unbilled_gap", r"\b(?:awarded|sanction(?:ed)?|won|secured|contracted)\b[^.?]{0,60}"
                     r"\b(?:billed|invoiced)\b"
                     r"|\b(?:billed|invoiced)\b[^.?]{0,60}"
                     r"\b(?:awarded|sanction(?:ed)?|contracted)\b", 3),
    # rank_value must win over category_delta: "the difference between the
    # highest and second highest value work" matches both, and category_delta
    # sits higher in RULES. Guard by excluding rank wording explicitly rather
    # than reordering, so the v1.4 block stays contiguous and readable.
    ("category_delta", r"\b(?:gap|difference|delta|spread)\b[^.?]{0,60}"
                       r"\bbetween\b(?![^.?]{0,60}"
                       r"\b(?:second|2nd|next|runner[-\s]?up|highest|largest|biggest|top)\b)"
                       r"[^.?]{0,60}\b(?:and|versus|vs\.?)\b", 3),

    ("date_span", r"\b(?:how many days|number of days|days (?:passed|between|elapsed)"
                  r"|exact interval|what is the interval|days from)\b", 3),
    ("role_split", r"\bas\s+(?:a\s+)?(?:prime|jv partner|sub-?contractor)\b", 3),
    ("role_split", r"\b(?:prime|jv[-\s]?partner)\b[^.?]{0,30}"
                   r"\b(?:share|total|value|aggregate|sum|worth|portion)\b", 3),
    ("role_split", r"\b(?:share|total|value|aggregate|sum|portion)\b[^.?]{0,30}"
                   r"\b(?:as\s+)?(?:prime|jv[-\s]?partner)\b", 3),
    ("referenced_share", r"\b(?:out of one hundred|share of|what percentage|percent of"
                         r"|divided by the total|what fraction)\b", 3),
    ("absence", r"\b(?:no|lack(?:s|ing)?|without|missing|absent|have no|don'?t have"
                r"|un-?referenced)\b[^.?]{0,40}"
                r"\b(?:reference letters?|client references?|letters?|verification)\b", 3),
    ("absence", r"\breference letter\b[^.?]{0,30}\b(?:on file)\b[^.?]{0,20}\?", 1),
    ("rank_value", r"\b(?:largest|biggest|highest|top)\b[^.?]{0,60}"
                   r"\b(?:second|2nd|runner[-\s]?up|next (?:largest|biggest|highest))\b", 3),
    ("rank_value", r"\b(?:difference|gap)\s+between\s+the\s+(?:largest|biggest|highest|top)\b", 3),
    ("gap_to_threshold", r"\b(?:how much (?:more|additional|further)|additional work|must we (?:secure|win)"
                         r"|to reach|to hit|shortfall|how far short|remaining to|close the gap)\b", 3),
    # NOTE: the unit alternation must include the abbreviation "Cr" -- the corpus
    # and the questions both use "INR 6 Cr" as readily as "six crore", and a rule
    # that only knows the spelled-out word silently drops the whole shape.
    ("threshold_aggregate", r"\b(?:crossing|hitting|exceeding|above|over|north of|in excess of"
                            r"|at or above|at least|no less than|upwards of|clear(?:ing)? the)\b"
                            r"[^.?]{0,40}"
                            r"\b(?:crores?|lakhs?|lacs?|Cr|mark|line|threshold)\b", 3),
    ("threshold_aggregate", r"\b(?:crores?|lakhs?|lacs?|Cr)\b\s*(?:or more|and above|\+)", 3),
    ("exclusion_aggregate", _EXCL_TRIGGER, 3),
    ("distinct_count", r"\b(?:how many (?:different|distinct|unique)|distinct\s+\w+"
                       r"|different (?:categories|types|classifications|kinds)"
                       r"|how many (?:categories|classifications|kinds|types))\b", 3),
    ("avg_work_size", r"\b(?:average|mean|typical)\b[^.?]{0,30}"
                      r"\b(?:size|value|project|work|assignment|contract)\b", 3),
    ("temporal_chain", r"\b(?:completed|wrapped up|finished|finishing|delivered|concluded"
                       r"|closed out|handed over)\b[^.?]{0,40}"
                       r"\b(?:after|since|later than|post[-\s])", 3),
    ("temporal_chain", r"\b(?:after|since|post[-\s]?)"
                       r"(?:that|her|his|their|the)?\s*"
                       r"(?:date|certification|certificate|issuance|credential|PMP|Six Sigma)\b", 3),
    ("doc_filtered_aggregate", r"\b(?:graded|marked|rated|assessed)\b", 2),
    ("doc_filtered_aggregate", r"\bgrad(?:e|ing)\b[^.?]{0,20}\b(?:is|of|was|as)\b", 2),
    ("hop_aggregate", r"\b(?:combined value|total value|aggregate value|sum of"
                      r"|combined amount|total amount|aggregate of)\b", 1),
    ("client_total", r"\b(?:total|combined|aggregate|overall)\b[^.?]{0,30}\bvalue\b", 0),
]


# 12 of the 28 clients (43%) share a name "head" with at least one other:
# three Jal Nigam, four Public Works Department, three Irrigation & Waterways,
# two Public Health Engineering. Only the state distinguishes them.
#
# The previous head-match fallback picked whichever shared head it saw first,
# which -- since db.clients is sorted -- was always the alphabetically-first
# member. "Jal Nigam in Uttar Pradesh" resolved to "Jal Nigam, Gujarat", at full
# confidence. Six of fifteen realistic phrasings resolved to the WRONG client.
#
# Token-coverage matching fixes this: the state token is part of the client's
# token set, so the correct member scores strictly higher. On a tie we return
# None rather than guess -- an unresolved client is flagged by the confidence
# floor and lands in the triage log; a wrongly-resolved one is invisible.

_STOP = {"of", "the", "and", "in", "for", "at", "to", "a", "an",
         "govt", "government", "we", "our", "us"}

_ABBREV = {
    r"\bpwd\b": "public works department",
    r"\bphed\b": "public health engineering department",
    r"\bnicl\b": "national infrastructure corp ltd",
}


def _norm_match(s):
    """Fold the spelling variants questions actually use into one form."""
    s = s.lower()
    s = s.replace("&", " and ")
    for pat, rep in _ABBREV.items():
        s = re.sub(pat, rep, s)
    s = re.sub(r"\bgovt\b", "government", s)
    s = re.sub(r"\bdept\b", "department", s)
    s = re.sub(r"\bcorp\b", "corporation", s)
    s = re.sub(r"\bltd\b", "limited", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s):
    return {t for t in _norm_match(s).split() if t not in _STOP}


def _mine_client(db, q):
    """Resolve a client mention, or None. Never guesses between ambiguous ones."""
    qn = _norm_match(q)
    # 1. the whole canonical name appears verbatim -- longest wins
    hits = [c for c in db.clients if _norm_match(c) in qn]
    if hits:
        return max(hits, key=len)

    # 2. token coverage: what fraction of THIS client's distinctive tokens are
    #    present? The state token is what separates the ambiguous groups.
    qtok = set(qn.split())
    scored = []
    for c in db.clients:
        ctok = _tokens(c)
        if not ctok:
            continue
        scored.append((len(ctok & qtok) / len(ctok), len(ctok), c))
    if not scored:
        return None
    top = max(s[0] for s in scored)
    if top < 0.75:                       # too weak to be a real mention
        return None
    winners = [s for s in scored if s[0] == top]
    if len(winners) > 1:                 # genuinely ambiguous -- refuse to guess
        return None
    return winners[0][2]


def _mine_person(db, q):
    ql = q.lower()
    for name in db.persons:
        if name.lower() in ql:
            return name
    return None


def _mine_work(q):
    """Return a work mention. A bare package number is the strongest form.

    Package numbers are unique across all 155 works, so "pkg 37" identifies a
    work outright -- which survives the lowercased, reordered phrasings the
    questions use ("on delhi pkg 37 wtp augmentation"). db.work() resolves it.
    """
    m = re.search(r"\bpkg[\s\-_]*\d{1,3}\b", q, re.I)
    if m:
        return m.group(0)
    m = re.search(r"([A-Z][\w&/.\- ]{4,60}?\s*[—–-]\s*[\w ]+Pkg-\d+)", q)
    if m:
        return m.group(1).strip()
    m = re.search(r"([\w &/.-]+?)\s+(?:project\s+)?in\s+([\w ]+)\s+Package\s+(\d+)", q, re.I)
    if m:
        return f"{m.group(1).strip()} — {m.group(2).strip()} Pkg-{m.group(3)}"
    return None


# The terminator is a LOOKAHEAD, and it includes ? and !. The original pattern
# required a comma/period/end-of-string, so "…excluding buildings?" -- the
# exclusion trailing the sentence, which is the commonest natural phrasing --
# matched nothing and the whole portfolio was summed instead.
_CATEGORY = re.compile(
    r"\b(?:" + _EXCL_WORDS + r")\s+"
    r"(?:the\s+|any\s+|all\s+)?"
    r"([A-Za-z][A-Za-z\s&/-]*?)"
    r"(?=[,;.?!]|$|\s+(?:what|how|give|show|tell|and|for|please|work|project)\b)",
    re.I)


def _mine_categories(db, q):
    """Return the work categories a question names, longest match first.

    Matched against the 13 real category strings rather than free text, and
    LONGEST-FIRST, because the organisers documented two collisions:
      - 'buildings' is a substring of 'small buildings', so a naive search for
        'buildings' also matches Small Buildings works;
      - a category whose name also appears in the CLIENT's name is unusable
        ('irrigation' matches every work of 'Irrigation & Waterways Dept').
    Longest-first resolves the first. For the second we strip the client's own
    name from the text before matching, so its tokens cannot supply a category.
    """
    text = q.lower()
    for c in db.clients:                      # remove client name from the haystack
        text = text.replace(c.lower(), " ")
    cats = sorted({(w.get("category") or "").strip() for w in db.works if w.get("category")},
                  key=len, reverse=True)
    found, used = [], []
    for c in cats:
        cl = c.lower()
        if cl in text and not any(cl in u for u in used):
            found.append(c)
            used.append(cl)
            text = text.replace(cl, " ")      # consume, so 'small buildings' != 'buildings'
    return found


def _mine_category(q):
    m = _CATEGORY.search(q)
    if not m:
        return None
    cat = re.sub(r"\s+", " ", m.group(1)).strip(" .,;-")
    # guard against swallowing a trailing verb phrase
    return cat or None


def _mine_grading(q):
    for g in sorted(GRADES, key=len, reverse=True):
        if re.search(r"\b" + re.escape(g) + r"\b", q):
            return g
    return None


def _mine_credential(q):
    m = re.search(r"\b(PMP|Six Sigma Black Belt|Six Sigma Green Belt|Six Sigma|ASQ)\b", q, re.I)
    return m.group(1) if m else None


def _mine_role(q):
    m = re.search(r"\b(Prime|JV Partner)\b", q, re.I)
    return m.group(1) if m else "Prime"


def _fallback_for(allowed):
    """Most-common shape within a unit class, used when no rule fires."""
    for pref in ("client_total", "distinct_count", "referenced_share", "date_span"):
        if pref in allowed:
            return pref
    return sorted(allowed)[0]


def classify(question):
    """-> (shape, confidence 0..1).  First matching rule wins."""
    for shape, pattern, weight in RULES:
        if re.search(pattern, question, re.I):
            return shape, min(1.0, weight / 3)
    return "client_total", 0.0


# Each shape produces exactly one kind of number, and the question file states
# which kind it wants. That makes answer_type a hard constraint, not a hint:
# only date_span yields days, only these three yield a percentage, and a money
# question can never be answered by a count. Honouring it rescues questions
# whose wording the lexical rules miss -- 14 "days" questions were falling
# through to a rupee total purely because they said "days to completion?"
# rather than "how many days".
_TYPE_SHAPES = {
    "days":    {"date_span"},
    "percent": {"referenced_share", "collection_pct"},
    "count":   {"absence", "distinct_count"},
    "money":   {"client_total", "hop_aggregate", "avg_work_size", "rank_value",
                "threshold_aggregate", "gap_to_threshold", "exclusion_aggregate",
                "doc_filtered_aggregate", "role_split", "temporal_chain",
                "outstanding_balance", "invoiced_total", "received_total",
                "category_delta", "unbilled_gap", "mean_median_gap",
                "year_delta", "year_total"},
}


def route(db, question, answer_type=None):
    """-> plan dict consumed by executor.run()."""
    shape, conf = classify(question)

    allowed = _TYPE_SHAPES.get((answer_type or "").lower())
    if allowed and shape not in allowed:
        # The lexical rules picked a shape that cannot produce the requested
        # unit. Re-run classification restricted to shapes that can.
        for s, pattern, weight in RULES:
            if s in allowed and re.search(pattern, question, re.I):
                shape, conf = s, min(1.0, weight / 3)
                break
        else:
            shape = sorted(allowed)[0] if len(allowed) == 1 else _fallback_for(allowed)
            conf = 0.5 if len(allowed) == 1 else 0.0
    plan = {
        "shape": shape,
        "confidence": conf,
        "client": _mine_client(db, question),
        "person": _mine_person(db, question),
        "work": _mine_work(question),
        "credential": _mine_credential(question),
    }
    if shape in ("threshold_aggregate", "gap_to_threshold"):
        plan["threshold"] = threshold_from_text(question)
        # a threshold question with no parseable number is really a total
        if plan["threshold"] is None and shape == "threshold_aggregate":
            plan["shape"], plan["confidence"] = "client_total", 0.0
    if shape in ("year_delta", "year_total"):
        yrs = sorted({int(y) for y in re.findall(r"(?:19|20)\d{2}", question)})
        plan["years"] = yrs
        if shape == "year_delta" and len(yrs) < 2:
            plan["confidence"] = 0.0
    if shape == "category_delta":
        plan["categories"] = _mine_categories(db, question)
        if len(plan["categories"]) < 2:      # cannot subtract without two
            plan["confidence"] = 0.0
    if shape == "exclusion_aggregate":
        plan["category"] = _mine_category(question)
        # An exclusion with no identifiable category would silently sum the whole
        # portfolio at full confidence. Drop confidence so it surfaces in triage;
        # the executor refuses to run it, so the fallback ladder logs it too.
        if not plan["category"]:
            plan["confidence"] = 0.0
    if shape == "doc_filtered_aggregate":
        plan["grading"] = _mine_grading(question)
        if not plan["grading"]:
            plan["shape"], plan["confidence"] = "client_total", 0.0
    if shape == "role_split":
        plan["role"] = _mine_role(question)
    # Work -> client indirection. 99 of the 371 validation questions name a work
    # package and then ask about "that client" or "them" without ever naming the
    # client. Resolving the work gives us the client for free.
    if not plan["client"] and plan.get("work"):
        w = db.work(plan["work"])
        if w and w.get("client"):
            plan["client"] = w["client"]
            plan["client_via"] = "work"

    # Person -> client indirection, for the same reason ("her main client").
    if not plan["client"] and plan.get("person"):
        led = db.led_by(plan["person"])
        clients = {w["client"] for w in led if w.get("client")}
        if len(clients) == 1:
            plan["client"] = clients.pop()
            plan["client_via"] = "person"

    # a client-scoped shape with no resolvable client cannot run
    if plan["shape"] != "date_span" and not plan["client"] and not plan["person"]:
        plan["confidence"] = 0.0
    return plan


# ---------------------------------------------------------------- LLM backend

ROUTER_SYSTEM = """You classify questions about an infrastructure contractor's records.

Return ONE shape and its parameters. You never compute or estimate a number.

Shapes:
  absence                 count of a client's works with no reference letter
  referenced_share        percent of a client's works that have a reference letter
  rank_value              largest work value minus second largest, for a client
  threshold_aggregate     sum of a client's works at or above a rupee threshold
  gap_to_threshold        target minus the sum of a client's works
  exclusion_aggregate     sum of a client's works excluding one category
  doc_filtered_aggregate  sum of a client's works carrying a given grading
  avg_work_size           mean value across a client's works
  role_split              sum of a client's works where contractor role matches
  hop_aggregate           person -> their client -> sum of that CLIENT'S WHOLE portfolio
  temporal_chain          sum of a person's works completed after their credential date
  distinct_count          number of distinct work categories for a person
  date_span               days between a credential issue date and a work's completion
  client_total            sum of a client's works (fallback)

Rules:
- hop_aggregate always means the client's ENTIRE portfolio, even when the question
  says "assignments HE delivered". The person only identifies the client.
- Thresholds in words ("seventy-three crore") are rupees: 1 crore = 10,000,000.
- Copy client, person and work names verbatim from the question."""

ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "shape": {"type": "string", "enum": SHAPES},
        "client": {"type": ["string", "null"]},
        "person": {"type": ["string", "null"]},
        "work": {"type": ["string", "null"]},
        "threshold": {"type": ["integer", "null"]},
        "category": {"type": ["string", "null"]},
        "grading": {"type": ["string", "null"]},
        "role": {"type": ["string", "null"]},
    },
    "required": ["shape"],
    "additionalProperties": False,
}


def llm_available():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def route_llm(questions, model="claude-opus-5"):
    """Batch-classify [{qid, question}] -> {qid: plan}.  Requires a credential.

    Batched so one request covers many questions; the executor still does all
    arithmetic, so a router slip costs one question rather than a wrong number
    everywhere.
    """
    import anthropic

    client = anthropic.Anthropic()
    numbered = "\n".join(f"{i+1}. {q['question']}" for i, q in enumerate(questions))
    resp = client.messages.create(
        model=model,
        max_tokens=16000,
        system=ROUTER_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": {
            "type": "object",
            "properties": {"plans": {"type": "array", "items": ROUTER_SCHEMA}},
            "required": ["plans"],
            "additionalProperties": False,
        }}},
        messages=[{"role": "user",
                   "content": f"Classify each question. Return one plan per question, "
                              f"in order.\n\n{numbered}"}],
    )
    text = next(b.text for b in resp.content if b.type == "text")
    plans = json.loads(text)["plans"]
    return {q["qid"]: p for q, p in zip(questions, plans)}
