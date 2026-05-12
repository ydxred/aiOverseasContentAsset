from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .artifact_writer import ArtifactWriter


GENERIC_SOURCE_TYPES = {"article", "blog_article", "newsletter_issue", "community_thread", "product_launch", "creator_project", "creator_link"}


def make_generic_candidate_content_id(candidate: dict[str, Any]) -> str:
    source_type = str(candidate.get("source_type") or "web").strip() or "web"
    value = str(candidate.get("url") or candidate.get("candidate_id") or candidate.get("name") or source_type)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    prefix = "".join(char if char.isalnum() else "_" for char in source_type.lower()).strip("_")[:16] or "web"
    return f"{prefix}_{digest}"


def build_generic_candidate_meta(candidate: dict[str, Any], writer: ArtifactWriter) -> dict[str, Any]:
    signals = candidate.get("signals") if isinstance(candidate.get("signals"), dict) else {}
    content_id = writer.output_dir.name
    source_type = str(candidate.get("source_type") or "article")
    meta = {
        "content_id": content_id,
        "source_url": candidate.get("url", ""),
        "source_type": source_type,
        "title": candidate.get("name") or "Overseas AI opportunity candidate",
        "author": signals.get("author") or candidate.get("source_id") or "Unknown source",
        "published_at": signals.get("published_at") or signals.get("updated_at"),
        "duration": None,
        "language": signals.get("language") or "en",
        "description": signals.get("description") or candidate.get("reason", ""),
        "webpage_url": candidate.get("url", ""),
        "thumbnail": signals.get("thumbnail", ""),
        "audio_path": None,
        "subtitles": [],
        "automatic_captions": [],
        "download_status": "metadata_only_candidate",
        "candidate_id": candidate.get("candidate_id", ""),
        "category": candidate.get("category", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    writer.write_json("meta.json", meta)
    writer.write_json("meta.json", meta, workspace=True)
    writer.write_json("generic_candidate.json", dict(candidate))
    writer.write_json("transcript_clean.json", build_generic_candidate_transcript(candidate, meta))
    return meta


def build_generic_candidate_transcript(candidate: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    signals = candidate.get("signals") if isinstance(candidate.get("signals"), dict) else {}
    text_parts = [
        f"Title: {meta.get('title', '')}",
        f"Source type: {meta.get('source_type', '')}",
        f"Source URL: {meta.get('source_url', '')}",
        f"Description: {meta.get('description', '')}",
        f"Discovery reason: {candidate.get('reason', '')}",
        f"Source category: {candidate.get('category', '')}",
        f"Signals: {signals}",
    ]
    full_text = "\n".join(part for part in text_parts if str(part).strip())
    return {
        "status": "metadata_only",
        "language": meta.get("language", "en"),
        "source": "source_discovery_candidate",
        "segments": [{"start": 0.0, "end": 0.0, "text": full_text}],
        "full_text": full_text,
    }
