from __future__ import annotations

import json
from pathlib import Path

from app.main import main


def test_mock_pipeline_generates_review_package(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"
    exit_code = main(
        [
            "--url",
            "https://youtube.com/watch?v=xxx",
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    content_dirs = list(output_dir.iterdir())
    assert len(content_dirs) == 1
    package_dir = content_dirs[0]
    for filename in [
        "meta.json",
        "transcript.json",
        "analysis.json",
        "score.json",
        "risk_report.json",
        "chinese_script.md",
        "title_options.md",
        "review_notes.md",
    ]:
        assert (package_dir / filename).exists()
    analysis = json.loads((package_dir / "analysis.json").read_text(encoding="utf-8"))
    score = json.loads((package_dir / "score.json").read_text(encoding="utf-8"))
    script = (package_dir / "chinese_script.md").read_text(encoding="utf-8")
    assert analysis["content_type"] == "ai_business_model_observation"
    assert "content_positioning" in analysis
    assert "why_now" in analysis["opportunity_dimensions"]
    assert "problem_intensity" in score["opportunity_dimensions"]
    assert "# 口播稿" in script
    assert "## 为什么突然值得关注" in script
    assert "## 边界：不承诺收益、不夸大、不照搬" in script


def test_init_db_skips_cleanly_in_mock_mode(capsys) -> None:
    exit_code = main(["--init-db", "--mock"])

    assert exit_code == 0
    assert "Skipped database initialization" in capsys.readouterr().out


def test_mock_pipeline_accepts_local_audio_file(tmp_path: Path) -> None:
    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"not real audio but mock mode does not transcribe it")
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"

    exit_code = main(
        [
            "--audio-file",
            str(audio_file),
            "--title",
            "Local validation sample",
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    package_dir = next(output_dir.iterdir())
    assert (package_dir / "meta.json").exists()
    assert (package_dir / "review_notes.md").exists()


def test_youtube_candidate_mock_skips_real_transcript_fetch(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(
        json.dumps(
            {
                "candidate_id": "cand_youtube_mock",
                "name": "海外 AI 工具观察",
                "url": "https://youtube.com/watch?v=mockvideo123",
                "source_type": "youtube_video",
                "decision": "approve_candidate",
                "score": 88,
                "signals": {
                    "video_id": "mockvideo123",
                    "channel_title": "Overseas AI Lab",
                    "description": "A new AI tool is getting attention overseas.",
                    "views": 120000,
                    "likes": 3200,
                    "comments": 420,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"

    exit_code = main(
        [
            "--candidate-package",
            str(candidate_path),
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    package_dir = next(output_dir.iterdir())
    transcript = json.loads((package_dir / "youtube_transcript.json").read_text(encoding="utf-8"))
    analysis = json.loads((package_dir / "analysis.json").read_text(encoding="utf-8"))
    assert transcript["status"] == "skipped"
    assert transcript["reason"] == "mock_mode"
    assert analysis["analysis_basis"] == "metadata_only"
    assert (package_dir / "risk_report.json").exists()
    assert (package_dir / "quality_check.json").exists()


def test_score_topic_tolerates_explanatory_llm_values(tmp_path: Path) -> None:
    from app.artifact_writer import ArtifactWriter
    from app.scorer import score_topic

    writer = ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "demo")
    score = score_topic(
        {
            "domestic_value": "Useful for explaining overseas context.",
            "commercial_value": "Could support business content.",
            "short_video_suitability": True,
            "content_formats": ["short_video"],
            "risk_points": ["Needs context"],
        },
        writer,
    )

    assert score["total_score"] > 0
    assert score["content_type"] in {
        "ai_tool_explainer",
        "ai_cli_agent",
        "github_open_source_project",
        "overseas_ai_startup_case",
        "product_hunt_new_product",
        "ai_business_model_observation",
        "overseas_info_gap_story",
    }
    for key in [
        "why_now",
        "problem_intensity",
        "china_gap",
        "narrative_value",
        "video_potential",
        "business_insight",
        "audience_fit",
        "evidence_completeness",
        "risk_control",
    ]:
        assert key in score["opportunity_dimensions"]
        assert key in score["dimensions"]
    assert (tmp_path / "output" / "demo" / "score.json").exists()


def test_rewriter_normalizes_unstructured_real_output(tmp_path: Path) -> None:
    from app.rewriter import _normalize_script, _normalize_titles

    meta = {"title": "Validation sample"}
    analysis = {
        "core_topic": "Public Speech",
        "summary": "A short English summary.",
        "main_points": ["Point one"],
        "risk_points": ["Needs context"],
        "facts_to_check": ["Exact source"],
    }

    script = _normalize_script("Plain paragraph.", meta, analysis)
    titles = _normalize_titles([], meta, analysis)

    assert "# 标题" in script
    assert "# 口播稿" in script
    assert "# 待核查内容" in script
    assert len(titles) == 3


def test_rewriter_converts_script_dict_to_markdown() -> None:
    from app.rewriter import _normalize_script

    script = _normalize_script(
        {
            "# 标题": "标题",
            "# 口播稿": "正文",
            "# 分镜建议": "分镜",
            "# 屏幕文字": "屏幕",
            "# 风险点": "风险",
            "# 待核查内容": "核查",
        },
        {},
        {},
    )

    assert script.startswith("# 标题")
    assert "{'# 标题'" not in script
    assert "# 口播稿\n\n正文" in script

