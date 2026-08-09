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
          "distinct_count", "date_span", "client_total"]

# Ordered most-specific first: the first rule that fires wins.  Each entry is
# (shape, regex, weight) -- weight feeds the confidence score so the caller can
# decide whether to escalate.
RULES = [
    ("date_span", r"\b(?:how many days|number of days|days (?:passed|between|elapsed)"
                  r"|exact interval|what is the interval|days from)\b", 3),
    ("referenced_share", r"\b(?:out of one hundred|share of|what percentage|percent of"
                         r"|divided by the total)\b", 3),
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
    ("exclusion_aggregate", r"\b(?:excluding|except|other than|apart from|but not)\b", 3),
    ("role_split", r"\bas\s+(?:a\s+)?(?:prime|jv partner|sub-?contractor)\b", 3),
    ("role_split", r"\b(?:prime|jv partner)\s*[—–-]", 2),
    ("distinct_count", r"\b(?:how many (?:different|distinct|unique)|distinct\s+\w+"
                       r"|different (?:categories|types|classifications)"
                       r"|how many (?:categories|classifications))\b", 3),
    ("avg_work_size", r"\b(?:average|mean|typical)\b[^.?]{0,30}"
                      r"\b(?:size|value|project|work|assignment)\b", 3),
    ("temporal_chain", r"\b(?:completed|wrapped up|finished|delivered|concluded)\b"
                       r"[^.?]{0,40}\bafter\b", 3),
    ("temporal_chain", r"\bafter (?:that|her|his|the) (?:date|certification|issuance)\b", 3),
    ("doc_filtered_aggregate", r"\b(?:graded|marked|rated|assessed)\b", 2),
    ("hop_aggregate", r"\b(?:combined value|total value|aggregate value|sum of"
                      r"|combined amount|total amount|aggregate of)\b", 1),
    ("client_total", r"\b(?:total|combined|aggregate|overall)\b[^.?]{0,30}\bvalue\b", 0),
]


def _mine_client(db, q):
    """Longest canonical client name mentioned; else longest head-of-name match."""
    ql = q.lower()
    hits = [c for c in db.clients if c.lower() in ql]
    if hits:
        return max(hits, key=len)
    best, score = None, 0
    for c in db.clients:
        head = re.split(r"[,(]", c)[0].strip()
        if head and head.lower() in ql and len(head) > score:
            best, score = c, len(head)
    return best


def _mine_person(db, q):
    ql = q.lower()
    for name in db.persons:
        if name.lower() in ql:
            return name
    return None


def _mine_work(q):
    m = re.search(r"([A-Z][\w&/.\- ]{4,60}?\s*[—–-]\s*[\w ]+Pkg-\d+)", q)
    if m:
        return m.group(1).strip()
    m = re.search(r"([\w &/.-]+?)\s+(?:project\s+)?in\s+([\w ]+)\s+Package\s+(\d+)", q, re.I)
    if m:
        return f"{m.group(1).strip()} — {m.group(2).strip()} Pkg-{m.group(3)}"
    return None


def _mine_category(q):
    m = re.search(r"\b(?:excluding|except|other than|apart from)\s+([a-z ]+?)"
                  r"(?:,|;|\.|\s+what|\s+what's|\s+how|$)", q, re.I)
    return m.group(1).strip() if m else None


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


def classify(question):
    """-> (shape, confidence 0..1).  First matching rule wins."""
    for shape, pattern, weight in RULES:
        if re.search(pattern, question, re.I):
            return shape, min(1.0, weight / 3)
    return "client_total", 0.0


def route(db, question):
    """-> plan dict consumed by executor.run()."""
    shape, conf = classify(question)
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
    if shape == "exclusion_aggregate":
        plan["category"] = _mine_category(question)
    if shape == "doc_filtered_aggregate":
        plan["grading"] = _mine_grading(question)
        if not plan["grading"]:
            plan["shape"], plan["confidence"] = "client_total", 0.0
    if shape == "role_split":
        plan["role"] = _mine_role(question)
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
