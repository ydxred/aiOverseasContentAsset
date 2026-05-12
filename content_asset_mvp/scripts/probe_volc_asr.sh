#!/usr/bin/env bash
# Smoke test for Volcengine 大模型录音文件识别 (ASR / 字幕打轴).
#
# Endpoint: POST https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit
# Auth header: ``Authorization: Bearer; <access_token>`` (semicolon, same as TTS).
# Submits an audio URL and returns a task_id, then polls for result.
#
# Usage:
#   bash scripts/probe_volc_asr.sh [path/to/audio.mp3]
#   # default: voice.mp3 from quality_smoke_browser_use

set -uo pipefail
cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
source .env
set +a

APPID="${VOLC_APPID:-}"
TOKEN="${VOLC_ACCESS_TOKEN:-}"
AUDIO_PATH="${1:-output/quality_smoke_browser_use/voice.mp3}"

if [[ -z "${APPID}" || -z "${TOKEN}" ]]; then
  echo "[probe_volc_asr] VOLC_APPID + VOLC_ACCESS_TOKEN required in .env" >&2
  exit 2
fi
if [[ ! -f "${AUDIO_PATH}" ]]; then
  echo "[probe_volc_asr] audio file not found: ${AUDIO_PATH}" >&2
  exit 2
fi

OUT_DIR="output/_probe"
mkdir -p "$OUT_DIR"

REQID=$(python3 -c 'import uuid; print(uuid.uuid4().hex)')
B64_PATH="$OUT_DIR/_audio.b64"
base64 -w0 "$AUDIO_PATH" > "$B64_PATH"
B64_LEN=$(wc -c < "$B64_PATH")

# Newer Volcengine "大模型录音文件识别" expects the request as JSON with
# audio URL. For local audio we use the older "auc/submit" v1 form which
# accepts base64. We'll try v3 first, fall back to v1.

PAYLOAD_PATH="$OUT_DIR/_volc_asr_payload.json"
python3 - "$REQID" "$APPID" "$AUDIO_PATH" "$PAYLOAD_PATH" <<'PY'
import base64, json, sys, pathlib
reqid, appid, audio_path, out_path = sys.argv[1:5]
audio_b64 = base64.b64encode(pathlib.Path(audio_path).read_bytes()).decode()
payload = {
    "app": {"appid": appid, "token": "placeholder", "cluster": "volc_auc_common"},
    "user": {"uid": "content_asset_probe"},
    "audio": {"format": "mp3", "rate": 16000, "channel": 1, "data": audio_b64},
    "request": {
        "reqid": reqid,
        "show_utterances": True,
        "enable_punc": True,
        "show_word_info": True,
    },
}
pathlib.Path(out_path).write_text(json.dumps(payload, ensure_ascii=False))
print(f"payload written: {out_path} ({len(json.dumps(payload))} bytes)")
PY

echo "[probe_volc_asr] submitting..."

RESP_PATH="$OUT_DIR/volc_asr_submit.json"
HTTP_INFO=$(curl -sS -X POST "https://openspeech.bytedance.com/api/v1/auc/submit" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer;${TOKEN}" \
  --data-binary @"$PAYLOAD_PATH" \
  -o "$RESP_PATH" \
  -w "http=%{http_code} time=%{time_total}s size=%{size_download}\n")

echo "[probe_volc_asr] $HTTP_INFO"

python3 - "$RESP_PATH" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
if not p.exists() or p.stat().st_size == 0:
    print("[probe_volc_asr] empty body")
    sys.exit(0)
try:
    data = json.loads(p.read_text())
except Exception as e:
    print(f"[probe_volc_asr] non-JSON: {e}")
    print(p.read_text()[:500])
    sys.exit(0)
print(json.dumps(data, ensure_ascii=False, indent=2))
PY
