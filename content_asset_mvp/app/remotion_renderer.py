from __future__ import annotations

import shutil
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
