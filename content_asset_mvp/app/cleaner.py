from __future__ import annotations

import re
from typing import Any

from .artifact_writer import ArtifactWriter


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\b(\w+)( \1\b)+", r"\1", text, flags=re.IGNORECASE)
    return text


def clean_transcript(transcript: dict[str, Any], writer: ArtifactWriter) -> dict[str, Any]:
    cleaned_segments: list[dict[str, Any]] = []
    previous_text = ""
    for segment in transcript.get("segments", []):
        text = _clean_text(segment.get("text", ""))
        if not text or text == previous_text:
            continue
        cleaned_segments.append(
            {
                "start": float(segment.get("start", 0.0)),
                "end": float(segment.get("end", segment.get("start", 0.0))),
                "text": text,
            }
        )
        previous_text = text

    cleaned = {
        "language": transcript.get("language", "en"),
        "source": transcript.get("source", "unknown"),
        "segments": cleaned_segments,
        "full_text": " ".join(segment["text"] for segment in cleaned_segments),
    }
    writer.write_json("transcript_clean.json", cleaned)
    return cleaned

