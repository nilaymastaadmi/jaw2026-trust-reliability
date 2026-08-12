"""Paraphrase the released questions and check the answers do not move.

WHY
---
The tie-break runs this harness against questions nobody here has seen. The one
thing we know about them is their distribution: the organisers wrote the 333
released questions and the 21 samples, and the hidden set comes from the same
pipeline. So the risk is not a new FAMILY of question -- it is the same families
worded differently, and a router built from regexes fails on wording.

Held-out question sets measure that too, but they are scarce and they burn: once
you have read the failures you cannot un-read them. This does not burn, because
the golds are not opinions. We hold a set of 333 questions whose answers are
confirmed correct by the leaderboard at 100.000. Rewrite a question without
changing what it asks, and the answer must not move. Every drop is a real bug,
found without spending a held-out set.

WHAT IT DOES
------------
Nine meaning-preserving rewrites, applied one at a time so a failure names the
rewrite that caused it:

    synonym    family vocabulary swapped for wording the set never uses
    money      "INR 30 Cr" <-> "30,00,00,000", the two notations the corpus mixes
    hurried    lowercase, no punctuation, a deadline on the end
    formal     an audit-memo frame around the same question
    spoken     a false start and a self-correction, as transcribed speech
    buried     the question arrives after a paragraph of preamble
    trailing   the client moves from the front of the sentence to the back
    sibling    the client is given as "the <state> one, not the <other> one"
    shorthand  the client is named by its distinctive word alone

Run:
    python stress.py                 # all rewrites, summary
    python stress.py --show synonym  # every question the rewrite broke
"""
import argparse
import csv
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import answer as answer_mod
import corpus
import executor

# ---------------------------------------------------------------- rewrites

# Meaning-preserving swaps. Each pair is checked against the corpus vocabulary:
# nothing here changes which client, which category, which operation or which
# unit is being asked for.
_SYNONYM = [
    (r"\bcombined value\b", "aggregate worth"),
    (r"\btotal value\b", "full value"),
    (r"\bhow much\b", "what amount"),
    (r"\bhow many\b", "what number of"),
    (r"\bexcluding\b", "leaving aside"),
    (r"\bexcept for\b", "other than"),
    (r"\bthe average\b", "the mean"),
    (r"\baverage\b", "typical"),
    (r"\bmedian\b", "middle value"),
    (r"\breference letters?\b", "client reference"),
    (r"\bcompleted works?\b", "finished assignments"),
    (r"\bportfolio\b", "book of work"),
    (r"\boutstanding\b", "still owed to us"),
    (r"\binvoiced\b", "billed"),
    (r"\breceived\b", "collected"),
    (r"\blargest\b", "biggest"),
    (r"\bsecond largest\b", "next biggest"),
    (r"\bshortfall\b", "gap"),
    (r"\bat least\b", "no less than"),
    (r"\bat or above\b", "or bigger"),
    (r"\bdifference between\b", "spread between"),
    (r"\bcalculate\b", "work out"),
    (r"\bplease\b", "if you would"),
    (r"\bwork out\b", "figure out"),
    (r"\bcategory\b", "type of work"),
    (r"\bvalue of\b", "worth of"),
]

_PREAMBLE = (
    "I'm putting the prequalification file together for a tender that closes "
    "on Friday and the bid desk wants every figure cross-checked against the "
    "certificates before it goes out, which is why I am asking rather than "
    "reading it off last quarter's pack. "
)
_MEMO = ("For the record, and per the audit checklist circulated this morning: ")
_TRAIL = " -- that's what I need, whenever you get a moment."


def _rw_synonym(q, rng, db):
    out = q
    for pat, rep in _SYNONYM:
        out = re.sub(pat, rep, out, flags=re.I)
    return out if out != q else None


def _rw_money(q, rng, db):
    """Swap between the two rupee notations the corpus itself mixes."""
    def to_digits(m):
        val = float(m.group(1).replace(",", ""))
        unit = 10 ** 7 if m.group(2).lower().startswith("cr") else 10 ** 5
        n = str(round(val * unit))
        head, tail = n[:-3], n[-3:]             # Indian grouping: 30,00,00,000
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        return ",".join(parts + [tail]) if parts else tail
    out = re.sub(r"(?:INR|Rs\.?|₹)?\s*([\d][\d,]*(?:\.\d+)?)\s*(Cr|Crores?|Lakhs?)\b",
                 to_digits, q, flags=re.I)
    return out if out != q else None


def _rw_hurried(q, rng, db):
    out = re.sub(r"[.?!]+\s*$", "", q).lower()
    return out + " asap, bid closes at 4"


def _rw_formal(q, rng, db):
    return _MEMO + q[0].lower() + q[1:]


def _rw_spoken(q, rng, db):
    head = q.split(",")[0][:40]
    return f"so what I need is -- sorry, let me start again. {q} That's the one."


def _rw_buried(q, rng, db):
    return _PREAMBLE + q


def _rw_trailing(q, rng, db):
    """Move a leading client mention to the end of the sentence."""
    m = re.match(r"^([A-Z][\w&,.'\- ]{8,70}?)(?:\s+is\b|\s+was\b|\s*[—–-]\s*|,\s+)", q)
    if not m:
        return None
    name, rest = m.group(1).strip(), q[m.end():].strip()
    if not rest:
        return None
    return rest[0].upper() + rest[1:] + f" -- this is for {name}."


def _siblings(db):
    fam = defaultdict(list)
    for n in db.all_names:
        fam[re.split(r",", n)[0].strip()].append(n)
    return {k: v for k, v in fam.items() if len(v) > 1}


def _rw_sibling(q, rng, db):
    """Name a client the way a person disambiguates one: by exclusion."""
    for head, names in _siblings(db).items():
        for n in names:
            if n.lower() not in q.lower():
                continue
            state = n.split(",")[-1].strip().replace("Govt of ", "")
            others = [o.split(",")[-1].strip().replace("Govt of ", "")
                      for o in names if o != n]
            if not others:
                continue
            phrase = (f"{head} -- the {state} one, not "
                      + " and not ".join(others[:2]))
            return re.sub(re.escape(n), phrase, q, count=1, flags=re.I)
    return None


def _rw_shorthand(q, rng, db):
    """Name a client the way a colleague would: by the word that identifies it.

    Only a word that belongs to exactly ONE client counts. Shortening "Public
    Works Department, Govt of Tamil Nadu" to "Tamil" does not name a client at
    all -- four departments and three other clients sit in Tamil Nadu -- so a
    system that refuses it is right and the rewrite would be measuring nothing.
    Where no single word identifies the client, the legal suffix and "Govt of"
    are dropped instead, which is how these are written in practice.
    """
    import classify
    idx = classify.ClientIndex(db.all_names)
    for n in sorted(db.all_names, key=len, reverse=True):
        if n.lower() not in q.lower():
            continue
        uniq = [t for t in classify._tokens(n)
                if idx.df.get(t) == 1 and t not in classify._STATE_TOKENS
                and len(t) > 4]
        if uniq:
            short = uniq[0].title()
        else:
            short = re.sub(r"\b(?:Govt of|Government of)\s+", "", n)
            short = re.sub(r",?\s*(?:Limited|Ltd\.?|Corporation|Corp\.?)\s*$", "", short)
            if short.strip().lower() == n.strip().lower():
                return None
        return re.sub(re.escape(n), short.strip(), q, count=1, flags=re.I)
    return None


_ONES = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
         7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
         12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
         16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen"}
_TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty",
         7: "seventy", 8: "eighty", 9: "ninety"}


def _in_words(k):
    if k in _ONES:
        return _ONES[k]
    if k % 10 == 0 and k // 10 in _TENS:
        return _TENS[k // 10]
    if 20 < k < 100 and k // 10 in _TENS:
        return _TENS[k // 10] + "-" + _ONES[k % 10]
    return None


def _rw_numword(q, rng, db):
    """"26 Cr" -> "twenty-six crore". The set writes thresholds both ways."""
    def sub(m):
        w = _in_words(int(m.group(1)))
        return m.group(0) if not w else f"{w} crore"
    out = re.sub(r"\b(?:INR\s*|Rs\.?\s*)?(\d{1,2})\s*(?:Cr\b|Crores?\b)", sub, q,
                 flags=re.I)
    return out if out != q else None


def _rw_punct(q, rng, db):
    """The same words, punctuated by someone else."""
    out = q.replace("\u2014", ",").replace("\u2013", ",").replace(";", ",")
    out = re.sub(r",\s*,", ",", out)
    out = re.sub(r"\s+,", ",", out)
    return out if out != q else None


def _rw_statement(q, rng, db):
    """Asked as an instruction rather than a question."""
    body = re.sub(r"^(?:could you|can you|would you|please|so|and|but)\s+", "", q,
                  flags=re.I)
    body = re.sub(r"[?]\s*$", ".", body.strip())
    return "Need this for the bid pack: " + body[0].lower() + body[1:]


def _rw_decoy(q, rng, db):
    """A figure the asker believes, which the right answer contradicts.

    Applied only where the question states no rupee figure of its own, so the
    decoy cannot be mistaken for a threshold the question actually sets.
    """
    if re.search(r"\d[\d,]*\s*(?:cr\b|crore|lakh)|\d{2},\d{2}|(?:INR|Rs\.?|\u20b9)\s*\d",
                 q, re.I):
        return None
    if re.search(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven"
                 r"|twelve|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
                 r"[\s-]*(?:crore|lakh)", q, re.I):
        return None
    return q.rstrip(" .?!") + " I have about 14 crore in my head for this, but I doubt it."


def _rw_firstname(q, rng, db):
    """A person named the way a colleague names them, when it stays unambiguous."""
    first = {}
    for name in db.persons:
        first.setdefault(name.split()[0].lower(), []).append(name)
    for name in sorted(db.persons, key=len, reverse=True):
        if name.lower() not in q.lower():
            continue
        f = name.split()[0]
        if len(first[f.lower()]) != 1:
            return None                        # two people share it: ambiguous
        return re.sub(re.escape(name), f, q, count=1, flags=re.I)
    return None


def _rw_pkgless(q, rng, db):
    """A work named without its package number, where the title is still unique."""
    titles = [w["work"] for w in db.works if w.get("work")]
    for t in sorted(titles, key=len, reverse=True):
        if t.lower() not in q.lower():
            continue
        base = re.sub(r"\s*[\u2014\u2013-]\s*[A-Za-z ]+Pkg[\s\-_]*\d+\s*$", "", t).strip()
        if base == t or sum(1 for o in titles if o.startswith(base)) != 1:
            return None                        # dropping it loses the identity
        return re.sub(re.escape(t), base, q, count=1, flags=re.I)
    return None


def _rw_compose(q, rng, db):
    """Three rewrites at once, which is how an unseen question actually differs."""
    out = q
    for fn in (_rw_synonym, _rw_punct, _rw_trailing, _rw_hurried):
        got = fn(out, rng, db)
        if got:
            out = got
    return out if out != q else None


REWRITES = {
    "synonym": _rw_synonym, "money": _rw_money, "numword": _rw_numword,
    "punct": _rw_punct, "hurried": _rw_hurried, "formal": _rw_formal,
    "spoken": _rw_spoken, "buried": _rw_buried, "statement": _rw_statement,
    "trailing": _rw_trailing, "sibling": _rw_sibling, "shorthand": _rw_shorthand,
    "firstname": _rw_firstname, "pkgless": _rw_pkgless, "decoy": _rw_decoy,
    "compose": _rw_compose,
}


# ------------------------------------------------------- the held-back bank
#
# THE DISCIPLINE. Everything above was fixed against until it passed, so 100%
# there says "the router handles the sixteen ways that were thought of", not
# "the router handles rewording". A fitted number cannot answer the only
# question that matters, which is whether the fixes generalise.
#
# So this bank is held back. Each type below was written AFTER the fixing above
# had stopped, run once, and its result reported as it stood. Where a run did
# force a change, that change is recorded in the commit and the bank is treated
# as spent from then on -- the next honest number needs types nobody has run.
#
# Two banks, both spent as of the commit that introduced them:
#   bank 1 (passive .. decimal crore)   98.94% cold, 99.98% after two fixes
#   bank 2 (tell me .. negative framing) 99.91% cold, no fixes made

def _passive(q, rng, db):
    out = re.sub(r"\bwhat (?:is|was) the\b", "what figure is arrived at for the", q, flags=re.I)
    out = re.sub(r"\bcould you (?:please )?(?:calculate|confirm|tell me|work out|give me)\b",
                 "it needs to be established", out, flags=re.I)
    out = re.sub(r"\bhow much (?:is|was|do|does)\b", "what amount is held as", out, flags=re.I)
    out = re.sub(r"\bwe(?:'ve| have) (?:completed|delivered|billed)\b",
                 lambda m: "was " + m.group(0).split()[-1] + " by us", out, flags=re.I)
    return out if out != q else None

def _nested(q, rng, db):
    return ('Forwarding this from the bid desk. They wrote: "' + q.rstrip() +
            '" Can you answer that for them?')

def _allcaps(q, rng, db):
    return q.upper()

def _nopunct(q, rng, db):
    out = re.sub(r"[—–\-,;:.?!'’\"]", " ", q)
    return re.sub(r"\s+", " ", out).strip()

def _newlines(q, rng, db):
    bits = re.split(r"(?<=[,;—])\s+", q)
    return "\n  ".join(b for b in bits if b.strip())

_TYPO = {"the": "teh", "value": "valeu", "total": "totla", "which": "whcih",
         "completed": "compelted", "client": "clinet", "reference": "refernce",
         "average": "avarage", "between": "betwen", "difference": "differnce",
         "works": "worksa", "please": "pleaes", "amount": "amoutn"}
def _typo(q, rng, db):
    out = q
    for a, b in _TYPO.items():
        out = re.sub(r"\b" + a + r"\b", b, out, count=1, flags=re.I)
    return out if out != q else None

def _pronoun(q, rng, db):
    """Second and later mentions of the client become a pronoun."""
    for n in sorted(db.all_names, key=len, reverse=True):
        hits = [m for m in re.finditer(re.escape(n), q, re.I)]
        if len(hits) < 2:
            continue
        out = q[:hits[1].start()] + "that account" + q[hits[1].end():]
        return out
    return None

def _redundant(q, rng, db):
    """The client named once properly and once loosely, as people actually write."""
    for n in sorted(db.all_names, key=len, reverse=True):
        if n.lower() not in q.lower():
            continue
        loose = re.sub(r"\b(?:Govt of|Government of)\s+", "", n)
        return re.sub(re.escape(n), n + " (i.e. " + loose + ")", q, count=1, flags=re.I)
    return None

def _listy(q, rng, db):
    m = re.search(r"^(.{0,90}?[,.;](?![\d]))\s+(.+)$", q, re.S)
    if not m:
        return None
    return "Request:\n  - context: " + m.group(1).strip() + "\n  - question: " + m.group(2).strip()

def _decimal_crore(q, rng, db):
    """'INR 26 Cr' -> 'INR 2.6 crore x10' is nonsense; use 260000000 style instead."""
    def sub(m):
        v = float(m.group(1).replace(",", ""))
        unit = 10**7 if m.group(2).lower().startswith("cr") else 10**5
        return f"{round(v*unit/10**7, 2):g} crore"
    out = re.sub(r"\b(?:INR\s*|Rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)\s*(Cr\b|Crores?\b|Lakhs?\b)",
                 sub, q, flags=re.I)
    return out if out != q else None

def _tellme(q, rng, db):
    out = re.sub(r"^\s*(?:what(?:'s| is| was)|could you (?:please )?(?:tell me|confirm|give me)"
                 r"|can you (?:tell me|confirm)|please confirm)\s+", "Tell me ", q, flags=re.I)
    out = re.sub(r"\?\s*$", ".", out)
    return out if out != q else "Any idea " + q[0].lower() + q[1:]

def _hedged(q, rng, db):
    return ("Sorry to bother you, and I might be misremembering how this works, but "
            "if it's not too much trouble — " + q[0].lower() + q[1:] +
            " No rush if you're busy.")

def _twosent(q, rng, db):
    m = re.search(r"^(.{25,110}?)(?:,|—|–|;|\s-\s)\s*(.+)$", q, re.S)
    if not m: return None
    a, b = m.group(1).strip(), m.group(2).strip()
    return a[0].upper() + a[1:] + ". " + b[0].upper() + b[1:]

def _paren(q, rng, db):
    return re.sub(r"(\bfor\b|\bof\b)", r"\1 (per the certificates on file)", q, count=1)

def _barline(q, rng, db):
    def sub(m):
        return f"the {m.group(1)}-crore line"
    out = re.sub(r"(?:INR\s*|Rs\.?\s*)?(\d{1,3})\s*(?:Cr\b|Crores?\b)", sub, q, flags=re.I)
    return out if out != q else None

def _datestyle(q, rng, db):
    out = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: f"{m.group(3)}/{m.group(2)}/{m.group(1)}", q)
    out = re.sub(r"\bMarch 10,? 2021\b", "10 March 2021", out, flags=re.I)
    out = re.sub(r"\bMar 10 2021\b", "10-Mar-2021", out, flags=re.I)
    return out if out != q else None

_BRIT = {r"\borganization\b": "organisation", r"\brecognize\b": "recognise",
         r"\banalyze\b": "analyse", r"\bprogram\b": "programme",
         r"\bcheck\b": "cheque", r"\bfulfill\b": "fulfil",
         r"\bcanceled\b": "cancelled", r"\bcolor\b": "colour"}
def _brit(q, rng, db):
    out = q
    for a, b in _BRIT.items(): out = re.sub(a, b, out, flags=re.I)
    return out if out != q else None

def _slack(q, rng, db):
    return "@here \U0001F44B quick one — " + q.rstrip() + " \U0001F64F thanks!"

def _qfirst(q, rng, db):
    m = re.search(r"^(.{30,140}?[,—–;])\s*(.{20,}\?)\s*$", q, re.S)
    if not m: return None
    return m.group(2).strip() + " (context: " + m.group(1).strip().rstrip(",—–;") + ")"

def _filler(q, rng, db):
    return re.sub(r"\s+(and|but|so|then)\s+", r" \1, um, like, ", q, count=2)

def _negframe(q, rng, db):
    return ("I don't want the single line item, and I don't want last quarter's pack. "
            + q[0].upper() + q[1:])

COLD = {
    "passive": _passive, "nested": _nested, "ALLCAPS": _allcaps,
    "no punctuation": _nopunct, "newlines": _newlines, "typos": _typo,
    "pronoun": _pronoun, "redundant name": _redundant, "bulleted": _listy,
    "decimal crore": _decimal_crore,
    "tell me": _tellme, "hedged": _hedged, "two sentences": _twosent,
    "parenthetical": _paren, "the N-crore line": _barline,
    "date restyled": _datestyle, "british spelling": _brit,
    "slack + emoji": _slack, "question first": _qfirst,
    "verbal filler": _filler, "negative framing": _negframe,
}


# ---------------------------------------------------------------- scoring

def score_one(gold, got):
    if got is None:
        return 0.0
    gold, got = float(gold), float(got)
    if gold == 0:
        return 1.0 if got == 0 else 0.0
    return max(0.0, 1.0 - abs(got - gold) / abs(gold))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=None)
    ap.add_argument("--golds", default=None,
                    help="CSV of verified answers; defaults to the submission")
    ap.add_argument("--show", default=None, help="print every miss for one rewrite")
    ap.add_argument("--cold", action="store_true",
                    help="run the held-back bank instead of the fitted one")
    ap.add_argument("--seed", type=int, default=20260811)
    a = ap.parse_args()

    qpath = a.questions or str(corpus.DATA / "questions.json")
    gpath = a.golds or str(corpus.WORK / "submission.csv")
    questions = answer_mod.load_questions(qpath)
    gold = {r["question_id"]: float(r["answer"])
            for r in csv.DictReader(open(gpath, encoding="utf-8"))}
    questions = [q for q in questions if q["qid"] in gold]

    answer_mod.ensure_database(False)
    db = executor.DB()
    rng = random.Random(a.seed)
    bank = COLD if a.cold else REWRITES
    names = {r: [] for r in bank}
    rows = {r: [] for r in bank}

    for name, fn in bank.items():
        mutated = []
        for q in questions:
            try:
                m = fn(q["question"], rng, db)
            except Exception:
                m = None
            if not m or m == q["question"]:
                continue
            mutated.append({**q, "question": m})
        if not mutated:
            continue
        got = answer_mod.answer_all(mutated, verbose=False)
        for q, g in zip(mutated, got):
            s = score_one(gold[q["qid"]], g["answer"])
            rows[name].append((s, q, g["answer"], gold[q["qid"]]))
        names[name] = mutated

    print(f"PARAPHRASE STRESS ({'held-back bank' if a.cold else 'fitted bank'})"
          f"  --  {len(questions)} questions with verified golds\n")
    print(f"  {'rewrite':11s} {'applied':>7s} {'score':>8s} {'exact':>7s} {'broken':>7s}")
    tot_s = tot_n = 0
    for name in bank:
        r = rows[name]
        if not r:
            continue
        s = sum(x[0] for x in r)
        tot_s += s
        tot_n += len(r)
        exact = sum(1 for x in r if x[0] > 0.9995)
        print(f"  {name:11s} {len(r):7d} {s / len(r) * 100:7.2f}% "
              f"{exact:7d} {len(r) - exact:7d}")
    if tot_n:
        print(f"\n  {'OVERALL':11s} {tot_n:7d} {tot_s / tot_n * 100:7.2f}%")

    # Not a rewrite of the question -- a rewrite of the FILE. `answer_type`
    # partitions the set before any lexical test runs, and it arrives as an
    # input field rather than being derived. A hidden set that omits it, or
    # spells it differently, must not cost twenty points.
    if a.cold:
        return
    stripped = [{**q, "answer_type": None} for q in questions]
    out = answer_mod.answer_all(stripped, verbose=False)
    ss = [score_one(gold[q["qid"]], g["answer"]) for q, g in zip(stripped, out)]
    print(f"\n  answer_type field removed entirely: {sum(ss) / len(ss) * 100:7.2f}%"
          f"   ({sum(1 for x in ss if x < 0.9995)} of {len(ss)} moved)")

    if a.show:
        print(f"\n--- every question the `{a.show}` rewrite broke ---")
        for s, q, got, g in sorted(rows.get(a.show, []), key=lambda r: r[0]):
            if s > 0.9995:
                continue
            print(f"\n  {q['qid']}  score {s:.3f}  got {got}  gold {g}")
            print(f"    {q['question'][:200]}")


if __name__ == "__main__":
    main()
