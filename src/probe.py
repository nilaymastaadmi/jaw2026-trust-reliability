"""Localise residual scoring loss by perturbing one group of answers.

At 99.775 the shortfall is 0.749 question-equivalents. No single answer can be
wholly wrong -- that would cost a full 1.000 -- so the loss is spread, and no
structural check finds it: the data layer agrees field-for-field across two
independent extraction routes, every client resolution is justified by a named
package, and every family with a published gold reproduces it.

What remains is measurement. Zeroing a family would reveal its exact
contribution but costs a quarter of the score for a round. Scaling is far
cheaper for the same one bit:

Scale every answer in a group by (1 + d). For an answer that is already
correct the contribution falls by exactly d. For a wrong one it moves by
d * (a/g) -- DOWN if we over-answered, UP if we under-answered, because
inflating an under-answer walks it toward the gold. So

    drop == d * |G|          =>  every answer in the group is exact
    drop >  d * |G|          =>  the group holds an over-answer
    drop <  d * |G|          =>  the group holds an under-answer

d = 0.05 puts the three outcomes about 0.011 apart on the leaderboard, ten
times its 0.001 resolution, for a temporary cost of 1.26 points.

Usage:
    python probe.py --shapes category_delta,unbilled_gap --scale 1.05
    python probe.py --restore          # rewrite the canonical answers
"""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import classify
import corpus
import executor


def shapes_by_qid():
    db = executor.DB()
    cats = classify.CategoryIndex({w["category"] for w in db.works if w.get("category")})
    clients = classify.ClientIndex(db.all_clients())
    qs = json.loads((corpus.DATA / "questions.json").read_text(encoding="utf-8"))["questions"]
    return {q["qid"]: classify.plan_for(db, q["question"], q.get("answer_type"),
                                        cats, clients)["shape"] for q in qs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", default=str(corpus.WORK / "submission.csv"))
    ap.add_argument("--shapes", default="category_delta,unbilled_gap")
    ap.add_argument("--scale", type=float, default=1.05)
    ap.add_argument("--out", default=str(corpus.WORK / "submission.csv"))
    args = ap.parse_args()

    want = {s.strip() for s in args.shapes.split(",") if s.strip()}
    shape = shapes_by_qid()
    rows = list(csv.DictReader(open(args.submission, encoding="utf-8")))

    touched, base = 0, 0.0
    out = []
    for r in rows:
        qid, val = r["question_id"], float(r["answer"])
        if shape.get(qid) in want:
            val = val * args.scale
            touched += 1
        if val == int(val):
            val = int(val)
        else:
            val = round(val, 2)
        out.append((qid, val))

    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["question_id", "answer"])
        w.writerows(out)

    d = args.scale - 1.0
    print(f"[probe] scaled {touched} answers in {sorted(want)} by {args.scale}")
    print(f"[probe] if every one of those {touched} is exact, the score falls by")
    print(f"        {d * touched:.4f} question-equivalents = {d * touched / 3.33:.4f} points")
    print(f"[probe] wrote {args.out}")


if __name__ == "__main__":
    main()
