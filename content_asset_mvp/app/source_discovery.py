from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode, urlparse
from urllib.request import Request, urlopen

from .config import load_settings
from .source_manager import generate_discovery_links, load_sources
from .source_scorer import score_candidates
from .github_auth import get_github_token

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_DISCOVERY_SOURCE_TYPES = {"creator", "youtube_channel", "keyword"}


def default_candidate_sources_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "candidate_sources.json"


def load_candidate_pool(path: Path | None = None) -> dict[str, Any]:
    candidate_path = path or default_candidate_sources_path()
    if not candidate_path.exists():
        return {"candidates": []}
    try:
        data = json.loads(candidate_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"candidates": []}
    if not isinstance(data, dict):
        return {"candidates": []}
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        data["candidates"] = []
    return data


def save_candidate_pool(pool: dict[str, Any], path: Path | None = None) -> None:
    candidate_path = path or default_candidate_sources_path()
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(json.dumps(pool, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def candidate_stats(candidates: list[dict[str, Any]] | None = None, path: Path | None = None) -> dict[str, Any]:
    candidate_list = candidates if candidates is not None else load_candidate_pool(path).get("candidates", [])
    decisions = Counter(str(item.get("decision", "unknown")) for item in candidate_list if isinstance(item, dict))
    statuses = Counter(str(item.get("status", "unknown")) for item in candidate_list if isinstance(item, dict))
    return {
        "total_candidates": len(candidate_list),
        "by_decision": dict(sorted(decisions.items())),
        "by_status": dict(sorted(statuses.items())),
    }


def discover_sources(
    *,
    mock: bool = False,
    limit: int | None = None,
    source_path: Path | None = None,
    candidate_path: Path | None = None,
) -> dict[str, Any]:
    seed_sources = load_sources(source_path)
    if mock:
        discovered = _mock_discovery(seed_sources)
        errors: list[dict[str, Any]] = []
    else:
        discovered, errors = _real_discovery(seed_sources, limit=limit)
    if limit is not None and limit > 0:
        discovered = discovered[:limit]
    scored = score_candidates(discovered)
    merge_result = merge_candidates(scored, candidate_path)
    stats = candidate_stats(merge_result["candidates"])
    return {
        "discovered_count": len(scored),
        "new_count": merge_result["new_count"],
        "updated_count": merge_result["updated_count"],
        "candidate_count": stats["total_candidates"],
        "by_decision": stats["by_decision"],
        "by_status": stats["by_status"],
        "errors": errors,
    }


def merge_candidates(candidates: list[dict[str, Any]], path: Path | None = None) -> dict[str, Any]:
    pool = load_candidate_pool(path)
    existing = [item for item in pool.get("candidates", []) if isinstance(item, dict)]
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in existing:
        key = _dedupe_key(item)
        if key not in by_key:
            order.append(key)
        by_key[key] = item

    new_count = 0
    updated_count = 0
    for candidate in candidates:
        key = _dedupe_key(candidate)
        if key in by_key:
            by_key[key] = {**by_key[key], **candidate, "status": by_key[key].get("status", candidate.get("status", "new"))}
            updated_count += 1
        else:
            order.append(key)
            by_key[key] = candidate
            new_count += 1

    pool["candidates"] = [by_key[key] for key in order]
    save_candidate_pool(pool, path)
    return {
        "candidates": pool["candidates"],
        "new_count": new_count,
        "updated_count": updated_count,
    }


def _mock_discovery(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source in sources:
        source_id = source.get("source_id")
        if source_id == "pieter_levels":
            candidates.extend(
                [
                    _candidate(source, "Photo AI", "https://photoai.com/", "creator_project", "Pieter product portfolio signal."),
                    _candidate(source, "Nomad List", "https://nomadlist.com/", "creator_project", "Known indie SaaS with paid community signals."),
                    _candidate(source, "Remote OK", "https://remoteok.com/", "creator_project", "Remote jobs product with durable revenue signal."),
                    _candidate(
                        source,
                        "levelsio GitHub",
                        "https://github.com/levelsio",
                        "github_repo",
                        "Creator GitHub profile can expose project repositories.",
                        signals={"stars": 1200, "forks": 120, "updated_at": _now_iso(), "keywords": ["indie", "project", "github"]},
                    ),
                ]
            )
        if source.get("source_type") in {"github_trending", "keyword"}:
            candidates.extend(_mock_github_keyword_candidates(source))
        if source.get("source_type") == "github_org":
            org = _github_org_from_source(source)
            if org:
                candidates.extend(
                    [
                        _candidate(
                            source,
                            f"{org}/agents-starter",
                            f"https://github.com/{org}/agents-starter",
                            "github_repo",
                            "Mock org repo discovered from recently updated GitHub repositories.",
                            signals={"stars": 2600, "forks": 320, "updated_at": _now_iso(), "keywords": ["AI agents", "developer tool"]},
                        ),
                        _candidate(
                            source,
                            f"{org}/automation-examples",
                            f"https://github.com/{org}/automation-examples",
                            "github_repo",
                            "Mock org repo discovered from automation examples.",
                            signals={"stars": 860, "forks": 90, "updated_at": _now_iso(), "keywords": ["automation", "workflow"]},
                        ),
                    ]
                )
        if _should_discover_youtube(source):
            candidates.extend(_mock_youtube_candidates(source))
        candidates.extend(_creator_link_candidates(source))
    return _dedupe_candidates(candidates)


def _real_discovery(sources: list[dict[str, Any]], *, limit: int | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    youtube_api_key = load_settings().youtube_api_key
    youtube_skip_recorded = False
    for source in sources:
        source_type = source.get("source_type")
        try:
            if _should_discover_youtube(source):
                if youtube_api_key:
                    candidates.extend(_discover_youtube_search(source, api_key=youtube_api_key, per_query=2))
                elif not youtube_skip_recorded:
                    errors.append(
                        {
                            "source_id": source.get("source_id"),
                            "error": "YouTube Data API key is not configured; skipping YouTube discovery.",
                            "status": "skipped",
                        }
                    )
                    youtube_skip_recorded = True
            if source_type == "github_org":
                candidates.extend(_discover_github_org(source))
            elif source_type in {"github_trending", "keyword"}:
                candidates.extend(_discover_github_search(source, per_query=3))
            elif source_type == "creator":
                candidates.extend(_creator_link_candidates(source))
        except DiscoveryError as exc:
            errors.append({"source_id": source.get("source_id"), "error": str(exc), "status": exc.status})
        if limit is not None and limit > 0 and len(candidates) >= limit:
            break
    return _dedupe_candidates(candidates), errors


def _discover_github_org(source: dict[str, Any]) -> list[dict[str, Any]]:
    org = _github_org_from_source(source)
    if not org:
        return []
    url = f"https://api.github.com/users/{quote_plus(org)}/repos?sort=updated&per_page=10"
    repos = _github_api_json(url)
    if not isinstance(repos, list):
        return []
    return [_candidate_from_repo(source, repo) for repo in repos if isinstance(repo, dict)]


def _discover_github_search(source: dict[str, Any], *, per_query: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    queries = source.get("watch_keywords") or [source.get("name", "")]
    for query in queries[:3]:
        if not query:
            continue
        url = f"https://api.github.com/search/repositories?q={quote_plus(str(query))}&sort=updated&order=desc&per_page={per_query}"
        data = _github_api_json(url)
        items = data.get("items", []) if isinstance(data, dict) else []
        candidates.extend(_candidate_from_repo(source, repo) for repo in items if isinstance(repo, dict))
    return candidates


def _discover_youtube_search(source: dict[str, Any], *, api_key: str, per_query: int) -> list[dict[str, Any]]:
    video_queries: dict[str, str] = {}
    for query in _youtube_queries_for_source(source)[:3]:
        params = {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": str(per_query),
            "order": "date",
            "relevanceLanguage": "en",
            "regionCode": "US",
            "safeSearch": "none",
            "key": api_key,
        }
        data = _youtube_api_json(YOUTUBE_SEARCH_URL, params)
        items = data.get("items", []) if isinstance(data, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            video_id = _get_nested_str(item, ("id", "videoId"))
            if video_id and video_id not in video_queries:
                video_queries[video_id] = query

    if not video_queries:
        return []

    params = {
        "part": "snippet,statistics",
        "id": ",".join(video_queries.keys()),
        "maxResults": str(len(video_queries)),
        "key": api_key,
    }
    data = _youtube_api_json(YOUTUBE_VIDEOS_URL, params)
    videos = data.get("items", []) if isinstance(data, dict) else []
    return [
        _candidate_from_youtube_video(source, video, query=video_queries.get(str(video.get("id")), "YouTube discovery"))
        for video in videos
        if isinstance(video, dict)
    ]


def _youtube_api_json(base_url: str, params: dict[str, str]) -> Any:
    request = Request(f"{base_url}?{urlencode(params)}", headers={"User-Agent": "content-asset-youtube-discovery"})
    try:
        with urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise DiscoveryError(f"YouTube Data API returned {exc.code}", status=exc.code) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DiscoveryError(f"YouTube discovery failed: {exc}") from exc


def _candidate_from_youtube_video(source: dict[str, Any], video: dict[str, Any], *, query: str) -> dict[str, Any]:
    snippet = video.get("snippet") if isinstance(video.get("snippet"), dict) else {}
    statistics = video.get("statistics") if isinstance(video.get("statistics"), dict) else {}
    video_id = str(video.get("id") or "")
    title = str(snippet.get("title") or "YouTube video").strip()
    description = str(snippet.get("description") or "")
    published_at = str(snippet.get("publishedAt") or "")
    channel_title = str(snippet.get("channelTitle") or "")
    channel_id = str(snippet.get("channelId") or "")
    url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
    return _candidate(
        source,
        title,
        url,
        "youtube_video",
        f"YouTube video discovered via Data API search for '{query}'.",
        signals={
            "platform": "youtube",
            "video_id": video_id,
            "channel_id": channel_id,
            "channel_title": channel_title,
            "published_at": published_at,
            "updated_at": published_at,
            "thumbnail": _youtube_thumbnail(snippet),
            "views": _as_int(statistics.get("viewCount")),
            "likes": _as_int(statistics.get("likeCount")),
            "comments": _as_int(statistics.get("commentCount")),
            "description": description[:500],
            "keywords": _youtube_signal_keywords(source, title, query),
        },
    )


def _github_api_json(url: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "content-asset-source-discovery",
    }
    token = get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise DiscoveryError(f"GitHub API returned {exc.code}", status=exc.code) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DiscoveryError(f"GitHub discovery failed: {exc}") from exc


def _candidate_from_repo(source: dict[str, Any], repo: dict[str, Any]) -> dict[str, Any]:
    name = str(repo.get("full_name") or repo.get("name") or "GitHub repository")
    description = str(repo.get("description") or "")
    return _candidate(
        source,
        name,
        str(repo.get("html_url") or ""),
        "github_repo",
        description or "Repository discovered from GitHub API.",
        signals={
            "stars": repo.get("stargazers_count", 0),
            "forks": repo.get("forks_count", 0),
            "updated_at": repo.get("updated_at", ""),
            "language": repo.get("language", ""),
            "description": description,
        },
    )


def _mock_github_keyword_candidates(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _candidate(
            source,
            "browser-use/browser-use",
            "https://github.com/browser-use/browser-use",
            "github_repo",
            "AI agent browser automation project suitable for Chinese explainer content.",
            signals={"stars": 8500, "forks": 900, "updated_at": _now_iso(), "keywords": ["AI agent", "automation", "github"]},
        ),
        _candidate(
            source,
            "All-Hands-AI/OpenHands",
            "https://github.com/All-Hands-AI/OpenHands",
            "github_repo",
            "Open-source coding agent project with strong developer-tool signal.",
            signals={"stars": 42000, "forks": 4800, "updated_at": _now_iso(), "keywords": ["AI coding assistant", "agent"]},
        ),
        _candidate(
            source,
            "n8n-io/n8n",
            "https://github.com/n8n-io/n8n",
            "github_repo",
            "Workflow automation project often used in AI automation businesses.",
            signals={"stars": 78000, "forks": 22000, "updated_at": _now_iso(), "keywords": ["automation", "workflow", "SaaS"]},
        ),
    ]


def _mock_youtube_candidates(source: dict[str, Any]) -> list[dict[str, Any]]:
    query = (_youtube_queries_for_source(source) or ["AI creator productivity workflow"])[0]
    return [
        _candidate(
            source,
            f"{query} - practical AI workflow demo",
            f"https://www.youtube.com/watch?v=mock_{_candidate_id(query)[-8:]}",
            "youtube_video",
            f"Mock YouTube video discovered from '{query}'.",
            signals={
                "mock": True,
                "platform": "youtube",
                "video_id": f"mock_{_candidate_id(query)[-8:]}",
                "channel_id": "mock_channel",
                "channel_title": "Mock Creator Lab",
                "published_at": _now_iso(),
                "updated_at": _now_iso(),
                "thumbnail": "https://i.ytimg.com/vi/mock/default.jpg",
                "views": 125000,
                "likes": 5200,
                "comments": 420,
                "description": "Mock English YouTube video for offline source discovery validation.",
                "keywords": _youtube_signal_keywords(source, "AI workflow demo", query),
            },
        )
    ]


def _creator_link_candidates(source: dict[str, Any]) -> list[dict[str, Any]]:
    if source.get("source_type") != "creator":
        return []
    candidates: list[dict[str, Any]] = []
    for link in generate_discovery_links(source):
        label = link.get("label", "")
        url = link.get("url", "")
        if label in {"x", "twitter"} or not url:
            continue
        candidates.append(
            _candidate(
                source,
                f"{source.get('name', 'Creator')} {label}",
                url,
                "creator_link",
                "Creator-owned link generated from seed source metadata.",
                signals={"label": label, "keywords": source.get("watch_keywords", [])},
            )
        )
    return candidates


def _should_discover_youtube(source: dict[str, Any]) -> bool:
    source_type = source.get("source_type")
    if source_type == "youtube_channel":
        return True
    if source_type == "keyword":
        return True
    urls = source.get("urls", {})
    return source_type == "creator" and isinstance(urls, dict) and bool(urls.get("youtube"))


def _youtube_queries_for_source(source: dict[str, Any]) -> list[str]:
    keywords = source.get("watch_keywords") or [source.get("name", "")]
    queries: list[str] = []
    for keyword in keywords:
        clean = _clean_youtube_query(str(keyword))
        if clean:
            queries.append(clean)
    if not queries and source.get("source_type") in YOUTUBE_DISCOVERY_SOURCE_TYPES:
        queries = [
            "AI coding workflow",
            "creator business AI tools",
            "productivity automation for founders",
        ]
    return _unique(queries)


def _clean_youtube_query(value: str) -> str:
    blocked_tokens = ("language:", "stars:", "forks:")
    parts = [part for part in value.replace(">", " ").replace("<", " ").split() if not part.lower().startswith(blocked_tokens)]
    clean = " ".join(parts).strip()
    if not clean:
        return ""
    topic_words = clean.lower()
    if not any(word in topic_words for word in ("ai", "coding", "creator", "business", "productivity", "saas", "startup", "automation")):
        clean = f"{clean} AI creator business"
    return clean


def _youtube_signal_keywords(source: dict[str, Any], title: str, query: str) -> list[str]:
    values = [query, title, "youtube", "AI", "coding", "creator", "business", "productivity"]
    values.extend(str(item) for item in source.get("watch_keywords", []) if item)
    return _unique(values)


def _youtube_thumbnail(snippet: dict[str, Any]) -> str:
    thumbnails = snippet.get("thumbnails")
    if not isinstance(thumbnails, dict):
        return ""
    for key in ("maxres", "standard", "high", "medium", "default"):
        item = thumbnails.get(key)
        if isinstance(item, dict) and item.get("url"):
            return str(item["url"])
    return ""


def _get_nested_str(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return str(current or "")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value).strip()
        key = clean.lower()
        if clean and key not in seen:
            result.append(clean)
            seen.add(key)
    return result


def _candidate(
    source: dict[str, Any],
    name: str,
    url: str,
    source_type: str,
    reason: str,
    *,
    signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = {
        "candidate_id": _candidate_id(url or name),
        "source_id": source.get("source_id", ""),
        "source_type": source_type,
        "name": name,
        "url": url,
        "category": source.get("category", "uncategorized"),
        "discovered_from": {
            "source_id": source.get("source_id", ""),
            "name": source.get("name", ""),
            "source_type": source.get("source_type", ""),
            "trust_score": source.get("trust_score", 0),
        },
        "discovery_method": "mock" if signals and signals.get("mock") else source.get("discovery_method", "source_discovery"),
        "reason": reason,
        "signals": signals or {},
        "score": 0,
        "decision": "review",
        "status": "new",
        "created_at": _now_iso(),
    }
    return candidate


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for candidate in candidates:
        key = _dedupe_key(candidate)
        if key not in by_key:
            order.append(key)
        by_key[key] = candidate
    return [by_key[key] for key in order]


def _dedupe_key(candidate: dict[str, Any]) -> str:
    url = str(candidate.get("url") or "").strip().lower().rstrip("/")
    if url:
        return f"url:{url}"
    return f"id:{candidate.get('candidate_id', '')}"


def _candidate_id(value: str) -> str:
    digest = hashlib.sha1(value.strip().lower().encode("utf-8")).hexdigest()[:12]
    slug = "".join(char if char.isalnum() else "_" for char in value.lower())[:48].strip("_")
    return f"cand_{slug}_{digest}" if slug else f"cand_{digest}"


def _github_org_from_source(source: dict[str, Any]) -> str:
    urls = source.get("urls", {})
    github_url = urls.get("github") if isinstance(urls, dict) else None
    if not github_url:
        github_url = source.get("url", "")
    parsed = urlparse(str(github_url))
    if parsed.netloc.lower() != "github.com":
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    return parts[0] if parts else ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DiscoveryError(RuntimeError):
    def __init__(self, message: str, *, status: int | str | None = None) -> None:
        super().__init__(message)
        self.status = status
