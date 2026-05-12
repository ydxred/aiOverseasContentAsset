from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def run_visual_qc(
    *,
    render_status_path: Path,
    video_quality_report_path: Path,
    audio_mastering_status_path: Path,
    subtitle_plan_path: Path,
    shot_list_path: Path,
) -> dict[str, Any]:
    render_status = _read_json(render_status_path)
    video_quality_report = _read_json(video_quality_report_path)
    audio_mastering = _read_json(audio_mastering_status_path)
    subtitle_plan = _read_json(subtitle_plan_path)
    shot_list = _read_json(shot_list_path)

    issues: list[str] = []
    must_fix: list[str] = []
    warnings: list[str] = []
    hard_failures: list[str] = []

    if render_status.get("status") not in {"succeeded", "ok", None} and not render_status.get("video_path"):
        hard_failures.append("Render status does not confirm a usable video output.")
    if render_status.get("subtitle_burned") is False:
        must_fix.append("Subtitles were not burned into the ffmpeg fallback render.")
    if audio_mastering.get("success") is not True:
        warnings.append(str(audio_mastering.get("reason") or "Audio mastering fell back to original narration."))

    subtitles = subtitle_plan.get("subtitles", []) if isinstance(subtitle_plan.get("subtitles"), list) else []
    if not subtitles:
        must_fix.append("subtitle_plan.json contains no subtitle entries.")

    shots = _extract_shots(shot_list)
    if len(shots) < 8:
        must_fix.append("Shot list is too thin for industrial short-video pacing.")

    quality_score = int(video_quality_report.get("video_quality_score") or 0)
    score = quality_score
    score -= len(hard_failures) * 35
    score -= len(must_fix) * 18
    score -= len(warnings) * 4
    score = max(0, min(100, score))

    issues.extend(hard_failures)
    issues.extend(must_fix)
    issues.extend(warnings)
    passed = not hard_failures and not must_fix and score >= 75
    return {
        "schema_version": 1,
        "architecture_version": "video_pipeline_v6_slice",
        "pass": passed,
        "score": score,
        "issues": issues,
        "must_fix": must_fix,
        "warnings": warnings,
        "hard_failures": hard_failures,
        "inputs": {
            "render_status_path": str(render_status_path),
            "video_quality_report_path": str(video_quality_report_path),
            "audio_mastering_status_path": str(audio_mastering_status_path),
            "subtitle_plan_path": str(subtitle_plan_path),
            "shot_list_path": str(shot_list_path),
        },
        "metrics": {
            "video_quality_score": quality_score,
            "subtitle_count": len(subtitles),
            "shot_count": len(shots),
            "audio_mastered": audio_mastering.get("success") is True,
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _extract_shots(shot_list: dict[str, Any]) -> list[Any]:
    for key in ("shots", "items", "shot_list"):
        value = shot_list.get(key)
        if isinstance(value, list):
            return value
    return []
