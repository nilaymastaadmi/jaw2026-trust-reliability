#!/usr/bin/env bash
# Runs before run.sh, untimed.
#
# Nothing to fetch: this pipeline ships no model weights, no embedding model and
# no reranker. Generation is the provided endpoint; everything else is
# deterministic Python over parsed documents. So the only job here is to fail
# LOUDLY now, in untimed setup, rather than 40 minutes into a timed run.
set -euo pipefail

echo "[setup] python: $(python3 --version 2>&1)"

python3 - <<'PY'
import sys
ok = True
for mod, why in (("pymupdf", "PDF text extraction"),
                 ("openpyxl", "XLSX workbooks")):
    try:
        __import__(mod)
        print(f"[setup] OK   {mod:10s} ({why})")
    except ImportError as e:
        ok = False
        print(f"[setup] FAIL {mod:10s} ({why}): {e}")
print(f"[setup] LLM_BASE_URL = {__import__('os').environ.get('LLM_BASE_URL') or '(unset)'}")
sys.exit(0 if ok else 1)
PY

echo "[setup] no weights to download; run.sh needs no network except LLM_BASE_URL"
