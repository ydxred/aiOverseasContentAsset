from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audio_mastering import master_voice_audio
from .artifact_writer import ArtifactWriter
from .remotion_renderer import probe_remotion_renderer, render_remotion_video
from .render_manifest import build_v6_render_manifest
from .subtitle_engine import build_subtitle_plan
from .tts_engine import synthesize_narration
from .video_director import assign_scene_timing, build_director_plan, write_director_artifacts
from .visual_qc import run_visual_qc


SCRIPT_HEADING_RE = re.compile(r"^#\s+口播稿\s*$", re.MULTILINE)
TITLE_HEADING_RE = re.compile(r"^#\s+标题\s*$", re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^#\s+", re.MULTILINE)
SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
BRAND_TEMPLATE_ID = "overseas_ai_narrative_v1"
BRAND_NAME = "Overseas AI Radar"


@dataclass(frozen=True)
class RenderResult:
    content_id: str
    script_path: str
    voice_path: str
    subtitle_path: str
    subtitle_zh_path: str
    subtitle_en_path: str
    subtitle_bilingual_path: str
    subtitle_translation_status_path: str
    video_path: str
    cover_path: str
    brand_template_path: str
    visual_asset_path: str
    render_manifest_path: str
    tts_status_path: str
    render_status_path: str
    status: str
    issues: list[str]

    def as_media_job(self) -> dict[str, object]:
        return {
            "content_id": self.content_id,
            "job_type": "short_video",
            "status": self.status,
            "voice_path": self.voice_path,
            "subtitle_path": self.subtitle_path,
            "subtitle_zh_path": self.subtitle_zh_path,
            "subtitle_en_path": self.subtitle_en_path,
            "subtitle_bilingual_path": self.subtitle_bilingual_path,
            "subtitle_translation_status_path": self.subtitle_translation_status_path,
            "video_path": self.video_path,
            "output_path": self.video_path,
            "cover_path": self.cover_path,
            "brand_template_path": self.brand_template_path,
            "visual_asset_path": self.visual_asset_path,
            "render_manifest_path": self.render_manifest_path,
            "script_path": self.script_path,
            "tts_status_path": self.tts_status_path,
            "render_status_path": self.render_status_path,
            "issues": self.issues,
        }


def prepare_media_job(content_id: str, script_path: str, writer: ArtifactWriter) -> dict[str, object]:
    result = {
        "content_id": content_id,
        "status": "skipped",
        "voice_path": "",
        "subtitle_path": "",
        "video_path": "",
        "cover_path": "",
        "script_path": script_path,
        "issues": ["MVP v1 does not generate final video assets."],
    }
    writer.write_json("media_job.json", result)
    return result


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def render_video_package(
    content_id: str,
    writer: ArtifactWriter,
    *,
    openai_api_key: str | None = None,
    force_mock: bool = False,
    bilingual_subtitles: bool = True,
) -> RenderResult:
    script_path = writer.output_path("chinese_script.md")
    if not script_path.exists():
        raise FileNotFoundError(f"chinese_script.md not found for content_id={content_id}")

    script_text = extract_voiceover_text(script_path.read_text(encoding="utf-8"))
    if not script_text:
        raise ValueError("# 口播稿 section is empty")
    director_plan = build_director_plan(content_id, script_path.read_text(encoding="utf-8"), writer)
    script_text = director_plan.voiceover

    ffmpeg = resolve_ffmpeg(writer)
    voice_path, tts_status = synthesize_narration(
        script_text,
        writer.output_path("voice.wav"),
        ffmpeg=ffmpeg,
        openai_api_key=openai_api_key,
        force_mock=force_mock,
    )
    tts_status_path = writer.write_json("tts_status.json", tts_status)
    mastered_voice_path, audio_mastering_status = master_voice_audio(
        voice_path,
        writer.output_path("voice_mastered.mp3"),
        ffmpeg=ffmpeg,
    )
    audio_mastering_status_path = writer.write_json("audio_mastering_status.json", audio_mastering_status)

    duration = probe_audio_duration(mastered_voice_path, ffmpeg=ffmpeg) or probe_audio_duration(voice_path, ffmpeg=ffmpeg) or estimate_duration(script_text)
    director_plan = assign_scene_timing(director_plan, duration)
    write_director_artifacts(writer, director_plan)
    sentences = split_sentences(script_text)
    segments = build_caption_segments(sentences, duration)
    subtitle_plan = build_subtitle_plan(segments, director_plan.as_dict())
    subtitle_plan_path = writer.write_json("subtitle_plan.json", subtitle_plan)
    title = extract_title_text(script_path.read_text(encoding="utf-8")) or content_id
    brand_template = build_brand_template(title, content_id=content_id)
    brand_template_path = writer.write_json("brand_template.json", brand_template)
    cover_path = writer.output_path("cover.png")
    cover_status = render_cover_image(cover_path, brand_template, ffmpeg=ffmpeg)
    visual_asset_source = select_visual_asset(writer)
    visual_asset_path, visual_asset_status = prepare_visual_asset_card(
        visual_asset_source,
        writer.output_path("visual_asset_card.png"),
        ffmpeg=ffmpeg,
    )

    subtitle_zh_path = writer.output_path("subtitles.zh.srt")
    subtitle_zh_path.write_text(build_srt_from_segments(segments, "zh"), encoding="utf-8")

    english_sentences, translation_status = translate_subtitles(
        sentences,
        openai_api_key=openai_api_key,
        force_mock=force_mock,
    )
    translation_status_path = writer.write_json("subtitle_translation_status.json", translation_status)

    subtitle_en_path = writer.output_path("subtitles.en.srt")
    subtitle_en_path.write_text(build_srt_from_segments(segments, "en", english_sentences), encoding="utf-8")

    subtitle_bilingual_path = writer.output_path("subtitles.bilingual.srt")
    subtitle_bilingual_path.write_text(build_bilingual_srt(segments, english_sentences), encoding="utf-8")
    subtitle_ass_path = writer.output_path("subtitles.bilingual.ass")
    subtitle_ass_path.write_text(build_bilingual_ass(segments, english_sentences), encoding="utf-8")
    director_subtitle_ass_path = writer.output_path("subtitles.director.zh.ass")
    director_subtitle_ass_path.write_text(build_director_zh_ass(segments, director_plan.as_dict()), encoding="utf-8")

    subtitle_path = subtitle_bilingual_path if bilingual_subtitles else subtitle_zh_path
    director_style = str(director_plan.style.get("version") or "")
    burned_subtitle_path = director_subtitle_ass_path if director_style.startswith("video_director_v") else (subtitle_ass_path if bilingual_subtitles else subtitle_zh_path)
    burned_subtitle_mode = "director_zh" if director_style.startswith("video_director_v") else ("bilingual" if bilingual_subtitles else "zh")
    legacy_subtitle_path = writer.output_path("subtitles.srt")
    legacy_subtitle_path.write_text(subtitle_path.read_text(encoding="utf-8"), encoding="utf-8")

    project_root = Path(__file__).resolve().parents[1]
    remotion_status = probe_remotion_renderer(project_root)
    video_path = writer.output_path("final_video.mp4")
    render_status: dict[str, Any] = {}
    if remotion_status.get("runtime_available"):
        remotion_status, render_status = render_remotion_video(
            project_root=project_root,
            content_id=content_id,
            title=title,
            duration_seconds=duration,
            audio_path=mastered_voice_path,
            subtitle_plan=subtitle_plan,
            output_dir=writer.output_dir,
            final_video_path=video_path,
            cover_path=cover_path,
            evidence_image_path=visual_asset_path,
        )
    if remotion_status.get("render_engine_actual") != "remotion":
        render_status = render_vertical_video(
            mastered_voice_path,
            burned_subtitle_path,
            video_path,
            duration=duration,
            ffmpeg=ffmpeg,
            subtitle_mode=burned_subtitle_mode,
            brand_template=brand_template,
            cover_status=cover_status,
            visual_asset_path=visual_asset_path,
            visual_asset_status=visual_asset_status,
            director_plan=director_plan.as_dict(),
        )
    remotion_status_path = writer.write_json("remotion_status.json", remotion_status)
    render_status.setdefault("video_path", str(video_path))
    render_status.setdefault("voice_path", str(mastered_voice_path))
    render_status.setdefault("subtitle_path", str(burned_subtitle_path))
    render_status.setdefault("subtitle_mode", burned_subtitle_mode)
    render_status.setdefault("duration_seconds", duration)
    render_status.setdefault("resolution", "1080x1920")
    render_status.setdefault("subtitle_burned", True)
    render_status.setdefault("template_id", brand_template.get("template_id", BRAND_TEMPLATE_ID))
    render_status.setdefault("brand_name", brand_template.get("brand_name", BRAND_NAME))
    render_status.setdefault("cover_status", cover_status or {})
    render_status.setdefault("visual_asset_status", visual_asset_status or {"status": "missing"})
    render_status.setdefault(
        "director_status",
        {
            "status": "enabled",
            "scene_count": len(director_plan.as_dict().get("scenes", [])),
            "shot_count": len(director_plan.as_dict().get("shots", [])),
            "style": director_plan.style.get("version", ""),
        },
    )
    render_status.setdefault("visual_quality", "remotion_douyin_explainer_v1" if remotion_status.get("render_engine_actual") == "remotion" else "brand_template_v1")
    generated_at = _utc_now_iso()
    video_version = str(video_path.stat().st_mtime_ns) if video_path.exists() else ""
    render_status.update(
        {
            "generated_at": generated_at,
            "video_version": video_version,
            "resource_dir": str(writer.output_dir),
            "workspace_dir": str(writer.workspace_dir),
            "output_layout": "one_resource_one_directory",
        }
    )
    render_status_path = writer.write_json("render_status.json", render_status)
    video_quality_report = build_video_quality_report(
        director_plan=director_plan.as_dict(),
        tts_status=tts_status,
        translation_status=translation_status,
        render_status=render_status,
    )
    video_quality_report_path = writer.write_json("video_quality_report.json", video_quality_report)
    visual_qc_report = run_visual_qc(
        render_status_path=render_status_path,
        video_quality_report_path=video_quality_report_path,
        audio_mastering_status_path=audio_mastering_status_path,
        subtitle_plan_path=subtitle_plan_path,
        shot_list_path=writer.output_path("shot_list.json"),
    )
    visual_qc_report_path = writer.write_json("visual_qc_report.json", visual_qc_report)
    render_manifest_v6 = build_v6_render_manifest(
        content_id=content_id,
        output_dir=writer.output_dir,
        platform="douyin",
        composition="DouyinExplainer",
        render_engine="remotion",
        fallback_engine="ffmpeg",
        audio_path=mastered_voice_path,
        subtitle_plan_path=subtitle_plan_path,
        shot_list_path=writer.output_path("shot_list.json"),
        quality_report_path=video_quality_report_path,
        outputs={
            "video_path": str(video_path),
            "cover_path": str(cover_path),
            "render_status_path": str(render_status_path),
            "remotion_status_path": str(remotion_status_path),
            "visual_qc_report_path": str(visual_qc_report_path),
        },
        remotion_status=remotion_status,
    )
    writer.write_json("render_manifest.v6.json", render_manifest_v6)
    render_manifest = build_video_render_manifest(
        content_id=content_id,
        writer=writer,
        generated_at=generated_at,
        video_version=video_version,
        video_path=video_path,
        voice_path=mastered_voice_path,
        burned_subtitle_path=burned_subtitle_path,
        subtitle_mode=burned_subtitle_mode,
        bilingual_subtitles=bilingual_subtitles,
        duration=duration,
        ffmpeg=ffmpeg,
        brand_template=brand_template,
        director_plan=director_plan.as_dict(),
        tts_status=tts_status,
        translation_status=translation_status,
        render_status=render_status,
        video_quality_report=video_quality_report,
        audio_mastering_status=audio_mastering_status,
        remotion_status=remotion_status,
        visual_qc_report=visual_qc_report,
    )
    render_manifest_path = writer.write_json("video_render_manifest.json", render_manifest)

    issues: list[str] = []
    if tts_status.get("mode") != "openai":
        issues.append(str(tts_status.get("reason") or "OpenAI TTS unavailable; used offline fallback."))
    if translation_status.get("mode") != "openai":
        issues.append(str(translation_status.get("reason") or "OpenAI subtitle translation unavailable; used fallback."))
    if render_status.get("subtitle_burned") is False:
        issues.append(str(render_status.get("subtitle_error") or "Subtitle burn failed; rendered video without subtitles."))
    for reason in video_quality_report.get("blocking_reasons", []):
        issues.append(str(reason))

    status = "succeeded" if video_path.exists() and video_path.stat().st_size > 0 else "failed"
    result = RenderResult(
        content_id=content_id,
        script_path=str(script_path),
        voice_path=str(mastered_voice_path),
        subtitle_path=str(subtitle_path),
        subtitle_zh_path=str(subtitle_zh_path),
        subtitle_en_path=str(subtitle_en_path),
        subtitle_bilingual_path=str(subtitle_bilingual_path),
        subtitle_translation_status_path=str(translation_status_path),
        video_path=str(video_path),
        cover_path=str(cover_path),
        brand_template_path=str(brand_template_path),
        visual_asset_path=str(visual_asset_path) if visual_asset_path else "",
        render_manifest_path=str(render_manifest_path),
        tts_status_path=str(tts_status_path),
        render_status_path=str(render_status_path),
        status=status,
        issues=issues,
    )
    writer.write_json("media_job.json", result.as_media_job())
    return result


def build_video_render_manifest(
    *,
    content_id: str,
    writer: ArtifactWriter,
    generated_at: str,
    video_version: str,
    video_path: Path,
    voice_path: Path,
    burned_subtitle_path: Path,
    subtitle_mode: str,
    bilingual_subtitles: bool,
    duration: float,
    ffmpeg: str,
    brand_template: dict[str, Any],
    director_plan: dict[str, Any],
    tts_status: dict[str, Any],
    translation_status: dict[str, Any],
    render_status: dict[str, Any],
    video_quality_report: dict[str, Any] | None = None,
    audio_mastering_status: dict[str, Any] | None = None,
    remotion_status: dict[str, Any] | None = None,
    visual_qc_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    video_quality_report = video_quality_report or {}
    audio_mastering_status = audio_mastering_status or {}
    remotion_status = remotion_status or {}
    visual_qc_report = visual_qc_report or {}
    director_style = (director_plan.get("style", {}) if isinstance(director_plan, dict) else {}).get("version", "")
    shots = director_plan.get("shots", []) if isinstance(director_plan, dict) else []
    shot_count = len(shots) if isinstance(shots, list) else 0
    return {
        "schema_version": 1,
        "content_id": content_id,
        "resource_dir": str(writer.output_dir),
        "workspace_dir": str(writer.workspace_dir),
        "generated_at": generated_at,
        "video_version": video_version,
        "output_layout": {
            "rule": "one_resource_one_directory",
            "video": "final_video.mp4",
            "manifest": "video_render_manifest.json",
            "render_status": "render_status.json",
        },
        "render_parameters": {
            "duration_seconds": duration,
            "ffmpeg": ffmpeg,
            "subtitle_mode": subtitle_mode,
            "bilingual_subtitles": bilingual_subtitles,
            "template_id": brand_template.get("template_id", BRAND_TEMPLATE_ID),
            "brand_name": brand_template.get("brand_name", BRAND_NAME),
            "visual_quality": render_status.get("visual_quality", ""),
            "director_style": director_style,
            "edit_template": (director_plan.get("style", {}) if isinstance(director_plan, dict) else {}).get("edit_template", ""),
            "director_scene_count": len(director_plan.get("scenes", [])) if isinstance(director_plan.get("scenes"), list) else 0,
            "shot_count": shot_count,
            "video_quality_score": video_quality_report.get("video_quality_score", 0),
            "publish_ready": video_quality_report.get("publish_ready", False),
            "tts_mode": tts_status.get("mode", ""),
            "translation_mode": translation_status.get("mode", ""),
            "architecture_version": "video_pipeline_v6_slice",
            "render_engine_preferred": "remotion",
            "render_engine_actual": remotion_status.get("render_engine_actual", "ffmpeg"),
            "audio_mastered": audio_mastering_status.get("success") is True,
            "visual_qc_score": visual_qc_report.get("score", 0),
            "visual_qc_pass": visual_qc_report.get("pass", False),
        },
        "artifacts": {
            "video_path": str(video_path),
            "voice_path": str(voice_path),
            "audio_mastering_status_path": str(writer.output_path("audio_mastering_status.json")),
            "subtitle_plan_path": str(writer.output_path("subtitle_plan.json")),
            "render_manifest_v6_path": str(writer.output_path("render_manifest.v6.json")),
            "remotion_status_path": str(writer.output_path("remotion_status.json")),
            "visual_qc_report_path": str(writer.output_path("visual_qc_report.json")),
            "subtitle_path": str(burned_subtitle_path),
            "render_status_path": str(writer.output_path("render_status.json")),
            "director_plan_path": str(writer.output_path("director_plan.json")),
            "shot_list_path": str(writer.output_path("shot_list.json")),
            "edit_decisions_path": str(writer.output_path("edit_decisions.json")),
            "visual_asset_pack_path": str(writer.output_path("visual_asset_pack.json")),
            "video_quality_report_path": str(writer.output_path("video_quality_report.json")),
            "brand_template_path": str(writer.output_path("brand_template.json")),
            "cover_path": str(writer.output_path("cover.png")),
        },
    }


def build_video_quality_report(
    *,
    director_plan: dict[str, Any],
    tts_status: dict[str, Any],
    translation_status: dict[str, Any],
    render_status: dict[str, Any],
) -> dict[str, Any]:
    shots = director_plan.get("shots", []) if isinstance(director_plan, dict) else []
    assets = director_plan.get("assets", []) if isinstance(director_plan, dict) else []
    duration = float(render_status.get("duration_seconds") or 0.0)
    visual_types = {str(shot.get("visual_type")) for shot in shots if isinstance(shot, dict) and shot.get("visual_type")}
    real_asset_types = {str(asset.get("role")) for asset in assets if isinstance(asset, dict) and asset.get("path")}
    shot_count = len(shots) if isinstance(shots, list) else 0
    expected_shots = max(1, int(duration / 4.5)) if duration else max(1, shot_count)
    visual_density_score = min(100, int(shot_count / expected_shots * 88)) if expected_shots else 0
    asset_diversity_score = min(100, 36 + len(real_asset_types) * 24 + len(visual_types) * 6)
    subtitle_quality_score = 86 if render_status.get("subtitle_burned") is not False else 40
    voice_quality_score = 92 if tts_status.get("mode") == "openai" else 25
    hook_strength_score = 86 if any(str(shot.get("visual_type")) == "impact_title_card" for shot in shots if isinstance(shot, dict)) else 55
    video_quality_score = int(
        round(
            visual_density_score * 0.24
            + asset_diversity_score * 0.22
            + subtitle_quality_score * 0.18
            + voice_quality_score * 0.22
            + hook_strength_score * 0.14
        )
    )
    blocking_reasons: list[str] = []
    if tts_status.get("mode") != "openai":
        blocking_reasons.append("Voice is offline silence/TTS fallback; publish requires real narration.")
    if len(real_asset_types) < 2:
        blocking_reasons.append("Visual asset diversity is too low; need at least two real asset types.")
    if shot_count < 8:
        blocking_reasons.append("Shot list is too thin for v4 industrial pacing.")
    if render_status.get("subtitle_burned") is False:
        blocking_reasons.append("Subtitle burn failed; final video is not publish-ready.")
    publish_ready = not blocking_reasons and video_quality_score >= 75
    suggestions = [
        "Add repo screenshots plus README visuals so evidence and explanation shots do not rely on cards only.",
        "Replace offline silence with real Chinese narration before publishing.",
        "Materialize cropped evidence/card assets inside visual_asset_pack directories.",
    ]
    return {
        "schema_version": 1,
        "video_quality_score": video_quality_score,
        "visual_density_score": visual_density_score,
        "asset_diversity_score": asset_diversity_score,
        "subtitle_quality_score": subtitle_quality_score,
        "voice_quality_score": voice_quality_score,
        "hook_strength_score": hook_strength_score,
        "publish_ready": publish_ready,
        "blocking_reasons": blocking_reasons,
        "suggestions": suggestions,
        "metrics": {
            "shot_count": shot_count,
            "visual_type_count": len(visual_types),
            "real_asset_type_count": len(real_asset_types),
            "tts_mode": tts_status.get("mode", ""),
            "translation_mode": translation_status.get("mode", ""),
        },
    }


def extract_voiceover_text(markdown: str) -> str:
    match = SCRIPT_HEADING_RE.search(markdown)
    if not match:
        return ""
    next_match = NEXT_HEADING_RE.search(markdown, match.end())
    section = markdown[match.end() : next_match.start() if next_match else len(markdown)]
    lines = [clean_voiceover_line(line) for line in section.strip().splitlines()]
    return "\n".join(line for line in lines if line).strip()


def clean_voiceover_line(line: str) -> str:
    text = line.strip()
    if not text:
        return ""
    if re.match(r"^#{1,6}\s+", text):
        return ""
    text = re.sub(r"^[-*+]\s+", "", text)
    text = re.sub(r"^\d+[.)]\s+", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("#", "")
    return " ".join(text.split())


def extract_title_text(markdown: str) -> str:
    match = TITLE_HEADING_RE.search(markdown)
    if not match:
        return ""
    next_match = NEXT_HEADING_RE.search(markdown, match.end())
    section = markdown[match.end() : next_match.start() if next_match else len(markdown)]
    lines = [line.strip() for line in section.strip().splitlines() if line.strip()]
    return lines[0] if lines else ""


def split_sentences(text: str) -> list[str]:
    sentences = [match.group(0).strip() for match in SENTENCE_RE.finditer(text.replace("\r", "\n"))]
    return [sentence for sentence in sentences if sentence]


def build_srt(sentences: list[str], duration_seconds: float) -> str:
    segments = build_caption_segments(sentences, duration_seconds)
    return build_srt_from_segments(segments, "zh")


@dataclass(frozen=True)
class CaptionSegment:
    index: int
    start: float
    end: float
    text: str


def build_caption_segments(sentences: list[str], duration_seconds: float) -> list[CaptionSegment]:
    if not sentences:
        return []
    duration_seconds = max(duration_seconds, len(sentences) * 1.2)
    weights = [max(1, len(sentence)) for sentence in sentences]
    total_weight = sum(weights)
    cursor = 0.0
    segments: list[CaptionSegment] = []
    for index, (sentence, weight) in enumerate(zip(sentences, weights), start=1):
        segment = max(1.2, duration_seconds * weight / total_weight)
        start = cursor
        end = duration_seconds if index == len(sentences) else min(duration_seconds, cursor + segment)
        segments.append(CaptionSegment(index=index, start=start, end=end, text=sentence))
        cursor = end
    return segments


def build_srt_from_segments(segments: list[CaptionSegment], language: str, translated_sentences: list[str] | None = None) -> str:
    blocks: list[str] = []
    for offset, segment in enumerate(segments):
        text = segment.text if language == "zh" else _translated_text(translated_sentences, offset)
        blocks.append(f"{segment.index}\n{format_srt_time(segment.start)} --> {format_srt_time(segment.end)}\n{text}\n")
    if not blocks:
        return ""
    return "\n".join(blocks).rstrip() + "\n"


def build_bilingual_srt(segments: list[CaptionSegment], english_sentences: list[str]) -> str:
    blocks: list[str] = []
    for offset, segment in enumerate(segments):
        english = _translated_text(english_sentences, offset)
        blocks.append(
            f"{segment.index}\n"
            f"{format_srt_time(segment.start)} --> {format_srt_time(segment.end)}\n"
            f"{segment.text}\n"
            f"{english}\n"
        )
    if not blocks:
        return ""
    return "\n".join(blocks).rstrip() + "\n"


def build_bilingual_ass(segments: list[CaptionSegment], english_sentences: list[str]) -> str:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,48,&H00FFFFFF,&H00FFFFFF,&HAA000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,90,90,210,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header.rstrip()]
    for offset, segment in enumerate(segments):
        english = _translated_text(english_sentences, offset)
        caption = f"{_ass_wrap(segment.text, 18)}\\N{{\\fs34}}{_ass_wrap(english, 30)}"
        lines.append(
            f"Dialogue: 0,{format_ass_time(segment.start)},{format_ass_time(segment.end)},Default,,0,0,0,,{caption}"
        )
    return "\n".join(lines).rstrip() + "\n"


def build_director_zh_ass(segments: list[CaptionSegment], director_plan: dict[str, Any] | None = None) -> str:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,58,&H00FFFFFF,&H00FFFFFF,&HAA000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,1,2,80,80,260,1
Style: Scene,Noto Sans CJK SC,50,&H0000D7FF,&H0000D7FF,&HAA000000,&H90000000,-1,0,0,0,100,100,0,0,1,3,1,8,70,70,125,1
Style: Shot,Noto Sans CJK SC,72,&H0000D7FF,&H0000D7FF,&HAA000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,1,5,90,90,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header.rstrip()]
    scenes = director_plan.get("scenes", []) if isinstance(director_plan, dict) else []
    shots = director_plan.get("shots", []) if isinstance(director_plan, dict) else []
    if isinstance(scenes, list):
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            screen_text = str(scene.get("screen_text") or scene.get("label") or "").strip()
            if not screen_text:
                continue
            start = float(scene.get("start") or 0.0)
            end = float(scene.get("end") or start + 1.0)
            lines.append(
                f"Dialogue: 1,{format_ass_time(start)},{format_ass_time(end)},Scene,,0,0,0,,{_ass_escape(screen_text)}"
            )
    if isinstance(shots, list):
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            shot_text = _shot_overlay_ass_text(shot)
            if not shot_text:
                continue
            start = float(shot.get("start") or 0.0)
            end = float(shot.get("end") or start + 1.0)
            lines.append(
                f"Dialogue: 2,{format_ass_time(start)},{format_ass_time(end)},Shot,,0,0,0,,{shot_text}"
            )
    for segment in segments:
        caption = _ass_wrap(segment.text, 20, max_lines=4)
        lines.append(
            f"Dialogue: 0,{format_ass_time(segment.start)},{format_ass_time(segment.end)},Default,,0,0,0,,{caption}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _shot_overlay_ass_text(shot: dict[str, Any]) -> str:
    visual_type = str(shot.get("visual_type") or "")
    if visual_type not in {"impact_title_card", "keyword_punch_card", "judgement_card"}:
        return ""
    screen_text = str(shot.get("screen_text") or "").strip()
    if not screen_text:
        return ""
    y = 605 if visual_type != "judgement_card" else 650
    return f"{{\\pos(540,{y})}}{_ass_wrap(screen_text, 11, max_lines=3)}"


def _translated_text(translated_sentences: list[str] | None, offset: int) -> str:
    if translated_sentences and offset < len(translated_sentences) and translated_sentences[offset].strip():
        return translated_sentences[offset].strip()
    return f"English summary for segment {offset + 1}."


def format_srt_time(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100)))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centis = divmod(remainder, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def estimate_duration(text: str) -> float:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    other_words = len(re.findall(r"[A-Za-z0-9]+", text))
    return max(4.0, min(180.0, chinese_chars / 4.2 + other_words / 2.6 + 1.5))


def resolve_ffmpeg(writer: ArtifactWriter) -> str:
    candidates: list[Path] = [
        Path(sys.executable).resolve().parent / "ffmpeg",
        writer.output_dir.parents[1] / ".venv" / "bin" / "ffmpeg",
        writer.output_dir.parent.parent / ".venv" / "bin" / "ffmpeg",
    ]
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        candidates.append(Path(system_ffmpeg))
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    try:
        import imageio_ffmpeg

        bundled_ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if bundled_ffmpeg.exists():
            return str(bundled_ffmpeg)
    except Exception:
        pass
    raise FileNotFoundError("ffmpeg is required to render video")


def synthesize_voice(
    text: str,
    output_path: Path,
    *,
    ffmpeg: str,
    openai_api_key: str | None,
    force_mock: bool = False,
) -> tuple[Path, dict[str, Any]]:
    if not force_mock and openai_api_key:
        try:
            mp3_path = output_path.with_suffix(".mp3")
            _openai_tts(text, mp3_path, openai_api_key=openai_api_key)
            return mp3_path, {
                "status": "succeeded",
                "mode": "openai",
                "model": "gpt-4o-mini-tts/tts-1 compatible",
                "voice_path": str(mp3_path),
                "text_chars": len(text),
            }
        except Exception as exc:  # pragma: no cover - depends on network/provider availability.
            reason = f"OpenAI TTS failed: {_safe_error_message(exc)}"
    else:
        reason = "video mock mode enabled" if force_mock else "OPENAI_API_KEY is not configured"

    duration = estimate_duration(text)
    _generate_silent_audio(output_path, duration, ffmpeg=ffmpeg)
    return output_path, {
        "status": "succeeded",
        "mode": "offline_silence",
        "reason": reason,
        "voice_path": str(output_path),
        "duration_seconds": duration,
        "text_chars": len(text),
    }


def translate_subtitles(
    sentences: list[str],
    *,
    openai_api_key: str | None,
    force_mock: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    if not sentences:
        return [], {
            "status": "succeeded",
            "mode": "empty",
            "sentence_count": 0,
        }

    if not force_mock and openai_api_key:
        try:
            translations = _openai_translate_subtitles(sentences, openai_api_key=openai_api_key)
            return translations, {
                "status": "succeeded",
                "mode": "openai",
                "model": "gpt-4o-mini",
                "sentence_count": len(sentences),
            }
        except Exception as exc:  # pragma: no cover - depends on network/provider availability.
            reason = f"OpenAI subtitle translation failed: {_safe_error_message(exc)}"
    else:
        reason = "video mock mode enabled" if force_mock else "OPENAI_API_KEY is not configured"

    translations = [_fallback_english_caption(sentence, index) for index, sentence in enumerate(sentences, start=1)]
    return translations, {
        "status": "succeeded",
        "mode": "mock_placeholder" if force_mock else "fallback_placeholder",
        "reason": reason,
        "sentence_count": len(sentences),
    }


def _openai_translate_subtitles(sentences: list[str], *, openai_api_key: str) -> list[str]:
    from openai import OpenAI

    client = OpenAI(api_key=openai_api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Translate Simplified Chinese short-video subtitles into natural, concise English. "
                    "Return only JSON with key translations, an array of strings. Preserve the number and order of lines."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"sentences": sentences}, ensure_ascii=False),
            },
        ],
    )
    text = response.choices[0].message.content or ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI returned invalid translation JSON: {exc}") from exc
    translations = parsed.get("translations") if isinstance(parsed, dict) else None
    if not isinstance(translations, list):
        raise RuntimeError("OpenAI translation response missed translations list")
    cleaned = [str(item).strip() for item in translations]
    if len(cleaned) != len(sentences) or any(not item for item in cleaned):
        raise RuntimeError("OpenAI translation response length mismatch")
    return cleaned


def _fallback_english_caption(sentence: str, index: int) -> str:
    topic = "this point"
    if "AI" in sentence or "人工智能" in sentence:
        topic = "AI content production"
    elif "审核" in sentence:
        topic = "human review"
    elif "脚本" in sentence:
        topic = "the Chinese script"
    elif "视频" in sentence:
        topic = "video production"
    return f"Conservative English placeholder {index}: {topic}."


def _openai_tts(text: str, output_path: Path, *, openai_api_key: str) -> None:
    from openai import OpenAI

    client = OpenAI(api_key=openai_api_key)
    last_error: Exception | None = None
    for model in ("gpt-4o-mini-tts", "tts-1"):
        try:
            response = client.audio.speech.create(model=model, voice="alloy", input=text)
            if hasattr(response, "stream_to_file"):
                response.stream_to_file(str(output_path))
            else:
                output_path.write_bytes(response.read())
            if output_path.exists() and output_path.stat().st_size > 0:
                return
        except Exception as exc:  # pragma: no cover - depends on installed SDK/provider state.
            last_error = exc
    raise RuntimeError(last_error or "OpenAI TTS produced no output")


def _safe_error_message(exc: Exception) -> str:
    message = str(exc)
    message = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", message)
    message = re.sub(r"(?i)(api[-_ ]?key[=:]\s*)[A-Za-z0-9_-]+", r"\1***", message)
    return message[-500:]


def _generate_silent_audio(output_path: Path, duration: float, *, ffmpeg: str) -> None:
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )


def probe_audio_duration(audio_path: Path, *, ffmpeg: str) -> float | None:
    ffprobe_path = str(Path(ffmpeg).with_name("ffprobe"))
    if not Path(ffprobe_path).exists():
        ffprobe_path = shutil.which("ffprobe") or ""
    if ffprobe_path:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            try:
                return float(json.loads(result.stdout)["format"]["duration"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass
    return None


def build_brand_template(title: str, *, content_id: str) -> dict[str, Any]:
    cover_title = _compact_text(title, max_chars=34)
    return {
        "template_id": BRAND_TEMPLATE_ID,
        "brand_name": BRAND_NAME,
        "content_id": content_id,
        "cover_title": cover_title,
        "safe_title": _ascii_overlay_text(cover_title) or "AI Opportunity Brief",
        "headline": "OVERSEAS AI RADAR",
        "subheadline": "Chinese narrative asset",
        "footer": "Observation, not income advice",
        "resolution": "1080x1920",
        "palette": {
            "background": "#0f172a",
            "panel": "#111827",
            "accent": "#38bdf8",
            "accent_secondary": "#a78bfa",
            "text": "#f8fafc",
            "muted": "#cbd5e1",
        },
        "layers": [
            "top brand bar",
            "center narrative title card",
            "left accent rail",
            "bottom source-boundary footer",
            "bilingual subtitle safe area",
        ],
    }


def render_cover_image(cover_path: Path, brand_template: dict[str, Any], *, ffmpeg: str) -> dict[str, Any]:
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    filter_chain = _brand_filter(brand_template, include_subtitle_safe_area=False)
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=#0f172a:s=1080x1920:r=1",
        "-frames:v",
        "1",
        "-vf",
        filter_chain,
        str(cover_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if result.returncode == 0 and cover_path.exists() and cover_path.stat().st_size > 0:
        return {"status": "succeeded", "cover_path": str(cover_path)}
    return {
        "status": "failed",
        "cover_path": str(cover_path),
        "error": (result.stderr or result.stdout or "cover render failed")[-1000:],
    }


def select_visual_asset(writer: ArtifactWriter) -> Path | None:
    snapshot_status = _read_json_if_exists(writer.output_path("snapshot_status.json"))
    screenshots = snapshot_status.get("screenshots") if isinstance(snapshot_status, dict) else None
    if isinstance(screenshots, list):
        for screenshot in screenshots:
            if not isinstance(screenshot, dict):
                continue
            path = _existing_image_path(screenshot.get("workspace_path"))
            if path:
                return path

    readme_images = _read_json_if_exists(writer.output_path("readme_images.json"))
    images = readme_images.get("images") if isinstance(readme_images, dict) else None
    if isinstance(images, list):
        for image in images:
            if not isinstance(image, dict):
                continue
            path = _existing_image_path(image.get("workspace_path"))
            if path and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                return path
    return None


def prepare_visual_asset_card(source_path: Path | None, output_path: Path, *, ffmpeg: str) -> tuple[Path | None, dict[str, Any]]:
    if source_path is None:
        return None, {"status": "missing", "reason": "No screenshot or README image was available."}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_path),
        "-vf",
        "scale=936:760:force_original_aspect_ratio=increase,crop=936:760:(iw-936)/2:0,setsar=1",
        "-frames:v",
        "1",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        return output_path, {
            "status": "succeeded",
            "source_path": str(source_path),
            "visual_asset_path": str(output_path),
            "placement": "center evidence card",
        }
    return None, {
        "status": "failed",
        "source_path": str(source_path),
        "error": (result.stderr or result.stdout or "visual asset preparation failed")[-1000:],
    }


def render_vertical_video(
    voice_path: Path,
    subtitle_path: Path,
    video_path: Path,
    *,
    duration: float,
    ffmpeg: str,
    subtitle_mode: str = "bilingual",
    brand_template: dict[str, Any] | None = None,
    cover_status: dict[str, Any] | None = None,
    visual_asset_path: Path | None = None,
    visual_asset_status: dict[str, Any] | None = None,
    director_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    brand_template = brand_template or build_brand_template("AI Opportunity Brief", content_id=video_path.parent.name)
    status: dict[str, Any] = {
        "status": "started",
        "video_path": str(video_path),
        "voice_path": str(voice_path),
        "subtitle_path": str(subtitle_path),
        "subtitle_mode": subtitle_mode,
        "duration_seconds": duration,
        "resolution": "1080x1920",
        "subtitle_burned": True,
        "template_id": brand_template.get("template_id", BRAND_TEMPLATE_ID),
        "brand_name": brand_template.get("brand_name", BRAND_NAME),
        "cover_status": cover_status or {},
        "visual_asset_status": visual_asset_status or {"status": "missing"},
        "director_status": {
            "status": "enabled" if director_plan else "disabled",
            "scene_count": len(director_plan.get("scenes", [])) if director_plan else 0,
            "shot_count": len(director_plan.get("shots", [])) if director_plan and isinstance(director_plan.get("shots"), list) else 0,
            "style": (director_plan.get("style", {}) if director_plan else {}).get("version", ""),
        },
        "visual_quality": "brand_template_v1",
        "visual_layers": brand_template.get("layers", []),
    }
    video_filter = _compose_video_filter(brand_template, subtitle_path)
    shot_assets = _director_shot_asset_paths(director_plan)
    scene_assets = shot_assets or _director_scene_asset_paths(director_plan)
    if scene_assets:
        _render_director_video(
            ffmpeg,
            voice_path,
            subtitle_path,
            video_path,
            duration=duration,
            brand_template=brand_template,
            scene_assets=scene_assets,
        )
        if video_path.exists() and video_path.stat().st_size > 0:
            status["status"] = "succeeded"
            status["director_status"]["render_mode"] = "shot_segmented_concat" if shot_assets else "segmented_concat"
            director_style = str((director_plan or {}).get("style", {}).get("version", ""))
            status["visual_quality"] = "director_v4_multi_shot" if director_style.startswith("video_director_v4") else ("director_v3_large_scene" if director_style.startswith("video_director_v3") else "brand_template_v1")
            return status

    command = _video_command(
        ffmpeg,
        voice_path,
        video_path,
        duration=duration,
        video_filter=video_filter,
        visual_asset_path=visual_asset_path,
    )
    result = subprocess.run(command, capture_output=True, text=True, timeout=max(120, math.ceil(duration) + 60))
    if result.returncode == 0 and video_path.exists() and video_path.stat().st_size > 0:
        status["status"] = "succeeded"
        return status

    status["subtitle_burned"] = False
    status["subtitle_error"] = (result.stderr or result.stdout or "subtitle render failed")[-2000:]
    fallback = subprocess.run(
        _video_command(ffmpeg, voice_path, video_path, duration=duration, video_filter=None, visual_asset_path=None),
        capture_output=True,
        text=True,
        timeout=max(120, math.ceil(duration) + 60),
    )
    if fallback.returncode != 0:
        status["status"] = "failed"
        status["error"] = (fallback.stderr or fallback.stdout or "video render failed")[-2000:]
        raise RuntimeError(status["error"])
    status["status"] = "succeeded"
    return status


def _video_command(
    ffmpeg: str,
    voice_path: Path,
    video_path: Path,
    *,
    duration: float,
    video_filter: str | None,
    visual_asset_path: Path | None = None,
    director_plan: dict[str, Any] | None = None,
) -> list[str]:
    _ = director_plan
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=#0f172a:s=1080x1920:r=30",
    ]
    if visual_asset_path:
        command.extend(["-loop", "1", "-i", str(visual_asset_path), "-i", str(voice_path)])
        audio_input_index = "2:a"
    else:
        command.extend(["-i", str(voice_path)])
        audio_input_index = "1:a"
    command.extend([
        "-t",
        f"{duration:.3f}",
    ])
    if video_filter:
        if visual_asset_path:
            command.extend(["-filter_complex", f"[0:v]{video_filter}[base];[base][1:v]overlay=72:352:format=auto[v]", "-map", "[v]", "-map", audio_input_index])
        else:
            command.extend(["-vf", video_filter])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(video_path),
        ]
    )
    return command


def _render_director_video(
    ffmpeg: str,
    voice_path: Path,
    subtitle_path: Path,
    video_path: Path,
    *,
    duration: float,
    brand_template: dict[str, Any],
    scene_assets: list[dict[str, Any]],
) -> None:
    segments_dir = video_path.parent / "director_segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []
    for index, scene in enumerate(scene_assets, start=1):
        start = float(scene.get("start") or 0.0)
        end = float(scene.get("end") or start + 1.0)
        segment_duration = max(0.8, min(duration, end) - start)
        segment_path = segments_dir / f"scene_{index:02d}.mp4"
        asset_path = scene.get("asset_path")
        command = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=#0f172a:s=1080x1920:r=30",
        ]
        if asset_path:
            command.extend(["-loop", "1", "-i", str(asset_path)])
            filter_complex = (
                f"[0:v]{_brand_filter(brand_template)}[base];"
                f"[1:v]{_asset_card_filter(scene, segment_duration)}[asset];"
                f"[base][asset]overlay={_asset_overlay_position(scene)}:format=auto[tmp];"
                f"[tmp]{_shot_style_filter(scene)}[v]"
            )
        else:
            filter_complex = f"[0:v]{_brand_filter(brand_template)},{_shot_style_filter(scene)}[v]"
        command.extend(
            [
                "-t",
                f"{segment_duration:.3f}",
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                str(segment_path),
            ]
        )
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=max(60, math.ceil(segment_duration) + 45),
        )
        segment_paths.append(segment_path)

    concat_list = segments_dir / "concat.txt"
    concat_list.write_text("\n".join(f"file '{_concat_escape(path)}'" for path in segment_paths) + "\n", encoding="utf-8")
    visual_track = segments_dir / "visual_track.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(visual_track),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=max(60, math.ceil(duration) + 45),
    )
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(visual_track),
            "-i",
            str(voice_path),
            "-t",
            f"{duration:.3f}",
            "-vf",
            _subtitle_filter(subtitle_path),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=max(120, math.ceil(duration) + 60),
    )


def _concat_escape(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def _asset_card_filter(scene: dict[str, Any], duration: float) -> str:
    role = str(scene.get("role") or "")
    visual_type = str(scene.get("visual_type") or "")
    motion = str(scene.get("motion") or "slow_push")
    frames = max(24, int(math.ceil(duration * 30)))
    if visual_type == "repo_full_bleed":
        base = "scale=1080:1220:force_original_aspect_ratio=increase,crop=1080:1220:(iw-1080)/2:0"
    elif role == "readme_image" or visual_type == "readme_visual_card":
        base = "scale=1000:920:force_original_aspect_ratio=decrease,pad=1000:920:(ow-iw)/2:(oh-ih)/2:color=#020617"
    else:
        base = "scale=1000:920:force_original_aspect_ratio=increase,crop=1000:920:(iw-1000)/2:0"
    if motion == "snap_zoom":
        zoom = "zoompan=z='min(zoom+0.0020,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        return f"{base},{zoom}:d={frames}:s=1000x920:fps=30,setsar=1"
    if motion in {"slow_push", "quick_push", "push_right"}:
        step = "0.0014" if motion == "quick_push" else "0.0007"
        zoom = f"zoompan=z='min(zoom+{step},1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        return f"{base},{zoom}:d={frames}:s=1000x920:fps=30,setsar=1"
    return f"{base},setsar=1"


def _asset_overlay_position(scene: dict[str, Any]) -> str:
    visual_type = str(scene.get("visual_type") or "")
    if visual_type == "repo_full_bleed":
        return "0:206"
    if visual_type == "repo_evidence_zoom":
        return "40:280"
    if visual_type == "readme_visual_card":
        return "40:300"
    return "40:240"


def _shot_style_filter(scene: dict[str, Any]) -> str:
    visual_type = str(scene.get("visual_type") or "")
    highlight = str(scene.get("highlight") or "")
    styles = {
        "impact_title_card": "drawbox=x=72:y=300:w=936:h=520:color=#111827@0.92:t=fill,drawbox=x=112:y=350:w=760:h=10:color=#38bdf8@0.95:t=fill,drawbox=x=112:y=440:w=520:h=8:color=#a78bfa@0.90:t=fill,drawbox=x=112:y=560:w=820:h=180:color=#020617@0.72:t=fill",
        "keyword_punch_card": "drawbox=x=96:y=430:w=888:h=430:color=#172554@0.88:t=fill,drawbox=x=136:y=500:w=620:h=12:color=#38bdf8@0.95:t=fill,drawbox=x=136:y=610:w=770:h=100:color=#0f172a@0.86:t=fill",
        "judgement_card": "drawbox=x=72:y=360:w=936:h=620:color=#111827@0.94:t=fill,drawbox=x=112:y=420:w=14:h=460:color=#f59e0b@0.95:t=fill,drawbox=x=160:y=500:w=760:h=10:color=#f59e0b@0.92:t=fill",
        "repo_full_bleed": "drawbox=x=0:y=206:w=1080:h=6:color=#38bdf8@0.95:t=fill,drawbox=x=0:y=1426:w=1080:h=6:color=#38bdf8@0.85:t=fill",
        "repo_evidence_zoom": "drawbox=x=52:y=292:w=976:h=896:color=#38bdf8@0.22:t=6",
        "readme_visual_card": "drawbox=x=52:y=312:w=976:h=896:color=#a78bfa@0.24:t=6",
    }
    return ",".join([styles.get(visual_type, "null"), _highlight_filter(highlight)])


def _highlight_filter(highlight: str) -> str:
    boxes = {
        "stars": "drawbox=x=790:y=310:w=210:h=70:color=#38bdf8@0.60:t=6",
        "repo_about": "drawbox=x=760:y=360:w=245:h=230:color=#a78bfa@0.55:t=6",
        "repo_header": "drawbox=x=40:y=240:w=1000:h=96:color=#38bdf8@0.48:t=6",
        "center": "drawbox=x=85:y=340:w=910:h=540:color=#38bdf8@0.40:t=6",
        "chart": "drawbox=x=70:y=320:w=940:h=390:color=#38bdf8@0.40:t=6",
    }
    return boxes.get(highlight, "null")


def _director_shot_asset_paths(director_plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not director_plan:
        return []
    shots = director_plan.get("shots")
    if not isinstance(shots, list):
        return []
    selected: list[dict[str, Any]] = []
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        raw_asset_path = str(shot.get("asset_path") or "")
        asset_path = Path(raw_asset_path) if raw_asset_path else None
        selected.append(
            {
                "asset_path": asset_path if asset_path and asset_path.exists() and asset_path.is_file() else None,
                "start": float(shot.get("start") or 0.0),
                "end": float(shot.get("end") or 0.0),
                "role": str(shot.get("visual_type") or ""),
                "visual_type": str(shot.get("visual_type") or ""),
                "motion": str(shot.get("motion") or ""),
                "highlight": str(shot.get("highlight") or ""),
            }
        )
    return selected


def _director_scene_asset_paths(director_plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not director_plan:
        return []
    scenes = director_plan.get("scenes")
    if not isinstance(scenes, list):
        return []
    selected: list[dict[str, Any]] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        asset_path = Path(str(scene.get("asset_path") or ""))
        if not asset_path.exists() or not asset_path.is_file():
            continue
        selected.append(
            {
                "asset_path": asset_path,
                "start": float(scene.get("start") or 0.0),
                "end": float(scene.get("end") or 0.0),
                "role": str(scene.get("visual_role") or ""),
                "motion": str(scene.get("motion") or ""),
                "highlight": str(scene.get("highlight") or ""),
            }
        )
    return selected


def _subtitle_filter(subtitle_path: Path) -> str:
    escaped_path = str(subtitle_path).replace("\\", "\\\\").replace("'", "\\'")
    if subtitle_path.suffix.lower() == ".ass":
        return f"ass=filename='{escaped_path}'"
    style = (
        "FontName=Noto Sans CJK SC,"
        "FontSize=42,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H80000000,"
        "BorderStyle=1,"
        "Outline=2,"
        "Alignment=2,"
        "MarginL=90,"
        "MarginR=90,"
        "MarginV=240"
    )
    return f"subtitles=filename='{escaped_path}':original_size=1080x1920:force_style='{style}'"


def _ass_wrap(value: str, max_chars: int, *, max_lines: int = 2) -> str:
    text = " ".join(str(value).split())
    if len(text) <= max_chars:
        return _ass_escape(text)
    lines: list[str] = []
    current = ""
    for token in _wrap_tokens(text):
        if current and len(current) + len(token) > max_chars:
            lines.append(current.rstrip())
            current = token
        else:
            current += token
    if current:
        lines.append(current.rstrip())
    return "\\N".join(_ass_escape(line) for line in lines[:max_lines])


def _wrap_tokens(text: str) -> list[str]:
    if re.search(r"[\u4e00-\u9fff]", text):
        return re.findall(r"[A-Za-z0-9_.+-]+|.", text)
    return [token + " " for token in text.split()]


def _ass_escape(value: str) -> str:
    return str(value).replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _existing_image_path(value: object) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    if path.exists() and path.is_file():
        return path
    return None


def _compose_video_filter(brand_template: dict[str, Any], subtitle_path: Path) -> str:
    return ",".join([_brand_filter(brand_template), _subtitle_filter(subtitle_path)])


def _brand_filter(brand_template: dict[str, Any], *, include_subtitle_safe_area: bool = True) -> str:
    _ = brand_template
    filters = [
        "drawbox=x=0:y=0:w=1080:h=1920:color=#0f172a:t=fill",
        "drawbox=x=40:y=72:w=1000:h=118:color=#111827@0.94:t=fill",
        "drawbox=x=40:y=72:w=14:h=118:color=#38bdf8:t=fill",
        "drawbox=x=40:y=240:w=1000:h=920:color=#020617@0.72:t=fill",
        "drawbox=x=40:y=240:w=1000:h=6:color=#a78bfa@0.95:t=fill",
        "drawbox=x=58:y=1198:w=964:h=92:color=#111827@0.88:t=fill",
        "drawbox=x=82:y=1227:w=380:h=4:color=#38bdf8@0.95:t=fill",
        "drawbox=x=82:y=1254:w=610:h=3:color=#64748b@0.85:t=fill",
        "drawbox=x=72:y=1668:w=936:h=96:color=#111827@0.84:t=fill",
        "drawbox=x=108:y=1700:w=360:h=3:color=#64748b@0.85:t=fill",
        "drawbox=x=108:y=1726:w=520:h=3:color=#475569@0.80:t=fill",
        "drawbox=x=72:y=1808:w=936:h=8:color=#38bdf8@0.85:t=fill",
    ]
    if include_subtitle_safe_area:
        filters.append("drawbox=x=64:y=1360:w=952:h=250:color=#020617@0.38:t=fill")
    return ",".join(filters)


def _ascii_overlay_text(value: str) -> str:
    cleaned = re.sub(r"[\r\n]+", " ", value).strip()
    if not cleaned:
        return ""
    ascii_text = cleaned.encode("ascii", "ignore").decode("ascii").strip()
    if ascii_text:
        return _compact_text(ascii_text, max_chars=42)
    return "AI Opportunity Brief"


def _compact_text(value: str, *, max_chars: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "..."

