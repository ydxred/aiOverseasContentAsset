from __future__ import annotations

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


def _bool_to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return 1 if value.strip().lower() in {"1", "true", "yes", "y", "on"} else 0
    return 1 if bool(value) else 0

