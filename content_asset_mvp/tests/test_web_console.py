from __future__ import annotations

import threading
from argparse import Namespace
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen
from pathlib import Path
import json

import pytest

from app.web import _layout, build_server, list_output_packages, list_rendered_videos, safe_artifact_path


def test_web_layout_renders_chinese_page() -> None:
    html = _layout("测试", "<div>内容</div>")

    assert 'lang="zh-CN"' in html
    assert "Content Asset MVP" in html
    assert "<div>内容</div>" in html


def test_safe_artifact_path_rejects_traversal(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    package_dir = output_dir / "yt_demo"
    package_dir.mkdir(parents=True)
    (package_dir / "review_notes.md").write_text("ok", encoding="utf-8")

    assert safe_artifact_path(output_dir, "yt_demo", "review_notes.md") == package_dir / "review_notes.md"
    with pytest.raises(ValueError):
        safe_artifact_path(output_dir, "../bad", "review_notes.md")
    with pytest.raises(ValueError):
        safe_artifact_path(output_dir, "yt_demo", "../secret")


def test_list_output_packages_newest_first(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    old = output_dir / "old"
    new = output_dir / "new"
    old.mkdir(parents=True)
    new.mkdir()

    packages = list_output_packages(output_dir)

    assert packages[0] == new
    assert old in packages


def test_list_rendered_videos_collects_video_metadata(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    package_dir = output_dir / "demo"
    package_dir.mkdir(parents=True)
    (package_dir / "final_video.mp4").write_bytes(b"fake-video")
    (package_dir / "meta.json").write_text(json.dumps({"title": "测试成片", "source_type": "youtube_video"}, ensure_ascii=False), encoding="utf-8")
    (package_dir / "tts_status.json").write_text(json.dumps({"mode": "openai"}, ensure_ascii=False), encoding="utf-8")
    (package_dir / "render_status.json").write_text(json.dumps({"subtitle_mode": "bilingual", "duration_seconds": 12.3}, ensure_ascii=False), encoding="utf-8")
    (package_dir / "subtitle_translation_status.json").write_text(json.dumps({"mode": "openai"}, ensure_ascii=False), encoding="utf-8")
    (package_dir / "publish_review.json").write_text(json.dumps({"status": "approved"}, ensure_ascii=False), encoding="utf-8")

    videos = list_rendered_videos(output_dir)

    assert len(videos) == 1
    assert videos[0]["content_id"] == "demo"
    assert videos[0]["title"] == "测试成片"
    assert videos[0]["tts_mode"] == "openai"
    assert videos[0]["subtitle_mode"] == "bilingual"
    assert videos[0]["publish_status"] == "approved"


def test_status_page_renders() -> None:
    server = build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/status", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "系统状态" in html
        assert "DATABASE_URL" in html
        assert "yt-dlp" in html
        assert "git status --short" in html
    finally:
        server.shutdown()
        server.server_close()


def test_source_manager_page_renders() -> None:
    server = build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/source-manager", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "源池管理" in html
        assert "Pieter Levels" in html
        assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()


def test_source_discovery_page_renders() -> None:
    server = build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/source-discovery", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "候选源审核" in html
        assert "运行 mock discovery" in html
        assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()


def test_source_discovery_page_renders_auto_close_loop_button() -> None:
    server = build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/source-discovery", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "/auto-close-loop" in html
        assert "一键完整闭环" in html
    finally:
        server.shutdown()
        server.server_close()


def test_web_auto_close_loop_route_redirects_to_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"
    content_id = "auto_demo"

    def fake_run_pipeline(args: Namespace) -> int:
        assert args.auto_close_loop is True
        assert args.auto_mock_discovery is True
        package_dir = output_dir / content_id
        package_dir.mkdir(parents=True)
        (package_dir / "auto_run_summary.json").write_text(
            json.dumps({"content_id": content_id, "candidate_id": "cand_auto"}, ensure_ascii=False),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr("app.web.run_pipeline", fake_run_pipeline)
    server = build_server("127.0.0.1", 0)
    server.output_dir = output_dir
    server.workspace_dir = workspace_dir
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        payload = urlencode({"mock_discovery": "1"}).encode("utf-8")
        request = Request(f"http://{host}:{port}/auto-close-loop", data=payload, method="POST")
        with urlopen(request, timeout=5) as response:
            html = response.read().decode("utf-8")
        assert content_id in html
        assert "auto_run_summary.json" in html
    finally:
        server.shutdown()
        server.server_close()


def test_source_discovery_page_renders_candidate_review_actions(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "candidate_sources.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": "cand_browser_use",
                        "name": "browser-use/browser-use",
                        "url": "https://github.com/browser-use/browser-use",
                        "source_type": "github_repo",
                        "score": 86,
                        "decision": "approve_candidate",
                        "status": "new",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    server = build_server("127.0.0.1", 0)
    server.root_dir = tmp_path
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/source-discovery", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "/candidate/approve" in html
        assert "/candidate/reject" in html
        assert "/candidate/archive" in html
        assert "批准" in html
        assert "拒绝" in html
        assert "归档" in html
    finally:
        server.shutdown()
        server.server_close()


def test_output_detail_contains_render_video_button(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    package_dir = output_dir / "demo"
    package_dir.mkdir(parents=True)
    (package_dir / "chinese_script.md").write_text("# 口播稿\n\n测试。", encoding="utf-8")

    server = build_server("127.0.0.1", 0)
    server.output_dir = output_dir
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/outputs/demo", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "/render-video" in html
        assert "生成视频" in html
        assert "final_video.mp4" in html
        assert "OpenAI TTS" in html
        assert "双语字幕默认" in html
        assert "使用离线 TTS fallback" in html
    finally:
        server.shutdown()
        server.server_close()


def test_videos_page_renders_player_and_status(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    package_dir = output_dir / "demo"
    package_dir.mkdir(parents=True)
    (package_dir / "final_video.mp4").write_bytes(b"fake-video")
    (package_dir / "meta.json").write_text(json.dumps({"title": "测试成片", "source_type": "youtube_video"}, ensure_ascii=False), encoding="utf-8")
    (package_dir / "tts_status.json").write_text(json.dumps({"mode": "openai"}, ensure_ascii=False), encoding="utf-8")
    (package_dir / "render_status.json").write_text(json.dumps({"subtitle_mode": "bilingual"}, ensure_ascii=False), encoding="utf-8")
    (package_dir / "subtitle_translation_status.json").write_text(json.dumps({"mode": "openai"}, ensure_ascii=False), encoding="utf-8")

    server = build_server("127.0.0.1", 0)
    server.output_dir = output_dir
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/videos", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "成片库" in html
        assert "测试成片" in html
        assert "<video" in html
        assert "/artifact/demo/final_video.mp4" in html
        assert "TTS: openai" in html
        assert "字幕: bilingual" in html
    finally:
        server.shutdown()
        server.server_close()


def test_output_detail_embeds_video_preview(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    package_dir = output_dir / "demo"
    package_dir.mkdir(parents=True)
    (package_dir / "chinese_script.md").write_text("# 口播稿\n\n测试。", encoding="utf-8")
    (package_dir / "final_video.mp4").write_bytes(b"fake-video")

    server = build_server("127.0.0.1", 0)
    server.output_dir = output_dir
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/outputs/demo", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "成片预览" in html
        assert "<video" in html
        assert "/artifact/demo/final_video.mp4" in html
        assert "返回成片库" in html
    finally:
        server.shutdown()
        server.server_close()


def test_output_detail_shows_publish_review_and_low_confidence_warning(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    package_dir = output_dir / "demo"
    package_dir.mkdir(parents=True)
    (package_dir / "analysis.json").write_text(
        json.dumps(
            {
                "analysis_basis": "metadata_only",
                "factual_confidence": "low_metadata_only",
                "facts_to_check": ["原视频具体论点"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (package_dir / "youtube_transcript.json").write_text(
        json.dumps({"status": "error", "reason": "TranscriptDisabled"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (package_dir / "risk_report.json").write_text(
        json.dumps({"pass": True, "risk_level": "medium", "must_review": True}, ensure_ascii=False),
        encoding="utf-8",
    )
    (package_dir / "quality_check.json").write_text(
        json.dumps({"pass": True, "quality_score": 70, "ready_for_human_review": True}, ensure_ascii=False),
        encoding="utf-8",
    )

    server = build_server("127.0.0.1", 0)
    server.output_dir = output_dir
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/outputs/demo", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "发布前审核" in html
        assert "publish_review" in html
        assert "pending" in html
        assert "metadata_only" in html
        assert "low_metadata_only" in html
        assert "需人工核查原视频/资料后再发布" in html
        assert "原视频具体论点" in html
    finally:
        server.shutdown()
        server.server_close()


def test_publish_review_form_writes_status_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    package_dir = output_dir / "demo"
    package_dir.mkdir(parents=True)

    server = build_server("127.0.0.1", 0)
    server.output_dir = output_dir
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        payload = urlencode(
            {
                "content_id": "demo",
                "review_status": "needs_revision",
                "review_note": "补充原视频核查记录",
            }
        ).encode("utf-8")
        request = Request(f"http://{host}:{port}/publish-review", data=payload, method="POST")
        with urlopen(request, timeout=5) as response:
            html = response.read().decode("utf-8")
        review = json.loads((package_dir / "publish_review.json").read_text(encoding="utf-8"))
        assert review["status"] == "needs_revision"
        assert review["review_note"] == "补充原视频核查记录"
        assert "needs_revision" in html
    finally:
        server.shutdown()
        server.server_close()
