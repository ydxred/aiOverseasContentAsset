import json
from pathlib import Path

from app.render_manifest import build_v6_render_manifest
from app.subtitle_engine import build_subtitle_plan
from app.visual_qc import run_visual_qc


def test_build_subtitle_plan_adds_v6_renderer_fields() -> None:
    plan = build_subtitle_plan(
        [{"start": 0.0, "end": 1.8, "text": "这个工具值得关注"}],
        {"shots": [{"start": 0.0, "end": 2.0, "visual_type": "impact_title_card", "screen_text": "值得关注"}]},
    )

    cue = plan["subtitles"][0]
    assert plan["architecture_version"] == "video_pipeline_v6_slice"
    assert cue["start"] == 0.0
    assert cue["highlight_words"]
    assert cue["style"] == "big_claim"
    assert cue["safe_area"]["width"] == 936


def test_visual_qc_reads_artifacts_and_scores(tmp_path: Path) -> None:
    render_status_path = _write_json(tmp_path / "render_status.json", {"subtitle_burned": True})
    quality_path = _write_json(tmp_path / "video_quality_report.json", {"video_quality_score": 88})
    audio_path = _write_json(tmp_path / "audio_mastering_status.json", {"success": True})
    subtitle_path = _write_json(tmp_path / "subtitle_plan.json", {"subtitles": [{"start": 0, "end": 1, "text": "demo"}]})
    shot_path = _write_json(tmp_path / "shot_list.json", {"shots": [{"id": str(index)} for index in range(8)]})

    report = run_visual_qc(
        render_status_path=render_status_path,
        video_quality_report_path=quality_path,
        audio_mastering_status_path=audio_path,
        subtitle_plan_path=subtitle_path,
        shot_list_path=shot_path,
    )

    assert report["pass"] is True
    assert report["score"] == 88
    assert report["hard_failures"] == []


def test_build_v6_render_manifest_links_core_artifacts(tmp_path: Path) -> None:
    manifest = build_v6_render_manifest(
        content_id="demo",
        output_dir=tmp_path,
        platform="douyin",
        composition="DouyinExplainer",
        render_engine="remotion",
        fallback_engine="ffmpeg",
        audio_path=tmp_path / "voice_mastered.mp3",
        subtitle_plan_path=tmp_path / "subtitle_plan.json",
        shot_list_path=tmp_path / "shot_list.json",
        quality_report_path=tmp_path / "video_quality_report.json",
        outputs={"video_path": str(tmp_path / "final_video.mp4")},
        remotion_status={"render_engine_actual": "ffmpeg"},
    )

    assert manifest["architecture_version"] == "video_pipeline_v6_slice"
    assert manifest["render_engine"] == "remotion"
    assert manifest["render_engine_actual"] == "ffmpeg"
    assert manifest["outputs"]["video_path"].endswith("final_video.mp4")


def _write_json(path: Path, data: dict[str, object]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path
