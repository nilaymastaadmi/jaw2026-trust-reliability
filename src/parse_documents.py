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
        # "for the work of X Works, and" is the long template's clause and it
        # sits AFTER the Subject line, so a single alternation matched the
        # subject first and left the work empty on all 28 bonds that carry an
        # amount. Tried in order of specificity instead.
        work = (re.search(r"for the work of\s+([A-Za-z &]+?)\s*Works?\s*,", f)
                or re.search(r"Performance Bond\s*[\u2014-]\s*([A-Za-z &]+?)"
                             r"\s*Works?\s*\(", f)
                or re.search(r"Subject:[^\u2014-]*[\u2014-]\s*([A-Za-z &]+?)"
                             r"(?:\s*Works?)?\s*(?:,|\(|Tender)", f))
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
# number and a heading.
#
# Counting the standalone STATUS tokens looks safe and is not: the evidence
# column also contains them. "Registration No." wraps and leaves a bare "N/A"
# on its own line in every long-format matrix, which made 17 requirements into
# 18 and invented a requirement not met in all 19 of them.
#
# Both templates number their rows, so the serial is the anchor. A row opens on
# a line that is exactly the next expected serial -- which no stray figure in
# the evidence column can be, since 210 and 486 do not follow 8 -- and takes
# the FIRST status token after it.
_STATUS = re.compile(r"^(Complied|Not Complied|Partially Complied|Not complied"
                     r"|MET|NOT MET|Not Met|N/A|Pending)$", re.M)
_MET = {"complied", "met"}


def _requirement_rows(text):
    rows, n, status = [], 1, None
    for line in text.split("\n"):
        line = line.strip()
        if line == str(n):
            if rows:
                rows[-1]["status"] = status
            rows.append({"n": n, "status": None})
            n, status = n + 1, None
        elif status is None and _STATUS.fullmatch(line):
            status = line
    if rows:
        rows[-1]["status"] = status
    return [r for r in rows if r["status"]]


def compliance():
    out = []
    for doc in _docs("DOC-CM-"):
        t = _text(doc)
        tender = re.search(r"(RFP-\d+)", t)
        f = _flat(t)
        work = re.search(r"Tender (?:Ref: )?RFP-\d+\s*(?:·|\u00b7)?\s*([A-Za-z][A-Za-z &]{3,40}?)"
                         r"\s*(?:CM/|Bid Value|\d)", f)
        reqs = _requirement_rows(t)
        if not reqs:                    # a layout with no serials: fall back
            reqs = [{"n": i + 1, "status": m.group(1)}
                    for i, m in enumerate(_STATUS.finditer(t))]
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


class _EmptyMatch:
    """Stands in for a regex that did not match, so a count can be zero."""

    @staticmethod
    def group(_):
        return ""


_EMPTY = _EmptyMatch()


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
        # Annexure H states the instrument actually lodged. The covering
        # letter's "Earnest money of INR 0 has been furnished" is a separate
        # figure and it is zero on all six, so a question about the bid
        # security read off the letter got nothing.
        sec = re.search(r"Annexure H\s*[\u2014-][^\n]*\n"
                        r"Instrument\s*\nIssuer\s*\nAmount\s*\nValid To\s*\n"
                        r"(.+?)\n(.+?)\n(" + _AMOUNT + r")\s*\n(.+?)$",
                        t, re.I | re.M)
        # Annexure B: the registrations table, then one block per certificate
        # whose true copy is annexed.
        annexb = re.search(r"Annexure b\s*[\u2014-][^\n]*\n(.*?)(?=CerTifiCATe Copy)",
                           t, re.S | re.I)
        regs = (len(re.findall(r"^\w[^\n]*\n[^\n]*\n(?:active|inactive|expired)\s*$",
                               annexb.group(1), re.M | re.I)) if annexb else None)
        out.append({
            "doc": doc,
            "work": work.group(1).strip() if work else None,
            "rfp_ref": rfp.group(1) if rfp else None,
            # The same column the bonds and the compliance matrices call
            # tender_ref. One name for one fact, so a filter written against
            # either table reaches this one too.
            "tender_ref": rfp.group(1) if rfp else None,
            "bid_value": _money(bid.group(1)) if bid else None,
            "submitted": sub.group(1).strip() if sub else None,
            "emd": _money(emd.group(1)) if emd else None,
            "bid_security": _money(sec.group(3)) if sec else None,
            "bid_security_bank": sec.group(2).strip() if sec else None,
            "bid_security_valid_to": sec.group(4).strip() if sec else None,
            "relevant_works": int(rel.group(1)) if rel else None,
            "registrations": regs,
            "cert_copies": len(re.findall(r"CerTifiCATe Copy", t, re.I)) or None,
            # The front page lists them as a two-column table, so the letters
            # arrive one per line under an "Annexure / Contents" header.
            "annexures": len(re.findall(r"^[A-H]$", (
                re.search(r"^Annexure\s*\nContents\s*\n(.*?)\n(?:DOC-|Page )",
                          t, re.S | re.M) or _EMPTY).group(1), re.M)) or None,
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
_FS_SECTION = re.compile(
    r"^(EQUITY AND LIABILITIES|ASSETS|[A-D]\. [A-Z][A-Za-z ()&+-]+)$", re.M)
_FS_SECTIONS = {
    "EQUITY AND LIABILITIES": "Equity and Liabilities",
    "ASSETS": "Assets",
    "A. REVENUE FROM OPERATIONS": "Revenue from Operations",
    "B. EXPENSES": "Expenses",
    "C. PROFIT BEFORE TAX (A - B)": "Profit",
    "D. BALANCE SHEET EXTRACT": "Balance Sheet",
}


def financials():
    out = []
    for doc in _docs("DOC-FS-"):
        t = _text(doc)
        # "Total Revenue from Operations\n(A)" is one label over two lines in
        # three of the seven years. Left split, the row loses both its figures
        # and the statement stops adding up.
        t = re.sub(r"\n\((A|B)\)\n", r" (\1)\n", t)
        fy = re.search(r"FY(\d{4})-\d{2}", t)
        # Which SECTION each line sits under. The statement is a profit and
        # loss followed by a balance-sheet extract, and "summing every Equity
        # and Liabilities line" needs to know where one ends and the next
        # begins -- a fact the line labels do not carry ("Reserves & Surplus"
        # names no section at all).
        heads = [(m.start(), m.group(1)) for m in _FS_SECTION.finditer(t)]

        def _section_at(pos):
            name = None
            for at, h in heads:
                if at > pos:
                    break
                name = _FS_SECTIONS.get(h.strip().rstrip(".").upper(), h.strip())
            return name

        lines = {}
        for m in _FS_LINE.finditer(t):
            key = " ".join(m.group(1).split()).rstrip(":")
            if key.lower().startswith("particulars"):
                continue
            lines.setdefault(key, {"current": _num(m.group(2)) * _LAKH,
                                   "previous": _num(m.group(3)) * _LAKH,
                                   "section": _section_at(m.start())})
        for m in _FS_ONE.finditer(t):
            lines.setdefault(" ".join(m.group(1).split()),
                             {"current": _num(m.group(2)) * _LAKH, "previous": None,
                              "section": _section_at(m.start())})
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
        _pm = re.search(r"(.+?)\s*[\u2014\u2013-]\s*(.+)", period or "")
        _p_from = normalize.parse_date(_pm.group(1)) if _pm else None
        _p_to = normalize.parse_date(_pm.group(2)) if _pm else None
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
            "period": period,
            # The billing period the final bill STATES, which runs from the
            # first RA bill to the final bill itself -- not to the last RA
            # bill, which is a month or two earlier. Derived from the RA
            # register it would be wrong by that much.
            "period_from": _p_from.isoformat() if _p_from else None,
            "period_to": _p_to.isoformat() if _p_to else None,
            "period_days": (_p_to - _p_from).days if (_p_from and _p_to) else None,
            "items": items, "bills": bills,
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
        # The opening balance is a one-figure row, so the two-figure pattern
        # drops it -- and without it the FIRST transaction has nothing to
        # compare against and is read as a deposit whichever way it went.
        # 51,167,788 taking the balance from 465,282,353 to 414,114,565 is a
        # payment out, and calling it a deposit put the year's net movement out
        # by twice the transaction.
        ob = re.search(r"Opening balance b/f\s*\n\s*([\d,]+)", t)
        opening = _num(ob.group(1)) if ob else 0
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
            prev = rows[-1]["balance"] if rows else opening
            rose = bal is not None and prev is not None and bal > prev
            rows.append({"date": m.group(1), "particulars": " ".join(m.group(2).split()),
                         "withdrawal": None if rose else amt,
                         "deposit": amt if rose else None, "balance": bal})
        rows.sort(key=lambda r: r["date"])
        out.append({"doc": doc, "year": int(fy.group(1)) if fy else None,
                    "rows": rows, "opening": opening,
                    "deposits": sum(r["deposit"] or 0 for r in rows),
                    "withdrawals": sum(r["withdrawal"] or 0 for r in rows),
                    "net_movement": ((rows[-1]["balance"] - opening)
                                     if rows else None),
                    "closing": rows[-1]["balance"] if rows else None})
    return out


_GL_ACCOUNT = re.compile(r"^ACCOUNT (\d+)\s*[—-]\s*(.+?)$", re.M)
# Two layouts. The asset accounts put the side on its own line; the liability
# accounts attach it to the balance ("6,577,630 Cr"). Knowing only the first
# parsed every liability account as empty -- no rows, no closing balance, and
# a question about accounts payable had nothing to read.
_GL_ROW = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\n(.+?)\n([\d,]+)\n([\d,]+)(?:[ \t]+(Dr|Cr)$|\n(Dr|Cr)$)",
    re.M | re.S)


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
                     "side": r.group(5) or r.group(6)} for r in _GL_ROW.finditer(seg)]
            last = rows[-1] if rows else None
            # A balance is a magnitude plus a side. Asked for as a SIGNED
            # number, a credit closing is negative -- and the question says so
            # when it wants that.
            signed = None
            if last and last["balance"] is not None:
                signed = (-last["balance"] if last.get("side") == "Cr"
                          else last["balance"])
            # "BANK (ASSET)" is a NAME and a classification, and the ledger
            # prints them as one string. Held together, a question naming "the
            # ledger's Bank account" matched nothing, because the store's value
            # carried a word the question had no reason to say.
            full = " ".join(m.group(2).split())
            kind = re.search(r"\((ASSET|LIABILITY|INCOME|EXPENSE|EQUITY|REVENUE)\)\s*$",
                             full, re.I)
            accounts.append({"code": int(m.group(1)),
                             "account": (full[:kind.start()].strip()
                                         if kind else full),
                             "account_type": (kind.group(1).title()
                                              if kind else None),
                             "rows": rows,
                             "closing": last["balance"] if last else None,
                             "side": last.get("side") if last else None,
                             "closing_signed": signed,
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
        # The SECTOR the client belongs to, which every one of the 155
        # contractor certificates states in brackets after the name and which
        # normalize.norm_client strips as noise -- correctly, for grouping, but
        # it is the only place the corpus records the fact. "How many of the
        # 155 completed works were delivered for a client tagged as a
        # central/state government entity, as opposed to PSU or private" needs
        # exactly this: 79 government, 47 PSU, 29 private.
        sector = re.search(r"\sClient\s+.+?\((government|private|psu)\)", f, re.I)
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
            "client_type": sector.group(1).lower() if sector else None,
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

# The four ways this corpus writes money, in one place. Three of the reference
# letter templates state the value differently, and each pattern used to carry
# its own idea of what a rupee amount looks like: the two that omitted the bare
# Indian-grouped form -- "INR 12,94,00,000/-" -- lost the value on 19 letters.
_AMOUNT = (r"(?:INR|Rs\.?|\u20b9)\s*[\d.,]+\s*(?:Cr|Crores?|Lakhs?|Lacs?)"
           r"|(?:INR|Rs\.?|\u20b9)\s*[\d,]{7,}")

# The client's name heads the letter, and on three of the 132 it wraps onto a
# second line -- "Irrigation & Waterways Dept, Govt of West" / "Bengal". Reading
# only the first line truncated the name, and a truncated name matches nothing.
_REF_HEAD_END = re.compile(r"\u00b7|^\s*(?:Letter of Recommendation|LETTER OF"
                           r"|Ref:|Our ref:|Date:|To whomsoever)", re.I)


def _ref_client(text):
    parts = []
    for line in text.strip().split("\n")[:3]:
        line = line.strip()
        if not line or _REF_HEAD_END.search(line):
            break
        parts.append(line)
    return " ".join(parts) or None


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
        val = re.search(r"\((" + _AMOUNT + r")\s*(?:/-)?\s*\)", f, re.I)
        comp = re.search(r"completed on ([\d]{1,2} \w{3} \d{4}|\d{4}-\d{2}-\d{2})", f, re.I)
        valid = re.search(r"valid for a period of\s+(\w+)", f, re.I)
        # Second template ("To whomsoever it may concern"): the work, value and
        # completion date are a label/value block rather than a sentence.
        if work is None:
            work = re.search(r"Work Executed\s+(.+?)\s+Value\s", f)
        if val is None:
            val = re.search(r"\sValue\s+(" + _AMOUNT + r")", f, re.I)
        if comp is None:
            comp = re.search(r"\sCompleted\s+(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", f)
        # Third template ("1. Project Details"), a labelled block that also
        # carries the category and the contractor's role -- two facts the other
        # two templates do not state at all.
        if work is None:
            work = re.search(r"Project Name\s+(.+?)\s+Scope of Work", f)
        if val is None:
            # Indian digit grouping with no unit word -- "INR 11,32,00,000/-" --
            # is the fourth way this corpus writes money, and the only one the
            # unit-suffixed pattern cannot see.
            val = re.search(r"Contract Value\s+(" + _AMOUNT + r")", f, re.I)
        if comp is None:
            comp = re.search(r"Date of Completion\s+(\d{4}-\d{2}-\d{2}"
                             r"|\d{2}/\d{2}/\d{4})", f)
        # The person who will confirm the letter, named three ways. In the two
        # label templates the name sits in the verification line; in the third
        # it is the signature block, which is the last name-then-designation
        # pair on the page.
        contact = (re.search(r"(?:Contact for Verification|Verification):?\s*"
                             r"([A-Z][A-Za-z.]+(?: [A-Z][A-Za-z.]+){1,2})\s*(?:\u00b7|,)", f)
                   or re.search(r"^([A-Z][A-Za-z.]+(?: [A-Z][A-Za-z.]+){1,2})\n"
                                r"(?:Chief|Executive|Superintending|Deputy|Project|"
                                r"Additional|Assistant|Senior)\b", _text(doc), re.M))
        nature = re.search(r"Nature of Work\s+(.+?)\s+Contract Value", f)
        role = re.search(r"Contractor's Role\s+(Prime|JV Partner)", f)
        client = _ref_client(_text(doc))
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
            "category": nature.group(1).strip() if nature else None,
            "role": role.group(1) if role else None,
            "contact": contact.group(1).strip() if contact else None,
        })
    return out


# ------------------------------------------- annual report tables (beyond the head)

_SEG = re.compile(r"^([A-Z][A-Za-z &]{2,32})\n(-?[\d,]+)\n(-?[\d,]+)$", re.M)
_SEVEN = re.compile(r"^(\d{4})[\u2013-]\d{2}\n(-?[\d,]+)\n(-?[\d,]+)\n(-?[\d,]+)\n(-?[\d.]+)%$", re.M)
_AGE = re.compile(r"^([A-Z][A-Za-z ,&.'-]{5,60})\n(-?[\d,]+)\n(-?[\d,]+)\n(-?[\d,]+)\n(-?[\d,]+)$", re.M)
_CLI = re.compile(r"^([A-Z][A-Za-z ,&.'-]{5,60})\n(-?[\d,]+)$", re.M)
# The annual report's own balance sheet, profit and loss and quarterly table.
# All three are stated directly in rupees -- unlike the financial statements,
# which are in lakhs -- and none of them was read, so a question about the
# balance sheet was answered from the statement extract, which carries
# different figures under the same names.
_AR_LINE = re.compile(r"^([A-Z][A-Za-z ,&:()'\u2014-]{4,60}?)\n"
                      r"\(?(-?[\d,]+)\)?$", re.M)
_QTR = re.compile(r"^(Q[1-4])\s*FY\s*(\d{4})[\u2013-]\d{2}\n(-?[\d,]+)$", re.M)
_VARIATION = re.compile(r"^#(\d+)\n(\d+)\n(\d{2}/\d{2}/\d{4})\n"
                        r"(-?[\d,]+)\n(.+)$", re.M)
_CREDIT = re.compile(r"^(CN-\d{4}-\d+)\n(\d{2}/\d{2}/\d{4})\n(-?[\d,]+)\n(.+)$", re.M)


def _order_book(txt):
    """The order-book annexure: one row per contract in force.

    The client name and the contract type both wrap, so a row is a RUN of
    lines rather than a line. The serial anchors it, the same way the
    compliance matrices are read: a row opens on the line that is exactly the
    next expected number, and the three figures inside it are awarded,
    variations and the current value in that order.
    """
    rows, n, buf = [], 1, None
    for line in txt.split("\n"):
        line = line.strip()
        if line == str(n):
            if buf is not None:
                rows.append(buf)
            buf, n = [], n + 1
            continue
        if buf is not None:
            buf.append(line)
    if buf is not None:
        rows.append(buf)
    out = []
    for i, buf in enumerate(rows, 1):
        nums = [x for x in buf if re.fullmatch(r"-?[\d,]+", x)]
        if len(nums) < 3:
            continue
        words = [x for x in buf if not re.fullmatch(r"-?[\d,]+", x)]
        status = words[-1] if words and words[-1] in ("active", "closed",
                                                      "on hold", "suspended") else None
        head = words[:-1] if status else words
        # Everything before the contract TYPE is the client. The type is the
        # last one or two fragments, and it is the only field written in
        # lower case with a hyphen ("item-\nrate", "lump-\nsum", "epc").
        kind, client = None, head
        for j in range(len(head) - 1, -1, -1):
            joined = "".join(head[j:]).lower()
            if joined in ("epc", "item-rate", "lump-sum", "itemrate", "lumpsum"):
                kind, client = joined.replace("itemrate", "item-rate").replace(
                    "lumpsum", "lump-sum"), head[:j]
                break
        out.append({"seq": i, "client": " ".join(client).strip() or None,
                    "type": kind, "awarded": _num(nums[0]),
                    "variations": _num(nums[1]),
                    "current_value": _num(nums[2]), "status": status})
    return out


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
        # A bracketed figure is negative in this report -- the P&L writes every
        # expense that way -- and the balance sheet's own "Total" row is the
        # section total, kept as a line so a question can ask for it directly.
        def _ar_rows(txt, section):
            rows = []
            for m in _AR_LINE.finditer(txt):
                label = " ".join(m.group(1).split())
                if label.lower() in ("particulars", "equity and liabilities",
                                     "assets", "quarter", "client", "segment"):
                    continue
                v = _num(m.group(2))
                if v is None:
                    continue
                # A bracketed expense keeps the magnitude the report prints:
                # revenue less the sum of the expense lines is the profit for
                # the year, which is the identity the statement itself asserts.
                rows.append({"line": label, "amount": v, "section": section})
            return rows

        bs = _section(t, "EQUITY AND LIABILITIES", "STATEMENT OF PROFIT")
        i_ass = bs.find("ASSETS")
        balance = (_ar_rows(bs[:i_ass] if i_ass > 0 else bs, "Equity and Liabilities")
                   + (_ar_rows(bs[i_ass:], "Assets") if i_ass > 0 else []))
        pl = _ar_rows(_section(t, "STATEMENT OF PROFIT", "NOTES TO THE"), "Profit and Loss")
        quarters = [{"quarter": m.group(1), "year": int(m.group(2)),
                     "net_revenue": _num(m.group(3))} for m in _QTR.finditer(t)]
        variations_list = [
            {"contract": int(m.group(1)), "amendment": int(m.group(2)),
             "date": (normalize.parse_date(m.group(3)).isoformat()
                      if normalize.parse_date(m.group(3)) else None),
             "value_delta": _num(m.group(4)), "reason": m.group(5).strip()}
            for m in _VARIATION.finditer(_section(t, "ANNEXURE \u2014 VARIATION ORDERS",
                                                  "CREDIT NOTES"))]
        order_lines = _order_book(_section(t, "ANNEXURE \u2014 ORDER BOOK",
                                           "ANNEXURE \u2014 VARIATION"))
        credit_list = [
            {"credit_note": m.group(1),
             "date": (normalize.parse_date(m.group(2)).isoformat()
                      if normalize.parse_date(m.group(2)) else None),
             "amount": _num(m.group(3)), "reason": m.group(4).strip()}
            for m in _CREDIT.finditer(_section(t, "CREDIT NOTES ISSUED",
                                               "ANNEXURE \u2014 TRADE"))]
        contracts = re.search(r"(\d+) contracts remained in execution", f)
        awarded = re.search(r"aggregate awarded value of (Rs\.?\s*[\d,.]+\s*Lakh)", f, re.I)
        variations = re.search(r"approved variations of (Rs\.?\s*[\d,.]+\s*Lakh)"
                               r"\s*across (\d+) variation orders", f, re.I)
        credits = re.search(r"(\d+) credit notes\s*aggregating\s*(Rs\.?\s*[\d,.]+\s*Lakh)", f, re.I)
        out.append({
            "doc": doc, "year": int(fy.group(1)) if fy else None,
            "segments": segments, "seven_year": seven,
            "ageing": ageing, "principal_clients": clients,
            "balance_sheet": balance, "profit_and_loss": pl,
            "quarters": quarters, "variations": variations_list,
            "order_lines": order_lines, "credit_note_list": credit_list,
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


# ------------------------------------------------------ personnel certificates

_PC_FIELDS = ["Credential Type", "Credential ID", "Issuing Authority",
              "Date of Issue", "Valid Through", "Employment Status",
              "Years of Experience", "Highest Qualification"]


def credentials():
    """The 48 personnel certificates.

    build_db reads the holder and the issue date off these; the EXPIRY is here
    too and nothing reads it, so "how many days is this credential valid for"
    -- arithmetic over two dates on the same page -- had no source at all.
    """
    out = []
    for doc in _docs("DOC-PCERT-"):
        t = _text(doc)
        rec = {"doc": doc}
        for lab in _PC_FIELDS:
            v = _after(t, lab, r"(.+)")
            rec[lab.lower().replace(" ", "_")] = v.strip() if v else None
        # Second template ("This credential is conferred upon"): a shorter
        # certificate that labels the same three facts differently -- `Issued`
        # rather than `Date of Issue`, `Certificate No.` rather than
        # `Credential ID`, and the holder on the line after a different phrase.
        if not rec.get("date_of_issue"):
            rec["date_of_issue"] = _after(t, "Issued", r"(.+)")
        if not rec.get("credential_id"):
            rec["credential_id"] = _after(t, "Certificate No.", r"(\S+)")
        m = re.search(r"(?:This is to certify that|This credential is conferred upon)"
                      r"\s*\n\s*(.+)", t)
        rec["name"] = m.group(1).strip() if m else None
        emp = re.search(r"Employee ID:\s*(\S+)", t)
        rec["employee_id"] = emp.group(1) if emp else None
        exp = re.search(r"(\d+)", rec.get("years_of_experience") or "")
        rec["experience_years"] = int(exp.group(1)) if exp else None
        d0 = normalize.parse_date(rec.get("date_of_issue") or "")
        d1 = normalize.parse_date(rec.get("valid_through") or "")
        rec["issued"] = d0.isoformat() if d0 else None
        rec["expires"] = d1.isoformat() if d1 else None
        rec["validity_days"] = (d1 - d0).days if (d0 and d1) else None
        out.append(rec)
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
        "credentials": credentials(),
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
