#!/usr/bin/env bash
# Synthesize the entire chinese_script.md voiceover via the new tts_engine,
# end to end (provider dispatch + DashScope), without running Remotion.
# This is the fastest way to verify integration before a full re-render.
set -euo pipefail

CONTENT_ID="${1:-quality_smoke_browser_use}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

VENV="${HOME}/venv-content-mvp"
if [ ! -d "$VENV" ]; then
  echo "ERR: linux venv not at $VENV" >&2
  exit 1
fi

# Load QWEN_API_KEY into env for the python process.
if [ -f .env ]; then
  KEY=$(grep -E '^QWEN_API_KEY=' .env | head -1 | cut -d= -f2-)
fi
if [ -z "${KEY:-}" ]; then
  echo "ERR: no QWEN_API_KEY in .env" >&2
  exit 1
fi

OUT_DIR="$PROJECT_ROOT/output/$CONTENT_ID"
SCRIPT_PATH="$OUT_DIR/chinese_script.md"
if [ ! -f "$SCRIPT_PATH" ]; then
  echo "ERR: chinese_script.md missing at $SCRIPT_PATH" >&2
  exit 1
fi

OUT_AUDIO="$OUT_DIR/voice_dashscope_probe.mp3"
STATUS_JSON="$OUT_DIR/voice_dashscope_probe_status.json"
FFMPEG="$(command -v ffmpeg)"

echo "==> running tts_engine.synthesize_narration ..."
QWEN_API_KEY="$KEY" "$VENV/bin/python" - <<PYEOF
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path("$PROJECT_ROOT").resolve()))
from app.tts_engine import synthesize_narration
from app.media_producer import extract_voiceover_text

script_text = Path("$SCRIPT_PATH").read_text(encoding="utf-8")
voiceover = extract_voiceover_text(script_text)
print(f"voiceover chars: {len(voiceover)}")
print(f"first 80 chars: {voiceover[:80]!r}")

import os
voice_path, status = synthesize_narration(
    voiceover,
    Path("$OUT_AUDIO"),
    ffmpeg="$FFMPEG",
    qwen_api_key=os.environ.get("QWEN_API_KEY"),
    openai_api_key=None,
    force_mock=False,
)

print("voice_path:", voice_path)
print("status:")
print(json.dumps(status, ensure_ascii=False, indent=2))

Path("$STATUS_JSON").write_text(
    json.dumps({"voice_path": str(voice_path), "status": status}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
PYEOF

echo "==> ffprobe on output ..."
ffprobe -v error -show_entries format=duration,size,bit_rate -of default=nw=1 "$OUT_AUDIO"
ls -lh "$OUT_AUDIO" "$STATUS_JSON"
