from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.main import main
from app.platform_publish import PLATFORMS, generate_platform_publish_package
from app.publish_board import filter_and_sort_publish_tasks, generate_publish_tasks, load_publish_tasks, update_publish_task
from app.web import build_server


def test_generate_publish_tasks_writes_one_task_per_platform(tmp_path: Path) -> None:
    package_dir = _write_package(tmp_path / "output", "demo")
    generate_platform_publish_package("demo", package_dir)

    tasks = generate_publish_tasks("demo", package_dir)

    assert len(tasks) == len(PLATFORMS)
    assert (package_dir / "publish_tasks.json").exists()
    assert {task["platform"] for task in tasks} == set(PLATFORMS)
    first = tasks[0]
    assert first["task_id"] == f"demo__{first['platform']}"
    assert first["status"] == "pending_review"
    assert first["priority"] == "normal"
    assert first["metrics"]["views"] == 0
    assert first["metrics"]["likes"] == 0
    assert first["metrics"]["completion_rate"] == 0.0
    assert first["metrics"]["coins"] == 0
    assert first["metrics_latest"]["views"] == 0
    assert first["metric_snapshots"] == []
    assert first["title"]
    assert first["manual_review_risks"]


def test_generate_publish_tasks_preserves_manual_fields(tmp_path: Path) -> None:
    package_dir = _write_package(tmp_path / "output", "demo")
    generate_platform_publish_package("demo", package_dir)
    generate_publish_tasks("demo", package_dir)
    saved = json.loads((package_dir / "publish_tasks.json").read_text(encoding="utf-8"))
    saved["tasks"][0].update(
        {
            "status": "scheduled",
            "priority": "high",
            "scheduled_at": "2026-05-02 20:00",
            "account": "main-account",
            "publish_url": "https://example.com/post",
            "published_at": "2026-05-02 21:00",
            "metrics": {"views": 123, "likes": 4, "comments": 3, "favorites": 2, "shares": 1},
            "metrics_latest": {"views": 456, "likes": 40, "comments": 30, "favorites": 20, "shares": 10},
            "metric_snapshots": [
                {
                    "label": "1h",
                    "captured_at": "2026-05-02T01:00:00Z",
                    "metrics": {"views": 456, "likes": 40, "comments": 30, "favorites": 20, "shares": 10},
                    "note": "首小时",
                }
            ],
            "note": "人工已排期",
        }
    )
    (package_dir / "publish_tasks.json").write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")

    tasks = generate_publish_tasks("demo", package_dir)
    preserved = tasks[0]

    assert preserved["status"] == "scheduled"
    assert preserved["priority"] == "high"
    assert preserved["scheduled_at"] == "2026-05-02 20:00"
    assert preserved["account"] == "main-account"
    assert preserved["publish_url"] == "https://example.com/post"
    assert preserved["published_at"] == "2026-05-02 21:00"
    assert preserved["metrics"]["views"] == 456
    assert preserved["metrics_latest"]["views"] == 456
    assert preserved["metric_snapshots"][0]["label"] == "1h"
    assert preserved["note"] == "人工已排期"


def test_update_publish_task_appends_metric_snapshot_and_syncs_latest(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    package_dir = _write_package(output_dir, "demo")
    generate_platform_publish_package("demo", package_dir)
    generate_publish_tasks("demo", package_dir)

    task = update_publish_task(
        output_dir,
        "demo__douyin",
        {
            "metric_snapshot": {
                "label": "1h",
                "captured_at": "2026-05-02T01:00:00Z",
                "metrics": {"views": "100", "likes": "10", "comments": "2", "completion_rate": "0.5"},
                "note": "首小时",
            }
        },
    )
    task = update_publish_task(
        output_dir,
        "demo__douyin",
        {
            "metric_snapshot": {
                "label": "24h",
                "captured_at": "2026-05-03T00:00:00Z",
                "metrics": {"views": "500", "likes": "60", "comments": "12", "shares": "6", "completion_rate": "0.68"},
                "note": "24小时",
            }
        },
    )

    assert [snapshot["label"] for snapshot in task["metric_snapshots"]] == ["1h", "24h"]
    assert task["metrics_latest"]["views"] == 500
    assert task["metrics"]["views"] == 500
    assert task["metric_snapshots"][-1]["note"] == "24小时"


def test_update_publish_task_legacy_metrics_still_sync_latest(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    package_dir = _write_package(output_dir, "demo")
    generate_platform_publish_package("demo", package_dir)
    generate_publish_tasks("demo", package_dir)

    task = update_publish_task(output_dir, "demo__douyin", {"metrics": {"views": 321, "likes": 12}})

    assert task["metrics"]["views"] == 321
    assert task["metrics_latest"]["views"] == 321
    assert task["metric_snapshots"] == []


def test_filter_and_sort_publish_tasks_prioritizes_actionable_items() -> None:
    tasks = [
        {"task_id": "a", "status": "published", "priority": "urgent", "platform": "douyin", "content_id": "demo"},
        {"task_id": "b", "status": "pending_review", "priority": "normal", "platform": "bilibili", "content_id": "demo"},
        {"task_id": "c", "status": "ready", "priority": "high", "platform": "kuaishou", "content_id": "demo"},
        {"task_id": "d", "status": "scheduled", "priority": "urgent", "scheduled_at": "2026-05-02 20:00", "platform": "douyin", "content_id": "demo"},
    ]

    sorted_tasks = filter_and_sort_publish_tasks(tasks)

    assert [task["task_id"] for task in sorted_tasks] == ["c", "d", "b", "a"]
    assert [task["task_id"] for task in filter_and_sort_publish_tasks(tasks, status="scheduled")] == ["d"]
    assert [task["task_id"] for task in filter_and_sort_publish_tasks(tasks, platform="douyin", sort_by="priority")] == ["d", "a"]


def test_cli_generates_all_publish_tasks(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"
    for content_id in ["demo_a", "demo_b"]:
        package_dir = _write_package(output_dir, content_id)
        generate_platform_publish_package(content_id, package_dir)

    exit_code = main(
        [
            "--generate-publish-tasks-all",
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    assert len(load_publish_tasks(output_dir / "demo_a")) == len(PLATFORMS)
    assert len(load_publish_tasks(output_dir / "demo_b")) == len(PLATFORMS)


def test_web_publish_board_renders_and_updates_task(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    package_dir = _write_package(output_dir, "demo")
    generate_platform_publish_package("demo", package_dir)
    generate_publish_tasks("demo", package_dir)

    server = build_server("127.0.0.1", 0)
    server.output_dir = output_dir
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/publish-board", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "分发审核与排期中心" in html
        assert "刷新全部发布任务" in html
        assert "排序与筛选" in html
        assert "运营优先级" in html
        assert "应用排序/筛选" in html
        assert "保存任务" in html
        assert "发布数据快照" in html
        assert "metric_snapshot_label" in html
        assert "metric_snapshot_captured_at" in html
        assert "metric_snapshot_note" in html
        assert "<option value='1h'" in html
        assert "<option value='24h'" in html
        assert "<option value='7d'" in html
        assert "douyin" in html
        assert "抖音" in html
        assert "快手" in html
        assert "微信视频号" in html
        assert "B站" in html
        assert "小红书" in html
        assert "views" in html

        with urlopen(f"http://{host}:{port}/publish-board?platform=douyin&status=pending_review&sort=platform", timeout=5) as response:
            filtered_html = response.read().decode("utf-8")
        assert "当前显示 1 / 5 条任务" in filtered_html
        assert "douyin" in filtered_html

        payload = urlencode(
            {
                "task_id": "demo__douyin",
                "status": "scheduled",
                "priority": "high",
                "scheduled_at": "2026-05-02 20:00",
                "account": "douyin-main",
                "publish_url": "https://example.com/douyin",
                "published_at": "",
                "views": "100",
                "likes": "10",
                "comments": "3",
                "favorites": "2",
                "shares": "1",
                "note": "等晚高峰发布",
            }
        ).encode("utf-8")
        request = Request(f"http://{host}:{port}/publish-task", data=payload, method="POST")
        with urlopen(request, timeout=5) as response:
            updated_html = response.read().decode("utf-8")
        tasks = {task["task_id"]: task for task in load_publish_tasks(package_dir)}
        assert tasks["demo__douyin"]["status"] == "scheduled"
        assert tasks["demo__douyin"]["priority"] == "high"
        assert tasks["demo__douyin"]["account"] == "douyin-main"
        assert tasks["demo__douyin"]["metrics"]["views"] == 100
        assert "scheduled" in updated_html
        assert "douyin-main" in updated_html

        snapshot_payload = urlencode(
            {
                "task_id": "demo__douyin",
                "metric_snapshot_label": "24h",
                "metric_snapshot_captured_at": "2026-05-03T00:00:00Z",
                "views": "1000",
                "likes": "120",
                "comments": "20",
                "favorites": "30",
                "shares": "12",
                "completion_rate": "0.75",
                "followers": "6",
                "private_messages": "2",
                "coins": "0",
                "search_hits": "30",
                "metric_snapshot_note": "24小时表现",
            }
        ).encode("utf-8")
        request = Request(f"http://{host}:{port}/publish-task", data=snapshot_payload, method="POST")
        with urlopen(request, timeout=5) as response:
            snapshot_html = response.read().decode("utf-8")
        tasks = {task["task_id"]: task for task in load_publish_tasks(package_dir)}
        assert tasks["demo__douyin"]["metric_snapshots"][-1]["label"] == "24h"
        assert tasks["demo__douyin"]["metrics_latest"]["views"] == 1000
        assert tasks["demo__douyin"]["metrics"]["views"] == 1000
        assert "24h" in snapshot_html
        assert "1 个" in snapshot_html
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
