"""Component-level verification.

A wrong sum and a wrong retrieval produce identical-looking final numbers, so
matching the gold answer is not by itself evidence the extraction is right.
sample_questions.json publishes the intermediate values each answer was built
from ("Values read from the documents: 134,000,000, 23,300,000") -- assert
against those, plus the corpus invariants and the date-format trap.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus
import executor
import router
from normalize import money, parse_date, words_to_number, threshold_from_text

FAIL = []


def check(name, ok, detail=""):
    print(f"  {'OK ' if ok else 'XX '} {name}{'  ' + detail if detail and not ok else ''}")
    if not ok:
        FAIL.append(name)


def main():
    db = executor.DB()
    print("--- normalisation ---")
    check("money INR 33.38 Cr", money("INR 33.38 Cr") == 333800000)
    check("money Rs. 33.38 Crore", money("Rs. 33.38 Crore") == 333800000)
    check("money 3,338.00 Lakh", money("3,338.00 Lakh") == 333800000)
    check("money 33,38,00,000 grouping", money("INR 33,38,00,000/-") == 333800000)
    check("money 81.44 Cr", money("INR 81.44 Cr") == 814400000)
    check("words seventy-three", words_to_number("seventy-three") == 73)
    check("threshold seventy-three crore",
          threshold_from_text("works crossing the seventy-three crore mark") == 730000000)
    check("threshold INR 20 Cr",
          threshold_from_text("credential target of INR 20 Cr") == 200000000)

    print("\n--- the date-format trap (day-first, never US month-first) ---")
    check("06/02/2011 is 6 Feb", parse_date("06/02/2011") == date(2011, 2, 6))
    check("2011-02-06 iso", parse_date("2011-02-06") == date(2011, 2, 6))
    check("DD/MM agrees with the client certificate",
          parse_date("06/02/2011") == parse_date("2011-02-06"))
    check("December 8, 2012", parse_date("December 8, 2012") == date(2012, 12, 8))
    check("31 Mar 2026", parse_date("31 Mar 2026") == date(2026, 3, 31))

    print("\n--- corpus invariants ---")
    works = db.works
    total = sum(w["value"] for w in works if w.get("value"))
    check("155 works", len(works) == 155, f"got {len(works)}")
    check("28 clients", len(db.clients) == 28, f"got {len(db.clients)}")
    check("132 works with a reference letter",
          sum(1 for w in works if w.get("has_ref")) == 132)
    check("23 works without one",
          sum(1 for w in works if not w.get("has_ref")) == 23)
    check("every work has a value", all(w.get("value") for w in works))
    check("every work has a client", all(w.get("client") for w in works))
    check("every work has a completion date", all(w.get("completed") for w in works))
    check("total = 5530.40 Cr (README ~5,530)", abs(total - 55_304_000_000) < 10_000_000,
          f"got {total/1e7:,.2f} Cr")

    print("\n--- intermediates published in reasoning_steps ---")
    # The published values are the set the gold answer was computed over.  Which
    # set that is depends on the shape: person-scoped shapes list the person's
    # own works, client-scoped shapes list the client's whole portfolio.  Mirror
    # executor.py's resolution exactly, or this test measures itself.
    PERSON_SCOPED = {"distinct_count", "temporal_chain"}

    def value_set(plan):
        if plan["shape"] in PERSON_SCOPED and plan.get("person"):
            return [w["value"] for w in db.led_by(plan["person"]) if w.get("value")]
        client = plan.get("client")
        if not client and plan.get("work"):            # executor prefers the named work
            w = db.work(plan["work"])
            client = w["client"] if w else None
        if not client and plan.get("person"):
            led = db.led_by(plan["person"])
            client = led[0]["client"] if led else None
        return [w["value"] for w in db.portfolio(client) if w.get("value")]

    def same(a, b):
        """Equal up to the corpus's sub-rupee rendering (19.33 Cr vs 193,299,999)."""
        return len(a) == len(b) and all(abs(x - y) <= 2 for x, y in zip(a, b))

    qs = json.loads((corpus.DATA / "sample_questions.json").read_text(encoding="utf-8"))["questions"]
    checked = 0
    for q in qs:
        steps = " ".join(q.get("reasoning_steps", []))
        m = re.search(r"Values read from the documents:\s*([\d,\s]+)", steps)
        if not m:
            continue
        want = sorted(int(x.replace(",", "")) for x in re.findall(r"[\d,]{4,}", m.group(1)))
        got = sorted(value_set(router.route(db, q["question"])))
        checked += 1
        check(f"{q['qid']} value set", same(got, want),
              f"\n        want {want}\n        got  {got}")
    print(f"  ({checked} questions publish intermediates)")

    print("\n--- grading: assert we do NOT over-infer ---")
    # Inverted deliberately. On 2026-08-09 the dataset authors withdrew
    # HS-IC-0013/0014 and excluded grading-filtered questions from scoring:
    #   "41 of 155 works have a grading stated nowhere in their own documents,
    #    and 17 of those carry a grading WORD that is not their grade."
    # An earlier rule here read the boilerplate "taken over on satisfactory
    # completion" as a grade, which is exactly that error, and it had been
    # reverse-engineered from a gold answer rather than from the documents.
    # So the risk to guard is fabricating grades, NOT missing them: a work whose
    # certificate never names a grade must carry None.
    graded = [w for w in works if w.get("grading")]
    dist = {}
    for w in graded:
        dist[w["grading"]] = dist.get(w["grading"], 0) + 1
    check("grading not over-inferred (<=130 of 155)", len(graded) <= 130,
          f"got {len(graded)}/155 — a jump here means a rule is reading boilerplate")
    # A grade may legitimately come from EITHER certificate, so check both.
    def states_a_grade(w):
        for doc in (w.get("cc_id"), w.get("ccc_id")):
            if not doc:
                continue
            flat = re.sub(r"\s+", " ", corpus.text(doc))
            if re.search(r"is\s+graded|\bgraded\s+(?:as\s+)?[A-Z]"
                         r"|assessed the completed work as", flat):
                return True
        return False

    unstated = [w["work"] for w in graded if not states_a_grade(w)]
    check("every graded work has a certificate that states the grade",
          not unstated, f"{len(unstated)} graded from boilerplate: {unstated[:3]}")
    print(f"       {len(graded)}/155 graded, {155 - len(graded)} correctly None")
    print(f"       distribution: {dist}")

    print("\n--- role extraction (role_split depends on it) ---")
    roles = {}
    for w in works:
        roles[w.get("role")] = roles.get(w.get("role"), 0) + 1
    check("role present on >=154 works", sum(1 for w in works if w.get("role")) >= 154)
    print(f"       distribution: {roles}")

    print(f"\n{'ALL COMPONENT CHECKS PASS' if not FAIL else f'{len(FAIL)} FAILED: {FAIL}'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
