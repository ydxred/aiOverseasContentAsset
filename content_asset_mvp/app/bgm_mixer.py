"""BGM mixdown step.

Given a rendered video, optionally mix a royalty-free BGM track over its
existing audio (TTS or silence), normalize the loudness to -14 LUFS (Douyin
/ B 站 / YouTube standard), and write a sibling ``final_video_with_bgm.mp4``.

Designed to be a no-op when no BGM file is available: that lets the pipeline
keep working before the user provides their own track.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .artifact_writer import stage_subdir


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BGM_DIR = PROJECT_ROOT / "assets" / "bgm"
MIX_SCRIPT = PROJECT_ROOT / "scripts" / "mix_bgm_into_video.sh"


def _pick_bgm(bgm_dir: Path, preferred: str | None = None) -> Path | None:
    if preferred:
        candidate = Path(preferred)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / preferred
        if candidate.is_file():
            return candidate
    if not bgm_dir.is_dir():
        return None
    candidates: list[Path] = []
    for ext in ("*.mp3", "*.wav", "*.m4a", "*.aac", "*.flac", "*.ogg"):
        candidates.extend(bgm_dir.glob(ext))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _probe_loudness(video_path: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(video_path),
                "-filter:a",
                "ebur128",
                "-f",
                "null",
                "-",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        tail = (proc.stderr or "").strip().splitlines()[-15:]
        result: dict[str, Any] = {"raw_tail": tail}
        for line in tail:
            stripped = line.strip()
            if stripped.startswith("I:") and "LUFS" in stripped:
                try:
                    result["integrated_lufs"] = float(stripped.split()[1])
                except (IndexError, ValueError):
                    pass
            elif stripped.startswith("LRA:") and "LU" in stripped and "low" not in stripped:
                try:
                    result["loudness_range_lu"] = float(stripped.split()[1])
                except (IndexError, ValueError):
                    pass
            elif stripped.startswith("Peak:") and "dBFS" in stripped:
                try:
                    result["true_peak_dbfs"] = float(stripped.split()[1])
                except (IndexError, ValueError):
                    pass
        return result
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": str(exc)[-200:]}


def mix_bgm(
    *,
    video_path: Path,
    output_dir: Path,
    bgm_dir: Path | None = None,
    preferred_bgm: str | None = None,
) -> dict[str, Any]:
    """Mix BGM into ``video_path`` and write a sibling ``_with_bgm.mp4`` file.

    Returns a status dict (always returned, never raises). The status reflects
    one of these cases::

        {"status": "skipped", "reason": "<why>"}
        {"status": "ok", "output_path": "...", "bgm_used": "...", "loudness": {...}}
        {"status": "failed", "error": "..."}
    """
    bgm_dir = bgm_dir or DEFAULT_BGM_DIR

    if not video_path.is_file():
        return {"status": "skipped", "reason": f"video not found: {video_path}"}
    if not MIX_SCRIPT.is_file():
        return {"status": "skipped", "reason": f"mix script missing: {MIX_SCRIPT}"}
    if shutil.which("ffmpeg") is None:
        return {"status": "skipped", "reason": "ffmpeg not on PATH"}

    bgm_file = _pick_bgm(bgm_dir, preferred_bgm)
    if bgm_file is None:
        return {
            "status": "skipped",
            "reason": f"no bgm files found in {bgm_dir}",
            "hint": "drop a royalty-free .mp3/.wav into assets/bgm/ to enable",
        }

    out_path = stage_subdir(output_dir, "final_video_with_bgm.mp4")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        proc = subprocess.run(
            ["bash", str(MIX_SCRIPT), str(video_path), str(bgm_file), str(out_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as exc:
        return {"status": "failed", "error": f"mix script invocation failed: {exc!r}"}

    if proc.returncode != 0:
        return {
            "status": "failed",
            "error": (proc.stderr or proc.stdout or "")[-2000:],
            "returncode": proc.returncode,
        }

    if not out_path.is_file():
        return {
            "status": "failed",
            "error": "mix script returned 0 but output file missing",
            "stdout_tail": (proc.stdout or "")[-1500:],
        }

    return {
        "status": "ok",
        "output_path": str(out_path),
        "bgm_used": str(bgm_file),
        "bgm_size_bytes": bgm_file.stat().st_size,
        "output_size_bytes": out_path.stat().st_size,
        "loudness": _probe_loudness(out_path),
        "target_loudness_lufs": -14,
        "stdout_tail": (proc.stdout or "")[-800:],
    }


def write_bgm_status(output_dir: Path, status: dict[str, Any]) -> Path:
    path = stage_subdir(output_dir, "bgm_mix_status.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
