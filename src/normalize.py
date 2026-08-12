"""Normalisation for the four corpus traps: money, dates, client names, work names.

Every function here is pure and deterministic. Nothing in the answer path may
approximate -- the scorer pays 1.0 only inside 0.5% relative error, and 0.3 beyond.
"""
import re
from datetime import date

# ---------------------------------------------------------------- money

_UNIT = {"cr": 10**7, "crore": 10**7, "crores": 10**7,
         "lakh": 10**5, "lakhs": 10**5, "lac": 10**5, "lacs": 10**5}

# The sign is part of the number. This corpus is full of losses -- negative
# profit years in the annual report and the dossiers' financial-standing
# annexure, credit balances in the ledgers, and every `paid` invoice in the
# ageing workbook, where Received exceeds Invoiced. Dropping the minus turns
# -39,026,159 into +39,026,159, which under proportional scoring is not a
# near-miss: it scores zero.
_MONEY_UNIT = re.compile(
    r"(?:INR|Rs\.?|₹|Rupees)?\s*(-?[\d][\d,]*(?:\.\d+)?)\s*(Cr|Crores?|Lakhs?|Lacs?)\b",
    re.I)
_MONEY_PLAIN = re.compile(r"(?:INR|Rs\.?|₹)\s*(-?[\d][\d,]*(?:\.\d+)?)")


def money(s):
    """'INR 33.38 Cr' | 'Rs. 33.38 Crore' | '3,338.00 Lakh' | '33,38,00,000' -> 333800000

    Indian digit grouping is handled by stripping commas, which is lossless here:
    the corpus never uses commas as decimal separators.
    """
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    # Accounting parentheses are a minus sign: the RA bills print retention as
    # "(2,464,151)".
    paren = bool(re.fullmatch(r"\(\s*[^()]*\d[^()]*\s*\)", s))
    if paren:
        s = s.strip()[1:-1].strip()
    m = _MONEY_UNIT.search(s)
    if m:
        val = float(m.group(1).replace(",", ""))
        if paren:
            val = -val
        # round(), not int(): 33.38 * 1e7 == 333800000.00000006 in binary float
        return round(val * _UNIT[m.group(2).lower()])
    m = _MONEY_PLAIN.search(s)
    if m:
        v = round(float(m.group(1).replace(",", "")))
        return -v if paren else v
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", s)
    if m:
        v = round(float(m.group(0).replace(",", "")))
        return -v if paren else v
    return None


# ---------------------------------------------------------------- word numbers

_WORD = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
         "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
         "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
         "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90, "hundred": 100}


def words_to_number(text):
    """'seventy-three' -> 73.  Returns None when no number words are present."""
    toks = re.split(r"[\s-]+", text.lower().strip())
    toks = [t for t in toks if t in _WORD or t == "and"]
    if not toks:
        return None
    total = cur = 0
    for t in toks:
        if t == "and":
            continue
        v = _WORD[t]
        if v == 100:
            cur = (cur or 1) * 100
        else:
            cur += v
    total += cur
    return total or None


def threshold_from_text(text):
    """Pull a rupee threshold out of question prose.

    'crossing the seventy-three crore mark' -> 730000000
    'credential target of INR 20 Cr'        -> 200000000
    """
    m = _MONEY_UNIT.search(text)
    if m:
        return round(float(m.group(1).replace(",", "")) * _UNIT[m.group(2).lower()])
    m = re.search(r"((?:[a-z]+[\s-]){1,4}?)(crore|lakh|lac)s?\b", text, re.I)
    if m:
        n = words_to_number(m.group(1))
        if n:
            return round(n * _UNIT[m.group(2).lower()])
    return _bare_rupees(text)


# A rupee figure written out in full, with no unit word to key on:
# "contracts of 30,00,00,000 or more", "anything above 500000000". The corpus
# and the organisers' own README write money this way as often as they write
# crore, so a threshold reader that only understands "30 Cr" is blind to half
# the phrasings -- and a missed threshold does not degrade the answer, it
# changes the SHAPE, because a threshold question with no threshold falls
# through to the client's whole portfolio.
_BARE = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{2,3})+|\d{7,})(?![\d.,])"
                   r"(?!\s*(?:cr\b|crore|lakh|lac))", re.I)


def _bare_rupees(text):
    """The largest plain rupee amount in the text, or None.

    Floored at ten lakh so that four-digit years, head-counts and percentages
    can never be read as money -- every threshold this corpus states is in
    crores, and the floor is two orders of magnitude below the smallest.
    """
    best = None
    for m in _BARE.finditer(text):
        v = float(m.group(1).replace(",", ""))
        if v >= 10**6 and (best is None or v > best):
            best = v
    return round(best) if best is not None else None


# ---------------------------------------------------------------- dates

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_date(s):
    """-> datetime.date

    The corpus mixes DD/MM/YYYY with YYYY-MM-DD.  DD/MM is verified against
    DOC-CC-001, whose table reads 06/02/2011 for a completion the client
    certificate states as 2011-02-06.  Reading these as US MM/DD silently
    corrupts every date_span answer, so day-first is asserted in tests.
    """
    if not s:
        return None
    s = str(s).strip()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", s)
    if m:                                    # day-first, never month-first
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b", s)
    if m and m.group(2)[:3].lower() in _MONTHS:
        return date(int(m.group(3)), _MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b", s)
    if m and m.group(1)[:3].lower() in _MONTHS:
        return date(int(m.group(3)), _MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    return None


def iso(d):
    return d.isoformat() if d else None


# ---------------------------------------------------------------- names

_CLIENT_SUFFIX = re.compile(r"\s*\((?:government|govt|psu|private|public|semi-govt)\)\s*$", re.I)


def norm_client(c):
    """Strip the trailing type tag and collapse whitespace.

    'Trishakti Power Generation Corporation (psu)' and '... (Psu)' are the SAME
    client.  Grouping on the raw string splits one portfolio into two and
    corrupts every client-level aggregate.
    """
    if not c:
        return None
    c = _CLIENT_SUFFIX.sub("", str(c))
    return re.sub(r"\s+", " ", c).strip(" .,;")


def norm_work(w):
    """Case- and dash-insensitive work key.

    The portfolio renders names in decorative mixed case
    ('extradosed BridGe - GUJarat PkG-106'), so the key must ignore case,
    dash flavour (em/en/hyphen) and spacing.
    """
    if not w:
        return None
    w = re.sub(r"[‐-―−-]+", " ", str(w))
    w = re.sub(r"[^\w\s]", " ", w)
    return re.sub(r"\s+", " ", w).strip().lower()


def norm_person(p):
    if not p:
        return None
    p = re.sub(r"\s+", " ", str(p)).strip(" .,;")
    p = re.sub(r"^(?:Mr|Mrs|Ms|Shri|Smt|Dr)\.?\s+", "", p, flags=re.I)
    return p


# ---------------------------------------------------------------- grading

GRADES = ["Outstanding", "Excellent", "Very Good", "Good", "Satisfactory", "Fair", "Average", "Poor"]


# Only these three renderings state a grade.  Everything else that contains the
# word "satisfactory" is boilerplate -- "The quality of work has been found
# satisfactory during the final inspection" appears verbatim on certificates
# whose stated grade is Good, so treating it as a grade poisons the filter.
_GRADE_PATTERNS = [
    r"is\s+graded\s+(?:as\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
    r"\bgraded\s+(?:as\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
    r"assessed\s+the\s+completed\s+work\s+as\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
    r"representative\s+assessed[^.]*?\bas\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
]

# DO NOT infer a grade from prose that merely contains a grading word.
#
# An earlier version read "taken over on satisfactory completion" as a grade of
# Satisfactory. That was wrong, and it was wrong in the specific way the dataset
# authors later measured: on 2026-08-09 they withdrew HS-IC-0013/0014 and
# excluded grading-filtered questions from scoring, reporting that
#
#   "41 of 155 works have a grading stated nowhere in their own documents, and
#    17 of those carry a grading WORD that is not their grade."
#
# The rule had been reverse-engineered to make HS-IC-0014's gold come out, so it
# encoded the gold rather than the documents. Grading is now reported ONLY where
# a certificate states it outright; works whose documents never name a grade
# correctly carry None.


def find_grading(text):
    """Client's written assessment, or None when no document states one."""
    flat = re.sub(r"\s+", " ", text)
    for p in _GRADE_PATTERNS:
        m = re.search(p, flat)
        if m:
            g = " ".join(m.group(1).split())
            for known in GRADES:
                if g.lower() == known.lower():
                    return known
    return None
