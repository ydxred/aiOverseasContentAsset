from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from app.db import Database


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.rows: list[tuple[Any, ...]] = []
        self.fetchone_row: tuple[Any, ...] | None = None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> "FakeConnection":
        self.calls.append((sql, params))
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.fetchone_row


def _db_with_connection(conn: FakeConnection) -> Database:
    db = Database("postgresql://example", mock=False)

    @contextmanager
    def connect():
        yield conn

    db.connect = connect  # type: ignore[method-assign]
    return db


def test_sync_source_candidates_upserts_candidate_payload() -> None:
    conn = FakeConnection()
    db = _db_with_connection(conn)

    db.sync_source_candidates(
        [
            {
                "candidate_id": "cand_1",
                "source_id": "product_hunt",
                "source_type": "product_launch",
                "name": "AI Launch",
                "url": "https://example.com/launch",
                "status": "new",
                "decision": "review",
                "score": 78,
                "signals": {"votes": 120},
            }
        ]
    )

    assert len(conn.calls) == 1
    sql, params = conn.calls[0]
    assert "source_candidates" in sql
    assert params[0] == "cand_1"
    assert params[2] == "product_launch"


def test_sync_publish_tasks_writes_task_and_metric_snapshot() -> None:
    conn = FakeConnection()
    db = _db_with_connection(conn)

    db.sync_publish_tasks(
        [
            {
                "task_id": "demo__douyin",
                "content_id": "demo",
                "platform": "douyin",
                "platform_name": "抖音",
                "status": "published",
                "priority": "high",
                "suitable": True,
                "metrics": {"views": 1000},
                "metrics_latest": {"views": 1200},
                "metric_snapshots": [
                    {"label": "24h", "captured_at": "2026-05-02T00:00:00Z", "metrics": {"views": 1200}, "note": "24h"}
                ],
            }
        ]
    )

    assert len(conn.calls) == 2
    assert "publish_tasks" in conn.calls[0][0]
    assert "publish_metric_snapshots" in conn.calls[1][0]


def test_sync_source_feedback_report_records_report_and_suggestions() -> None:
    conn = FakeConnection()
    db = _db_with_connection(conn)

    db.sync_source_feedback_report(
        {
            "generated_at": "2026-05-02T00:00:00Z",
            "report_path": "data/source_feedback_report.json",
            "source_suggestions": [
                {
                    "source_key": "github_ai_project_keyword",
                    "source_type": "keyword",
                    "source_name": "GitHub AI Project Discovery",
                    "action": "increase",
                    "recommended_weight_delta": 0.03,
                    "reasons": ["high performance"],
                }
            ],
        }
    )

    assert len(conn.calls) == 2
    assert "feedback_reports" in conn.calls[0][0]
    assert "source_feedback_suggestions" in conn.calls[1][0]


def test_db_first_read_methods_return_raw_payloads() -> None:
    conn = FakeConnection()
    conn.rows = [('{"task_id":"demo__douyin","content_id":"demo","platform":"douyin"}',)]
    db = _db_with_connection(conn)

    tasks = db.list_publish_tasks()

    assert tasks == [{"task_id": "demo__douyin", "content_id": "demo", "platform": "douyin"}]
    assert "publish_tasks" in conn.calls[0][0]


def test_latest_feedback_report_reads_newest_payload() -> None:
    conn = FakeConnection()
    conn.fetchone_row = ('{"report_type":"publish_feedback","total_tasks":5}',)
    db = _db_with_connection(conn)

    report = db.latest_feedback_report("publish_feedback")

    assert report["total_tasks"] == 5
    assert conn.calls[0][1] == ("publish_feedback",)
