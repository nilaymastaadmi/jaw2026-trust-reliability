"""Text extraction over the document estate.

PyMuPDF only.  pdfplumber returns field LABELS and silently drops field VALUES on
the table-heavy certificates (15 digits recovered vs 129 on DOC-CC-001) and
reports no error while doing it.  layout=True does not fix it.
"""
import csv
import json
import sys
import warnings
from pathlib import Path

# The corpus is full of em dashes and rupee signs, and so is the triage output.
# On a console that is not UTF-8 -- the Windows default -- printing one raises
# UnicodeEncodeError and takes the run down AFTER the answers were computed.
# Every entry point imports this module, so reconfiguring here covers all of
# them rather than asking whoever runs the harness to set PYTHONIOENCODING.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                   # not a real stream
        pass

warnings.filterwarnings("ignore")
import pymupdf

import os

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("JAW_DATA") or (ROOT / "dataset"))
# The evaluation hands us a directory and says the nesting will not match any
# sample we have seen, so nothing may depend on the shipped layout.
DOCS = Path(os.environ.get("JAW_DOCS") or (DATA / "documents"))
WORK = Path(os.environ.get("JAW_WORK") or (ROOT / "work"))
CACHE = WORK / "text_cache"

# Files that are documents. Everything else in the tree is ignored.
_PDF = (".pdf",)
_XLSX = (".xlsx", ".xlsm")


def walk(exts=_PDF + _XLSX):
    """Every document under DOCS, at any depth, deepest-stable order."""
    return sorted((p for p in DOCS.rglob("*")
                   if p.is_file() and p.suffix.lower() in exts),
                  key=lambda p: (p.name.lower(), str(p)))


def find(name):
    """The path of a document by file name, wherever it sits in the tree."""
    for p in walk():
        if p.name == name or p.stem == name:
            return p
    return None


def index():
    """[{doc_id, doc_type, filename, size_bytes}].

    From the shipped index where there is one; otherwise built by walking the
    tree. The doc id is the file STEM, which is what every parser keys on and
    what the documents print in their own footers.
    """
    idx = DATA / "document_index.csv"
    if idx.exists():
        with open(idx, encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    return [{"doc_id": p.stem, "doc_type": p.parent.name,
             "filename": str(p.relative_to(DOCS)), "size_bytes": p.stat().st_size}
            for p in walk()]


def _path(row):
    """The file for an index row, whichever layout the tree uses."""
    p = DOCS / row["filename"]
    return p if p.exists() else (find(row["filename"]) or find(row["doc_id"]) or p)


def _extract(path):
    doc = pymupdf.open(path)
    try:
        return "\n".join(p.get_text("text") for p in doc)
    finally:
        doc.close()


def build_cache(verbose=True):
    """Extract all PDFs once into work/text_cache/<doc_id>.txt."""
    CACHE.mkdir(parents=True, exist_ok=True)
    n = 0
    for row in index():
        if not row["filename"].lower().endswith(".pdf"):
            continue
        out = CACHE / f"{row['doc_id']}.txt"
        if out.exists():
            continue
        text = _extract(_path(row))
        out.write_text(text, encoding="utf-8")
        n += 1
    if verbose:
        print(f"[corpus] extracted {n} new, cache holds {len(list(CACHE.glob('*.txt')))}")
    return n


def text(doc_id):
    p = CACHE / f"{doc_id}.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    row = next(r for r in index() if r["doc_id"] == doc_id)
    return _extract(_path(row))


# The document id encodes the type, and the FOLDER only encodes it when the
# tree is laid out the way the sample was. The evaluation nests by document
# type in a layout we have not seen, so the id is the reliable key and the
# folder is the fallback.
_TYPE_PREFIX = {
    "company_completion_certificate": "DOC-CCC-",
    "completion_certificate": "DOC-CC-",
    "reference_letter": "DOC-REF-",
    "personnel_certificate": "DOC-PCERT-",
    "cv": "DOC-CV-",
    "past_performance_portfolio": "DOC-PPP-",
    "performance_bond": "DOC-BOND-",
    "compliance_matrix": "DOC-CM-",
    "iso_certificate": "DOC-CERT-",
    "tender_dossier": "DOC-DOSSIER-",
    "financial_statement": "DOC-FS-",
    "ra_bill": "DOC-RABILL-",
    "final_ra_bill": "DOC-FINBILL-",
    "bank_statement": "DOC-BANK-",
    "general_ledger_book": "DOC-GLB-",
    "annual_report": "DOC-AR-",
}


def by_type(doc_type):
    """[(doc_id, text)] for one document type, in doc_id order."""
    pre = _TYPE_PREFIX.get(doc_type)
    rows = [r for r in index() if r["doc_type"] == doc_type]
    if not rows and pre:
        rows = [r for r in index() if str(r["doc_id"]).startswith(pre)]
        # DOC-CC- is a prefix of DOC-CCC-, so the shorter one has to exclude
        # the longer or the client copies swallow the contractor's.
        longer = [v for v in _TYPE_PREFIX.values() if v != pre and v.startswith(pre)]
        rows = [r for r in rows
                if not any(str(r["doc_id"]).startswith(x) for x in longer)]
    rows.sort(key=lambda r: r["doc_id"])
    return [(r["doc_id"], text(r["doc_id"])) for r in rows]


def save_json(name, obj):
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str),
                             encoding="utf-8")
    return WORK / name


def load_json(name):
    return json.loads((WORK / name).read_text(encoding="utf-8"))
