"""The same question must get the same answer on every run.

Python randomises set iteration order per process. Anything that iterates a
set and then keeps the first or the best-scoring member -- which the schema
matcher does for columns and for the values of a column -- answers differently
on different runs. A submission built that way is not reproducible, and an A/B
measurement taken against it is noise.

This runs the schema in-process many times over questions that put two equally
strong candidates in front of it, and asserts the answer never moves. The
cross-process case is covered by /tmp/nondet.py, which runs the whole harness
under several hash seeds; this file is the part that belongs in the suite.
"""
import subprocess
import sys

import graph
import schema

# Each of these puts at least two values of one column, or two columns of one
# table, in front of the matcher at equal strength.
CASES = [
    ("asset", "The register grades condition as new, good or fair. How many "
              "assets are graded fair, and -- no, sorry, what I want is the "
              "cost of the assets graded fair."),
    ("asset", "How many 'Hydraulic Crane 50T' units appear on the plant & "
              "machinery register?"),
    ("asset", "Of the leased assets on the register, how many are ALSO marked "
              "safety-certified?"),
    ("work", "Every completed work in Bihar for the Buildings category"),
    ("iso_cert", "How many distinct certification bodies issued our 5 "
                 "quality/safety certificates?"),
    ("reference_letter", "How many client reference letters do we hold on file "
                         "for Irrigation & Waterways Dept, Govt of Rajasthan?"),
    ("audit", "Across the conducted audits on certificate ORG-1002 "
              "(ISO 14001:2015), how many minor non-conformities in total?"),
]

_CHILD = """
import sys
sys.path.insert(0, %r)
import graph, schema
gr = graph.Graph()
sch = schema.Schema(gr.entities)
CASES = %r
for ent, q in CASES:
    print(ent, [h[:2] for h in sch.value_hits(ent, q)],
          sch.best_column(ent, q), sch.name_column(ent, q), sep="|")
    print(ent, "cols", list(sch.col_forms.get(ent, ())), sep="|")
"""


def main():
    gr = graph.Graph()
    # In-process: the index itself must not depend on iteration order.
    first = None
    for _ in range(5):
        sch = schema.Schema(gr.entities)
        snap = [(e, [h[:2] for h in sch.value_hits(e, q)],
                 sch.best_column(e, q), sch.name_column(e, q),
                 list(sch.col_forms.get(e, ()))) for e, q in CASES]
        if first is None:
            first = snap
        elif snap != first:
            for a, b in zip(first, snap):
                if a != b:
                    print("FAIL rebuild differs:\n  %s\n  %s" % (a, b))
            return 1

    # Across processes, where the hash seed actually changes.
    src = sys.path[0] or "."
    runs = set()
    for _ in range(4):
        r = subprocess.run([sys.executable, "-c", _CHILD % (src, CASES)],
                           capture_output=True, text=True)
        if r.returncode:
            print("FAIL child errored:\n" + r.stderr[-600:])
            return 1
        runs.add(r.stdout)
    if len(runs) != 1:
        print("FAIL answers move between processes:")
        for out in runs:
            print("  ---")
            for line in out.splitlines():
                print("   ", line)
        return 1

    print("test_determinism: %d cases, stable over 5 rebuilds and 4 processes"
          % len(CASES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
