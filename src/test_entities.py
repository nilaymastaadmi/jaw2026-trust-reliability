"""Entity resolution under realistic name variation.

12 of the 28 clients (43%) differ from a sibling ONLY by state name:

    Jal Nigam, {Gujarat | Jharkhand | Uttar Pradesh}
    Public Works Department, Govt of {Gujarat | Maharashtra | Tamil Nadu | West Bengal}
    Irrigation & Waterways Dept, Govt of {Rajasthan | Uttar Pradesh | West Bengal}
    Public Health Engineering Dept, {Gujarat | Odisha}

The original head-match fallback picked whichever sibling it encountered first,
which -- db.clients being sorted -- was always the alphabetically-first one. So
"Jal Nigam in Uttar Pradesh" resolved to "Jal Nigam, Gujarat", at confidence
1.00, and every downstream number was computed over the wrong portfolio.
Six of fifteen realistic phrasings resolved to the WRONG client.

The three outcomes are not equally bad:
    correct  - the goal
    None     - safe: confidence drops to 0, the question lands in the triage log
    WRONG    - silent: a confident, plausible, completely incorrect number

This file asserts zero WRONG. A None on a hard phrasing is an acceptable result;
a WRONG never is. It also asserts that a genuinely ambiguous mention (a client
head with no distinguishing state) resolves to None rather than being guessed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import executor
import router

# (expected canonical name or None, question text)
CLIENTS = [
    # --- the ambiguous groups, phrased the way a person would ---
    ("Jal Nigam, Uttar Pradesh",
     "Jal Nigam in Uttar Pradesh — how many of their works lack a client reference letter?"),
    ("Jal Nigam, Jharkhand",
     "Jal Nigam Jharkhand: what is the combined value of their completed works?"),
    ("Jal Nigam, Gujarat",
     "What is the total value delivered for the Gujarat Jal Nigam?"),
    ("Jal Nigam, Uttar Pradesh",
     "How many distinct categories has Jal Nigam (Uttar Pradesh) commissioned?"),
    ("Public Works Department, Govt of Maharashtra",
     "What is the total for the Public Works Department in Maharashtra?"),
    ("Public Works Department, Govt of Tamil Nadu",
     "Public Works Department, Government of Tamil Nadu — average work size?"),
    ("Public Works Department, Govt of West Bengal",
     "Sum everything for PWD West Bengal."),
    ("Public Health Engineering Dept, Odisha",
     "How many works for the Public Health Engineering Dept in Odisha have no reference letter?"),
    ("Public Health Engineering Dept, Gujarat",
     "PHED Gujarat — what did we deliver as Prime?"),
    ("Irrigation & Waterways Dept, Govt of Rajasthan",
     "Total for Irrigation & Waterways Dept, Government of Rajasthan?"),
    ("Irrigation & Waterways Dept, Govt of Uttar Pradesh",
     "What is the aggregate for the Irrigation and Waterways Department in Uttar Pradesh?"),

    # --- spelling and word-order variants ---
    ("Jharkhand Municipal Corporation",
     "Jharkhand Municipal Corporation's largest work minus the second largest?"),
    ("Maharashtra Municipal Corporation",
     "For the Municipal Corporation of Maharashtra, what is the total?"),
    ("Trishakti Power Generation Corporation",
     "Trishakti Power Generation Corp — total value?"),
    ("Meridian Constructors & Co",
     "What is the average work size for Meridian Constructors and Co?"),
    ("Central Works & Buildings Bureau",
     "Central Works and Buildings Bureau — how many works have no reference letter?"),

    # --- MUST refuse to guess: head named, no distinguishing state ---
    (None, "Jal Nigam — what is the total?"),
    (None, "What is the combined value for the Public Works Department?"),
]

PERSONS = [
    ("Farhan Roy", "What is the combined value of Farhan Roy's works completed after his PMP?"),
    ("Farhan Rao", "How many distinct categories has Farhan Rao delivered?"),
    ("Farhan Khan", "Total for Farhan Khan's projects finished after certification?"),
    ("Meera Roy", "How many kinds of work has Meera Roy led?"),
    ("Meera Banerjee", "Distinct classifications delivered by Meera Banerjee?"),
    ("Meera Chatterjee", "How many categories has Meera Chatterjee completed?"),
    ("Suresh Desai", "Suresh Desai's works completed after his certification — total?"),
    ("Suresh Das", "How many categories has Suresh Das completed?"),
    ("Suresh Chopra", "Distinct work types for Suresh Chopra?"),
    ("Sunita Joshi", "Combined value of Sunita Joshi's works after her Six Sigma Black Belt?"),
    ("Gautam Joshi", "Sum Gautam Joshi's projects finished after his PMP was issued."),
    ("Imran Joshi", "How many distinct categories has Imran Joshi delivered?"),
    ("Rahul Menon", "How many distinct types has Rahul Menon delivered?"),
    ("Rahul Das", "Distinct categories for Rahul Das?"),

    # --- MUST refuse to guess: surname shared by four people ---
    (None, "How many categories has Joshi delivered?"),
]


def run(label, cases, resolve):
    ok = none = wrong = 0
    bad = []
    for want, q in cases:
        got = resolve(q)
        if got == want:
            ok += 1
        elif got is None:
            none += 1
            bad.append(("NONE", want, got, q))
        else:
            wrong += 1
            bad.append(("WRONG", want, got, q))
    print(f"\n--- {label} ---")
    print(f"  correct={ok}  none(safe)={none}  WRONG(silent)={wrong}   of {len(cases)}")
    for tag, want, got, q in bad:
        print(f"  {tag}: want={want!r} got={got!r}\n        {q}")
    return wrong, none


def main():
    db = executor.DB()
    cw, cn = run("clients", CLIENTS, lambda q: router._mine_client(db, q))
    pw, pn = run("persons", PERSONS, lambda q: router._mine_person(db, q))

    # A misresolved entity is the failure this file exists to prevent.
    wrong = cw + pw
    print(f"\n{'PASS — zero silent misresolutions' if wrong == 0 else f'FAIL — {wrong} SILENT misresolutions'}")
    if cn or pn:
        print(f"note: {cn + pn} unresolved (safe — these surface in the triage log)")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
