#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for d in "$@"; do
  echo "== $d =="
  ls -1 "$d" 2>/dev/null
done
