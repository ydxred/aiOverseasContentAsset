from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_writer import ArtifactWriter


def transcribe(meta: dict[str, Any], writer: ArtifactWriter, *, mock: bool, openai_api_key: str | None) -> dict[str, Any]:
    if mock:
        transcript = {
            "language": "en",
            "source": "mock",
            "segments": [
                {
                    "start": 0.0,
                    "end": 8.0,
                    "text": "Today I want to explain why AI agents are changing the economics of content production.",
                },
                {
                    "start": 8.0,
                    "end": 18.0,
                    "text": "The important shift is not that every video becomes automated, but that research and drafting get cheaper.",
                },
                {
                    "start": 18.0,
                    "end": 30.0,
                    "text": "Teams still need editorial judgment, fact checking, and a format that fits the audience.",
                },
            ],
        }
        writer.write_json("transcript.json", transcript)
        return transcript

    audio_path = meta.get("audio_path")
    if not audio_path or not Path(audio_path).exists():
        raise RuntimeError("audio_path is required for real transcription mode, but no audio file was found. Check the download step or run with --mock.")
    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for real transcription mode.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package is required for Whisper transcription") from exc

    client = OpenAI(api_key=openai_api_key)
    with open(audio_path, "rb") as audio_file:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments = _segments_from_result(result)
    transcript = {"language": _result_value(result, "language", "en"), "source": "openai_whisper", "segments": segments}
    writer.write_json("transcript.json", transcript)
    return transcript


def _result_value(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _segments_from_result(result: Any) -> list[dict[str, Any]]:
    raw_segments = _result_value(result, "segments", None) or []
    segments: list[dict[str, Any]] = []
    for segment in raw_segments:
        start = _result_value(segment, "start", 0.0)
        end = _result_value(segment, "end", start)
        text = _result_value(segment, "text", "")
        segments.append({"start": float(start or 0.0), "end": float(end or 0.0), "text": str(text)})
    if segments:
        return segments

    text = _result_value(result, "text", "")
    if text:
        return [{"start": 0.0, "end": 0.0, "text": str(text)}]
    raise RuntimeError("OpenAI transcription returned no text or segments")

