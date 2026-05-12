#!/usr/bin/env bash
# Smoke test for OpenAI Whisper word-level timestamps via verbose_json.
#
# Curl form: POST /v1/audio/transcriptions with multipart
#   file=@audio.mp3
#   model=whisper-1
#   response_format=verbose_json
#   timestamp_granularities[]=word
#   timestamp_granularities[]=segment
#   language=zh
#
# Returns ``words: [{word, start, end}]`` and ``segments: [{...}]``.

set -uo pipefail
cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
source .env
set +a

KEY="${OPENAI_API_KEY:-}"
AUDIO_PATH="${1:-output/quality_smoke_browser_use/voice.mp3}"

if [[ -z "${KEY}" ]]; then
  echo "[probe_whisper] OPENAI_API_KEY required" >&2
  exit 2
fi
if [[ ! -f "${AUDIO_PATH}" ]]; then
  echo "[probe_whisper] audio not found: ${AUDIO_PATH}" >&2
  exit 2
fi

OUT_DIR="output/_probe"
mkdir -p "$OUT_DIR"
RESP="$OUT_DIR/whisper_word_timestamps.json"

echo "[probe_whisper] audio = $AUDIO_PATH ($(stat -c%s "$AUDIO_PATH") bytes)"
echo "[probe_whisper] calling OpenAI..."

curl -sS https://api.openai.com/v1/audio/transcriptions \
  -H "Authorization: Bearer ${KEY}" \
  -F "file=@${AUDIO_PATH}" \
  -F "model=whisper-1" \
  -F "response_format=verbose_json" \
  -F "timestamp_granularities[]=word" \
  -F "timestamp_granularities[]=segment" \
  -F "language=zh" \
  -o "$RESP" \
  -w "http=%{http_code} time=%{time_total}s size=%{size_download}\n"

echo
python3 - "$RESP" <<'PY'
import json, pathlib, sys
data = json.loads(pathlib.Path(sys.argv[1]).read_text())
print(f"top-level keys: {list(data.keys())}")
print(f"language: {data.get('language')}")
print(f"duration: {data.get('duration')} s")
words = data.get("words") or []
segments = data.get("segments") or []
print(f"\nword-level entries: {len(words)}")
for w in words[:8]:
    print(f"  {w.get('start'):.3f}s - {w.get('end'):.3f}s  '{w.get('word')}'")
print(f"...({len(words)} total)")
print(f"\nsegment-level entries: {len(segments)}")
for s in segments[:3]:
    print(f"  {s.get('start'):.2f}s - {s.get('end'):.2f}s  '{(s.get('text') or '')[:40]}...'")
PY
