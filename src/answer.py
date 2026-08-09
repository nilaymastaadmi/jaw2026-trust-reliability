"""questions.json -> submission.jsonl, end to end.

Answering policy: never leave a question blank.  Under the scorer's bands a
blank scores 0, a wrong guess scores 0, and a rough guess can score 0.3 -- so
emitting a number is free upside on every question.  The fallback ladder is
logged per question so triage knows what was computed vs guessed.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus
import executor
import router


def load_questions(path):
    """Accept whatever shape the validation file arrives in.

    The samples are {"questions": [...]}, but the validation drop is unseen and
    a loader crash at 3 PM costs more than any single question. Handles a
    top-level list, several envelope keys, JSONL, and id/text field aliases.
    """
    text = Path(path).read_text(encoding="utf-8").strip()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:                       # JSONL
        raw = [json.loads(ln) for ln in text.splitlines() if ln.strip()]

    if isinstance(raw, dict):
        for key in ("questions", "data", "items", "records", "rows"):
            if isinstance(raw.get(key), list):
                qs = raw[key]
                break
        else:
            qs = [raw] if "qid" in raw or "id" in raw else []
    else:
        qs = raw

    out = []
    for i, q in enumerate(qs):
        qid = next((q[k] for k in ("qid", "id", "question_id", "qID") if q.get(k)), None)
        question = next((q[k] for k in ("question", "text", "prompt", "query")
                         if q.get(k)), "")
        gold = next((q[k] for k in ("answer", "answer_gold", "gold", "expected")
                     if q.get(k) is not None), None)
        if qid is None:
            print(f"[load] warning: entry {i} has no qid; skipping", file=sys.stderr)
            continue
        out.append({"qid": str(qid), "question": question, "gold": gold,
                    "shape": q.get("shape"), "answer_type": q.get("answer_type")})
    if not out:
        raise SystemExit(f"[load] no questions parsed from {path} -- inspect the file")
    print(f"[load] {len(out)} questions from {Path(path).name}")
    return out


def fallbacks(db, plan, q, corpus_medians):
    """Ladder: nearest simpler shape -> client total -> corpus median."""
    tried = []
    if plan.get("client"):
        for shape in ("client_total", "avg_work_size"):
            got = executor.run(db, {**plan, "shape": shape})
            tried.append(shape)
            if got is not None:
                return got, f"fallback:{shape}"
    if plan.get("person"):
        got = executor.run(db, {**plan, "shape": "temporal_chain"})
        if got is not None:
            return got, "fallback:temporal_chain"
    t = (q.get("answer_type") or "").lower()
    med = corpus_medians.get(t if t in corpus_medians else "value")
    return med, "fallback:median"


def answer_all(questions, use_llm=False, verbose=True):
    db = executor.DB()
    vals = [w["value"] for w in db.works if w.get("value")]
    medians = {
        "value": round(statistics.median(vals)),
        "count": 3,
        "days": 900,
        "percent": 50.0,
        "percentage": 50.0,
    }

    llm_plans = {}
    if use_llm and router.llm_available():
        try:
            llm_plans = router.route_llm(questions)
            if verbose:
                print(f"[router] LLM classified {len(llm_plans)} questions")
        except Exception as e:
            print(f"[router] LLM backend failed ({e}); deterministic only")

    rows = []
    for q in questions:
        plan = router.route(db, q["question"])
        # LLM output only overrides where the deterministic router is unsure
        if q["qid"] in llm_plans and plan["confidence"] < 1.0:
            merged = {k: v for k, v in llm_plans[q["qid"]].items() if v is not None}
            plan = {**plan, **merged, "confidence": 1.0}
        got = executor.run(db, plan)
        source = "router"
        if got is None:
            got, source = fallbacks(db, plan, q, medians)
        rows.append({"qid": q["qid"], "answer": got, "shape": plan["shape"],
                     "confidence": plan["confidence"], "source": source,
                     "gold": q.get("gold"), "question": q["question"]})
    return rows


def write_submission(rows, path):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            a = r["answer"]
            if a is None:
                a = 0
            if isinstance(a, float) and a.is_integer():
                a = int(a)
            fh.write(json.dumps({"qid": r["qid"], "answer": a}) + "\n")
    return path


def score(rows):
    """Local scoring with the shipped bands, when golds are present."""
    def band(gold, got):
        if got is None:
            return 0.0
        gold, got = float(gold), float(got)
        if abs(gold) < 100:
            return 1.0 if got == gold else (0.3 if abs(got - gold) <= 1 else 0.0)
        err = abs(got - gold) / abs(gold)
        return 1.0 if err <= 0.005 else 0.7 if err <= 0.02 else 0.3 if err <= 0.10 else 0.0

    scored = [r for r in rows if r.get("gold") is not None]
    if not scored:
        return None
    per_shape = {}
    total = 0.0
    for r in scored:
        s = band(r["gold"], r["answer"])
        total += s
        acc = per_shape.setdefault(r["shape"], [0.0, 0])
        acc[0] += s
        acc[1] += 1
    return total, len(scored), per_shape


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(corpus.DATA / "sample_questions.json"))
    ap.add_argument("--out", default=str(corpus.WORK / "submission.jsonl"))
    ap.add_argument("--llm", action="store_true", help="escalate low-confidence to the LLM router")
    ap.add_argument("--per-question", action="store_true")
    a = ap.parse_args()

    questions = load_questions(a.questions)
    rows = answer_all(questions, use_llm=a.llm)
    corpus.WORK.mkdir(parents=True, exist_ok=True)
    write_submission(rows, a.out)
    corpus.save_json("answer_log.json", rows)

    result = score(rows)
    if a.per_question:
        for r in rows:
            mark = "" if r["gold"] is None else (
                "OK " if abs(float(r["answer"] or 0) - float(r["gold"])) < 1e-9
                or (abs(float(r["gold"])) >= 100
                    and abs(float(r["answer"] or 0) - float(r["gold"])) / abs(float(r["gold"])) <= 0.005)
                else "XX ")
            print(f"  {mark}{r['qid']:11s} {r['shape']:22s} conf={r['confidence']:.2f} "
                  f"{r['source']:20s} got={r['answer']}  gold={r['gold']}")
        print()
    if result:
        total, n, per_shape = result
        print(f"{'shape':24s} {'score':>7s} {'n':>3s}")
        for shape, (s, k) in sorted(per_shape.items(), key=lambda kv: kv[1][0] / max(kv[1][1], 1)):
            print(f"{shape:24s} {s:7.1f} {k:3d}   {s/max(k,1):.0%}")
        print(f"\nTOTAL {total:.1f} / {n} = {total/max(n,1):.1%}")
    print(f"\nwrote {a.out}")
    unsure = [r for r in rows if r["confidence"] < 1.0 or r["source"] != "router"]
    if unsure:
        print(f"low-confidence / fallback: {len(unsure)}")
        for r in unsure[:12]:
            print(f"   {r['qid']}  conf={r['confidence']:.2f}  {r['source']}  {r['question'][:70]}")


if __name__ == "__main__":
    main()
