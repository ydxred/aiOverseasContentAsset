#!/usr/bin/env bash
# Detect scene cuts using metadata mode (more reliable).
set -euo pipefail
VIDEO="${1:?video path required}"
OUT="${2:-$(dirname "$VIDEO")/ref_analysis}"
mkdir -p "$OUT"

META="$OUT/scene_metadata.txt"
echo "[*] computing scene scores -> $META"
ffmpeg -hide_banner -loglevel error -y -i "$VIDEO" \
    -filter:v "select='gte(scene,0)',metadata=print:file=$META" \
    -f null -

echo "[*] head of metadata:"
head -20 "$META"

echo
for threshold in 0.05 0.10 0.20 0.30 0.40; do
    count=$(awk -v t="$threshold" '/scene_score/ { split($0,a,"="); if (a[2]+0 >= t) c++ } END { print c+0 }' "$META")
    echo "threshold $threshold : $count cuts"
done
