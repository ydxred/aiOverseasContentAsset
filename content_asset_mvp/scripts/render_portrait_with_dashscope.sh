#!/usr/bin/env bash
# Run the full portrait pipeline (--render-video <id>) with DashScope TTS
# automatically picked up via QWEN_API_KEY in .env. No --render-landscape
# here so the run stays around 5-7 minutes.
set -euo pipefail

CONTENT_ID="${1:-quality_smoke_browser_use}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

VENV="${HOME}/venv-content-mvp"
"$VENV/bin/python" -m app.main --render-video "$CONTENT_ID"
