#!/usr/bin/env bash
# End-to-end pipeline: documents in, one CSV out.
#
#   ./run.sh --docs /path/to/documents --questions /path/to/questions.json \
#            --out submission.csv
#
# Everything happens here: extraction, the entity store, and the answers. There
# are no model weights to fetch -- we ship no embedding model, reranker or
# vector store -- so the only network the pipeline touches is LLM_BASE_URL, the
# endpoint provided to us, and it touches that only where the deterministic
# path has already failed. Every figure that path produces is computed in
# Python over exactly-parsed integers.
set -euo pipefail

DOCS=""; QUESTIONS=""; OUT="submission.csv"
while [ $# -gt 0 ]; do
  case "$1" in
    --docs)      DOCS="$2";      shift 2 ;;
    --questions) QUESTIONS="$2"; shift 2 ;;
    --out)       OUT="$2";       shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$DOCS" ]      || { echo "--docs is required" >&2; exit 2; }
[ -n "$QUESTIONS" ] || { echo "--questions is required" >&2; exit 2; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Resolve BEFORE changing directory. The documented invocation is
# `--out submission.csv`, a path relative to wherever the caller stands; run
# from src/ it would land there instead and look like the run produced nothing.
case "$QUESTIONS" in /*) ;; *) QUESTIONS="$PWD/$QUESTIONS" ;; esac
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac
mkdir -p "$(dirname "$OUT")"

# The tree we are handed is nested by document type in a layout we have not
# seen, so nothing may depend on the shipped one: every document is found by
# walking recursively and keying on the file name.
export JAW_DOCS="$(cd "$DOCS" && pwd)"
export JAW_DATA="$JAW_DOCS"
export JAW_WORK="${JAW_WORK:-$HERE/work}"
export PYTHONIOENCODING=utf-8

# Pick an interpreter that actually CARRIES the dependencies, not merely one
# that exists. `command -v python3` succeeds on machines where python3 is a
# stub that has never seen `pip install -r requirements.txt`, and the run then
# dies on `import pymupdf` after the harness has already started timing it.
PY=""
for cand in "${PYTHON:-}" python3 python; do
  [ -n "$cand" ] || continue
  if command -v "$cand" >/dev/null 2>&1 \
     && "$cand" -c "import pymupdf, openpyxl" >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "no interpreter with pymupdf+openpyxl; run: pip install -r requirements.txt" >&2
  exit 1
fi
echo "[run] python    : $PY ($("$PY" --version 2>&1))"

echo "[run] documents : $JAW_DOCS"
echo "[run] questions : $QUESTIONS"
echo "[run] output    : $OUT"
mkdir -p "$JAW_WORK"

cd "$HERE/src"
"$PY" answer.py --questions "$QUESTIONS" --out "$OUT" --force
echo "[run] done -> $OUT"
