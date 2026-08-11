"""Guards for the family classifier in classify.py.

Three levels of assurance, weakest last:

1. PUBLISHED GOLDS. The 21 worked samples, plus three answers the organisers
   printed in the dataset README as a submission-format example. Those three are
   real questions from the scored set (HV-IC-0001/0002/0003) with real values,
   and they cover three families the 21 samples do not pin down between them --
   most valuably `collection_pct`, whose 24 questions depend on the receivables
   workbook and on resolving a client through a named work, neither of which any
   sample exercises.

2. TOTAL COVERAGE. Every one of the 333 questions must produce a number. A blank
   scores zero outright, so a regression that silently drops a family to None is
   the most expensive failure mode available.

3. FAMILY CENSUS. The size of each family, as a canary. These counts are not
   ground truth -- they are what a careful read of all 333 questions produced --
   but a change in them means a rule started or stopped firing, and that should
   never happen silently. Update the census deliberately, never to make the test
   pass.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import classify
import corpus
import executor

# Printed in dataset/README.md under "How to submit". Real qids, real values.
README_GOLDS = {
    "HV-IC-0001": 2942400000,     # hop_aggregate: the client's WHOLE portfolio
    "HV-IC-0002": 1516600000,     # exclusion_aggregate: portfolio less one category
    "HV-IC-0003": 90.19,          # collection_pct: received/invoiced, client via work
}

CENSUS = {
    # outstanding_balance 25 -> 24 and unbilled_gap 24 -> 25: HV-IC-0381 asks
    # for "the outstanding balance against the total contract value", which is
    # the unbilled gap. The census is what caught it -- outstanding_balance held
    # 25 questions across only 24 clients, Arunodaya Infrastructure twice. It is
    # now one question per receivables client.
    "category_delta": 61, "outstanding_balance": 24, "collection_pct": 24,
    "unbilled_gap": 25, "date_span": 24, "avg_work_size": 24, "year_delta": 24,
    "exclusion_aggregate": 21, "threshold_aggregate": 21, "mean_median_gap": 19,
    "hop_aggregate": 18, "rank_value": 16, "temporal_chain": 11,
    "distinct_count": 9, "referenced_share": 7, "gap_to_threshold": 3,
    "client_total": 1, "absence": 1,
}


def _ctx():
    db = executor.DB()
    cats = classify.CategoryIndex({w["category"] for w in db.works if w.get("category")})
    clients = classify.ClientIndex(db.all_clients())
    return db, cats, clients


def _close(got, gold):
    if got is None:
        return False
    return abs(float(got) - float(gold)) <= max(1e-9, abs(float(gold)) * 0.005)


def main():
    db, cats, clients = _ctx()
    fail = 0

    print("--- 21 published samples ---")
    samples = json.loads((corpus.DATA / "sample_questions.json")
                         .read_text(encoding="utf-8"))["questions"]
    ok = 0
    for q in samples:
        plan = classify.plan_for(db, q["question"], q.get("answer_type"), cats, clients)
        got = executor.run(db, plan)
        if _close(got, q["answer"]):
            ok += 1
        else:
            print(f"  FAIL {q['qid']:12} gold={q['answer']} got={got} plan={plan}")
    print(f"  {ok}/{len(samples)} exact")
    fail += len(samples) - ok

    questions = json.loads((corpus.DATA / "questions.json")
                           .read_text(encoding="utf-8"))["questions"]
    by_id = {q["qid"]: q for q in questions}

    print("--- README example answers (real scored questions) ---")
    for qid, gold in README_GOLDS.items():
        q = by_id.get(qid)
        if not q:
            print(f"  SKIP {qid} absent from the question set")
            continue
        plan = classify.plan_for(db, q["question"], q.get("answer_type"), cats, clients)
        got = executor.run(db, plan)
        mark = "OK " if _close(got, gold) else "FAIL"
        if mark == "FAIL":
            fail += 1
        print(f"  {mark} {qid} {plan['shape']:22} gold={gold} got={got}")

    print("--- coverage: every question answers ---")
    blanks, census = [], {}
    for q in questions:
        plan = classify.plan_for(db, q["question"], q.get("answer_type"), cats, clients)
        census[plan["shape"]] = census.get(plan["shape"], 0) + 1
        if executor.run(db, plan) is None:
            blanks.append((q["qid"], plan["shape"]))
    if blanks:
        fail += len(blanks)
        for qid, shape in blanks[:15]:
            print(f"  FAIL {qid} {shape} produced no number")
    print(f"  {len(questions) - len(blanks)}/{len(questions)} answered")

    print("--- every executor shape is reachable from a question ---")
    # The tie-break runs this harness against unseen questions, so a shape the
    # classifier can never emit is dead weight that will simply be missed.
    # Five were in exactly that state -- role_split, doc_filtered_aggregate,
    # year_total, invoiced_total and received_total existed in the executor
    # with no rule able to select them.
    probes = [
        ("role_split", "What is the total value of work we delivered as Prime for "
                       "Mahanadi Steel Corporation?", "money"),
        ("doc_filtered_aggregate", "For Trishakti Power Generation Corporation, what is "
                                   "the combined value of the works graded Excellent?", "money"),
        ("year_total", "What was the completed work value for Suvarna Projects "
                       "Limited in 2018?", "money"),
        ("invoiced_total", "What is the total amount we have invoiced to "
                           "Mega Infrastructure Authority?", "money"),
        ("received_total", "How much have we actually received from Lakshya "
                           "Engineering & Construction in total?", "money"),
        ("client_total", "What is the combined value of all completed work for "
                         "Arunodaya Infrastructure?", "money"),
    ]
    unreachable = 0
    for want, text, at in probes:
        plan = classify.plan_for(db, text, at, cats, clients)
        got = executor.run(db, plan)
        if plan["shape"] != want or got is None:
            unreachable += 1
            fail += 1
            print(f"  FAIL {want:24} routed to {plan['shape']!r}, value {got}")
    if not unreachable:
        print(f"  {len(probes)} shapes reachable, all returning a number")

    print("--- resolved client agrees with the named package ---")
    # The sharpest check available without golds. When a question names a
    # package number, that package's client is the client the question is
    # about, so any disagreement is a silent wrong answer. It caught three:
    # "Highway CONSTRUCTION — Rajasthan Pkg-77" resolving to Lakshya
    # Engineering & CONSTRUCTION, and "STEEL Truss Bridge — Gujarat Pkg-112" to
    # Mahanadi STEEL Corporation, both at full confidence.
    #
    # HV-IC-0130 is the one legitimate exception: it names a package and then
    # asks about a DIFFERENT client outright ("on your pkg-104 highway pmp,
    # what's the combined value of all completed subarnarekha work?").
    allowed_mismatch = {"HV-IC-0130"}
    mismatches = 0
    for q in questions:
        plan = classify.plan_for(db, q["question"], q.get("answer_type"), cats, clients)
        client = plan.get("client")
        pkgs = [int(m.group(1)) for m in
                __import__("re").finditer(r"pkg[\s\-_]*(\d{1,3})", q["question"], 2)]
        if not pkgs or not client or q["qid"] in allowed_mismatch:
            continue
        work = db._by_pkg.get(pkgs[0])
        if work and work.get("client") != client:
            mismatches += 1
            fail += 1
            print(f"  FAIL {q['qid']} pkg-{pkgs[0]} is {work['client']!r}"
                  f" but plan used {client!r}")
    if not mismatches:
        print("  no package/client disagreements")

    print("--- exclusion removes exactly one category ---")
    # "Buildings" and "Small Buildings" are substrings of one another, and the
    # loose matcher treated each as matching the other in BOTH directions.
    # Central Works & Buildings Bureau holds two Buildings works and one Small
    # Buildings, so "excluding small buildings" dropped all three.
    excl = 0
    for q in questions:
        plan = classify.plan_for(db, q["question"], q.get("answer_type"), cats, clients)
        if plan["shape"] != "exclusion_aggregate":
            continue
        port = db.portfolio(plan.get("client"))
        term = (plan.get("category") or "").strip().lower()
        want = sum(w["value"] for w in port if w.get("value") is not None
                   and (w.get("category") or "").strip().lower() != term)
        got = executor.run(db, plan)
        if got != want:
            excl += 1
            fail += 1
            print(f"  FAIL {q['qid']} excluding {plan.get('category')!r}:"
                  f" got {got} want {want}")
    if not excl:
        print("  all exclusions drop exactly the named category")

    # The census is pinned to the released 333-question set. Run against any
    # other question file -- the tie-break set, for instance -- the counts are
    # simply unknown, so it reports the distribution instead of failing. The
    # gold, coverage, package-agreement and exclusion checks above are
    # question-set independent and always assert.
    known_set = len(questions) == sum(CENSUS.values())
    print(f"--- family census ({'pinned' if known_set else 'informational'}) ---")
    if known_set:
        for shape in sorted(set(census) | set(CENSUS)):
            want, got = CENSUS.get(shape, 0), census.get(shape, 0)
            if want != got:
                fail += 1
                print(f"  FAIL {shape:24} expected {want:3}  got {got:3}")
        if not fail:
            print(f"  {len(CENSUS)} families all at expected size")
    else:
        for shape, n in sorted(census.items(), key=lambda kv: -kv[1]):
            print(f"  {shape:24} {n:4}")
        unreachable = sorted(set(executor.SHAPES) - set(census))
        if unreachable:
            print(f"  shapes not exercised by this set: {', '.join(unreachable)}")

    print()
    if fail:
        print(f"FAILURES: {fail}")
        sys.exit(1)
    print("ALL CLASSIFIER CHECKS PASS")


if __name__ == "__main__":
    main()
