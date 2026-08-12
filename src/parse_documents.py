"""The nine document types no shape could reach, parsed into entities.

WHY
---
`build_db.py` reads the certificates, reference letters and personnel records;
`parse_workbooks.py` reads the four Excel files. Between them that is 375 of the
687 documents. The other 312 -- performance bonds, compliance matrices, ISO
certificates, tender dossiers, financial statements, RA bills, bank statements,
general ledgers and annual reports -- were never opened, so any question about
them could only be guessed at.

Every one of them is regular. The bonds state a bond number, an issuing bank, a
tender reference, a guarantee percentage and an amount; the compliance matrices
are numbered checklists with a status per row; the RA bills carry BOQ lines,
GST at 18%, retention at 5% and a cumulative position. Parsing is a matter of
reading each layout once.

Two traps carried over from the rest of the corpus, and one new one:

  * Money is written four ways -- `INR 127.18 Cr`, `Rs. 65.46 Lakh`,
    `81,10,00,652`, and bare `811000652` -- sometimes twice in one sentence.
  * Financial statements are stated **in lakhs**. Every figure there is
    multiplied by 100,000 on the way in, so the store holds rupees throughout
    and no consumer has to remember the unit.
  * PDF text extraction puts each table cell on its own line, so a row is a
    RUN of lines rather than one line. Every table here is read as a run.

-> work/estate.json
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus
import normalize


def _flat(t):
    """Whitespace collapsed to single spaces.

    These PDFs wrap prose mid-phrase -- "an amount not\nexceeding INR 1.73 Cr"
    -- so a regex written the way the sentence reads misses a third of the
    bonds and silently records no guarantee at all. Table rows still need the
    line breaks, so this is used only where the field is prose.
    """
    return re.sub(r"\s+", " ", t)


def _text(doc_id):
    p = corpus.CACHE / f"{doc_id}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _docs(prefix):
    return sorted(p.stem for p in corpus.CACHE.glob(f"{prefix}*.txt"))


def _money(s):
    return normalize.money(s) if s else None


def _num(s):
    """A bare number with Indian or Western grouping -> int, or None."""
    if s is None:
        return None
    s = str(s).replace(",", "").replace("(", "-").replace(")", "").strip()
    try:
        return round(float(s))
    except ValueError:
        return None


def _after(text, label, pattern=r"(.+)"):
    """The value on the line after `label`, which is how these tables extract."""
    m = re.search(re.escape(label) + r"\s*\n\s*" + pattern, text, re.I)
    return m.group(1).strip() if m else None


# ------------------------------------------------------------------- bonds

def bonds():
    out = []
    for doc in _docs("DOC-BOND-"):
        t = _text(doc)
        f = _flat(t)
        no = re.search(r"(?:Bond No|BG No|Bond Reference)\s*:?\s*([A-Z]+[/-][\w-]+)", f, re.I)
        date = re.search(r"(?:Issue Date|Date)\s*:?\s*(\d{4}-\d{2}-\d{2}|\d{1,2} \w{3,9} \d{4}"
                         r"|\w{3,9} \d{1,2},? \d{4})", f, re.I)
        bank = re.search(r"^([A-Z][\w &.]+Bank[\w ]*)$", t, re.M)
        tender = re.search(r"(RFP-\d+)", f)
        pct = re.search(r"for\s+([\d.]+)%\s*\(", f, re.I)
        # The guaranteed amount, stated twice; both forms are read and the
        # larger taken, because "Rs. 0" appears in the short template where the
        # figure was not filled in.
        # 32 of the 60 use a short template that states a guarantee of zero.
        # That is the corpus's own figure, not a parse failure, so a zero is
        # kept as a zero -- dropping it as falsy would have made a stated
        # nothing indistinguishable from an unreadable something.
        amts = [_money(m.group(1)) for m in
                re.finditer(r"not\s+exceeding\s+(Rs\.?\s*[\d.,]+\s*(?:Lakh|Cr|Crore)s?|"
                            r"INR\s*[\d.,]+\s*(?:Lakh|Cr|Crore)s?|Rs\.?\s*[\d,]+"
                            r"|INR\s*[\d,]+)", f, re.I)]
        amts = [a for a in amts if a is not None]
        work = re.search(r"(?:for the work of|Performance Bond\s*[—-]\s*|Subject:.*?[—-]\s*)"
                         r"([A-Za-z &]+?)(?:\s*Works?)?\s*(?:,|\(|Tender)", f)
        valid = re.search(r"(?:valid from\s+(\S+)\s+until\s+(\S+)"
                          r"|in force up to and including\s+([\d\w ]+?),)", f, re.I)
        status = re.search(r"Bond Reference \S+ Status (\w+)", f, re.I)
        stamp = re.search(r"Stamp Paper\s*[\u2014-]\s*Value:\s*(INR\s*[\d,.]+)", f, re.I)
        d_iss = normalize.parse_date(date.group(1)) if date else None
        d_end = normalize.parse_date(valid.group(2) or valid.group(3) or "") if valid else None
        # The long template states the date the guarantee comes into force; the
        # short one runs from issue. Either way the validity SPAN is arithmetic
        # over two dates already on the page, and questions ask for it.
        d_from = (normalize.parse_date(valid.group(1))
                  if (valid and valid.group(1)) else d_iss)
        out.append({
            "doc": doc,
            "bond_no": no.group(1) if no else None,
            "issue_date": normalize.parse_date(date.group(1)).isoformat() if date and normalize.parse_date(date.group(1)) else (date.group(1) if date else None),
            "bank": bank.group(1).strip() if bank else None,
            "tender_ref": tender.group(1) if tender else None,
            "guarantee_pct": float(pct.group(1)) if pct else None,
            "amount": max(amts) if amts else None,
            "work": work.group(1).strip() if work else None,
            "valid_from": d_from.isoformat() if d_from else None,
            "valid_until": (d_end.isoformat() if d_end else
                            ((valid.group(2) or valid.group(3)) if valid else None)),
            "validity_days": (d_end - d_from).days if (d_end and d_from) else None,
            "stamp_value": _money(stamp.group(1)) if stamp else None,
            "status": status.group(1) if status else None,
        })
    return out


# ------------------------------------------------------- compliance matrices

# Two templates, and in both the rows break across page boundaries -- a
# requirement's text can be separated from its status by a footer, a page
# number and a heading. Reconstructing rows from that is guesswork; counting
# the STATUS tokens is not, and the status is the only field a question about
# compliance actually asks for.
_STATUS = re.compile(r"^(Complied|Not Complied|Partially Complied|Not complied"
                     r"|MET|NOT MET|Not Met|N/A|Pending)$", re.M)
_MET = {"complied", "met"}


def compliance():
    out = []
    for doc in _docs("DOC-CM-"):
        t = _text(doc)
        tender = re.search(r"(RFP-\d+)", t)
        f = _flat(t)
        work = re.search(r"Tender (?:Ref: )?RFP-\d+\s*(?:·|\u00b7)?\s*([A-Za-z][A-Za-z &]{3,40}?)"
                         r"\s*(?:CM/|Bid Value|\d)", f)
        st = [m.group(1) for m in _STATUS.finditer(t)]
        reqs = [{"n": i + 1, "status": v} for i, v in enumerate(st)]
        turnover = re.search(r"(?:turnover requirement\s*\(|Annual Turnover\s*>?=?\s*)"
                             r"(?:Rs\.?|INR)\s*([\d.,]+)\s*(Cr|Crore|Lakh)", f, re.I)
        staff = re.search(r"[Kk]ey technical staff\s*\((\d+)\s*minimum\)"
                          r"|Minimum\s+(\d+)\s+site engineers", f)
        assets = re.search(r"(\d+)\s+owned assets|Asset register on record\s*\((\d+)\s*items\)", f)
        people = re.search(r"(\d+)\s+personnel on rolls|(\d+)\s+engineers available", f)
        emd = re.search(r"(EMD-\d+)", f)
        emd_amt = re.search(r"EMD Amount\s+((?:INR|Rs\.?)\s*[\d.,]+\s*(?:Cr|Crore|Lakh)s?)"
                            r"(?:\s*\(([\d.]+)%\))?", f, re.I)
        bid = re.search(r"Bid Value\s+((?:INR|Rs\.?)\s*[\d.,]+\s*(?:Cr|Crore|Lakh)s?)", f, re.I)
        subd = re.search(r"Bid Submission Date\s+(\d{4}-\d{2}-\d{2})", f, re.I)
        years = re.search(r"FY\s*(\d{4})\s*[–-]\s*(?:FY)?\s*(\d{4})", f)
        def _g(m):
            return next((x for x in (m.groups() if m else ()) if x), None)
        out.append({
            "doc": doc,
            "tender_ref": tender.group(1) if tender else None,
            "work": work.group(1).strip() if work else None,
            "requirements": len(reqs),
            "complied": sum(1 for r in reqs if r["status"].lower() in _MET),
            "not_complied": sum(1 for r in reqs if r["status"].lower() not in _MET),
            "rows": reqs,
            "turnover_req": (_money(turnover.group(1) + " " + turnover.group(2))
                             if turnover else None),
            "staff_min": int(_g(staff)) if _g(staff) else None,
            "owned_assets": int(_g(assets)) if _g(assets) else None,
            "personnel": int(_g(people)) if _g(people) else None,
            "emd_ref": emd.group(1) if emd else None,
            # Some matrices quote the EMD only as a percentage of the bid.
            # The rupee figure is derivable and is what a question asks for.
            "emd_amount": (_money(emd_amt.group(1)) if emd_amt else
                           (round(_money(bid.group(1)) * float(emd_amt.group(2)) / 100)
                            if (emd_amt and emd_amt.group(2) and bid) else None)),
            "emd_pct": float(emd_amt.group(2)) if emd_amt and emd_amt.group(2) else None,
            "bid_value": _money(bid.group(1)) if bid else None,
            "submitted": subd.group(1) if subd else None,
            "fy_from": int(years.group(1)) if years else None,
            "fy_to": int(years.group(2)) if years else None,
        })
    return out


# -------------------------------------------------------------- ISO certificates

_AUDIT = re.compile(
    r"^((?:Initial Certification|Surveillance Audit \d|Re-certification))\n"
    r"(\d{4}-\d{2}-\d{2})\n(.+?)\n(.+?)$", re.M)


def iso_certs():
    out = []
    for doc in _docs("DOC-CERT-"):
        t = _text(doc)
        no = re.search(r"Certificate No\s*:?\s*(\S+)", t, re.I)
        # Three of the five are ISO standards; the other two certify against a
        # registration scheme ("CPWD Class I Registration"). The standard is
        # whatever follows "conform to the requirements of", whatever it is.
        std = (re.search(r"conform to the requirements of\s+(.+?)\s+SCOPE OF REGISTRATION",
                         _flat(t), re.I)
               or re.search(r"\b(ISO\s*\d{4,5}(?::\d{4})?)", t))
        initial = re.search(r"Initial Certification Date\s*\n\s*(\d{4}-\d{2}-\d{2})", t, re.I)
        until = re.search(r"Valid Until\s*\n\s*(\d{4}-\d{2}-\d{2})", t, re.I)
        body = re.search(r"Certification Body\s*\n\s*(.+)", t, re.I)
        audits = []
        for m in _AUDIT.finditer(t):
            f = m.group(4)
            major = re.search(r"(\d+)\s*major", f, re.I)
            minor = re.search(r"(\d+)\s*minor", f, re.I)
            audits.append({"type": m.group(1), "date": m.group(2),
                           "auditor": m.group(3).strip(),
                           "major": int(major.group(1)) if major else None,
                           "minor": int(minor.group(1)) if minor else None,
                           # A future audit is on the schedule but has not
                           # happened; counting it as one carried out is wrong.
                           "status": ("scheduled"
                                      if re.search(r"scheduled|TBD", f, re.I)
                                      else "completed")})
        span = None
        if initial and until:
            span = (normalize.parse_date(until.group(1))
                    - normalize.parse_date(initial.group(1))).days
        out.append({
            "doc": doc,
            "cert_no": no.group(1) if no else None,
            "standard": re.sub(r"\s+", " ", std.group(1)) if std else None,
            "body": body.group(1).strip() if body else None,
            "initial_date": initial.group(1) if initial else None,
            "valid_until": until.group(1) if until else None,
            "validity_days": span,
            "audits": audits,
            "major_ncs": sum(a["major"] or 0 for a in audits),
            "minor_ncs": sum(a["minor"] or 0 for a in audits),
            "audits_done": sum(1 for a in audits if a["status"] == "completed"),
        })
    return out


# ------------------------------------------------------------ tender dossiers

_UNIT = re.compile(r"^([A-Z][\w &.\-]+?)\n(enterprise|mega|sme|small|medium)\n(\d{1,4})$", re.M)


def dossiers():
    out = []
    for doc in _docs("DOC-DOSSIER-"):
        t = _text(doc)
        rfp = re.search(r"(RFP-\d+)", t)
        bid = re.search(r"Bid value:\s*(INR\s*[\d.,]+\s*(?:Cr|Crore|Lakh)s?)", t, re.I)
        sub = re.search(r"Submitted:\s*(.+)", t)
        emd = re.search(r"Earnest money of\s+(INR\s*[\d.,]*\s*(?:Cr|Crore|Lakh)?s?|INR\s*\d+)", t, re.I)
        rel = re.search(r"Past performance\s*[—-]\s*(\d+)\s*relevant works", t, re.I)
        units = [{"unit": m.group(1).strip(), "scale": m.group(2),
                  "headcount": int(m.group(3))} for m in _UNIT.finditer(t)]
        client = re.search(r"The Tender Inviting Authority,\s*\n\s*(.+)", t)
        # Anchored on the title that precedes it, because the heading itself is
        # letters and would otherwise be swept into the capture.
        work = re.search(r"[Dd]o[Ss][Ss]ier\s+([A-Za-z][A-Za-z &]{2,30}?)\s*Works?"
                         r"\s*[\u2014-]\s*Tender RFP-\d+", _flat(t))
        out.append({
            "doc": doc,
            "work": work.group(1).strip() if work else None,
            "rfp_ref": rfp.group(1) if rfp else None,
            "bid_value": _money(bid.group(1)) if bid else None,
            "submitted": sub.group(1).strip() if sub else None,
            "emd": _money(emd.group(1)) if emd else None,
            "relevant_works": int(rel.group(1)) if rel else None,
            "client": client.group(1).strip() if client else None,
            "units": units,
            "headcount": sum(u["headcount"] for u in units) or None,
        })
    return out


# ------------------------------------------------------ financial statements

# Every P&L and balance-sheet line, as printed. Stated in LAKHS; stored in
# rupees, so nothing downstream has to remember the unit.
_FS_LINE = re.compile(r"^([A-Z][^\n]{3,70}?)\n(-?[\d,]+)\n(-?[\d,]+)$", re.M)
_FS_ONE = re.compile(r"^(Profit Before Tax|Tax Expense \(current \+ deferred\)|Profit After Tax)\n(-?[\d,]+)$", re.M)
_LAKH = 10 ** 5


def financials():
    out = []
    for doc in _docs("DOC-FS-"):
        t = _text(doc)
        # "Total Revenue from Operations\n(A)" is one label over two lines in
        # three of the seven years. Left split, the row loses both its figures
        # and the statement stops adding up.
        t = re.sub(r"\n\((A|B)\)\n", r" (\1)\n", t)
        fy = re.search(r"FY(\d{4})-\d{2}", t)
        lines = {}
        for m in _FS_LINE.finditer(t):
            key = " ".join(m.group(1).split()).rstrip(":")
            if key.lower().startswith("particulars"):
                continue
            lines.setdefault(key, {"current": _num(m.group(2)) * _LAKH,
                                   "previous": _num(m.group(3)) * _LAKH})
        for m in _FS_ONE.finditer(t):
            lines.setdefault(" ".join(m.group(1).split()),
                             {"current": _num(m.group(2)) * _LAKH, "previous": None})
        out.append({"doc": doc,
                    "year": int(fy.group(1)) if fy else _num(doc.split("-")[-1]),
                    "lines": lines})
    return out


# ------------------------------------------------------------------ RA bills

_BOQ_ROW = re.compile(r"^(\d{1,2})\n(.+?)\n(cum|MT|rmt|sqm|nos|LS|km|kg|t)\n"
                      r"([\d,]+)\n([\d,.]+)\n([\d,]+)$", re.M)
_RA_ROW = re.compile(r"^(\d{1,2})\n(AR-\d{4}-\d+)\n(\d{4}-\d{2}-\d{2})\n([\d,]+)\n([\d,]+)$", re.M)


def ra_bills():
    out = []
    for doc in _docs("DOC-RABILL-"):
        t = _text(doc)
        no = re.search(r"Bill No:\s*(\S+)", t)
        ra = re.search(r"Running Account Bill\s*[—-]\s*RA\s*(\d+)", t, re.I)
        con = re.search(r"Contract #(\d+)\s*·\s*(.+)", t)
        date = re.search(r"^Date:\s*(.+)$", t, re.M)
        items = [{"item": int(m.group(1)), "description": " ".join(m.group(2).split()),
                  "unit": m.group(3), "rate": _num(m.group(4)),
                  "quantity": float(m.group(5).replace(",", "")),
                  "amount": _num(m.group(6))} for m in _BOQ_ROW.finditer(t)]
        val = _num(_after(t, "Value of work done — this bill", r"([\d,]+)"))
        gst_m = re.search(r"Add: GST @([\d.]+)%\s*\n\s*([\d,]+)", t, re.I)
        # The retention rate is stated per bill and is not always 5% -- two of
        # the six carry 0.0%. Reading the rate off the bill rather than
        # assuming it is what makes the identity check meaningful.
        ret_m = re.search(r"Less: Retention @([\d.]+)%\s*\n\s*\(?([\d,]+)\)?", t, re.I)
        gst = _num(gst_m.group(2)) if gst_m else None
        ret = _num(ret_m.group(2)) if ret_m else None
        net = _num(_after(t, "Net claimed (before client TDS)", r"([\d,]+)"))
        cum = re.search(r"Cumulative up to & incl\. RA \d+\n([\d,]+)", t)
        d = normalize.parse_date(date.group(1)) if date else None
        out.append({
            "doc": doc, "bill_no": no.group(1) if no else None,
            "ra": int(ra.group(1)) if ra else None,
            "contract": int(con.group(1)) if con else None,
            "client": con.group(2).strip() if con else None,
            "date": d.isoformat() if d else None,
            "year": d.year if d else None,
            "items": items,
            "value_of_work": val, "gst": gst, "retention": ret,
            "gst_pct": float(gst_m.group(1)) if gst_m else None,
            "retention_pct": float(ret_m.group(1)) if ret_m else None,
            "net_claimed": net,
            "cumulative": _num(cum.group(1)) if cum else None,
        })
    return out


def final_bills():
    out = []
    for doc in _docs("DOC-FINBILL-"):
        t = _text(doc)
        con = re.search(r"Contract #(\d+)\s*·\s*(.+?)\s*·\s*(\d+)\s*RA bills", t)
        awarded = _after(t, "Awarded Value", r"(INR\s*[\d.,]+\s*(?:Cr|Crore|Lakh)s?)")
        billed = _after(t, "Total Value of Work Billed",
                        r"(INR\s*[\d.,]+\s*(?:Cr|Crore|Lakh)s?)")
        revised = _after(t, "Revised Value", r"(INR\s*[\d.,]+\s*(?:Cr|Crore|Lakh)s?)")
        variations = _after(t, "Approved Variations",
                            r"(INR\s*[\d.,]+\s*(?:Cr|Crore|Lakh)s?)")
        period = _after(t, "Period", r"(.+)")
        items = [{"item": int(m.group(1)), "description": " ".join(m.group(2).split()),
                  "unit": m.group(3), "rate": _num(m.group(4)),
                  "quantity": float(m.group(5).replace(",", "")),
                  "amount": _num(m.group(6))} for m in _BOQ_ROW.finditer(t)]
        # "Total" on the line after the last BOQ row is the executed total, and
        # is the figure an awarded-versus-billed question is asking about --
        # the Part I headline is rounded to two decimals of a crore.
        total = re.search(r"\nTotal\n([\d,]+)\n", t)
        bills = [{"ra": int(m.group(1)), "bill_no": m.group(2), "date": m.group(3),
                  "value": _num(m.group(4)), "cumulative": _num(m.group(5))}
                 for m in _RA_ROW.finditer(t)]
        aw = _money(awarded)
        ex = _num(total.group(1)) if total else (sum(i["amount"] for i in items) or None)
        rv = _money(revised)
        out.append({
            "doc": doc,
            "contract": int(con.group(1)) if con else None,
            "client": con.group(2).strip() if con else None,
            "ra_count": int(con.group(3)) if con else None,
            "awarded": aw, "billed_headline": _money(billed),
            "revised": rv, "variations": _money(variations),
            "executed": ex,
            "gap": (aw - ex) if (aw is not None and ex is not None) else None,
            "revised_gap": (rv - ex) if (rv is not None and ex is not None) else None,
            "period": period, "items": items, "bills": bills,
        })
    return out


# ------------------------------------------------- bank statements and ledgers

_BANK_ROW = re.compile(r"^(\d{4}-\d{2}-\d{2})\n(.+?)\n([\d,]+)\n([\d,]+)$", re.M)
_BANK_TWO = re.compile(r"^(\d{4}-\d{2}-\d{2})\n(.+?)\n([\d,]+)\n([\d,]+)\n([\d,]+)$", re.M)


def bank_statements():
    out = []
    for doc in _docs("DOC-BANK-"):
        t = _text(doc)
        fy = re.search(r"FY\s*(\d{4})", t)
        rows = []
        for m in _BANK_TWO.finditer(t):
            rows.append({"date": m.group(1), "particulars": " ".join(m.group(2).split()),
                         "withdrawal": _num(m.group(3)), "deposit": _num(m.group(4)),
                         "balance": _num(m.group(5))})
        seen = {r["date"] + r["particulars"] for r in rows}
        for m in _BANK_ROW.finditer(t):
            key = m.group(1) + " ".join(m.group(2).split())
            if key in seen:
                continue
            # Two columns only: an amount and the running balance. Which column
            # the amount belongs to is settled by whether the balance rose.
            amt, bal = _num(m.group(3)), _num(m.group(4))
            prev = rows[-1]["balance"] if rows else 0
            rose = bal is not None and prev is not None and bal > prev
            rows.append({"date": m.group(1), "particulars": " ".join(m.group(2).split()),
                         "withdrawal": None if rose else amt,
                         "deposit": amt if rose else None, "balance": bal})
        rows.sort(key=lambda r: r["date"])
        out.append({"doc": doc, "year": int(fy.group(1)) if fy else None,
                    "rows": rows,
                    "deposits": sum(r["deposit"] or 0 for r in rows),
                    "withdrawals": sum(r["withdrawal"] or 0 for r in rows),
                    "closing": rows[-1]["balance"] if rows else None})
    return out


_GL_ACCOUNT = re.compile(r"^ACCOUNT (\d+)\s*[—-]\s*(.+?)$", re.M)
_GL_ROW = re.compile(r"^(\d{4}-\d{2}-\d{2})\n(.+?)\n([\d,]+)\n([\d,]+)\n(Dr|Cr)$", re.M | re.S)


def ledgers():
    out = []
    for doc in _docs("DOC-GLB-"):
        t = _text(doc)
        fy = re.search(r"FY\s*(\d{4})", t)
        blocks = list(_GL_ACCOUNT.finditer(t))
        accounts = []
        for i, m in enumerate(blocks):
            end = blocks[i + 1].start() if i + 1 < len(blocks) else len(t)
            seg = t[m.start():end]
            rows = [{"date": r.group(1), "narration": " ".join(r.group(2).split()),
                     "amount": _num(r.group(3)), "balance": _num(r.group(4)),
                     "side": r.group(5)} for r in _GL_ROW.finditer(seg)]
            accounts.append({"code": int(m.group(1)),
                             "account": " ".join(m.group(2).split()),
                             "rows": rows,
                             "closing": rows[-1]["balance"] if rows else None,
                             "total": sum(r["amount"] or 0 for r in rows)})
        out.append({"doc": doc, "year": int(fy.group(1)) if fy else None,
                    "accounts": accounts})
    return out


# ------------------------------------------------------------ annual reports

_DIRECTOR = re.compile(r"^([A-Z][a-z]+ [A-Z][a-z]+)\n([A-Z][\w ]+)\n(\d{1,2}/\d)$", re.M)
_HIGHLIGHT = re.compile(r"^([A-Z][\w &'-]{5,45})\n(Rs\.?\s*[-\d,.]+(?:\s*Lakh)?)\n"
                        r"(Rs\.?\s*[-\d,.]+(?:\s*Lakh)?)$", re.M)


def annual_reports():
    out = []
    for doc in _docs("DOC-AR-"):
        t = _text(doc)
        fy = re.search(r"FY\s*(\d{4})", t)
        directors = [{"name": m.group(1), "designation": m.group(2).strip()}
                     for m in _DIRECTOR.finditer(t)]
        highlights = {}
        for m in _HIGHLIGHT.finditer(t):
            highlights[" ".join(m.group(1).split())] = {
                "current": _money(m.group(2)), "previous": _money(m.group(3))}
        out.append({"doc": doc, "year": int(fy.group(1)) if fy else None,
                    "directors": directors, "director_count": len(directors),
                    "highlights": highlights})
    return out


# ------------------------------------------------ company completion certificates

# The client's certificate records the work; the CONTRACTOR's copy records what
# happens after it -- the defect liability period, in days and as an expiry
# date. Nothing else in the corpus carries either.
_DLP = re.compile(r"defect liability period of (\d+) days from the date of completion"
                  r"(?:\s*\(i\.e\.,? until (\d{4}-\d{2}-\d{2})\))?", re.I)


def company_certs():
    out = []
    for doc in _docs("DOC-CCC-"):
        f = _flat(_text(doc))
        work = re.search(r"Project Name\s+(.+?)\s+Client\s", f)
        client = re.search(r"\sClient\s+(.+?)\s*\((?:Government|Private|PSU)\)", f)
        val = re.search(r"Contract Value\s+((?:INR|Rs\.?)\s*[\d.,]+\s*(?:Cr|Crore|Lakh)s?)", f, re.I)
        comp = re.search(r"Completion Date\s+(\d{4}-\d{2}-\d{2})", f)
        pm = re.search(r"Project Manager\s+(.+?)\s+\d\.", f)
        cat = re.search(r"Work Category\s+(.+?)\s+Contract Value", f)
        d = _DLP.search(f)
        dlp_days = int(d.group(1)) if d else None
        dlp_until = d.group(2) if (d and d.group(2)) else None
        # Second template ("RECORD OF WORK COMPLETED"): a flat label/value list
        # that states the defect liability END DATE rather than a duration. Half
        # the 155 use it, and the duration is the difference of two dates it
        # already prints.
        if work is None:
            work = re.search(r"\sWork\s+(.+?)\s+Client\s", f)
            client = re.search(r"\sClient\s+(.+?)\s*\((?:government|private|psu)\)", f, re.I)
            cat = re.search(r"\sCategory\s+(.+?)\s+Executed Value", f)
            val = re.search(r"Executed Value\s+((?:INR|Rs\.?)\s*[\d.,]+\s*(?:Cr|Crore|Lakh)s?)", f, re.I)
            comp = re.search(r"\sCompletion\s+(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", f)
            pm = re.search(r"Project Lead\s+(.+?)\s+Defect Liability", f)
            ends = re.search(r"Defect Liability Ends\s+(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", f)
            dc = normalize.parse_date(comp.group(1)) if comp else None
            de = normalize.parse_date(ends.group(1)) if ends else None
            if de:
                dlp_until = de.isoformat()
            if dc and de:
                dlp_days = (de - dc).days
            if dc:
                comp = type("M", (), {"group": staticmethod(lambda i, v=dc.isoformat(): v)})
        out.append({
            "doc": doc,
            "work": work.group(1).strip() if work else None,
            "client": client.group(1).strip() if client else None,
            "category": cat.group(1).strip() if cat else None,
            "value": _money(val.group(1)) if val else None,
            "completed": comp.group(1) if comp else None,
            "manager": pm.group(1).strip() if pm else None,
            "defect_liability_days": dlp_days,
            "defect_liability_until": dlp_until,
        })
    return out


# ------------------------------------------------------------------------ CVs

_CV_FIELDS = ["Name", "Employee ID", "Designation", "Business Unit",
              "Total Experience", "Qualification", "Date of Joining", "Wage Group"]


def cvs():
    """The 39 key-personnel CVs. Nothing else states a joining date or a
    qualification, and both are asked about directly."""
    out = []
    for doc in _docs("DOC-CV-"):
        t = _text(doc)
        rec = {"doc": doc}
        for lab in _CV_FIELDS:
            v = _after(t, lab, r"(.+)")
            key = lab.lower().replace(" ", "_")
            rec[key] = v.strip() if v else None
        exp = re.search(r"(\d+)\s*years?", rec.get("total_experience") or "")
        rec["experience_years"] = int(exp.group(1)) if exp else None
        doj = normalize.parse_date(rec.get("date_of_joining") or "")
        rec["joined"] = doj.isoformat() if doj else None
        # Tenure to the corpus's own "as at" date, which every document uses.
        rec["tenure_days"] = ((normalize.parse_date("2026-03-31") - doj).days
                              if doj else None)
        out.append(rec)
    return out


# ------------------------------------------------------------ reference letters

def reference_letters():
    """The 132 client reference letters.

    Each states the work, its contract value as the CLIENT records it, and the
    completion date. 40 of them state a validity of the literal word `High` or
    `Medium` -- a leaked category label where a duration was intended -- which
    is worth recording as what it is rather than discarding.
    """
    out = []
    for doc in _docs("DOC-REF-"):
        f = _flat(_text(doc))
        ref = re.search(r"Our ref:\s*(\S+)", f)
        work = re.search("work\\s*[\u201c\"']([^\u201d\"']+)[\u201d\"']", f)
        val = re.search(r"\(((?:INR|Rs\.?)\s*[\d.,]+\s*(?:Cr|Crore|Lakh)s?)\)", f, re.I)
        comp = re.search(r"completed on ([\d]{1,2} \w{3} \d{4}|\d{4}-\d{2}-\d{2})", f, re.I)
        valid = re.search(r"valid for a period of\s+(\w+)", f, re.I)
        # Second template ("To whomsoever it may concern"): the work, value and
        # completion date are a label/value block rather than a sentence.
        if work is None:
            work = re.search(r"Work Executed\s+(.+?)\s+Value\s", f)
        if val is None:
            val = re.search(r"\sValue\s+((?:INR|Rs\.?)\s*[\d.,]+\s*(?:Cr|Crore|Lakh)s?)", f, re.I)
        if comp is None:
            comp = re.search(r"\sCompleted\s+(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", f)
        client = _text(doc).strip().split("\n")[0].strip()
        letter_date = re.search(r"(\d{1,2} \w{3} \d{4})", f)
        d = normalize.parse_date(comp.group(1)) if comp else None
        out.append({
            "doc": doc,
            "our_ref": ref.group(1) if ref else None,
            "client": client or None,
            "work": work.group(1).strip() if work else None,
            "value": _money(val.group(1)) if val else None,
            "completed": d.isoformat() if d else None,
            "year": d.year if d else None,
            "validity": valid.group(1) if valid else None,
            "letter_date": letter_date.group(1) if letter_date else None,
        })
    return out


# ------------------------------------------- annual report tables (beyond the head)

_SEG = re.compile(r"^([A-Z][A-Za-z &]{2,32})\n(-?[\d,]+)\n(-?[\d,]+)$", re.M)
_SEVEN = re.compile(r"^(\d{4})[\u2013-]\d{2}\n(-?[\d,]+)\n(-?[\d,]+)\n(-?[\d,]+)\n(-?[\d.]+)%$", re.M)
_AGE = re.compile(r"^([A-Z][A-Za-z ,&.'-]{5,60})\n(-?[\d,]+)\n(-?[\d,]+)\n(-?[\d,]+)\n(-?[\d,]+)$", re.M)
_CLI = re.compile(r"^([A-Z][A-Za-z ,&.'-]{5,60})\n(-?[\d,]+)$", re.M)


def _section(t, start, end=None):
    i = t.find(start)
    if i < 0:
        return ""
    j = t.find(end, i + len(start)) if end else -1
    return t[i:j if j > 0 else i + 12000]


def annual_tables():
    """Segment revenue, the seven-year summary, the ageing annexure and the
    principal-clients table. All four are tables the head of the report only
    summarises, and all four are asked about directly."""
    out = []
    for doc in _docs("DOC-AR-"):
        t = _text(doc)
        fy = re.search(r"FY\s*(\d{4})", t)
        f = _flat(t)
        seg_txt = _section(t, "SEGMENT REVENUE", "PRINCIPAL CLIENTS")
        segments = [{"segment": m.group(1).strip(), "current": _num(m.group(2)),
                     "previous": _num(m.group(3))} for m in _SEG.finditer(seg_txt)
                    if m.group(1).strip().lower() not in ("segment", "client")]
        seven = [{"year": int(m.group(1)), "gross_billings": _num(m.group(2)),
                  "net_revenue": _num(m.group(3)), "profit": _num(m.group(4)),
                  "margin": float(m.group(5))}
                 for m in _SEVEN.finditer(_section(t, "SEVEN-YEAR FINANCIAL SUMMARY",
                                                   "ANNEXURE"))]
        ageing = [{"client": m.group(1).strip(), "lt6": _num(m.group(2)),
                   "m6_12": _num(m.group(3)), "gt12": _num(m.group(4)),
                   "total": _num(m.group(5))}
                  for m in _AGE.finditer(_section(t, "TRADE RECEIVABLES AGEING"))]
        cli_txt = _section(t, "PRINCIPAL CLIENTS", "Order inflow")
        clients = [{"client": m.group(1).strip(), "billings": _num(m.group(2))}
                   for m in _CLI.finditer(cli_txt)
                   if m.group(1).strip().lower() not in ("client", "billings gross")]
        contracts = re.search(r"(\d+) contracts remained in execution", f)
        awarded = re.search(r"aggregate awarded value of (Rs\.?\s*[\d,.]+\s*Lakh)", f, re.I)
        variations = re.search(r"approved variations of (Rs\.?\s*[\d,.]+\s*Lakh)"
                               r"\s*across (\d+) variation orders", f, re.I)
        credits = re.search(r"(\d+) credit notes\s*aggregating\s*(Rs\.?\s*[\d,.]+\s*Lakh)", f, re.I)
        out.append({
            "doc": doc, "year": int(fy.group(1)) if fy else None,
            "segments": segments, "seven_year": seven,
            "ageing": ageing, "principal_clients": clients,
            "contracts_in_execution": int(contracts.group(1)) if contracts else None,
            "order_book_awarded": _money(awarded.group(1)) if awarded else None,
            "variation_orders": int(variations.group(2)) if variations else None,
            "variations_value": _money(variations.group(1)) if variations else None,
            "credit_notes": int(credits.group(1)) if credits else None,
            "credit_notes_value": _money(credits.group(2)) if credits else None,
        })
    return out


# --------------------------------------------------- dossier financial standing

_STANDING = re.compile(r"^(\d{4})[\u2013-]\d{2}\n"
                       r"((?:INR|Rs\.?)\s*[-\d.,]+(?:\s*(?:Cr|Crore|Lakh)s?)?)\n"
                       r"((?:INR|Rs\.?)\s*[-\d.,]+(?:\s*(?:Cr|Crore|Lakh)s?)?)\n"
                       r"((?:INR|Rs\.?)\s*[-\d.,]+(?:\s*(?:Cr|Crore|Lakh)s?)?)$", re.M)


def dossier_standing():
    """Annexure C of each dossier: gross billings, net turnover and net profit
    per financial year. Stated in a mix of crore and raw rupees within the same
    column, so each cell is read on its own terms."""
    out = []
    for doc in _docs("DOC-DOSSIER-"):
        t = _text(doc)
        rfp = re.search(r"(RFP-\d+)", t)
        for m in _STANDING.finditer(t):
            out.append({"doc": doc, "rfp_ref": rfp.group(1) if rfp else None,
                        "year": int(m.group(1)),
                        "gross_billings": _money(m.group(2)),
                        "net_turnover": _money(m.group(3)),
                        "net_profit": _money(m.group(4))})
    return out


# ------------------------------------------------------------------- driver

def build(verbose=True):
    est = {
        "bonds": bonds(),
        "compliance": compliance(),
        "iso_certs": iso_certs(),
        "dossiers": dossiers(),
        "financials": financials(),
        "ra_bills": ra_bills(),
        "final_bills": final_bills(),
        "bank": bank_statements(),
        "ledgers": ledgers(),
        "annual_reports": annual_reports(),
        "company_certs": company_certs(),
        "cvs": cvs(),
        "reference_letters": reference_letters(),
        "annual_tables": annual_tables(),
        "dossier_standing": dossier_standing(),
    }
    corpus.WORK.mkdir(parents=True, exist_ok=True)
    (corpus.WORK / "estate.json").write_text(
        json.dumps(est, indent=1, ensure_ascii=False), encoding="utf-8")
    if verbose:
        for k, v in est.items():
            print(f"[estate] {k:16s} {len(v):3d}")
        b = [x for x in est["bonds"] if x["amount"]]
        print(f"[estate] bonds: {len(b)} with an amount, "
              f"total guaranteed INR {sum(x['amount'] for x in b)/10**7:,.2f} Cr")
        print(f"[estate] -> work/estate.json")
    return est


if __name__ == "__main__":
    build()
