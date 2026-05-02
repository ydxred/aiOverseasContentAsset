from __future__ import annotations

import json
import sys
from pathlib import Path

from app.github_collector import make_github_content_id, parse_github_repo_url
from app.main import main
from app.snapshotter import snapshot_github_repo
from app.artifact_writer import ArtifactWriter


def test_parse_github_repo_url_accepts_common_forms() -> None:
    ref = parse_github_repo_url("https://github.com/openai/openai-python/tree/main")
    assert ref.owner == "openai"
    assert ref.repo == "openai-python"
    assert ref.full_name == "openai/openai-python"
    assert make_github_content_id("https://github.com/openai/openai-python") == "gh_openai_openai-python"


def test_parse_github_repo_url_rejects_non_github() -> None:
    try:
        parse_github_repo_url("https://example.com/openai/openai-python")
    except ValueError as exc:
        assert "github.com" in str(exc)
    else:
        raise AssertionError("Expected non-GitHub URL to fail")


def test_mock_github_pipeline_generates_key_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"

    exit_code = main(
        [
            "--github-url",
            "https://github.com/example/mock-ai-repo",
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    package_dir = output_dir / "gh_example_mock-ai-repo"
    for filename in [
        "meta.json",
        "github_meta.json",
        "readme.md",
        "readme_images.json",
        "snapshot_status.json",
        "github_analysis.json",
        "score.json",
        "risk_report.json",
        "opportunity_engine.json",
        "chinese_script.md",
        "title_options.md",
        "review_notes.md",
        "quality_check.json",
        "media_job.json",
        "distribution.json",
        "feedback_template.json",
        "publish_review.json",
    ]:
        assert (package_dir / filename).exists()
    assert (package_dir / "meta.json").read_text(encoding="utf-8").find('"source_type": "github_repo"') != -1
    analysis = json.loads((package_dir / "github_analysis.json").read_text(encoding="utf-8"))
    score = json.loads((package_dir / "score.json").read_text(encoding="utf-8"))
    opportunity = json.loads((package_dir / "opportunity_engine.json").read_text(encoding="utf-8"))
    risk_report = json.loads((package_dir / "risk_report.json").read_text(encoding="utf-8"))
    script = (package_dir / "chinese_script.md").read_text(encoding="utf-8")
    assert analysis["content_type"] == "github_open_source_project"
    assert "why_now" in analysis["opportunity_dimensions"]
    assert "business_insight" in analysis
    assert score["content_type"] == "github_open_source_project"
    assert opportunity["content_type"] == "github_open_source_project"
    assert "risk_level" in risk_report
    assert "## 开发者为什么关注" not in script
    assert "## 海外发生了什么" in script
    assert "## 对中文用户/开发者/创作者/创业者的启发" in script


def test_snapshotter_skips_when_playwright_missing(tmp_path: Path, monkeypatch) -> None:
    writer = ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "gh_demo")
    monkeypatch.setitem(sys.modules, "playwright", None)

    status = snapshot_github_repo("https://github.com/example/repo", writer, playwright_available=False)

    assert status["status"] == "skipped"
    assert "Playwright" in status["reason"]
    assert (tmp_path / "output" / "gh_demo" / "snapshot_status.json").exists()
