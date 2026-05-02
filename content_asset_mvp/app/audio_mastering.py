from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def master_voice_audio(
    voice_path: Path,
    output_path: Path,
    *,
    ffmpeg: str,
) -> tuple[Path, dict[str, Any]]:
    """Normalize narration audio and fall back to the original on failure."""
    status: dict[str, Any] = {
        "schema_version": 1,
        "architecture_version": "video_pipeline_v6_slice",
        "input_path": str(voice_path),
        "output_path": str(output_path),
        "fallback_path": str(voice_path),
        "filter": "loudnorm=I=-16:LRA=11:TP=-1.5,atrim=start=0",
    }
    if not voice_path.exists():
        status.update(
            {
                "status": "fallback",
                "mode": "missing_input",
                "success": False,
                "audio_path": str(voice_path),
                "reason": f"Input audio not found: {voice_path}",
            }
        )
        return voice_path, status

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(voice_path),
        "-af",
        str(status["filter"]),
        "-ar",
        "48000",
        "-ac",
        "2",
        str(output_path),
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise RuntimeError("ffmpeg completed but mastered audio is empty")
        status.update(
            {
                "status": "succeeded",
                "mode": "ffmpeg_loudnorm",
                "success": True,
                "audio_path": str(output_path),
                "stderr_tail": completed.stderr[-1200:],
            }
        )
        return output_path, status
    except Exception as exc:  # pragma: no cover - depends on local ffmpeg codecs.
        status.update(
            {
                "status": "fallback",
                "mode": "ffmpeg_failed",
                "success": False,
                "audio_path": str(voice_path),
                "reason": str(exc),
            }
        )
        return voice_path, status
