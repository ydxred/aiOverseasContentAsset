#!/usr/bin/env bash
# Render a single frame to debug a specific shot.
set -euo pipefail
CONTENT_ID="${1:?content_id required}"
FRAME="${2:?frame number required}"
OUT="${3:-/tmp/single_frame_${FRAME}.png}"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROPS="$PROJECT_ROOT/output/$CONTENT_ID/remotion_props.json"
REMOTION_DIR="$PROJECT_ROOT/video_engine/remotion"

if [ ! -f "$PROPS" ]; then echo "props not found: $PROPS"; exit 1; fi

cd "$REMOTION_DIR"
PROPS_JSON="$(cat "$PROPS")"
npx remotion still src/index.ts DouyinExplainer "$OUT" --props="$PROPS_JSON" --frame="$FRAME" 2>&1
ls -l "$OUT"
echo "[done] $OUT"
