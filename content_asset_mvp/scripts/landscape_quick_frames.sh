#!/usr/bin/env bash
# Quickly render 4 representative still frames from LandscapeExplainer to
# verify the visual layout BEFORE doing a full ~60s render. Each still takes
# ~10-15s vs ~3-5min for the full video.
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

DEST_DIR="$OUTPUT_DIR/landscape_quick_frames"
rm -rf "$DEST_DIR" && mkdir -p "$DEST_DIR"

cd "$REMOTION_DIR"
# Picked to cover every landscape shot variant for visual review:
#   30   = mid cover (Cover)
#   180  = ~6s   first text shot (Definition)
#   500  = ~17s  Variable spotlight
#   900  = ~30s  Repo full bleed
#   1300 = ~43s  Evidence zoom
#   1500 = ~50s  README cell
#   1800 = ~60s  Assertion / final
for FRAME in 30 180 500 900 1300 1500 1800; do
  OUT="$DEST_DIR/frame_${FRAME}.png"
  echo "==> rendering frame $FRAME ..."
  npx remotion still \
    src/index.ts \
    LandscapeExplainer \
    "$OUT" \
    --props="$PROPS" \
    --frame="$FRAME"
done

ls -lh "$DEST_DIR"
echo "==> done. Open the PNGs to inspect layout."
