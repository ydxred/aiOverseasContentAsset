from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .artifact_writer import ArtifactWriter
from .db import Database
from .downloader import make_content_id
from .llm_client import LLMClient


def make_youtube_candidate_content_id(candidate: dict[str, Any]) -> str:
    url = str(candidate.get("url") or "").strip()
    if url:
        return make_content_id(url)
    candidate_id = str(candidate.get("candidate_id") or "youtube_candidate")
    return "ytcand_" + "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in candidate_id)[:64]


def build_youtube_candidate_meta(candidate: dict[str, Any], writer: ArtifactWriter) -> dict[str, Any]:
    signals = candidate.get("signals") if isinstance(candidate.get("signals"), dict) else {}
    content_id = writer.output_dir.name
    meta = {
        "content_id": content_id,
        "source_url": candidate.get("url", ""),
        "source_type": "youtube_video",
        "title": candidate.get("name") or "YouTube candidate",
        "author": signals.get("channel_title") or "Unknown YouTube channel",
        "published_at": signals.get("published_at"),
        "duration": None,
        "language": "en",
        "description": signals.get("description") or candidate.get("reason", ""),
        "webpage_url": candidate.get("url", ""),
        "thumbnail": signals.get("thumbnail"),
        "audio_path": None,
        "subtitles": [],
        "automatic_captions": [],
        "download_status": "metadata_only_candidate",
        "candidate_id": candidate.get("candidate_id", ""),
        "channel_id": signals.get("channel_id", ""),
        "channel_title": signals.get("channel_title", ""),
        "video_id": signals.get("video_id", ""),
        "stats": {
            "views": _as_int(signals.get("views")),
            "likes": _as_int(signals.get("likes")),
            "comments": _as_int(signals.get("comments")),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    writer.write_json("meta.json", meta)
    writer.write_json("meta.json", meta, workspace=True)
    writer.write_json("youtube_candidate.json", _candidate_payload(candidate, content_id))
    return meta


def analyze_youtube_candidate(
    meta: dict[str, Any],
    candidate: dict[str, Any],
    transcript_clean: dict[str, Any],
    transcript_status: dict[str, Any],
    writer: ArtifactWriter,
    llm: LLMClient,
    db: Database,
) -> dict[str, Any]:
    has_transcript = bool(str(transcript_clean.get("full_text") or "").strip())
    transcript_language = str(transcript_clean.get("language") or transcript_status.get("language") or "").strip()
    analysis_basis = "transcript_any_language" if has_transcript and transcript_language not in {"", "en", "en-US", "en-GB"} else "transcript" if has_transcript else "metadata_only"
    factual_confidence = "higher_transcript_based" if has_transcript else "low_metadata_only"
    payload = {
        "meta": meta,
        "candidate": _candidate_payload(candidate, writer.output_dir.name),
        "transcript": transcript_clean,
        "transcript_status": {
            "status": transcript_status.get("status", "unknown"),
            "reason": transcript_status.get("reason"),
            "message": transcript_status.get("message"),
            "language": transcript_status.get("language"),
            "segment_count": transcript_status.get("segment_count", 0),
        },
        "analysis_basis": analysis_basis,
        "factual_confidence": factual_confidence,
        "instruction": (
            "Prioritize transcript text in any available language when it is present. Translate/interpret it into "
            "Chinese for the content analysis instead of rejecting non-English subtitles. If no transcript is "
            "available, fall back to title, description, channel and stats only, and explicitly mark factual "
            "confidence as low."
        ),
    }
    response = llm.generate("youtube_candidate_analysis", payload)
    analysis = response.content
    if not isinstance(analysis, dict):
        raise RuntimeError("youtube_candidate_analysis response must be JSON-compatible")
    analysis.setdefault("analysis_basis", payload["analysis_basis"])
    analysis.setdefault("transcript_status", payload["transcript_status"])
    analysis.setdefault("factual_confidence", factual_confidence)
    if not has_transcript:
        facts_to_check = analysis.get("facts_to_check")
        if not isinstance(facts_to_check, list):
            facts_to_check = []
        facts_to_check.append("Transcript was unavailable; verify the video's specific claims before scripting.")
        analysis["facts_to_check"] = facts_to_check
    path = writer.write_json("analysis.json", analysis)
    db.record_model_run(writer.output_dir.name, "youtube_candidate_analysis", response.provider, response.model, "succeeded")
    db.record_artifact(writer.output_dir.name, "analysis", str(path))
    return analysis


def _candidate_payload(candidate: dict[str, Any], content_id: str) -> dict[str, Any]:
    payload = dict(candidate)
    payload["content_id"] = content_id
    return payload


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
