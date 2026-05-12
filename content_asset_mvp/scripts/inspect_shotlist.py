"""Inspect shot_list visual types and time ranges for a rendered package."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: inspect_shotlist.py <package-dir>")
        return 2
    package_dir = Path(sys.argv[1])
    shot_list = json.loads((package_dir / "shot_list.json").read_text(encoding="utf-8"))
    review = json.loads((package_dir / "video_self_review.json").read_text(encoding="utf-8"))

    shots = shot_list.get("shots", []) or []
    timestamps = []
    for frame in review.get("frames", []):
        try:
            timestamps.append(float(Path(frame["path"]).stem.split("_")[-1]))
        except Exception:
            timestamps.append(None)

    print(f"shot count: {len(shots)}")
    seen_types: dict[str, int] = {}
    for shot in shots:
        seen_types[shot.get("visual_type", "?")] = seen_types.get(shot.get("visual_type", "?"), 0) + 1
        print(
            f"  shot {shot.get('shot_id', '?')}: {float(shot.get('start', 0)):>5.1f}-{float(shot.get('end', 0)):<5.1f} "
            f"[{shot.get('visual_type'):<22}] {shot.get('screen_text')!r}"
        )
    print(f"visual_type counts: {seen_types}")

    print()
    print("review frame coverage:")
    duration = float(json.loads((package_dir / "render_status.json").read_text(encoding="utf-8")).get("duration_seconds", 0))
    for index, ratio in enumerate((0.12, 0.5, 0.88), start=1):
        timestamp = max(0.1, duration * ratio)
        directorTimestamp = max(0.0, timestamp - 3.0)  # cover sequence runs 0-3s
        match = next(
            (
                shot for shot in shots
                if float(shot.get("start", 0)) <= directorTimestamp <= float(shot.get("end", 0))
            ),
            None,
        )
        if match:
            print(
                f"  frame_{index:02d} @ {timestamp:.2f}s -> shot {match.get('shot_id')} "
                f"({match.get('visual_type')}) screen_text={match.get('screen_text')!r}"
            )
        else:
            print(f"  frame_{index:02d} @ {timestamp:.2f}s -> no shot match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
