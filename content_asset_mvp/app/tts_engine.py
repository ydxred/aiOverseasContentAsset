from __future__ import annotations

from pathlib import Path
from typing import Any


def synthesize_narration(
    text: str,
    output_path: Path,
    *,
    ffmpeg: str,
    openai_api_key: str | None,
    force_mock: bool = False,
) -> tuple[Path, dict[str, Any]]:
    """Compatibility wrapper for narration synthesis.

    The v6 slice keeps the existing media_producer implementation as the
    stable backend while moving orchestration behind a dedicated module.
    """
    from .media_producer import synthesize_voice

    voice_path, status = synthesize_voice(
        text,
        output_path,
        ffmpeg=ffmpeg,
        openai_api_key=openai_api_key,
        force_mock=force_mock,
    )
    status = dict(status)
    status.setdefault("engine", "media_producer.synthesize_voice")
    status["architecture_version"] = "video_pipeline_v6_slice"
    return voice_path, status
