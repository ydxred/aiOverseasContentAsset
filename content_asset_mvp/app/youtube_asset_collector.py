"""YouTube visual asset collector.

Produces raw visual evidence for a YouTube candidate so the Remotion
compositor has something to show besides branded placeholders. The
strategy is intentionally cheap and robust:

1. Download a low-resolution copy of the video with ``yt-dlp`` into
   the workspace (never the output dir – it can be several hundred MB).
2. Probe the duration and extract N keyframes at evenly-spaced time
   offsets with ``ffmpeg``. We avoid the first/last ~5% to skip intro
   logos and outro end-cards.
3. Download the YouTube-supplied thumbnail image for use as a
   "wide hero" evidence (good for the Cover and Hook shots).

The function writes a ``youtube_assets.json`` index file listing every
produced asset with both ``workspace_path`` (real bytes) and ``role``
fields. ``media_producer.collect_visual_evidence_items`` picks up this
file in a new branch so downstream shots can reference real frames.

Fail-soft philosophy: any single failure (yt-dlp blocked, ffprobe
missing, thumbnail 404) degrades gracefully rather than killing the
pipeline. The returned ``status`` field records what went wrong so
operators can diagnose without digging through logs.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .artifact_writer import ArtifactWriter

logger = logging.getLogger(__name__)

DEFAULT_NUM_KEYFRAMES = 8
# Render targets are 1080×1920 (portrait) and 1920×1080 (landscape). When the
# source download is 480p, every keyframe gets up-scaled ~3× linearly when
# Remotion renders, producing the all-too-familiar "blurry macOS chrome" look.
# We now pull 1080p so keyframes match render resolution 1:1.
DEFAULT_MAX_HEIGHT = 1080
# 1080p MP4 of a 30 minute talking-head can hit ~500-700 MB; 200 MB used to
# clip mid-stream and silently drop to 480p. Bump the cap and rely on
# ``_purge_video_after_keyframes`` to remove the source after extraction.
DEFAULT_MAX_FILESIZE_MB = 800
DEFAULT_TIMEOUT_SECONDS = 600
# Keyframes are now extracted at the render output width — no upscale step.
KEYFRAME_WIDTH = 1920
EDGE_TRIM_FRACTION = 0.05  # Skip first and last 5% of the video when sampling.


def collect_youtube_assets(
    meta: dict[str, Any],
    writer: ArtifactWriter,
    *,
    num_keyframes: int = DEFAULT_NUM_KEYFRAMES,
    max_height: int = DEFAULT_MAX_HEIGHT,
    max_filesize_mb: int = DEFAULT_MAX_FILESIZE_MB,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    mock: bool = False,
    yt_dlp_cmd: str = "yt-dlp",
    ffmpeg_cmd: str = "ffmpeg",
) -> dict[str, Any]:
    content_id = writer.output_dir.name
    video_url = str(meta.get("webpage_url") or meta.get("source_url") or "").strip()
    thumbnail_url = str(meta.get("thumbnail") or "").strip()

    assets_dir = writer.workspace_dir / "youtube_assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    status: dict[str, Any] = {
        "status": "pending",
        "content_id": content_id,
        "video_url": video_url,
        "thumbnail_url": thumbnail_url,
        "num_keyframes_requested": num_keyframes,
        "max_height": max_height,
        "max_filesize_mb": max_filesize_mb,
        "assets": [],
        "steps": {},
    }

    if mock:
        status["status"] = "skipped_mock"
        writer.write_json("youtube_assets.json", status)
        return status

    if not video_url:
        status["status"] = "skipped_no_url"
        writer.write_json("youtube_assets.json", status)
        return status

    # Always attempt the thumbnail first – it's cheap and unlocks at
    # least the Cover shot even if the full download fails.
    thumbnail_asset = _download_thumbnail(thumbnail_url, assets_dir, status)
    if thumbnail_asset is not None:
        status["assets"].append(thumbnail_asset)

    video_path, download_info = _download_video(
        video_url,
        assets_dir,
        yt_dlp_cmd=yt_dlp_cmd,
        max_height=max_height,
        max_filesize_mb=max_filesize_mb,
        timeout=timeout,
    )
    status["steps"]["video_download"] = download_info

    if video_path is None:
        status["status"] = "thumbnail_only" if thumbnail_asset else "failed"
        writer.write_json("youtube_assets.json", status)
        return status

    duration = _probe_duration(video_path, ffmpeg_cmd=ffmpeg_cmd)
    status["video_path"] = str(video_path)
    status["video_duration_seconds"] = duration

    keyframe_assets = _extract_keyframes(
        video_path,
        assets_dir,
        duration=duration,
        num_keyframes=num_keyframes,
        ffmpeg_cmd=ffmpeg_cmd,
        timeout=timeout,
    )
    status["assets"].extend(keyframe_assets)
    status["steps"]["keyframe_extraction"] = {
        "requested": num_keyframes,
        "produced": len(keyframe_assets),
    }

    # Now that keyframes are on disk, the source MP4 is dead weight (can be
    # 500 MB+ for a 30-min 1080p talking head). Drop it to keep the workspace
    # lean — re-running the pipeline will re-pull as needed.
    if keyframe_assets:
        try:
            size_freed_mb = video_path.stat().st_size / 1024 / 1024
            video_path.unlink()
            status["steps"]["video_purge"] = {
                "status": "purged",
                "freed_mb": round(size_freed_mb, 1),
            }
        except OSError as exc:
            status["steps"]["video_purge"] = {"status": "failed", "error": str(exc)}

    if keyframe_assets:
        status["status"] = "succeeded"
    elif thumbnail_asset:
        status["status"] = "thumbnail_only"
    else:
        status["status"] = "failed"

    writer.write_json("youtube_assets.json", status)
    return status


def _download_thumbnail(url: str, assets_dir: Path, status: dict[str, Any]) -> dict[str, Any] | None:
    step: dict[str, Any] = {"status": "skipped_no_url"}
    status["steps"]["thumbnail_download"] = step
    if not url:
        return None

    step["status"] = "pending"
    dest = assets_dir / "thumbnail.jpg"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 content-asset-mvp/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response, dest.open("wb") as handle:
            shutil.copyfileobj(response, handle, length=64 * 1024)
        if dest.stat().st_size < 1024:
            step["status"] = "failed"
            step["error"] = f"thumbnail too small ({dest.stat().st_size}B)"
            dest.unlink(missing_ok=True)
            return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        step["status"] = "failed"
        step["error"] = str(exc)
        dest.unlink(missing_ok=True)
        return None

    step["status"] = "succeeded"
    step["path"] = str(dest)
    step["bytes"] = dest.stat().st_size
    return {
        "workspace_path": str(dest),
        "role": "youtube_thumbnail",
        "label": "视频封面",
        "source": "youtube_thumbnail",
    }


def _download_video(
    url: str,
    assets_dir: Path,
    *,
    yt_dlp_cmd: str,
    max_height: int,
    max_filesize_mb: int,
    timeout: int,
) -> tuple[Path | None, dict[str, Any]]:
    step: dict[str, Any] = {"status": "pending", "url": url}
    output_template = str(assets_dir / "video.%(ext)s")

    # Prefer the BEST mp4 at or below max_height — keyframes extracted from
    # this video are the actual render-time visual material, so a 480p source
    # turns every shot into an upscaled blur. Fall back to any format only
    # when mp4 is unavailable.
    format_spec = (
        f"best[height<={max_height}][ext=mp4]/"
        f"best[height<={max_height}]/"
        "best[ext=mp4]/best"
    )

    command = [
        yt_dlp_cmd,
        "--quiet",
        "--no-warnings",
        "--no-playlist",
        "--max-filesize",
        f"{max_filesize_mb}M",
        "-f",
        format_spec,
        "-o",
        output_template,
        url,
    ]

    step["command"] = _scrub_command(command)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        step["status"] = "failed"
        step["error"] = f"{yt_dlp_cmd} not installed on PATH"
        return None, step
    except subprocess.TimeoutExpired:
        step["status"] = "failed"
        step["error"] = f"yt-dlp timed out after {timeout}s"
        return None, step

    step["exit_code"] = result.returncode
    if result.stderr:
        step["stderr_tail"] = result.stderr[-500:]
    if result.returncode != 0:
        step["status"] = "failed"
        return None, step

    # yt-dlp resolves the real extension at runtime; find the first matching file.
    for candidate in sorted(assets_dir.glob("video.*")):
        if candidate.suffix.lower() in {".mp4", ".mkv", ".webm"} and candidate.stat().st_size > 0:
            step["status"] = "succeeded"
            step["path"] = str(candidate)
            step["bytes"] = candidate.stat().st_size
            return candidate, step

    step["status"] = "failed"
    step["error"] = "yt-dlp reported success but no video file was found"
    return None, step


def _probe_duration(video_path: Path, *, ffmpeg_cmd: str) -> float | None:
    # ffprobe ships alongside ffmpeg in the same bin dir.
    ffprobe_cmd = str(Path(ffmpeg_cmd).with_name("ffprobe")) if Path(ffmpeg_cmd).is_absolute() else "ffprobe"
    try:
        result = subprocess.run(
            [
                ffprobe_cmd,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _extract_keyframes(
    video_path: Path,
    assets_dir: Path,
    *,
    duration: float | None,
    num_keyframes: int,
    ffmpeg_cmd: str,
    timeout: int,
) -> list[dict[str, Any]]:
    if num_keyframes <= 0:
        return []
    if not duration or duration <= 1.0:
        # Can't plan timestamps without duration; fall back to a single
        # fast-seek grab at t=1s so at least one frame exists.
        timestamps = [1.0]
    else:
        start = duration * EDGE_TRIM_FRACTION
        end = duration * (1.0 - EDGE_TRIM_FRACTION)
        if end <= start:
            start = 0.0
            end = duration
        if num_keyframes == 1:
            timestamps = [(start + end) / 2.0]
        else:
            step = (end - start) / (num_keyframes - 1)
            timestamps = [start + step * idx for idx in range(num_keyframes)]

    produced: list[dict[str, Any]] = []
    for idx, ts in enumerate(timestamps, start=1):
        dest = assets_dir / f"keyframe_{idx:02d}.jpg"
        # Use input-seek (-ss before -i) for speed; accuracy within a few
        # hundred ms is fine because we're picking evenly-distributed
        # representative frames, not a specific moment.
        command = [
            ffmpeg_cmd,
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{ts:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={KEYFRAME_WIDTH}:-2:flags=lanczos",
            "-q:v",
            "3",
            str(dest),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("keyframe %s extraction failed: %s", idx, exc)
            continue
        if result.returncode != 0 or not dest.exists() or dest.stat().st_size < 1024:
            logger.warning(
                "keyframe %s ffmpeg exit=%s stderr=%s",
                idx,
                result.returncode,
                result.stderr[-200:] if result.stderr else "",
            )
            dest.unlink(missing_ok=True)
            continue
        produced.append(
            {
                "workspace_path": str(dest),
                "role": "youtube_keyframe",
                "label": f"视频第 {ts:.0f} 秒关键帧",
                "timestamp_seconds": round(ts, 3),
                "source": "youtube_video_keyframe",
            }
        )
    return produced


def _scrub_command(command: list[str]) -> list[str]:
    # No secrets are actually passed on the yt-dlp CLI today, but keep this
    # hook in place so we can add auth cookies later without accidentally
    # writing them to a JSON artifact.
    return list(command)
