#!/usr/bin/env bash
# Probe and sample the landscape final_video.mp4 for self-review.
set -euo pipefail

CONTENT_ID="${1:-quality_smoke_browser_use}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VID="$PROJECT_ROOT/output/$CONTENT_ID/platform_renders/bilibili/final_video.mp4"
OUT="$PROJECT_ROOT/output/$CONTENT_ID/landscape_review_frames"

if [ ! -f "$VID" ]; then
  echo "ERR: missing $VID" >&2
  exit 1
fi

echo "==> ffprobe ..."
ffprobe -v error \
  -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate,duration,bit_rate \
  -of default=nw=1 \
  "$VID"

echo "==> file size ..."
ls -lh "$VID"

rm -rf "$OUT" && mkdir -p "$OUT"
echo "==> extracting 8 review frames ..."

declare -a TIMES=( "1.5" "5.5" "12.0" "22.0" "32.0" "42.0" "52.0" "60.0" )
for T in "${TIMES[@]}"; do
  OUT_PNG="$OUT/frame_${T}s.png"
  ffmpeg -hide_banner -loglevel error -y -ss "$T" -i "$VID" -frames:v 1 "$OUT_PNG"
  echo "  - $OUT_PNG"
done

ls -lh "$OUT"
echo "==> done."
