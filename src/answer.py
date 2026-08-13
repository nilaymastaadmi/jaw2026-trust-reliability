"""questions.json -> submission.jsonl, end to end.

Answering policy: never leave a question blank.  Under the scorer's bands a
blank scores 0, a wrong guess scores 0, and a rough guess can score 0.3 -- so
emitting a number is free upside on every question.  The fallback ladder is
logged per question so triage knows what was computed vs guessed.
"""
import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus
import executor
import llm
import router


# --------------------------------------------------------- LLM last resort
#
# Applied ONLY where the deterministic ladder has already given up and would
# emit `fallback:typical` -- a corpus-median guess.  Under this round's exact-
# match scoring that guess is worth exactly 0, and a wrong LLM answer is also
# worth exactly 0, so this can only add points and can never cost any.  It never
# touches a question the executor answered: a computed number always wins.
#
# This is the one place the model is allowed near a number, and it reads
# structured rows out of db.json rather than raw PDF text, so it is arithmetic
# over a verified extraction rather than extraction and arithmetic at once.

_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "number"},
        "basis": {"type": "string"},
    },
    "required": ["answer", "basis"],
    "additionalProperties": False,
}


def _context(db, plan, limit=60):
    """Compact, factual rows for the entity the router did manage to resolve."""
    client = plan.get("client")
    if not client and plan.get("work"):
        w = db.work(plan["work"])
        client = w["client"] if w else None
    if not client and plan.get("person"):
        led = db.led_by(plan["person"])
        client = led[0]["client"] if led else None

    if client:
        works = db.portfolio(client)[:limit]
        rows = [{k: w.get(k) for k in
                 ("work", "value", "completed", "category", "role", "has_ref", "grading")}
                for w in works]
        ctx = {"client": client, "works": rows}
        ar = db.receivables.get(client)
        if ar:
            ctx["receivables"] = ar
        return ctx
    # Nothing resolved: give the client roster so it can at least pick one.
    return {"clients": sorted({w["client"] for w in db.works if w.get("client")})}


def llm_last_resort(db, plan, q):
    """A number from the endpoint, or None.  Never raises."""
    if not llm.available():
        return None
    t = (q.get("answer_type") or "money").lower()
    unit = {"money": "an integer number of RUPEES (1 crore = 10000000, 1 lakh = 100000)",
            "count": "an integer count",
            "percent": "a percentage out of 100",
            "days": "an integer number of days"}.get(t, "a plain number")
    got = llm.chat_json(
        [{"role": "system", "content":
            "You answer questions about an infrastructure contractor from the JSON "
            "records given. Use ONLY those records. Compute carefully and return "
            "the final number with no units, no separators and no symbols."},
         {"role": "user", "content":
            f"Records:\n{json.dumps(_context(db, plan), default=str)[:60000]}\n\n"
            f"Question: {q['question']}\n\n"
            f"Answer with {unit}."}],
        schema=_ANSWER_SCHEMA,
        max_tokens=4096,
    )
    if not got or not isinstance(got.get("answer"), (int, float)):
        return None
    val = got["answer"]
    return round(val, 2) if t == "percent" else round(val)


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


# A fallback must produce the RIGHT KIND of number. Scoring is proportional --
# score = max(0, 1 - |got-gold|/gold) -- so answering a "how many works" question
# with a rupee total is not merely wrong, it is unboundedly wrong and scores 0.
# A plausible small integer scores something. Ladder per unit:
_FALLBACK_CHAIN = {
    "money":   ("client_total", "avg_work_size", "hop_aggregate"),
    "count":   ("distinct_count", "absence"),
    "percent": ("referenced_share",),
    "days":    ("date_span",),
}


def fallbacks(db, plan, q, corpus_medians):
    """Nearest shape of the CORRECT unit, then a corpus-typical value."""
    t = (q.get("answer_type") or "").lower()
    for shape in _FALLBACK_CHAIN.get(t, ("client_total",)):
        got = executor.run(db, {**plan, "shape": shape})
        if got is not None:
            return got, f"fallback:{shape}"

    # Nothing deterministic ran. Last resort, in order:
    #   1. the provided endpoint, reading db.json rows for this entity
    #   2. a corpus-typical value of the right unit
    # Under exact match (1) can only gain and (2) is worth 0 -- but (2) still
    # costs nothing, and a filled row is required, so keep both.
    got = llm_last_resort(db, plan, q)
    if got is not None:
        return got, "llm:last_resort"
    return corpus_medians.get(t, corpus_medians["money"]), "fallback:typical"


def answer_all(questions, use_llm=False, verbose=True):
    db = executor.DB()
    vals = [w["value"] for w in db.works if w.get("value")]
    # Typical value per unit, used only when no shape of the right unit can run.
    # Medians, not means: the value distribution is heavily right-skewed.
    per_client = {}
    for w in db.works:
        if w.get("client") and w.get("value") is not None:
            per_client.setdefault(w["client"], []).append(w["value"])
    medians = {
        "money": round(statistics.median([sum(v) for v in per_client.values()])),
        "count": round(statistics.median([len(v) for v in per_client.values()])),
        "days": 900,
        "percent": 50.0,
    }

    # Escalate only what the deterministic router is unsure about. The endpoint
    # is shared across finalists, so sending it 300 questions it cannot improve
    # wastes their capacity and our wall clock alike.
    llm_plans = {}
    if use_llm and llm.health():
        unsure = [q for q in questions
                  if router.route(db, q["question"], q.get("answer_type"))["confidence"] < 1.0]
        if verbose:
            print(f"[router] escalating {len(unsure)}/{len(questions)} low-confidence questions")
        try:
            llm_plans = router.route_llm(unsure, verbose=verbose)
            if verbose:
                print(f"[router] llm returned {len(llm_plans)} usable plans")
        except Exception as e:                  # must never end the run
            print(f"[router] llm backend failed ({e}); deterministic only")

    rows = []
    for q in questions:
        plan = router.route(db, q["question"], q.get("answer_type"))
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
    """CSV with a `question_id,answer` header -- the format the scorer reads.

    Scoring is proportional: score = max(0, 1 - |got-gold|/gold). So a wrong
    answer costs nothing beyond the credit it fails to earn, and a rough answer
    still scores. Never emit a blank: 0 is strictly worse than any estimate.
    """
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["question_id", "answer"])
        for r in rows:
            a = r["answer"]
            if a is None:
                a = 0
            if isinstance(a, float) and a.is_integer():
                a = int(a)
            w.writerow([r["qid"], a])
    return path


def score(rows):
    """Local scoring with the shipped bands, when golds are present."""
    def band(gold, got):
        # Proportional, matching the shipped scorer as of the 2026-08-10 release:
        #   score = max(0, 1 - |got - gold| / gold)
        # There are no bands. A 5% error scores 0.95, a 50% error 0.50.
        if got is None:
            return 0.0
        gold, got = float(gold), float(got)
        if gold == 0:
            return 1.0 if got == 0 else 0.0
        return max(0.0, 1.0 - abs(got - gold) / abs(gold))

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
    ap.add_argument("--docs", help="document estate root (walked recursively)")
    ap.add_argument("--questions", default=str(corpus.DATA / "sample_questions.json"))
    ap.add_argument("--out", default=str(corpus.WORK / "submission.csv"))
    ap.add_argument("--llm", action="store_true", help="escalate low-confidence to the LLM router")
    ap.add_argument("--per-question", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="allow overwriting a larger existing submission")
    a = ap.parse_args()
    if a.docs:
        corpus.set_docs_root(a.docs)

    questions = load_questions(a.questions)
    print(f"[answer] {len(questions)} questions")
    rows = answer_all(questions, use_llm=a.llm)
    corpus.WORK.mkdir(parents=True, exist_ok=True)

    # Refuse to shrink an existing submission. Running this with the default
    # --out while testing against the 23 samples silently replaced a finished
    # 371-row submission with 23 rows -- the file still looked valid. Losing 348
    # answers an hour before the deadline is not a recoverable mistake.
    out = Path(a.out)
    if out.exists() and not a.force:
        with open(out, newline="", encoding="utf-8") as fh:
            existing = max(0, sum(1 for _ in csv.reader(fh)) - 1)
        if existing > len(rows):
            raise SystemExit(
                f"[guard] {out.name} already holds {existing} answers; this run "
                f"produced only {len(rows)}.\n"
                f"[guard] Refusing to overwrite. Use a different --out, or pass "
                f"--force if you really mean to shrink it.")

    write_submission(rows, a.out)
    corpus.save_json("answer_log.json", rows)

    # Always verify what we just wrote, using the official reader when available.
    try:
        sys.path.insert(0, str(corpus.DATA))
        import evaluate as official
        parsed = official.read_submission(str(out))
        missing = {q["qid"] for q in questions} - set(parsed)
        print(f"[verify] official reader parsed {len(parsed)}/{len(rows)} rows; "
              f"missing qids: {len(missing)}")
        if missing:
            print(f"[verify] WARNING missing: {sorted(missing)[:5]}")
    except Exception as e:                      # never block on the check itself
        print(f"[verify] skipped ({e})")

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
    if a.llm:
        print(f"[llm] {llm.stats()}")
        used = sum(1 for r in rows if r["source"] == "llm:last_resort")
        print(f"[llm] answered {used} questions the deterministic ladder could not")
    unsure = [r for r in rows if r["confidence"] < 1.0 or r["source"] != "router"]
    if unsure:
        print(f"low-confidence / fallback: {len(unsure)}")
        for r in unsure[:12]:
            print(f"   {r['qid']}  conf={r['confidence']:.2f}  {r['source']}  {r['question'][:70]}")


if __name__ == "__main__":
    main()
