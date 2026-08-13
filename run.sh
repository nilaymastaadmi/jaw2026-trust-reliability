#!/usr/bin/env bash
# End-to-end pipeline: documents in, one CSV out.
#
#   ./run.sh --docs /path/to/documents --questions /path/to/questions.json \
#            --out submission.csv
#
# Everything happens here: extraction, the entity store, and the answers. No
# network is used at any point -- there are no model weights to fetch, because
# no language model runs in the answer path. Every figure is computed in Python
# over exactly-parsed integers.
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

# The tree we are handed is nested by document type in a layout we have not
# seen, so nothing may depend on the shipped one: every document is found by
# walking recursively and keying on the file name.
export JAW_DOCS="$(cd "$DOCS" && pwd)"
export JAW_DATA="$JAW_DOCS"
export JAW_WORK="${JAW_WORK:-$HERE/work}"
export PYTHONIOENCODING=utf-8

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

echo "[run] documents : $JAW_DOCS"
echo "[run] questions : $QUESTIONS"
echo "[run] output    : $OUT"
mkdir -p "$JAW_WORK"

cd "$HERE/src"
"$PY" answer.py --questions "$QUESTIONS" --out "$OUT" --force
echo "[run] done -> $OUT"
