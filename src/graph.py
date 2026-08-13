"""An entity store over the whole estate, and a compositional query over it.

WHY THIS EXISTS
---------------
executor.py holds 23 hand-written shapes. Each one answers exactly one kind of
question, and all 23 read from two places: the completed works and the
receivables ledger. That covers the released question set completely, and it
does not scale -- every new kind of question needs a new shape, a new router
rule, and a new test.

Measured against the corpus rather than against the question set, the ceiling is
obvious. Three datasets were already extracted and had no shape able to reach
them: the 211-item plant and machinery register, seven years of trial balance,
and the BOQ workbooks. Nine document types were never parsed at all.

So this module inverts the design. Instead of naming a shape per question, it
holds ENTITIES with typed fields and answers by composing three primitives:

    select   which entity type
    filter   zero or more predicates on its fields
    reduce   sum / count / mean / median / min / max / distinct

Every one of the 23 shapes is a special case. `client_total` is
sum(value) where client = X; `absence` is count where client = X and
has_ref = false. The point is not to replace them -- they are tested against
published golds and they stay -- but that a question nobody anticipated needs
new PARAMETERS here rather than new code.

Entities are derived, not re-extracted: works and people come from db.json,
assets, accounts, invoices and BOQ items from finance.json. Derived fields
(a work's state and year, a client's roll-ups) are computed once at load so
that questions about them need no traversal.
"""
import datetime
import re
import statistics

import corpus


def _year(iso):
    return int(str(iso)[:4]) if iso and str(iso)[:4].isdigit() else None


def _date(iso):
    try:
        return datetime.date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return None


class Graph:
    def __init__(self, db=None, fin=None, est=None):
        self.db = db or corpus.load_json("db.json")
        try:
            self.fin = fin if fin is not None else corpus.load_json("finance.json")
        except Exception:
            self.fin = {}
        try:
            self.est = est if est is not None else corpus.load_json("estate.json")
        except Exception:
            self.est = {}
        self.entities = {}
        self._build_works()
        self._build_people()
        self._build_finance()
        self._build_clients()
        self._build_estate()

    # ------------------------------------------------------------- builders
    def _build_works(self):
        out = []
        for w in self.db.get("works", []):
            title = w.get("work") or ""
            m = re.search(r"[—–-]\s*([A-Za-z ]+?)\s*Pkg", title)
            out.append({
                "work": title,
                "client": w.get("client"),
                "category": w.get("category"),
                "value": w.get("value"),
                "completed": w.get("completed"),
                "year": _year(w.get("completed")),
                "state": (m.group(1).strip() if m else None),
                "lead": w.get("lead"),
                "role": w.get("role"),
                "grading": w.get("grading"),
                "has_ref": bool(w.get("has_ref")),
            })
        self.entities["work"] = out

    def _build_people(self):
        works = self.entities["work"]
        out = []
        for p in self.db.get("persons", []):
            led = [w for w in works if w.get("lead") == p.get("name")]
            creds = p.get("credentials", []) or []
            out.append({
                "name": p.get("name"),
                "designation": p.get("designation"),
                "credentials": len(creds),
                "credential_names": [c.get("credential") for c in creds],
                "works_led": len(led),
                "value_led": sum(w["value"] for w in led if w.get("value")),
                "categories_led": len({w["category"] for w in led if w.get("category")}),
                "clients_served": len({w["client"] for w in led if w.get("client")}),
            })
        self.entities["person"] = out

    def _build_finance(self):
        rec = (self.fin.get("receivables") or {})
        inv = []
        for r in rec.get("invoices", []) or []:
            inv.append({
                "invoice_no": r.get("invoice_no"),
                "client": r.get("client"),
                "date": r.get("date"),
                "year": _year(r.get("date")),
                "invoiced": r.get("invoiced"),
                "received": r.get("received"),
                "outstanding": r.get("outstanding"),
                "status": r.get("status"),
            })
        self.entities["invoice"] = inv

        # The register's last row is a TOTAL, not an asset. Counting it makes
        # 210 items into 211 and puts a summary row in reach of every filter.
        self.entities["asset"] = [
            dict(a) for a in (self.fin.get("assets") or [])
            if str(a.get("asset_id") or "").strip().lower() not in ("total", "")]

        accounts = []
        for year, rows in (self.fin.get("trial_balance") or {}).items():
            for r in rows or []:
                accounts.append({
                    "year": year,
                    "account": r.get("account"),
                    "debit": r.get("debit"),
                    "credit": r.get("credit"),
                    "balance": r.get("balance"),
                })
        self.entities["account"] = accounts

        items = []
        for key, c in (self.fin.get("boq") or {}).items():
            for it in c.get("items", []) or []:
                items.append({
                    "contract_no": c.get("contract_no"),
                    "pkg": c.get("pkg"),
                    "description": it.get("description"),
                    "unit": it.get("unit"),
                    "quantity": it.get("quantity"),
                    "rate": it.get("rate"),
                    "amount": it.get("amount"),
                })
        self.entities["boq_item"] = items

    def _build_clients(self):
        works = self.entities["work"]
        rec = ((self.fin.get("receivables") or {}).get("by_client") or {})
        names = sorted({w["client"] for w in works if w.get("client")} | set(rec))
        out = []
        for n in names:
            mine = [w for w in works if w.get("client") == n]
            ar = rec.get(n) or {}
            vals = [w["value"] for w in mine if w.get("value") is not None]
            out.append({
                "client": n,
                "works": len(mine),
                "value": sum(vals),
                "largest": max(vals) if vals else None,
                "smallest": min(vals) if vals else None,
                "categories": len({w["category"] for w in mine if w.get("category")}),
                "referenced": sum(1 for w in mine if w.get("has_ref")),
                "unreferenced": sum(1 for w in mine if not w.get("has_ref")),
                "invoiced": ar.get("invoiced"),
                "received": ar.get("received"),
                "outstanding": ar.get("outstanding"),
            })
        self.entities["client"] = out

    def _build_estate(self):
        """The nine document types parse_documents.py reads.

        Rows are flattened to one level so that every question is a filter and a
        reduction over a table -- an audit is a row, not a field of a
        certificate, because "how many minor NCs did S. Kapoor raise" is a sum
        over audits. The nesting is kept alongside for anything that needs it.
        """
        e = self.est
        if not e:
            return

        def year_of(v):
            return _year(v)

        # A bond states a guarantee AND the percentage of contract value it
        # represents, so the contract value it secures is arithmetic the
        # document already contains.
        self.entities["bond"] = [{
            **b, "year": year_of(b.get("issue_date")),
            "expiry_year": year_of(b.get("valid_until")),
            "contract_value": (round(b["amount"] / (b["guarantee_pct"] / 100))
                               if b.get("amount") and b.get("guarantee_pct") else None),
        } for b in e.get("bonds", [])]

        self.entities["compliance"] = [dict(c) for c in e.get("compliance", [])]

        self.entities["iso_cert"] = [{k: v for k, v in c.items() if k != "audits"}
                                     for c in e.get("iso_certs", [])]
        self.entities["audit"] = [{**a, "cert_no": c.get("cert_no"),
                                   "standard": c.get("standard"),
                                   "year": year_of(a.get("date"))}
                                  for c in e.get("iso_certs", [])
                                  for a in c.get("audits", [])]

        self.entities["dossier"] = [{k: v for k, v in d.items() if k != "units"}
                                    for d in e.get("dossiers", [])]
        # Business units repeat identically across the six dossiers; a question
        # asking for head-count by unit wants six rows, not thirty-six.
        seen, units = set(), []
        for d in e.get("dossiers", []):
            for u in d.get("units", []):
                if u["unit"] in seen:
                    continue
                seen.add(u["unit"])
                units.append(dict(u))
        self.entities["business_unit"] = units

        self.entities["fin_line"] = [
            {"year": f.get("year"), "account": k,
             "current": v.get("current"), "previous": v.get("previous"),
             "balance": v.get("current"), "section": v.get("section"),
             "doc": f.get("doc")}
            for f in e.get("financials", []) for k, v in (f.get("lines") or {}).items()]

        self.entities["ra_bill"] = [{k: v for k, v in b.items() if k != "items"}
                                    for b in e.get("ra_bills", [])]
        self.entities["final_bill"] = [{k: v for k, v in b.items()
                                        if k not in ("items", "bills")}
                                       for b in e.get("final_bills", [])]
        self.entities["boq_line"] = [
            {**i, "contract": b.get("contract"), "client": b.get("client")}
            for b in e.get("final_bills", []) for i in b.get("items", [])] + [
            {**i, "contract": b.get("contract"), "client": b.get("client")}
            for b in e.get("ra_bills", []) for i in b.get("items", [])]

        # A transaction's size, whichever side of the account it fell on: "the
        # single largest transaction, deposit or withdrawal" needs one column.
        self.entities["bank_txn"] = [
            {**r, "year": s.get("year"), "doc": s.get("doc"),
             "amount": (r.get("deposit") or 0) + (r.get("withdrawal") or 0)}
            for s in e.get("bank", []) for r in s.get("rows", [])]
        self.entities["bank_year"] = [{k: v for k, v in s.items() if k != "rows"}
                                      for s in e.get("bank", [])]
        self.entities["ledger_account"] = [
            {k: v for k, v in a.items() if k != "rows"} | {"year": l.get("year")}
            for l in e.get("ledgers", []) for a in l.get("accounts", [])]
        self.entities["ledger_line"] = [
            {**r, "account": a.get("account"), "code": a.get("code"),
             "year": l.get("year")}
            for l in e.get("ledgers", []) for a in l.get("accounts", [])
            for r in a.get("rows", [])]

        # The board is the same board in both annual reports, so listing it
        # twice would answer "how many directors" with twelve.
        seen, dirs = set(), []
        for a in e.get("annual_reports", []):
            for d in a.get("directors", []):
                if d["name"] in seen:
                    continue
                seen.add(d["name"])
                dirs.append({**d, "year": a.get("year")})
        self.entities["director"] = dirs
        # The contractor's own copy of each completion certificate. Same 155
        # works, independently stated -- which is what lets the two be
        # cross-checked -- plus the defect liability period, which appears
        # nowhere else in the corpus.
        self.entities["company_cert"] = [dict(c) for c in e.get("company_certs", [])]

        self.entities["cv"] = [dict(c) for c in e.get("cvs", [])]

        # The certificates carry the credential's EXPIRY, which build_db does
        # not read: a validity span is arithmetic over two dates on one page.
        self.entities["credential"] = [dict(c) for c in e.get("credentials", [])]

        # The letterhead spells the client the way the letter's author typed
        # it, and twelve of the 132 shout it: "MAHANADI STEEL CORPORATION",
        # "MERIDIAN CONSTRUCTORS & CO.". A question writes the name the way the
        # rest of the corpus does, so filtering on the shouted spelling found
        # nothing. Where the letter names a work the estate knows, that work's
        # client IS this client, and its spelling is the canonical one -- taken
        # only when the two agree under case and punctuation, so a genuinely
        # different name is never overwritten.
        _canon = {}
        for w in self.entities.get("work", []):
            if w.get("work") and w.get("client"):
                _canon[w["work"]] = w["client"]

        def _key(c):
            return re.sub(r"[^a-z0-9]+", "", str(c or "").lower())

        letters = []
        for r in e.get("reference_letters", []):
            r = dict(r)
            c = _canon.get(r.get("work"))
            if c and r.get("client") and c != r["client"] and _key(c) == _key(r["client"]):
                r["client"] = c
            letters.append(r)
        self.entities["reference_letter"] = letters

        self.entities["dossier_standing"] = [dict(r) for r in e.get("dossier_standing", [])]

        # The annual reports' four tables, each a table in its own right: the
        # head of the report only summarises them.
        # Each report states two years of every segment -- the current column
        # and the previous-year comparative -- and the two reports overlap. Held
        # as one row per segment per FINANCIAL YEAR, a question naming a year
        # selects one cell instead of summing every copy of it.
        seg = {}
        for a in sorted(e.get("annual_tables", []), key=lambda x: x.get("year") or 0):
            y = a.get("year")
            for sgm in a.get("segments", []):
                if y is not None:
                    seg[(sgm["segment"], y)] = {"segment": sgm["segment"], "year": y,
                                                "current": sgm.get("current"),
                                                "previous": sgm.get("previous")}
                    seg.setdefault((sgm["segment"], y - 1),
                                   {"segment": sgm["segment"], "year": y - 1,
                                    "current": sgm.get("previous"), "previous": None})
        self.entities["segment"] = list(seg.values())
        self.entities["seven_year"] = [
            dict(r) for a in e.get("annual_tables", [])[-1:] for r in a.get("seven_year", [])]
        self.entities["ageing"] = [
            {**r, "year": a.get("year")}
            for a in e.get("annual_tables", [])[-1:] for r in a.get("ageing", [])]
        self.entities["principal_client"] = [
            {**r, "year": a.get("year")}
            for a in e.get("annual_tables", [])[-1:] for r in a.get("principal_clients", [])]
        # The two annual reports carry a byte-identical order-book note, so
        # holding both answers "how many contracts remained in execution" with
        # 34 rather than 17. The latest report is the one a question means.
        self.entities["order_book"] = [
            {k: v for k, v in a.items()
             if k not in ("segments", "seven_year", "ageing", "principal_clients",
                          "balance_sheet", "profit_and_loss", "quarters",
                          "variations", "order_lines", "credit_note_list")}
            for a in sorted(e.get("annual_tables", []),
                            key=lambda x: x.get("year") or 0)[-1:]]

        # The annual report's OWN balance sheet and profit and loss, stated
        # directly in rupees. They are not the financial statement's extract:
        # the same line names carry different figures, because the statement is
        # in lakhs and covers a different set of lines. A question naming the
        # annual report means these.
        self.entities["ar_balance"] = [
            {**r, "year": a.get("year"), "doc": a.get("doc")}
            for a in e.get("annual_tables", [])
            for r in a.get("balance_sheet", [])]
        self.entities["ar_pl"] = [
            {**r, "year": a.get("year"), "doc": a.get("doc")}
            for a in e.get("annual_tables", [])
            for r in a.get("profit_and_loss", [])]
        self.entities["quarter"] = [
            {**r, "doc": a.get("doc")} for a in e.get("annual_tables", [])
            for r in a.get("quarters", [])]
        self.entities["variation"] = [
            {**r, "year": a.get("year"), "doc": a.get("doc")}
            for a in e.get("annual_tables", [])
            for r in a.get("variations", [])]
        self.entities["credit_note"] = [
            {**r, "year": a.get("year"), "doc": a.get("doc")}
            for a in e.get("annual_tables", [])
            for r in a.get("credit_note_list", [])]
        # One row per contract in force, with what was awarded, what the
        # variations came to and the current value. Both reports print the
        # same 17 contracts, so the later one is the estate's position.
        self.entities["order_line"] = [
            {**r, "year": a.get("year"), "doc": a.get("doc")}
            for a in sorted(e.get("annual_tables", []),
                            key=lambda x: x.get("year") or 0)[-1:]
            for r in a.get("order_lines", [])]

        self.entities["ar_line"] = [
            {"year": a.get("year"), "account": k, "current": v.get("current"),
             "previous": v.get("previous"), "balance": v.get("current")}
            for a in e.get("annual_reports", [])
            for k, v in (a.get("highlights") or {}).items()]

    # -------------------------------------------------------------- queries
    OPS = {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "gt": lambda a, b: a > b,
        "gte": lambda a, b: a >= b,
        "lt": lambda a, b: a < b,
        "lte": lambda a, b: a <= b,
        "contains": lambda a, b: b.lower() in str(a).lower(),
        # Presence. select() already drops a row whose value is None before any
        # comparison runs, so "the field is stated" is a filter that always
        # holds for the rows that reach the predicate -- which is exactly what
        # "how many of the forty matrices state an EMD percentage" asks for.
        "exists": lambda a, b: bool(b),
    }

    def _apply(self, entity, filters):
        rows = self.entities.get(entity) or []
        for field, op, value in (filters or []):
            fn = self.OPS.get(op)
            if not fn:
                return []
            kept = []
            for r in rows:
                v = r.get(field)
                if v is None:
                    continue
                try:
                    if fn(v, value):
                        kept.append(r)
                except TypeError:
                    continue
            rows = kept
        return rows

    def select(self, entity, filters=None):
        """Rows matching every filter, with NULL read as "not stated".

        A blank field is not a mismatch, it is an absence. Only 44 of the 132
        reference letters use the template that states a category at all, so
        "the Water Treatment Plant project in Madhya Pradesh -- what value does
        it state" resolved both the work and the category, and the category the
        letter never records emptied the table.

        Where the full filter set selects nothing, a filter is dropped only if
        the column it names is unstated on EVERY row the other filters select.
        That is the case where the filter can carry no information. A column
        that IS stated there and simply disagrees keeps its filter, so a real
        zero stays a zero.
        """
        rows = self._apply(entity, filters)
        if rows or not filters or len(filters) < 2:
            return rows
        keep, dropped = list(filters), True
        while dropped and len(keep) > 1:
            dropped = False
            for f in list(keep):
                others = [g for g in keep if g is not f]
                cand = self._apply(entity, others)
                if cand and all(r.get(f[0]) is None for r in cand):
                    keep, dropped = others, True
                    break
        return self._apply(entity, keep) if len(keep) < len(filters) else rows

    def reduce(self, rows, fn, field=None):
        if fn == "count":
            return len(rows)
        if fn == "distinct":
            return len({r.get(field) for r in rows if r.get(field) is not None})
        vals = [r.get(field) for r in rows if isinstance(r.get(field), (int, float))]
        if not vals:
            return None
        if fn == "sum":
            return sum(vals)
        if fn == "mean":
            return round(sum(vals) / len(vals))
        if fn == "median":
            return round(statistics.median(vals))
        if fn == "min":
            return min(vals)
        if fn == "max":
            return max(vals)
        return None

    def run(self, plan):
        """plan = {entity, filters, fn, field} -> a number, or None.

        Two compositions on top of select/filter/reduce, because both are
        questions the corpus invites and neither is a single reduction:

          delta  the same query run for two years, subtracted. "By how much did
                 sub-contracting move between FY2022-23 and FY2023-24."
          ratio  two queries over the same rows, divided and scaled to 100.
                 "Profit after tax margin on total revenue, as a percentage."
        """
        if not plan or not plan.get("entity") or not plan.get("fn"):
            return None
        op = plan.get("op")
        if op == "delta" and len(plan.get("years") or ()) == 2:
            vals = []
            for y in plan["years"]:
                f = [x for x in plan.get("filters", []) if x[0] != "year"]
                f.append(("year", "eq", y))
                vals.append(self.run({**plan, "op": None, "filters": f}))
            if None in vals:
                return None
            return abs(vals[1] - vals[0]) if plan.get("absolute", True) \
                else vals[1] - vals[0]
        if op == "datespan" and len(plan.get("subjects") or ()) == 2:
            col, ent = plan.get("field", "completed"), plan["entity"]
            got = []
            for name in plan["subjects"]:
                row = next((r for r in self.entities.get(ent, [])
                            if r.get(plan.get("key", "work")) == name), None)
                d = _date(row.get(col)) if row else None
                if d is None:
                    return None
                got.append(d)
            return abs((got[1] - got[0]).days)
        if op == "diff" and plan.get("subtrahend") is not None:
            # Two values of one column, subtracted. "Take the total value of
            # completed Tunnels works and subtract the total value of completed
            # Expressways works" -- one table, one column, two selections.
            a = self.run({**plan, "op": None})
            b = self.run({**plan, "op": None, "filters": plan["subtrahend"],
                          "field": plan.get("field_b", plan.get("field"))})
            if a is None or b is None:
                return None
            return abs(a - b) if plan.get("absolute") else a - b
        if op == "argsel" and plan.get("by"):
            # The value of one column on the row that maximises ANOTHER: "the
            # amount on the most recently issued bond", "the year the first
            # Large Bridges work completed". A reduction returns a number from
            # a column; this returns a number from the ROW a column picks.
            rows = self.select(plan["entity"], plan.get("filters"))
            keyed = [r for r in rows if r.get(plan["by"]) is not None]
            if not keyed:
                return None
            pick = (max if plan.get("dir", "max") == "max" else min)(
                keyed, key=lambda r: str(r[plan["by"]]))
            v = pick.get(plan.get("field"))
            return v if isinstance(v, (int, float)) else None
        # `in`, not truthiness: an EMPTY denominator filter list is the whole
        # table, which is exactly what "share of our total exposure" divides by.
        # A date, expressed as the number of days from an origin the question
        # states. The reduction picks WHICH date; the subtraction is arithmetic
        # the question asked for outright.
        if op == "epoch" and plan.get("origin"):
            rows = self.select(plan["entity"], plan.get("filters"))
            days = [_date(r.get(plan["field"])) for r in rows]
            days = [d for d in days if d is not None]
            if not days:
                return None
            pick = min(days) if plan.get("fn") == "min" else max(days)
            origin = _date(plan["origin"])
            return (pick - origin).days if origin else None
        if op == "ratio" and plan.get("denominator") is not None:
            num = self.run({**plan, "op": None})
            den = self.run({**plan, "op": None, "filters": plan["denominator"]})
            if num is None or not den:
                return None
            return round(num / den * 100, 2)
        rows = self.select(plan["entity"], plan.get("filters"))
        if not rows:
            # An empty selection is a real answer for a COUNT -- "how many
            # bonds are still live" is zero, not unknown -- but only when every
            # column the filters name actually exists. Filtering on a column
            # the table does not have empties it for the wrong reason, and
            # there the honest answer is nothing.
            table = self.entities.get(plan["entity"])
            if not table:
                return None        # no such table: an empty count is fabricated
            cols = set(table[0])
            if plan["fn"] == "count" and all(
                    f[0] in cols for f in (plan.get("filters") or [])):
                return 0
            return None
        return self.reduce(rows, plan["fn"], plan.get("field"))

    def fields(self, entity):
        rows = self.entities.get(entity) or []
        return sorted(rows[0]) if rows else []

    def summary(self):
        return {k: len(v) for k, v in self.entities.items()}
