from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.main import main
from app.platform_accounts import default_platform_accounts, init_platform_accounts, save_platform_accounts
from app.platform_publish import PLATFORMS, generate_platform_publish_package
from app.publish_adapter import dry_run_publish_task, dry_run_ready_publish_tasks, load_publish_attempts
from app.publish_board import generate_publish_tasks, load_publish_tasks, update_publish_task
from app.web import build_server


def test_platform_account_template_is_non_sensitive(tmp_path: Path) -> None:
    accounts_path = tmp_path / "data" / "platform_accounts.yaml"

    accounts = init_platform_accounts(accounts_path)

    assert accounts_path.exists()
    assert len(accounts) == len(PLATFORMS)
    assert {account["platform"] for account in accounts} == set(PLATFORMS)
    assert all(account["enabled"] is True for account in accounts)
    assert all(account["auto_publish_enabled"] is False for account in accounts)
    text = accounts_path.read_text(encoding="utf-8").lower()
    assert "password" not in text
    assert "cookie" not in text
    assert "token" not in text


def test_single_task_dry_run_records_attempt_without_publishing(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    accounts_path = tmp_path / "data" / "platform_accounts.yaml"
    package_dir = _write_package(output_dir, "demo")
    generate_platform_publish_package("demo", package_dir)
    generate_publish_tasks("demo", package_dir)
    update_publish_task(output_dir, "demo__douyin", {"status": "ready"})
    init_platform_accounts(accounts_path)

    attempt = dry_run_publish_task(output_dir, accounts_path, "demo__douyin")

    assert attempt["status"] == "succeeded"
    assert attempt["mode"] == "dry_run"
    assert attempt["metadata_ready"] is True
    assert attempt["publish_url"]
    assert (package_dir / "publish_attempts.json").exists()
    attempts = load_publish_attempts(package_dir)
    assert attempts[-1]["attempt_id"] == attempt["attempt_id"]
    task = {item["task_id"]: item for item in load_publish_tasks(package_dir)}["demo__douyin"]
    assert task["status"] == "ready"
    assert task["last_attempt_status"] == "succeeded"


def test_ready_scheduled_batch_dry_run_skips_disabled_accounts(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    accounts_path = tmp_path / "data" / "platform_accounts.yaml"
    package_dir = _write_package(output_dir, "demo")
    generate_platform_publish_package("demo", package_dir)
    generate_publish_tasks("demo", package_dir)
    update_publish_task(output_dir, "demo__douyin", {"status": "ready"})
    update_publish_task(output_dir, "demo__kuaishou", {"status": "scheduled"})
    accounts = default_platform_accounts()
    for account in accounts:
        if account["platform"] == "kuaishou":
            account["enabled"] = False
    init_platform_accounts(accounts_path)

    save_platform_accounts(accounts_path, accounts)

    attempts = dry_run_ready_publish_tasks(output_dir, accounts_path)

    assert [attempt["task_id"] for attempt in attempts] == ["demo__douyin"]
    assert attempts[0]["status"] == "succeeded"


def test_cli_dry_run_ready_writes_attempts(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"
    package_dir = _write_package(output_dir, "demo")
    generate_platform_publish_package("demo", package_dir)
    generate_publish_tasks("demo", package_dir)
    update_publish_task(output_dir, "demo__douyin", {"status": "ready"})

    exit_code = main(
        [
            "--publish-dry-run-ready",
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    assert load_publish_attempts(package_dir)


def test_web_accounts_and_publish_board_dry_run_controls(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    data_dir = tmp_path / "data"
    package_dir = _write_package(output_dir, "demo")
    generate_platform_publish_package("demo", package_dir)
    generate_publish_tasks("demo", package_dir)
    update_publish_task(output_dir, "demo__douyin", {"status": "ready"})

    server = build_server("127.0.0.1", 0)
    server.output_dir = output_dir
    server.data_dir = data_dir
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/platform-accounts", timeout=5) as response:
            accounts_html = response.read().decode("utf-8")
        assert "平台账号配置中心" in accounts_html
        assert "保存非敏感配置" in accounts_html
        assert "发布入口" in accounts_html
        assert "auto_publish_enabled" in accounts_html

        with urlopen(f"http://{host}:{port}/publish-board", timeout=5) as response:
            board_html = response.read().decode("utf-8")
        assert "账号配置" in board_html
        assert "Dry-run 所有 ready/scheduled" in board_html
        assert "Dry-run 发布检查" in board_html
        assert "最近 dry-run：暂无" in board_html

        payload = urlencode({"task_id": "demo__douyin"}).encode("utf-8")
        request = Request(f"http://{host}:{port}/publish-dry-run", data=payload, method="POST")
        with urlopen(request, timeout=5) as response:
            updated_html = response.read().decode("utf-8")
        assert "最近 dry-run" in updated_html
        assert "succeeded" in updated_html
        assert load_publish_attempts(package_dir)
    finally:
        server.shutdown()
        server.server_close()


def _write_package(output_dir: Path, content_id: str) -> Path:
    package_dir = output_dir / content_id
    package_dir.mkdir(parents=True)
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
                "main_points": ["免费创建实例", "快速搭建工作流", "发布前要核查官方限制"],
                "facts_to_check": ["免费额度和注册条件是否仍然有效"],
                "risk_points": ["不要把免费体验说成永久免费"],
                "factual_confidence": "higher_transcript_based",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (package_dir / "chinese_script.md").write_text(
        "# 标题\n\nn8n 免费自动化工作流\n\n# 口播稿\n\nn8n playground 的看点不是免费两个字，而是让新手更快理解工作流自动化。\n",
        encoding="utf-8",
    )
    (package_dir / "risk_report.json").write_text(json.dumps({"pass": True, "risk_level": "low"}, ensure_ascii=False), encoding="utf-8")
    (package_dir / "quality_check.json").write_text(json.dumps({"pass": True, "quality_score": 82}, ensure_ascii=False), encoding="utf-8")
    (package_dir / "publish_review.json").write_text(json.dumps({"schema_version": 1, "content_id": content_id, "status": "approved"}, ensure_ascii=False), encoding="utf-8")
    (package_dir / "render_status.json").write_text(json.dumps({"status": "succeeded", "duration_seconds": 12.3}, ensure_ascii=False), encoding="utf-8")
    (package_dir / "final_video.mp4").write_bytes(b"fake-video")
    return package_dir
