"""Re-run video self-review against an already rendered package."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app.video_self_review import run_video_self_review


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: rerun_self_review.py <package-dir>")
        return 2
    package = Path(sys.argv[1])
    final_video = package / "final_video.mp4"
    director_plan = json.loads((package / "director_plan.json").read_text(encoding="utf-8"))
    render_status = json.loads((package / "render_status.json").read_text(encoding="utf-8"))

    report = run_video_self_review(
        video_path=final_video,
        output_dir=package,
        ffmpeg="ffmpeg",
        director_plan=director_plan,
        render_status=render_status,
    )
    out = package / "video_self_review.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    print(json.dumps({k: report[k] for k in ("status", "pass", "checks", "issues", "warnings")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
