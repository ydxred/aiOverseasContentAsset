#!/usr/bin/env bash
# Benchmark 9p (Windows /mnt/f) vs ext4 (WSL ~) IO performance.
# Simulates Remotion's per-frame PNG output workload.
set -uo pipefail

BENCH_F="/mnt/f/kaifa/OverseasContentAsset Automated Production System/content_asset_mvp/output/_bench"
BENCH_E="$HOME/_bench"

cleanup() {
  rm -rf "$BENCH_F" "$BENCH_E"
}
trap cleanup EXIT

echo "== Bench: 200 PNG-sized writes (Remotion frame-output workload) =="
echo

echo "--- A) /mnt/f/  (Windows F: via 9p) ---"
rm -rf "$BENCH_F"
mkdir -p "$BENCH_F"
time (for i in $(seq 1 200); do
  dd if=/dev/zero of="$BENCH_F/frame_$i.png" bs=300K count=1 status=none
done)
echo

echo "--- B) ~/  (WSL ext4) ---"
rm -rf "$BENCH_E"
mkdir -p "$BENCH_E"
time (for i in $(seq 1 200); do
  dd if=/dev/zero of="$BENCH_E/frame_$i.png" bs=300K count=1 status=none
done)
echo

echo "== Sequential 600 MB write =="
echo
echo "--- C) /mnt/f/ ---"
time dd if=/dev/zero of="$BENCH_F/big.bin" bs=10M count=60 status=none
echo
echo "--- D) ~/ ---"
time dd if=/dev/zero of="$BENCH_E/big.bin" bs=10M count=60 status=none
echo

echo "== Sequential read of the same 600 MB =="
echo
echo "--- E) /mnt/f/ ---"
time dd if="$BENCH_F/big.bin" of=/dev/null bs=10M status=none
echo
echo "--- F) ~/ ---"
time dd if="$BENCH_E/big.bin" of=/dev/null bs=10M status=none
