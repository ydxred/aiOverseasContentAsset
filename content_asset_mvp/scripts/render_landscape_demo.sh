#!/usr/bin/env bash
# Render the LandscapeExplainer composition (1920x1080) using the props from
# a previously rendered portrait pipeline.
#
# Usage:
#   bash scripts/render_landscape_demo.sh [content_id]
#
# Defaults to ``quality_smoke_browser_use`` because that's the latest reference
# render in the repo. Output goes to:
#   content_asset_mvp/output/<content_id>/platform_renders/bilibili/final_video.mp4
set -euo pipefail

CONTENT_ID="${1:-quality_smoke_browser_use}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="$PROJECT_ROOT/output/$CONTENT_ID"
PROPS="$OUTPUT_DIR/remotion_props.json"
REMOTION_DIR="$PROJECT_ROOT/video_engine/remotion"

if [ ! -f "$PROPS" ]; then
  echo "ERR: props not found: $PROPS" >&2
  exit 1
fi

DEST_DIR="$OUTPUT_DIR/platform_renders/bilibili"
mkdir -p "$DEST_DIR"
DEST_MP4="$DEST_DIR/final_video.mp4"
DEST_PNG="$DEST_DIR/cover.png"

cd "$REMOTION_DIR"
echo "==> rendering landscape ($CONTENT_ID) ..."
npx remotion render \
  src/index.ts \
  LandscapeExplainer \
  "$DEST_MP4" \
  --props="$PROPS"

echo "==> rendering landscape cover (frame 30) ..."
npx remotion still \
  src/index.ts \
  LandscapeExplainer \
  "$DEST_PNG" \
  --props="$PROPS" \
  --frame=30

ls -lh "$DEST_MP4" "$DEST_PNG"
echo "==> done."
