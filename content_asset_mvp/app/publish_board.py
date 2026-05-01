from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .platform_publish import PLATFORMS


STATUSES = ["pending_review", "ready", "needs_revision", "scheduled", "published", "rejected", "not_suitable"]
PRIORITIES = ["low", "normal", "high", "urgent"]
METRIC_KEYS = ["views", "likes", "comments", "favorites", "shares"]
MANUAL_FIELDS = {"status", "priority", "scheduled_at", "account", "publish_url", "published_at", "metrics", "note"}


def generate_publish_tasks(content_id: str, package_dir: Path) -> list[dict[str, Any]]:
    package_path = package_dir / "platform_publish_package.json"
    package = _read_json(package_path)
    if not package:
        raise FileNotFoundError(f"Platform publish package not found: {package_path}")

    existing = {str(task.get("task_id")): task for task in load_publish_tasks(package_dir)}
    platforms = package.get("platforms", {})
    tasks: list[dict[str, Any]] = []
    now = _utc_now()

    for platform in PLATFORMS:
        asset = platforms.get(platform)
        if not isinstance(asset, dict):
            continue
        task_id = make_task_id(content_id, platform)
        previous = existing.get(task_id, {})
        suitable = bool(asset.get("suitable"))
        default_status = "pending_review" if suitable else "not_suitable"
        task = {
            "task_id": task_id,
            "content_id": content_id,
            "platform": platform,
            "platform_name": asset.get("platform_name") or PLATFORMS[platform]["platform_name"],
            "status": previous.get("status") or default_status,
            "priority": previous.get("priority") or "normal",
            "scheduled_at": previous.get("scheduled_at") or "",
            "account": previous.get("account") or "",
            "publish_url": previous.get("publish_url") or "",
            "published_at": previous.get("published_at") or "",
            "metrics": _normalize_metrics(previous.get("metrics")),
            "note": previous.get("note") or "",
            "title": asset.get("title") or "",
            "suitable": suitable,
            "manual_review_risks": _as_text_list(asset.get("manual_review_risks")),
            "updated_at": now,
        }
        tasks.append(task)

    _write_tasks(package_dir, tasks)
    return tasks


def generate_publish_tasks_all(output_dir: Path) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    if not output_dir.exists():
        return tasks
    for package_dir in sorted(path for path in output_dir.iterdir() if path.is_dir()):
        if not (package_dir / "platform_publish_package.json").exists():
            continue
        tasks.extend(generate_publish_tasks(package_dir.name, package_dir))
    return tasks


def load_publish_tasks(package_dir: Path) -> list[dict[str, Any]]:
    data = _read_json(package_dir / "publish_tasks.json")
    if isinstance(data.get("tasks"), list):
        return [task for task in data["tasks"] if isinstance(task, dict)]
    return []


def load_all_publish_tasks(output_dir: Path) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    if not output_dir.exists():
        return tasks
    for package_dir in sorted((path for path in output_dir.iterdir() if path.is_dir()), key=lambda path: path.name):
        for task in load_publish_tasks(package_dir):
            task_copy = dict(task)
            task_copy["_package_dir"] = package_dir
            tasks.append(task_copy)
    return tasks


def update_publish_task(output_dir: Path, task_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    package_dir = _find_task_package(output_dir, task_id)
    tasks = load_publish_tasks(package_dir)
    now = _utc_now()
    for task in tasks:
        if task.get("task_id") != task_id:
            continue
        for key, value in updates.items():
            if key in MANUAL_FIELDS:
                if key == "metrics":
                    metrics = _normalize_metrics(task.get("metrics"))
                    metrics.update(_normalize_metric_updates(value))
                    task[key] = metrics
                else:
                    task[key] = value
        task["metrics"] = _normalize_metrics(task.get("metrics"))
        task["updated_at"] = now
        _write_tasks(package_dir, tasks)
        return task
    raise FileNotFoundError(f"Publish task not found: {task_id}")


def make_task_id(content_id: str, platform: str) -> str:
    return f"{content_id}__{platform}"


def _find_task_package(output_dir: Path, task_id: str) -> Path:
    for package_dir in sorted(path for path in output_dir.iterdir() if path.is_dir()):
        if any(task.get("task_id") == task_id for task in load_publish_tasks(package_dir)):
            return package_dir
    raise FileNotFoundError(f"Publish task not found: {task_id}")


def _write_tasks(package_dir: Path, tasks: list[dict[str, Any]]) -> None:
    payload = {"schema_version": 1, "updated_at": _utc_now(), "tasks": tasks}
    (package_dir / "publish_tasks.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_metrics(value: Any) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    metrics: dict[str, int] = {}
    for key in METRIC_KEYS:
        try:
            metrics[key] = max(0, int(source.get(key, 0) or 0))
        except (TypeError, ValueError):
            metrics[key] = 0
    return metrics


def _normalize_metric_updates(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    updates: dict[str, int] = {}
    for key, raw in value.items():
        if key not in METRIC_KEYS:
            continue
        try:
            updates[key] = max(0, int(raw or 0))
        except (TypeError, ValueError):
            updates[key] = 0
    return updates


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
