"""Replace ``Default`` (Layer 0) cues in the burned-in ASS subtitle file with
the word-aligned cues from subtitle_plan.json. Scene (Layer 1) and Shot
(Layer 2) cues are left untouched.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


def secs_to_ass(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def patch_ass(ass_path: Path, plan_path: Path) -> None:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    cues = plan.get("subtitles") or []
    if not cues:
        raise SystemExit(f"plan has no subtitles: {plan_path}")

    raw = ass_path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    # Walk lines: drop existing ``Dialogue: 0,...,Default,...`` lines, keep
    # everything else. Then append rebuilt Default cues at the end of the file
    # (ASS render order is determined by Layer; absolute placement in file
    # doesn't matter).
    default_re = re.compile(r"^Dialogue:\s*\d+,[^,]+,[^,]+,Default,")
    kept: list[str] = []
    removed = 0
    for ln in lines:
        if default_re.match(ln):
            removed += 1
            continue
        kept.append(ln)

    rebuilt: list[str] = []
    for cue in cues:
        text = cue["text"].replace("\n", " ").strip()
        # ASS escape: backslashes / commas don't need escaping in plain text.
        rebuilt.append(
            f"Dialogue: 0,{secs_to_ass(float(cue['start']))},{secs_to_ass(float(cue['end']))},Default,,0,0,0,,{text}"
        )

    backup = ass_path.with_suffix(".before_word_align.ass")
    if not backup.exists():
        shutil.copy(ass_path, backup)

    new_text = "\n".join(kept).rstrip() + "\n" + "\n".join(rebuilt) + "\n"
    ass_path.write_text(new_text, encoding="utf-8")
    print(f"[patch_ass] {ass_path.name}: removed {removed} old Default cues, "
          f"added {len(rebuilt)} aligned cues (backup: {backup.name})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ass", action="append", required=True)
    parser.add_argument("--plan", required=True)
    args = parser.parse_args()
    plan_path = Path(args.plan)
    for a in args.ass:
        p = Path(a)
        if not p.exists():
            print(f"[patch_ass] skip missing: {p}")
            continue
        patch_ass(p, plan_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
