from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .artifact_writer import ArtifactWriter
from .browser_agent import write_browser_agent_status


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
        return _write_status(repo_url, writer, status)

    if playwright_available is False:
        status.update({"status": "skipped", "reason": "Playwright is not installed."})
        return _write_status(repo_url, writer, status)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        status.update({"status": "skipped", "reason": "Playwright is not installed."})
        return _write_status(repo_url, writer, status)

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
    return _write_status(repo_url, writer, status)


def _write_status(repo_url: str, writer: ArtifactWriter, status: dict[str, Any]) -> dict[str, Any]:
    writer.write_json("snapshot_status.json", status)
    writer.write_json("snapshot_status.json", status, workspace=True)
    write_browser_agent_status(repo_url, writer, snapshot_status=status)
    return status


def _fetch_unavatar(handle: str, target: Path) -> bool:
    """Fetch a Twitter/X avatar via unavatar.io (open redirector to the
    actual profile picture). Returns True on success.

    Why this exists: X/Twitter has a strict login wall — Playwright
    landing on x.com/levelsio gets a near-blank "Sign in to continue"
    page, so the PortraitCard ends up with a white circle. unavatar.io
    is a free service that resolves the public profile image and
    redirects to the canonical pbs.twimg.com URL with no auth needed.
    """
    handle = handle.strip().lstrip("@")
    if not handle:
        return False
    try:
        from urllib.request import Request, urlopen
        req = Request(
            f"https://unavatar.io/twitter/{handle}?fallback=false",
            headers={"User-Agent": "Mozilla/5.0 (overseas-ai-asset)"},
        )
        with urlopen(req, timeout=10) as resp:
            data = resp.read()
        if not data or len(data) < 1024:
            return False  # likely an error page / redirect placeholder
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return True
    except Exception:
        return False


def _extract_x_handle(url: str) -> str:
    """Pull a bare handle out of an X / Twitter URL. Returns "" on failure."""
    if not url:
        return ""
    import re as _re
    m = _re.search(r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})(?:[/?#]|$)", url)
    return m.group(1) if m else ""


def snapshot_creator_profile(
    creator_urls: dict[str, str] | list[str] | str,
    writer: ArtifactWriter,
    *,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    """Capture viewport screenshots for creator-portrait sources.

    Walks a creator's canonical URLs (X profile / personal site / project
    homepages) and saves a viewport-sized screenshot for each — not
    full_page, because creator pages are usually long timelines / feeds
    and full_page produces 1440×8000 portraits that ScreenshotFrame can't
    fit. Each viewport shot lands as a separate asset with a role tag
    (``creator_avatar`` / ``creator_x_profile`` / ``creator_personal_site``
    / ``creator_project_landing``) so the dispatcher can route them to
    the right portrait template.

    ``creator_urls`` accepts:
      * dict (e.g. ``{"x": "https://x.com/levelsio", "website": "..."}``)
      * list of URLs (each gets a generic role)
      * a single URL string
    """
    status: dict[str, Any] = {
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "screenshots": [],
    }

    if isinstance(creator_urls, str):
        url_pairs = [("personal_site", creator_urls)]
    elif isinstance(creator_urls, dict):
        url_pairs = [(str(k), str(v)) for k, v in creator_urls.items() if v]
    elif isinstance(creator_urls, list):
        url_pairs = [("creator_url", str(u)) for u in creator_urls if u]
    else:
        url_pairs = []

    if skip_reason:
        status.update({"status": "skipped", "reason": skip_reason})
        return _write_status_creator(url_pairs, writer, status)
    if not url_pairs:
        status.update({"status": "skipped", "reason": "no creator urls"})
        return _write_status_creator(url_pairs, writer, status)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        status.update({"status": "skipped", "reason": "Playwright is not installed."})
        return _write_status_creator(url_pairs, writer, status)

    snapshots_dir = writer.workspace_path("snapshots")
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    role_map = {
        "x": "creator_x_profile",
        "twitter": "creator_x_profile",
        "website": "creator_personal_site",
        "projects": "creator_project_landing",
        "github": "creator_github",
        "blog": "creator_blog",
        "personal_site": "creator_personal_site",
        "creator_url": "creator_landing",
    }
    captured: list[dict[str, str]] = []

    # Step 1: try to grab a real avatar via unavatar.io for any X handle
    # we can extract. This produces the high-value asset (creator_avatar)
    # the PortraitCard absolutely needs and that Playwright cannot get
    # past X's login wall.
    avatar_path = snapshots_dir / "creator_avatar.png"
    avatar_handle = ""
    for kind, url in url_pairs:
        if kind in {"x", "twitter"}:
            avatar_handle = _extract_x_handle(url)
            if avatar_handle:
                break
    if avatar_handle and _fetch_unavatar(avatar_handle, avatar_path):
        captured.append({
            "label": f"@{avatar_handle}",
            "workspace_path": str(avatar_path),
            "role": "creator_avatar",
            "source_url": f"https://unavatar.io/twitter/{avatar_handle}",
        })

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            for kind, url in url_pairs[:5]:  # cap at 5 captures per creator
                role = role_map.get(kind, "creator_landing")
                slug = "".join(c if c.isalnum() else "_" for c in kind)[:20]
                screenshot_path = snapshots_dir / f"creator_{slug}.png"
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                    # viewport screenshot only — creator pages are tall feeds/grids
                    # and full_page would defeat ScreenshotFrame's 16:9 framing.
                    page.screenshot(path=str(screenshot_path), full_page=False)
                    page.close()
                    captured.append({
                        "label": kind,
                        "workspace_path": str(screenshot_path),
                        "role": role,
                        "source_url": url,
                    })
                except Exception as exc:  # one URL failure shouldn't kill the rest
                    captured.append({
                        "label": kind,
                        "workspace_path": "",
                        "role": role,
                        "source_url": url,
                        "error": str(exc)[-300:],
                    })
            browser.close()
        status.update({"status": "captured", "screenshots": captured})
    except Exception as exc:
        status.update({"status": "skipped", "reason": f"Playwright failed: {exc}", "screenshots": captured})
    return _write_status_creator(url_pairs, writer, status)


def _write_status_creator(
    url_pairs: list[tuple[str, str]],
    writer: ArtifactWriter,
    status: dict[str, Any],
) -> dict[str, Any]:
    status["urls"] = [{"kind": k, "url": u} for k, u in url_pairs]
    writer.write_json("snapshot_status.json", status)
    writer.write_json("snapshot_status.json", status, workspace=True)
    primary_url = url_pairs[0][1] if url_pairs else ""
    if primary_url:
        write_browser_agent_status(primary_url, writer, snapshot_status=status)
    return status
