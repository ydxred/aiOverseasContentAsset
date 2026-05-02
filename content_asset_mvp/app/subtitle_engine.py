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
    candidates: list[str] = []
    for key in ("highlight", "screen_text", "title", "visual_type"):
        value = shot.get(key)
        if isinstance(value, str):
            candidates.extend(_tokenize_highlight(value))
        elif isinstance(value, list):
            candidates.extend(str(item) for item in value if item)
    if not candidates:
        candidates = _tokenize_highlight(text)
    seen: set[str] = set()
    words: list[str] = []
    for word in candidates:
        word = word.strip()
        if len(word) < 2 or word in seen:
            continue
        seen.add(word)
        words.append(word[:16])
        if len(words) >= 4:
            break
    return words


def _tokenize_highlight(value: str) -> list[str]:
    tokens = [part.strip(" ,.。！？!?:：;；()[]{}") for part in value.replace("/", " ").split()]
    if len(tokens) > 1:
        return [token for token in tokens if token]
    return [value.strip()[:8]] if value.strip() else []


def _subtitle_style(shot: dict[str, Any], default_style: str) -> str:
    visual_type = str(shot.get("visual_type") or "")
    if visual_type in {"impact_title_card", "keyword_punch_card"}:
        return "big_claim"
    if visual_type in {"screenshot", "evidence_card", "repo_snapshot"}:
        return "evidence_caption"
    return default_style
