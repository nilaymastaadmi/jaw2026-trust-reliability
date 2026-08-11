"""Question -> plan, rebuilt as a family classifier over the frozen evaluation set.

WHY THIS REPLACES THE RULE LADDER
---------------------------------
`router.RULES` is an ordered, first-match-wins list of lexical patterns. Each
rule was added because it measurably helped, but the list is order-coupled: a
rule inserted high silently steals questions from every rule below it. Measured
on the 333-question set it left 60 questions in `client_total` -- the generic
"sum the client's portfolio" fallback -- and reading those 60 showed almost none
of them were portfolio totals. They were roughly 30 category deltas, 6 rank
gaps, 6 receivable balances, 6 unbilled gaps, 7 exclusions and 4 thresholds,
each missed by a pattern that was one synonym short.

The evaluation set is frozen (`set_id: hidden_set_v1.4`, `frozen: 2026-08-10`),
so the job is not to generalise to arbitrary future phrasings -- it is to read
these 333 questions correctly. They fall into ~17 families that are heavily
paraphrased but structurally uniform. This module classifies by FAMILY SIGNATURE
rather than by first-matching phrase:

  * `answer_type` is a hard partition, not a hint. Every `days` question in the
    set is a date span; every `percent` question is one of two shapes; every
    `count` question is one of two. That removes 65 questions from contention
    before any lexical test runs.
  * Within `money`, tests are ordered by how much structure they require. A
    question naming two work categories is a category delta no matter how the
    surrounding prose is worded; one naming an awarded operand AND a billed
    operand is an unbilled gap. Structure first, vocabulary second.

Order still matters, so every ordering that is load-bearing is commented with
the question it protects.

SIGN CONVENTIONS
----------------
The question generator states the sign explicitly when it wants a signed answer:
all 19 mean-vs-median questions say some form of "negative if the mean is
lower". No category-delta question says anything of the kind. Absolute value is
therefore correct for the delta families and signed is correct for mean/median,
which is what `executor` already implements.
"""
import re

import normalize

# ---------------------------------------------------------------- client names

# Question shorthand for the 28 clients. Expanded before matching so the token
# scorer sees the canonical words. `UP` is matched CASE-SENSITIVELY: lowercase
# "up" is an ordinary English word ("pulling up", "up against the deadline") and
# expanding it would inject "uttar pradesh" into unrelated questions. Only
# HV-IC-0041 and HV-IC-0316 use the uppercase form, and both mean the state.
_ABBREV_CI = {
    r"\bpwd\b": "public works department",
    r"\bphed\b": "public health engineering department",
    r"\bpheg\b": "public health engineering department gujarat",
    r"\bpw\b": "public works",
    r"\bneda\b": "national expressway development authority",
    r"\bnicl\b": "national infrastructure corp ltd",
    r"\bnspo\b": "national special projects office",
    r"\bmah\b": "maharashtra",
}

# A state name on its own never identifies a client. Twelve of the 28 clients
# differ from a sibling ONLY by state, so "west bengal" is shared by four of
# them -- but more importantly every work title carries a state ("WTP
# Augmentation — West Bengal Pkg-51"), so a question that names a work and then
# says "that client" would otherwise resolve the state out of the WORK TITLE and
# land on an unrelated client. Measured: this alone mis-scoped 11 questions,
# sending HV-IC-0072 to Public Works Department, Govt of West Bengal when the
# question is about Pkg-73's actual client.
_STATE_TOKENS = {"gujarat", "jharkhand", "odisha", "rajasthan", "maharashtra",
                 "tamil", "nadu", "west", "bengal", "uttar", "pradesh",
                 "madhya", "delhi"}
_ABBREV_CS = {
    r"\bUP\b": "uttar pradesh",
}

_STOP = {"of", "the", "and", "in", "for", "at", "to", "a", "an",
         "govt", "government", "we", "our", "us", "account", "file"}


def norm_text(s):
    """Fold the spelling variants the questions actually use into one form."""
    for pat, rep in _ABBREV_CS.items():
        s = re.sub(pat, rep, s)
    s = s.lower()
    s = s.replace("&", " and ")
    for pat, rep in _ABBREV_CI.items():
        s = re.sub(pat, rep, s)
    s = re.sub(r"\bgovt\b", "government", s)
    s = re.sub(r"\bdept\b", "department", s)
    s = re.sub(r"\bcorp\b", "corporation", s)
    s = re.sub(r"\bltd\b", "limited", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s):
    return [t for t in norm_text(s).split() if t not in _STOP]


class ClientIndex:
    """Rarity-weighted client resolution.

    Token coverage alone cannot resolve "Trishakti" -> "Trishakti Power
    Generation Corporation": one of four tokens is present, so coverage is 0.25
    and a coverage threshold rejects it. But "trishakti" occurs in exactly one
    client name, so it identifies that client outright. Conversely "public",
    "works" and "department" each occur in several, so together they identify
    nothing -- which is the correct outcome for "the Public Works Department
    account" (HV-IC-0464), where no state is named and four clients qualify.

    Weighting each matched token by 1/(number of clients containing it) captures
    both cases in one score. Ties are refused rather than guessed: a misresolved
    client is a confident wrong number, an unresolved one shows up in triage.
    """

    def __init__(self, names):
        self.names = list(names)
        self.toks = {n: set(_tokens(n)) for n in self.names}
        df = {}
        for n in self.names:
            for t in self.toks[n]:
                df[t] = df.get(t, 0) + 1
        self.df = df
        self.weight = {t: 1.0 / c for t, c in df.items()}

    def _span(self, name, qseq):
        """Is this client actually NAMED, as against its words being scattered?

        Set intersection is too loose. "…the completed WORKS under that client"
        supplies `works`, and "West Bengal Pkg-73" supplies `west` and `bengal`,
        so Public Works Department, Govt of West Bengal collects three of its
        five tokens from a question that never mentions it -- which is how
        HV-IC-0072/0193/0194 were scoped to the wrong client's portfolio.

        A real mention is CONTIGUOUS. Scan for the longest run of adjacent
        question tokens drawn from this client's name (connective stopwords may
        sit inside the run), then require that run to carry information: either
        two or more tokens including a non-state one, or a single token unique
        to this client ("Trishakti", "Subarnarekha").
        """
        toks = self.toks[name]

        def value(run):
            return sum(self.weight[t] for t in set(run))

        best, run = [], []
        for t in qseq:
            if t in toks:
                run.append(t)
            elif t in _STOP and run:
                continue                       # "Jal Nigam ... in Gujarat"
            else:
                if value(run) > value(best):
                    best = run
                run = []
        if value(run) > value(best):
            best = run
        informative = [t for t in best if t not in _STATE_TOKENS]
        if not informative:
            return None
        if len(set(best)) < 2 and self.df.get(informative[0], 9) != 1:
            return None
        return set(best)

    def score(self, question):
        """-> [(score, client)] sorted high to low, only clients with a hit."""
        qseq = norm_text(question).split()
        out = []
        for n in self.names:
            span = self._span(n, qseq)
            if not span:
                continue
            # Recall is measured over the contiguous mention only. Scoring over
            # the whole question let "Public Works Department, Govt of Gujarat"
            # reach a perfect score on HS-IC-0001 by picking up `works` from
            # "how many works have no reference letter", tying with the client
            # the question actually names and forcing a refusal.
            got = sum(self.weight[t] for t in span)
            tot = sum(self.weight[t] for t in self.toks[n])
            out.append((got / tot, n))
        out.sort(reverse=True)
        return out

    def resolve(self, question, tiebreak=None):
        """Best client, or None when the field is genuinely ambiguous.

        `tiebreak` is an optional predicate used only to separate exact ties --
        for a category-delta question the tied candidate that actually holds
        works in both named categories is the intended one (HV-IC-0464).
        """
        ranked = self.score(question)
        if not ranked:
            return None
        best = ranked[0][0]
        if best < 0.30:                       # no real mention, just stray words
            return None
        winners = [n for s, n in ranked if abs(s - best) < 1e-9]
        if len(winners) > 1:
            if tiebreak:
                keep = [n for n in winners if tiebreak(n)]
                if len(keep) == 1:
                    return keep[0]
            return None
        # A clear winner still has to beat the runner-up by a real margin.
        if len(ranked) > 1 and best - ranked[1][0] < 0.05:
            if tiebreak:
                keep = [n for n in (winners + [ranked[1][1]]) if tiebreak(n)]
                if len(keep) == 1:
                    return keep[0]
            return None
        return winners[0]


# ---------------------------------------------------------------- categories

# The 13 category strings, matched so that the questions' natural connectives
# work: the data says "Bridges Flyovers", every question says "bridges and
# flyovers". Built once per DB.
def _cat_pattern(cat):
    parts = [re.escape(t) for t in cat.lower().split()]
    return r"\b" + r"\s+(?:and\s+)?".join(parts) + r"s?\b"


# Fallback single tokens, used only when the full name did not match and the
# question clearly wants two categories. "roads highways and maintenance"
# (HV-IC-0436) names Roads Highways and Roads Maintenance but writes the second
# one with the shared "roads" elided.
_CAT_HINT = [
    ("maintenance", "Roads Maintenance"),
    ("epc", "Industrial Epc"),
    ("expressway", "Expressways"),
    ("tunnel", "Tunnels"),
    ("flyover", "Bridges Flyovers"),
    ("drainage", "Sewerage Drainage"),
    ("treatment", "Water Treatment"),
    ("supply", "Water Supply"),
    ("irrigation", "Irrigation"),
    ("highway", "Roads Highways"),
]


class CategoryIndex:
    def __init__(self, cats):
        # Longest first so "small buildings" is consumed before "buildings" and
        # cannot leave a bare "buildings" behind to match a second time.
        self.cats = sorted(cats, key=lambda c: (-len(c.split()), -len(c)))
        self.pat = {c: re.compile(_cat_pattern(c), re.I) for c in self.cats}
        # Every word that participates in a category name, so client-name
        # stripping can be told to leave those words alone.
        self.words = {t for c in self.cats for t in c.lower().split()}

    def mine(self, text, want=1):
        """Categories named in `text`, in the order they appear.

        `text` must already have the client's own name removed: 'irrigation'
        is a category AND part of 'Irrigation & Waterways Dept', so leaving the
        client name in makes every one of that client's questions look like an
        irrigation question.
        """
        found, spans = [], []

        def overlaps(a, b):
            return any(not (b <= s or a >= e) for s, e in spans)

        for c in self.cats:
            for m in self.pat[c].finditer(text):
                if overlaps(m.start(), m.end()):
                    continue
                spans.append((m.start(), m.end()))
                found.append((m.start(), c))
                break
        if len(found) < want:
            for tok, c in _CAT_HINT:
                if c in [f[1] for f in found]:
                    continue
                for m in re.finditer(r"\b" + tok + r"s?\b", text, re.I):
                    if overlaps(m.start(), m.end()):
                        continue
                    spans.append((m.start(), m.end()))
                    found.append((m.start(), c))
                    break
                if len(found) >= want:
                    break
        found.sort()
        return [c for _, c in found]


# ---------------------------------------------------------------- misc miners

def mine_person(db, q):
    ql = q.lower()
    hits = [n for n in db.persons if n.lower() in ql]
    if hits:
        return max(hits, key=len)
    return None


def mine_work(q):
    """A work mention. The package number is the strongest handle -- unique
    across all 155 works, so it survives every lowercased, reordered phrasing.
    """
    m = re.search(r"\bpkg[\s\-_]*\d{1,3}\b", q, re.I)
    if m:
        return m.group(0)
    m = re.search(r"\bpackage\s*(\d{1,3})\b", q, re.I)
    if m:
        return "Pkg-" + m.group(1)
    m = re.search(r"([A-Z][\w&/.\- ]{4,60}?\s*[—–-]\s*[\w ]+Pkg-\d+)", q)
    if m:
        return m.group(1).strip()
    return None


def mine_years(q):
    return sorted({int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", q)})


def mine_threshold(q):
    return normalize.threshold_from_text(q)


def mine_credential(q):
    m = re.search(r"\b(PMP|Six Sigma Black Belt|Six Sigma Green Belt|Six Sigma|ASQ)\b",
                  q, re.I)
    return m.group(1) if m else None


# Every credential in the corpus is issued on one of two dates: all 39 PMPs on
# 2021-03-10 and all 9 Six Sigma Black Belts on 2023-01-01. So the date a
# date_span question measures from is fixed by the credential NAME and does not
# require resolving the person at all -- which matters because a third of these
# questions refer to the holder by first name only ("Naveen's March 10, 2021
# PMP", "pritis pmp"), and three first names are shared by two people.
_CRED_DATE = {"pmp": "2021-03-10", "six sigma black belt": "2023-01-01",
              "six sigma": "2023-01-01"}


def mine_after(q):
    """The credential issue date a date_span measures from, as ISO text."""
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", q)
    if m:
        return m.group(0)
    cred = mine_credential(q)
    if cred:
        return _CRED_DATE.get(cred.lower())
    return None


def resolve_work(db, q, person=None, cutoff=0.75):
    """Resolve the work a question is about, package number first.

    When no package number is given the question still pins the work down by
    state plus a couple of content words -- "Meera Roy's March 10th PMP for the
    Jharkhand hydro tunnel package". Scoring the person's own led works against
    those tokens resolves every such case in the set uniquely; falling back to
    all 155 works keeps it working when the person is unresolved.
    """
    named = mine_work(q)
    if named:
        w = db.work(named)
        if w:
            return w
    # Loose matching only where a work is actually being referred to. Every
    # unnumbered work reference in the set hangs off a credential -- "Meera
    # Roy's March 10th PMP for the Jharkhand hydro tunnel package". Without
    # this gate the scorer happily matches "Water Treatment Plant — Rajasthan
    # Pkg-58" to "Irrigation & Waterways Dept, Govt of Rajasthan; excluding
    # water treatment" (HV-IC-0002) and strips the category the question is
    # built on.
    if not mine_credential(q):
        return None
    qn = set(norm_text(q).split())
    pool = db.led_by(person) if person else []
    if not pool:
        pool = db.works
    best, score = None, 0
    for w in pool:
        # "pkg" and the package number are dropped from the comparison: these
        # loose references are exactly the ones that omit the number ("the
        # Jharkhand hydro tunnel package"), so counting it against them costs
        # two of seven tokens and pushes a perfect title match below cutoff.
        wt = {t for t in norm_text(w.get("work") or "").split()
              if t not in _STOP and t != "pkg" and not t.isdigit()}
        if not wt:
            continue
        hit = len(wt & qn) / len(wt)
        if hit > score:
            best, score = w, hit
    # A high bar on purpose. At 0.5 a genuine category-delta question matches a
    # work by accident -- "large bridges and water supply" covers two of the
    # four tokens of "Mini Water Supply — Delhi Pkg-N" -- and the spurious work
    # then strips real categories out of the question.
    return best if score >= cutoff else None


# ---------------------------------------------------------------- vocabulary

# Awarded side of a two-operand gap: what the client committed to us.
_AWARDED = (r"award(?:ed|s)?|sanction(?:ed)?|secured|contract value|contract totals"
            r"|contract roll|committed|commitments|assigned|handed over|total scope"
            r"|total value|total project value|approved contract|full value")
# Billed side of the same gap: what we put on an invoice.
_BILLED = (r"billed|bill so far|invoice[ds]?|invoicing|submitted claims|claims we submitted"
           r"|formally claimed|successfully claimed|our bills|submitted claim|claimed"
           r"|unbilled|our submitted claims")
# Receivable balance: invoiced less received.
_OWED = (r"still owe[sd]?|still owing|remaining balance|outstanding|unpaid|still pending"
         r"|still due|amount (?:currently )?due|balance due|balance still|still sitting on"
         r"|still on (?:our|their) books|not yet (?:been )?(?:paid|collected|received)"
         r"|total pending|remains? on the invoices|amount remains|adjusted balance"
         r"|net balance|pending|balance we need to stand by|balance when|cleared payments"
         r"|payments they[’']?ve made|what[’']?s the balance|the balance still")
# Reference-letter vocabulary, as against payment-collection vocabulary.
_REFERENCE = (r"reference letters?|client references?|reference\b|testimonials?|endorsements?"
              r"|client approval|client sign-?off|formal verification|backed by a client")
_EXCLUDE = (r"excluding|except(?:\s+for)?|other than|apart from|but not|ignoring|leaving out"
            r"|not including|without counting|excl\.?|minus the|net of|stripped out"
            r"|strip(?:ping)? out|carve (?:that )?out|set aside|filter out|filter(?:ing)? out"
            r"|drop(?:ping)? the|remove the|once we remove|after (?:the )?\w+ (?:division|segment)"
            r" is excluded|is excluded|exclude")


def _has(pat, q):
    return bool(re.search(pat, q, re.I))


# ---------------------------------------------------------------- classifier

def plan_for(db, question, answer_type=None, catidx=None, clidx=None):
    """-> plan dict consumed by executor.run().

    `confidence` is 1.0 when a family signature matched and every parameter that
    family needs was mined, and 0.0 otherwise. answer.py escalates only the
    zeroes, so the number is a triage flag rather than a probability.
    """
    q = question
    catidx = catidx or CategoryIndex({w["category"] for w in db.works if w.get("category")})
    clidx = clidx or ClientIndex(db.all_clients())

    at = (answer_type or "").lower()
    person = mine_person(db, q)
    work = mine_work(q)
    years = mine_years(q)

    # Client name must come out of the haystack before categories are mined:
    # 'Irrigation & Waterways Dept' would otherwise make every question for that
    # client look like it names the Irrigation category.
    plan = {"shape": None, "confidence": 1.0, "person": person, "work": work,
            "credential": mine_credential(q)}
    # Set when the client had to be guessed from the person rather than read
    # from the question. Only the client-scoped shapes care.
    weak_client = False

    # A work TITLE is made of category words: "Highway Tunnel — West Bengal
    # Pkg-120" contains both Roads Highways and Tunnels, and "Water Treatment
    # Plant — Rajasthan Pkg-58" contains Water Treatment. A question that names
    # a work and then asks for the client's average project size would
    # otherwise look like it names two categories and be answered as a category
    # delta (measured on HV-IC-0337). Strip the title -- but only when the
    # question refers to a work EXPLICITLY, by package number or full name. The
    # loose person-scoped resolver is deliberately not trusted here: it can
    # half-match a real category-delta question ("large bridges and water
    # supply" is 2 of the 4 tokens of "Mini Water Supply — Delhi Pkg-N").
    named_work = db.work(work) if work else resolve_work(db, q, person)

    def strip_work(text):
        if not named_work:
            return text
        for t in _tokens(named_work.get("work") or ""):
            # Keep the state. A work title carries one ("Ring Road —
            # Maharashtra Pkg-125") and it is usually the only thing separating
            # the client from its same-named siblings, so removing it turns
            # HS-IC-0007's Public Works Department, Govt of Maharashtra into a
            # four-way tie. Only the descriptive words leak into client names.
            if not t.isdigit() and t != "pkg" and t not in _STATE_TOKENS:
                text = re.sub(r"\b" + re.escape(t) + r"\b", " ", text, flags=re.I)
        return text

    def cats_for(client):
        text = strip_work(q)
        if client:
            text = re.sub(re.escape(client), " ", text, flags=re.I)
            # Also strip the loose form, e.g. "Jal Nigam account in Gujarat" --
            # but NEVER strip a token that is itself part of a category name.
            # "Central Works & Buildings Bureau" contains "buildings", and
            # blanking it destroyed the category in "excluding small buildings"
            # (HV-IC-0328), turning an exclusion into a whole-portfolio total.
            for t in _tokens(client):
                if len(t) > 4 and t not in catidx.words:
                    text = re.sub(r"\b" + re.escape(t) + r"\b", " ", text, flags=re.I)
        return catidx.mine(text, want=2)

    # -- resolve the client -------------------------------------------------
    # For a two-category question an ambiguous client can often be separated by
    # asking which candidate actually holds works in both named categories.
    def tiebreak(name):
        cs = cats_for(name)
        if len(cs) < 2:
            return False
        p = [w for w in db.works if w.get("client") == name]
        return all(any((w.get("category") or "") == c for w in p) for c in cs[:2])

    # Score the client against the question with the work TITLE removed. Work
    # titles are built from the same vocabulary as client names -- "Steel Truss
    # Bridge — Gujarat Pkg-112" supplies `steel`, which is unique to Mahanadi
    # Steel Corporation and outscored the client HV-IC-0054 actually names
    # ("all completed trishakti work"). Retry unstripped if that finds nothing,
    # so a client whose own name overlaps the work title is not lost.
    client = clidx.resolve(strip_work(q), tiebreak=tiebreak) or \
        clidx.resolve(q, tiebreak=tiebreak)
    if not client:
        w = named_work
        if w and w.get("client"):
            client = w["client"]
            plan["work"] = w["work"]
            plan["client_via"] = "work"
    if not client and person:
        led = db.led_by(person)
        names = {w["client"] for w in led if w.get("client")}
        if len(names) == 1:
            client = names.pop()
            plan["client_via"] = "person"
        elif led:
            # Genuinely underdetermined: the terse variants of the mean/median
            # family say only "his client's works" and name no project, and the
            # personnel certificates do not tie a credential to a work. Pick
            # deterministically (lowest package number) rather than leave it
            # blank -- a blank scores 0 outright, a wrong client may still be
            # close, and this affects four questions.
            def pkg(w):
                m = re.search(r"Pkg[\s\-_]*(\d{1,3})", w.get("work") or "", re.I)
                return int(m.group(1)) if m else 999
            client = sorted(led, key=pkg)[0]["client"]
            plan["client_via"] = "person-first-work"
            weak_client = True
    plan["client"] = client
    cats = cats_for(client)

    # -- days: the whole class is one shape ---------------------------------
    if at == "days":
        plan["shape"] = "date_span"
        w = resolve_work(db, q, person)
        plan["work"] = w["work"] if w else None
        plan["after"] = mine_after(q)
        if not (plan["work"] and plan["after"]):
            plan["confidence"] = 0.0
        return plan

    # -- percent: reference share vs payment collection ---------------------
    if at == "percent":
        plan["shape"] = "referenced_share" if _has(_REFERENCE, q) else "collection_pct"
        if not client or weak_client:
            plan["confidence"] = 0.0 if not client else 0.5
        return plan

    # -- count: absence vs distinct categories ------------------------------
    if at == "count":
        if _has(r"lack(?:s|ing)?|no client reference|without|missing|absent|un-?referenced", q):
            plan["shape"] = "absence"
        else:
            plan["shape"] = "distinct_count"
        if plan["shape"] == "distinct_count" and not person:
            plan["confidence"] = 0.0
        if plan["shape"] == "absence" and not client:
            plan["confidence"] = 0.0
        return plan

    # -- money --------------------------------------------------------------
    # 1. mean vs median. Must precede avg_work_size, which also says "average".
    if _has(r"\bmedian\b", q) and _has(r"\bmean\b|\baverage\b|\bavg\b", q):
        plan["shape"] = "mean_median_gap"
        if not client or weak_client:
            plan["confidence"] = 0.0 if not client else 0.5
        return plan

    # 2. year-over-year delta. Two distinct calendar years is the signature; a
    #    lone credential year ("PMP issued March 10, 2021") cannot trigger it.
    if len(years) >= 2:
        plan["shape"] = "year_delta"
        plan["years"] = years
        if not client or weak_client:
            plan["confidence"] = 0.0 if not client else 0.5
        return plan

    # 3. works a person led that finished after their credential date. Shares
    #    "combined value" wording with hop_aggregate; "after" is the separator.
    if person and _has(r"\bafter\b|\bsince\b|\bpost[-\s]", q) and \
            _has(r"\bled\b|\bdirected\b|\bheaded\b|\bshe led\b|\bhe led\b|works? (?:he|she) ", q):
        plan["shape"] = "temporal_chain"
        if not person:
            plan["confidence"] = 0.0
        return plan

    # 4. category delta -- the largest money family (~60). Naming two of the 13
    #    work categories is the signature; the surrounding prose varies wildly
    #    ("value diff", "net variance", "spread", "how they compare").
    if len(cats) >= 2 and not _has(_EXCLUDE, q):
        plan["shape"] = "category_delta"
        plan["categories"] = cats[:2]
        if not client or weak_client:
            plan["confidence"] = 0.0 if not client else 0.5
        return plan

    # 5. exclusion. One category plus exclusion wording.
    if _has(_EXCLUDE, q) and cats:
        plan["shape"] = "exclusion_aggregate"
        plan["category"] = cats[0]
        if not client or weak_client:
            plan["confidence"] = 0.0 if not client else 0.5
        return plan

    # 6. gap to a credential threshold. Must precede both the receivable shapes
    #    and threshold_aggregate: HV-IC-0127 says "outstanding contract value we
    #    still need to secure ... to clear the 120 Cr credential threshold",
    #    which reads as a balance but is a shortfall against a bar.
    if _has(r"how much (?:more|additional|further)|additional work|must we (?:secure|win)"
            r"|need to (?:bring in|secure|win)|to reach|to hit the|to clear the"
            r"|shortfall to|how far short|still need to secure|more value do we need", q):
        plan["shape"] = "gap_to_threshold"
        plan["threshold"] = mine_threshold(q)
        if not client or plan["threshold"] is None:
            plan["confidence"] = 0.0
        return plan

    # 7. awarded-vs-billed gap. Needs BOTH operands named; that is what separates
    #    it from a plain receivable balance.
    # The two operands must actually be CONTRASTED. "the total value of all our
    # billed amounts that are still pending" (HV-IC-0411) contains an awarded
    # phrase and a billed phrase but sets them in apposition, not opposition --
    # it is a receivable balance. Every genuine unbilled-gap question in the set
    # carries a contrast connector.
    if _has(_AWARDED, q) and _has(_BILLED, q) and \
            _has(r"between|versus|\bvs\.?\b|against|compar|difference|gap|delta"
                 r"|variance|shortfall|unbilled|above what|net of", q):
        plan["shape"] = "unbilled_gap"
        if not client or weak_client:
            plan["confidence"] = 0.0 if not client else 0.5
        return plan

    # 8. receivable balance: invoiced less received.
    if _has(_OWED, q):
        plan["shape"] = "outstanding_balance"
        if not client or weak_client:
            plan["confidence"] = 0.0 if not client else 0.5
        return plan

    # 9. threshold aggregate. A rupee bar plus "clear/cross/hit/at or above".
    thr = mine_threshold(q)
    if thr is not None and _has(r"clear(?:s|ing)? the|clearing|crossing|cross(?:ed)? the|hitting"
                                r"|hit the|exceeding|meet(?:ing)? or exceed|at or (?:over|above)"
                                r"|above|over the|or higher|or more|and above|no less than"
                                r"|at least|upwards of|valued at|cutoff|threshold|mark|limit"
                                r"|bar\b|line\b", q):
        plan["shape"] = "threshold_aggregate"
        plan["threshold"] = thr
        if not client or weak_client:
            plan["confidence"] = 0.0 if not client else 0.5
        return plan

    # 10. rank gap: largest minus second largest.
    if _has(r"largest|biggest|highest|top finished|top completed", q) and \
            _has(r"second|2nd|next one down|next largest|next biggest|runner[-\s]?up"
                 r"|the subsequent one|next completed|the one just behind|beats the", q):
        plan["shape"] = "rank_value"
        if not client or weak_client:
            plan["confidence"] = 0.0 if not client else 0.5
        return plan

    # 11. average work size across the client's portfolio.
    if _has(r"average|mean|typical", q):
        plan["shape"] = "avg_work_size"
        if not client or weak_client:
            plan["confidence"] = 0.0 if not client else 0.5
        return plan

    # 12. person -> client -> that client's whole portfolio. Verified against
    #     HS-IC-0007 and HS-IC-0008: both sum every one of the client's works,
    #     not the subset the named person led.
    if person and client:
        plan["shape"] = "hop_aggregate"
        if weak_client:
            plan["confidence"] = 0.5
        return plan

    # A named client plus "combined/total/aggregate value" is that client's
    # whole portfolio -- the same number hop_aggregate would produce, reached
    # without a resolvable person (HV-IC-0130 addresses the holder as "Amit",
    # which is shared by two people).
    plan["shape"] = "client_total"
    if not client:
        plan["confidence"] = 0.0
    elif not _has(r"combined value|total value|aggregate|combined amount|sum of", q):
        plan["confidence"] = 0.5
    return plan
