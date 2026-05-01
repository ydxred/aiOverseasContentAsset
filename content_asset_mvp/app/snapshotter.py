from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .artifact_writer import ArtifactWriter


def snapshot_github_repo(
    repo_url: str,
    writer: ArtifactWriter,
    *,
    playwright_available: bool | None = None,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    status: dict[str, Any] = {
        "repo_url": repo_url,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "screenshots": [],
    }

    if skip_reason:
        status.update({"status": "skipped", "reason": skip_reason})
        return _write_status(writer, status)

    if playwright_available is False:
        status.update({"status": "skipped", "reason": "Playwright is not installed."})
        return _write_status(writer, status)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        status.update({"status": "skipped", "reason": "Playwright is not installed."})
        return _write_status(writer, status)

    snapshots_dir = writer.workspace_path("snapshots")
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = snapshots_dir / "github_repo_home.png"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            page.goto(repo_url, wait_until="networkidle", timeout=30_000)
            page.screenshot(path=str(screenshot_path), full_page=True)
            browser.close()
        status.update(
            {
                "status": "captured",
                "screenshots": [{"label": "repo_home", "workspace_path": str(screenshot_path)}],
            }
        )
    except Exception as exc:
        status.update({"status": "skipped", "reason": f"Playwright is installed but screenshot failed: {exc}"})
    return _write_status(writer, status)


def _write_status(writer: ArtifactWriter, status: dict[str, Any]) -> dict[str, Any]:
    writer.write_json("snapshot_status.json", status)
    writer.write_json("snapshot_status.json", status, workspace=True)
    return status
