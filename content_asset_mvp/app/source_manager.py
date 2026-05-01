from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


SOURCE_TYPES = {
    "creator",
    "youtube_channel",
    "youtube_video",
    "github_org",
    "github_trending",
    "product_hunt",
    "newsletter",
    "blog",
    "community",
    "keyword",
}


def default_sources_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "sources.yaml"


def load_source_config(path: Path | None = None) -> dict[str, Any]:
    source_path = path or default_sources_path()
    if yaml is None or not source_path.exists():
        return {"sources": [], "search_queries": []}
    data = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"sources": [], "search_queries": []}
    return data


def load_sources(path: Path | None = None) -> list[dict[str, Any]]:
    data = load_source_config(path)
    raw_sources = data.get("sources", [])
    if not isinstance(raw_sources, list):
        return []
    return [source for source in (_normalize_source(item) for item in raw_sources) if source]


def filter_sources(
    sources: Iterable[dict[str, Any]] | None = None,
    *,
    source_type: str | Iterable[str] | None = None,
    category: str | Iterable[str] | None = None,
    status: str | Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    source_list = list(sources) if sources is not None else load_sources()
    return [
        source
        for source in source_list
        if _matches(source.get("source_type"), source_type)
        and _matches(source.get("category"), category)
        and _matches(source.get("status"), status)
    ]


def source_stats(sources: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    source_list = list(sources) if sources is not None else load_sources()
    by_type = Counter(str(source.get("source_type", "unknown")) for source in source_list)
    return {
        "total_sources": len(source_list),
        "by_type": dict(sorted(by_type.items())),
        "high_trust_sources": sum(1 for source in source_list if _as_int(source.get("trust_score")) >= 8),
        "active_sources": sum(1 for source in source_list if source.get("status") == "active"),
    }


def group_sources_by_type(sources: Iterable[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_list = list(sources) if sources is not None else load_sources()
    for source in sorted(source_list, key=lambda item: (item.get("source_type", ""), -_as_int(item.get("priority")), item.get("name", ""))):
        grouped[str(source.get("source_type", "unknown"))].append(source)
    return dict(sorted(grouped.items()))


def generate_discovery_links(source: dict[str, Any]) -> list[dict[str, str]]:
    source_type = source.get("source_type")
    if source_type == "creator":
        return _creator_links(source)
    if source_type == "keyword":
        return _keyword_links(source)
    return _url_links(source)


def _normalize_source(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    source_id = str(item.get("source_id") or "").strip()
    name = str(item.get("name") or source_id or "Untitled").strip()
    source_type = str(item.get("source_type") or "keyword").strip()
    if source_type not in SOURCE_TYPES:
        source_type = "blog" if source_type in {"website", "site"} else source_type
    urls = _normalize_urls(item)
    watch_keywords = _normalize_list(item.get("watch_keywords"))
    normalized = {
        "source_id": source_id or _slugify(name),
        "source_type": source_type,
        "name": name,
        "category": str(item.get("category") or "uncategorized").strip(),
        "trust_score": _as_int(item.get("trust_score")),
        "status": str(item.get("status") or "active").strip(),
        "urls": urls,
        "watch_keywords": watch_keywords,
        "note": str(item.get("note") or "").strip(),
        "priority": _as_int(item.get("priority"), default=3),
        "discovery_method": str(item.get("discovery_method") or "").strip(),
    }
    if urls:
        normalized["url"] = next(iter(urls.values()))
    return normalized


def _normalize_urls(item: dict[str, Any]) -> dict[str, str]:
    urls = item.get("urls")
    if isinstance(urls, dict):
        return {str(key): str(value) for key, value in urls.items() if value}
    if isinstance(urls, list):
        return {f"url_{index + 1}": str(value) for index, value in enumerate(urls) if value}
    legacy_url = item.get("url")
    return {"primary": str(legacy_url)} if legacy_url else {}


def _normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _matches(value: Any, expected: str | Iterable[str] | None) -> bool:
    if expected is None:
        return True
    if isinstance(expected, str):
        expected_values = {expected}
    else:
        expected_values = {str(item) for item in expected}
    return str(value) in expected_values


def _creator_links(source: dict[str, Any]) -> list[dict[str, str]]:
    urls = source.get("urls", {})
    links: list[dict[str, str]] = []
    for key in ("x", "twitter", "website", "projects", "youtube", "newsletter"):
        url = urls.get(key)
        if url:
            links.append({"label": key, "url": url})
    for keyword in source.get("watch_keywords", []):
        links.append({"label": f"Google: {keyword}", "url": f"https://www.google.com/search?q={quote_plus(keyword)}"})
    return links


def _keyword_links(source: dict[str, Any]) -> list[dict[str, str]]:
    terms = source.get("watch_keywords") or [source.get("name", "")]
    query = " ".join(str(term) for term in terms if term).strip()
    if not query:
        return []
    return [
        {"label": "GitHub", "url": f"https://github.com/search?q={quote_plus(query)}&type=repositories&s=updated&o=desc"},
        {"label": "YouTube", "url": f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp=CAI%253D"},
        {"label": "Google", "url": f"https://www.google.com/search?q={quote_plus(query)}"},
    ]


def _url_links(source: dict[str, Any]) -> list[dict[str, str]]:
    urls = source.get("urls", {})
    return [{"label": str(label), "url": str(url)} for label, url in urls.items()]


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slugify(value: str) -> str:
    return "_".join(part for part in value.lower().replace("/", " ").replace("-", " ").split() if part)
