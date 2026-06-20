#!/usr/bin/env bash
set -euo pipefail

URL="${1:-http://127.0.0.1:8787/health}"

for attempt in $(seq 1 10); do
  if curl -fsS "$URL" >/dev/null; then
    echo "API is warm: $URL"
    exit 0
  fi
  echo "Waiting for API ($attempt/10)..."
  sleep 5
done

echo "API did not become healthy: $URL" >&2
exit 1
