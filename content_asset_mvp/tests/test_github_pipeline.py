from __future__ import annotations

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
        "chinese_script.md",
        "title_options.md",
        "review_notes.md",
    ]:
        assert (package_dir / filename).exists()
    assert (package_dir / "meta.json").read_text(encoding="utf-8").find('"source_type": "github_repo"') != -1


def test_snapshotter_skips_when_playwright_missing(tmp_path: Path, monkeypatch) -> None:
    writer = ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "gh_demo")
    monkeypatch.setitem(sys.modules, "playwright", None)

    status = snapshot_github_repo("https://github.com/example/repo", writer, playwright_available=False)

    assert status["status"] == "skipped"
    assert "Playwright" in status["reason"]
    assert (tmp_path / "output" / "gh_demo" / "snapshot_status.json").exists()
