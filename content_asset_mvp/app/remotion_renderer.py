from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def probe_remotion_renderer(project_root: Path, *, composition: str = "DouyinExplainer") -> dict[str, Any]:
    remotion_dir = project_root / "video_engine" / "remotion"
    package_json = remotion_dir / "package.json"
    node = shutil.which("node")
    npm = shutil.which("npm")
    local_cli = remotion_dir / "node_modules" / ".bin" / "remotion"
    global_cli = shutil.which("remotion")
    npx = shutil.which("npx")
    remotion_cli = str(local_cli) if local_cli.exists() else (global_cli or "")

    missing: list[str] = []
    if not package_json.exists():
        missing.append("video_engine/remotion/package.json")
    if not node:
        missing.append("node")
    if not npm:
        missing.append("npm")
    if not remotion_cli:
        missing.append("remotion_cli")

    available = not missing
    return {
        "schema_version": 1,
        "architecture_version": "video_pipeline_v6_slice",
        "status": "ready" if available else "fallback",
        "runtime_available": available,
        "preferred_engine": "remotion",
        "render_engine_actual": "ffmpeg",
        "fallback_engine": "ffmpeg",
        "composition": composition,
        "remotion_dir": str(remotion_dir),
        "package_json": str(package_json),
        "node_path": node or "",
        "npm_path": npm or "",
        "npx_path": npx or "",
        "remotion_cli": remotion_cli,
        "missing": missing,
        "reason": (
            "Remotion runtime detected; v6 slice still renders through ffmpeg fallback."
            if available
            else "Remotion runtime is not fully installed; using ffmpeg fallback."
        ),
    }


def render_remotion_video(
    *,
    project_root: Path,
    content_id: str,
    title: str,
    duration_seconds: float,
    audio_path: Path,
    subtitle_plan: dict[str, Any],
    output_dir: Path,
    final_video_path: Path,
    cover_path: Path,
    evidence_image_path: Path | None = None,
    composition: str = "DouyinExplainer",
) -> tuple[dict[str, Any], dict[str, Any]]:
    status = probe_remotion_renderer(project_root, composition=composition)
    if not status.get("runtime_available"):
        return status, {}

    remotion_dir = Path(str(status["remotion_dir"]))
    public_dir = remotion_dir / "public" / "render_inputs" / _safe_name(content_id)
    public_dir.mkdir(parents=True, exist_ok=True)
    platform_dir = output_dir / "platform_renders" / "douyin"
    platform_dir.mkdir(parents=True, exist_ok=True)
    platform_video_path = platform_dir / "final_video.mp4"
    platform_cover_path = platform_dir / "cover.png"
    props_path = output_dir / "remotion_props.json"

    audio_public_path = _copy_public_asset(audio_path, public_dir, "voice")
    evidence_public_path = _copy_public_asset(evidence_image_path, public_dir, "evidence") if evidence_image_path else ""
    props = {
        "title": title,
        "durationSeconds": max(1.0, float(duration_seconds)),
        "audioPath": audio_public_path,
        "evidenceImage": evidence_public_path,
        "subtitles": subtitle_plan.get("subtitles", []) if isinstance(subtitle_plan, dict) else [],
    }
    props_path.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")

    render_status: dict[str, Any] = {
        "status": "started",
        "render_engine_actual": "remotion",
        "video_path": str(final_video_path),
        "platform_video_path": str(platform_video_path),
        "cover_path": str(cover_path),
        "platform_cover_path": str(platform_cover_path),
        "duration_seconds": duration_seconds,
        "resolution": "1080x1920",
        "subtitle_burned": True,
        "composition": composition,
        "props_path": str(props_path),
    }
    try:
        for path in (platform_video_path, platform_cover_path):
            if path.exists():
                path.unlink()
        props_arg = json.dumps(props, ensure_ascii=False)
        _run_remotion(
            [
                str(status["remotion_cli"]),
                "render",
                "src/index.ts",
                composition,
                str(platform_video_path),
                "--props",
                props_arg,
            ],
            cwd=remotion_dir,
            timeout=max(240, int(duration_seconds) + 180),
        )
        _run_remotion(
            [
                str(status["remotion_cli"]),
                "still",
                "src/index.ts",
                composition,
                str(platform_cover_path),
                "--props",
                props_arg,
                "--frame",
                "30",
            ],
            cwd=remotion_dir,
            timeout=120,
        )
        shutil.copy2(platform_video_path, final_video_path)
        shutil.copy2(platform_cover_path, cover_path)
    except Exception as exc:
        status.update(
            {
                "status": "fallback",
                "render_engine_actual": "ffmpeg",
                "reason": f"Remotion render failed; using ffmpeg fallback: {exc}",
                "error": str(exc)[-2000:],
                "platform_video_path": str(platform_video_path),
                "platform_cover_path": str(platform_cover_path),
                "props_path": str(props_path),
            }
        )
        render_status.update({"status": "failed", "error": str(exc)[-2000:]})
        return status, render_status

    status.update(
        {
            "status": "succeeded",
            "runtime_available": True,
            "render_engine_actual": "remotion",
            "reason": "Remotion rendered the v6 DouyinExplainer output.",
            "platform_video_path": str(platform_video_path),
            "platform_cover_path": str(platform_cover_path),
            "props_path": str(props_path),
        }
    )
    render_status.update({"status": "succeeded"})
    return status, render_status


def _run_remotion(command: list[str], *, cwd: Path, timeout: int) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        detail = result.stderr or result.stdout or f"Remotion command failed with exit code {result.returncode}"
        raise RuntimeError(detail[-2000:])


def _copy_public_asset(path: Path | None, public_dir: Path, stem: str) -> str:
    if path is None or not path.exists():
        return ""
    target = public_dir / f"{stem}{path.suffix.lower()}"
    shutil.copy2(path, target)
    return str(target.relative_to(public_dir.parents[1])).replace("\\", "/")


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)[:80] or "content"
