#!/usr/bin/env bash
# Re-render quality_smoke_browser_use using Volcengine Doubao BigTTS as the
# primary TTS provider. Assumes .env contains VOLC_APPID + VOLC_ACCESS_TOKEN.
set -uo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-$HOME/venv-content-mvp/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo "[render_with_doubao] python not found at $PYTHON" >&2
  exit 2
fi

echo "[render_with_doubao] forcing TTS provider = doubao"
export CONTENT_ASSET_TTS_PROVIDER=doubao

CONTENT_ID="${1:-quality_smoke_browser_use}"
echo "[render_with_doubao] content_id=$CONTENT_ID"

"$PYTHON" -m app.main --render-video "$CONTENT_ID" 2>&1 | tee "output/_probe/render_doubao_${CONTENT_ID}.log"
