#!/usr/bin/env bash
# Render 3 still frames to verify the latest polish:
#   - frame 30  : Cover (backdrop drift now hugs the rim)
#   - frame 600 : Repo View (chrome title bar should show github.com/<repoName>)
#   - frame 1300: Variable Spotlight (centered headline, clean centerline)
set -euo pipefail

CONTENT_ID="${1:-quality_smoke_browser_use}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROPS="$PROJECT_ROOT/output/$CONTENT_ID/remotion_props.json"
DEST="$PROJECT_ROOT/output/$CONTENT_ID/_polish2_frames"
REMOTION_DIR="$PROJECT_ROOT/video_engine/remotion"

if [ ! -f "$PROPS" ]; then
  echo "ERR: missing $PROPS" >&2
  exit 1
fi

rm -rf "$DEST" && mkdir -p "$DEST"
cd "$REMOTION_DIR"

for FRAME in 30 600 1300; do
  echo "==> frame $FRAME ..."
  npx remotion still \
    src/index.ts \
    LandscapeExplainer \
    "$DEST/frame_${FRAME}.png" \
    --props="$PROPS" \
    --frame="$FRAME"
done

ls -lh "$DEST"
echo "==> done."
