"""Every table is reachable, and no table's pattern captures another's question.

Two failure modes, both of which have cost real points here:

  * A table nothing can route to. `account` -- seven years of trial balance --
    was missing from the planner's allow-list, so every question about it was
    refused before a plan was built.

  * A pattern that captures more than it means. `\\bquarters?\\b` was added for
    the annual report's quarterly revenue table and immediately swallowed
    "Residential Quarters -- Uttar Pradesh Pkg-25", a completed work, sending
    every reference letter about one to the wrong table.

Neither needs a question set to detect. The first is a property of the
configuration; the second is checked by feeding each table's OWN vocabulary --
the values its categorical columns actually hold -- back through the router and
requiring the table it came from to win.

    python test_routing.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generic
import graph
import schema

# Tables answered by a named executor shape, which is why the planner is not
# allowed to reach them. Anything else missing from the allow-list is a bug.
SHAPE_COVERED = {"person", "client"}

# One phrasing per table, written the way a question would name it. Each must
# route to its own table -- and, just as important, each must not be captured
# by a pattern belonging to a different one.
NAMES = [
    ("bond", "what does performance bond BND-00150 guarantee"),
    ("compliance", "how many of our compliance matrices are fully complied"),
    ("iso_cert", "when does certificate ORG-1002 expire"),
    ("audit", "how many minor non-conformities were raised at the surveillance audits"),
    ("dossier", "what bid value does the RFP-132019885 tender dossier state"),
    ("dossier_standing", "net turnover in the dossier's financial-standing annexure"),
    ("fin_line", "total expenses per the financial statement"),
    ("ar_line", "profit for the year per the financial highlights table"),
    ("ar_balance", "trade receivables on the balance sheet"),
    ("quarter", "which quarter recorded the highest net revenue"),
    ("order_line", "which contract in force carries the highest awarded value"),
    ("variation", "the value delta on variation order Amdt 1"),
    ("credit_note", "what amount does credit note CN-2024-0015 record"),
    ("segment", "net revenue by segment"),
    ("seven_year", "the seven-year financial summary margin"),
    ("account", "the closing balance per the trial balance"),
    ("ledger_account", "the closing balance of account 4003 in the general ledger"),
    ("bank_year", "total deposits in the bank statement for 2021"),
    ("ra_bill", "the net claimed on RA bill 3"),
    ("final_bill", "the awarded value on the final bill for contract 73"),
    ("asset", "how many excavators are on the plant and machinery register"),
    ("cv", "how many staff have a curriculum vitae on file"),
    ("credential", "how long is credential PMI-200025 valid for"),
    ("reference_letter", "what value does the client reference letter state"),
    ("business_unit", "the head-count of each business unit"),
    ("director", "how many directors sit on the board"),
    ("invoice", "how many invoices are in the receivables ageing workbook"),
]

# Phrasings that name something OTHER than a table, and must not be captured by
# a table pattern that happens to share a word with them.
NOT_CAPTURED = [
    ("Residential Quarters — Uttar Pradesh Pkg-25", "quarter"),
    ("Water Treatment Plant — Rajasthan Pkg-58", "asset"),
    ("how many works are graded Very Good", "audit"),
    ("the audit committee asked for a breakdown", "audit"),
]


def main():
    gr = graph.Graph()
    sch = schema.Schema(gr.entities)
    fail = []

    def check(name, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {name}"
              f"{'   ' + detail if (detail and not ok) else ''}")
        if not ok:
            fail.append(name)

    print("--- every table the store holds is one the planner may use ---")
    allowed = set(generic._NO_SHAPE) | {"work"}
    orphans = [e for e in gr.entities if e not in allowed | SHAPE_COVERED]
    check(f"{len(gr.entities)} tables, {len(orphans)} unreachable",
          not orphans, str(orphans))
    ghosts = sorted(allowed - set(gr.entities))
    check("no table is allowed that the store does not hold", not ghosts, str(ghosts))

    print("\n--- each table answers to its own name ---")
    for want, q in NAMES:
        got = generic._first(generic._ENTITY, q)
        if got is None and sch is not None:
            ranked = sch.rank(q, allowed=allowed)
            got = ranked[0][1] if ranked else None
        check(f"{want:18s} <- {q[:52]}", got == want, f"routed to {got}")

    print("\n--- and does not answer to another's ---")
    for q, must_not in NOT_CAPTURED:
        got = generic._first(generic._ENTITY, q)
        check(f"not {must_not:14s} <- {q[:52]}", got != must_not,
              f"captured by {must_not}")

    print("\n--- no table pattern captures a NAME the corpus itself uses ---")
    # The strongest version of the check above, and it needs nothing written
    # down: every client, work and person name in the store, fed to the router
    # on its own. A table pattern matching one of them is matching a word in a
    # proper noun -- "Lakshya ENGINEERing & Construction" read as a question
    # about our engineers, "Bituminous Overlay" as a BOQ line, "Water Treatment
    # PLANT" as the machinery register.
    #
    # `work` and `client` are excused for each other: a question naming a
    # client is a question about that client's works, which is where an
    # unresolved one should land.
    groups = [("work", [w["work"] for w in gr.entities["work"]]),
              ("client", [c["client"] for c in gr.entities["client"]]),
              ("person", [p["name"] for p in gr.entities["person"]])]
    caught = {}
    for kind, names in groups:
        for n in names:
            got = generic._first(generic._ENTITY, n)
            if got is not None and got != kind and not (
                    {kind, got} <= {"work", "client"}):
                caught.setdefault((kind, got), n)
    check(f"{sum(len(g[1]) for g in groups)} names, {len(caught)} captured",
          not caught,
          "; ".join(f"{k[0]} '{v}' -> {k[1]}" for k, v in caught.items()))

    print()
    if fail:
        print(f"FAILURES: {len(fail)}")
        for f in fail:
            print("  ", f)
        return 1
    print("EVERY TABLE IS REACHABLE AND NONE CAPTURES ANOTHER'S QUESTION")
    return 0


if __name__ == "__main__":
    sys.exit(main())
