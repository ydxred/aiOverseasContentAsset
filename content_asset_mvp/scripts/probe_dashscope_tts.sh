#!/usr/bin/env bash
# Smoke test: install dashscope SDK and synthesize one Chinese line.
# Uses QWEN_API_KEY (== DASHSCOPE_API_KEY) from content_asset_mvp/.env.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# Load API key from .env (only the QWEN_API_KEY line).
if [ -f .env ]; then
  KEY=$(grep -E '^QWEN_API_KEY=' .env | head -1 | cut -d= -f2-)
fi

if [ -z "${KEY:-}" ]; then
  echo "ERR: no QWEN_API_KEY in content_asset_mvp/.env" >&2
  exit 1
fi

VENV="${HOME}/venv-content-mvp"
if [ ! -d "$VENV" ]; then
  echo "ERR: linux venv not at $VENV" >&2
  exit 1
fi

echo "==> ensuring dashscope SDK is installed ..."
"$VENV/bin/pip" install -q --upgrade dashscope 2>&1 | tail -3

echo "==> synthesizing one Chinese sentence ..."
OUT="$PROJECT_ROOT/output/_tts_probe.mp3"
mkdir -p "$(dirname "$OUT")"

DASHSCOPE_API_KEY="$KEY" "$VENV/bin/python" - <<PYEOF
import os, sys
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer

dashscope.api_key = os.environ["DASHSCOPE_API_KEY"]

# cosyvoice-v3-flash uses v3 voices. longanyang is the v3 default male.
# (longxiaochun belongs to v1/v2 — pairing it with v3-flash returns code 418.)
model = "cosyvoice-v3-flash"
voice = "longanyang"

text = "以前 AI 只能回答你问题，现在它开始自己点网页、填表、找资料了。"

print(f"model={model} voice={voice}")
print(f"text={text}")

synth = SpeechSynthesizer(model=model, voice=voice)
audio = synth.call(text)

if not audio:
    print("ERR: empty audio bytes returned", file=sys.stderr)
    sys.exit(2)

out = "$OUT"
with open(out, "wb") as f:
    f.write(audio)
print(f"wrote {len(audio)} bytes -> {out}")

req_id = synth.get_last_request_id()
delay = synth.get_first_package_delay()
print(f"request_id={req_id} first_pkg_delay_ms={delay}")
PYEOF

echo "==> ffprobe ..."
ffprobe -v error -show_entries format=duration,size,bit_rate -of default=nw=1 "$OUT"
ls -lh "$OUT"
echo "==> done. play it with: ffplay -autoexit '$OUT'  or copy to Windows side."
