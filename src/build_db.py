"""Fuse the document estate into work/db.json.

Field precedence follows source reliability established during recon:
  value/client/date/lead : CCC (uniform, one per work)  <- PPP <- CC
  role                   : PPP only source covering all 155
  grading                : CC prose (the client's own assessment)
  ref-letter link        : REF matched to work, diffed against the full 155

Nothing here approximates.  A field that cannot be read stays None so the
invariant check can see it, rather than being quietly defaulted.
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus
from normalize import norm_work
from parsers import parse_certificate, parse_reference, parse_personnel, parse_cv
from parse_portfolio import parse_portfolio


def _fill(dst, src, keys):
    """Copy keys from src into dst only where dst is missing a value."""
    for k in keys:
        if dst.get(k) in (None, "") and src.get(k) not in (None, ""):
            dst[k] = src[k]


def build(verbose=True):
    corpus.build_cache(verbose=verbose)

    ccc = [parse_certificate(d, t) for d, t in corpus.by_type("company_completion_certificate")]
    cc = [parse_certificate(d, t) for d, t in corpus.by_type("completion_certificate")]
    refs = [parse_reference(d, t) for d, t in corpus.by_type("reference_letter")]
    people = [parse_personnel(d, t) for d, t in corpus.by_type("personnel_certificate")]
    cvs = [parse_cv(d, t) for d, t in corpus.by_type("cv")]
    # By type, never by hardcoded doc_id: the estate we are run against is a
    # different instance of the same templates, so ids are not guaranteed.
    ppp = parse_portfolio(corpus.one_of_type("past_performance_portfolio"))

    # ---- works keyed on the normalised work name -------------------------
    works = {}
    for r in ccc:
        if not r["work_key"]:
            continue
        w = dict(r)
        w["ccc_id"] = r["doc_id"]
        w.pop("doc_id")
        works[r["work_key"]] = w

    by_seq = {}
    for p in ppp:
        by_seq[p["work_key"]] = p
        tgt = works.get(p["work_key"])
        if tgt is None:
            tgt = {"work": p["work"], "work_key": p["work_key"]}
            works[p["work_key"]] = tgt
        tgt["role"] = p.get("role")
        _fill(tgt, p, ["client", "category", "value", "completed"])

    for r in cc:
        tgt = works.get(r["work_key"])
        if tgt is None:
            continue
        tgt["cc_id"] = r["doc_id"]
        if r.get("grading"):
            tgt["grading"] = r["grading"]          # client's own assessment wins
        _fill(tgt, r, ["client", "category", "value", "completed", "lead", "certref"])

    # ---- reference letters ----------------------------------------------
    ref_keys, unmatched = set(), []
    for r in refs:
        if r["work_key"] and r["work_key"] in works:
            ref_keys.add(r["work_key"])
            works[r["work_key"]]["ref_id"] = r["doc_id"]
            if r.get("role") and not works[r["work_key"]].get("role"):
                works[r["work_key"]]["role"] = r["role"]
        else:
            unmatched.append((r["doc_id"], r["work"]))
    for k, w in works.items():
        w["has_ref"] = k in ref_keys

    # ---- people ----------------------------------------------------------
    persons = {}
    for p in people:
        if not p["name"]:
            continue
        rec = persons.setdefault(p["name"], {"name": p["name"], "credentials": []})
        rec["credentials"].append({
            "credential": p["credential"], "credential_id": p["credential_id"],
            "issued": p["issued"], "doc_id": p["doc_id"],
        })
        if p.get("emp_id"):
            rec["emp_id"] = p["emp_id"]
    for c in cvs:
        if c["name"]:
            rec = persons.setdefault(c["name"], {"name": c["name"], "credentials": []})
            rec["cv_id"] = c["doc_id"]
            if c.get("emp_id"):
                rec["emp_id"] = c["emp_id"]
            if c.get("designation"):
                rec["designation"] = c["designation"]

    # lead -> works they led
    led = defaultdict(list)
    for k, w in works.items():
        if w.get("lead"):
            led[w["lead"]].append(k)
    for name, keys in led.items():
        persons.setdefault(name, {"name": name, "credentials": []})["led"] = sorted(keys)

    db = {
        "works": sorted(works.values(), key=lambda w: (w.get("client") or "", w.get("work") or "")),
        "persons": sorted(persons.values(), key=lambda p: p["name"]),
        "unmatched_refs": unmatched,
    }
    corpus.save_json("db.json", db)
    if verbose:
        report(db)
    return db


def report(db):
    works = db["works"]
    clients = {w.get("client") for w in works if w.get("client")}
    total = sum(w["value"] for w in works if w.get("value"))
    missing = {k: sum(1 for w in works if not w.get(k))
               for k in ("client", "value", "completed", "category", "lead", "role", "grading")}
    print(f"\n[db] works={len(works)}  clients={len(clients)}  persons={len(db['persons'])}")
    print(f"[db] with ref letter={sum(1 for w in works if w.get('has_ref'))}  "
          f"without={sum(1 for w in works if not w.get('has_ref'))}  "
          f"unmatched ref docs={len(db['unmatched_refs'])}")
    print(f"[db] total value = INR {total/1e7:,.2f} Cr   (README says ~5,530 Cr)")
    print(f"[db] missing fields: {missing}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", help="document estate root (walked recursively)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    if args.docs:
        print(f"[db] docs root: {corpus.set_docs_root(args.docs)}")
    build(verbose=not args.quiet)
