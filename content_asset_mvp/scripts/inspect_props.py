"""Quick inspector for the latest remotion_props.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: inspect_props.py <path-to-remotion_props.json>")
        return 2
    path = Path(sys.argv[1])
    data = json.loads(path.read_text(encoding="utf-8"))
    director_plan = data.get("directorPlan", {}) or {}
    shots = director_plan.get("shots", []) or []
    evidence_items = data.get("evidenceItems", []) or []
    subtitles = data.get("subtitles", []) or []
    print(f"title: {data.get('title')}")
    print(f"durationSeconds: {data.get('durationSeconds')}")
    print(f"subtitle count: {len(subtitles)}")
    print(f"evidence count: {len(evidence_items)} -> roles: {[i.get('role') for i in evidence_items]}")
    print(f"directorPlan keys: {list(director_plan.keys())}")
    print(f"shot count: {len(shots)}")
    for index, shot in enumerate(shots[:3], 1):
        print(f"  shot {index}: visual_type={shot.get('visual_type')} screen_text={shot.get('screen_text')!r} start={shot.get('start')} end={shot.get('end')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
