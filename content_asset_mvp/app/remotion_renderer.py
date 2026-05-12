from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .artifact_writer import stage_subdir


def _remotion_use_tmp_output() -> bool:
    return os.getenv("REMOTION_OUTPUT_TMP", "1").strip().lower() not in ("0", "false", "no", "off")


def _tmp_render_path(suffix: str) -> Path:
    return Path(tempfile.gettempdir()) / f"remotion_{uuid.uuid4().hex}{suffix}"


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


_ORIENTATION_PRESETS: dict[str, dict[str, str]] = {
    "portrait": {
        "composition": "DouyinExplainer",
        "platform_subdir": "douyin",
        "resolution": "1080x1920",
    },
    "landscape": {
        "composition": "LandscapeExplainer",
        "platform_subdir": "bilibili",
        "resolution": "1920x1080",
    },
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
    evidence_items: list[dict[str, str]] | None = None,
    director_plan: dict[str, Any] | None = None,
    composition: str | None = None,
    orientation: str = "portrait",
    repo_name: str | None = None,
    quality_tier: str = "release",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Render a single composition through Remotion.

    ``orientation`` selects the composition / platform subdir / resolution
    triplet via ``_ORIENTATION_PRESETS``. ``composition`` overrides the
    composition id when caller wants to bypass the preset.

    ``quality_tier`` selects between ``release`` (1080p / 30fps / x264 medium —
    default, publish-ready) and ``draft`` (540p / 24fps / x264 ultrafast — fast
    iteration preview, ~60% shorter render). Both tiers reuse the same
    bundle/props/composition, only the encoder/scale knobs change.
    """
    if quality_tier not in {"draft", "release"}:
        raise ValueError(
            f"quality_tier must be 'draft' or 'release', got {quality_tier!r}"
        )
    preset = _ORIENTATION_PRESETS.get(orientation, _ORIENTATION_PRESETS["portrait"])
    composition_id = composition or preset["composition"]
    platform_subdir = preset["platform_subdir"]
    resolution = preset["resolution"]
    if quality_tier == "draft":
        # 540p draft: half the pixels, half the encoder cost, ~60% faster.
        # Resolution stamp follows actual encoder output so quality report
        # / web pill don't lie about what the user is watching.
        if orientation == "landscape":
            resolution = "960x540"
        else:
            resolution = "540x960"

    status = probe_remotion_renderer(project_root, composition=composition_id)
    if not status.get("runtime_available"):
        return status, {}

    remotion_dir = Path(str(status["remotion_dir"]))
    public_dir = remotion_dir / "public" / "render_inputs" / _safe_name(content_id)
    public_dir.mkdir(parents=True, exist_ok=True)
    platform_dir = stage_subdir(output_dir, "platform_renders") / platform_subdir
    platform_dir.mkdir(parents=True, exist_ok=True)
    platform_video_path = platform_dir / "final_video.mp4"
    platform_cover_path = platform_dir / "cover.png"
    props_path = stage_subdir(output_dir, f"remotion_props_{orientation}.json")

    audio_public_path = _copy_public_asset(audio_path, public_dir, "voice")
    evidence_public_path = _copy_public_asset(evidence_image_path, public_dir, "evidence") if evidence_image_path else ""
    evidence_public_items = _copy_evidence_items(evidence_items or [], public_dir)
    props: dict[str, Any] = {
        "title": title,
        "durationSeconds": max(1.0, float(duration_seconds)),
        "audioPath": audio_public_path,
        "evidenceImage": evidence_public_path,
        "evidenceItems": evidence_public_items,
        "subtitles": subtitle_plan.get("subtitles", []) if isinstance(subtitle_plan, dict) else [],
        "directorPlan": director_plan or {},
    }
    if repo_name:
        props["repoName"] = repo_name
    props_path.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")

    render_status: dict[str, Any] = {
        "status": "started",
        "render_engine_actual": "remotion",
        "video_path": str(final_video_path),
        "platform_video_path": str(platform_video_path),
        "cover_path": str(cover_path),
        "platform_cover_path": str(platform_cover_path),
        "duration_seconds": duration_seconds,
        "resolution": resolution,
        "orientation": orientation,
        "subtitle_burned": True,
        "composition": composition_id,
        "props_path": str(props_path),
        "quality_tier": quality_tier,
    }
    tmp_video: Path | None = None
    tmp_cover: Path | None = None
    pipeline_script = remotion_dir / "scripts" / "render_pipeline.mjs"
    use_node_pipeline = pipeline_script.exists() and (
        os.getenv("REMOTION_USE_NODE_PIPELINE", "1").strip().lower() not in ("0", "false", "no", "off")
    )
    try:
        for path in (platform_video_path, platform_cover_path):
            if path.exists():
                path.unlink()
        video_render_target = platform_video_path
        cover_render_target = platform_cover_path
        if _remotion_use_tmp_output():
            tmp_video = _tmp_render_path(".mp4")
            tmp_cover = _tmp_render_path(".png")
            video_render_target = tmp_video
            cover_render_target = tmp_cover

        if use_node_pipeline:
            # One-shot Node API path: bundle once, render video + still
            # in a single process. Saves ~80s of duplicated webpack work
            # vs. invoking ``npx remotion`` twice.
            node_bin = shutil.which("node") or "node"
            pipeline_cmd = [
                node_bin,
                str(pipeline_script),
                "--composition",
                composition_id,
                "--props",
                str(props_path),
                "--out",
                str(video_render_target),
                "--cover",
                str(cover_render_target),
                "--cover-frame",
                "30",
                "--quality-tier",
                quality_tier,
            ]
            # Draft mode shrinks the render budget hard: scale, fps, encoder
            # preset are all relaxed in render_pipeline.mjs based on
            # ``--quality-tier draft``. We just pass the flag and trust the
            # node side; that keeps the encoding policy in one place.
            _run_remotion(
                pipeline_cmd,
                cwd=remotion_dir,
                timeout=max(360, int(duration_seconds) * 4 + 240),
            )
        else:
            props_arg = json.dumps(props, ensure_ascii=False)
            _run_remotion(
                [
                    str(status["remotion_cli"]),
                    "render",
                    "src/index.ts",
                    composition_id,
                    str(video_render_target),
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
                    composition_id,
                    str(cover_render_target),
                    "--props",
                    props_arg,
                    "--frame",
                    "30",
                ],
                cwd=remotion_dir,
                timeout=120,
            )
        if tmp_video is not None and tmp_video.resolve() != platform_video_path.resolve():
            shutil.copy2(tmp_video, platform_video_path)
        if tmp_cover is not None and tmp_cover.resolve() != platform_cover_path.resolve():
            shutil.copy2(tmp_cover, platform_cover_path)
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
    finally:
        for tmp in (tmp_video, tmp_cover):
            if tmp is not None and tmp.exists():
                tmp.unlink(missing_ok=True)

    status.update(
        {
            "status": "succeeded",
            "runtime_available": True,
            "render_engine_actual": "remotion",
            "reason": f"Remotion rendered the v6 {composition_id} output.",
            "platform_video_path": str(platform_video_path),
            "platform_cover_path": str(platform_cover_path),
            "props_path": str(props_path),
            "orientation": orientation,
            "resolution": resolution,
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


def _copy_evidence_items(items: list[dict[str, str]], public_dir: Path) -> list[dict[str, str]]:
    copied: list[dict[str, str]] = []
    for index, item in enumerate(items, start=1):
        source = Path(str(item.get("path") or ""))
        if not source.exists():
            continue
        public_path = _copy_public_asset(source, public_dir, f"evidence_{index:02d}")
        if not public_path:
            continue
        copied.append(
            {
                "src": public_path,
                "label": str(item.get("label") or f"Evidence {index}"),
                "role": str(item.get("role") or "evidence"),
            }
        )
    return copied[:8]


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)[:80] or "content"
