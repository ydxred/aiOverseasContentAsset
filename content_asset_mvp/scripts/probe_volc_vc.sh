#!/usr/bin/env bash
# Smoke test for Volcengine 音视频字幕生成 (Subtitle Generation, vc/submit).
# Different from ATA: this transcribes audio → subtitle directly (no text input
# required), and gives you per-word/per-utterance timestamps.
#
# Endpoint:
#   POST https://openspeech.bytedance.com/api/v1/vc/submit?appid=APPID&...
#   GET  https://openspeech.bytedance.com/api/v1/vc/query?appid=APPID&id=TASK_ID
# Auth: ``Authorization: Bearer; <access_token>``

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
  echo "[probe_volc_vc] VOLC_APPID + VOLC_ACCESS_TOKEN required in .env" >&2
  exit 2
fi
if [[ ! -f "${AUDIO_PATH}" ]]; then
  echo "[probe_volc_vc] audio not found: ${AUDIO_PATH}" >&2
  exit 2
fi

OUT_DIR="output/_probe"
mkdir -p "$OUT_DIR"

echo "[probe_volc_vc] audio = $AUDIO_PATH ($(stat -c%s "$AUDIO_PATH") bytes)"
echo "[probe_volc_vc] appid = $APPID"
echo

SUBMIT_URL="https://openspeech.bytedance.com/api/v1/vc/submit?appid=${APPID}&language=zh-CN&use_itn=True&use_capitalize=True&max_lines=1&words_per_line=15"
SUBMIT_RESP="$OUT_DIR/volc_vc_submit.json"

echo "[probe_volc_vc] submitting..."
curl -sS -X POST "$SUBMIT_URL" \
  -H "Authorization: Bearer;${TOKEN}" \
  -H "Content-Type: audio/mpeg" \
  --data-binary @"$AUDIO_PATH" \
  -o "$SUBMIT_RESP" \
  -w "submit_http=%{http_code} time=%{time_total}s\n"

echo "--- submit response ---"
cat "$SUBMIT_RESP"
echo
echo

TASK_ID=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("id") or "")' "$SUBMIT_RESP" 2>/dev/null)

if [[ -z "${TASK_ID}" ]]; then
  echo "[probe_volc_vc] no task_id; aborting" >&2
  exit 1
fi
echo "[probe_volc_vc] task_id = $TASK_ID"
echo

QUERY_URL="https://openspeech.bytedance.com/api/v1/vc/query?appid=${APPID}&id=${TASK_ID}"
QUERY_RESP="$OUT_DIR/volc_vc_query.json"

for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  sleep 3
  curl -sS -X GET "$QUERY_URL" \
    -H "Authorization: Bearer;${TOKEN}" \
    -o "$QUERY_RESP" \
    -w "query_http=%{http_code} attempt=$attempt "

  STATE=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("code="+str(d.get("code")), "msg="+str(d.get("message")))' "$QUERY_RESP" 2>/dev/null || echo "parse_error")
  echo "$STATE"
  if echo "$STATE" | grep -qE 'code=(0|1000)\b'; then
    break
  fi
done

echo
echo "--- query response ---"
python3 - "$QUERY_RESP" <<'PY'
import json, sys, pathlib
data = json.loads(pathlib.Path(sys.argv[1]).read_text())
print(f"top-level keys: {list(data.keys())}")
if isinstance(data.get("utterances"), list):
    utts = data["utterances"]
    print(f"\nutterances: {len(utts)}")
    for u in utts[:3]:
        kept = {k: u.get(k) for k in ("start_time", "end_time", "text") if k in u}
        words = u.get("words")
        if isinstance(words, list):
            kept["words[:3]"] = words[:3]
            kept["word_count"] = len(words)
        print(json.dumps(kept, ensure_ascii=False))
    print(f"\ntotal words across all utterances: {sum(len(u.get('words') or []) for u in utts)}")
else:
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
PY
