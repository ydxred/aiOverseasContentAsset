#!/usr/bin/env bash
# Re-render the latest run with current Remotion code, reusing existing props.json.
# Skips LLM/asset pipeline.
#
# Speed:
#   - Renders into ``/tmp`` (native ext4 in WSL) instead of straight to /mnt/f/
#     to avoid 9p write amplification on Windows-hosted folders. The final
#     mp4/png is copied back to the run dir at the end.
#   - Reads ``video_engine/remotion/remotion.config.ts`` for jpeg/x264/concurrency
#     defaults; CLI flags can still override anything.
set -euo pipefail

CONTENT_ID="${1:?content_id required}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$PROJECT_ROOT/output/$CONTENT_ID"
PROPS_FILE="$RUN_DIR/remotion_props.json"
REMOTION_DIR="$PROJECT_ROOT/video_engine/remotion"

if [ ! -f "$PROPS_FILE" ]; then
    echo "[!] props file not found: $PROPS_FILE"
    exit 1
fi

PUBLIC_BASE="$REMOTION_DIR/public/render_inputs/$(echo "$CONTENT_ID" | sed 's/[^A-Za-z0-9_-]/_/g')"
mkdir -p "$PUBLIC_BASE"

OUT_VIDEO="$RUN_DIR/platform_renders/douyin/final_video.mp4"
OUT_COVER="$RUN_DIR/platform_renders/douyin/cover.png"
mkdir -p "$(dirname "$OUT_VIDEO")"

# Stage outputs in /tmp so Remotion's many small frame writes hit ext4, not 9p.
TMP_DIR="$(mktemp -d -t remotion-render-XXXXXX)"
TMP_VIDEO="$TMP_DIR/final_video.mp4"
TMP_COVER="$TMP_DIR/cover.png"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$REMOTION_DIR"

START_TS=$(date +%s)
echo "[1/2] one-shot bundle + render via Node API"
node scripts/render_pipeline.mjs \
  --composition DouyinExplainer \
  --props "$PROPS_FILE" \
  --out "$TMP_VIDEO" \
  --cover "$TMP_COVER" \
  --cover-frame 30
RENDER_TS=$(date +%s)
echo "    render+still took $((RENDER_TS - START_TS))s"

echo "[2/2] copy back to /mnt/f/ outputs"
cp -f "$TMP_VIDEO" "$OUT_VIDEO"
cp -f "$TMP_COVER" "$OUT_COVER"
cp -f "$OUT_VIDEO" "$RUN_DIR/final_video.mp4"
cp -f "$OUT_COVER" "$RUN_DIR/cover.png"
COPY_TS=$(date +%s)
echo "    copy-back took $((COPY_TS - RENDER_TS))s"

ls -lh "$OUT_VIDEO" "$RUN_DIR/final_video.mp4"
echo "[done] total $((COPY_TS - START_TS))s -> $OUT_VIDEO"
