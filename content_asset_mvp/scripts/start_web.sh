#!/usr/bin/env bash
# Start the content asset web console using the WSL Linux venv,
# pinned to this exact project copy on /mnt/f and bound to 0.0.0.0
# so Windows browser can hit http://localhost:8001
set -euo pipefail

cd "$(dirname "$0")/.."
export PYTHONPATH=.
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8001}"

exec ~/venv-content-mvp/bin/python -m app.web --host "$HOST" --port "$PORT"
