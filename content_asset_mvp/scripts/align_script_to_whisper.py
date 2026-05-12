"""Align our authoritative script (with proper punctuation) onto
Whisper's word-level timestamps. The result is a subtitle plan that has
both correct text (from the script) AND precise timing (from Whisper).

Why this is needed
------------------
Whisper's Chinese transcription drops most punctuation, so cues built
straight from Whisper read like "以前AI只能回答你问题现在它"  — no
commas, no rhythm. We want the original script's typography while
keeping Whisper's millisecond-accurate per-word boundaries.

Algorithm
---------
1. Strip both texts to a comparable base (CJK chars + ASCII alphanumerics).
2. Walk both sequences with a two-pointer scan; on each match, attach the
   matched script char to the Whisper word's start/end. Mismatches are
   resolved by greedy lookahead (Whisper's recognition errors are usually
   1-3 chars off — e.g. 'github' for 'GitHub').
3. Insert punctuation back into the text by attributing each punctuation
   mark to the timestamp of the character that immediately precedes it.
4. Group the now-punctuated, timestamped chars into display cues using
   the same hard/soft-break rules as ``words_to_subtitle_plan.py``.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

HARD_BREAK = set("。！？!?；;")
SOFT_BREAK = set("，、,")
PUNCTUATION = HARD_BREAK | SOFT_BREAK | set("：:—…\"'")

MAX_CHARS = 14
MAX_SECONDS = 3.0
MIN_SECONDS = 0.45
MIN_CHARS_BEFORE_SOFT_BREAK = 6
MIN_DURATION_BEFORE_SOFT_BREAK = 1.2


def extract_voiceover(script_md: str) -> str:
    """Pull the voice-over body. Prefers the director script's '# 导演层口播稿'
    section (which is what TTS actually consumes); falls back to '# 口播稿' or
    raw text. Strips any '##' subsection headings and markdown decoration."""
    patterns = (
        r"#\s*导演层口播稿\s*\n(.*?)(?:\n#\s|\Z)",
        r"#\s*口播稿\s*\n(.*?)(?:\n#\s|\Z)",
    )
    body = script_md
    for pat in patterns:
        m = re.search(pat, script_md, re.S)
        if m:
            body = m.group(1)
            break
    # Drop ## subsection headings entirely (they aren't spoken).
    body = re.sub(r"^##.*$", "", body, flags=re.M)
    body = re.sub(r"^[\-\*\>\s]+", "", body, flags=re.M)
    body = re.sub(r"\*+", "", body)
    body = re.sub(r"\s+\n", "\n", body)
    return body.replace("\r", "").strip()


def normalize_for_match(ch: str) -> str:
    """Strip case + width differences so 'github' matches 'GitHub'."""
    return unicodedata.normalize("NFKC", ch).lower()


def is_alignable(ch: str) -> bool:
    if not ch:
        return False
    if ch in PUNCTUATION:
        return False
    if ch.isspace():
        return False
    cp = ord(ch)
    # CJK unified ideographs OR ASCII alphanumeric.
    if 0x4E00 <= cp <= 0x9FFF:
        return True
    if ch.isalnum():
        return True
    return False


def explode_word(word: str) -> list[str]:
    """Whisper 'word' tokens contain multiple chars for English, single for CJK."""
    out: list[str] = []
    for ch in word:
        if ch.isspace():
            continue
        out.append(ch)
    return out


def align(script_text: str, whisper_words: list[dict]) -> list[dict]:
    """Return a list of {char, start, end} entries — char is from script,
    start/end are derived from Whisper word containing the matching char.
    Punctuation chars get attached to the previous timestamp."""
    # Flatten Whisper words into per-char tokens with timestamps interpolated
    # within the word (e.g. "github" with start=0.0 end=1.0 → 6 chars at 0.17s each).
    whisper_chars: list[tuple[str, float, float]] = []
    for w in whisper_words:
        token = (w.get("word") or "").strip()
        if not token:
            continue
        chars = explode_word(token)
        if not chars:
            continue
        ws = float(w.get("start", 0.0))
        we = float(w.get("end", ws))
        n = len(chars)
        if n == 1:
            whisper_chars.append((chars[0], ws, we))
        else:
            step = (we - ws) / n
            for i, ch in enumerate(chars):
                whisper_chars.append((ch, ws + step * i, ws + step * (i + 1)))

    aligned: list[dict] = []
    si = 0  # script index
    wi = 0  # whisper index
    last_end = 0.0
    LOOKAHEAD = 3

    while si < len(script_text):
        sch = script_text[si]
        # Carry over punctuation/whitespace using the last known timestamp.
        if not is_alignable(sch):
            if not sch.isspace():
                aligned.append({"char": sch, "start": last_end, "end": last_end})
            si += 1
            continue

        target = normalize_for_match(sch)
        matched_at = -1
        for k in range(min(LOOKAHEAD, len(whisper_chars) - wi)):
            cand = normalize_for_match(whisper_chars[wi + k][0])
            if cand == target:
                matched_at = wi + k
                break

        if matched_at >= 0:
            ch, ws, we = whisper_chars[matched_at]
            aligned.append({"char": sch, "start": ws, "end": we})
            last_end = we
            wi = matched_at + 1
            si += 1
        else:
            # Fall back: use Whisper's current char's timing for the script
            # char. This handles the "ITN" cases where Whisper recognizes
            # numbers as a single token but our script has separated chars.
            if wi < len(whisper_chars):
                _, ws, we = whisper_chars[wi]
                aligned.append({"char": sch, "start": ws, "end": we})
                last_end = we
                wi += 1
            else:
                aligned.append({"char": sch, "start": last_end, "end": last_end})
            si += 1

    return aligned


def _is_word_internal(prev_ch: str, ch: str, next_ch: str) -> bool:
    """True if cutting between prev_ch and ch (or ch and next_ch) would split
    a continuous Latin/digit token like 'browser-use' or 'GitHub'."""
    def latin(c: str) -> bool:
        return bool(c) and (c.isalnum() and ord(c) < 0x4E00) or c in "-_."
    return latin(prev_ch) and latin(ch)


def build_cues(aligned: list[dict], style: str) -> list[dict]:
    cues: list[dict] = []
    cur: list[dict] = []
    cur_text: list[str] = []

    def flush() -> None:
        nonlocal cur, cur_text
        if not cur:
            return
        text = "".join(cur_text).strip()
        while text and text[0] in PUNCTUATION:
            text = text[1:]
        if not text:
            cur = []
            cur_text = []
            return
        start = cur[0]["start"]
        end = cur[-1]["end"]
        if end - start < MIN_SECONDS:
            end = start + MIN_SECONDS
        cues.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
            "style": style,
            "highlight_words": [],
        })
        cur = []
        cur_text = []

    for i, entry in enumerate(aligned):
        ch = entry["char"]
        cur.append(entry)
        cur_text.append(ch)
        running_chars = sum(1 for c in cur_text if is_alignable(c))
        running_dur = entry["end"] - cur[0]["start"]
        next_ch = aligned[i + 1]["char"] if i + 1 < len(aligned) else ""

        if ch in HARD_BREAK:
            flush()
            continue
        if (
            ch in SOFT_BREAK
            and running_chars >= MIN_CHARS_BEFORE_SOFT_BREAK
            and running_dur >= MIN_DURATION_BEFORE_SOFT_BREAK
        ):
            flush()
            continue
        if running_chars >= MAX_CHARS or running_dur >= MAX_SECONDS:
            # Don't split through a Latin token like 'browser-use'. Hold the
            # cut until the next non-Latin / punctuation / CJK boundary.
            if _is_word_internal(ch, next_ch, ""):
                continue
            flush()
            continue

    flush()
    return cues


def merge_short_cues(cues: list[dict]) -> list[dict]:
    """Glue cues that are too short (< MIN_SECONDS or < 4 alignable chars) onto
    a neighbour, preferring the previous cue."""
    if not cues:
        return cues
    merged: list[dict] = []
    for cue in cues:
        char_count = sum(1 for c in cue["text"] if is_alignable(c))
        too_short = (cue["end"] - cue["start"]) < MIN_SECONDS or char_count <= 3
        if too_short and merged:
            prev = merged[-1]
            prev["end"] = max(prev["end"], cue["end"])
            prev["text"] = prev["text"] + cue["text"]
            continue
        merged.append(cue)
    # Second pass: if the very first cue is too short, fold it into the next.
    if len(merged) >= 2:
        first = merged[0]
        first_chars = sum(1 for c in first["text"] if is_alignable(c))
        if (first["end"] - first["start"]) < MIN_SECONDS or first_chars <= 3:
            merged[1]["start"] = first["start"]
            merged[1]["text"] = first["text"] + merged[1]["text"]
            merged.pop(0)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--whisper", required=True)
    parser.add_argument("--script", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--existing", required=False)
    args = parser.parse_args()

    whisper_path = Path(args.whisper)
    script_path = Path(args.script)
    output_path = Path(args.output)

    whisper_data = json.loads(whisper_path.read_text(encoding="utf-8"))
    words = whisper_data.get("words") or []
    if not words:
        print(f"[align] no words in {whisper_path}")
        return 1

    script_md = script_path.read_text(encoding="utf-8")
    script_text = extract_voiceover(script_md)
    if not script_text:
        print(f"[align] could not extract voiceover from {script_path}")
        return 1

    aligned = align(script_text, words)
    cues = build_cues(aligned, style="douyin_explainer_v6")
    cues = merge_short_cues(cues)

    # Carry forward common metadata.
    schema = {
        "schema_version": 1,
        "architecture_version": "video_pipeline_v6_slice",
        "style": "douyin_explainer_v6",
        "max_chars": MAX_CHARS,
        "safe_area": {"x": 72, "y": 1220, "width": 936, "height": 360},
    }
    if args.existing:
        try:
            existing = json.loads(Path(args.existing).read_text(encoding="utf-8"))
            for k in ("style", "safe_area", "max_chars", "architecture_version"):
                if k in existing:
                    schema[k] = existing[k]
        except Exception:
            pass

    for c in cues:
        c["max_chars"] = schema["max_chars"]
        c["safe_area"] = schema["safe_area"]

    plan = {
        **schema,
        "subtitles": cues,
        "source": {
            "engine": "openai_whisper_word_align_with_script",
            "whisper_duration": whisper_data.get("duration"),
            "whisper_word_count": len(words),
            "script_chars": sum(1 for c in script_text if is_alignable(c)),
        },
    }
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[align] wrote {len(cues)} cues -> {output_path}")
    durs = [c["end"] - c["start"] for c in cues]
    print(f"  cue duration: min={min(durs):.2f}s max={max(durs):.2f}s avg={sum(durs)/len(durs):.2f}s")
    print(f"  cue char counts: {[sum(1 for c in cue['text'] if is_alignable(c)) for cue in cues[:8]]}...")
    print("  first 8 cues:")
    for c in cues[:8]:
        print(f"    {c['start']:5.2f}s - {c['end']:5.2f}s  '{c['text']}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
