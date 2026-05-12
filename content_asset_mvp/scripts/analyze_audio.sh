#!/usr/bin/env bash
# Analyze audio: loudness, silence, volume profile.
set -euo pipefail
WAV="${1:?wav path required}"
OUT="$(dirname "$WAV")"

echo "=== EBU R128 loudness ==="
ffmpeg -hide_banner -nostats -i "$WAV" \
    -filter:a ebur128=peak=true -f null - 2>&1 \
    | tail -25

echo
echo "=== silence detect (threshold -35dB, min 0.5s) ==="
ffmpeg -hide_banner -nostats -i "$WAV" \
    -af silencedetect=noise=-35dB:d=0.5 -f null - 2>&1 \
    | grep -E 'silence_(start|end)' | head -40

echo
echo "=== mean / max volume ==="
ffmpeg -hide_banner -nostats -i "$WAV" -filter:a volumedetect -f null - 2>&1 \
    | grep -E 'mean|max|histogram' | head -10
