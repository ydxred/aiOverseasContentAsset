from __future__ import annotations

from typing import Any


DEFAULT_SAFE_AREA = {
    "x": 72,
    "y": 1220,
    "width": 936,
    "height": 360,
}


def build_subtitle_plan(
    caption_segments: list[Any],
    director_plan: dict[str, Any] | None = None,
    *,
    style: str = "douyin_explainer_v6",
    max_chars: int = 18,
) -> dict[str, Any]:
    """Build a renderer-neutral subtitle plan for Remotion/ffmpeg."""
    director_plan = director_plan or {}
    shots = director_plan.get("shots", []) if isinstance(director_plan, dict) else []
    subtitles: list[dict[str, Any]] = []
    for index, segment in enumerate(caption_segments):
        start = _segment_value(segment, "start", 0.0)
        end = _segment_value(segment, "end", start)
        text = str(_segment_value(segment, "text", "")).strip()
        shot = _shot_for_time(shots, float(start), index)
        subtitles.append(
            {
                "start": round(float(start), 3),
                "end": round(float(end), 3),
                "text": text,
                "highlight_words": _highlight_words(text, shot),
                "style": _subtitle_style(shot, style),
                "max_chars": max_chars,
                "safe_area": dict(DEFAULT_SAFE_AREA),
            }
        )

    return {
        "schema_version": 1,
        "architecture_version": "video_pipeline_v6_slice",
        "style": style,
        "max_chars": max_chars,
        "safe_area": dict(DEFAULT_SAFE_AREA),
        "subtitles": subtitles,
    }


def _segment_value(segment: Any, key: str, default: Any) -> Any:
    if isinstance(segment, dict):
        return segment.get(key, default)
    return getattr(segment, key, default)


def _shot_for_time(shots: Any, start: float, fallback_index: int) -> dict[str, Any]:
    if not isinstance(shots, list):
        return {}
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        shot_start = float(shot.get("start") or 0.0)
        shot_end = float(shot.get("end") or shot.get("duration") or shot_start)
        if shot_start <= start <= shot_end:
            return shot
    if 0 <= fallback_index < len(shots) and isinstance(shots[fallback_index], dict):
        return shots[fallback_index]
    return {}


def _highlight_words(text: str, shot: dict[str, Any]) -> list[str]:
    """Pick keywords that should be color-highlighted in the burned subtitle.

    Source priority (topic-agnostic):
      1. ``shot["subtitle_keywords"]`` — populated by ``video_director`` from
         the actual scene voiceover. These are real Chinese / English brand
         tokens (e.g. ``"Codex"``, ``"npm"``, ``"AI Agent"``) and are the
         only safe source.
      2. ``shot["screen_text"]`` — split on `` / `` since director writes
         e.g. ``"浏览器 / 文件 / API"``. Only kept if the resulting tokens
         actually appear in ``text``.
      3. Nothing — return [] rather than emitting layout enums.

    **Hard contract**: every returned word MUST appear as a substring of
    ``text``. Previously we were leaking ``visual_type`` enum truncations
    like ``"impact_t"`` / ``"top_thir"`` / ``"keyword_"`` into highlight_words,
    none of which exist in the cue text — Remotion's regex never matched,
    so the entire pipeline silently shipped white-only subtitles for months.
    """
    candidates: list[str] = []
    raw_keywords = shot.get("subtitle_keywords")
    if isinstance(raw_keywords, list):
        candidates.extend(str(item) for item in raw_keywords if item)
    elif isinstance(raw_keywords, tuple):
        candidates.extend(str(item) for item in raw_keywords if item)

    screen_text = shot.get("screen_text")
    if isinstance(screen_text, str) and screen_text:
        candidates.extend(part.strip() for part in screen_text.replace("/", " / ").split(" / ") if part.strip())

    seen: set[str] = set()
    words: list[str] = []
    for word in candidates:
        word = word.strip(" ,.。！？!?:：;；()[]{}「」『』")
        if len(word) < 2 or len(word) > 16:
            continue
        if word in seen:
            continue
        # Hard contract: keyword must actually appear in the cue text. Otherwise
        # Remotion's regex won't match and the highlight is invisible — better
        # to drop the keyword than to silently noop.
        if word not in text:
            continue
        seen.add(word)
        words.append(word)
        if len(words) >= 3:
            break
    return words


def _subtitle_style(shot: dict[str, Any], default_style: str) -> str:
    visual_type = str(shot.get("visual_type") or "")
    if visual_type in {"impact_title_card", "keyword_punch_card"}:
        return "big_claim"
    if visual_type in {"screenshot", "evidence_card", "repo_snapshot"}:
        return "evidence_caption"
    return default_style
