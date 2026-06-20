#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CSV_PATH="${1:-../jan to may police violation_anonymized791b166.csv}"
PYTHON_BIN="${PYTHON_BIN:-/Users/dakshaggarwal/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"

"$PYTHON_BIN" -m ml.pipeline.etl --csv "$CSV_PATH"
npm run generate
npm test

echo "NammaPark Intel local demo pipeline completed."
