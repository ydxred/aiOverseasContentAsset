from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_writer import stage_subdir


def build_v6_render_manifest(
    *,
    content_id: str,
    output_dir: Path,
    platform: str,
    composition: str,
    render_engine: str,
    fallback_engine: str,
    audio_path: Path,
    subtitle_plan_path: Path,
    shot_list_path: Path,
    quality_report_path: Path,
    outputs: dict[str, Any],
    remotion_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "architecture_version": "video_pipeline_v6_slice",
        "content_id": content_id,
        "resource_dir": str(output_dir),
        "platform": platform,
        "composition": composition,
        "render_engine": render_engine,
        "fallback_engine": fallback_engine,
        "render_engine_actual": (remotion_status or {}).get("render_engine_actual", fallback_engine),
        "audio_path": str(audio_path),
        "subtitle_plan_path": str(subtitle_plan_path),
        "shot_list_path": str(shot_list_path),
        "quality_report_path": str(quality_report_path),
        "outputs": outputs,
        "remotion_status_path": str(stage_subdir(output_dir, "remotion_status.json")),
        "audio_mastering_status_path": str(stage_subdir(output_dir, "audio_mastering_status.json")),
        "visual_qc_report_path": str(stage_subdir(output_dir, "visual_qc_report.json")),
    }
