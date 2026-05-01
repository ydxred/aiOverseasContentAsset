from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_writer import ArtifactWriter


def make_content_id(url: str) -> str:
    return "yt_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def make_file_content_id(path: str | Path) -> str:
    return "audio_" + hashlib.sha256(str(Path(path).resolve()).encode("utf-8")).hexdigest()[:12]


def tool_path(name: str) -> str | None:
    system_path = shutil.which(name)
    if system_path:
        return system_path
    project_root = Path(__file__).resolve().parents[1]
    local_path = project_root / ".venv" / "bin" / name
    if local_path.exists():
        return str(local_path)
    return None


def check_download_dependencies() -> dict[str, bool]:
    return {
        "yt-dlp": tool_path("yt-dlp") is not None,
        "ffmpeg": tool_path("ffmpeg") is not None,
    }


def _normalize_meta(raw: dict[str, Any], url: str, content_id: str, audio_path: Path | None, mock: bool) -> dict[str, Any]:
    subtitles = raw.get("subtitles") or {}
    automatic_captions = raw.get("automatic_captions") or {}
    return {
        "content_id": content_id,
        "source_url": url,
        "source_type": "youtube",
        "title": raw.get("title") or "Mock overseas content asset case",
        "author": raw.get("uploader") or raw.get("channel") or "Unknown",
        "published_at": raw.get("upload_date") or raw.get("release_date"),
        "duration": raw.get("duration"),
        "language": raw.get("language") or "en",
        "description": raw.get("description") or "",
        "webpage_url": raw.get("webpage_url") or url,
        "thumbnail": raw.get("thumbnail"),
        "audio_path": str(audio_path) if audio_path else None,
        "subtitles": sorted(subtitles.keys()) if isinstance(subtitles, dict) else [],
        "automatic_captions": sorted(automatic_captions.keys()) if isinstance(automatic_captions, dict) else [],
        "download_status": "mocked" if mock else "metadata_ready",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_metadata_and_audio(url: str, writer: ArtifactWriter, *, mock: bool = False) -> dict[str, Any]:
    content_id = writer.output_dir.name
    if mock:
        meta = _normalize_meta(
            {
                "title": "Mock: Why AI agents change content production",
                "uploader": "Mock Creator",
                "duration": 480,
                "language": "en",
                "description": "A mock source used to validate the MVP pipeline.",
                "webpage_url": url,
            },
            url,
            content_id,
            None,
            True,
        )
        writer.write_json("meta.json", meta)
        writer.write_json("meta.json", meta, workspace=True)
        return meta

    dependencies = check_download_dependencies()
    yt_dlp_path = tool_path("yt-dlp")
    if not yt_dlp_path:
        raise RuntimeError("yt-dlp is required for real download mode. Install yt-dlp or run with --mock.")

    try:
        metadata_cmd = [yt_dlp_path, "--dump-json", "--no-playlist", url]
        metadata_result = subprocess.run(metadata_cmd, capture_output=True, text=True, check=True, timeout=120)
        raw_meta = json.loads(metadata_result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as exc:
        fallback = _normalize_meta(
            {"title": "Metadata fetch failed", "description": str(exc)},
            url,
            content_id,
            None,
            False,
        )
        fallback["download_status"] = "metadata_failed"
        fallback["error"] = str(exc)
        writer.write_json("meta.json", fallback)
        writer.write_json("meta.json", fallback, workspace=True)
        return fallback

    audio_template = str(writer.workspace_path("source_audio.%(ext)s"))
    audio_path = writer.workspace_path("source_audio.mp3")
    if not dependencies["ffmpeg"]:
        try:
            audio_cmd = [
                yt_dlp_path,
                "--no-playlist",
                "-f",
                "bestaudio/best",
                "-o",
                audio_template,
                url,
            ]
            subprocess.run(audio_cmd, capture_output=True, text=True, check=True, timeout=600)
            downloaded = sorted(writer.workspace_dir.glob("source_audio.*"))
            audio_path = downloaded[0] if downloaded else None
            if audio_path is None:
                raw_meta["audio_error"] = "Audio download completed but no source_audio file was found."
            else:
                raw_meta["audio_note"] = "ffmpeg was not available; saved original audio format without mp3 conversion."
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            audio_path = None
            raw_meta["audio_error"] = str(exc)
    else:
        try:
            ffmpeg_path = tool_path("ffmpeg")
            audio_cmd = [
                yt_dlp_path,
                "--no-playlist",
                "-x",
                "--audio-format",
                "mp3",
                "-o",
                audio_template,
                url,
            ]
            if ffmpeg_path:
                audio_cmd.extend(["--ffmpeg-location", ffmpeg_path])
            subprocess.run(audio_cmd, capture_output=True, text=True, check=True, timeout=600)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            audio_path = None
            raw_meta["audio_error"] = str(exc)

    meta = _normalize_meta(raw_meta, url, content_id, audio_path if audio_path and audio_path.exists() else None, False)
    if raw_meta.get("audio_error"):
        meta["download_status"] = "metadata_ready_audio_failed"
        meta["audio_error"] = raw_meta["audio_error"]
    writer.write_json("meta.json", meta)
    writer.write_json("meta.json", meta, workspace=True)
    return meta


def build_local_audio_meta(audio_file: str | Path, writer: ArtifactWriter, *, title: str | None = None) -> dict[str, Any]:
    source = Path(audio_file).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Audio file not found: {source}")
    if not source.is_file():
        raise RuntimeError(f"Audio path is not a file: {source}")

    target = writer.workspace_path(source.name)
    if source != target:
        target.write_bytes(source.read_bytes())

    content_id = writer.output_dir.name
    meta = {
        "content_id": content_id,
        "source_url": f"file://{source}",
        "source_type": "local_audio",
        "title": title or source.stem,
        "author": "Local audio",
        "published_at": None,
        "duration": None,
        "language": "en",
        "description": "Local audio validation input.",
        "webpage_url": f"file://{source}",
        "thumbnail": None,
        "audio_path": str(target),
        "subtitles": [],
        "automatic_captions": [],
        "download_status": "local_audio_ready",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    writer.write_json("meta.json", meta)
    writer.write_json("meta.json", meta, workspace=True)
    return meta

