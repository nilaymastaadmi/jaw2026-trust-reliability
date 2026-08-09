"""Router stress test: paraphrases the router has never seen.

The 25 samples validate the pipeline against ONE phrasing per shape. The hidden
set is "larger and harder" and "written in natural language, not templated", so
the untested risk is a paraphrase the regex rules miss. These cases are written
to be plausible for the hidden set -- chatty, varied, synonym-heavy -- and are
deliberately NOT copied from the samples.

Each case asserts the shape and the parameters that shape depends on. It does
not assert an answer: correctness of the arithmetic is already covered by
test_executor.py and test_components.py. What is under test here is routing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import executor
import router

# (shape, question, required params) -- params checked only where given
CASES = [
    # ---------------------------------------------------------- absence
    ("absence", "How many of Jal Nigam, Jharkhand's completed works have no reference letter?",
     {"client": "Jal Nigam, Jharkhand"}),
    ("absence", "For Jharkhand Municipal Corporation, count the projects missing a client reference letter.",
     {"client": "Jharkhand Municipal Corporation"}),
    ("absence", "Public Health Engineering Dept, Gujarat — how many jobs are we lacking letters for?",
     {"client": "Public Health Engineering Dept, Gujarat"}),
    ("absence", "I need to know how many works for Mega Infrastructure Authority don't have a reference letter on file.",
     {"client": "Mega Infrastructure Authority"}),

    # ---------------------------------------------------- referenced_share
    ("referenced_share", "What percentage of Jal Nigam, Jharkhand's works carry a reference letter?",
     {"client": "Jal Nigam, Jharkhand"}),
    ("referenced_share", "For Suvarna Projects Limited, what share of completed assignments have formal verification?",
     {"client": "Suvarna Projects Limited"}),
    ("referenced_share", "Jharkhand Municipal Corporation — what number out of one hundred represents referenced works?",
     {"client": "Jharkhand Municipal Corporation"}),

    # ---------------------------------------------------------- rank_value
    ("rank_value", "For Jal Nigam, Jharkhand, how much does the biggest contract exceed the second biggest?",
     {"client": "Jal Nigam, Jharkhand"}),
    ("rank_value", "Mahanadi Steel Corporation: what's the gap between the largest work and the runner-up?",
     {"client": "Mahanadi Steel Corporation"}),
    ("rank_value", "What is the difference between the highest and second highest value work for Arunodaya Infrastructure?",
     {"client": "Arunodaya Infrastructure"}),

    # ------------------------------------------------- threshold_aggregate
    ("threshold_aggregate", "Sum Jal Nigam, Jharkhand's works north of seventy-three crore.",
     {"client": "Jal Nigam, Jharkhand", "threshold": 730000000}),
    ("threshold_aggregate", "For Maharashtra Municipal Corporation, total the contracts above INR 6 Cr.",
     {"client": "Maharashtra Municipal Corporation", "threshold": 60000000}),
    ("threshold_aggregate", "Trishakti Power Generation Corporation — combined value of works exceeding fifty crore?",
     {"client": "Trishakti Power Generation Corporation", "threshold": 500000000}),
    ("threshold_aggregate", "What do Mega Infrastructure Authority's projects in excess of 20 Cr add up to?",
     {"client": "Mega Infrastructure Authority", "threshold": 200000000}),

    # --------------------------------------------------- gap_to_threshold
    ("gap_to_threshold", "How much additional work must we win from Jal Nigam, Gujarat to reach INR 200 Cr?",
     {"client": "Jal Nigam, Gujarat", "threshold": 2000000000}),
    ("gap_to_threshold", "Peninsular Petroleum Corporation — what's the shortfall against a credential target of 50 crore?",
     {"client": "Peninsular Petroleum Corporation", "threshold": 500000000}),

    # ------------------------------------------------- exclusion_aggregate
    ("exclusion_aggregate", "Total Irrigation & Waterways Dept, Govt of West Bengal's works, excluding buildings.",
     {"client": "Irrigation & Waterways Dept, Govt of West Bengal", "category": "buildings"}),
    ("exclusion_aggregate", "For Jharkhand Municipal Corporation, sum everything apart from roads maintenance.",
     {"client": "Jharkhand Municipal Corporation"}),
    ("exclusion_aggregate", "Central Works & Buildings Bureau — combined value other than tunnels?",
     {"client": "Central Works & Buildings Bureau"}),

    # ---------------------------------------------- doc_filtered_aggregate
    ("doc_filtered_aggregate", "Sum the Jal Nigam, Jharkhand projects graded Satisfactory on their certificates.",
     {"client": "Jal Nigam, Jharkhand", "grading": "Satisfactory"}),
    ("doc_filtered_aggregate", "Irrigation & Waterways Dept, Govt of Uttar Pradesh rated some works Excellent — what do those total?",
     {"client": "Irrigation & Waterways Dept, Govt of Uttar Pradesh", "grading": "Excellent"}),
    ("doc_filtered_aggregate", "For Mega Infrastructure Authority, total the assignments marked Very Good.",
     {"client": "Mega Infrastructure Authority", "grading": "Very Good"}),

    # ------------------------------------------------------ avg_work_size
    ("avg_work_size", "What's the typical project size across Jal Nigam, Jharkhand's portfolio?",
     {"client": "Jal Nigam, Jharkhand"}),
    ("avg_work_size", "Average contract value for Subarnarekha Valley Corporation?",
     {"client": "Subarnarekha Valley Corporation"}),
    ("avg_work_size", "For Tamil Nadu Municipal Corporation, what is the mean size of the works we've delivered?",
     {"client": "Tamil Nadu Municipal Corporation"}),

    # ---------------------------------------------------------- role_split
    ("role_split", "Public Health Engineering Dept, Gujarat — what did we deliver as Prime?",
     {"client": "Public Health Engineering Dept, Gujarat", "role": "Prime"}),
    ("role_split", "For Jharkhand Municipal Corporation, total the work where we acted as JV Partner.",
     {"client": "Jharkhand Municipal Corporation", "role": "JV Partner"}),

    # ------------------------------------------------------ hop_aggregate
    ("hop_aggregate", "Neha Chopra led work for Lakshya Engineering & Construction. What's the combined value for that client?",
     {"client": "Lakshya Engineering & Construction"}),
    ("hop_aggregate", "Starting from Rahul Menon's certification, what is the total value of everything for Public Works Department, Govt of Maharashtra?",
     {"client": "Public Works Department, Govt of Maharashtra"}),

    # ------------------------------------------------------ temporal_chain
    ("temporal_chain", "What's the combined value of the works Asha Nair delivered after her PMP certification date?",
     {"person": "Asha Nair", "credential": "PMP"}),
    ("temporal_chain", "Sum the projects Gautam Joshi finished after his PMP was issued.",
     {"person": "Gautam Joshi"}),
    ("temporal_chain", "For Sunita Joshi, total the assignments completed after her Six Sigma Black Belt certification.",
     {"person": "Sunita Joshi", "credential": "Six Sigma Black Belt"}),

    # ------------------------------------------------------ distinct_count
    ("distinct_count", "How many different kinds of work has Chandan Banerjee delivered?",
     {"person": "Chandan Banerjee"}),
    ("distinct_count", "Count the distinct work classifications Neha Chopra has completed.",
     {"person": "Neha Chopra"}),
    ("distinct_count", "How many unique categories has Meera Roy led to completion?",
     {"person": "Meera Roy"}),

    # ----------------------------------------------------------- date_span
    ("date_span", "How many days passed between Asha Nair's PMP issuance and the completion of School Building — Madhya Pradesh Pkg-145?",
     {"person": "Asha Nair"}),
    ("date_span", "What is the interval in days from Chandan Banerjee's certification to the finish of WTP Augmentation — West Bengal Pkg-51?",
     {"person": "Chandan Banerjee"}),

    # ================================================================
    # REGRESSION GUARDS — every case below is a bug that shipped.
    #
    # The exclusion block is the important one. The category miner required a
    # comma/period/end-of-string terminator, so an exclusion trailing the
    # sentence ("...excluding buildings?") mined NOTHING, and the shape then
    # summed the entire portfolio: 52.9% error, reported at confidence 1.00
    # with no triage signal. Confident and wrong is the worst failure the
    # scoring bands can punish. Keep every phrasing here.
    # ================================================================
    ("exclusion_aggregate", "What is the aggregate value of every project for Irrigation & Waterways Dept, Govt of West Bengal, excluding buildings?",
     {"client": "Irrigation & Waterways Dept, Govt of West Bengal", "category": "buildings"}),
    ("exclusion_aggregate", "Total the works for Irrigation & Waterways Dept, Govt of West Bengal, but not buildings.",
     {"category": "buildings"}),
    ("exclusion_aggregate", "What have we delivered in total for Irrigation & Waterways Dept, Govt of West Bengal apart from buildings?",
     {"category": "buildings"}),
    ("exclusion_aggregate", "Ignoring buildings, what is the total for Irrigation & Waterways Dept, Govt of West Bengal?",
     {"category": "buildings"}),
    ("exclusion_aggregate", "For Jharkhand Municipal Corporation, sum everything leaving out roads maintenance.",
     {"category": "roads maintenance"}),

    # "share of" is a referenced_share trigger; role_split must win when a role
    # is named, or a rupee total is answered as a percentage.
    ("role_split", "What is our JV Partner share of the Public Works Department, Govt of Maharashtra?",
     {"client": "Public Works Department, Govt of Maharashtra", "role": "JV Partner"}),

    ("temporal_chain", "What's the combined value of Gautam Joshi's projects that closed out post-certification?",
     {"person": "Gautam Joshi"}),
    ("temporal_chain", "Total value of Imran Joshi's works finishing later than his PMP date?",
     {"person": "Imran Joshi"}),
    ("doc_filtered_aggregate", "Jal Nigam, Jharkhand: total value where the grading is Excellent.",
     {"client": "Jal Nigam, Jharkhand", "grading": "Excellent"}),
]


def main():
    db = executor.DB()
    shape_fail, param_fail, exec_fail = [], [], []

    for want_shape, q, want_params in CASES:
        plan = router.route(db, q)
        got_shape = plan["shape"]
        ok_shape = got_shape == want_shape

        bad = {}
        for k, v in want_params.items():
            if plan.get(k) != v:
                bad[k] = (v, plan.get(k))

        result = executor.run(db, plan) if ok_shape else None
        ran = result is not None

        mark = "OK " if (ok_shape and not bad and ran) else "XX "
        print(f"  {mark}{want_shape:22s} -> {got_shape:22s} "
              f"{'' if not bad else 'PARAM ' + str(bad)}"
              f"{'' if ran or not ok_shape else ' EXEC=None'}")
        if not ok_shape:
            shape_fail.append((want_shape, got_shape, q))
        elif bad:
            param_fail.append((want_shape, bad, q))
        elif not ran:
            exec_fail.append((want_shape, q))

    n = len(CASES)
    ok = n - len(shape_fail) - len(param_fail) - len(exec_fail)
    print(f"\n{ok}/{n} fully correct   "
          f"(shape errors {len(shape_fail)}, param errors {len(param_fail)}, "
          f"exec-None {len(exec_fail)})")

    for label, items in (("SHAPE", shape_fail), ("PARAM", param_fail), ("EXEC", exec_fail)):
        if items:
            print(f"\n--- {label} failures ---")
            for it in items:
                print(f"  {it}")
    return 0 if ok == n else 1


if __name__ == "__main__":
    sys.exit(main())
