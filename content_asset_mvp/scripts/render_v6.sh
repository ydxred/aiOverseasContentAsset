#!/usr/bin/env bash
set -euo pipefail
content_id="${1:?content_id required}"
shift || true
cd "$(dirname "$0")/.."
export PYTHONPATH=.
exec ~/venv-content-mvp/bin/python -m app.main --render-video "$content_id" "$@"
