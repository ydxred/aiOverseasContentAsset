from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from app.main import main, select_auto_candidate
from app.web import build_server
from app.generic_candidate import make_generic_candidate_content_id
from app.youtube_analyzer import make_youtube_candidate_content_id
from app.youtube_transcript import fetch_youtube_transcript


def test_cli_candidate_id_generates_youtube_review_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = _youtube_candidate()
    monkeypatch.setattr(
        "app.youtube_transcript._fetch_transcript",
        lambda video_id: pytest.fail("mock candidate pipeline must not call youtube-transcript-api"),
    )
    candidate_path = tmp_path / "candidate_sources.json"
    candidate_path.write_text(json.dumps({"candidates": [candidate]}, ensure_ascii=False), encoding="utf-8")
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"

    exit_code = main(
        [
            "--candidate-id",
            candidate["candidate_id"],
            "--candidate-path",
            str(candidate_path),
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    package_dir = output_dir / make_youtube_candidate_content_id(candidate)
    for filename in [
        "meta.json",
        "youtube_candidate.json",
        "youtube_transcript.json",
        "transcript_clean.json",
        "analysis.json",
        "score.json",
        "risk_report.json",
        "chinese_script.md",
        "quality_check.json",
        "publish_review.json",
        "media_job.json",
        "distribution.json",
        "feedback_template.json",
        "review_notes.md",
    ]:
        assert (package_dir / filename).exists()
    meta = json.loads((package_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["source_type"] == "youtube_video"
    assert meta["download_status"] == "metadata_only_candidate"
    assert meta["audio_path"] is None
    transcript = json.loads((package_dir / "youtube_transcript.json").read_text(encoding="utf-8"))
    assert transcript["status"] == "skipped"
    assert transcript["reason"] == "mock_mode"
    analysis = json.loads((package_dir / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["analysis_basis"] == "metadata_only"
    assert analysis["factual_confidence"] == "low_metadata_only"
    script = (package_dir / "chinese_script.md").read_text(encoding="utf-8")
    assert "# 口播稿" in script
    publish_review = json.loads((package_dir / "publish_review.json").read_text(encoding="utf-8"))
    assert publish_review["status"] == "pending"

    updated = json.loads(candidate_path.read_text(encoding="utf-8"))["candidates"][0]
    assert updated["review_package_content_id"] == package_dir.name


def test_web_candidate_package_button_and_route_generate_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = _youtube_candidate()
    monkeypatch.setattr(
        "app.youtube_transcript._fetch_transcript",
        lambda video_id: ([{"start": 0.0, "duration": 2.0, "text": "OpenClaw helps content systems."}], "en", "preferred_language"),
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "candidate_sources.json").write_text(
        json.dumps({"candidates": [candidate]}, ensure_ascii=False),
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"

    server = build_server("127.0.0.1", 0)
    server.root_dir = tmp_path
    server.output_dir = output_dir
    server.workspace_dir = workspace_dir
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/source-discovery", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "/candidate/package" in html
        assert "生成审核包" in html

        payload = urlencode({"candidate_id": candidate["candidate_id"]}).encode("utf-8")
        request = Request(f"http://{host}:{port}/candidate/package", data=payload, method="POST")
        with urlopen(request, timeout=10) as response:
            assert response.status == 200
            detail_html = response.read().decode("utf-8")
        content_id = make_youtube_candidate_content_id(candidate)
        assert content_id in detail_html
        assert "youtube_transcript.json" in detail_html
        assert "transcript" in detail_html
        assert (output_dir / content_id / "youtube_candidate.json").exists()

        with urlopen(f"http://{host}:{port}/source-discovery", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "查看审核包" in html
    finally:
        server.shutdown()
        server.server_close()


def test_cli_candidate_package_generates_generic_review_package(tmp_path: Path) -> None:
    candidate = {
        "candidate_id": "cand_product_hunt_ai",
        "source_id": "product_hunt",
        "source_type": "product_launch",
        "name": "AI Launch Radar",
        "url": "https://www.producthunt.com/posts/ai-launch-radar",
        "category": "new_tools",
        "discovered_from": {"name": "Product Hunt", "source_id": "product_hunt", "trust_score": 7},
        "discovery_method": "Product Hunt AI launch discovery",
        "reason": "Product Hunt AI launch with early adoption signal.",
        "signals": {"platform": "product_hunt", "votes": 420, "comments": 36, "description": "AI tool launch"},
        "score": 82,
        "decision": "approve_candidate",
        "status": "new",
        "created_at": "2026-05-02T00:00:00Z",
    }
    candidate_path = tmp_path / "candidate_sources.json"
    candidate_path.write_text(json.dumps({"candidates": [candidate]}, ensure_ascii=False), encoding="utf-8")
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"

    exit_code = main(
        [
            "--candidate-id",
            candidate["candidate_id"],
            "--candidate-path",
            str(candidate_path),
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    package_dir = output_dir / make_generic_candidate_content_id(candidate)
    for filename in [
        "meta.json",
        "generic_candidate.json",
        "transcript_clean.json",
        "analysis.json",
        "score.json",
        "risk_report.json",
        "chinese_script.md",
        "quality_check.json",
        "publish_review.json",
    ]:
        assert (package_dir / filename).exists()
    meta = json.loads((package_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["source_type"] == "product_launch"
    script = (package_dir / "chinese_script.md").read_text(encoding="utf-8")
    assert "## 为什么突然值得关注" in script


def test_auto_candidate_selection_prioritizes_youtube_then_decision_and_score() -> None:
    github_high_score = {
        "candidate_id": "cand_github_high",
        "source_type": "github_repo",
        "decision": "approve_candidate",
        "score": 99,
        "status": "new",
    }
    youtube_review = {
        "candidate_id": "cand_youtube_review",
        "source_type": "youtube_video",
        "decision": "review",
        "score": 70,
        "status": "new",
    }
    youtube_approved = {
        "candidate_id": "cand_youtube_approved",
        "source_type": "youtube_video",
        "decision": "approve_candidate",
        "score": 65,
        "status": "new",
    }
    archived_youtube = {
        "candidate_id": "cand_youtube_archived",
        "source_type": "youtube_video",
        "decision": "approve_candidate",
        "score": 100,
        "status": "archived",
    }

    selected = select_auto_candidate([github_high_score, youtube_review, youtube_approved, archived_youtube])

    assert selected is not None
    assert selected["candidate_id"] == "cand_youtube_approved"


def test_cli_review_package_writes_publish_review(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"
    package_dir = output_dir / "demo"
    package_dir.mkdir(parents=True)

    exit_code = main(
        [
            "--review-package",
            "demo",
            "--review-status",
            "approved",
            "--review-note",
            "已核查原视频与资料",
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    review = json.loads((package_dir / "publish_review.json").read_text(encoding="utf-8"))
    assert review["status"] == "approved"
    assert review["review_note"] == "已核查原视频与资料"


def test_fetch_youtube_transcript_success_writes_clean_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    writer = _writer(tmp_path)

    def fake_fetch(video_id: str) -> tuple[list[dict[str, object]], str]:
        assert video_id == "abc123"
        return [
            {"start": 0.0, "duration": 1.2, "text": "Hello from the transcript."},
            {"start": 1.2, "duration": 2.0, "text": "This is the factual basis."},
        ], "en"

    monkeypatch.setattr("app.youtube_transcript._fetch_transcript", lambda video_id: (*fake_fetch(video_id), "preferred_language"))

    transcript = fetch_youtube_transcript(_youtube_candidate(), writer)

    assert transcript["status"] == "fetched"
    saved = json.loads((writer.output_dir / "youtube_transcript.json").read_text(encoding="utf-8"))
    cleaned = json.loads((writer.output_dir / "transcript_clean.json").read_text(encoding="utf-8"))
    assert saved["segment_count"] == 2
    assert "factual basis" in cleaned["full_text"]


def test_fetch_youtube_transcript_failure_writes_error_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    writer = _writer(tmp_path)

    def fake_fetch(video_id: str) -> tuple[list[dict[str, object]], str]:
        raise RuntimeError("transcript unavailable")

    monkeypatch.setattr("app.youtube_transcript._fetch_transcript", lambda video_id: (*fake_fetch(video_id), "preferred_language"))

    transcript = fetch_youtube_transcript(_youtube_candidate(), writer)

    assert transcript["status"] == "error"
    assert (writer.output_dir / "youtube_transcript.json").exists()
    cleaned = json.loads((writer.output_dir / "transcript_clean.json").read_text(encoding="utf-8"))
    assert cleaned["full_text"] == ""


def test_cli_auto_close_loop_mock_generates_summary_and_video(tmp_path: Path) -> None:
    source_path = _write_youtube_sources(tmp_path)
    candidate_path = tmp_path / "candidate_sources.json"
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"

    exit_code = main(
        [
            "--auto-close-loop",
            "--auto-mock-discovery",
            "--sources-path",
            str(source_path),
            "--candidate-path",
            str(candidate_path),
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    summaries = list(output_dir.glob("*/auto_run_summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert summary["mock_discovery"] is True
    assert summary["video_mock"] is True
    assert summary["candidate_id"]
    assert summary["content_id"]
    final_video = Path(summary["final_video_path"])
    assert final_video.exists()
    assert final_video.stat().st_size > 0


def _youtube_candidate() -> dict[str, object]:
    return {
        "candidate_id": "cand_youtube_abc123",
        "source_id": "greg_isenberg",
        "source_type": "youtube_video",
        "name": "5 tips for OpenClaw",
        "url": "https://www.youtube.com/watch?v=abc123",
        "category": "startup_ideas",
        "discovered_from": {"source_id": "greg_isenberg", "name": "Greg Isenberg", "trust_score": 9},
        "discovery_method": "YouTube Data API search",
        "reason": "YouTube video discovered via Data API search.",
        "signals": {
            "platform": "youtube",
            "video_id": "abc123",
            "channel_id": "channel_1",
            "channel_title": "Greg Isenberg",
            "published_at": "2026-04-16T20:00:05Z",
            "thumbnail": "https://i.ytimg.com/vi/abc123/maxresdefault.jpg",
            "views": 22582,
            "likes": 624,
            "comments": 11,
            "description": "A practical English demo about making OpenClaw useful for content systems.",
            "keywords": ["AI", "creator", "business"],
        },
        "score": 71,
        "decision": "review",
        "status": "new",
        "created_at": "2026-05-01T15:43:46Z",
    }


def _write_youtube_sources(tmp_path: Path) -> Path:
    source_path = tmp_path / "youtube_sources.yaml"
    source_path.write_text(
        """
sources:
  - source_id: fireship_youtube
    source_type: youtube_channel
    name: Fireship
    category: developer_trends
    trust_score: 8
    status: active
    urls:
      youtube: https://www.youtube.com/@Fireship
    watch_keywords:
      - AI coding
      - developer tools
      - productivity automation
    discovery_method: Track fast-moving developer videos.
""".strip(),
        encoding="utf-8",
    )
    return source_path


def _writer(tmp_path: Path):
    from app.artifact_writer import ArtifactWriter

    return ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "yt_test")
