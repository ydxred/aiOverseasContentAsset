#!/usr/bin/env bash
# Smoke test for Volcengine 自动字幕打轴 (ATA / Auto Time Alignment).
#
# Endpoint:
#   POST   http://openspeech.bytedance.com/api/v1/vc/ata/submit?appid=APPID&caption_type=speech
#   GET    https://openspeech.bytedance.com/api/v1/vc/ata/query?appid=APPID&id=TASK_ID
# Auth: ``Authorization: Bearer; <access_token>``
#
# We use the binary multipart form: stream local audio + correct text. The
# server returns { id: <task_id>, code: 0, message: "Success" }, after which
# we poll /query until code is final.

set -uo pipefail
cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
source .env
set +a

APPID="${VOLC_APPID:-}"
TOKEN="${VOLC_ACCESS_TOKEN:-}"
AUDIO_PATH="${1:-output/quality_smoke_browser_use/voice.mp3}"
TEXT_PATH="${2:-}"

if [[ -z "${APPID}" || -z "${TOKEN}" ]]; then
  echo "[probe_volc_ata] VOLC_APPID + VOLC_ACCESS_TOKEN required in .env" >&2
  exit 2
fi
if [[ ! -f "${AUDIO_PATH}" ]]; then
  echo "[probe_volc_ata] audio not found: ${AUDIO_PATH}" >&2
  exit 2
fi

OUT_DIR="output/_probe"
mkdir -p "$OUT_DIR"

# Resolve the script text. If TEXT_PATH not given, pull voiceover from the
# chinese_script.md sitting next to the audio (works for our pipeline).
if [[ -z "${TEXT_PATH}" ]]; then
  RUN_DIR="$(dirname "$AUDIO_PATH")"
  TEXT_PATH="$RUN_DIR/chinese_script.md"
fi
if [[ ! -f "$TEXT_PATH" ]]; then
  echo "[probe_volc_ata] script not found: $TEXT_PATH" >&2
  exit 2
fi

# Strip markdown headings + frontmatter, keep only voiceover plain text.
SCRIPT_TEXT=$(python3 - "$TEXT_PATH" <<'PY'
import re, sys, pathlib
raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
# Pull only the # 口播稿 section (matches our writer convention).
m = re.search(r"#\s*口播稿\s*\n(.*?)(?:\n#\s|\Z)", raw, re.S)
body = m.group(1) if m else raw
# Remove markdown bold/italic, list bullets, and quote prefixes.
body = re.sub(r"^[\-\*\>\s]+", "", body, flags=re.M)
body = re.sub(r"\*+", "", body)
body = body.replace("\r", "").strip()
sys.stdout.write(body)
PY
)

if [[ -z "${SCRIPT_TEXT}" ]]; then
  echo "[probe_volc_ata] could not extract script text from $TEXT_PATH" >&2
  exit 2
fi

echo "[probe_volc_ata] audio  = $AUDIO_PATH ($(stat -c%s "$AUDIO_PATH") bytes)"
echo "[probe_volc_ata] script = $TEXT_PATH (${#SCRIPT_TEXT} chars)"
echo "[probe_volc_ata] appid  = $APPID"
echo

# 1) Submit (multipart binary)
SUBMIT_URL="https://openspeech.bytedance.com/api/v1/vc/ata/submit?appid=${APPID}&caption_type=speech"
SUBMIT_RESP="$OUT_DIR/volc_ata_submit.json"

# Use a temp file for the script text (keeps multipart simple).
TMP_TEXT="$OUT_DIR/_ata_text.txt"
printf '%s' "$SCRIPT_TEXT" > "$TMP_TEXT"

echo "[probe_volc_ata] submitting..."
curl -sS -X POST "$SUBMIT_URL" \
  -H "Authorization: Bearer;${TOKEN}" \
  -F "data=@${AUDIO_PATH};type=audio/mpeg" \
  -F "audio-text=<${TMP_TEXT}" \
  -o "$SUBMIT_RESP" \
  -w "submit_http=%{http_code} time=%{time_total}s\n"

echo "--- submit response ---"
cat "$SUBMIT_RESP"
echo
echo

TASK_ID=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("id") or d.get("task_id") or "")' "$SUBMIT_RESP")

if [[ -z "${TASK_ID}" ]]; then
  echo "[probe_volc_ata] submit did not return id; aborting" >&2
  exit 1
fi
echo "[probe_volc_ata] task_id = $TASK_ID"
echo

# 2) Poll query (typically <10s for ~1min audio).
QUERY_URL="https://openspeech.bytedance.com/api/v1/vc/ata/query?appid=${APPID}&id=${TASK_ID}"
QUERY_RESP="$OUT_DIR/volc_ata_query.json"

for attempt in 1 2 3 4 5 6 7 8 9 10; do
  sleep 3
  curl -sS -X GET "$QUERY_URL" \
    -H "Authorization: Bearer;${TOKEN}" \
    -o "$QUERY_RESP" \
    -w "query_http=%{http_code} attempt=$attempt\n"

  STATE=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("code"), d.get("message"))' "$QUERY_RESP" 2>/dev/null || echo "parse_error")
  echo "  state: $STATE"
  if echo "$STATE" | grep -qE '^(0|1000)'; then
    echo "[probe_volc_ata] result ready"
    break
  fi
done

echo
echo "--- query response (truncated to 4 KB) ---"
python3 - "$QUERY_RESP" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
data = json.loads(p.read_text())
# Compact summary if utterances present.
if isinstance(data, dict) and isinstance(data.get("utterances"), list):
    utts = data["utterances"]
    print(f"utterances={len(utts)} first 3:")
    for u in utts[:3]:
        print(json.dumps(u, ensure_ascii=False)[:300])
    print("...")
    print(f"total chars in alignment: {sum(len(u.get('text','')) for u in utts)}")
elif isinstance(data, dict) and isinstance(data.get("data"), dict):
    print(json.dumps({k: ('<...>' if isinstance(v,(list,dict)) and len(json.dumps(v))>2000 else v) for k,v in data['data'].items()}, ensure_ascii=False, indent=2)[:4000])
else:
    print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
PY
