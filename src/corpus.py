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

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "dataset"
DOCS = DATA / "documents"
WORK = ROOT / "work"
CACHE = WORK / "text_cache"


def index():
    """[{doc_id, doc_type, filename, size_bytes}] from the shipped index."""
    with open(DATA / "document_index.csv", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


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
        text = _extract(DOCS / row["filename"])
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
    return _extract(DOCS / row["filename"])


def by_type(doc_type):
    """[(doc_id, text)] for one document type, in doc_id order."""
    rows = [r for r in index() if r["doc_type"] == doc_type]
    rows.sort(key=lambda r: r["doc_id"])
    return [(r["doc_id"], text(r["doc_id"])) for r in rows]


def save_json(name, obj):
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str),
                             encoding="utf-8")
    return WORK / name


def load_json(name):
    return json.loads((WORK / name).read_text(encoding="utf-8"))
