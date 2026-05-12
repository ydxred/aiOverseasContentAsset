"""Re-run BGM mix on an already-rendered run."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bgm_mixer import mix_bgm, write_bgm_status  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: rerun_bgm_mix.py <run_dir>")
        return 2
    run_dir = Path(sys.argv[1])
    if not run_dir.is_dir():
        print(f"not a directory: {run_dir}")
        return 1
    video = run_dir / "final_video.mp4"
    status = mix_bgm(video_path=video, output_dir=run_dir)
    write_bgm_status(run_dir, status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if status.get("status") in {"ok", "skipped"} else 1


if __name__ == "__main__":
    sys.exit(main())
