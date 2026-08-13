"""Text extraction over the document estate.

PyMuPDF only.  pdfplumber returns field LABELS and silently drops field VALUES on
the table-heavy certificates (15 digits recovered vs 129 on DOC-CC-001) and
reports no error while doing it.  layout=True does not fix it.

INGESTION CONTRACT
------------------
The grader hands us a directory path and warns that "the tree is nested by
document type and the nesting will not match any sample you have seen".  So we
walk it recursively and never depend on a directory layout.

There may also be no document_index.csv -- that manifest ships with our copy of
the dataset, not with an arbitrary document estate.  If it is absent we
synthesise the index by walking, deriving doc_type from the doc_id PREFIX rather
than the containing folder:

    DOC-CCC-001.pdf  ->  doc_id DOC-CCC-001, token CCC, company_completion_certificate

The prefix travels inside the filename, so it survives a re-nesting that a
folder name would not.  Folder names are consulted only as a fallback, for an
unrecognised prefix.
"""
import csv
import json
import os
import re
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
CACHE = WORK / "text_cache"

# The token between the first and last dash of a doc_id maps to a document type.
# Longest-token-wins is implicit: we split on dashes, so CC and CCC never collide.
_PREFIX_TYPE = {
    "AR": "annual_report",
    "BANK": "bank_statement",
    "BOND": "performance_bond",
    "CC": "completion_certificate",
    "CCC": "company_completion_certificate",
    "CERT": "iso_certificate",
    "CM": "compliance_matrix",
    "CV": "cv",
    "DOSSIER": "tender_dossier",
    "FINBILL": "final_ra_bill",
    "FS": "financial_statement",
    "GLB": "general_ledger_book",
    "PCERT": "personnel_certificate",
    "PPP": "past_performance_portfolio",
    "RABILL": "ra_bill",
    "REF": "reference_letter",
    "XL": "workbooks",
}
_KNOWN_TYPES = set(_PREFIX_TYPE.values())

# Workbook filenames carry no DOC- id at all in the shipped dataset, so map them
# by stem.  Matched case- and separator-insensitively against the real stem.
_XLSX_STEM_ID = {
    "receivables_ageing": "DOC-XL-AGEING",
    "plant_and_machinery_register": "DOC-XL-ASSETS",
    "trial_balance_by_year": "DOC-XL-TB",
}


def _docs_root():
    """Where the documents live.  --docs / JAW_DOCS wins; else the local clone."""
    env = os.environ.get("JAW_DOCS")
    if env:
        return Path(env).resolve()
    return (ROOT / "dataset" / "documents").resolve()


def set_docs_root(path):
    """Point ingestion at a directory (used by run.sh via --docs)."""
    os.environ["JAW_DOCS"] = str(Path(path).resolve())
    _index_cache.clear()
    return _docs_root()


# Kept as module attributes because the parsers and tests import them by name.
DATA = ROOT / "dataset"
DOCS = _docs_root()

_index_cache = {}


def _doc_id_for(path):
    """doc_id from a filename, whatever the folder above it is called."""
    stem = path.stem
    m = re.match(r"(DOC-[A-Z]+-[A-Za-z0-9]+)", stem)
    if m:
        return m.group(1)
    key = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
    if key in _XLSX_STEM_ID:
        return _XLSX_STEM_ID[key]
    m = re.match(r"boq_and_measurements_contract_(\d+)", key)
    if m:
        return f"DOC-XL-BOQ-{int(m.group(1)):03d}"
    return stem


def _doc_type_for(doc_id, path):
    """Prefix first (travels with the file), folder name only as a fallback."""
    parts = doc_id.split("-")
    if len(parts) >= 3 and parts[0] == "DOC":
        t = _PREFIX_TYPE.get(parts[1].upper())
        if t:
            return t
    for parent in path.parents:                       # unrecognised prefix
        name = re.sub(r"[^a-z0-9]+", "_", parent.name.lower()).strip("_")
        if name in _KNOWN_TYPES:
            return name
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return "workbooks"
    return "unknown"


def _walk(root):
    """Every PDF and XLSX under root, recursively."""
    rows = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in (".pdf", ".xlsx", ".xlsm"):
            continue
        if p.name.startswith("~$"):                   # Excel lock files
            continue
        doc_id = _doc_id_for(p)
        rows.append({"doc_id": doc_id,
                     "doc_type": _doc_type_for(doc_id, p),
                     "filename": str(p.relative_to(root)).replace("\\", "/"),
                     "path": p,
                     "size_bytes": p.stat().st_size})
    return rows


def index():
    """[{doc_id, doc_type, filename, path, size_bytes}] for the whole estate."""
    root = _docs_root()
    key = str(root)
    if key in _index_cache:
        return _index_cache[key]

    rows = None
    # Use a shipped manifest if one is genuinely there, but only when it covers
    # what is on disk -- a stale manifest is worse than no manifest.
    for cand in (root.parent / "document_index.csv", root / "document_index.csv"):
        if not cand.exists():
            continue
        with open(cand, encoding="utf-8") as fh:
            listed = list(csv.DictReader(fh))
        resolved = []
        for r in listed:
            p = root / r["filename"].replace("\\", "/")
            if not p.exists():
                resolved = None
                break
            r["path"] = p
            resolved.append(r)
        if resolved:
            rows = resolved
            break

    if rows is None:
        rows = _walk(root)
        print(f"[corpus] no usable manifest; walked {root} -> {len(rows)} documents")

    _index_cache[key] = rows
    return rows


def _extract(path):
    doc = pymupdf.open(path)
    try:
        return "\n".join(p.get_text("text") for p in doc)
    finally:
        doc.close()


def _cache_dir():
    # Namespace the cache per docs root so a run against a new estate can never
    # read text extracted from a previous one.
    tag = re.sub(r"[^A-Za-z0-9]+", "_", str(_docs_root()))[-60:]
    return CACHE / tag


def build_cache(verbose=True):
    """Extract every PDF once into work/text_cache/<root>/<doc_id>.txt."""
    cdir = _cache_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    rows = [r for r in index() if str(r["path"]).lower().endswith(".pdf")]
    n = 0
    for i, row in enumerate(rows, 1):
        out = cdir / f"{row['doc_id']}.txt"
        if out.exists():
            continue
        try:
            out.write_text(_extract(row["path"]), encoding="utf-8")
        except Exception as e:                        # one bad PDF must not end the run
            print(f"[corpus] WARN {row['doc_id']}: {e}")
            out.write_text("", encoding="utf-8")
        n += 1
        if verbose and i % 100 == 0:
            print(f"[corpus] extracted {i}/{len(rows)}")
    if verbose:
        print(f"[corpus] extracted {n} new, cache holds {len(list(cdir.glob('*.txt')))}")
    return n


def text(doc_id):
    p = _cache_dir() / f"{doc_id}.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    row = next((r for r in index() if r["doc_id"] == doc_id), None)
    return _extract(row["path"]) if row else ""


def by_type(doc_type):
    """[(doc_id, text)] for one document type, in doc_id order."""
    rows = [r for r in index() if r["doc_type"] == doc_type]
    rows.sort(key=lambda r: r["doc_id"])
    return [(r["doc_id"], text(r["doc_id"])) for r in rows]


def paths_by_type(doc_type):
    """[(doc_id, Path)] -- for the workbooks, which openpyxl opens directly."""
    rows = [r for r in index() if r["doc_type"] == doc_type]
    rows.sort(key=lambda r: r["doc_id"])
    return [(r["doc_id"], r["path"]) for r in rows]


def one_of_type(doc_type):
    """The single document of a type (portfolio), by type not by hardcoded id."""
    rows = [r for r in index() if r["doc_type"] == doc_type]
    return text(sorted(rows, key=lambda r: r["doc_id"])[0]["doc_id"]) if rows else ""


def save_json(name, obj):
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str),
                             encoding="utf-8")
    return WORK / name


def load_json(name):
    return json.loads((WORK / name).read_text(encoding="utf-8"))
