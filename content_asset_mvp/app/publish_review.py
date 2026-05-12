from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_writer import ArtifactWriter


PUBLISH_REVIEW_FILENAME = "publish_review.json"
PUBLISH_REVIEW_STATUSES = {"pending", "approved", "needs_revision", "rejected"}


def default_publish_review(content_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "content_id": content_id,
        "status": "pending",
        "review_note": "",
        "updated_at": None,
    }


def load_publish_review(package_dir: Path) -> dict[str, Any]:
    path = package_dir / PUBLISH_REVIEW_FILENAME
    if not path.exists():
        return default_publish_review(package_dir.name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default_publish_review(package_dir.name)
    if not isinstance(data, dict):
        return default_publish_review(package_dir.name)
    review = default_publish_review(package_dir.name)
    review.update(data)
    if review.get("status") not in PUBLISH_REVIEW_STATUSES:
        review["status"] = "pending"
    review["content_id"] = str(review.get("content_id") or package_dir.name)
    review["review_note"] = str(review.get("review_note") or "")
    return review


def ensure_publish_review(writer: ArtifactWriter) -> dict[str, Any]:
    if writer.exists(PUBLISH_REVIEW_FILENAME):
        return load_publish_review(writer.output_dir)
    review = default_publish_review(writer.output_dir.name)
    writer.write_json(PUBLISH_REVIEW_FILENAME, review)
    return review


def update_publish_review(package_dir: Path, status: str, note: str = "") -> dict[str, Any]:
    status = status.strip()
    if status not in PUBLISH_REVIEW_STATUSES - {"pending"}:
        raise ValueError("publish review status must be approved, needs_revision, or rejected")
    review = load_publish_review(package_dir)
    review.update(
        {
            "status": status,
            "review_note": note.strip(),
            "updated_at": _now(),
        }
    )
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / PUBLISH_REVIEW_FILENAME).write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return review


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
