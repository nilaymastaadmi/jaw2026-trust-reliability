"""The harness must survive the question file it is actually given.

The tie-break runs this code on a file nobody here has seen. Everything about
that file is an assumption until it is tested: the envelope key, the field
names, whether `answer_type` is present, the encoding, whether every row is
well formed. A loader crash at that point costs all 300 questions, not one.

So each case below hands `answer.py` a deliberately awkward version of the
released set and requires the answers to come back unchanged -- or, where the
input is genuinely lossy, requires the run to complete rather than raise.

    python test_io.py
"""
import csv
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import answer as answer_mod
import corpus

QUESTIONS = corpus.DATA / "questions.json"
GOLD = corpus.WORK / "submission.csv"


def _load():
    raw = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    return raw["questions"] if isinstance(raw, dict) else raw


def _gold():
    # On a clean checkout work/submission.csv does not exist yet -- the harness
    # writes it -- so this suite failed on the one machine where it matters
    # most, a judge's fresh clone. Build it if it is not there.
    if not GOLD.exists():
        print("[setup] work/submission.csv missing - running the harness once",
              file=sys.stderr)
        GOLD.parent.mkdir(parents=True, exist_ok=True)
        answer_mod.write_submission(
            answer_mod.answer_all(_load(), verbose=False), GOLD)
    with open(GOLD, encoding="utf-8") as fh:
        return {r["question_id"]: float(r["answer"]) for r in csv.DictReader(fh)}


def _write(text, suffix=".json", encoding="utf-8"):
    fh = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False,
                                     encoding=encoding)
    fh.write(text)
    fh.close()
    return fh.name


def _score(rows, gold):
    """Official metric over whatever came back."""
    got = {r["qid"]: r["answer"] for r in rows}
    total = 0.0
    for qid, g in gold.items():
        a = got.get(qid)
        if a is None:
            continue
        a, g = float(a), float(g)
        total += 1.0 if g == 0 and a == 0 else (
            max(0.0, 1.0 - abs(a - g) / abs(g)) if g else 0.0)
    return total / len(gold) * 100


# ------------------------------------------------------------------ shapes

def envelope_questions(qs):
    return _write(json.dumps({"questions": qs}))


def envelope_bare_list(qs):
    return _write(json.dumps(qs))


def envelope_data_key(qs):
    return _write(json.dumps({"set_id": "hidden", "data": qs}))


def envelope_jsonl(qs):
    return _write("\n".join(json.dumps(q) for q in qs), suffix=".jsonl")


def field_aliases(qs):
    out = [{"id": q["qid"], "text": q["question"], "type": q.get("answer_type")}
           for q in qs]
    return _write(json.dumps({"items": out}))


def no_answer_type(qs):
    return _write(json.dumps({"questions": [
        {k: v for k, v in q.items() if k != "answer_type"} for q in qs]}))


def blank_answer_type(qs):
    return _write(json.dumps({"questions": [{**q, "answer_type": ""} for q in qs]}))


def utf8_bom(qs):
    return _write("﻿" + json.dumps({"questions": qs}))


def utf16(qs):
    return _write(json.dumps({"questions": qs}), encoding="utf-16")


def crlf_and_padding(qs):
    return _write("\r\n  " + json.dumps({"questions": qs}) + "  \r\n")


def extra_unknown_fields(qs):
    return _write(json.dumps({"questions": [
        {**q, "difficulty": "hard", "topic": "x", "notes": None} for q in qs]}))


def duplicate_rows(qs):
    return _write(json.dumps({"questions": qs + qs[:20]}))


def malformed_rows(qs):
    """Rows with no qid, no text, or a null body, mixed into a good file."""
    junk = [{"question": "no id at all"}, {"qid": None, "question": "null id"},
            {"qid": "JUNK-1", "question": ""}, {"qid": "JUNK-2"}]
    return _write(json.dumps({"questions": junk + qs}))


# Each case: (name, builder, must the answers be IDENTICAL to the released run?)
CASES = [
    ("envelope: {questions: []}", envelope_questions, True),
    ("envelope: bare list", envelope_bare_list, True),
    ("envelope: {data: []}", envelope_data_key, True),
    ("envelope: JSONL", envelope_jsonl, True),
    ("fields: id / text / type", field_aliases, True),
    ("answer_type absent", no_answer_type, True),
    ("answer_type blank string", blank_answer_type, True),
    ("UTF-8 BOM", utf8_bom, True),
    ("UTF-16", utf16, True),
    ("CRLF and padding", crlf_and_padding, True),
    ("extra unknown fields", extra_unknown_fields, True),
    ("duplicate rows", duplicate_rows, True),
    ("malformed rows mixed in", malformed_rows, True),
]


def main():
    gold = _gold()
    qs = [q for q in _load() if q["qid"] in gold]
    fail = 0
    print(f"question-file robustness -- {len(qs)} questions, "
          f"answers must not move\n")
    for name, build, must_match in CASES:
        path = build([dict(q) for q in qs])
        try:
            loaded = answer_mod.load_questions(path)
            rows = answer_mod.answer_all(loaded, verbose=False)
            got = {r["qid"]: r["answer"] for r in rows}
            covered = sum(1 for k in gold if k in got)
            score = _score(rows, gold)
            ok = covered == len(gold) and (score > 99.9995 or not must_match)
            print(f"  {'PASS' if ok else 'FAIL'}  {name:30s} "
                  f"{covered:3d}/{len(gold)} answered   {score:7.3f}")
            if not ok:
                fail += 1
        except Exception as e:                          # a crash is the failure
            print(f"  FAIL  {name:30s} raised {type(e).__name__}: {e}")
            fail += 1

    print()
    if fail:
        print(f"FAILURES: {fail}")
        sys.exit(1)
    print("ALL QUESTION-FILE SHAPES HANDLED")


if __name__ == "__main__":
    main()
