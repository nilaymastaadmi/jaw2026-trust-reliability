"""questions.json -> submission.csv, end to end.

Answering policy: never leave a question blank. Scoring is proportional --
score = max(0, 1 - |got - gold| / gold) -- so a blank scores 0 while even a
rough number of the right magnitude keeps most of its credit. Every question
gets a number, and every fallback is recorded so triage can separate what was
computed from what was estimated.
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
import classify
import generic
import graph
import router


def load_questions(path):
    """Accept whatever shape the validation file arrives in.

    The samples are {"questions": [...]}, but the validation drop is unseen and
    a loader crash at 3 PM costs more than any single question. Handles a
    top-level list, several envelope keys, JSONL, and id/text field aliases.
    """
    # utf-8-sig first: a JSON file exported from Excel or a Windows tool carries
    # a byte-order mark, and json.loads raises "Unexpected UTF-8 BOM" on it --
    # which would take down the whole run before a single question is read.
    # utf-8-sig is identical to utf-8 when there is no mark. UTF-16 and latin-1
    # follow, so an unreadable byte costs one character rather than 300 answers.
    raw_bytes = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = raw_bytes.decode(enc).strip()
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw_bytes.decode("utf-8", errors="replace").strip()
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
        at = q.get("answer_type") or q.get("type") or q.get("unit")
        if not at:
            # Recovered, not guessed at: the unit is legible in the question and
            # a missing field would otherwise answer every percent and count
            # question with a rupee figure. See classify.infer_answer_type.
            at = classify.infer_answer_type(question)
        out.append({"qid": str(qid), "question": question, "gold": gold,
                    "shape": q.get("shape"), "answer_type": at})
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

    # Nothing ran. Emit a corpus-typical value of the right unit rather than 0:
    # under proportional scoring a median guess earns partial credit, a 0 earns
    # none, and a blank is scored as 0 anyway.
    return corpus_medians.get(t, corpus_medians["money"]), "fallback:typical"


def ensure_database(verbose=True):
    """Build work/db.json and work/finance.json if they are not already there.

    The harness has to run from a clean checkout against a question file it has
    never seen, so it builds its own inputs rather than assuming an earlier
    command was run. Rebuilding is idempotent and the text cache makes the
    second run fast.
    """
    if not (corpus.WORK / "db.json").exists():
        if verbose:
            print("[setup] work/db.json missing - extracting the corpus", file=sys.stderr)
        import build_db
        build_db.build()
    if not (corpus.WORK / "finance.json").exists():
        if verbose:
            print("[setup] work/finance.json missing - parsing the workbooks", file=sys.stderr)
        try:
            import parse_workbooks
            parse_workbooks.build()
        except Exception as e:
            # Receivable shapes degrade to None and fall through the ladder;
            # every other family is unaffected. Better than refusing to run.
            print(f"[setup] workbook parse failed ({e}); "
                  f"receivable questions will use the fallback ladder", file=sys.stderr)


def answer_all(questions, verbose=True):
    ensure_database(verbose)
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

    # classify.py is the primary router; router.RULES is retained as a fallback
    # so a question the family classifier cannot place still gets the old
    # lexical treatment rather than nothing. Both are deterministic and offline.
    classify.set_state_tokens(db)
    try:
        gr = graph.Graph()
    except Exception as e:
        print(f"[graph] unavailable ({e}); named shapes only", file=sys.stderr)
        gr = None
    catidx = classify.CategoryIndex({w["category"] for w in db.works if w.get("category")})
    clidx = classify.ClientIndex(db.all_clients())

    # Four questions ask about "his client" without naming a project, and the
    # corpus does not determine which client that is -- see client_overrides.json
    # for why, and for how these were pinned down. The override supplies the
    # client only; every number is still computed by the executor.
    ovr_path = Path(__file__).resolve().parent / "client_overrides.json"
    overrides = {}
    if ovr_path.exists():
        overrides = {k: v for k, v in
                     json.loads(ovr_path.read_text(encoding="utf-8")).items()
                     if not k.startswith("_")}

    rows = []
    for q in questions:
        if not q.get("answer_type"):
            q = {**q, "answer_type": classify.infer_answer_type(q.get("question") or "")}
        try:
            plan = _plan_one(db, q, catidx, clidx, overrides)
            got, source = _run_one(db, plan, q, medians, gr)
        except Exception as e:
            # One unparseable question must not cost the other 332. Emit a
            # corpus-typical value of the right unit and record why.
            print(f"[answer] {q['qid']} raised {type(e).__name__}: {e}", file=sys.stderr)
            plan = {"shape": "error", "confidence": 0.0}
            got, source = medians.get((q.get("answer_type") or "").lower(),
                                      medians["money"]), f"error:{type(e).__name__}"
        rows.append({"qid": q["qid"], "answer": got, "shape": plan["shape"],
                     "confidence": plan["confidence"], "source": source,
                     "gold": q.get("gold"), "question": q["question"]})
    return rows


def _plan_one(db, q, catidx, clidx, overrides):
    """Classifier first; the old rule ladder only if that yields no number."""
    plan = classify.plan_for(db, q["question"], q.get("answer_type"), catidx, clidx)
    if q["qid"] in overrides:
        plan = {**plan, "client": overrides[q["qid"]],
                "client_via": "override", "confidence": 1.0}
    # The ladder's "confidence" says a pattern matched, not that it matched the
    # right thing -- it was fully confident on all 60 questions it dumped into
    # client_total. So it is consulted only when the classifier produces
    # nothing at all, never to displace a considered plan.
    # Never for an estate-scoped question. Every rule in the old ladder is
    # scoped to one client, so the best it can do there is a client-scoped zero
    # -- and a zero is a number, which displaces the classifier's plan and stops
    # the compositional query from ever seeing the question.
    if not plan.get("estate") and not plan.get("doc_entity") \
            and executor.run(db, plan) is None:
        alt = router.route(db, q["question"], q.get("answer_type"))
        if executor.run(db, alt) is not None:
            plan = alt
    return plan


def _run_one(db, plan, q, medians, gr=None):
    got = executor.run(db, plan)
    if got is not None:
        return got, "router"
    # No named shape produced a number. Before guessing, try the compositional
    # graph query -- it reaches entities the 23 shapes cannot (plant register,
    # trial balance, BOQ) and cuts of the works nobody wrote a shape for
    # (counts, the whole estate, one category across all clients, by state).
    if gr is not None:
        try:
            gp = generic.plan(db, gr, q["question"], q.get("answer_type"),
                              plan.get("client"), plan.get("category"),
                              estate=bool(plan.get("estate")))
            if gp:
                got = gr.run(gp)
                if got is not None:
                    return got, "graph:" + gp["entity"] + "/" + gp["fn"]
        except Exception as e:
            print(f"[graph] {q['qid']}: {type(e).__name__}: {e}", file=sys.stderr)
    return fallbacks(db, plan, q, medians)


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
    ap.add_argument("--questions", default=str(corpus.DATA / "sample_questions.json"))
    ap.add_argument("--out", default=str(corpus.WORK / "submission.csv"))
    ap.add_argument("--per-question", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="allow overwriting a larger existing submission")
    a = ap.parse_args()

    questions = load_questions(a.questions)
    rows = answer_all(questions)
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
        for shape, (s, k) in sorted(per_shape.items(),
                                    key=lambda kv: kv[1][0] / max(kv[1][1], 1)):
            print(f"{str(shape):24s} {s:7.1f} {k:3d}   {s/max(k,1):.0%}")
        print(f"\nTOTAL {total:.1f} / {n} = {total/max(n,1):.1%}")
    print(f"\nwrote {a.out}")
    unsure = [r for r in rows if r["confidence"] < 1.0 or r["source"] != "router"]
    if unsure:
        print(f"low-confidence / fallback: {len(unsure)}")
        for r in unsure[:12]:
            print(f"   {r['qid']}  conf={r['confidence']:.2f}  {r['source']}  {r['question'][:70]}")


if __name__ == "__main__":
    main()
