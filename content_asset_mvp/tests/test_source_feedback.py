from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from app.feedback_analysis import analyze_feedback
from app.main import main
from app.source_feedback import apply_source_feedback, generate_source_feedback_report
from app.source_scorer import score_candidate
from app.web import build_server


def test_low_data_marks_source_feedback_insufficient(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    sources_path = _write_sources(tmp_path)
    _write_package(output_dir, "demo", "ai_agent_workflow_keyword")
    feedback_path = tmp_path / "feedback_report.json"
    feedback_path.write_text(json.dumps(analyze_feedback([]), ensure_ascii=False), encoding="utf-8")

    report = generate_source_feedback_report(output_dir, tmp_path / "source_feedback_report.json", feedback_report_path=feedback_path, sources_path=sources_path)

    assert report["total_scored_tasks"] == 0
    assert report["source_suggestions"][0]["action"] == "insufficient_data"
    assert report["source_suggestions"][0]["recommended_weight_delta"] == 0.0


def test_source_feedback_generates_increase_and_decrease(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    sources_path = _write_sources(tmp_path)
    high_tasks = _tasks("high", [{"views": 60000, "likes": 6000, "comments": 900, "favorites": 2500, "shares": 600, "completion_rate": 0.82}] * 3)
    low_tasks = _tasks("low", [{"views": 10, "likes": 0, "comments": 0, "favorites": 0, "shares": 0}] * 3)
    _write_package(output_dir, "high", "ai_agent_workflow_keyword")
    _write_package(output_dir, "low", "github_ai_project_keyword")
    feedback_path = tmp_path / "feedback_report.json"
    feedback_path.write_text(json.dumps(analyze_feedback(high_tasks + low_tasks), ensure_ascii=False), encoding="utf-8")

    report = generate_source_feedback_report(output_dir, tmp_path / "source_feedback_report.json", feedback_report_path=feedback_path, sources_path=sources_path)
    by_source = {item["source_key"]: item for item in report["source_suggestions"]}

    assert by_source["ai_agent_workflow_keyword"]["action"] == "increase"
    assert by_source["ai_agent_workflow_keyword"]["recommended_weight_delta"] > 0
    assert by_source["github_ai_project_keyword"]["action"] == "decrease"
    assert by_source["github_ai_project_keyword"]["recommended_weight_delta"] < 0


def test_dry_run_does_not_modify_sources_yaml(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    sources_path = _write_sources(tmp_path)
    original = sources_path.read_text(encoding="utf-8")
    _write_package(output_dir, "demo", "ai_agent_workflow_keyword")
    feedback_path = tmp_path / "feedback_report.json"
    feedback_path.write_text(
        json.dumps(analyze_feedback(_tasks("demo", [{"views": 1000, "likes": 10, "comments": 1}]))),
        encoding="utf-8",
    )

    result = apply_source_feedback(
        output_dir,
        dry_run=True,
        report_path=tmp_path / "source_feedback_report.json",
        feedback_report_path=feedback_path,
        sources_path=sources_path,
        audit_path=tmp_path / "source_feedback_audit.json",
    )

    assert result["application"]["dry_run"] is True
    assert sources_path.read_text(encoding="utf-8") == original
    assert not (tmp_path / "source_feedback_audit.json").exists()


def test_web_source_feedback_button_and_report_display(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_sources(data_dir)
    _write_package(output_dir, "demo", "ai_agent_workflow_keyword")
    feedback = analyze_feedback(_tasks("demo", [{"views": 0, "likes": 0, "comments": 0}]))
    (data_dir / "feedback_report.json").write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")

    server = build_server("127.0.0.1", 0)
    server.output_dir = output_dir
    server.data_dir = data_dir
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/feedback-board", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "生成源池反馈建议" in html
        assert "数据不足时会标记 insufficient_data" in html

        request = Request(f"http://{host}:{port}/feedback-board/source-feedback", data=b"", method="POST")
        with urlopen(request, timeout=5) as response:
            refreshed_html = response.read().decode("utf-8")
        assert "源池反馈建议" in refreshed_html
        assert "AI Agent Workflow" in refreshed_html
        assert (data_dir / "source_feedback_report.json").exists()
    finally:
        server.shutdown()
        server.server_close()


def test_scorer_reads_feedback_weight() -> None:
    neutral = score_candidate(_candidate_with_weight(0.0))
    boosted = score_candidate(_candidate_with_weight(0.2))

    assert boosted["score"] > neutral["score"]
    assert "source_feedback_weight" in " ".join(boosted["score_reasons"])


def test_cli_generates_source_feedback_report(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sources_path = _write_sources(data_dir)
    report_path = data_dir / "source_feedback_report.json"
    feedback_path = data_dir / "feedback_report.json"
    _write_package(output_dir, "demo", "ai_agent_workflow_keyword")
    feedback_path.write_text(
        json.dumps(analyze_feedback(_tasks("demo", [{"views": 0, "likes": 0, "comments": 0}]))),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--generate-source-feedback-report",
            "--mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
            "--source-feedback-report-path",
            str(report_path),
            "--sources-path",
            str(sources_path),
        ]
    )

    assert exit_code == 0
    assert report_path.exists()


def _candidate_with_weight(weight: float) -> dict[str, object]:
    return {
        "name": "AI automation project",
        "url": "https://github.com/example/ai-automation",
        "source_type": "github_repo",
        "category": "ai_projects",
        "reason": "Useful AI automation project.",
        "discovered_from": {"trust_score": 7, "feedback_weight": weight},
        "signals": {"stars": 100, "updated_at": "2026-04-01T00:00:00Z"},
    }


def _tasks(content_id: str, metric_sets: list[dict[str, object]]) -> list[dict[str, object]]:
    platforms = ["douyin", "kuaishou", "wechat_channels", "bilibili", "xiaohongshu"]
    names = ["抖音", "快手", "微信视频号", "B站", "小红书"]
    tasks = []
    for index, metrics in enumerate(metric_sets):
        platform = platforms[index % len(platforms)]
        tasks.append(
            {
                "task_id": f"{content_id}__{platform}_{index}",
                "content_id": content_id,
                "platform": platform,
                "platform_name": names[index % len(names)],
                "metrics": metrics,
            }
        )
    return tasks


def _write_package(output_dir: Path, content_id: str, source_id: str) -> Path:
    package_dir = output_dir / content_id
    package_dir.mkdir(parents=True)
    (package_dir / "meta.json").write_text(
        json.dumps(
            {
                "content_id": content_id,
                "source_type": "youtube_video",
                "title": content_id,
                "source_url": f"https://youtube.com/watch?v={content_id}",
                "channel_title": "Demo Channel",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    source_name = "AI Agent Workflow" if source_id == "ai_agent_workflow_keyword" else "GitHub AI Project Discovery"
    (package_dir / "youtube_candidate.json").write_text(
        json.dumps(
            {
                "candidate_id": f"cand_{content_id}",
                "source_id": source_id,
                "source_type": "youtube_video",
                "name": content_id,
                "url": f"https://youtube.com/watch?v={content_id}",
                "discovered_from": {
                    "source_id": source_id,
                    "name": source_name,
                    "source_type": "keyword",
                    "trust_score": 7,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return package_dir


def _write_sources(tmp_path: Path) -> Path:
    source_path = tmp_path / "sources.yaml"
    source_path.write_text(
        """
sources:
  - source_id: ai_agent_workflow_keyword
    source_type: keyword
    name: AI Agent Workflow
    category: ai_agents
    trust_score: 7
    status: active
    urls: {}
    watch_keywords:
      - AI agent workflow
    feedback_weight: 0.0
  - source_id: github_ai_project_keyword
    source_type: keyword
    name: GitHub AI Project Discovery
    category: ai_projects
    trust_score: 7
    status: active
    urls: {}
    watch_keywords:
      - AI agent framework
    feedback_weight: 0.0
""".strip(),
        encoding="utf-8",
    )
    return source_path
