#!/usr/bin/env bash
# Extract one frame per visual_type (and the cover) from the latest render.
set -euo pipefail
CONTENT_ID="${1:?content_id required}"
RUN_DIR="$(cd "$(dirname "$0")/.." && pwd)/output/$CONTENT_ID"
VIDEO="$RUN_DIR/final_video.mp4"
OUT_DIR="$RUN_DIR/v7_review_frames"
mkdir -p "$OUT_DIR"

declare -a SHOTS=(
    "01_cover|1.5"
    "02_impact_title|5.7"
    "03_repo_full_bleed|11.3"
    "04_keyword_punch|16.7"
    "05_repo_evidence_zoom|28.5"
    "06_readme_visual|38.9"
    "07_keyword_punch_long|54.0"
    "08_judgement|63.2"
)

for entry in "${SHOTS[@]}"; do
    name="${entry%%|*}"
    ts="${entry##*|}"
    out="$OUT_DIR/${name}_${ts}s.jpg"
    ffmpeg -hide_banner -loglevel error -y -ss "$ts" -i "$VIDEO" -frames:v 1 -q:v 2 "$out"
    echo "  $name @ ${ts}s -> $out"
done
ls -l "$OUT_DIR/"
