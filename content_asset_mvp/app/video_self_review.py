from __future__ import annotations

import statistics
import subprocess
from pathlib import Path
from typing import Any

from .artifact_writer import stage_subdir


SUBTITLE_SAFE_AREA = {"x": 72, "y": 1218, "width": 936, "height": 360}


def run_video_self_review(
    *,
    video_path: Path,
    output_dir: Path,
    ffmpeg: str,
    director_plan: dict[str, Any],
    render_status: dict[str, Any],
) -> dict[str, Any]:
    frames_dir = stage_subdir(output_dir, "self_review_frames")
    frames_dir.mkdir(parents=True, exist_ok=True)
    duration = _as_float(render_status.get("duration_seconds"), default=0.0)
    frame_paths, frame_errors = _extract_review_frames(video_path, frames_dir, ffmpeg=ffmpeg, duration=duration)
    shots = director_plan.get("shots", []) if isinstance(director_plan.get("shots"), list) else []
    asset_roles = _asset_roles(director_plan)

    issues: list[str] = []
    warnings: list[str] = []
    if not video_path.exists() or video_path.stat().st_size <= 0:
        issues.append("final_video.mp4 is missing or empty.")
    if len(shots) < 8:
        issues.append("shot_list is too thin; expected at least 8 shots for short-video pacing.")
    if len(asset_roles) < 2:
        warnings.append("visual asset diversity is low; add browser evidence or README/demo screenshots.")
    if frame_errors:
        warnings.extend(frame_errors)
    if frame_paths and len(frame_paths) < 3:
        warnings.append("self-review extracted fewer than 3 frames.")

    visual_type_diversity = _visual_type_diversity(shots)
    if visual_type_diversity < 3:
        warnings.append(
            f"shot template diversity is low ({visual_type_diversity} unique visual_types); aim for 3+."
        )

    pixel_report = _analyze_frames(frame_paths)
    issues.extend(pixel_report["issues"])
    warnings.extend(pixel_report["warnings"])

    passed = not issues and bool(frame_paths)
    return {
        "schema_version": 2,
        "architecture_version": "video_self_review_v2",
        "status": "passed" if passed else "needs_review",
        "pass": passed,
        "video_path": str(video_path),
        "frames_dir": str(frames_dir),
        "frames": [
            {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "metrics": pixel_report["frames"].get(path.name, {}),
            }
            for path in frame_paths
            if path.exists()
        ],
        "checks": {
            "video_exists": video_path.exists() and video_path.stat().st_size > 0,
            "frame_count": len(frame_paths),
            "shot_count": len(shots),
            "asset_role_count": len(asset_roles),
            "visual_type_diversity": visual_type_diversity,
            "render_engine_actual": render_status.get("render_engine_actual", "unknown"),
            "pixel_analysis_available": pixel_report["available"],
            "min_brightness": pixel_report["aggregates"].get("min_brightness"),
            "min_sharpness": pixel_report["aggregates"].get("min_sharpness"),
            "subtitle_band_min_brightness": pixel_report["aggregates"].get("subtitle_band_min_brightness"),
        },
        "issues": issues,
        "warnings": warnings,
    }


def _extract_review_frames(video_path: Path, frames_dir: Path, *, ffmpeg: str, duration: float) -> tuple[list[Path], list[str]]:
    if not video_path.exists():
        return [], ["Cannot extract review frames because final_video.mp4 does not exist."]
    if duration <= 0:
        duration = 12.0
    timestamps = [max(0.1, duration * ratio) for ratio in (0.12, 0.5, 0.88)]
    frame_paths: list[Path] = []
    errors: list[str] = []
    for index, timestamp in enumerate(timestamps, start=1):
        target = frames_dir / f"review_frame_{index:02d}.jpg"
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(target),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        except Exception as exc:  # pragma: no cover - depends on local ffmpeg codecs.
            errors.append(f"Frame {index} extraction failed: {exc}")
            continue
        if target.exists() and target.stat().st_size > 0:
            frame_paths.append(target)
        else:
            errors.append(f"Frame {index} extraction produced no image.")
    return frame_paths, errors


def _analyze_frames(frame_paths: list[Path]) -> dict[str, Any]:
    """Run pixel-level QC. Falls back gracefully when Pillow is unavailable."""

    try:
        from PIL import Image, ImageFilter, ImageStat  # type: ignore
    except Exception:  # pragma: no cover - environment-dependent
        return {
            "available": False,
            "frames": {},
            "issues": [],
            "warnings": [
                "Pillow not installed; pixel-level brightness/blur/subtitle-band checks are skipped.",
            ],
            "aggregates": {},
        }

    if not frame_paths:
        return {"available": True, "frames": {}, "issues": [], "warnings": [], "aggregates": {}}

    metrics: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    warnings: list[str] = []
    brightness_values: list[float] = []
    sharpness_values: list[float] = []
    subtitle_band_brightness: list[float] = []

    laplacian = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=0)

    for path in frame_paths:
        try:
            with Image.open(path) as image:
                image.load()
                gray = image.convert("L")
                width, height = gray.size
                stats = ImageStat.Stat(gray)
                brightness = float(stats.mean[0])
                global_stddev = float(stats.stddev[0])
                edge = gray.filter(laplacian)
                edge_var = float(ImageStat.Stat(edge).var[0])
                subtitle_band = _crop_subtitle_band(gray, width, height)
                subtitle_brightness = float(ImageStat.Stat(subtitle_band).mean[0]) if subtitle_band else 0.0
                subtitle_stddev = float(ImageStat.Stat(subtitle_band).stddev[0]) if subtitle_band else 0.0
        except Exception as exc:
            warnings.append(f"Pixel analysis failed for {path.name}: {exc}")
            continue

        metrics[path.name] = {
            "brightness": round(brightness, 2),
            "sharpness": round(edge_var, 2),
            "global_stddev": round(global_stddev, 2),
            "subtitle_band_brightness": round(subtitle_brightness, 2),
            "subtitle_band_stddev": round(subtitle_stddev, 2),
        }
        brightness_values.append(brightness)
        sharpness_values.append(edge_var)
        subtitle_band_brightness.append(subtitle_brightness)

        # 深色高对比是抖音/视频号常见风格，stddev 大说明画面有内容；
        # 只有亮度极低 (<14) 且 stddev 也低（<20）才算真黑屏。
        if brightness < 14 and global_stddev < 20:
            issues.append(
                f"{path.name} is effectively black (brightness={brightness:.1f}, stddev={global_stddev:.1f}); render likely failed."
            )
        elif brightness > 245:
            issues.append(
                f"{path.name} is effectively white (brightness={brightness:.1f}); subtitles probably hidden."
            )
        elif brightness < 22 and global_stddev < 35:
            warnings.append(
                f"{path.name} is very dark with low contrast (brightness={brightness:.1f}, stddev={global_stddev:.1f})."
            )

        if edge_var < 15:
            issues.append(
                f"{path.name} looks blurry (laplacian_variance={edge_var:.1f}); upscale source or fix scale-up."
            )
        elif edge_var < 35:
            warnings.append(
                f"{path.name} sharpness is borderline (laplacian_variance={edge_var:.1f}); evidence may look soft."
            )

        if subtitle_band and subtitle_stddev < 6:
            warnings.append(
                f"{path.name} subtitle band looks flat (stddev={subtitle_stddev:.1f}); subtitles may not be visible."
            )

    aggregates = {
        "min_brightness": round(min(brightness_values), 2) if brightness_values else None,
        "max_brightness": round(max(brightness_values), 2) if brightness_values else None,
        "mean_brightness": round(statistics.mean(brightness_values), 2) if brightness_values else None,
        "min_sharpness": round(min(sharpness_values), 2) if sharpness_values else None,
        "max_sharpness": round(max(sharpness_values), 2) if sharpness_values else None,
        "subtitle_band_min_brightness": round(min(subtitle_band_brightness), 2) if subtitle_band_brightness else None,
    }

    return {
        "available": True,
        "frames": metrics,
        "issues": issues,
        "warnings": warnings,
        "aggregates": aggregates,
    }


def _crop_subtitle_band(image: Any, width: int, height: int) -> Any | None:
    """Crop the subtitle safe area scaled to the actual frame size."""

    base_width = 1080
    base_height = 1920
    if width <= 0 or height <= 0:
        return None
    scale_x = width / base_width
    scale_y = height / base_height
    left = max(0, int(SUBTITLE_SAFE_AREA["x"] * scale_x))
    top = max(0, int(SUBTITLE_SAFE_AREA["y"] * scale_y))
    right = min(width, int((SUBTITLE_SAFE_AREA["x"] + SUBTITLE_SAFE_AREA["width"]) * scale_x))
    bottom = min(height, int((SUBTITLE_SAFE_AREA["y"] + SUBTITLE_SAFE_AREA["height"]) * scale_y))
    if right <= left or bottom <= top:
        return None
    return image.crop((left, top, right, bottom))


def _asset_roles(director_plan: dict[str, Any]) -> set[str]:
    assets = director_plan.get("assets", []) if isinstance(director_plan.get("assets"), list) else []
    roles = {str(asset.get("role") or "") for asset in assets if isinstance(asset, dict) and asset.get("path")}
    return {role for role in roles if role}


def _visual_type_diversity(shots: list[Any]) -> int:
    types: set[str] = set()
    for shot in shots:
        if isinstance(shot, dict):
            visual_type = str(shot.get("visual_type") or "").strip()
            if visual_type:
                types.add(visual_type)
    return len(types)


def _as_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
