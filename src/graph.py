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
import re
import statistics

import corpus


def _year(iso):
    return int(str(iso)[:4]) if iso and str(iso)[:4].isdigit() else None


class Graph:
    def __init__(self, db=None, fin=None):
        self.db = db or corpus.load_json("db.json")
        try:
            self.fin = fin if fin is not None else corpus.load_json("finance.json")
        except Exception:
            self.fin = {}
        self.entities = {}
        self._build_works()
        self._build_people()
        self._build_finance()
        self._build_clients()

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

        self.entities["asset"] = [dict(a) for a in (self.fin.get("assets") or [])]

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

    # -------------------------------------------------------------- queries
    OPS = {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "gt": lambda a, b: a > b,
        "gte": lambda a, b: a >= b,
        "lt": lambda a, b: a < b,
        "lte": lambda a, b: a <= b,
        "contains": lambda a, b: b.lower() in str(a).lower(),
    }

    def select(self, entity, filters=None):
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
        """plan = {entity, filters, fn, field} -> a number, or None."""
        if not plan or not plan.get("entity") or not plan.get("fn"):
            return None
        rows = self.select(plan["entity"], plan.get("filters"))
        if not rows:
            return None
        return self.reduce(rows, plan["fn"], plan.get("field"))

    def fields(self, entity):
        rows = self.entities.get(entity) or []
        return sorted(rows[0]) if rows else []

    def summary(self):
        return {k: len(v) for k, v in self.entities.items()}
