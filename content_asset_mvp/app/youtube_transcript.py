from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from .artifact_writer import ArtifactWriter


ENGLISH_LANGUAGES = ["en", "en-US", "en-GB"]
FALLBACK_LANGUAGES = [
    "en",
    "en-US",
    "en-GB",
    "zh-Hans",
    "zh",
    "ar",
    "es",
    "fr",
    "de",
    "pt",
    "ja",
    "ko",
    "hi",
    "id",
]


def fetch_youtube_transcript(candidate: dict[str, Any], writer: ArtifactWriter, *, mock: bool = False) -> dict[str, Any]:
    video_id = _video_id(candidate)
    if not video_id:
        return _write_skipped(writer, "missing_video_id", "Candidate does not include a YouTube video id.")
    if mock:
        return _write_skipped(writer, "mock_mode", "Mock mode does not call youtube-transcript-api.")

    try:
        raw_segments, language, mode = _fetch_transcript(video_id)
    except ImportError as exc:
        return _write_error(writer, video_id, "dependency_missing", str(exc))
    except Exception as exc:  # Transcript availability should never break package generation.
        return _write_error(writer, video_id, exc.__class__.__name__, str(exc))

    segments = [_normalize_segment(segment) for segment in raw_segments]
    transcript = {
        "status": "fetched",
        "video_id": video_id,
        "source": "youtube-transcript-api",
        "language": language or "en",
        "fetch_mode": mode,
        "languages_attempted": FALLBACK_LANGUAGES,
        "fetched_at": _now(),
        "segment_count": len(segments),
        "segments": segments,
    }
    writer.write_json("youtube_transcript.json", transcript)
    writer.write_json("transcript_clean.json", _clean_transcript(transcript))
    return transcript


def _fetch_transcript(video_id: str) -> tuple[list[Any], str | None, str]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise ImportError("youtube-transcript-api is required to fetch YouTube transcripts.") from exc

    api = YouTubeTranscriptApi()
    if hasattr(api, "list"):
        transcript_list = api.list(video_id)
        for transcript in transcript_list:
            language_code = getattr(transcript, "language_code", None)
            if language_code in ENGLISH_LANGUAGES:
                return list(transcript.fetch()), language_code, "preferred_language"
        for transcript in transcript_list:
            language_code = getattr(transcript, "language_code", None)
            return list(transcript.fetch()), language_code, "any_available_language"

    if hasattr(api, "fetch"):
        fetched = api.fetch(video_id, languages=FALLBACK_LANGUAGES)
        language = getattr(fetched, "language_code", None)
        mode = "preferred_language" if language in ENGLISH_LANGUAGES else "fallback_language"
        return list(fetched), language, mode

    fetched = YouTubeTranscriptApi.get_transcript(video_id, languages=FALLBACK_LANGUAGES)
    return list(fetched), None, "preferred_or_fallback_language"


def _normalize_segment(segment: Any) -> dict[str, Any]:
    if hasattr(segment, "text"):
        text = str(getattr(segment, "text", ""))
        start = float(getattr(segment, "start", 0.0) or 0.0)
        duration = float(getattr(segment, "duration", 0.0) or 0.0)
    elif isinstance(segment, dict):
        text = str(segment.get("text", ""))
        start = float(segment.get("start", 0.0) or 0.0)
        duration = float(segment.get("duration", 0.0) or 0.0)
    else:
        text = str(segment)
        start = 0.0
        duration = 0.0
    return {"start": start, "end": start + duration, "text": text.strip()}


def _clean_transcript(transcript: dict[str, Any]) -> dict[str, Any]:
    segments = []
    for segment in transcript.get("segments", []):
        if not isinstance(segment, dict):
            continue
        text = " ".join(str(segment.get("text", "")).split())
        if not text:
            continue
        segments.append(
            {
                "start": float(segment.get("start", 0.0) or 0.0),
                "end": float(segment.get("end", segment.get("start", 0.0)) or 0.0),
                "text": text,
            }
        )
    return {
        "status": transcript.get("status", "unknown"),
        "language": transcript.get("language", "en"),
        "source": transcript.get("source", "youtube-transcript-api"),
        "segments": segments,
        "full_text": " ".join(segment["text"] for segment in segments),
    }


def _write_skipped(writer: ArtifactWriter, reason: str, message: str) -> dict[str, Any]:
    video_id = ""
    transcript = {
        "status": "skipped",
        "video_id": video_id,
        "source": "youtube-transcript-api",
        "languages_attempted": ENGLISH_LANGUAGES,
        "reason": reason,
        "message": message,
        "fetched_at": _now(),
        "segments": [],
    }
    writer.write_json("youtube_transcript.json", transcript)
    writer.write_json("transcript_clean.json", _empty_clean(transcript))
    return transcript


def _write_error(writer: ArtifactWriter, video_id: str, reason: str, message: str) -> dict[str, Any]:
    transcript = {
        "status": "error",
        "video_id": video_id,
        "source": "youtube-transcript-api",
        "languages_attempted": ENGLISH_LANGUAGES,
        "reason": reason,
        "message": message,
        "fetched_at": _now(),
        "segments": [],
    }
    writer.write_json("youtube_transcript.json", transcript)
    writer.write_json("transcript_clean.json", _empty_clean(transcript))
    return transcript


def _empty_clean(transcript: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": transcript.get("status", "skipped"),
        "language": "en",
        "source": transcript.get("source", "youtube-transcript-api"),
        "segments": [],
        "full_text": "",
    }


def _video_id(candidate: dict[str, Any]) -> str:
    signals = candidate.get("signals") if isinstance(candidate.get("signals"), dict) else {}
    video_id = str(signals.get("video_id") or candidate.get("video_id") or "").strip()
    if video_id:
        return video_id
    return _video_id_from_url(str(candidate.get("url") or ""))


def _video_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/")
    query_id = parse_qs(parsed.query).get("v", [""])[0]
    if query_id:
        return query_id
    if parsed.path.startswith("/shorts/"):
        return parsed.path.split("/", 2)[2].split("/", 1)[0]
    return ""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
