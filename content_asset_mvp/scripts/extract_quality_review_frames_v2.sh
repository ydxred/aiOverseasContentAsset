#!/usr/bin/env bash
# Extract review frames from a specific video file (default final_video.mp4).
set -euo pipefail
cd "$(dirname "$0")/.."

CONTENT_ID="${1:-quality_smoke_browser_use}"
SRC_NAME="${2:-final_video.mp4}"
SRC="output/${CONTENT_ID}/${SRC_NAME}"
OUT_DIR="output/${CONTENT_ID}/_quality_review_v2"

if [[ ! -f "$SRC" ]]; then
  echo "[quality_review_v2] not found: $SRC" >&2
  exit 2
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

DUR=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$SRC")
echo "[quality_review_v2] source=$SRC duration=${DUR}s"

python3 - "$DUR" <<'PY' > /tmp/_qr_timestamps2
import sys
dur = float(sys.argv[1])
n = 14
start, end = 0.5, max(0.5, dur - 0.5)
step = (end - start) / (n - 1)
for i in range(n):
    print(f"{start + step * i:.2f}")
PY

i=0
mapfile -t TIMESTAMPS < /tmp/_qr_timestamps2
for ts in "${TIMESTAMPS[@]}"; do
  ts="${ts//[$'\r\n\t ']/}"
  [[ -z "$ts" ]] && continue
  i=$((i+1))
  out="$OUT_DIR/$(printf '%02d' $i)_${ts}s.jpg"
  ffmpeg -ss "$ts" -i "$SRC" -frames:v 1 -q:v 2 "$out" -y -loglevel error
done

ls -la "$OUT_DIR"
echo
echo "[quality_review_v2] frames -> $OUT_DIR"
