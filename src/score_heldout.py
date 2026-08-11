"""Score this harness against a held-out question file that carries answers.

Reports the official metric, a breakdown by topic and by difficulty, and the
worst individual misses with their stated derivations, so a disagreement can be
adjudicated against the documents rather than argued about.

    python score_heldout.py heldout.json answers.csv
"""
import csv
import json
import sys
from collections import defaultdict


def score_one(gold, got):
    if got is None:
        return 0.0
    gold, got = float(gold), float(got)
    if gold == 0:
        return 1.0 if got == 0 else 0.0
    return max(0.0, 1.0 - abs(got - gold) / abs(gold))


def main():
    qs = json.load(open(sys.argv[1], encoding="utf-8"))
    qs = qs["questions"] if isinstance(qs, dict) else qs
    got = {r["question_id"]: float(r["answer"])
           for r in csv.DictReader(open(sys.argv[2], encoding="utf-8"))}

    rows, by_topic, by_diff = [], defaultdict(list), defaultdict(list)
    for q in qs:
        s = score_one(q["answer"], got.get(q["qid"]))
        rows.append((s, q))
        by_topic[q.get("topic", "?")].append(s)
        by_diff[q.get("difficulty", "?")].append(s)

    total = sum(s for s, _ in rows)
    print(f"SCORE  {total / len(rows) * 100:.3f}   "
          f"({total:.2f} / {len(rows)} questions)")
    exact = sum(1 for s, _ in rows if s > 0.9995)
    zero = sum(1 for s, _ in rows if s < 0.0005)
    print(f"exact: {exact}   partial: {len(rows) - exact - zero}   zero: {zero}")

    print("\n--- by difficulty ---")
    for d in ("easy", "medium", "hard"):
        v = by_diff.get(d, [])
        if v:
            print(f"  {d:8} {sum(v) / len(v) * 100:6.2f}   "
                  f"({sum(1 for x in v if x > 0.9995)}/{len(v)} exact)")

    print("\n--- by topic, worst first ---")
    for t, v in sorted(by_topic.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
        print(f"  {sum(v) / len(v) * 100:6.2f}  "
              f"{sum(1 for x in v if x > 0.9995):2}/{len(v):2} exact   {t}")

    print("\n--- every question scoring below 1.0 ---")
    for s, q in sorted(rows, key=lambda r: r[0]):
        if s > 0.9995:
            continue
        print(f"\n  {q['qid']}  score {s:.3f}  [{q.get('difficulty')}] {q.get('topic')}")
        print(f"    Q      {q['question'][:150]}")
        print(f"    gold   {q['answer']}")
        print(f"    ours   {got.get(q['qid'])}")
        print(f"    deriv  {str(q.get('derivation'))[:150]}")


if __name__ == "__main__":
    main()
