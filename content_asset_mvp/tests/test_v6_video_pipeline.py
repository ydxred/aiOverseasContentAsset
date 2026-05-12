import json
from pathlib import Path

from app.remotion_renderer import render_remotion_video
from app.render_manifest import build_v6_render_manifest
from app.skill_registry import build_skill_registry_report, list_project_skills
from app.subtitle_engine import build_subtitle_plan
from app.video_self_review import run_video_self_review
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


def test_project_skill_registry_marks_active_skills() -> None:
    skills = list_project_skills()
    report = build_skill_registry_report(active_skill_ids=["remotion-shotlist-renderer"])

    assert any(skill["skill_id"] == "remotion-shotlist-renderer" for skill in skills)
    by_id = {skill["skill_id"]: skill for skill in report["skills"]}
    assert by_id["remotion-shotlist-renderer"]["used_in_current_run"] is True
    assert by_id["video-self-review"]["used_in_current_run"] is False


def test_video_self_review_reports_missing_video(tmp_path: Path) -> None:
    report = run_video_self_review(
        video_path=tmp_path / "missing.mp4",
        output_dir=tmp_path,
        ffmpeg="ffmpeg",
        director_plan={"shots": []},
        render_status={"duration_seconds": 10},
    )

    assert report["pass"] is False
    assert report["status"] == "needs_review"
    assert report["checks"]["shot_count"] == 0
    assert report["checks"]["visual_type_diversity"] == 0
    assert report["issues"]


def test_video_self_review_pixel_analysis_flags_black_frames(tmp_path: Path) -> None:
    pytest = __import__("pytest")
    Image = pytest.importorskip("PIL.Image")
    from app.video_self_review import _analyze_frames

    frames_dir = tmp_path / "self_review_frames"
    frames_dir.mkdir()
    black_path = frames_dir / "review_frame_01.jpg"
    Image.new("RGB", (1080, 1920), (0, 0, 0)).save(black_path, "JPEG")

    report = _analyze_frames([black_path])

    assert report["available"] is True
    assert any("effectively black" in issue for issue in report["issues"])
    assert report["frames"]["review_frame_01.jpg"]["brightness"] < 5


def test_remotion_renderer_passes_director_plan_to_props(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    remotion_dir = project_root / "video_engine" / "remotion"
    remotion_dir.mkdir(parents=True)
    audio_path = tmp_path / "voice.mp3"
    evidence_path = tmp_path / "evidence.png"
    audio_path.write_bytes(b"audio")
    evidence_path.write_bytes(b"image")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    def fake_probe(_project_root: Path, *, composition: str = "DouyinExplainer") -> dict[str, object]:
        return {
            "runtime_available": True,
            "render_engine_actual": "ffmpeg",
            "remotion_dir": str(remotion_dir),
            "remotion_cli": "remotion",
            "composition": composition,
            "preferred_engine": "remotion",
        }

    def fake_run(command: list[str], *, cwd: Path, timeout: int) -> None:
        output = Path(command[4])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"rendered")

    monkeypatch.setattr("app.remotion_renderer.probe_remotion_renderer", fake_probe)
    monkeypatch.setattr("app.remotion_renderer._run_remotion", fake_run)

    _status, render_status = render_remotion_video(
        project_root=project_root,
        content_id="demo",
        title="Demo",
        duration_seconds=8,
        audio_path=audio_path,
        subtitle_plan={"subtitles": []},
        output_dir=output_dir,
        final_video_path=output_dir / "final_video.mp4",
        cover_path=output_dir / "cover.png",
        evidence_image_path=evidence_path,
        director_plan={"shots": [{"visual_type": "impact_title_card", "screen_text": "前三秒"}]},
    )

    props = json.loads((output_dir / "remotion_props.json").read_text(encoding="utf-8"))
    assert render_status["status"] == "succeeded"
    assert props["directorPlan"]["shots"][0]["screen_text"] == "前三秒"


def _write_json(path: Path, data: dict[str, object]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path
