from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.artifact_writer import ArtifactWriter
from app.main import main
from app.media_producer import build_bilingual_ass, build_bilingual_srt, build_caption_segments, build_director_zh_ass, build_srt, build_video_quality_report, collect_visual_evidence_items, extract_title_text, extract_voiceover_text, render_video_package, resolve_ffmpeg, select_visual_asset, split_sentences


SCRIPT = """# 标题

测试标题

# 口播稿

第一句测试。第二句继续！

# 分镜建议

画面建议
"""

SCRIPT_WITH_MARKDOWN_IN_VOICEOVER = """# 标题

测试标题

# 口播稿
## 为什么突然值得关注
第一句 **测试**。
- 第二句继续！

# 分镜建议
画面建议
"""


def test_extract_voiceover_text_from_chinese_script() -> None:
    assert extract_voiceover_text(SCRIPT) == "第一句测试。第二句继续！"


def test_extract_voiceover_text_drops_markdown_headings_and_marks() -> None:
    assert extract_voiceover_text(SCRIPT_WITH_MARKDOWN_IN_VOICEOVER) == "第一句 测试。\n第二句继续！"


def test_extract_title_text_from_chinese_script() -> None:
    assert extract_title_text(SCRIPT) == "测试标题"


def test_build_srt_from_chinese_sentences() -> None:
    sentences = split_sentences("第一句测试。第二句继续！")
    srt = build_srt(sentences, 6.0)

    assert "1\n00:00:00,000 -->" in srt
    assert "第一句测试。" in srt
    assert "第二句继续！" in srt


def test_build_bilingual_srt_from_caption_segments() -> None:
    sentences = split_sentences("第一句测试。第二句继续！")
    segments = build_caption_segments(sentences, 6.0)
    srt = build_bilingual_srt(segments, ["First test sentence.", "Second sentence continues!"])

    assert "第一句测试。\nFirst test sentence." in srt
    assert "第二句继续！\nSecond sentence continues!" in srt


def test_build_bilingual_ass_uses_vertical_resolution_and_bottom_alignment() -> None:
    sentences = split_sentences("第一句测试。第二句继续！")
    segments = build_caption_segments(sentences, 6.0)
    ass = build_bilingual_ass(segments, ["First test sentence.", "Second sentence continues!"])

    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "Style: Default" in ass
    assert ",2,90,90,210," in ass
    assert "Dialogue: 0,0:00:00.00" in ass


def test_build_director_zh_ass_uses_chinese_primary_subtitles() -> None:
    sentences = split_sentences("第一句测试。第二句继续！")
    segments = build_caption_segments(sentences, 6.0)
    ass = build_director_zh_ass(segments)

    assert "Fontsize, PrimaryColour" in ass
    assert "Style: Default,Noto Sans CJK SC,58" in ass
    assert "Style: Scene,Noto Sans CJK SC,50" in ass
    assert "Style: Shot,Noto Sans CJK SC,72" in ass
    assert "First test sentence" not in ass
    assert "第一句测试。" in ass


def test_build_director_zh_ass_adds_scene_screen_text() -> None:
    sentences = split_sentences("第一句测试。第二句继续！")
    segments = build_caption_segments(sentences, 6.0)
    ass = build_director_zh_ass(
        segments,
        {
            "scenes": [
                {
                    "screen_text": "AI 开始自己操作网页",
                    "start": 0.0,
                    "end": 3.0,
                }
            ]
        },
    )

    assert "Dialogue: 1,0:00:00.00,0:00:03.00,Scene" in ass
    assert "AI 开始自己操作网页" in ass


def test_build_director_zh_ass_adds_shot_screen_text() -> None:
    sentences = split_sentences("第一句测试。第二句继续！")
    segments = build_caption_segments(sentences, 6.0)
    ass = build_director_zh_ass(
        segments,
        {
            "shots": [
                {
                    "screen_text": "三秒换一个画面",
                    "visual_type": "keyword_punch_card",
                    "start": 0.0,
                    "end": 2.5,
                }
            ]
        },
    )

    assert "Dialogue: 2,0:00:00.00,0:00:02.50,Shot" in ass
    assert "\\pos(540,605)" in ass
    assert "三秒换一个画面" in ass


def test_director_subtitles_do_not_split_short_english_terms() -> None:
    sentences = split_sentences("AI Agent 终于不是 PPT 里的概念，而是开始真实干活了。")
    segments = build_caption_segments(sentences, 4.0)
    ass = build_director_zh_ass(segments)

    assert "PPT" in ass
    assert "PP\\N" not in ass


def test_director_subtitles_keep_third_line_for_long_chinese_text() -> None:
    sentences = split_sentences("这东西现在还不一定成熟，但方向很猛：AI Agent 终于不是 PPT 里的概念，而是开始往真实干活走了。")
    segments = build_caption_segments(sentences, 4.0)
    ass = build_director_zh_ass(segments)

    assert "真实干活" in ass


def test_select_visual_asset_prefers_github_screenshot(tmp_path: Path) -> None:
    writer = ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "demo")
    screenshot = writer.workspace_path("snapshots/github_repo_home.png")
    screenshot.parent.mkdir(parents=True)
    screenshot.write_bytes(b"fake-image")
    writer.write_json("snapshot_status.json", {"screenshots": [{"workspace_path": str(screenshot)}]})

    assert select_visual_asset(writer) == screenshot


def test_select_visual_asset_prefers_browser_agent_asset(tmp_path: Path) -> None:
    writer = ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "demo")
    browser_asset = writer.workspace_path("browser_agent_assets/source.png")
    screenshot = writer.workspace_path("snapshots/github_repo_home.png")
    browser_asset.parent.mkdir(parents=True)
    screenshot.parent.mkdir(parents=True)
    browser_asset.write_bytes(b"browser-image")
    screenshot.write_bytes(b"snapshot-image")
    writer.write_json("browser_agent_assets.json", {"assets": [{"workspace_path": str(browser_asset)}]})
    writer.write_json("snapshot_status.json", {"screenshots": [{"workspace_path": str(screenshot)}]})

    assert select_visual_asset(writer) == browser_asset


def test_collect_visual_evidence_items_keeps_browser_sequence_first(tmp_path: Path) -> None:
    writer = ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "demo")
    browser_one = writer.workspace_path("browser_agent_assets/source.png")
    browser_two = writer.workspace_path("browser_agent_assets/docs.png")
    snapshot = writer.workspace_path("snapshots/github_repo_home.png")
    for path in (browser_one, browser_two, snapshot):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
    writer.write_json(
        "browser_agent_assets.json",
        {
            "assets": [
                {"workspace_path": str(browser_one), "label": "Source", "role": "browser_source_screenshot"},
                {"workspace_path": str(browser_two), "label": "Docs", "role": "browser_docs_screenshot"},
            ]
        },
    )
    writer.write_json("snapshot_status.json", {"screenshots": [{"workspace_path": str(snapshot), "label": "Repo"}]})

    items = collect_visual_evidence_items(writer)

    assert [item["label"] for item in items[:3]] == ["Source", "Docs", "Repo"]
    assert [item["role"] for item in items[:2]] == ["browser_source_screenshot", "browser_docs_screenshot"]


def test_video_quality_report_blocks_offline_voice_and_low_asset_diversity() -> None:
    report = build_video_quality_report(
        director_plan={
            "shots": [
                {"visual_type": "impact_title_card"},
                {"visual_type": "keyword_punch_card"},
            ],
            "assets": [{"role": "repo_snapshot", "path": "/tmp/repo.png"}],
        },
        tts_status={"mode": "offline_silence"},
        translation_status={"mode": "mock_placeholder"},
        render_status={"duration_seconds": 12.0, "subtitle_burned": True},
    )

    assert report["voice_quality_score"] < 50
    assert report["publish_ready"] is False
    assert report["blocking_reasons"]


def test_offline_render_generates_final_video(tmp_path: Path) -> None:
    writer = ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "demo")
    pytest.importorskip("subprocess")
    try:
        resolve_ffmpeg(writer)
    except FileNotFoundError:
        pytest.skip("ffmpeg is not available")
    writer.write_markdown("chinese_script.md", SCRIPT)

    result = render_video_package("demo", writer, force_mock=True)

    video_path = Path(result.video_path)
    assert result.status == "succeeded"
    assert video_path.exists()
    assert video_path.stat().st_size > 0
    assert writer.output_path("subtitles.srt").exists()
    assert writer.output_path("subtitles.zh.srt").exists()
    assert writer.output_path("subtitles.en.srt").exists()
    assert writer.output_path("subtitles.bilingual.srt").exists()
    assert writer.output_path("subtitles.bilingual.ass").exists()
    assert writer.output_path("subtitles.director.zh.ass").exists()
    assert writer.output_path("subtitle_plan.json").exists()
    assert writer.output_path("subtitle_translation_status.json").exists()
    assert writer.output_path("tts_status.json").exists()
    assert writer.output_path("audio_mastering_status.json").exists()
    assert writer.output_path("render_status.json").exists()
    assert writer.output_path("video_render_manifest.json").exists()
    assert writer.output_path("render_manifest.v6.json").exists()
    assert writer.output_path("remotion_status.json").exists()
    assert writer.output_path("visual_qc_report.json").exists()
    assert writer.output_path("video_self_review.json").exists()
    assert writer.output_path("skill_registry.json").exists()
    assert writer.output_path("director_plan.json").exists()
    assert writer.output_path("shot_list.json").exists()
    assert writer.output_path("edit_decisions.json").exists()
    assert writer.output_path("visual_asset_pack.json").exists()
    assert writer.output_path("video_quality_report.json").exists()
    assert writer.output_path("director_script.md").exists()
    assert writer.output_path("director_quality_checklist.json").exists()
    assert writer.output_path("brand_template.json").exists()
    assert writer.output_path("cover.png").exists()
    translation_status = json.loads(writer.output_path("subtitle_translation_status.json").read_text(encoding="utf-8"))
    render_status = json.loads(writer.output_path("render_status.json").read_text(encoding="utf-8"))
    render_manifest = json.loads(writer.output_path("video_render_manifest.json").read_text(encoding="utf-8"))
    render_manifest_v6 = json.loads(writer.output_path("render_manifest.v6.json").read_text(encoding="utf-8"))
    video_quality_report = json.loads(writer.output_path("video_quality_report.json").read_text(encoding="utf-8"))
    audio_mastering_status = json.loads(writer.output_path("audio_mastering_status.json").read_text(encoding="utf-8"))
    remotion_status = json.loads(writer.output_path("remotion_status.json").read_text(encoding="utf-8"))
    visual_qc_report = json.loads(writer.output_path("visual_qc_report.json").read_text(encoding="utf-8"))
    video_self_review = json.loads(writer.output_path("video_self_review.json").read_text(encoding="utf-8"))
    skill_registry = json.loads(writer.output_path("skill_registry.json").read_text(encoding="utf-8"))
    media_job = json.loads(writer.output_path("media_job.json").read_text(encoding="utf-8"))
    brand_template = json.loads(writer.output_path("brand_template.json").read_text(encoding="utf-8"))
    assert translation_status["mode"] == "mock_placeholder"
    assert render_status["subtitle_mode"] == "director_zh"
    assert render_status["generated_at"]
    assert render_status["output_layout"] == "one_resource_one_directory"
    assert render_manifest["content_id"] == "demo"
    assert render_manifest["generated_at"] == render_status["generated_at"]
    assert render_manifest["video_version"] == render_status["video_version"]
    assert render_manifest["output_layout"]["rule"] == "one_resource_one_directory"
    assert render_manifest["render_parameters"]["subtitle_mode"] == "director_zh"
    assert render_manifest["render_parameters"]["director_style"] == "video_director_v4"
    assert render_manifest["render_parameters"]["edit_template"] == "github_tool_explainer_v4"
    assert render_manifest["render_parameters"]["shot_count"] >= 10
    assert render_manifest["render_parameters"]["video_quality_score"] == video_quality_report["video_quality_score"]
    assert render_manifest["render_parameters"]["architecture_version"] == "video_pipeline_v6_slice"
    assert render_manifest["render_parameters"]["render_engine_preferred"] == "remotion"
    assert render_manifest["render_parameters"]["render_engine_actual"] == remotion_status["render_engine_actual"]
    assert render_manifest["render_parameters"]["audio_mastered"] == (audio_mastering_status["success"] is True)
    assert render_manifest["render_parameters"]["visual_qc_score"] == visual_qc_report["score"]
    assert render_manifest["render_parameters"]["visual_qc_pass"] == visual_qc_report["pass"]
    assert render_manifest_v6["platform"] == "douyin"
    assert render_manifest_v6["composition"] == "DouyinExplainer"
    assert render_manifest_v6["fallback_engine"] == "ffmpeg"
    assert render_manifest_v6["outputs"]["video_self_review_path"].endswith("video_self_review.json")
    assert render_manifest_v6["outputs"]["skill_registry_path"].endswith("skill_registry.json")
    assert remotion_status["preferred_engine"] == "remotion"
    assert remotion_status["render_engine_actual"] in {"remotion", "ffmpeg"}
    assert visual_qc_report["metrics"]["shot_count"] >= 10
    assert video_self_review["checks"]["shot_count"] >= 10
    assert any(skill["skill_id"] == "remotion-shotlist-renderer" and skill["used_in_current_run"] for skill in skill_registry["skills"])
    assert video_quality_report["publish_ready"] is False
    assert video_quality_report["voice_quality_score"] < 50
    assert media_job["render_manifest_path"].endswith("video_render_manifest.json")
    assert render_status["template_id"] == "overseas_ai_narrative_v1"
    assert render_status["director_status"]["status"] == "enabled"
    assert render_status["director_status"]["shot_count"] >= 10
    assert render_status["visual_quality"] in {
        "brand_template_v1",
        "director_v3_large_scene",
        "director_v4_multi_shot",
        "remotion_douyin_explainer_v1",
    }
    assert brand_template["brand_name"] == "Overseas AI Radar"


def test_cli_render_video_runs_against_temp_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"
    package_dir = output_dir / "demo_cli"
    package_dir.mkdir(parents=True)
    (package_dir / "chinese_script.md").write_text(SCRIPT, encoding="utf-8")
    try:
        resolve_ffmpeg(ArtifactWriter(output_dir, workspace_dir, "demo_cli"))
    except FileNotFoundError:
        pytest.skip("ffmpeg is not available")

    exit_code = main(
        [
            "--render-video",
            "demo_cli",
            "--video-mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    assert "final_video.mp4" in capsys.readouterr().out
    assert (package_dir / "final_video.mp4").stat().st_size > 0
    assert (package_dir / "brand_template.json").exists()
    assert (package_dir / "cover.png").exists()
