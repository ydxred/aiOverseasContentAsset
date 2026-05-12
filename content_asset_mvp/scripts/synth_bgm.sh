#!/usr/bin/env bash
# Synthesize an AI-Lab-Terminal-style ambient BGM with ffmpeg lavfi.
# Layers:
#   1. Low drone (sine 55Hz + 110Hz)
#   2. Mid pad (sine 220Hz with slow tremolo)
#   3. High texture (filtered brown noise, slow LFO)
#   4. Ticking perc (gated noise burst at slow tempo for "lab"/"step" feel)
# Output: stereo wav + mp3, looped for 180 seconds (covers most short videos).
set -euo pipefail

OUT_DIR="${1:?out_dir required}"
DURATION="${2:-180}"
mkdir -p "$OUT_DIR"
WAV="$OUT_DIR/ai_lab_ambient.wav"
MP3="$OUT_DIR/ai_lab_ambient.mp3"

echo "[1/2] synthesizing $DURATION s ambient BGM -> $WAV"
ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -t "$DURATION" -i "sine=frequency=55" \
  -f lavfi -t "$DURATION" -i "sine=frequency=110" \
  -f lavfi -t "$DURATION" -i "sine=frequency=220" \
  -f lavfi -t "$DURATION" -i "anoisesrc=color=brown:amplitude=0.25" \
  -f lavfi -t "$DURATION" -i "anoisesrc=color=pink:amplitude=0.15" \
  -filter_complex "
    [0:a]volume=0.22[d1];
    [1:a]volume=0.12[d2];
    [2:a]volume=0.08,tremolo=f=0.18:d=0.7[pad];
    [3:a]bandpass=f=900:width_type=h:w=1400,volume=0.20[tex_low];
    [4:a]highpass=f=2400,bandpass=f=3500:width_type=h:w=2200,volume=0.06[tex_high];
    [d1][d2][pad][tex_low][tex_high]amix=inputs=5:weights='1 1 1 1 1':normalize=0[mix];
    [mix]aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo,
         volume=0.85,
         lowpass=f=8000,
         highpass=f=40[stereo]
  " \
  -map "[stereo]" -ac 2 -ar 48000 -c:a pcm_s16le "$WAV"

echo "[2/2] encoding mp3 -> $MP3"
ffmpeg -hide_banner -loglevel error -y -i "$WAV" -c:a libmp3lame -q:a 2 "$MP3"

ls -lh "$WAV" "$MP3"
ffprobe -v error -show_entries format=duration,bit_rate -of json "$MP3"
