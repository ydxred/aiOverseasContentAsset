from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from .artifact_writer import ArtifactWriter


BROWSER_AGENT_TASKS: dict[str, str] = {
    "source_page_research": "Open the source page and summarize product positioning, proof points, audience fit, and risk boundaries for a Chinese explainer video.",
    "visual_evidence_hunt": "Open the source page and identify visually useful screenshots, demo pages, documentation diagrams, release notes, and proof points.",
    "web_console_smoke": "Open the local web console and verify that generated assets, video, cover, and artifact links are visible and usable.",
}
BROWSER_ASSET_VIEWPORT = {"width": 2560, "height": 1440}
BROWSER_ASSET_DEVICE_SCALE_FACTOR = 2


def build_browser_agent_status(
    *,
    source_url: str,
    snapshot_status: dict[str, Any] | None = None,
    browser_use_available: bool | None = None,
) -> dict[str, Any]:
    snapshot_status = snapshot_status or {}
    available = _browser_use_available() if browser_use_available is None else browser_use_available
    screenshots = snapshot_status.get("screenshots") if isinstance(snapshot_status.get("screenshots"), list) else []
    has_browser_use_llm = any(
        os.getenv(name)
        for name in (
            "BROWSER_USE_API_KEY",
            "DEEPSEEK_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
        )
    )
    blocking_reasons: list[str] = []
    if not available:
        blocking_reasons.append("browser-use package is not installed; Playwright screenshot capture remains the active browser layer.")
    if available and not has_browser_use_llm:
        blocking_reasons.append("browser-use is installed but no supported LLM/API key is configured.")
    provider, model = _browser_agent_provider_model()

    return {
        "schema_version": 1,
        "architecture_version": "browser_agent_v1",
        "source_url": source_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if available and has_browser_use_llm else "standby",
        "browser_use_available": available,
        "playwright_snapshot_status": snapshot_status.get("status", "unknown"),
        "screenshot_count": len(screenshots),
        "active_capture_layer": "playwright",
        "optional_agent_layer": "browser-use",
        "agent_llm_provider": provider,
        "agent_llm_model": model,
        "blocking_reasons": blocking_reasons,
        "recommended_tasks": [
            {
                "id": "source_page_research",
                "label": "Open the source page and summarize product positioning, proof points, and risks.",
                "risk": "read_only",
            },
            {
                "id": "visual_evidence_hunt",
                "label": "Find visually useful screenshots, demo pages, docs diagrams, and release evidence.",
                "risk": "read_only",
            },
            {
                "id": "web_console_smoke",
                "label": "Open the local web console and verify that generated assets are visible and playable.",
                "risk": "local_read_only",
            },
        ],
    }


def write_browser_agent_status(
    source_url: str,
    writer: ArtifactWriter,
    *,
    snapshot_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = build_browser_agent_status(source_url=source_url, snapshot_status=snapshot_status)
    writer.write_json("browser_agent_status.json", status)
    writer.write_json("browser_agent_status.json", status, workspace=True)
    return status


def run_browser_agent_report(
    *,
    source_url: str,
    writer: ArtifactWriter,
    task_id: str = "source_page_research",
    mock: bool = False,
    max_steps: int | None = None,
) -> dict[str, Any]:
    if task_id not in BROWSER_AGENT_TASKS:
        raise ValueError(f"Unsupported browser agent task: {task_id}")
    status = build_browser_agent_status(source_url=source_url)
    prompt = _task_prompt(source_url, task_id)
    report: dict[str, Any] = {
        "schema_version": 1,
        "architecture_version": "browser_agent_v1",
        "source_url": source_url,
        "task_id": task_id,
        "task_prompt": prompt,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "mock" if mock else "live",
        "status": "planned",
        "browser_agent_status": status,
        "findings": [],
        "recommended_next_actions": [],
    }
    if mock:
        _write_browser_agent_assets(writer, source_url=source_url, task_id=task_id, assets=[], status="mocked")
        report.update(
            {
                "status": "mocked",
                "findings": [
                    "Mock browser agent report generated without opening a browser.",
                    "Use this task as a read-only research step before improving visual evidence assets.",
                ],
                "recommended_next_actions": _recommended_next_actions(task_id),
            }
        )
        return _write_report(writer, report)
    if status["status"] != "ready":
        report.update(
            {
                "status": "standby",
                "blocking_reasons": status["blocking_reasons"],
                "recommended_next_actions": _recommended_next_actions(task_id),
            }
        )
        return _write_report(writer, report)

    asset_report = _capture_browser_agent_assets(source_url=source_url, writer=writer, task_id=task_id)
    if asset_report.get("assets"):
        report["browser_agent_assets_path"] = str(writer.output_path("browser_agent_assets.json"))
        report["browser_agent_asset_count"] = len(asset_report["assets"])

    try:
        result = asyncio.run(_run_browser_use_agent(prompt, max_steps=max_steps))
        report.update(
            {
                "status": "succeeded",
                "raw_result": result,
                "findings": _normalize_agent_result(result),
                "recommended_next_actions": _recommended_next_actions(task_id),
            }
        )
    except Exception as exc:
        fallback = _run_playwright_fallback(source_url=source_url, writer=writer, task_id=task_id, error=str(exc))
        report.update(fallback)
    return _write_report(writer, report)


async def _run_browser_use_agent(task_prompt: str, *, max_steps: int | None = None) -> str:
    from browser_use import Agent, Browser, ChatAnthropic, ChatBrowserUse, ChatGoogle, ChatOpenAI

    llm = _select_browser_use_llm(ChatBrowserUse, ChatOpenAI, ChatAnthropic, ChatGoogle)
    browser = Browser(
        headless=True,
        chromium_sandbox=False,
        enable_default_extensions=False,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    )
    agent = Agent(task=task_prompt, llm=llm, browser=browser)
    history = await agent.run(max_steps=max_steps or int(os.getenv("BROWSER_AGENT_MAX_STEPS") or "10"))
    result = str(history)
    if "invalid_request_error" in result or "success=False" in result:
        raise RuntimeError(result[-2000:])
    return result


def _select_browser_use_llm(
    chat_browser_use: type[Any],
    chat_openai: type[Any],
    chat_anthropic: type[Any],
    chat_google: type[Any],
) -> Any:
    provider = (os.getenv("BROWSER_AGENT_PROVIDER") or "").strip().lower()
    if provider == "deepseek" or (not provider and os.getenv("DEEPSEEK_API_KEY")):
        return chat_openai(
            model=os.getenv("BROWSER_AGENT_MODEL") or "deepseek-v4-pro",
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
            max_completion_tokens=int(os.getenv("BROWSER_AGENT_MAX_TOKENS") or "4096"),
            add_schema_to_system_prompt=True,
            dont_force_structured_output=True,
        )
    if os.getenv("BROWSER_USE_API_KEY"):
        return chat_browser_use()
    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("BROWSER_AGENT_PROVIDER=openai but OPENAI_API_KEY is not configured.")
    if os.getenv("OPENAI_API_KEY"):
        return chat_openai(model=os.getenv("BROWSER_AGENT_MODEL") or os.getenv("BROWSER_AGENT_OPENAI_MODEL") or "gpt-4.1-mini")
    if os.getenv("ANTHROPIC_API_KEY"):
        return chat_anthropic(model=os.getenv("BROWSER_AGENT_MODEL") or os.getenv("BROWSER_AGENT_ANTHROPIC_MODEL") or "claude-sonnet-4-0")
    if os.getenv("GOOGLE_API_KEY"):
        return chat_google(model=os.getenv("BROWSER_AGENT_MODEL") or os.getenv("BROWSER_AGENT_GOOGLE_MODEL") or "gemini-flash-latest")
    raise RuntimeError("No supported browser-use LLM/API key is configured.")


def _browser_agent_provider_model() -> tuple[str, str]:
    provider = (os.getenv("BROWSER_AGENT_PROVIDER") or "").strip().lower()
    if provider == "deepseek" or (not provider and os.getenv("DEEPSEEK_API_KEY")):
        return "deepseek", os.getenv("BROWSER_AGENT_MODEL") or "deepseek-v4-pro"
    if os.getenv("BROWSER_USE_API_KEY"):
        return "browser-use", os.getenv("BROWSER_AGENT_MODEL") or "default"
    if os.getenv("OPENAI_API_KEY"):
        return "openai", os.getenv("BROWSER_AGENT_MODEL") or os.getenv("BROWSER_AGENT_OPENAI_MODEL") or "gpt-4.1-mini"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic", os.getenv("BROWSER_AGENT_MODEL") or os.getenv("BROWSER_AGENT_ANTHROPIC_MODEL") or "claude-sonnet-4-0"
    if os.getenv("GOOGLE_API_KEY"):
        return "google", os.getenv("BROWSER_AGENT_MODEL") or os.getenv("BROWSER_AGENT_GOOGLE_MODEL") or "gemini-flash-latest"
    return "unconfigured", ""


def _task_prompt(source_url: str, task_id: str) -> str:
    return (
        f"{BROWSER_AGENT_TASKS[task_id]}\n"
        f"URL: {source_url}\n"
        "Constraints: read-only browsing only; do not log in, submit forms, purchase, publish, or modify remote data. "
        "Return concise Chinese notes with concrete evidence URLs or page sections when available."
    )


def _normalize_agent_result(result: str) -> list[str]:
    extracted_items = _extract_action_contents(result)
    if extracted_items:
        return extracted_items[:12]
    lines = [line.strip(" -\t") for line in result.splitlines() if line.strip()]
    return lines[:12] or [result[:1000]]


def _extract_action_contents(result: str) -> list[str]:
    contents: list[str] = []
    marker = "extracted_content='"
    start = 0
    while True:
        marker_index = result.find(marker, start)
        if marker_index < 0:
            break
        value_start = marker_index + len(marker)
        value_end = result.find("', include_extracted_content", value_start)
        if value_end < 0:
            start = value_start
            continue
        value = result[value_start:value_end].encode("utf-8", "ignore").decode("unicode_escape", "ignore").strip()
        if value and value not in contents:
            contents.append(value)
        start = value_end + 1
    final_text_marker = "Task completed: True - "
    final_index = result.rfind(final_text_marker)
    if final_index >= 0:
        final_text = result[final_index + len(final_text_marker) : final_index + len(final_text_marker) + 1200].strip()
        if final_text and final_text not in contents:
            contents.insert(0, final_text)
    return contents


def _recommended_next_actions(task_id: str) -> list[str]:
    if task_id == "visual_evidence_hunt":
        return ["Add the best evidence screenshots to the visual asset pack.", "Re-render the video after visual assets improve."]
    if task_id == "web_console_smoke":
        return ["Fix broken artifact links or missing media previews before publishing."]
    return ["Use findings to update github_analysis.json or the script angle before video rendering."]


def _run_playwright_fallback(*, source_url: str, writer: ArtifactWriter, task_id: str, error: str) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "status": "failed",
            "error": error[-2000:],
            "fallback_status": "playwright_unavailable",
            "recommended_next_actions": _recommended_next_actions(task_id),
        }

    screenshot_dir = writer.workspace_path("browser_agent")
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = screenshot_dir / f"{task_id}.png"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(
                viewport=BROWSER_ASSET_VIEWPORT,
                device_scale_factor=BROWSER_ASSET_DEVICE_SCALE_FACTOR,
            )
            page.goto(source_url, wait_until="domcontentloaded", timeout=20_000)
            title = page.title()
            body_text = page.locator("body").inner_text(timeout=5_000)
            page.screenshot(path=str(screenshot_path), full_page=True)
            browser.close()
        findings = _playwright_findings(task_id, title, body_text, screenshot_path)
        return {
            "status": "succeeded_with_playwright_fallback",
            "browser_use_error": error[-2000:],
            "fallback_status": "playwright_succeeded",
            "fallback_screenshot_path": str(screenshot_path),
            "findings": findings,
            "recommended_next_actions": _recommended_next_actions(task_id),
        }
    except Exception as fallback_exc:
        return {
            "status": "failed",
            "error": error[-1200:],
            "fallback_status": "playwright_failed",
            "fallback_error": str(fallback_exc)[-1200:],
            "recommended_next_actions": _recommended_next_actions(task_id),
        }


def _playwright_findings(task_id: str, title: str, body_text: str, screenshot_path: Path) -> list[str]:
    text = " ".join(body_text.split())
    findings = [
        f"Playwright fallback opened the page successfully. Title: {title or '-'}",
        f"Screenshot captured: {screenshot_path}",
    ]
    if task_id == "web_console_smoke":
        checks = {
            "has_output_package": "quality_smoke_browser_use" in body_text or "叙事资产审核包" in body_text,
            "has_video_or_artifacts": "final_video.mp4" in body_text or "Artifacts" in body_text,
            "has_browser_agent": "浏览器研究助手" in body_text or "browser_agent_report.json" in body_text,
        }
        findings.extend(f"{key}: {value}" for key, value in checks.items())
    if text:
        findings.append(f"Page text sample: {text[:500]}")
    return findings


def _capture_browser_agent_assets(*, source_url: str, writer: ArtifactWriter, task_id: str) -> dict[str, Any]:
    if task_id == "web_console_smoke":
        return _write_browser_agent_assets(writer, source_url=source_url, task_id=task_id, assets=[])
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _write_browser_agent_assets(
            writer,
            source_url=source_url,
            task_id=task_id,
            assets=[],
            status="skipped",
            reason="Playwright is not installed.",
        )

    assets_dir = writer.workspace_path("browser_agent_assets")
    assets_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(
                viewport=BROWSER_ASSET_VIEWPORT,
                device_scale_factor=BROWSER_ASSET_DEVICE_SCALE_FACTOR,
            )
            page.goto(source_url, wait_until="domcontentloaded", timeout=25_000)
            focused_assets = _capture_focused_source_assets(page, assets_dir=assets_dir, source_url=source_url, task_id=task_id)
            if focused_assets:
                browser.close()
                return _write_browser_agent_assets(writer, source_url=source_url, task_id=task_id, assets=focused_assets)
            candidates = _discover_visual_evidence_urls(page, source_url, task_id)
            assets: list[dict[str, Any]] = []
            for index, candidate in enumerate(candidates, start=1):
                try:
                    if page.url != candidate["url"]:
                        page.goto(candidate["url"], wait_until="domcontentloaded", timeout=20_000)
                    title = page.title()
                    screenshot_path = assets_dir / f"{task_id}_{index:02d}_{candidate['slug']}.png"
                    page.screenshot(path=str(screenshot_path), full_page=False)
                    assets.append(
                        {
                            "role": candidate["role"],
                            "label": title or candidate["label"],
                            "source_url": candidate["url"],
                            "workspace_path": str(screenshot_path),
                            "status": "captured",
                            "task_id": task_id,
                            "sequence": index,
                            "capture_width": BROWSER_ASSET_VIEWPORT["width"] * BROWSER_ASSET_DEVICE_SCALE_FACTOR,
                            "capture_height": BROWSER_ASSET_VIEWPORT["height"] * BROWSER_ASSET_DEVICE_SCALE_FACTOR,
                            "capture_mode": "viewport_2x",
                        }
                    )
                except Exception as asset_exc:
                    assets.append(
                        {
                            "role": candidate["role"],
                            "label": candidate["label"],
                            "source_url": candidate["url"],
                            "workspace_path": "",
                            "status": "failed",
                            "error": str(asset_exc)[-600:],
                            "task_id": task_id,
                            "sequence": index,
                        }
                    )
            browser.close()
        captured_assets = [asset for asset in assets if asset.get("workspace_path")]
        return _write_browser_agent_assets(writer, source_url=source_url, task_id=task_id, assets=captured_assets)
    except Exception as exc:
        return _write_browser_agent_assets(
            writer,
            source_url=source_url,
            task_id=task_id,
            assets=[],
            status="failed",
            reason=str(exc)[-1200:],
        )


def _capture_focused_source_assets(page: Any, *, assets_dir: Path, source_url: str, task_id: str) -> list[dict[str, Any]]:
    if task_id != "visual_evidence_hunt":
        return []

    base = source_url.rstrip("/")
    # Eight focused capture points — designed so the asset pack can support a
    # 3-minute video with one *unique* screenshot per ~22 seconds. The previous
    # 5-point plan left a codex-style repo at 1 unique screenshot for the whole
    # video, because README only had ASCII art and 4 of the 5 plan steps fell
    # back to "scroll repo overview, take same screenshot again". The new plan
    # spreads across distinct GitHub surfaces (Issues / Contributors / Pulse /
    # Commits) so even minimal-README repos get visual variety.
    plan = [
        {
            "role": "browser_focus_repo_overview",
            "label": "仓库首页核心信息",
            "slug": "repo_overview",
            "text": "",
            "url": source_url,
        },
        {
            "role": "browser_focus_demo_section",
            "label": "README Demo 展示区",
            "slug": "readme_demos",
            "text": "Demos",
            "url": source_url,
        },
        {
            "role": "browser_focus_quickstart",
            "label": "Quickstart 使用示例",
            "slug": "quickstart",
            "text": "Quickstart",
            "url": source_url,
        },
        {
            "role": "browser_focus_cli",
            "label": "CLI 命令示例",
            "slug": "cli",
            "text": "CLI",
            "url": source_url,
        },
        {
            "role": "browser_focus_releases",
            "label": "Release 版本证据",
            "slug": "releases",
            "text": "",
            "url": base + "/releases",
        },
        {
            "role": "browser_focus_issues",
            "label": "Issues 活跃度证据",
            "slug": "issues",
            "text": "",
            "url": base + "/issues",
        },
        {
            "role": "browser_focus_contributors",
            "label": "Contributors / 协作者列表",
            "slug": "contributors",
            "text": "",
            "url": base + "/graphs/contributors",
        },
        {
            "role": "browser_focus_commits",
            "label": "近期 commits 历史",
            "slug": "commits",
            "text": "",
            "url": base + "/commits",
        },
    ]
    assets: list[dict[str, Any]] = []
    for index, target in enumerate(plan, start=1):
        try:
            if page.url.rstrip("/") != target["url"].rstrip("/"):
                page.goto(target["url"], wait_until="domcontentloaded", timeout=20_000)
            if target["text"]:
                page.get_by_text(target["text"], exact=False).first.scroll_into_view_if_needed(timeout=7_000)
                page.mouse.wheel(0, -260)
                page.wait_for_timeout(350)
            else:
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(350)
            screenshot_path = assets_dir / f"{task_id}_{index:02d}_{target['slug']}.png"
            page.screenshot(path=str(screenshot_path), full_page=False)
            assets.append(
                {
                    "role": target["role"],
                    "label": target["label"],
                    "source_url": target["url"],
                    "workspace_path": str(screenshot_path),
                    "status": "captured",
                    "task_id": task_id,
                    "sequence": index,
                    "capture_width": BROWSER_ASSET_VIEWPORT["width"] * BROWSER_ASSET_DEVICE_SCALE_FACTOR,
                    "capture_height": BROWSER_ASSET_VIEWPORT["height"] * BROWSER_ASSET_DEVICE_SCALE_FACTOR,
                    "capture_mode": "focused_viewport_2x",
                }
            )
        except Exception as exc:
            assets.append(
                {
                    "role": target["role"],
                    "label": target["label"],
                    "source_url": target["url"],
                    "workspace_path": "",
                    "status": "failed",
                    "error": str(exc)[-600:],
                    "task_id": task_id,
                    "sequence": index,
                }
            )
    return [asset for asset in assets if asset.get("workspace_path")]


def _discover_visual_evidence_urls(page: Any, source_url: str, task_id: str) -> list[dict[str, str]]:
    candidates = [
        {
            "url": source_url,
            "role": "browser_source_screenshot",
            "label": "source page",
            "slug": "source",
        }
    ]
    if task_id != "visual_evidence_hunt":
        return candidates

    links = page.eval_on_selector_all(
        "a[href]",
        """elements => elements.map((element) => ({
            href: element.href,
            text: (element.innerText || element.getAttribute('aria-label') || '').trim()
        }))""",
    )
    seen = {source_url.rstrip("/")}
    for link in links:
        if not isinstance(link, dict):
            continue
        href = str(link.get("href") or "").strip()
        if not href:
            continue
        url = urljoin(source_url, href)
        normalized = url.rstrip("/")
        if normalized in seen or not _is_visual_evidence_url(url, source_url):
            continue
        role = _visual_evidence_role(url, str(link.get("text") or ""))
        candidates.append(
            {
                "url": url,
                "role": role,
                "label": str(link.get("text") or role).strip()[:120] or role,
                "slug": _safe_asset_slug(role),
            }
        )
        seen.add(normalized)
        if len(candidates) >= 5:
            break
    return candidates


def _is_visual_evidence_url(url: str, source_url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    lowered = url.lower()
    source_host = urlparse(source_url).netloc.lower()
    if parsed.netloc.lower() == source_host and any(token in lowered for token in ("/releases", "/blob/", "/tree/", "#readme")):
        return True
    return any(token in lowered for token in ("docs.", "/docs", "/examples", "demo", "release", "benchmark"))


def _visual_evidence_role(url: str, text: str) -> str:
    lowered = f"{url} {text}".lower()
    if "release" in lowered:
        return "browser_release_screenshot"
    if "example" in lowered or "demo" in lowered:
        return "browser_demo_screenshot"
    if "doc" in lowered:
        return "browser_docs_screenshot"
    if "benchmark" in lowered:
        return "browser_benchmark_screenshot"
    return "browser_evidence_screenshot"


def _safe_asset_slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)[:48] or "asset"


def _write_browser_agent_assets(
    writer: ArtifactWriter,
    *,
    source_url: str,
    task_id: str,
    assets: list[dict[str, Any]],
    status: str = "captured",
    reason: str = "",
) -> dict[str, Any]:
    report = {
        "schema_version": 1,
        "architecture_version": "browser_agent_v1",
        "source_url": source_url,
        "task_id": task_id,
        "status": status if assets or status != "captured" else "empty",
        "reason": reason,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "assets": assets,
    }
    writer.write_json("browser_agent_assets.json", report)
    writer.write_json("browser_agent_assets.json", report, workspace=True)
    return report


def _write_report(writer: ArtifactWriter, report: dict[str, Any]) -> dict[str, Any]:
    writer.write_json("browser_agent_report.json", report)
    writer.write_json("browser_agent_report.json", report, workspace=True)
    return report


def _browser_use_available() -> bool:
    return importlib.util.find_spec("browser_use") is not None
