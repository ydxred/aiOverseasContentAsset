#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
RUN="output/quality_smoke_browser_use"
OUT="$RUN/_word_align_review"
mkdir -p "$OUT"
# Frames spaced to land mid-cue across the 26-cue track:
#   0.8s   -> "以前AI只能回答你问题，"  (cue 0: 0.00-2.08)
#   2.5s   -> "现在它开始自己点网页、"  (cue 1: 2.08-3.92)
#   4.5s   -> "填表、找资料了。"        (cue 2: 3.92-5.80)
#   7.0s   -> "最近国外火起来的browser-use"
#   9.0s   -> "GitHub上已经有9.2万star"
#   11.0s  -> "就是这个方向的代表。"
#   13.5s  -> "简单说，以前你要自己点..."
#   16.0s  -> "填表、找信息；"
TIMES=(0.8 2.5 4.5 7.0 9.0 11.0 13.5 16.0 22.0 32.0 42.0 52.0)
for ts in "${TIMES[@]}"; do
  ffmpeg -ss "$ts" -i "$RUN/final_video.mp4" -vframes 1 -q:v 2 "$OUT/frame_${ts}.jpg" -y >/dev/null 2>&1
done
ls -la "$OUT/"
