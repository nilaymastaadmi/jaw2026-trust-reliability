"""Independent re-extraction diff -- the teammate's harness.

The failure this catches is the one the scorer punishes hardest: a value that is
silently wrong. A number that is wrong-but-plausible looks exactly like a number
that is right, until two independent extractions disagree about it.

  Nilay  : company_completion_certificate x155  ->  work/db.json      (build_db.py)
  Mate   : past_performance_portfolio + completion_certificate x155
                                                ->  work/db_alt.json  (alt_extract.py)

The two routes share no parser. Agreement across all 155 works is the strongest
evidence available that the corpus was read correctly, and it exists before the
leaderboard does.

Teammate contract: write ONLY src/alt_extract.py, emitting work/db_alt.json with
  {"works": [{"work": str, "value": int, "client": str,
              "completed": "YYYY-MM-DD", "lead": str, "role": str}]}
Nothing else is shared, so there are no merge conflicts.

    python reconcile.py            # diff db.json against db_alt.json
    python reconcile.py --selftest # prove the harness catches a seeded error
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus
from normalize import norm_work, norm_client

FIELDS = ["value", "client", "completed", "lead", "role"]


def index(db):
    out = {}
    for w in db.get("works", []):
        key = w.get("work_key") or norm_work(w.get("work"))
        if key:
            out[key] = w
    return out


def compare(a, b):
    ka, kb = set(a), set(b)
    report = {
        "only_in_primary": sorted(ka - kb),
        "only_in_alt": sorted(kb - ka),
        "mismatches": [],
        "agreed": 0,
    }
    for key in sorted(ka & kb):
        wa, wb = a[key], b[key]
        diffs = {}
        for f in FIELDS:
            va, vb = wa.get(f), wb.get(f)
            if va is None or vb is None:          # field absent from one route
                continue
            if f == "client":
                va, vb = norm_client(va), norm_client(vb)
            if f == "value":
                # the corpus renders money to 2dp in crore, so sub-rupee
                # disagreement is rendering, not a parse error
                if abs(int(va) - int(vb)) <= 2:
                    continue
            if va != vb:
                diffs[f] = {"primary": va, "alt": vb}
        if diffs:
            report["mismatches"].append({"work": wa.get("work"), "key": key, "diffs": diffs})
        else:
            report["agreed"] += 1
    return report


def render(report, total_primary, total_alt):
    lines = ["# Reconciliation report", "",
             f"- primary works: {total_primary}",
             f"- alt works:     {total_alt}",
             f"- agreed:        {report['agreed']}",
             f"- mismatched:    {len(report['mismatches'])}",
             f"- only primary:  {len(report['only_in_primary'])}",
             f"- only alt:      {len(report['only_in_alt'])}", ""]
    if report["mismatches"]:
        lines += ["## Mismatches", "",
                  "Every row is a real bug in one of the two routes. Resolve by",
                  "opening the underlying document and reading the field.", ""]
        for m in report["mismatches"]:
            lines.append(f"### {m['work']}")
            for f, v in m["diffs"].items():
                lines.append(f"- **{f}** — primary `{v['primary']}` vs alt `{v['alt']}`")
            lines.append("")
    for label, key in (("Only in primary", "only_in_primary"), ("Only in alt", "only_in_alt")):
        if report[key]:
            lines += [f"## {label}", ""] + [f"- `{k}`" for k in report[key]] + [""]
    if not report["mismatches"] and not report["only_in_primary"] and not report["only_in_alt"]:
        lines += ["## Clean", "",
                  "Both routes agree on every work across every shared field.", ""]
    return "\n".join(lines)


def selftest():
    """Prove the harness detects a disagreement rather than reporting clean."""
    primary = corpus.load_json("db.json")
    works = primary["works"]
    seeded = {"works": [dict(w) for w in works]}
    # perturb three works in ways the corpus could plausibly produce
    seeded["works"][0]["value"] = (seeded["works"][0]["value"] or 0) + 100_000
    seeded["works"][1]["completed"] = "1999-01-01"
    seeded["works"][2]["lead"] = "Wrong Person"
    rep = compare(index(primary), index(seeded))
    ok = len(rep["mismatches"]) == 3
    print(f"selftest: seeded 3 disagreements, harness found {len(rep['mismatches'])}"
          f" -> {'PASS' if ok else 'FAIL'}")
    for m in rep["mismatches"]:
        print(f"   {m['work']}: {list(m['diffs'])}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", default="db.json")
    ap.add_argument("--alt", default="db_alt.json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    if not (corpus.WORK / a.alt).exists():
        print(f"[reconcile] {a.alt} not present yet -- teammate has not produced it.")
        print("[reconcile] harness is ready; verify it works with --selftest")
        return 0

    primary, alt = corpus.load_json(a.primary), corpus.load_json(a.alt)
    rep = compare(index(primary), index(alt))
    text = render(rep, len(primary.get("works", [])), len(alt.get("works", [])))
    (corpus.WORK / "recon_report.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"\nwrote {corpus.WORK / 'recon_report.md'}")
    return 1 if rep["mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
