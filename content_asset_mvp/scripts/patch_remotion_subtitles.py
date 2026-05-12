"""Patch the Remotion props files to use word-aligned subtitle cues.

The renderer reads ``subtitles`` directly from ``remotion_props*.json`` (not
from ``subtitle_plan.json``), so updating subtitle_plan alone has no effect.
This script copies the freshly-aligned cues over each props file's subtitles.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def patch(props_path: Path, plan_path: Path) -> None:
    props = json.loads(props_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    new_cues = plan.get("subtitles") or []
    if not new_cues:
        raise SystemExit(f"plan has no subtitles: {plan_path}")

    safe_area_props = None
    if isinstance(props.get("subtitles"), list) and props["subtitles"]:
        safe_area_props = props["subtitles"][0].get("safe_area")

    rebuilt = []
    for cue in new_cues:
        rebuilt.append({
            "start": cue["start"],
            "end": cue["end"],
            "text": cue["text"],
            "highlight_words": cue.get("highlight_words", []),
            "style": cue.get("style") or props.get("style") or "douyin_explainer_v6",
            "max_chars": cue.get("max_chars", 14),
            "safe_area": cue.get("safe_area") or safe_area_props or {
                "x": 72, "y": 1220, "width": 936, "height": 360
            },
        })

    backup = props_path.with_suffix(".before_word_align.json")
    if not backup.exists():
        shutil.copy(props_path, backup)

    props["subtitles"] = rebuilt
    props_path.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[patch_props] {props_path.name}: {len(rebuilt)} cues written (backup: {backup.name})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--props", action="append", required=True, help="props json paths (repeat for landscape+portrait)")
    parser.add_argument("--plan", required=True, help="aligned subtitle_plan.json")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    for props_arg in args.props:
        p = Path(props_arg)
        if not p.exists():
            print(f"[patch_props] skip missing: {p}")
            continue
        patch(p, plan_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
