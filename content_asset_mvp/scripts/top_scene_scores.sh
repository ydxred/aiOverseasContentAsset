#!/usr/bin/env bash
set -euo pipefail
META="${1:?metadata file required}"

# Pair each scene_score with the pts_time of its preceding frame line.
python3 - "$META" <<'PY'
import sys, re
path = sys.argv[1]
times = []
prev_t = None
for line in open(path):
    line = line.strip()
    m = re.match(r"frame:\d+\s+pts:\d+\s+pts_time:([0-9.]+)", line)
    if m:
        prev_t = float(m.group(1))
        continue
    m = re.match(r"lavfi\.scene_score=([0-9.]+)", line)
    if m and prev_t is not None:
        times.append((float(m.group(1)), prev_t))
times.sort(reverse=True)
print(f"total frames with score: {len(times)}")
print(f"max score: {times[0][0]:.4f} at t={times[0][1]:.2f}s")
print("top 30 cuts (score, time_seconds):")
for s, t in times[:30]:
    print(f"  {s:.4f}  @ {t:7.2f}s")
PY
