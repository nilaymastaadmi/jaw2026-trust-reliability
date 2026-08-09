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
        self._by_key = {w["work_key"]: w for w in self.works}

    # ---------------------------------------------------------- resolution
    def client(self, name):
        """Resolve a client mention to one of the 28 canonical names."""
        if not name:
            return None
        n = name.strip().lower()
        for c in self.clients:
            if c.lower() == n:
                return c
        cands = [c for c in self.clients if n in c.lower() or c.lower() in n]
        if len(cands) == 1:
            return cands[0]
        if cands:                       # prefer the closest of several substring hits
            return max(cands, key=lambda c: difflib.SequenceMatcher(None, n, c.lower()).ratio())
        m = difflib.get_close_matches(name, self.clients, n=1, cutoff=0.6)
        return m[0] if m else None

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
