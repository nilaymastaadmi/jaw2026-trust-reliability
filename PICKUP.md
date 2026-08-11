# Handoff prompt — paste this into a fresh session

---

JAW 2026 hackathon — take over an in-flight competition entry. ~24h to the
deadline (13 Aug 12:00 PM IST). Read everything before changing anything.

REPO:  https://github.com/nilaymastaadmi/jaw2026-trust-reliability  (private)
LOCAL: C:\Users\toshn\Projects\jaw2026   — read HANDOFF.md and README.md FIRST.
Dataset is a separate clone in dataset/ (public, gitignored).

ALWAYS prefix python with PYTHONIOENCODING=utf-8 (Windows cp1252 dies on em-dashes).

## START HERE: the previous session's own verdict on its work

I built this and I do not think incremental fixes will win it. Two things I
could not resolve, stated plainly so you can decide rather than inherit:

**1. I never validated the core assumption.** Every "shape" encodes a GUESS at
what a question means, inferred from a handful of samples. `hop_aggregate`
returns the client's WHOLE portfolio even when the question says "assignments
HE delivered" — I inferred that from two examples and it now drives ~32
questions. `year_delta` returns an absolute value because the wording *felt*
magnitude-like. Nobody has verified any of these semantics against a gold. If a
shape's meaning is wrong, every question routed to it scores ~0 and no test
catches it, because the tests assert against the same guesses.

**2. The gap to the leaders is probably not 20 more shapes.** We are at 66.553.
Six teams are above 97; the leader is 99.399. That is near-perfect on EVERY
question, which tells you two things: every question has a clean deterministic
answer readable from the documents, and those teams almost certainly found a
formulation that GENERALISES rather than 24 hand-written regex rules that each
cover one phrasing. I kept adding shapes because each one measurably helped, but
the curve flattens and the fragility compounds — `router.RULES` is
first-match-wins, so every new rule can silently steal questions from an older
one.

**So before you optimise this architecture, seriously consider replacing the
routing layer.** Concretely, the thing I would try first:

The extraction layer is probably FINE — that is the important diagnostic. A
teammate independently re-extracted all 155 works by a different route (portfolio
+ client certificates, no shared parser) and `reconcile.py` reported 155/155
agreement on every field, zero mismatches. `work/db.json` is very likely correct.
So the bottleneck is almost certainly question -> query, NOT documents -> data.

Given that, a text-to-query approach should dominate regex shapes: give a model
the compact schema (155 works with client/value/date/category/lead/role/has_ref,
plus receivables per client) and have it emit a small Python expression or SQL
per question, executed deterministically. That generalises to phrasings nobody
enumerated, which is exactly where we are losing. Keep the ironclad rule that
the model never does arithmetic — it emits the query, code computes the number.

`router.route_llm()` already exists as a batched, structured-output stub. It
needs ANTHROPIC_API_KEY (none is set; the `claude` CLI is session-limited and
would burn the operator's own quota — do not route through it).

Measure before you commit to a rewrite: hold out the 23 sample questions with
published golds and compare approaches on those. And keep the current
deterministic path working as a fallback — it scores 66.5 and a half-finished
rewrite scores 0.

## WHERE WE ARE

  Leaderboard: 10th of 10. Us 66.553. Leader 99.399. Six teams above 97.
  20 attempts total, 2 used. Live leaderboard, immediate scoring.
  Scoring: score = max(0, 1 - |yours - gold| / gold), averaged over 333 questions.
    No bands. 5% off scores 0.95. Wrong magnitude scores 0. Blank scores 0.
  Every submission needs its own fresh commit SHA (a reused SHA is refused, free).

  Un-submitted on disk: year_delta (24 questions). Executor failures 59 -> 37.
  SHA b43597cf84a9a41bb1c6066b350f4d3d9ca69336 is committed, pushed, ready.

## THE TASK

687 documents about a synthetic Indian contractor. No database, no schema, no
document-to-entity mapping. 333 natural-language questions, each wanting one
number. We rebuilt the withheld database and answer by deterministic query.

  corpus.py -> parsers.py -> build_db.py -> work/db.json
    (155 works, 28 clients, 39 people)
  parse_workbooks.py -> work/finance.json  (519 invoices, per-client receivables)
  router.py  question -> {shape, params}
  executor.py  the shapes; ALL arithmetic
  answer.py  -> work/submission.csv + unit-aware fallback ladder

## HIGHEST-VALUE DIAGNOSTIC (run this first, whatever you decide)

    cd src && PYTHONIOENCODING=utf-8 python -c "
    import sys,json; sys.path.insert(0,'.')
    import corpus,executor,router
    db=executor.DB()
    qs=json.load(open(corpus.DATA/'questions.json',encoding='utf-8'))['questions']
    for q in qs:
      p=router.route(db,q['question'],q.get('answer_type'))
      if p['shape'] in ('client_total','hop_aggregate') or p['confidence']<1.0:
        print(p['shape'],'|',q['answer_type'],'|',q['question'][:150])"

~60 questions land in `client_total`, a generic portfolio sum that is almost
certainly wrong for most of them. READ THEM. Each cluster you can name is worth
~0.3 points per question. This exact loop is how I found `year_delta` (24
questions, 7.2 points) — the questions were saying "net difference between 2020
and 2022" and we were answering with the entire portfolio total.

Found by analysis but NOT verified — check the counts yourself before building:
  - two-person questions ("Pooja Sen AND Sanjay Joshi's assignments")  ~25
  - "top client" / "two largest client relationships", person-scoped   ~23
  - first-name-only person references ("meera, what pct...")           ~25 (13 unambiguous)

## TRAPS THAT COST ME HOURS — do not rediscover these

1. PyMuPDF only. pdfplumber silently returns field LABELS and drops VALUES on
   these PDFs, with no error at all.
2. Dates are DAY-first. 06/02/2011 is 6 Feb, verified against a certificate that
   states the same date in ISO form.
3. 12 of 28 clients differ from a sibling ONLY by state name (three Jal Nigam,
   four Public Works Department...). Resolution returns None on a tie rather
   than guessing — KEEP THAT. A misresolved client is a confident wrong number;
   an unresolved one shows up in triage. test_entities.py guards it.
4. NEVER write regexes through a shell heredoc. `\b` becomes a literal 0x08
   BACKSPACE byte. It is invisible in Read, in editors, and in
   inspect.getsource() — only `cat -A` reveals it. It silently broke two
   features (the package index built empty; all 24 year_delta questions returned
   None) and cost about an hour each time. test_components.py now asserts no
   src/*.py contains a control byte. Keep it green.
5. router.RULES is FIRST-MATCH-WINS. A rule inserted high steals questions from
   existing shapes. test_router_stress.py catches this — run it every time.
6. The organisers audited and WITHDREW question families on written grading,
   contract role, and business unit — none are recoverable from the documents.
   Do not build toward them. (I had a grading rule reverse-engineered from a
   gold answer; they confirmed it was underivable and I removed it.)

## BEFORE EVERY SUBMISSION

    cd src && for t in test_components test_executor test_router_stress test_entities; \
      do PYTHONIOENCODING=utf-8 python $t.py; done
    PYTHONIOENCODING=utf-8 python answer.py --questions ../dataset/questions.json \
        --out ../work/submission.csv --force

Then commit (a fresh SHA is required), push, and CHECK THE UPDATES TAB on
jaw.hackathon.gikagraph.ai. The question set was revised FIVE times in one day
and our first submission scored 49.822 purely because it was stale. Confirm
`cd dataset && git fetch && git diff origin/main` is empty before submitting.

The operator submits — you cannot (login credentials, irreversible action,
capped attempts). Give them: the SHA, the file path, and what changed.
