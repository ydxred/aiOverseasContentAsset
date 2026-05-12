"""Rebuild subtitle_plan.json from OpenAI Whisper word-level timestamps.

Strategy
--------
- Use Whisper's per-word ``start``/``end`` timestamps as ground truth.
- Group words into display cues by:
  1) hard breaks at sentence-final punctuation (。 ! ？ ；),
  2) soft breaks at clause punctuation (，、) when the running cue is already
     long enough (>= 8 chars or >= 1.5 s),
  3) emergency split at 14 chars / 3.0 s to avoid runaway cues.

The result is short, rhythm-matched cues that light up with the actual
narration — instead of one big block hovering for 8 seconds.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HARD_BREAK = set("。！？!?；;")
SOFT_BREAK = set("，、,")

MAX_CHARS = 14
MAX_SECONDS = 3.0
MIN_SECONDS = 0.45  # avoid frame-flickering tiny cues
MIN_CHARS_BEFORE_SOFT_BREAK = 6
MIN_DURATION_BEFORE_SOFT_BREAK = 1.2


def build_cues(words: list[dict], style: str) -> list[dict]:
    cues: list[dict] = []
    cur_text_parts: list[str] = []
    cur_start: float | None = None
    cur_end: float | None = None

    def flush() -> None:
        nonlocal cur_text_parts, cur_start, cur_end
        if not cur_text_parts or cur_start is None or cur_end is None:
            cur_text_parts = []
            cur_start = None
            cur_end = None
            return
        text = "".join(cur_text_parts).strip()
        if text:
            # Stretch cues that are below the minimum hold time so subtitles
            # don't strobe between fast words.
            if cur_end - cur_start < MIN_SECONDS:
                cur_end = cur_start + MIN_SECONDS
            cues.append({
                "start": round(cur_start, 3),
                "end": round(cur_end, 3),
                "text": text,
                "style": style,
                "highlight_words": [],
            })
        cur_text_parts = []
        cur_start = None
        cur_end = None

    for w in words:
        token = (w.get("word") or "").strip()
        if not token:
            continue
        ws = float(w.get("start", 0.0))
        we = float(w.get("end", ws))
        if cur_start is None:
            cur_start = ws
        cur_text_parts.append(token)
        cur_end = we

        running_text = "".join(cur_text_parts)
        running_chars = len(running_text)
        running_dur = (cur_end or 0) - (cur_start or 0)
        last_char = running_text[-1] if running_text else ""

        # Hard break — always cut after sentence-final punctuation.
        if last_char in HARD_BREAK:
            flush()
            continue

        # Soft break — cut after clause punctuation if the cue is already meaty.
        if (
            last_char in SOFT_BREAK
            and running_chars >= MIN_CHARS_BEFORE_SOFT_BREAK
            and running_dur >= MIN_DURATION_BEFORE_SOFT_BREAK
        ):
            flush()
            continue

        # Emergency split — never let a cue blow past these limits.
        if running_chars >= MAX_CHARS or running_dur >= MAX_SECONDS:
            flush()
            continue

    flush()
    return cues


def merge_short_tail(cues: list[dict]) -> list[dict]:
    """Glue a too-tiny last cue back onto its predecessor (avoids 0.3s flickers)."""
    if len(cues) >= 2 and (cues[-1]["end"] - cues[-1]["start"]) < MIN_SECONDS:
        last = cues.pop()
        prev = cues[-1]
        prev["end"] = max(prev["end"], last["end"])
        prev["text"] = prev["text"] + last["text"]
    return cues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--whisper", required=True, help="path to whisper verbose_json output")
    parser.add_argument("--output", required=True, help="path to write subtitle_plan.json")
    parser.add_argument("--existing", required=False, help="existing subtitle_plan.json to preserve metadata from")
    args = parser.parse_args()

    whisper_path = Path(args.whisper)
    output_path = Path(args.output)

    data = json.loads(whisper_path.read_text(encoding="utf-8"))
    words = data.get("words") or []
    if not words:
        print(f"[words_to_subtitle_plan] no words in {whisper_path}")
        return 1

    style = "douyin_explainer_v6"
    safe_area = {"x": 72, "y": 1220, "width": 936, "height": 360}
    schema = {
        "schema_version": 1,
        "architecture_version": "video_pipeline_v6_slice",
        "style": style,
        "max_chars": MAX_CHARS,
        "safe_area": safe_area,
    }
    if args.existing:
        try:
            existing = json.loads(Path(args.existing).read_text(encoding="utf-8"))
            for k in ("style", "safe_area", "max_chars", "architecture_version"):
                if k in existing:
                    schema[k] = existing[k]
        except Exception:
            pass

    cues_raw = build_cues(words, style=schema["style"])
    cues = merge_short_tail(cues_raw)

    # Stamp common metadata on each cue.
    for c in cues:
        c["max_chars"] = schema["max_chars"]
        c["safe_area"] = schema["safe_area"]

    plan = {
        **schema,
        "subtitles": cues,
        "source": {
            "engine": "openai_whisper_word_align",
            "whisper_duration": data.get("duration"),
            "whisper_word_count": len(words),
        },
    }

    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[words_to_subtitle_plan] wrote {len(cues)} cues -> {output_path}")
    print(f"  cue duration stats: min={min(c['end']-c['start'] for c in cues):.2f}s "
          f"max={max(c['end']-c['start'] for c in cues):.2f}s "
          f"avg={sum(c['end']-c['start'] for c in cues)/len(cues):.2f}s")
    print("  first 5 cues:")
    for c in cues[:5]:
        print(f"    {c['start']:5.2f}s - {c['end']:5.2f}s  '{c['text']}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
