from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from app.feedback_analysis import analyze_feedback, generate_feedback_report, score_publish_task
from app.main import main
from app.platform_publish import generate_platform_publish_package
from app.publish_board import generate_publish_tasks
from app.web import build_server


def test_scores_platform_task_and_marks_proxy_metrics() -> None:
    task = {
        "task_id": "demo__douyin",
        "content_id": "demo",
        "platform": "douyin",
        "platform_name": "抖音",
        "metrics": {"views": 1200, "likes": 96, "comments": 18, "shares": 12},
    }

    scored = score_publish_task(task)

    assert scored["performance_score"] > 0
    assert scored["metric_source"]["type"] == "metrics"
    assert scored["score_breakdown"]["proxy_used"] is True
    proxy_labels = {component["label"] for component in scored["score_breakdown"]["components"] if component["proxy"]}
    assert "完播" in proxy_labels
    assert "转粉" in proxy_labels
    assert "proxy" in scored["score_breakdown"]["components"][0]["proxy_reason"]


def test_feedback_report_summarizes_best_and_weak_tasks() -> None:
    report = analyze_feedback(
        [
            {
                "task_id": "strong__bilibili",
                "content_id": "strong",
                "platform": "bilibili",
                "platform_name": "B站",
                "metrics": {"views": 5000, "likes": 400, "comments": 160, "favorites": 300, "coins": 80, "completion_rate": 0.72},
            },
            {
                "task_id": "weak__xiaohongshu",
                "content_id": "weak",
                "platform": "xiaohongshu",
                "platform_name": "小红书",
                "metrics": {"views": 100, "likes": 1, "comments": 0, "favorites": 0, "shares": 0},
            },
        ]
    )

    assert report["total_tasks"] == 2
    assert report["data_tasks"] == 2
    assert report["best_tasks"][0]["task_id"] == "strong__bilibili"
    assert report["weak_tasks"][0]["task_id"] == "weak__xiaohongshu"
    assert report["content_insights"]
    assert report["platform_insights"]
    assert report["source_weight_suggestions"]


def test_score_publish_task_prefers_latest_snapshot_over_legacy_metrics() -> None:
    task = {
        "task_id": "demo__bilibili",
        "content_id": "demo",
        "platform": "bilibili",
        "platform_name": "B站",
        "metrics": {"views": 10, "likes": 1, "comments": 0, "favorites": 0, "shares": 0},
        "metrics_latest": {"views": 20, "likes": 2, "comments": 0, "favorites": 0, "shares": 0},
        "metric_snapshots": [
            {
                "label": "1h",
                "captured_at": "2026-05-02T01:00:00Z",
                "metrics": {"views": 100, "likes": 10, "comments": 2, "favorites": 3, "shares": 1, "coins": 1},
                "note": "首小时",
            },
            {
                "label": "latest",
                "captured_at": "2026-05-03T00:00:00Z",
                "metrics": {"views": 5000, "likes": 400, "comments": 160, "favorites": 300, "shares": 80, "coins": 80},
                "note": "最新",
            },
        ],
    }

    scored = score_publish_task(task)

    assert scored["metrics"]["views"] == 5000
    assert scored["metric_source"]["type"] == "snapshot"
    assert scored["metric_source"]["label"] == "latest"
    assert scored["metric_source"]["captured_at"] == "2026-05-03T00:00:00Z"
    assert scored["performance_score"] > 0


def test_score_publish_task_falls_back_to_metrics_latest_and_legacy_metrics() -> None:
    latest_scored = score_publish_task(
        {
            "task_id": "demo__douyin",
            "content_id": "demo",
            "platform": "douyin",
            "metrics": {"views": 1},
            "metrics_latest": {"views": 2000, "likes": 100, "comments": 20, "shares": 10},
        }
    )
    legacy_scored = score_publish_task(
        {
            "task_id": "demo__kuaishou",
            "content_id": "demo",
            "platform": "kuaishou",
            "metrics": {"views": 800, "likes": 40, "comments": 8, "favorites": 12, "shares": 4},
        }
    )

    assert latest_scored["metrics"]["views"] == 2000
    assert latest_scored["metric_source"]["type"] == "metrics_latest"
    assert legacy_scored["metrics"]["views"] == 800
    assert legacy_scored["metric_source"]["type"] == "metrics"


def test_analyze_feedback_adds_time_window_summary() -> None:
    report = analyze_feedback(
        [
            {
                "task_id": "demo__bilibili",
                "content_id": "demo",
                "platform": "bilibili",
                "platform_name": "B站",
                "metric_snapshots": [
                    {
                        "label": "1h",
                        "captured_at": "2026-05-02T01:00:00Z",
                        "metrics": {"views": 1000, "likes": 80, "comments": 20, "favorites": 40, "coins": 10},
                    },
                    {
                        "label": "24h",
                        "captured_at": "2026-05-03T00:00:00Z",
                        "metrics": {"views": 4000, "likes": 300, "comments": 80, "favorites": 160, "coins": 50},
                    },
                ],
            }
        ]
    )

    summary = {item["label"]: item for item in report["time_window_summary"]}
    assert summary["1h"]["task_count"] == 1
    assert summary["24h"]["average_score"] > summary["1h"]["average_score"]


def test_cli_generates_feedback_report(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"
    report_path = tmp_path / "data" / "feedback_report.json"
    package_dir = _write_package(output_dir, "demo")
    generate_platform_publish_package("demo", package_dir)
    tasks = generate_publish_tasks("demo", package_dir)
    tasks[0]["metrics"].update({"views": 1000, "likes": 80, "comments": 12, "favorites": 20, "shares": 10})
    _write_tasks(package_dir, tasks)

    exit_code = main(
        [
            "--generate-feedback-report",
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
            "--feedback-report-path",
            str(report_path),
        ]
    )

    assert exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["report_path"] == str(report_path)
    assert report["total_tasks"] == 5
    assert report["data_tasks"] == 1
    assert report["best_tasks"][0]["task_id"] == tasks[0]["task_id"]
    assert report["best_tasks"][0]["metric_source"]["type"] == "metrics"


def test_generate_feedback_report_writes_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    report_path = tmp_path / "data" / "feedback_report.json"
    package_dir = _write_package(output_dir, "demo")
    generate_platform_publish_package("demo", package_dir)
    tasks = generate_publish_tasks("demo", package_dir)
    tasks[0]["metrics"].update({"views": 2000, "likes": 120, "comments": 20, "favorites": 35, "shares": 18})
    _write_tasks(package_dir, tasks)

    report = generate_feedback_report(output_dir, report_path)

    assert report_path.exists()
    assert report["report_path"] == str(report_path)
    assert report["best_platforms"]


def test_web_feedback_board_renders_and_refreshes(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    package_dir = _write_package(output_dir, "demo")
    generate_platform_publish_package("demo", package_dir)
    tasks = generate_publish_tasks("demo", package_dir)
    tasks[0]["metrics"].update({"views": 1500, "likes": 90, "comments": 15, "favorites": 30, "shares": 12})
    _write_tasks(package_dir, tasks)

    server = build_server("127.0.0.1", 0)
    server.output_dir = output_dir
    server.data_dir = data_dir
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/feedback-board", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "平台表现评分与反馈看板" in html
        assert "刷新反馈报告" in html
        assert "最佳平台" in html
        assert "时间窗口汇总" in html
        assert "源池权重建议" in html

        request = Request(f"http://{host}:{port}/feedback-board/refresh", data=b"", method="POST")
        with urlopen(request, timeout=5) as response:
            refreshed_html = response.read().decode("utf-8")
        assert "平台表现评分与反馈看板" in refreshed_html
        assert (data_dir / "feedback_report.json").exists()
    finally:
        server.shutdown()
        server.server_close()


def test_web_feedback_board_explains_no_data(tmp_path: Path) -> None:
    server = build_server("127.0.0.1", 0)
    server.output_dir = tmp_path / "output"
    server.data_dir = tmp_path / "data"
    server.data_dir.mkdir()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/feedback-board", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "还没有可分析的数据" in html
        assert "去发布看板录入数据" in html
    finally:
        server.shutdown()
        server.server_close()


def _write_tasks(package_dir: Path, tasks: list[dict[str, object]]) -> None:
    payload = {"schema_version": 1, "updated_at": "2026-05-02T00:00:00Z", "tasks": tasks}
    (package_dir / "publish_tasks.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


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
    (package_dir / "publish_review.json").write_text(json.dumps({"status": "approved"}, ensure_ascii=False), encoding="utf-8")
    (package_dir / "render_status.json").write_text(json.dumps({"status": "succeeded"}, ensure_ascii=False), encoding="utf-8")
    (package_dir / "final_video.mp4").write_bytes(b"fake-video")
    return package_dir
