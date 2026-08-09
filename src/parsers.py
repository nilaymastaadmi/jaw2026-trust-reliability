"""Per-document-type parsers.

The corpus ships the same semantic fields under different label vocabularies and,
for a third of the certificates, as running prose with no table at all.  Counts
verified by label discovery over the full estate:

  CCC   155 = 75 (Work/Executed Value/Project Lead) + 80 (Project Name/Contract Value)
  CC    155 = 84 (Name of Work table)               + 71 (pure prose)
  REF   132 = 44 (Project Name table) + 45 (Work Executed table) + 43 (prose)
  PCERT  48 = 28 (Credential Type table)            + 20 (Certificate No. table)
"""
import re

from normalize import (money, parse_date, iso, norm_client, norm_work,
                       norm_person, find_grading)

# Label synonyms -> canonical field.  Order within a list is preference order.
SYNONYMS = {
    "work":     ["Work", "Project Name", "Name of Work", "Work Executed", "Project"],
    "client":   ["Client", "Employer", "Client / Employer"],
    "category": ["Category", "Work Category", "Nature / Category", "Nature of Work"],
    "value":    ["Executed Value", "Contract Value", "Contract Value (Original)", "Value"],
    "completed": ["Completion", "Completion Date", "Date of Completion", "Completed"],
    "lead":     ["Project Lead", "Project Manager", "Contractor's Project Manager"],
    "certref":  ["Client Certificate Ref", "Contract / Tender Reference"],
    "role":     ["Contractor's Role", "Role"],
    "credential": ["Credential Type", "Certificate Type"],
    "credential_id": ["Credential ID", "Certificate No.", "Certificate Number"],
    "issued":   ["Date of Issue", "Issued", "Issue Date"],
    "emp_id":   ["Employee ID", "Emp ID"],
    "designation": ["Designation"],
    "valid":    ["Valid Through"],
}
_LABEL_TO_FIELD = {}
for _f, _labels in SYNONYMS.items():
    for _l in _labels:
        _LABEL_TO_FIELD.setdefault(_l, _f)


def fields(text):
    """label/value line pairs -> {canonical_field: raw_value}.

    PyMuPDF emits a two-column table as alternating lines, so the value for a
    label is the next non-empty line.  First occurrence wins: later sections
    (milestones, quality tables) reuse generic words we do not want to capture.
    """
    lines = [l.strip() for l in text.split("\n")]
    out = {}
    for i, line in enumerate(lines):
        field = _LABEL_TO_FIELD.get(line)
        if not field or field in out:
            continue
        for nxt in lines[i + 1:i + 3]:
            if nxt:
                out[field] = nxt
                break
    return out


def _clean_work(w):
    """Drop a trailing parenthetical category and any 'Pkg' noise kept intact."""
    if not w:
        return None
    return re.sub(r"\s*\((?!Pkg)[^)]*\)\s*$", "", w).strip(" .,;\"“”")


# ------------------------------------------------------------------ CCC / CC

_PROSE_WORK = re.compile(r"(?:the work of|for the work)\s*[“\"']([^”\"']+)[”\"']", re.I)
_PROSE_ON = re.compile(r"completed in all respects on\s+([\d/.-]+|\w+\s+\d{1,2},?\s+\d{4})", re.I)
_PROSE_VALUE = re.compile(r"(?:gross executed value|executed value|value)\s+of\s+((?:INR|Rs\.?)\s*[\d.,]+\s*(?:Cr|Crore|Lakh)s?)", re.I)
_PROSE_LEAD = re.compile(r"supervised[^.]*?\bby\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", re.I)
_PROSE_CLIENT_HEAD = re.compile(r"^([^\n]+)\n")


def parse_certificate(doc_id, text):
    """CCC and CC share a shape: one work, its client, value, date, lead."""
    f = fields(text)
    work = _clean_work(f.get("work"))
    value = money(f.get("value"))
    completed = parse_date(f.get("completed"))
    lead = norm_person(f.get("lead"))
    client = f.get("client")

    if not work:                                        # prose layout (71 CCs)
        m = _PROSE_WORK.search(text)
        if m:
            work = _clean_work(m.group(1))
    if value is None:
        m = _PROSE_VALUE.search(text)
        if m:
            value = money(m.group(1))
    if completed is None:
        m = _PROSE_ON.search(text)
        if m:
            completed = parse_date(m.group(1))
    if not lead:
        m = _PROSE_LEAD.search(text)
        if m:
            lead = norm_person(m.group(1))
    if not client:
        # prose certificates are issued ON the client's letterhead: line 1
        m = _PROSE_CLIENT_HEAD.match(text)
        if m and "National Infrastructure" not in m.group(1):
            client = m.group(1)

    return {
        "doc_id": doc_id,
        "work": work,
        "work_key": norm_work(work),
        "client": norm_client(client),
        "category": (f.get("category") or "").strip() or None,
        "value": value,
        "completed": iso(completed),
        "lead": lead,
        "certref": f.get("certref"),
        "grading": find_grading(text),
    }


# ------------------------------------------------------------------ REF

def parse_reference(doc_id, text):
    """Which work does this letter attest to?  Absence questions hinge on this."""
    f = fields(text)
    work = _clean_work(f.get("work"))
    if not work:
        m = _PROSE_WORK.search(text)
        if m:
            work = _clean_work(m.group(1))
    if not work:                                   # any quoted string, last resort
        m = re.search(r"[“\"']([^”\"']{8,90})[”\"']", text)
        if m:
            work = _clean_work(m.group(1))
    role = f.get("role")
    return {
        "doc_id": doc_id,
        "work": work,
        "work_key": norm_work(work),
        "value": money(f.get("value")),
        "role": role.strip() if role else None,
        "grading": find_grading(text),
    }


# ------------------------------------------------------------------ PCERT / CV

_CERT_NAME = re.compile(
    r"(?:This is to certify that|This credential is conferred upon|Credential Holder)\s*\n\s*([^\n]+)", re.I)

# Credential TYPES, not issuing authorities.  Layout B prints the authority
# ("PMI", "ASQ") on line 1 and the credential ("PMP", "SIX SIGMA BLACK BELT")
# on line 3, so a regex that treats both alike files 20 of 48 certificates
# under the authority -- and date_span / temporal_chain filter on the type.
_CRED_TYPE = re.compile(
    r"\b(PMP|Six\s+Sigma\s+Black\s+Belt|Six\s+Sigma\s+Green\s+Belt|CSSBB|CQE)\b", re.I)
_CRED_BODY = re.compile(r"\b(PMI|ASQ)\b")
_CONFERRED = re.compile(r"^(.+)\n(?:This credential is conferred upon)", re.M)

_CANON = {"pmp": "PMP", "sixsigmablackbelt": "Six Sigma Black Belt",
          "sixsigmagreenbelt": "Six Sigma Green Belt", "cssbb": "Six Sigma Black Belt",
          "cqe": "CQE", "pmi": "PMI", "asq": "ASQ"}


def _canon_credential(s):
    if not s:
        return None
    key = re.sub(r"[^a-z]", "", s.lower())
    return _CANON.get(key, " ".join(w.capitalize() for w in s.split()))


def parse_personnel(doc_id, text):
    f = fields(text)
    m = _CERT_NAME.search(text)
    name = norm_person(m.group(1)) if m else None
    if not name:
        m = re.search(r"^([A-Z][a-z]+\s+[A-Z][a-z]+)$", text, re.M)
        name = norm_person(m.group(1)) if m else None

    cred = f.get("credential")                    # layout A: labelled field
    if not cred:
        m = _CONFERRED.search(text)               # layout B: line above conferral
        if m and _CRED_TYPE.fullmatch(m.group(1).strip()):
            cred = m.group(1).strip()
    if not cred:
        m = _CRED_TYPE.search(text)               # any credential type anywhere
        cred = m.group(1) if m else None
    if not cred:
        m = _CRED_BODY.search(text)               # last resort: the authority
        cred = m.group(1) if m else None

    return {
        "doc_id": doc_id,
        "name": name,
        "emp_id": f.get("emp_id"),
        "credential": _canon_credential(cred),
        "credential_id": f.get("credential_id"),
        "issued": iso(parse_date(f.get("issued"))),
        "designation": f.get("designation"),
    }


_CV_NAME = re.compile(r"\bName\s*\n\s*([^\n]+)")


def parse_cv(doc_id, text):
    f = fields(text)
    m = _CV_NAME.search(text)
    return {
        "doc_id": doc_id,
        "name": norm_person(m.group(1)) if m else None,
        "emp_id": f.get("emp_id"),
        "designation": f.get("designation"),
    }
