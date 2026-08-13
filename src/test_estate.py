"""The parsed estate, checked against the documents' own arithmetic.

The point of this file is that it uses NO questions. Every check below is an
identity the document itself asserts -- an RA bill's net claimed equals its
value of work plus GST less retention, a bank statement's running balance
equals the previous balance plus the deposit less the withdrawal, a profit and
loss statement's total expenses equal the sum of its expense lines. If the
parser reads the document correctly the identity holds; if it does not, the
identity breaks and names the field.

That matters because the alternative -- tuning a parser until a question set
scores well -- fits the parser to the questions. These checks cannot be fitted
to anything: they were written into the documents by whoever generated them.

    python test_estate.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus
import parse_documents


def near(a, b, tol=1):
    return a is not None and b is not None and abs(a - b) <= tol


def main():
    path = corpus.WORK / "estate.json"
    est = (json.loads(path.read_text(encoding="utf-8")) if path.exists()
           else parse_documents.build(verbose=False))
    fail = []

    def check(name, ok, detail=""):
        # Detail only on failure: printed next to a PASS it reads as one.
        print(f"  {'PASS' if ok else 'FAIL'}  {name}"
              f"{'   ' + detail if (detail and not ok) else ''}")
        if not ok:
            fail.append(name)

    print("--- coverage: every document of each type parsed ---")
    for key, want in [("bonds", 60), ("compliance", 40), ("iso_certs", 5),
                      ("dossiers", 6), ("financials", 7), ("ra_bills", 6),
                      ("final_bills", 6), ("bank", 8), ("ledgers", 8),
                      ("annual_reports", 2)]:
        check(f"{key:15s} {len(est[key]):3d}/{want}", len(est[key]) == want)

    print("\n--- bonds: every one carries the fields a bond states ---")
    for f in ("bond_no", "issue_date", "bank", "tender_ref", "amount", "work"):
        miss = [b["doc"] for b in est["bonds"] if b.get(f) is None]
        check(f"every bond has {f}", not miss, f"missing in {len(miss)}")
    longs = [b for b in est["bonds"] if b["guarantee_pct"] is not None]
    check("the long template states a percentage", len(longs) == 28,
          f"{len(longs)} of 60")
    check("every long-template bond guarantees something",
          all(b["amount"] for b in longs))

    print("\n--- RA bills: net claimed = work + GST - retention ---")
    for b in est["ra_bills"]:
        v, g, r, n = b["value_of_work"], b["gst"], b["retention"], b["net_claimed"]
        check(f"{b['doc']} identity", near(n, (v or 0) + (g or 0) - (r or 0), 2),
              f"{v} + {g} - {r} = {n}")
        check(f"{b['doc']} GST at the stated rate",
              near(g, round((v or 0) * (b["gst_pct"] or 0) / 100), 2))
        check(f"{b['doc']} retention at the stated rate",
              near(r, round((v or 0) * (b["retention_pct"] or 0) / 100), 2))
        check(f"{b['doc']} items sum to the value",
              near(sum(i["amount"] for i in b["items"]), v, 2))

    print("\n--- final bills: BOQ total = the printed total, RA bills accumulate ---")
    for b in est["final_bills"]:
        check(f"{b['doc']} items sum to executed",
              near(sum(i['amount'] for i in b["items"]), b["executed"], 2),
              f"{sum(i['amount'] for i in b['items'])} vs {b['executed']}")
        if b["bills"]:
            check(f"{b['doc']} RA values sum to the last cumulative",
                  near(sum(x["value"] for x in b["bills"]),
                       b["bills"][-1]["cumulative"], 2))
        check(f"{b['doc']} awarded exceeds executed",
              b["awarded"] is not None and b["executed"] is not None
              and b["awarded"] > b["executed"])

    print("\n--- financial statements: the P&L adds up (stored in rupees) ---")
    L = 10 ** 5
    for f in est["financials"]:
        ln = f["lines"]
        def g(k, side="current"):
            return (ln.get(k) or {}).get(side)
        rev = g("Total Revenue from Operations (A)")
        check(f"{f['doc']} revenue = contract + other",
              near(rev, (g("Contract Revenue (EPC)") or 0)
                   + (g("Other Operating Revenue") or 0), L))
        exp = g("Total Expenses (B)")
        parts = ["Cost of Materials Consumed", "Sub-contracting & Labour",
                 "Employee Benefit Expenses", "Depreciation & Amortisation",
                 "Other Expenses"]
        check(f"{f['doc']} expenses = the five lines",
              near(exp, sum(g(p) or 0 for p in parts), L))
        check(f"{f['doc']} amounts are rupees not lakhs",
              rev is not None and rev > 10 ** 7)

    print("\n--- bank statements: the running balance is consistent ---")
    for s in est["bank"]:
        # The year as a whole, not just row to row: opening plus everything in
        # less everything out must equal the closing balance. The row-by-row
        # check passed while the FIRST transaction was misclassified, because
        # it started comparing at the second row.
        check(f"{s['doc']} opening + in - out = closing",
              near(s["opening"] + s["deposits"] - s["withdrawals"], s["closing"], 2),
              f"{s['opening']} + {s['deposits']} - {s['withdrawals']} != {s['closing']}")
        rows, bad = s["rows"], 0
        for i in range(1, len(rows)):
            prev, cur = rows[i - 1]["balance"], rows[i]
            want = (prev or 0) + (cur["deposit"] or 0) - (cur["withdrawal"] or 0)
            if not near(cur["balance"], want, 2):
                bad += 1
        check(f"{s['doc']} {len(rows):3d} rows", bad == 0, f"{bad} inconsistent")

    print("\n--- ISO certificates: validity span and NC counts ---")
    for c in est["iso_certs"]:
        check(f"{c['doc']} has a standard and a span",
              c["standard"] and c["validity_days"] and c["validity_days"] > 0,
              f"{c['standard']} {c['validity_days']}d")
        check(f"{c['doc']} audits parsed", len(c["audits"]) >= 3,
              f"{len(c['audits'])} audits")

    print("\n--- annual report: its own tables, in rupees ---")
    for a in est["annual_tables"]:
        bs = a["balance_sheet"]
        eq = [r for r in bs if r["section"] == "Equity and Liabilities"]
        asset = [r for r in bs if r["section"] == "Assets"]
        # The report's own arithmetic: each side carries a Total row, and the
        # two sides agree.
        te = next((r["amount"] for r in eq if r["line"].lower() == "total"), None)
        ta = next((r["amount"] for r in asset if r["line"].lower() == "total"), None)
        check(f"{a['doc']} balance sheet balances", near(te, ta, 2), f"{te} vs {ta}")
        check(f"{a['doc']} equity and liabilities sum to their total",
              near(sum(r["amount"] for r in eq if r["line"].lower() != "total"),
                   te, 2))
        check(f"{a['doc']} assets sum to their total",
              near(sum(r["amount"] for r in asset if r["line"].lower() != "total"),
                   ta, 2))
        pl = {r["line"]: r["amount"] for r in a["profit_and_loss"]}
        rev = pl.get("Revenue from operations (net)")
        prof = pl.get("Profit for the year")
        exp = sum(v for k, v in pl.items()
                  if k not in ("Revenue from operations (net)", "Profit for the year"))
        check(f"{a['doc']} revenue - expenses = profit for the year",
              near(rev - exp, prof, 2), f"{rev} - {exp} != {prof}")
        check(f"{a['doc']} four quarters", len(a["quarters"]) == 4)
        check(f"{a['doc']} order book has 17 contracts in force",
              len(a["order_lines"]) == a["contracts_in_execution"],
              f"{len(a['order_lines'])} vs {a['contracts_in_execution']}")
        check(f"{a['doc']} awarded + variations = current value on every line",
              all(near(r["awarded"] + r["variations"], r["current_value"], 2)
                  for r in a["order_lines"]))
        check(f"{a['doc']} order book sums to the aggregate awarded value",
              near(sum(r["awarded"] for r in a["order_lines"]),
                   a["order_book_awarded"], 10 ** 5),
              f"{sum(r['awarded'] for r in a['order_lines'])} vs "
              f"{a['order_book_awarded']}")
        check(f"{a['doc']} every variation row carries its four fields",
              all(r["contract"] and r["amendment"] and r["date"]
                  and r["value_delta"] is not None for r in a["variations"]),
              str(len(a["variations"])))
        check(f"{a['doc']} credit notes match the stated count",
              len(a["credit_note_list"]) == a["credit_notes"],
              f"{len(a['credit_note_list'])} vs {a['credit_notes']}")

    # The order book is a SNAPSHOT and both reports print the same one; the
    # variation annexures are the movements behind it, one report per year.
    # Every variation figure the order book carries is one contract's
    # amendments summed ACROSS both annexures -- contract #90 moved 7,593,914
    # in FY2024-25 and 7,973,471 in FY2025-26, and the order book shows
    # 15,567,385. That ties three tables together and breaks if any is misread.
    per = {}
    for a in est["annual_tables"]:
        for v in a["variations"]:
            per[v["contract"]] = per.get(v["contract"], 0) + v["value_delta"]
    latest = max(est["annual_tables"], key=lambda x: x.get("year") or 0)
    ob = {r["variations"] for r in latest["order_lines"] if r["variations"]}
    check("every order-book variation total is a contract's amendments summed",
          ob <= set(per.values()), f"{sorted(ob - set(per.values()))}")

    print("\n--- compliance matrices and dossiers ---")
    # Exactly two layouts, and each states its own length: the short checklist
    # numbers 8 requirements, the long eligibility-cum-compliance matrix 17.
    # Counting standalone status tokens instead gave the long one 18 -- the
    # evidence column leaves a bare "N/A" on its own line -- which also
    # invented one requirement not met in all 19 of them.
    check("every matrix has 8 or 17 numbered requirements",
          {c["requirements"] for c in est["compliance"]} == {8, 17},
          str(sorted({c["requirements"] for c in est["compliance"]})))
    check("the serial numbers run 1..n with no gaps",
          all([r["n"] for r in c["rows"]] == list(range(1, c["requirements"] + 1))
              for c in est["compliance"]))
    check("complied + not complied = requirements",
          all(c["complied"] + c["not_complied"] == c["requirements"]
              for c in est["compliance"]))
    check("every matrix quotes a turnover bar",
          all(c["turnover_req"] for c in est["compliance"]))
    check("every dossier lists 8 annexures, 10 registrations, 5 true copies",
          all(d["annexures"] == 8 and d["registrations"] == 10
              and d["cert_copies"] == 5 for d in est["dossiers"]),
          str([(d["annexures"], d["registrations"], d["cert_copies"])
               for d in est["dossiers"]]))
    check("every dossier states the bid security it lodged",
          all(d["bid_security"] and d["bid_security_bank"]
              for d in est["dossiers"]))
    check("every dossier has 6 business units",
          all(len(d["units"]) == 6 for d in est["dossiers"]),
          str([len(d["units"]) for d in est["dossiers"]]))
    check("dossier head-count = sum of its units",
          all(d["headcount"] == sum(u["headcount"] for u in d["units"])
              for d in est["dossiers"]))
    check("every dossier states a bid value",
          all(d["bid_value"] for d in est["dossiers"]))

    print("\n--- general ledgers and annual reports ---")
    check("every ledger year has accounts",
          all(len(l["accounts"]) >= 4 for l in est["ledgers"]),
          str([len(l["accounts"]) for l in est["ledgers"]]))
    check("every annual report lists directors",
          all(a["director_count"] >= 3 for a in est["annual_reports"]),
          str([a["director_count"] for a in est["annual_reports"]]))

    print("\n--- completeness: every document yields the fields it states ---")
    # This is the check that would have caught, on the day the parser was
    # written, that half the certificates and a third of the letters use a
    # SECOND TEMPLATE. Each of those gaps was found by a question instead --
    # which only happens if a question happens to ask.
    for key, total, field, want in [
            ("company_certs", 155, "work", 155),
            ("company_certs", 155, "value", 155),
            ("company_certs", 155, "defect_liability_days", 155),
            ("cvs", 39, "joined", 39),
            ("cvs", 39, "experience_years", 39),
            ("credentials", 48, "validity_days", 48),
            ("reference_letters", 132, "work", 132),
            # Three templates, four money renderings between them. Two of the
            # three patterns omitted the bare Indian-grouped form and lost the
            # value on 19 letters, which is the fact most of the questions
            # about them ask for.
            ("reference_letters", 132, "value", 132),
            ("reference_letters", 132, "client", 132),
            ("bonds", 60, "amount", 60),
            ("compliance", 40, "turnover_req", 40),
            ("dossiers", 6, "bid_value", 6)]:
        got = sum(1 for r in est.get(key, []) if r.get(field) is not None)
        check(f"{key}.{field:24s} {got:3d}/{want}", got >= want)

    print("\n--- cross-source: two independent readings of the same fact ---")
    # The contractor's certificate copy and the client's are separate documents
    # describing the same 155 works, and 113 reference letters restate the value
    # a third time. Agreement is the strongest evidence available that the
    # extraction is right, and it needs no question set at all.
    db = corpus.load_json("db.json")
    cc = {w["work"]: w for w in db["works"]}
    ccc = {c["work"]: c for c in est["company_certs"] if c.get("work")}
    both = set(cc) & set(ccc)
    check(f"client and contractor copies cover the same works  {len(both)}/155",
          len(both) == 155)
    for f_a, f_b in (("value", "value"), ("completed", "completed"),
                     ("category", "category"), ("lead", "manager")):
        dis = [w for w in both
               if str(cc[w].get(f_a) or "").lower()[:10]
               != str(ccc[w].get(f_b) or "").lower()[:10]]
        check(f"the two copies agree on {f_a:10s} {len(both) - len(dis):3d}/{len(both)}",
              not dis, ("e.g. " + str(dis[:1])) if dis else "")
    # The one work whose value is not a clean multiple of a lakh is rendered
    # two ways across the corpus: 193,299,999 in raw digits and 193.30 Cr when
    # rounded. The raw figure is canonical -- the organisers' own worked example
    # HS-IC-0007 sums to 2,008,199,999 using it.
    letters = {r["work"]: r["value"] for r in est["reference_letters"]
               if r.get("value") and r.get("work") in cc}
    dis = [w for w, v in letters.items() if v != cc[w]["value"]]
    check(f"reference letters agree with the certificates  "
          f"{len(letters) - len(dis)}/{len(letters)}",
          all(w == "Road Widening — Maharashtra Pkg-21" for w in dis),
          f"unexplained: {[w for w in dis if 'Pkg-21' not in w][:2]}")

    print()
    if fail:
        print(f"FAILURES: {len(fail)}")
        for f in fail[:20]:
            print(f"   {f}")
        sys.exit(1)
    print("THE PARSED ESTATE AGREES WITH THE DOCUMENTS")


if __name__ == "__main__":
    main()
