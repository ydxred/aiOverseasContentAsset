from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STAGE_DIRS: tuple[str, ...] = (
    "00_source",
    "01_analysis",
    "02_script",
    "03_visual",
    "04_audio",
    "05_subtitle",
    "06_render_props",
    "07_render_output",
    "08_qc",
    "09_publish",
)


# Authoritative file -> stage subdir map. Files not listed stay flat at output_dir.
STAGE_MAP: dict[str, str] = {
    # 00_source -- raw inputs collected from the world
    "meta.json": "00_source",
    "youtube_candidate.json": "00_source",
    "youtube_transcript.json": "00_source",
    "transcript.json": "00_source",
    "transcript_clean.json": "00_source",
    "transcript_status.json": "00_source",
    "candidate_metadata.json": "00_source",
    "generic_candidate.json": "00_source",
    "github_meta.json": "00_source",
    "readme.md": "00_source",
    "readme_images.json": "00_source",
    "snapshot_status.json": "00_source",
    "browser_agent_status.json": "00_source",
    "browser_agent_assets.json": "00_source",
    "browser_agent_report.json": "00_source",
    "youtube_assets.json": "00_source",
    # 01_analysis -- LLM driven scoring / understanding
    "analysis.json": "01_analysis",
    "github_analysis.json": "01_analysis",
    "score.json": "01_analysis",
    "risk_report.json": "01_analysis",
    "opportunity_engine.json": "01_analysis",
    "quality_check.json": "01_analysis",
    # 02_script -- chinese narration + director plan
    "chinese_script.md": "02_script",
    "title_options.md": "02_script",
    "director_plan.json": "02_script",
    "director_script.md": "02_script",
    "shot_list.json": "02_script",
    "edit_decisions.json": "02_script",
    "review_notes.md": "02_script",
    # 03_visual -- visual asset pack, covers, brand template
    "visual_asset_pack.json": "03_visual",
    "visual_asset_pack": "03_visual",
    "visual_asset_card.png": "03_visual",
    "cover.png": "03_visual",
    "cover_landscape.png": "03_visual",
    "cover_portrait.png": "03_visual",
    "brand_template.json": "03_visual",
    # 04_audio -- TTS + mastering
    "voice.wav": "04_audio",
    "voice.mp3": "04_audio",
    "voice_mastered.mp3": "04_audio",
    "tts_status.json": "04_audio",
    "audio_mastering_status.json": "04_audio",
    "bgm_mix_status.json": "04_audio",
    # 05_subtitle -- subtitle plan + final srt/ass files
    "subtitle_plan.json": "05_subtitle",
    "subtitle_translation_status.json": "05_subtitle",
    "subtitle_word_alignment.json": "05_subtitle",
    "subtitle_word_alignment_status.json": "05_subtitle",
    "subtitles.srt": "05_subtitle",
    "subtitles.zh.srt": "05_subtitle",
    "subtitles.en.srt": "05_subtitle",
    "subtitles.bilingual.srt": "05_subtitle",
    "subtitles.bilingual.ass": "05_subtitle",
    "subtitles.director.zh.ass": "05_subtitle",
    # 06_render_props -- inputs handed to remotion
    "remotion_props_portrait.json": "06_render_props",
    "remotion_props_landscape.json": "06_render_props",
    "render_manifest.v6.json": "06_render_props",
    "video_render_manifest.json": "06_render_props",
    # 07_render_output -- the actual mp4 deliverables
    "final_video.mp4": "07_render_output",
    "final_video_landscape.mp4": "07_render_output",  # legacy alias (pre-2026-05)
    "final_video_portrait.mp4": "07_render_output",
    "final_video_with_bgm.mp4": "07_render_output",
    "platform_renders": "07_render_output",
    # 08_qc -- everything quality / status related
    "video_quality_report.json": "08_qc",
    "visual_qc_report.json": "08_qc",
    "video_self_review.json": "08_qc",
    "self_review_frames": "08_qc",
    "director_quality_checklist.json": "08_qc",
    "render_status.json": "08_qc",
    "landscape_render_status.json": "08_qc",  # legacy stub after 2026-05
    "portrait_render_status.json": "08_qc",
    "remotion_status.json": "08_qc",
    # 09_publish -- distribution plumbing
    "media_job.json": "09_publish",
    "distribution.json": "09_publish",
    "feedback_template.json": "09_publish",
    "publish_review.json": "09_publish",
    "skill_registry.json": "09_publish",
    "auto_run_summary.json": "09_publish",
}


# Suffix-based fallback for files that are emitted with dynamic names but
# clearly belong to one stage (e.g. additional .srt/.ass tracks).
_STAGE_SUFFIX: tuple[tuple[str, str], ...] = (
    (".srt", "05_subtitle"),
    (".ass", "05_subtitle"),
)


def stage_for(filename: str) -> str | None:
    """Return the stage subdir for a given filename, or None if it stays flat."""
    if filename in STAGE_MAP:
        return STAGE_MAP[filename]
    for suffix, stage in _STAGE_SUFFIX:
        if filename.endswith(suffix):
            return stage
    return None


def stage_subdir(output_dir: Path, name: str) -> Path:
    """Resolve ``output_dir / [stage/] name`` with backwards-compat fallback.

    Used by call sites that don't have an ``ArtifactWriter`` handy (a few
    helpers in remotion_renderer / bgm_mixer / video_self_review). When the
    legacy flat path still exists but the staged path doesn't, the legacy
    path wins so we never silently lose access to old artifacts mid-migration.
    """
    stage = stage_for(name)
    if not stage:
        return output_dir / name
    new_path = output_dir / stage / name
    legacy = output_dir / name
    if not new_path.exists() and legacy.exists():
        return legacy
    return new_path


class ArtifactWriter:
    """Per-candidate filesystem facade.

    Files are routed into lifecycle subdirs (``00_source/`` ... ``09_publish/``)
    via :data:`STAGE_MAP`. Reads transparently fall back to the legacy flat
    layout so half-migrated candidates keep working; writes always land in the
    new stage path and clean up any leftover flat copy.
    """

    STAGE_MAP = STAGE_MAP
    STAGE_DIRS = STAGE_DIRS

    def __init__(self, output_dir: Path, workspace_dir: Path, content_id: str):
        self.output_dir = output_dir / content_id
        self.workspace_dir = workspace_dir / content_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _stage_for(filename: str) -> str | None:
        return stage_for(filename)

    def _resolve(self, base: Path, filename: str) -> Path:
        stage = self._stage_for(filename)
        if not stage:
            return base / filename
        new_path = base / stage / filename
        legacy = base / filename
        if not new_path.exists() and legacy.exists():
            return legacy
        return new_path

    def _write_target(self, base: Path, filename: str) -> Path:
        stage = self._stage_for(filename)
        return base / stage / filename if stage else base / filename

    def _cleanup_legacy(self, base: Path, filename: str, target: Path) -> None:
        legacy = base / filename
        if legacy == target or not legacy.exists() or not legacy.is_file():
            return
        try:
            legacy.unlink()
        except OSError:
            pass

    def output_path(self, filename: str) -> Path:
        return self._resolve(self.output_dir, filename)

    def workspace_path(self, filename: str) -> Path:
        return self._resolve(self.workspace_dir, filename)

    def stage_dir(self, stage_name: str, *, workspace: bool = False) -> Path:
        base = self.workspace_dir if workspace else self.output_dir
        return base / stage_name

    def write_json(self, filename: str, data: dict[str, Any], *, workspace: bool = False) -> Path:
        base = self.workspace_dir if workspace else self.output_dir
        path = self._write_target(base, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._cleanup_legacy(base, filename, path)
        return path

    def read_json(self, filename: str, *, workspace: bool = False) -> dict[str, Any]:
        path = self.workspace_path(filename) if workspace else self.output_path(filename)
        return json.loads(path.read_text(encoding="utf-8"))

    def write_markdown(self, filename: str, content: str, *, workspace: bool = False) -> Path:
        base = self.workspace_dir if workspace else self.output_dir
        path = self._write_target(base, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        self._cleanup_legacy(base, filename, path)
        return path

    def exists(self, filename: str, *, workspace: bool = False) -> bool:
        path = self.workspace_path(filename) if workspace else self.output_path(filename)
        return path.exists()
