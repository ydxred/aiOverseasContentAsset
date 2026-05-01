from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

from .artifact_writer import ArtifactWriter
from .github_auth import get_github_token


README_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", re.IGNORECASE)


@dataclass(frozen=True)
class GitHubRepoRef:
    owner: str
    repo: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


def parse_github_repo_url(url: str) -> GitHubRepoRef:
    parsed = urlparse(url.strip())
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise ValueError("GitHub repo URL must use github.com")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("GitHub repo URL must include owner and repo")
    owner = parts[0].strip()
    repo = parts[1].removesuffix(".git").strip()
    if not owner or not repo or owner.startswith(".") or repo.startswith("."):
        raise ValueError("GitHub repo owner and repo are required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        raise ValueError("GitHub repo owner or repo contains unsupported characters")
    return GitHubRepoRef(owner=owner, repo=repo)


def make_github_content_id(url: str) -> str:
    ref = parse_github_repo_url(url)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{ref.owner}_{ref.repo}").strip("._-")
    if not safe:
        safe = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"gh_{safe}"[:96]


def collect_github_repository(url: str, writer: ArtifactWriter, *, mock: bool = False) -> dict[str, Any]:
    ref = parse_github_repo_url(url)
    if mock:
        return _write_mock_repository(ref, url, writer)

    errors: list[str] = []
    repo_data = _github_json(f"/repos/{ref.owner}/{ref.repo}", errors)
    topics_data = _github_json(f"/repos/{ref.owner}/{ref.repo}/topics", errors, accept="application/vnd.github+json")
    release_data = _github_json(f"/repos/{ref.owner}/{ref.repo}/releases/latest", errors, allow_404=True)
    readme_markdown, readme_status = _fetch_readme_markdown(ref, repo_data, errors)

    meta = _build_meta(ref, url, writer.output_dir.name, repo_data or {}, topics_data or {}, release_data, errors)
    meta["collection_status"] = "ready" if repo_data else "degraded"
    meta["readme_status"] = readme_status
    writer.write_json("github_meta.json", meta)
    writer.write_json("github_meta.json", meta, workspace=True)
    writer.write_json("meta.json", meta)
    writer.write_json("meta.json", meta, workspace=True)
    writer.write_markdown("readme.md", readme_markdown or "# README unavailable\n\nREADME 未能获取，请人工打开仓库确认。")
    writer.write_markdown("readme.md", readme_markdown or "# README unavailable\n\nREADME 未能获取，请人工打开仓库确认。", workspace=True)

    image_report = extract_and_download_readme_images(readme_markdown, ref, meta.get("default_branch") or "main", writer, mock=False)
    writer.write_json("readme_images.json", image_report)
    writer.write_json("readme_images.json", image_report, workspace=True)
    return meta


def extract_and_download_readme_images(
    readme_markdown: str,
    ref: GitHubRepoRef,
    default_branch: str,
    writer: ArtifactWriter,
    *,
    mock: bool = False,
) -> dict[str, Any]:
    image_urls = _extract_readme_image_urls(readme_markdown, ref, default_branch)
    images_dir = writer.workspace_path("images")
    images_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    for idx, image_url in enumerate(image_urls[:12], start=1):
        record: dict[str, Any] = {"source_url": image_url, "status": "pending"}
        if mock:
            suffix = Path(urlparse(image_url).path).suffix or ".txt"
            target = images_dir / f"readme_image_{idx:02d}{suffix}"
            target.write_text("mock image placeholder\n", encoding="utf-8")
            record.update({"status": "mocked", "workspace_path": str(target)})
            records.append(record)
            continue

        try:
            data, content_type = _request_bytes(image_url)
            ext = Path(urlparse(image_url).path).suffix
            if not ext:
                ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".img"
            target = images_dir / f"readme_image_{idx:02d}{ext}"
            target.write_bytes(data)
            record.update({"status": "downloaded", "workspace_path": str(target), "content_type": content_type, "bytes": len(data)})
        except Exception as exc:
            record.update({"status": "failed", "error": _friendly_network_error(exc)})
        records.append(record)

    return {
        "count": len(records),
        "workspace_images_dir": str(images_dir),
        "images": records,
    }


def _write_mock_repository(ref: GitHubRepoRef, url: str, writer: ArtifactWriter) -> dict[str, Any]:
    readme = (
        f"# {ref.repo}\n\n"
        "A mock GitHub AI project README used to validate the AI 项目解读 pipeline.\n\n"
        "![architecture](docs/architecture.png)\n\n"
        "## Highlights\n\n"
        "- Agent workflow for research and code generation\n"
        "- Clear demo path for Chinese technical explainers\n"
    )
    meta = {
        "content_id": writer.output_dir.name,
        "source_url": url,
        "source_type": "github_repo",
        "title": f"{ref.owner}/{ref.repo}",
        "author": ref.owner,
        "published_at": None,
        "duration": None,
        "language": "en",
        "description": "Mock GitHub AI project for pipeline validation.",
        "webpage_url": url,
        "html_url": url,
        "owner": ref.owner,
        "repo": ref.repo,
        "full_name": ref.full_name,
        "default_branch": "main",
        "topics": ["ai", "agents", "developer-tools"],
        "stars": 1234,
        "forks": 88,
        "watchers": 1234,
        "open_issues": 12,
        "latest_release": {"tag_name": "v0.1.0", "name": "Mock Release", "html_url": url + "/releases/tag/v0.1.0"},
        "collection_status": "mocked",
        "readme_status": "mocked",
        "api_errors": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    writer.write_json("github_meta.json", meta)
    writer.write_json("github_meta.json", meta, workspace=True)
    writer.write_json("meta.json", meta)
    writer.write_json("meta.json", meta, workspace=True)
    writer.write_markdown("readme.md", readme)
    writer.write_markdown("readme.md", readme, workspace=True)
    image_report = extract_and_download_readme_images(readme, ref, "main", writer, mock=True)
    writer.write_json("readme_images.json", image_report)
    writer.write_json("readme_images.json", image_report, workspace=True)
    return meta


def _build_meta(
    ref: GitHubRepoRef,
    url: str,
    content_id: str,
    repo_data: dict[str, Any],
    topics_data: dict[str, Any],
    release_data: dict[str, Any] | None,
    errors: list[str],
) -> dict[str, Any]:
    topics = topics_data.get("names") if isinstance(topics_data.get("names"), list) else repo_data.get("topics", [])
    return {
        "content_id": content_id,
        "source_url": url,
        "source_type": "github_repo",
        "title": repo_data.get("full_name") or ref.full_name,
        "author": (repo_data.get("owner") or {}).get("login") or ref.owner,
        "published_at": repo_data.get("created_at"),
        "duration": None,
        "language": repo_data.get("language"),
        "description": repo_data.get("description") or "",
        "webpage_url": repo_data.get("html_url") or url,
        "html_url": repo_data.get("html_url") or url,
        "owner": ref.owner,
        "repo": ref.repo,
        "full_name": repo_data.get("full_name") or ref.full_name,
        "default_branch": repo_data.get("default_branch") or "main",
        "topics": topics or [],
        "stars": repo_data.get("stargazers_count"),
        "forks": repo_data.get("forks_count"),
        "watchers": repo_data.get("watchers_count"),
        "open_issues": repo_data.get("open_issues_count"),
        "latest_release": _compact_release(release_data),
        "api_errors": errors,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _compact_release(release_data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not release_data:
        return None
    return {
        "tag_name": release_data.get("tag_name"),
        "name": release_data.get("name"),
        "published_at": release_data.get("published_at"),
        "html_url": release_data.get("html_url"),
    }


def _github_json(path: str, errors: list[str], *, accept: str = "application/vnd.github+json", allow_404: bool = False) -> dict[str, Any] | None:
    api_url = "https://api.github.com" + path
    headers = {"Accept": accept, "User-Agent": "content-asset-mvp"}
    token = get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        data, _content_type = _request_bytes(api_url, headers=headers)
        import json

        parsed = json.loads(data.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else None
    except HTTPError as exc:
        if allow_404 and exc.code == 404:
            return None
        errors.append(f"GitHub API {path} failed: HTTP {exc.code} {_rate_limit_hint(exc)}".strip())
    except Exception as exc:
        errors.append(f"GitHub API {path} failed: {_friendly_network_error(exc)}")
    return None


def _fetch_readme_markdown(ref: GitHubRepoRef, repo_data: dict[str, Any] | None, errors: list[str]) -> tuple[str, str]:
    readme_data = _github_json(f"/repos/{ref.owner}/{ref.repo}/readme", errors)
    if readme_data and readme_data.get("content"):
        try:
            raw = base64.b64decode(str(readme_data["content"]), validate=False)
            return raw.decode("utf-8", errors="replace"), "api"
        except Exception as exc:
            errors.append(f"GitHub README decode failed: {_friendly_network_error(exc)}")

    branch = (repo_data or {}).get("default_branch") or "main"
    for filename in ("README.md", "readme.md", "Readme.md"):
        raw_url = f"https://raw.githubusercontent.com/{quote(ref.owner)}/{quote(ref.repo)}/{quote(branch)}/{filename}"
        try:
            data, _content_type = _request_bytes(raw_url)
            return data.decode("utf-8", errors="replace"), "raw"
        except Exception:
            continue
    return "", "unavailable"


def _extract_readme_image_urls(readme_markdown: str, ref: GitHubRepoRef, default_branch: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in README_IMAGE_RE.finditer(readme_markdown or ""):
        raw_url = (match.group(1) or match.group(2) or "").strip()
        if not raw_url or raw_url.startswith("data:"):
            continue
        resolved = _resolve_readme_asset_url(raw_url, ref, default_branch)
        if resolved not in seen:
            seen.add(resolved)
            urls.append(resolved)
    return urls


def _resolve_readme_asset_url(raw_url: str, ref: GitHubRepoRef, default_branch: str) -> str:
    if raw_url.startswith(("http://", "https://")):
        return raw_url
    if raw_url.startswith("/"):
        return urljoin("https://github.com", raw_url)
    return f"https://raw.githubusercontent.com/{quote(ref.owner)}/{quote(ref.repo)}/{quote(default_branch)}/{raw_url.lstrip('./')}"


def _request_bytes(url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> tuple[bytes, str]:
    request_headers = {"User-Agent": "content-asset-mvp"}
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


def _friendly_network_error(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code} {_rate_limit_hint(exc)}".strip()
    if isinstance(exc, URLError):
        return str(exc.reason)
    return str(exc)


def _rate_limit_hint(exc: HTTPError) -> str:
    remaining = exc.headers.get("X-RateLimit-Remaining") if exc.headers else None
    reset = exc.headers.get("X-RateLimit-Reset") if exc.headers else None
    if remaining == "0":
        return f"GitHub rate limit reached; configure GITHUB_TOKEN or retry after reset={reset}"
    return ""
