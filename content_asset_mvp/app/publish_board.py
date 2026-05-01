from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .platform_publish import PLATFORMS


STATUSES = ["pending_review", "ready", "needs_revision", "scheduled", "published", "rejected", "not_suitable"]
PRIORITIES = ["low", "normal", "high", "urgent"]
SNAPSHOT_LABELS = ["1h", "24h", "7d", "latest", "custom"]
BASE_METRIC_KEYS = ["views", "likes", "comments", "favorites", "shares"]
EXTENDED_METRIC_KEYS = ["completion_rate", "followers", "private_messages", "coins", "search_hits"]
METRIC_KEYS = BASE_METRIC_KEYS + EXTENDED_METRIC_KEYS
MANUAL_FIELDS = {
    "status",
    "priority",
    "scheduled_at",
    "account",
    "publish_url",
    "published_at",
    "metrics",
    "metrics_latest",
    "metric_snapshot",
    "metric_snapshots",
    "note",
}
ATTEMPT_FIELDS = {"last_attempt_id", "last_attempt_status", "last_attempt_at", "last_attempt_mode"}
STATUS_SORT_RANK = {
    "ready": 0,
    "scheduled": 1,
    "pending_review": 2,
    "needs_revision": 3,
    "not_suitable": 4,
    "published": 5,
    "rejected": 6,
}
PRIORITY_SORT_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


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
            "metrics": _latest_metrics_for_task(previous),
            "metrics_latest": _latest_metrics_for_task(previous),
            "metric_snapshots": _normalize_metric_snapshots(previous.get("metric_snapshots")),
            "note": previous.get("note") or "",
            "last_attempt_id": previous.get("last_attempt_id") or "",
            "last_attempt_status": previous.get("last_attempt_status") or "",
            "last_attempt_at": previous.get("last_attempt_at") or "",
            "last_attempt_mode": previous.get("last_attempt_mode") or "",
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


def filter_and_sort_publish_tasks(
    tasks: list[dict[str, Any]],
    *,
    status: str = "",
    platform: str = "",
    sort_by: str = "recommended",
) -> list[dict[str, Any]]:
    filtered = []
    for task in tasks:
        if status and task.get("status") != status:
            continue
        if platform and task.get("platform") != platform:
            continue
        filtered.append(task)
    return sorted(filtered, key=lambda task: _task_sort_key(task, sort_by))


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
                    task["metrics"] = metrics
                    task["metrics_latest"] = metrics
                elif key == "metrics_latest":
                    metrics = _normalize_metrics(value)
                    task["metrics_latest"] = metrics
                    task["metrics"] = metrics
                elif key == "metric_snapshot":
                    snapshot = _normalize_metric_snapshot(value)
                    task.setdefault("metric_snapshots", [])
                    if isinstance(task["metric_snapshots"], list):
                        task["metric_snapshots"].append(snapshot)
                    _sync_latest_metrics_from_snapshot(task, snapshot)
                elif key == "metric_snapshots":
                    snapshots = _normalize_metric_snapshots(value)
                    task["metric_snapshots"] = _normalize_metric_snapshots(task.get("metric_snapshots")) + snapshots
                    if snapshots:
                        _sync_latest_metrics_from_snapshot(task, snapshots[-1])
                else:
                    task[key] = value
        task["metric_snapshots"] = _normalize_metric_snapshots(task.get("metric_snapshots"))
        task["metrics_latest"] = _latest_metrics_for_task(task)
        task["metrics"] = _normalize_metrics(task.get("metrics_latest"))
        task["updated_at"] = now
        _write_tasks(package_dir, tasks)
        return task
    raise FileNotFoundError(f"Publish task not found: {task_id}")


def update_publish_task_attempt(output_dir: Path, task_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    package_dir = _find_task_package(output_dir, task_id)
    tasks = load_publish_tasks(package_dir)
    now = _utc_now()
    for task in tasks:
        if task.get("task_id") != task_id:
            continue
        for key, value in updates.items():
            if key in ATTEMPT_FIELDS:
                task[key] = value
        task["updated_at"] = now
        _write_tasks(package_dir, tasks)
        return task
    raise FileNotFoundError(f"Publish task not found: {task_id}")


def make_task_id(content_id: str, platform: str) -> str:
    return f"{content_id}__{platform}"


def _task_sort_key(task: dict[str, Any], sort_by: str) -> tuple[Any, ...]:
    status = str(task.get("status") or "pending_review")
    priority = str(task.get("priority") or "normal")
    platform = str(task.get("platform") or "")
    scheduled_at = str(task.get("scheduled_at") or "")
    content_id = str(task.get("content_id") or "")
    metrics = _normalize_metrics(task.get("metrics"))
    if sort_by == "scheduled_at":
        return (0 if scheduled_at else 1, scheduled_at, STATUS_SORT_RANK.get(status, 99), platform, content_id)
    if sort_by == "priority":
        return (PRIORITY_SORT_RANK.get(priority, 99), STATUS_SORT_RANK.get(status, 99), scheduled_at or "9999", platform, content_id)
    if sort_by == "platform":
        return (list(PLATFORMS).index(platform) if platform in PLATFORMS else 99, STATUS_SORT_RANK.get(status, 99), content_id)
    if sort_by == "performance":
        engagement = metrics["likes"] + metrics["comments"] + metrics["favorites"] + metrics["shares"]
        return (-metrics["views"], -engagement, STATUS_SORT_RANK.get(status, 99), platform, content_id)
    return (
        STATUS_SORT_RANK.get(status, 99),
        PRIORITY_SORT_RANK.get(priority, 99),
        0 if scheduled_at else 1,
        scheduled_at or "9999",
        list(PLATFORMS).index(platform) if platform in PLATFORMS else 99,
        content_id,
    )


def _find_task_package(output_dir: Path, task_id: str) -> Path:
    for package_dir in sorted(path for path in output_dir.iterdir() if path.is_dir()):
        if any(task.get("task_id") == task_id for task in load_publish_tasks(package_dir)):
            return package_dir
    raise FileNotFoundError(f"Publish task not found: {task_id}")


def _write_tasks(package_dir: Path, tasks: list[dict[str, Any]]) -> None:
    payload = {"schema_version": 1, "updated_at": _utc_now(), "tasks": tasks}
    (package_dir / "publish_tasks.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _latest_metrics_for_task(task: dict[str, Any]) -> dict[str, int | float]:
    snapshots = _normalize_metric_snapshots(task.get("metric_snapshots"))
    if snapshots:
        return _normalize_metrics(snapshots[-1].get("metrics"))
    metrics_latest = _normalize_metrics(task.get("metrics_latest"))
    legacy_metrics = _normalize_metrics(task.get("metrics"))
    if _has_metric_data(metrics_latest) or not _has_metric_data(legacy_metrics):
        return metrics_latest
    return legacy_metrics


def _sync_latest_metrics_from_snapshot(task: dict[str, Any], snapshot: dict[str, Any]) -> None:
    metrics = _normalize_metrics(snapshot.get("metrics"))
    task["metrics_latest"] = metrics
    task["metrics"] = metrics


def _normalize_metric_snapshots(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_normalize_metric_snapshot(item) for item in value if isinstance(item, dict)]


def _normalize_metric_snapshot(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    label = str(source.get("label") or "custom").strip() or "custom"
    if label not in SNAPSHOT_LABELS:
        label = "custom"
    captured_at = str(source.get("captured_at") or "").strip() or _utc_now()
    note = str(source.get("note") or "").strip()
    return {
        "label": label,
        "captured_at": captured_at,
        "metrics": _normalize_metrics(source.get("metrics")),
        "note": note,
    }


def _normalize_metrics(value: Any) -> dict[str, int | float]:
    source = value if isinstance(value, dict) else {}
    metrics: dict[str, int | float] = {}
    for key in METRIC_KEYS:
        metrics[key] = _parse_metric_value(key, source.get(key, 0))
    return metrics


def _has_metric_data(metrics: dict[str, int | float]) -> bool:
    return any(metrics.get(key, 0) > 0 for key in METRIC_KEYS)


def _normalize_metric_updates(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    updates: dict[str, int | float] = {}
    for key, raw in value.items():
        if key not in METRIC_KEYS:
            continue
        updates[key] = _parse_metric_value(key, raw)
    return updates


def _parse_metric_value(key: str, raw: Any) -> int | float:
    if key == "completion_rate":
        try:
            return max(0.0, float(raw or 0))
        except (TypeError, ValueError):
            return 0.0
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


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
