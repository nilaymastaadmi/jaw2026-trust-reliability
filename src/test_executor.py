"""Gate: does the executor reproduce all 25 sample golds?

This tests the EXECUTOR only.  Parameters are mined from the question text by
deterministic helpers and the shape is taken from the sample file, so a failure
here is an extraction or arithmetic bug, never a routing bug.  The router is
tested separately end-to-end.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus
import executor
from normalize import threshold_from_text, GRADES

QS = json.loads((corpus.DATA / "sample_questions.json").read_text(encoding="utf-8"))["questions"]


def mine_client(db, q):
    """Longest canonical client name that appears in the question."""
    hits = [c for c in db.clients if c.lower() in q.lower()]
    if hits:
        return max(hits, key=len)
    # 'Irrigation & Waterways Dept, Govt of UP' may appear with 'and' or no comma
    best, score = None, 0
    for c in db.clients:
        head = re.split(r"[,(]", c)[0].strip()
        if head and head.lower() in q.lower() and len(head) > score:
            best, score = c, len(head)
    return best


def mine_person(db, q):
    for name in db.persons:
        if name.lower() in q.lower():
            return name
    return None


def mine_work(db, q):
    m = re.search(r"([A-Z][\w&/.\- ]{4,60}?\s*[—–-]\s*[\w ]+Pkg-\d+)", q)
    if m:
        return m.group(1).strip()
    m = re.search(r"([\w &/.-]+?)\s+(?:project\s+)?in\s+([\w ]+)\s+Package\s+(\d+)", q, re.I)
    if m:
        return f"{m.group(1).strip()} — {m.group(2).strip()} Pkg-{m.group(3)}"
    return None


def mine_category(q):
    m = re.search(r"exclud(?:ing|e)\s+([a-z ]+?)(?:,|;|\.|\s+what|\s+what's|$)", q, re.I)
    return m.group(1).strip() if m else None


def mine_grading(q):
    for g in GRADES:
        if re.search(r"\b" + re.escape(g) + r"\b", q):
            return g
    return None


def mine_credential(q):
    m = re.search(r"\b(PMP|Six Sigma Black Belt|Six Sigma Green Belt|Six Sigma)\b", q, re.I)
    return m.group(1) if m else None


def plan_for(db, q, shape):
    text = q["question"]
    p = {"shape": shape,
         "client": mine_client(db, text),
         "person": mine_person(db, text),
         "work": mine_work(db, text),
         "credential": mine_credential(text)}
    if shape in ("threshold_aggregate", "gap_to_threshold"):
        p["threshold"] = threshold_from_text(text)
    if shape == "exclusion_aggregate":
        p["category"] = mine_category(text)
    if shape == "doc_filtered_aggregate":
        p["grading"] = mine_grading(text)
    if shape == "role_split":
        m = re.search(r"\b(Prime|JV Partner)\b", text, re.I)
        p["role"] = m.group(1) if m else "Prime"
    return p


def main():
    db = executor.DB()
    rows, bad = [], []
    for q in QS:
        plan = plan_for(db, q, q["shape"])
        got = executor.run(db, plan)
        gold = q["answer"]
        ok = got is not None and (
            abs(got - gold) < 1e-9 if abs(gold) < 100
            else abs(got - gold) / abs(gold) <= 0.005)
        rows.append((q["qid"], q["shape"], gold, got, ok))
        if not ok:
            bad.append((q, plan, got))

    w = max(len(r[1]) for r in rows)
    for qid, shape, gold, got, ok in rows:
        print(f"  {'OK ' if ok else 'XX '} {qid:11s} {shape:{w}s} gold={gold:<14} got={got}")
    print(f"\n{sum(1 for r in rows if r[4])}/{len(rows)} exact")

    for q, plan, got in bad:
        print(f"\n--- {q['qid']} ({q['shape']}) gold={q['answer']} got={got}")
        print(f"    plan: { {k: v for k, v in plan.items() if v} }")
        print(f"    Q: {q['question'][:150]}")
        for s in q.get("reasoning_steps", []):
            print(f"      {s}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
