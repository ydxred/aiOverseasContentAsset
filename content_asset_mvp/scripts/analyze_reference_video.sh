#!/usr/bin/env bash
# Analyze a reference video: probe metadata, sample frames, extract audio waveform.
# Usage: ./analyze_reference_video.sh <video_path> [out_dir]

set -euo pipefail

VIDEO="${1:?video path required}"
OUT="${2:-$(dirname "$VIDEO")/ref_analysis}"

mkdir -p "$OUT/frames"

echo "[1/4] ffprobe metadata"
ffprobe -v error \
    -show_entries 'format=duration,bit_rate,size,format_name : stream=codec_type,codec_name,width,height,r_frame_rate,bit_rate,sample_rate,channels' \
    -of json "$VIDEO" > "$OUT/metadata.json"

DURATION_INT=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO" | awk -F. '{print $1}')

echo "[2/4] sample frames (every 8s, plus first/last)"
TS_LIST=(1)
T=8
while [ "$T" -lt "$DURATION_INT" ]; do
    TS_LIST+=("$T")
    T=$((T + 8))
done
TS_LIST+=("$((DURATION_INT - 1))")

for ts in "${TS_LIST[@]}"; do
    fname=$(printf "frame_%04ds.jpg" "$ts")
    ffmpeg -hide_banner -loglevel error -y -ss "$ts" -i "$VIDEO" \
        -frames:v 1 -q:v 2 "$OUT/frames/$fname"
done

echo "[3/4] extract audio mono 16k"
ffmpeg -hide_banner -loglevel error -y -i "$VIDEO" \
    -vn -ac 1 -ar 16000 -c:a pcm_s16le "$OUT/audio.wav"

echo "[4/4] scene detection (cut points >=0.4 confidence)"
ffmpeg -hide_banner -loglevel info -i "$VIDEO" \
    -filter:v "select='gt(scene,0.4)',showinfo" -f null - 2>&1 \
    | grep -E "showinfo.*pts_time" \
    | sed -E 's/.*pts_time:([0-9.]+).*/\1/' \
    > "$OUT/scene_cuts.txt" || true

echo
echo "=== summary ==="
echo "metadata: $OUT/metadata.json"
echo "frames:   $OUT/frames/  ($(ls "$OUT/frames" | wc -l) files)"
echo "audio:    $OUT/audio.wav  ($(du -h "$OUT/audio.wav" | cut -f1))"
echo "cuts:     $OUT/scene_cuts.txt  ($(wc -l < "$OUT/scene_cuts.txt") cut points)"
