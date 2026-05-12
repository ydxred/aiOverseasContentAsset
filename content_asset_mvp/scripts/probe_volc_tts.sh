#!/usr/bin/env bash
# Smoke test for Volcengine Doubao TTS 2.0 (BigTTS)
# Usage: VOLC_TTS_APPID=xxxx VOLC_TTS_ACCESS_TOKEN=yyyy bash scripts/probe_volc_tts.sh
#   if VOLC_TTS_APPID is empty we still hit the endpoint to see what the
#   server complains about, which tells us what the required fields are.

set -uo pipefail

APPID="${VOLC_APPID:-${VOLC_TTS_APPID:-}}"
TOKEN="${VOLC_ACCESS_TOKEN:-${VOLC_TTS_ACCESS_TOKEN:-}}"
CLUSTER="${VOLC_TTS_CLUSTER:-volcano_tts}"
VOICE="${VOLC_TTS_VOICE:-zh_male_M392_conversation_wvae_bigtts}"
TEXT="${VOLC_TTS_TEXT:-火山引擎豆包语音合成2.0测试。这是一段中文播报，用来验证音色、语速、停顿是否自然。}"

if [[ -z "${TOKEN}" ]]; then
  echo "[probe_volc_tts] VOLC_TTS_ACCESS_TOKEN is required" >&2
  exit 2
fi

REQID=$(python3 - <<'PY'
import uuid
print(uuid.uuid4().hex)
PY
)

OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/output/_probe"
mkdir -p "$OUT_DIR"
RESP_JSON="$OUT_DIR/volc_tts_probe.json"
DEBUG_LOG="$OUT_DIR/volc_tts_probe.log"

cat > "$OUT_DIR/volc_tts_payload.json" <<JSON
{
  "app": {
    "appid": "${APPID}",
    "token": "${TOKEN}",
    "cluster": "${CLUSTER}"
  },
  "user": {
    "uid": "content_asset_probe"
  },
  "audio": {
    "voice_type": "${VOICE}",
    "encoding": "mp3",
    "speed_ratio": 1.0
  },
  "request": {
    "reqid": "${REQID}",
    "text": "${TEXT}",
    "operation": "query"
  }
}
JSON

echo "[probe_volc_tts] Hitting openspeech.bytedance.com (appid='${APPID:-<empty>}')..."

curl -sS -X POST "https://openspeech.bytedance.com/api/v1/tts" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer;${TOKEN}" \
  --data-binary @"$OUT_DIR/volc_tts_payload.json" \
  -o "$RESP_JSON" \
  -w "http_code=%{http_code} time=%{time_total}s size=%{size_download}\n" \
  2> "$DEBUG_LOG"

EXIT=$?

echo
echo "[probe_volc_tts] curl exit=$EXIT"
echo "[probe_volc_tts] response saved to $RESP_JSON"
echo

# Pretty print the JSON header and decode the base64 audio if present.
python3 - "$RESP_JSON" "$OUT_DIR" <<'PY'
import base64, json, sys, pathlib
p = pathlib.Path(sys.argv[1])
out_dir = pathlib.Path(sys.argv[2])
if not p.exists() or p.stat().st_size == 0:
    print("[probe_volc_tts] empty body")
    sys.exit(0)
try:
    data = json.loads(p.read_text())
except Exception as e:
    print(f"[probe_volc_tts] non-JSON body: {e}")
    print(p.read_text()[:500])
    sys.exit(0)

audio_b64 = data.get("data") if isinstance(data, dict) else None
audio_len = len(audio_b64) if isinstance(audio_b64, str) else 0
if audio_len:
    audio_bytes = base64.b64decode(audio_b64)
    mp3_path = out_dir / "volc_tts_sample.mp3"
    mp3_path.write_bytes(audio_bytes)
    redacted = {**data, "data": f"<base64 {audio_len} chars>"}
    print(json.dumps(redacted, ensure_ascii=False, indent=2))
    print(f"\n[probe_volc_tts] mp3 written: {mp3_path} ({len(audio_bytes)} bytes)")
else:
    print(json.dumps(data, ensure_ascii=False, indent=2))
PY
