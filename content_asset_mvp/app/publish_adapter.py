from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .platform_accounts import account_by_platform, load_platform_accounts
from .publish_board import load_all_publish_tasks, load_publish_tasks, update_publish_task_attempt


DRY_RUN_READY_STATUSES = {"ready", "scheduled"}
ATTEMPTS_FILENAME = "publish_attempts.json"


def dry_run_publish_task(output_dir: Path, accounts_path: Path, task_id: str) -> dict[str, Any]:
    package_dir, task = _find_task(output_dir, task_id)
    accounts = account_by_platform(load_platform_accounts(accounts_path))
    account = accounts.get(str(task.get("platform") or ""))
    attempt = _run_dry_run(task, package_dir, account)
    _append_attempt(package_dir, attempt)
    update_publish_task_attempt(
        output_dir,
        task_id,
        {
            "last_attempt_id": attempt["attempt_id"],
            "last_attempt_status": attempt["status"],
            "last_attempt_at": attempt["created_at"],
            "last_attempt_mode": attempt["mode"],
        },
    )
    return attempt


def dry_run_ready_publish_tasks(output_dir: Path, accounts_path: Path) -> list[dict[str, Any]]:
    accounts = account_by_platform(load_platform_accounts(accounts_path))
    attempts: list[dict[str, Any]] = []
    for task in load_all_publish_tasks(output_dir):
        status = str(task.get("status") or "")
        platform = str(task.get("platform") or "")
        account = accounts.get(platform)
        if status not in DRY_RUN_READY_STATUSES:
            continue
        if not account or not account.get("enabled"):
            continue
        attempts.append(dry_run_publish_task(output_dir, accounts_path, str(task.get("task_id"))))
    return attempts


def load_publish_attempts(package_dir: Path) -> list[dict[str, Any]]:
    data = _read_json(package_dir / ATTEMPTS_FILENAME)
    attempts = data.get("attempts") if isinstance(data, dict) else []
    return [attempt for attempt in attempts if isinstance(attempt, dict)] if isinstance(attempts, list) else []


def latest_attempts_by_task(output_dir: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not output_dir.exists():
        return latest
    for package_dir in sorted(path for path in output_dir.iterdir() if path.is_dir()):
        for attempt in load_publish_attempts(package_dir):
            task_id = str(attempt.get("task_id") or "")
            created_at = str(attempt.get("created_at") or "")
            if task_id and created_at >= str(latest.get(task_id, {}).get("created_at") or ""):
                latest[task_id] = attempt
    return latest


def _run_dry_run(task: dict[str, Any], package_dir: Path, account: dict[str, Any] | None) -> dict[str, Any]:
    platform = str(task.get("platform") or "")
    now = _utc_now()
    attempt = {
        "attempt_id": f"dry_{now.replace(':', '').replace('-', '')}_{uuid.uuid4().hex[:8]}",
        "task_id": str(task.get("task_id") or ""),
        "platform": platform,
        "account_id": str(account.get("account_id") or task.get("account") or "") if account else str(task.get("account") or ""),
        "mode": "dry_run",
        "status": "succeeded",
        "steps": [],
        "video_path": str(package_dir / "final_video.mp4"),
        "metadata_ready": False,
        "publish_url": str(account.get("publish_url") or task.get("publish_url") or "") if account else str(task.get("publish_url") or ""),
        "error": "",
        "created_at": now,
    }
    try:
        _step(attempt, "prepare", _validate_account(account))
        _step(attempt, "upload_video", _validate_video(package_dir / "final_video.mp4"))
        metadata_result = _validate_metadata(package_dir, platform)
        attempt["metadata_ready"] = metadata_result["status"] == "ok"
        _step(attempt, "fill_metadata", metadata_result)
        _step(attempt, "submit", {"status": "ok", "message": "dry-run only; skipped real submit"})
        _step(attempt, "record_result", {"status": "ok", "message": "attempt recorded locally"})
    except ValueError as exc:
        attempt["status"] = "failed"
        attempt["error"] = str(exc)
    return attempt


def _validate_account(account: dict[str, Any] | None) -> dict[str, str]:
    if not account:
        raise ValueError("Platform account is not configured")
    if not account.get("enabled"):
        raise ValueError("Platform account is disabled")
    if not str(account.get("account_id") or "").strip():
        raise ValueError("Platform account_id is missing")
    return {"status": "ok", "message": "account configuration is enabled"}


def _validate_video(video_path: Path) -> dict[str, Any]:
    if not video_path.exists():
        raise ValueError(f"final_video.mp4 not found: {video_path}")
    if video_path.stat().st_size <= 0:
        raise ValueError(f"final_video.mp4 is empty: {video_path}")
    return {"status": "ok", "message": "video file exists", "size_bytes": video_path.stat().st_size}


def _validate_metadata(package_dir: Path, platform: str) -> dict[str, Any]:
    package = _read_json(package_dir / "platform_publish_package.json")
    platforms = package.get("platforms") if isinstance(package, dict) else {}
    asset = platforms.get(platform) if isinstance(platforms, dict) else None
    if not isinstance(asset, dict):
        raise ValueError(f"Platform copy block not found: {platform}")
    copy_block = str(asset.get("copy_block") or "").strip()
    title = str(asset.get("title") or "").strip()
    description = str(asset.get("description") or "").strip()
    if not copy_block or not title or not description:
        raise ValueError(f"Platform metadata is incomplete: {platform}")
    return {
        "status": "ok",
        "message": "copy block, title and description are ready",
        "copy_block_chars": len(copy_block),
        "suitable": bool(asset.get("suitable")),
    }


def _step(attempt: dict[str, Any], name: str, result: dict[str, Any]) -> None:
    attempt["steps"].append({"name": name, **result})


def _append_attempt(package_dir: Path, attempt: dict[str, Any]) -> None:
    attempts = load_publish_attempts(package_dir)
    attempts.append(attempt)
    payload = {"schema_version": 1, "updated_at": _utc_now(), "attempts": attempts}
    (package_dir / ATTEMPTS_FILENAME).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _find_task(output_dir: Path, task_id: str) -> tuple[Path, dict[str, Any]]:
    for package_dir in sorted(path for path in output_dir.iterdir() if path.is_dir()):
        for task in load_publish_tasks(package_dir):
            if task.get("task_id") == task_id:
                return package_dir, task
    raise FileNotFoundError(f"Publish task not found: {task_id}")


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
