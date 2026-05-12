from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, database_url: str | None, *, mock: bool = False):
        self.database_url = database_url
        self.enabled = bool(database_url) and not mock

    @contextmanager
    def connect(self) -> Iterator[Any]:
        if not self.enabled:
            yield None
            return
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg is required for PostgreSQL writes") from exc

        try:
            with psycopg.connect(self.database_url) as conn:
                yield conn
        except Exception as exc:
            raise RuntimeError(f"PostgreSQL operation failed: {exc}") from exc

    def init_schema(self, migration_path: str | Path) -> str:
        if not self.enabled:
            return "Skipped database initialization: DATABASE_URL is not configured or mock mode is enabled."

        path = Path(migration_path)
        if not path.exists():
            raise FileNotFoundError(f"Migration file not found: {path}")

        sql = path.read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.execute(sql)
        return f"Initialized PostgreSQL schema from {path}"

    def record_task(self, content_id: str, task_type: str, status: str, error_message: str | None = None) -> None:
        if not self.enabled:
            return
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (content_id, task_type, status, error_message, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (content_id, task_type, status, error_message, now, now),
            )

    def record_artifact(self, content_id: str, artifact_type: str, file_path: str, version: str = "v1") -> None:
        if not self.enabled:
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (content_id, artifact_type, file_path, version, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (content_id, artifact_type, file_path, version, utc_now()),
            )

    def record_model_run(
        self,
        content_id: str,
        task_type: str,
        provider: str,
        model: str,
        status: str,
        *,
        prompt_version: str = "v1",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_estimate: float | None = None,
        error_message: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_runs (
                  content_id, task_type, provider, model, prompt_version, input_tokens,
                  output_tokens, cost_estimate, status, error_message, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    content_id,
                    task_type,
                    provider,
                    model,
                    prompt_version,
                    input_tokens,
                    output_tokens,
                    cost_estimate,
                    status,
                    error_message,
                    utc_now(),
                ),
            )

    def upsert_content(self, meta: dict[str, Any], status: str = "created") -> None:
        if not self.enabled:
            return
        now = utc_now()
        content_id = meta.get("content_id")
        source_url = meta.get("source_url") or meta.get("webpage_url")
        if not content_id or not source_url:
            raise RuntimeError("content_id and source_url are required to upsert content")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO contents (
                  content_id, source_url, source_type, title, author, published_at,
                  duration, language, status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (content_id) DO UPDATE SET
                  title = EXCLUDED.title,
                  author = EXCLUDED.author,
                  published_at = EXCLUDED.published_at,
                  duration = EXCLUDED.duration,
                  language = EXCLUDED.language,
                  status = EXCLUDED.status,
                  updated_at = EXCLUDED.updated_at
                """,
                (
                    content_id,
                    source_url,
                    meta.get("source_type", "youtube"),
                    meta.get("title"),
                    meta.get("author"),
                    meta.get("published_at"),
                    meta.get("duration"),
                    meta.get("language"),
                    status,
                    now,
                    now,
                ),
            )

    def record_topic_opportunity(self, content_id: str, opportunity: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO topic_opportunities (
                  content_id, topic_cluster, foreign_heat, domestic_gap, user_value,
                  content_rebuildability, risk_score, opportunity_score, decision, reason, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    content_id,
                    opportunity.get("topic_cluster"),
                    opportunity.get("foreign_heat"),
                    opportunity.get("domestic_gap"),
                    opportunity.get("user_value"),
                    opportunity.get("content_rebuildability"),
                    opportunity.get("risk_score"),
                    opportunity.get("opportunity_score"),
                    opportunity.get("decision", "review"),
                    opportunity.get("reason"),
                    utc_now(),
                ),
            )

    def record_media_job(self, content_id: str, media_job: dict[str, Any]) -> None:
        if not self.enabled:
            return
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO media_jobs (
                  content_id, job_type, status, template_id, platform, output_path,
                  error_message, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    content_id,
                    media_job.get("job_type", "short_video"),
                    media_job.get("status", "created"),
                    media_job.get("template_id"),
                    media_job.get("platform"),
                    media_job.get("video_path") or media_job.get("output_path"),
                    media_job.get("error_message") or "; ".join(media_job.get("issues", [])),
                    now,
                    now,
                ),
            )

    def record_feedback(self, content_id: str, feedback: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO feedback (
                  content_id, feedback_type, reviewer, is_topic_useful, is_script_usable,
                  main_issues, notes, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    content_id,
                    feedback.get("feedback_type", "manual_review"),
                    feedback.get("reviewer"),
                    _bool_to_int(feedback.get("is_topic_useful")),
                    _bool_to_int(feedback.get("is_script_usable")),
                    feedback.get("main_issues"),
                    feedback.get("notes"),
                    utc_now(),
                ),
            )

    def sync_source_candidates(self, candidates: list[dict[str, Any]]) -> None:
        if not self.enabled:
            return
        now = utc_now()
        with self.connect() as conn:
            for candidate in candidates:
                candidate_id = str(candidate.get("candidate_id") or "").strip()
                name = str(candidate.get("name") or "").strip()
                url = str(candidate.get("url") or "").strip()
                source_type = str(candidate.get("source_type") or "").strip()
                if not candidate_id or not name or not url or not source_type:
                    continue
                conn.execute(
                    """
                    INSERT INTO source_candidates (
                      candidate_id, source_id, source_type, name, url, category, status,
                      decision, score, reason, signals, discovered_from, raw_payload,
                      review_package_content_id, review_package_generated_at, created_at, updated_at
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s
                    )
                    ON CONFLICT (candidate_id) DO UPDATE SET
                      source_id = EXCLUDED.source_id,
                      source_type = EXCLUDED.source_type,
                      name = EXCLUDED.name,
                      url = EXCLUDED.url,
                      category = EXCLUDED.category,
                      status = EXCLUDED.status,
                      decision = EXCLUDED.decision,
                      score = EXCLUDED.score,
                      reason = EXCLUDED.reason,
                      signals = EXCLUDED.signals,
                      discovered_from = EXCLUDED.discovered_from,
                      raw_payload = EXCLUDED.raw_payload,
                      review_package_content_id = EXCLUDED.review_package_content_id,
                      review_package_generated_at = EXCLUDED.review_package_generated_at,
                      updated_at = EXCLUDED.updated_at
                    """,
                    (
                        candidate_id,
                        candidate.get("source_id"),
                        source_type,
                        name,
                        url,
                        candidate.get("category"),
                        candidate.get("status", "new"),
                        candidate.get("decision"),
                        _int_or_none(candidate.get("score")),
                        candidate.get("reason"),
                        _json(candidate.get("signals", {})),
                        _json(candidate.get("discovered_from", {})),
                        _json(candidate),
                        candidate.get("review_package_content_id"),
                        candidate.get("review_package_generated_at"),
                        candidate.get("created_at") or now,
                        now,
                    ),
                )

    def sync_publish_tasks(self, tasks: list[dict[str, Any]]) -> None:
        if not self.enabled:
            return
        now = utc_now()
        with self.connect() as conn:
            for task in tasks:
                task_id = str(task.get("task_id") or "").strip()
                content_id = str(task.get("content_id") or "").strip()
                platform = str(task.get("platform") or "").strip()
                if not task_id or not content_id or not platform:
                    continue
                updated_at = str(task.get("updated_at") or now)
                conn.execute(
                    """
                    INSERT INTO publish_tasks (
                      task_id, content_id, platform, platform_name, status, priority,
                      scheduled_at, account, publish_url, published_at, title, suitable,
                      metrics, metrics_latest, manual_review_risks, raw_payload, note,
                      created_at, updated_at
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s
                    )
                    ON CONFLICT (task_id) DO UPDATE SET
                      content_id = EXCLUDED.content_id,
                      platform = EXCLUDED.platform,
                      platform_name = EXCLUDED.platform_name,
                      status = EXCLUDED.status,
                      priority = EXCLUDED.priority,
                      scheduled_at = EXCLUDED.scheduled_at,
                      account = EXCLUDED.account,
                      publish_url = EXCLUDED.publish_url,
                      published_at = EXCLUDED.published_at,
                      title = EXCLUDED.title,
                      suitable = EXCLUDED.suitable,
                      metrics = EXCLUDED.metrics,
                      metrics_latest = EXCLUDED.metrics_latest,
                      manual_review_risks = EXCLUDED.manual_review_risks,
                      raw_payload = EXCLUDED.raw_payload,
                      note = EXCLUDED.note,
                      updated_at = EXCLUDED.updated_at
                    """,
                    (
                        task_id,
                        content_id,
                        platform,
                        task.get("platform_name"),
                        task.get("status", "pending_review"),
                        task.get("priority"),
                        task.get("scheduled_at"),
                        task.get("account"),
                        task.get("publish_url"),
                        task.get("published_at"),
                        task.get("title"),
                        _bool_to_int(task.get("suitable")),
                        _json(task.get("metrics", {})),
                        _json(task.get("metrics_latest", {})),
                        _json(task.get("manual_review_risks", [])),
                        _json(task),
                        task.get("note"),
                        task.get("created_at") or updated_at,
                        updated_at,
                    ),
                )
                self._sync_metric_snapshots(conn, task, now)

    def sync_feedback_report(self, report: dict[str, Any], *, report_type: str = "publish_feedback") -> None:
        if not self.enabled or not report:
            return
        generated_at = str(report.get("generated_at") or utc_now())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO feedback_reports (report_type, report_path, generated_at, raw_payload, created_at)
                VALUES (%s, %s, %s, %s::jsonb, %s)
                """,
                (report_type, report.get("report_path"), generated_at, _json(report), utc_now()),
            )

    def sync_source_feedback_report(self, report: dict[str, Any]) -> None:
        if not self.enabled or not report:
            return
        generated_at = str(report.get("generated_at") or utc_now())
        suggestions = report.get("source_suggestions")
        if not isinstance(suggestions, list):
            suggestions = []
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO feedback_reports (report_type, report_path, generated_at, raw_payload, created_at)
                VALUES (%s, %s, %s, %s::jsonb, %s)
                """,
                ("source_feedback", report.get("report_path"), generated_at, _json(report), utc_now()),
            )
            for suggestion in suggestions:
                if not isinstance(suggestion, dict):
                    continue
                conn.execute(
                    """
                    INSERT INTO source_feedback_suggestions (
                      source_key, source_type, source_name, action, recommended_weight_delta,
                      related_content_ids, reasons, evidence_tasks, raw_payload, generated_at, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
                    """,
                    (
                        suggestion.get("source_key", ""),
                        suggestion.get("source_type"),
                        suggestion.get("source_name"),
                        suggestion.get("action", "keep"),
                        _float_or_zero(suggestion.get("recommended_weight_delta")),
                        _json(suggestion.get("related_content_ids", [])),
                        _json(suggestion.get("reasons", [])),
                        _json(suggestion.get("evidence_tasks", [])),
                        _json(suggestion),
                        generated_at,
                        utc_now(),
                    ),
                )

    def list_source_candidates(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self.connect() as conn:
            cursor = conn.execute(
                """
                SELECT raw_payload::text
                FROM source_candidates
                ORDER BY updated_at DESC, id DESC
                """
            )
            return [_json_dict(row[0]) for row in cursor.fetchall()]

    def list_publish_tasks(self, output_dir: Path | None = None) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self.connect() as conn:
            cursor = conn.execute(
                """
                SELECT raw_payload::text
                FROM publish_tasks
                ORDER BY updated_at DESC, id DESC
                """
            )
            tasks = [_json_dict(row[0]) for row in cursor.fetchall()]
        if output_dir is not None:
            for task in tasks:
                content_id = str(task.get("content_id") or "")
                if content_id:
                    task["_package_dir"] = output_dir / content_id
        return tasks

    def latest_feedback_report(self, report_type: str) -> dict[str, Any]:
        if not self.enabled:
            return {}
        with self.connect() as conn:
            cursor = conn.execute(
                """
                SELECT raw_payload::text
                FROM feedback_reports
                WHERE report_type = %s
                ORDER BY generated_at DESC, id DESC
                LIMIT 1
                """,
                (report_type,),
            )
            row = cursor.fetchone()
        return _json_dict(row[0]) if row else {}

    def _sync_metric_snapshots(self, conn: Any, task: dict[str, Any], now: str) -> None:
        snapshots = task.get("metric_snapshots")
        if not isinstance(snapshots, list):
            return
        task_id = str(task.get("task_id") or "")
        content_id = str(task.get("content_id") or "")
        platform = str(task.get("platform") or "")
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            label = str(snapshot.get("label") or "custom")
            captured_at = str(snapshot.get("captured_at") or now)
            conn.execute(
                """
                INSERT INTO publish_metric_snapshots (
                  task_id, content_id, platform, label, captured_at, metrics, note, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (task_id, label, captured_at) DO UPDATE SET
                  metrics = EXCLUDED.metrics,
                  note = EXCLUDED.note
                """,
                (
                    task_id,
                    content_id,
                    platform,
                    label,
                    captured_at,
                    _json(snapshot.get("metrics", {})),
                    snapshot.get("note"),
                    now,
                ),
            )


def _bool_to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return 1 if value.strip().lower() in {"1", "true", "yes", "y", "on"} else 0
    return 1 if bool(value) else 0


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}

