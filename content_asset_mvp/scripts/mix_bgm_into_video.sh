#!/usr/bin/env bash
# Mix a BGM track into a rendered video.
#
# Usage: ./mix_bgm_into_video.sh <input_video> <bgm_file> [output_video]
#
# Pipeline:
#   1. Trim BGM to video duration with 0.6s fade-in / 1.4s fade-out.
#   2. Mix BGM with the video's existing audio track (voice, if present).
#      - BGM weight 1.0, voice weight 1.5 (voice always wins when present).
#      - When voice is loud (>-30 dB), sidechain ducks BGM by ~6 dB.
#   3. Loudness normalize whole audio to -14 LUFS / true peak -1 dBTP
#      (Douyin / B站 / YouTube投放标准).
#   4. Re-encode AAC 192k stereo, copy video stream.
set -euo pipefail

INPUT="${1:?input video required}"
BGM="${2:?bgm file required}"
OUT="${3:-}"

if [ -z "$OUT" ]; then
    base="${INPUT%.*}"
    OUT="${base}_with_bgm.mp4"
fi

TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

# Probe video duration.
DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$INPUT")
echo "[1/3] video duration = ${DURATION}s"
echo "       BGM source     = $BGM"
echo "       output         = $OUT"

# Detect whether the input has any non-silent audio.
HAS_VOICE=0
MEAN_VOL=$(ffmpeg -hide_banner -nostats -i "$INPUT" -filter:a volumedetect -f null - 2>&1 \
    | sed -nE 's/.*mean_volume:\s*(-?[0-9]+(\.[0-9]+)?).*/\1/p' \
    | head -1)
MEAN_VOL="${MEAN_VOL:--100}"
echo "[2/3] input mean_volume = ${MEAN_VOL} dB"
# If mean_volume above -60 dB, treat as a real voice track.
if awk "BEGIN { exit !(${MEAN_VOL} > -60) }"; then
    HAS_VOICE=1
    echo "       voice track detected -> sidechain duck BGM"
else
    echo "       voice track is silent -> BGM as sole audio"
fi

# Trim+fade BGM to exact video length.
BGM_TRIMMED="$TMP/bgm_trimmed.wav"
FADE_OUT_START=$(awk "BEGIN { printf \"%.3f\", ${DURATION} - 1.4 }")
ffmpeg -hide_banner -loglevel error -y -i "$BGM" \
    -af "afade=t=in:st=0:d=0.6,afade=t=out:st=${FADE_OUT_START}:d=1.4" \
    -t "$DURATION" -ar 48000 -ac 2 -c:a pcm_s16le "$BGM_TRIMMED"

if [ "$HAS_VOICE" = "1" ]; then
    # BGM + voice with sidechain compression.
    # voice -> through; BGM -> ducked by sidechaincompress
    ffmpeg -hide_banner -loglevel error -y \
        -i "$INPUT" -i "$BGM_TRIMMED" \
        -filter_complex "
            [0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=1.5[voice];
            [1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=0.85[bgm];
            [voice]asplit=2[v_main][v_key];
            [bgm][v_key]sidechaincompress=threshold=0.08:ratio=4:attack=20:release=350[bgm_d];
            [v_main][bgm_d]amix=inputs=2:weights='1.5 1':normalize=0,
            loudnorm=I=-14:TP=-1:LRA=11[mix]
        " \
        -map 0:v -map "[mix]" -c:v copy -c:a aac -b:a 192k -ar 48000 -ac 2 -shortest "$OUT"
else
    # BGM only.
    ffmpeg -hide_banner -loglevel error -y \
        -i "$INPUT" -i "$BGM_TRIMMED" \
        -filter_complex "
            [1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,
                 volume=1.0,
                 loudnorm=I=-14:TP=-1:LRA=11[mix]
        " \
        -map 0:v -map "[mix]" -c:v copy -c:a aac -b:a 192k -ar 48000 -ac 2 -shortest "$OUT"
fi

echo "[3/3] verifying output loudness"
ffmpeg -hide_banner -nostats -i "$OUT" -filter:a ebur128 -f null - 2>&1 | tail -8 | head -7

ls -lh "$OUT"
echo "[done] $OUT"
