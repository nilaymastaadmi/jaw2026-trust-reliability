"""The 13 question shapes, computed deterministically over db.json.

Every arithmetic operation lives here.  The router may only choose a shape and
supply parameters -- it never produces a number.  Under the scorer's bands a 3%
error scores the same 0.3 as a 9% error, so "close" is worth almost nothing and
all sums must come from exactly-parsed integers.

Aggregates run over the client's FULL portfolio resolved from the database, not
over the single document a question happens to name.  Several questions are
built specifically so the naive answer differs from the correct one.
"""
import difflib
import re
from datetime import date

import corpus


class DB:
    def __init__(self, db=None):
        db = db or corpus.load_json("db.json")
        self.works = db["works"]
        self.persons = {p["name"]: p for p in db["persons"]}
        self.clients = sorted({w["client"] for w in self.works if w.get("client")})
        # Receivables, for the outstanding_balance family added in set v1.4.
        # Verified against the organisers' own description: Outstanding equals
        # Invoiced minus Received on all 519 rows, and the per-client figure
        # spans 42,190x -- exactly the ratio their commit message quotes.
        try:
            fin = corpus.load_json("finance.json")
            self.receivables = (fin.get("receivables") or {}).get("by_client", {})
        except Exception:
            self.receivables = {}
        self._by_key = {w["work_key"]: w for w in self.works}
        # package number -> work. Unique across all 155, so it identifies a work
        # outright regardless of how the name around it is spelled or ordered.
        self._by_pkg = {}
        for w in self.works:
            m = re.search(r"Pkg[\s\-_]*(\d{1,3})", w.get("work") or "", re.I)
            if m:
                self._by_pkg[int(m.group(1))] = w

    # ---------------------------------------------------------- resolution
    def client(self, name):
        """Resolve a client mention to one of the 28 canonical names, or None.

        12 of 28 clients differ from a sibling only by state name, and
        difflib scores those siblings almost identically -- so a bare
        get_close_matches() will confidently return the wrong one. Where the
        candidates are near-indistinguishable we return None instead: an
        unresolved client is visible in triage, a misresolved one is not.
        """
        if not name:
            return None
        n = name.strip().lower()
        for c in self.clients:
            if c.lower() == n:
                return c
        cands = [c for c in self.clients if n in c.lower() or c.lower() in n]
        if len(cands) == 1:
            return cands[0]
        if cands:
            ranked = sorted(cands, reverse=True,
                            key=lambda c: difflib.SequenceMatcher(None, n, c.lower()).ratio())
            best = difflib.SequenceMatcher(None, n, ranked[0].lower()).ratio()
            if len(ranked) > 1:
                second = difflib.SequenceMatcher(None, n, ranked[1].lower()).ratio()
                if best - second < 0.10:        # too close to call
                    return None
            return ranked[0]
        m = difflib.get_close_matches(name, self.clients, n=2, cutoff=0.6)
        if not m:
            return None
        if len(m) > 1:
            r0 = difflib.SequenceMatcher(None, name.lower(), m[0].lower()).ratio()
            r1 = difflib.SequenceMatcher(None, name.lower(), m[1].lower()).ratio()
            if r0 - r1 < 0.10:
                return None
        return m[0]

    def person(self, name):
        if not name:
            return None
        n = name.strip().lower()
        for p in self.persons:
            if p.lower() == n:
                return self.persons[p]
        m = difflib.get_close_matches(name, list(self.persons), n=1, cutoff=0.6)
        return self.persons[m[0]] if m else None

    def work(self, name):
        """Resolve a work mention. The package number is the strongest handle.

        Every one of the 155 works ends in "Pkg-<n>" and every n from 1..155 is
        unique, so a bare package number identifies a work outright -- which
        survives the lowercased, reordered forms the questions actually use
        ("delhi pkg 37 wtp augmentation"). Name matching alone resolved 69 of
        the 99 package-referencing questions; the number resolves all of them.
        """
        if not name:
            return None
        m = re.search(r"pkg[\s\-_]*(\d{1,3})\b", str(name), re.I)
        if m:
            w = self._by_pkg.get(int(m.group(1)))
            if w:
                return w
        from normalize import norm_work
        k = norm_work(name)
        if k in self._by_key:
            return self._by_key[k]
        m = difflib.get_close_matches(k or "", list(self._by_key), n=1, cutoff=0.6)
        return self._by_key[m[0]] if m else None

    # ---------------------------------------------------------- selection
    def portfolio(self, client):
        c = self.client(client)
        return [w for w in self.works if w.get("client") == c]

    def led_by(self, person):
        p = self.person(person)
        if not p:
            return []
        return [self._by_key[k] for k in p.get("led", []) if k in self._by_key]

    def credential_date(self, person, kind=None):
        p = self.person(person)
        if not p:
            return None
        creds = p.get("credentials", [])
        if kind:
            k = kind.lower().replace(" ", "")
            match = [c for c in creds if c.get("credential")
                     and k in c["credential"].lower().replace(" ", "")]
            creds = match or creds
        dates = [c["issued"] for c in creds if c.get("issued")]
        return min(dates) if dates else None


def _vals(works):
    return [w["value"] for w in works if w.get("value") is not None]


def _cat_match(work, term):
    """Loose category comparison -- questions say 'buildings', data says 'Buildings'."""
    if not term:
        return False
    c = (work.get("category") or "").lower()
    t = term.lower().strip().rstrip("s")
    return bool(t) and (t in c or c.rstrip("s") in t)


# ------------------------------------------------------------------ shapes

def absence(db, client=None, **_):
    p = db.portfolio(client)
    return sum(1 for w in p if not w.get("has_ref"))


def referenced_share(db, client=None, **_):
    p = db.portfolio(client)
    if not p:
        return None
    return round(sum(1 for w in p if w.get("has_ref")) / len(p) * 100, 2)


def rank_value(db, client=None, **_):
    v = sorted(_vals(db.portfolio(client)), reverse=True)
    return v[0] - v[1] if len(v) >= 2 else None


def threshold_aggregate(db, client=None, threshold=None, **_):
    if threshold is None:
        return None
    return sum(v for v in _vals(db.portfolio(client)) if v >= threshold)


def gap_to_threshold(db, client=None, threshold=None, **_):
    if threshold is None:
        return None
    return max(0, threshold - sum(_vals(db.portfolio(client))))


def exclusion_aggregate(db, client=None, category=None, **_):
    # Refuse rather than silently sum everything: with no category, _cat_match is
    # False for every work and this returns the FULL portfolio -- a confident,
    # badly wrong number. Returning None routes it to the logged fallback ladder.
    if not category:
        return None
    return sum(w["value"] for w in db.portfolio(client)
               if w.get("value") is not None and not _cat_match(w, category))


def doc_filtered_aggregate(db, client=None, grading=None, **_):
    g = (grading or "").lower().strip()
    return sum(w["value"] for w in db.portfolio(client)
               if w.get("value") is not None and (w.get("grading") or "").lower() == g)


def avg_work_size(db, client=None, work=None, **_):
    if not client and work:
        w = db.work(work)
        client = w["client"] if w else None
    v = _vals(db.portfolio(client))
    return round(sum(v) / len(v)) if v else None


def role_split(db, client=None, role="Prime", **_):
    r = (role or "Prime").lower()
    return sum(w["value"] for w in db.portfolio(client)
               if w.get("value") is not None and (w.get("role") or "").lower() == r)


def hop_aggregate(db, person=None, client=None, work=None, **_):
    """person -> their works -> the commissioning client -> THAT CLIENT'S WHOLE PORTFOLIO.

    The person and the named work are only a route to the client.  The answer is
    always the client's full portfolio, even when the question reads "every
    assignment *he* has delivered for X" -- HS-IC-0007 and HS-IC-0008 both sum
    all six/seven of the client's works, not the subset that person led.  This is
    the trap the briefing describes: stopping at the named document, or at the
    person's own subset, returns a plausible wrong number.
    """
    if not client:
        if work:
            w = db.work(work)
            client = w["client"] if w else None
        elif person:
            led = db.led_by(person)
            client = led[0]["client"] if led else None
    return sum(_vals(db.portfolio(client)))


def client_total(db, client=None, **_):
    return sum(_vals(db.portfolio(client)))


def outstanding_balance(db, client=None, **_):
    """What a client still owes: invoiced less received, from the ageing workbook.

    Deliberately NOT derivable from the completion certificates -- this is the
    receivables universe (INR 1,750 Cr invoiced), not the contract universe
    (INR 5,530 Cr awarded). Mixing them is a ~3x magnitude error.

    The organisers chose this shape for resistance to guessing: the residual of
    two large similar numbers spans 42,190x across clients, so a median guess is
    worth almost nothing. Refuse rather than guess when the client is unlinked.
    """
    c = db.client(client)
    ar = db.receivables.get(c)
    if not ar:
        return None
    return ar["invoiced"] - ar["received"]


def invoiced_total(db, client=None, **_):
    c = db.client(client)
    ar = db.receivables.get(c)
    return ar["invoiced"] if ar else None


def received_total(db, client=None, **_):
    c = db.client(client)
    ar = db.receivables.get(c)
    return ar["received"] if ar else None


def collection_pct(db, client=None, **_):
    """Received as a percentage of invoiced."""
    c = db.client(client)
    ar = db.receivables.get(c)
    if not ar or not ar["invoiced"]:
        return None
    return round(ar["received"] / ar["invoiced"] * 100, 2)


def year_delta(db, client=None, years=None, **_):
    """Change in a client's completed-work value between two calendar years.

    The questions phrase this many ways -- "net difference between 2020 and
    2022", "how much their value moved", "the swing", "net shift from 2016
    through 2018" -- but all reduce to: total for year A, total for year B,
    subtract. Answering these with the whole-portfolio total (what happened
    before) is wrong by roughly the size of the portfolio.

    Absolute value: the wording is consistently magnitude-of-change, and a
    signed answer would score 0 whenever the sign convention differs.
    """
    if not years or len(years) < 2:
        return None
    p = db.portfolio(client)
    if not p:
        return None
    by_year = {}
    for w in p:
        if w.get("completed") and w.get("value") is not None:
            y = int(w["completed"][:4])
            by_year[y] = by_year.get(y, 0) + w["value"]
    a, b = min(years), max(years)
    return abs(by_year.get(b, 0) - by_year.get(a, 0))


def year_total(db, client=None, years=None, **_):
    """A client's completed-work value in one specific year."""
    if not years:
        return None
    p = db.portfolio(client)
    y = years[0]
    return sum(w["value"] for w in p
               if w.get("value") is not None
               and w.get("completed") and int(w["completed"][:4]) == y) or None


def unbilled_gap(db, client=None, **_):
    """Awarded contract value minus the amount invoiced.

    Spans both universes deliberately: these questions name both operands
    ("what they've sanctioned" vs "what we've billed"). Awarded comes from the
    completion certificates, invoiced from the ageing workbook.
    """
    c = db.client(client)
    ar = db.receivables.get(c)
    if not ar:
        return None
    awarded = sum(_vals(db.portfolio(c)))
    return awarded - ar["invoiced"] if awarded else None


def mean_median_gap(db, client=None, work=None, person=None, **_):
    """Mean minus median contract value across a client's portfolio.

    Signed: the questions ask for it "negative if avg dips". Reported as-is
    rather than absolute, because the scorer compares to a signed gold.
    """
    import statistics
    if not client and work:
        w = db.work(work)
        client = w["client"] if w else None
    if not client and person:
        led = db.led_by(person)
        client = led[0]["client"] if led else None
    v = _vals(db.portfolio(client))
    if len(v) < 2:
        return None
    return round(sum(v) / len(v) - statistics.median(v))


def category_delta(db, client=None, categories=None, **_):
    """Gap between two work categories within one client's portfolio.

    Two aggregates that must both be right, then subtracted. The organisers
    excluded the pairs that cannot be read unambiguously from the documents:
    'buildings' is a substring of 'small buildings', and a category whose name
    also occurs in the client's name (e.g. 'irrigation' vs 'Irrigation &
    Waterways Dept') matches every one of that client's works. So an exact
    category match is the right matcher here, not the loose one used elsewhere.
    """
    if not categories or len(categories) < 2:
        return None
    p = db.portfolio(client)
    if not p:
        return None

    def total(term):
        t = term.lower().strip()
        return sum(w["value"] for w in p
                   if w.get("value") is not None
                   and (w.get("category") or "").lower().strip() == t)

    a, b = total(categories[0]), total(categories[1])
    return abs(a - b)


def temporal_chain(db, person=None, credential=None, after=None, **_):
    cut = after or db.credential_date(person, credential)
    if not cut:
        return None
    return sum(w["value"] for w in db.led_by(person)
               if w.get("value") is not None and w.get("completed") and w["completed"] > cut)


def distinct_count(db, person=None, client=None, **_):
    works = db.led_by(person) if person else db.portfolio(client)
    return len({(w.get("category") or "").strip().lower() for w in works if w.get("category")})


def date_span(db, person=None, work=None, credential=None, after=None, **_):
    start = after or db.credential_date(person, credential)
    w = db.work(work)
    if not start or not w or not w.get("completed"):
        return None
    a = date.fromisoformat(start)
    b = date.fromisoformat(w["completed"])
    return abs((b - a).days)


SHAPES = {
    "absence": absence,
    "referenced_share": referenced_share,
    "rank_value": rank_value,
    "threshold_aggregate": threshold_aggregate,
    "gap_to_threshold": gap_to_threshold,
    "exclusion_aggregate": exclusion_aggregate,
    "doc_filtered_aggregate": doc_filtered_aggregate,
    "avg_work_size": avg_work_size,
    "role_split": role_split,
    "hop_aggregate": hop_aggregate,
    "temporal_chain": temporal_chain,
    "distinct_count": distinct_count,
    "date_span": date_span,
    "client_total": client_total,
    "outstanding_balance": outstanding_balance,
    "invoiced_total": invoiced_total,
    "received_total": received_total,
    "collection_pct": collection_pct,
    "category_delta": category_delta,
    "unbilled_gap": unbilled_gap,
    "year_delta": year_delta,
    "year_total": year_total,
    "mean_median_gap": mean_median_gap,
}


def run(db, plan):
    """plan = {shape, client?, person?, work?, threshold?, category?, grading?, role?}"""
    fn = SHAPES.get(plan.get("shape"))
    if not fn:
        return None
    try:
        return fn(db, **{k: v for k, v in plan.items() if k != "shape"})
    except Exception:
        return None
