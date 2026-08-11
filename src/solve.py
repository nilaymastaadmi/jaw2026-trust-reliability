"""Solve for the residual error from the scaling-probe measurement.

Probe c007dac scaled 134 answers (category_delta, unbilled_gap,
outstanding_balance, collection_pct) by 1.05 and scored 97.782, against 99.775
unscaled.

Scaling an answer by (1+d) costs exactly d when the answer is already correct.
When it is wrong the contribution moves by d*(a/g): DOWN if we over-answered,
UP if we under-answered, because inflating an under-answer walks it toward the
gold. Writing L for a question's loss:

    exact              drop  =  d
    over-answer        drop  =  d*(1+L)          deviation  +d*L
    under-answer       drop  = -d*(1-L)          deviation  -d*(2-L)

Measured drop is SMALLER than the all-exact prediction, so the group holds an
under-answer -- our answer is below the gold. With n_u under-answers,

    2*n_u - (total loss inside the group) = measured_deviation / d

n_u = 2 already demands more loss than the whole set is missing, so n_u = 1:
a single question in that group answered LOW, and the gold is several times
our value. This module bounds that multiple and lists every question whose
alternative readings land inside it.
"""
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import classify
import corpus
import executor

BASE, PROBE, D = 99.775, 97.782, 0.05
GROUP = {"category_delta", "unbilled_gap", "outstanding_balance", "collection_pct"}


def main():
    db = executor.DB()
    cats = classify.CategoryIndex({w["category"] for w in db.works if w.get("category")})
    clients = classify.ClientIndex(db.all_clients())
    qs = json.loads((corpus.DATA / "questions.json").read_text(encoding="utf-8"))["questions"]
    cur = {r["question_id"]: float(r["answer"]) for r in
           csv.DictReader(open(corpus.WORK / "canonical.csv", encoding="utf-8"))}

    plans = {q["qid"]: classify.plan_for(db, q["question"], q.get("answer_type"),
                                         cats, clients) for q in qs}
    n = sum(1 for q in qs if plans[q["qid"]]["shape"] in GROUP)

    C = BASE * 333 / 100
    drop = C - PROBE * 333 / 100
    dev = D * n - drop                      # positive => less drop => under-answer
    print(f"group size {n}, all-exact drop {D * n:.4f}, measured drop {drop:.4f}")
    print(f"deviation {dev:+.5f} q-equiv  (positive = an UNDER-answer)")
    loss = 2 - dev / D
    print(f"=> one under-answer of loss {loss:.4f}; gold / ours = {1 / (1 - loss):.3f}")

    # measurement slack: both scores are rounded to 3 decimals
    lo_dev, hi_dev = dev - 0.0034, dev + 0.0034
    lo_L, hi_L = 2 - hi_dev / D, 2 - lo_dev / D
    lo_r, hi_r = 1 / (1 - lo_L), 1 / (1 - hi_L)
    print(f"   with rounding slack, gold / ours in [{lo_r:.2f}, {hi_r:.2f}]\n")

    print("candidates: alternative readings landing in that ratio band")
    print("(collection_pct is excluded outright -- a percentage cannot be 3x-5x)\n")
    for q in qs:
        p = plans[q["qid"]]
        if p["shape"] not in GROUP:
            continue
        a = cur[q["qid"]]
        if a == 0:
            continue
        cl, port = p.get("client"), db.portfolio(p.get("client"))
        vals = [w["value"] for w in port if w.get("value") is not None]
        ar = db.receivables.get(cl) or {}
        alts = {}
        if p["shape"] == "category_delta":
            c1, c2 = p["categories"][:2]

            def tot(c):
                return sum(w["value"] for w in port
                           if w.get("value") is not None and w.get("category") == c)
            alts["sum of the two categories"] = tot(c1) + tot(c2)
            alts["whole portfolio"] = sum(vals)
            alts["larger category alone"] = max(tot(c1), tot(c2))
        elif p["shape"] == "unbilled_gap":
            alts["awarded total"] = sum(vals)
            alts["invoiced"] = ar.get("invoiced")
            alts["awarded - received"] = (sum(vals) - ar["received"]) if ar else None
        elif p["shape"] == "outstanding_balance":
            alts["invoiced"] = ar.get("invoiced")
            alts["received"] = ar.get("received")
            alts["awarded - invoiced"] = (sum(vals) - ar["invoiced"]) if ar and vals else None
        for name, v in alts.items():
            if not v:
                continue
            r = abs(v) / abs(a)
            if lo_r <= r <= hi_r:
                print(f"  {q['qid']}  {p['shape']:20} {name:28} "
                      f"ours={a:,.0f}  alt={v:,.0f}  ratio={r:.3f}")


if __name__ == "__main__":
    main()
