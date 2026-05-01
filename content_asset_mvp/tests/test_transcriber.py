from __future__ import annotations

from pathlib import Path

import pytest

from app.artifact_writer import ArtifactWriter
from app.transcriber import transcribe


def test_real_transcriber_requires_audio_file(tmp_path: Path) -> None:
    writer = ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "yt_missing_audio")

    with pytest.raises(RuntimeError, match="audio file was found"):
        transcribe({"audio_path": str(tmp_path / "missing.mp3")}, writer, mock=False, openai_api_key="test-key")


def test_real_transcriber_requires_openai_key(tmp_path: Path) -> None:
    writer = ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "yt_missing_key")
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        transcribe({"audio_path": str(audio_path)}, writer, mock=False, openai_api_key=None)
