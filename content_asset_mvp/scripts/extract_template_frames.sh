#!/usr/bin/env bash
# Extract one frame per visual_type from final_video.mp4 for visual review.
set -euo pipefail
PKG="${1:?usage: extract_template_frames.sh <package-dir-relative-to-content_asset_mvp>}"
cd "$(dirname "$0")/.."
VIDEO="$PKG/final_video.mp4"
OUT="$PKG/template_review_frames"
mkdir -p "$OUT"

# timestamp(real video seconds) | visual_type label
extract() {
  local ts="$1"; local label="$2"
  ffmpeg -hide_banner -loglevel error -y \
    -ss "$ts" -i "$VIDEO" \
    -frames:v 1 -q:v 2 \
    "$OUT/${label}.jpg"
  echo "  $label  @ ${ts}s"
}

echo "writing frames to $OUT"
extract 5.75  "01_impact_title_card"
extract 11.25 "02_repo_full_bleed"
extract 16.75 "03_keyword_punch_card"
extract 28.50 "04_repo_evidence_zoom"
extract 38.95 "05_readme_visual_card"
extract 63.20 "06_judgement_card"
echo "done."
