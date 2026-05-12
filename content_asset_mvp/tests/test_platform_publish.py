from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.main import main
from app.platform_publish import PLATFORMS, generate_platform_publish_package
from app.web import build_server, list_rendered_videos


def test_generate_platform_publish_package_writes_json_and_markdown(tmp_path: Path) -> None:
    package_dir = _write_package(tmp_path / "output", "demo")

    package = generate_platform_publish_package("demo", package_dir)

    assert (package_dir / "platform_publish_package.json").exists()
    assert (package_dir / "platform_publish_package.md").exists()
    assert set(package["platforms"]) == set(PLATFORMS)
    saved = json.loads((package_dir / "platform_publish_package.json").read_text(encoding="utf-8"))
    for asset in saved["platforms"].values():
        assert set(asset) == {
            "platform_name",
            "priority",
            "publish_stage",
            "content_fit",
            "video_length",
            "key_metrics",
            "focus",
            "suitable",
            "suitability_reason",
            "title",
            "description",
            "hashtags",
            "cover_text",
            "pinned_comment",
            "publish_notes",
            "manual_review_risks",
            "copy_block",
        }
        assert "【标题】" in asset["copy_block"]
        assert "【简介】" in asset["copy_block"]
        assert "【话题】" in asset["copy_block"]
        assert "【首评/置顶评论】" in asset["copy_block"]
        assert asset["content_fit"]
        assert isinstance(asset["priority"], int)
        assert asset["publish_stage"]
        assert asset["video_length"]
        assert asset["key_metrics"]
        assert asset["focus"]


def test_low_confidence_package_requires_manual_review(tmp_path: Path) -> None:
    package_dir = _write_package(tmp_path / "output", "demo", approved=False, low_confidence=True)

    package = generate_platform_publish_package("demo", package_dir)

    for asset in package["platforms"].values():
        joined_notes = "\n".join(asset["publish_notes"])
        joined_risks = "\n".join(asset["manual_review_risks"])
        assert "发布前必须人工核查" in joined_notes
        assert "发布前必须人工核查" in joined_risks


def test_platform_publish_copy_uses_observation_style_without_income_promises(tmp_path: Path) -> None:
    package_dir = _write_package(tmp_path / "output", "demo")

    package = generate_platform_publish_package("demo", package_dir)

    banned = ["教你赚钱", "照做赚钱", "保证收益", "月入", "稳赚"]
    joined = "\n".join(
        "\n".join([asset["title"], asset["description"], asset["copy_block"]])
        for asset in package["platforms"].values()
    )
    assert any(phrase in joined for phrase in ["为什么", "海外 AI 工具观察", "AI 商业机会", "开发者"])
    for phrase in banned:
        assert phrase not in joined


def test_cli_generates_single_platform_package(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"
    _write_package(output_dir, "demo")

    exit_code = main(
        [
            "--generate-platform-package",
            "demo",
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "demo" / "platform_publish_package.json").exists()
    assert (output_dir / "demo" / "platform_publish_package.md").exists()


def test_cli_generates_all_rendered_platform_packages(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"
    _write_package(output_dir, "demo_a")
    _write_package(output_dir, "demo_b")
    _write_package(output_dir, "draft_without_video")
    (output_dir / "draft_without_video" / "final_video.mp4").unlink()

    exit_code = main(
        [
            "--generate-platform-packages-all",
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "demo_a" / "platform_publish_package.json").exists()
    assert (output_dir / "demo_b" / "platform_publish_package.json").exists()
    assert not (output_dir / "draft_without_video" / "platform_publish_package.json").exists()


def test_web_videos_and_output_show_platform_package_ui(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    package_dir = _write_package(output_dir, "demo")
    generate_platform_publish_package("demo", package_dir)
    videos = list_rendered_videos(output_dir)
    assert videos[0]["platform_package_exists"] is True

    server = build_server("127.0.0.1", 0)
    server.output_dir = output_dir
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/videos", timeout=5) as response:
            videos_html = response.read().decode("utf-8")
        assert "平台发布包: 已生成" in videos_html
        assert "/platform-publish-package" in videos_html
        assert "刷新发布包" in videos_html
        assert "展开五平台发布文案" in videos_html
        assert "video-list" in videos_html
        assert "video-main" in videos_html
        assert "<textarea readonly>" in videos_html
        assert "抖音" in videos_html
        assert "快手" in videos_html
        assert "微信视频号" in videos_html
        assert "B站" in videos_html
        assert "小红书" in videos_html
        assert "小红书当前先滞后处理" in videos_html

        with urlopen(f"http://{host}:{port}/outputs/demo", timeout=5) as response:
            detail_html = response.read().decode("utf-8")
        assert "多平台发布包" in detail_html
        assert "<textarea readonly>" in detail_html
        assert "【首评/置顶评论】" in detail_html
        assert "抖音" in detail_html
        assert "B站" in detail_html
        assert "小红书" in detail_html
    finally:
        server.shutdown()
        server.server_close()


def test_xiaohongshu_is_deferred_not_primary(tmp_path: Path) -> None:
    package_dir = _write_package(tmp_path / "output", "demo")

    package = generate_platform_publish_package("demo", package_dir)
    xiaohongshu = package["platforms"]["xiaohongshu"]

    assert xiaohongshu["publish_stage"] == "deferred"
    assert xiaohongshu["priority"] == 99
    assert xiaohongshu["suitable"] is False
    assert "滞后处理" in xiaohongshu["suitability_reason"]


def test_web_generate_platform_package_button_writes_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    _write_package(output_dir, "demo")

    server = build_server("127.0.0.1", 0)
    server.output_dir = output_dir
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        payload = urlencode({"content_id": "demo", "return_to": "/outputs/demo"}).encode("utf-8")
        request = Request(f"http://{host}:{port}/platform-publish-package", data=payload, method="POST")
        with urlopen(request, timeout=5) as response:
            html = response.read().decode("utf-8")
        assert (output_dir / "demo" / "platform_publish_package.json").exists()
        assert "多平台发布包" in html
        assert "<textarea readonly>" in html
    finally:
        server.shutdown()
        server.server_close()


def _write_package(output_dir: Path, content_id: str, *, approved: bool = True, low_confidence: bool = False) -> Path:
    package_dir = output_dir / content_id
    package_dir.mkdir(parents=True)
    confidence = "low_metadata_only" if low_confidence else "higher_transcript_based"
    review_status = "approved" if approved else "pending"
    (package_dir / "meta.json").write_text(
        json.dumps(
            {
                "content_id": content_id,
                "source_type": "youtube_video",
                "title": "n8n playground changes everything",
                "source_url": "https://youtube.com/watch?v=demo",
                "channel_title": "Demo Channel",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (package_dir / "analysis.json").write_text(
        json.dumps(
            {
                "core_topic": "n8n 免费自动化工作流",
                "summary": "这条内容解释 n8n playground 如何降低自动化工作流的上手门槛。",
                "content_type": "ai_tool_explainer",
                "main_points": ["免费创建实例", "快速搭建工作流", "发布前要核查官方限制"],
                "facts_to_check": ["免费额度和注册条件是否仍然有效"],
                "risk_points": ["不要把免费体验说成永久免费"],
                "factual_confidence": confidence,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (package_dir / "chinese_script.md").write_text(
        "# 标题\n\nn8n 免费自动化工作流\n\n# 口播稿\n\nn8n playground 的看点不是免费两个字，而是让新手更快理解工作流自动化。\n\n# 风险点\n\n- 核查免费额度。\n",
        encoding="utf-8",
    )
    (package_dir / "risk_report.json").write_text(
        json.dumps({"pass": True, "risk_level": "low", "must_review": ["免费额度"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (package_dir / "quality_check.json").write_text(
        json.dumps({"pass": True, "quality_score": 82, "ready_for_human_review": True}, ensure_ascii=False),
        encoding="utf-8",
    )
    (package_dir / "publish_review.json").write_text(
        json.dumps({"schema_version": 1, "content_id": content_id, "status": review_status}, ensure_ascii=False),
        encoding="utf-8",
    )
    (package_dir / "render_status.json").write_text(
        json.dumps({"status": "succeeded", "duration_seconds": 12.3}, ensure_ascii=False),
        encoding="utf-8",
    )
    (package_dir / "final_video.mp4").write_bytes(b"fake-video")
    return package_dir
