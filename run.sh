#!/usr/bin/env bash
# ./run.sh --docs /path/to/documents --questions /path/to/questions.json --out submission.csv
#
# Ingestion -> database -> query -> CSV, from a clean checkout given only those
# three paths. Every stage prints progress to stdout so a stall is locatable.
set -euo pipefail

DOCS=""; QUESTIONS=""; OUT="submission.csv"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --docs)      DOCS="$2";      shift 2 ;;
    --questions) QUESTIONS="$2"; shift 2 ;;
    --out)       OUT="$2";       shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$DOCS" || -z "$QUESTIONS" ]]; then
  echo "usage: ./run.sh --docs DIR --questions FILE.json --out FILE.csv" >&2
  exit 2
fi
if [[ ! -d "$DOCS" ]]; then echo "--docs is not a directory: $DOCS" >&2; exit 2; fi
if [[ ! -f "$QUESTIONS" ]]; then echo "--questions is not a file: $QUESTIONS" >&2; exit 2; fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

# Pick an interpreter that actually carries the dependencies. On a clean grader
# image python3 is right; on other machines `python3` can resolve to a stub that
# has never seen `pip install -r requirements.txt`. Check, do not assume.
PY=""
for cand in "${PYTHON:-}" python3 python; do
  [[ -z "$cand" ]] && continue
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import pymupdf, openpyxl" >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
if [[ -z "$PY" ]]; then
  echo "no interpreter with pymupdf+openpyxl found; run: pip install -r requirements.txt" >&2
  exit 1
fi
echo "  python    : $PY ($("$PY" --version 2>&1))"
export PYTHONIOENCODING=utf-8          # the corpus carries em-dashes and rupee signs
export PYTHONUNBUFFERED=1              # so a stalled run shows where it stalled
export JAW_DOCS="$DOCS"

echo "=============================================================="
echo "  docs      : $DOCS"
echo "  questions : $QUESTIONS"
echo "  out       : $OUT"
echo "  endpoint  : ${LLM_BASE_URL:-(unset -- deterministic path only)}"
echo "=============================================================="

echo "[1/2] ingest + build database"
"$PY" src/build_db.py --docs "$DOCS"

echo "[2/2] answer questions"
"$PY" src/answer.py --docs "$DOCS" --questions "$QUESTIONS" --out "$OUT" --llm --force

echo "[done] wrote $OUT ($(($(wc -l < "$OUT") - 1)) answers)"
