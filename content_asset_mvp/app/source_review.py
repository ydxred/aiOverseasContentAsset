from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .source_discovery import load_candidate_pool, save_candidate_pool
from .source_manager import default_sources_path, load_source_config

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


FINAL_STATUSES = {"approved", "approved_existing", "rejected", "archived"}


def approve_candidate(
    candidate_id: str,
    *,
    candidate_path: Path | None = None,
    sources_path: Path | None = None,
) -> dict[str, Any]:
    candidate, pool = _find_candidate(candidate_id, candidate_path)
    source_config = load_source_config(sources_path)
    sources = source_config.get("sources")
    if not isinstance(sources, list):
        sources = []
        source_config["sources"] = sources

    source = candidate_to_source(candidate)
    duplicate = _find_duplicate_source(source, sources)
    now = _now_iso()

    if duplicate:
        candidate["status"] = "approved_existing"
        candidate["approved_at"] = now
        candidate["approved_source_id"] = duplicate.get("source_id", "")
        candidate["review_note"] = "Matched existing source by source_id or URL."
        save_candidate_pool(pool, candidate_path)
        return {
            "status": "approved_existing",
            "candidate_id": candidate_id,
            "source_id": duplicate.get("source_id", ""),
            "message": "Candidate already exists in sources.yaml; no new source was added.",
        }

    sources.append(source)
    _save_source_config(source_config, sources_path)
    candidate["status"] = "approved"
    candidate["approved_at"] = now
    candidate["approved_source_id"] = source["source_id"]
    save_candidate_pool(pool, candidate_path)
    return {
        "status": "approved",
        "candidate_id": candidate_id,
        "source_id": source["source_id"],
        "message": "Candidate approved and added to sources.yaml.",
    }


def reject_candidate(
    candidate_id: str,
    reason: str | None = None,
    *,
    candidate_path: Path | None = None,
) -> dict[str, Any]:
    candidate, pool = _find_candidate(candidate_id, candidate_path)
    _mark_candidate(candidate, "rejected", reason)
    save_candidate_pool(pool, candidate_path)
    return {"status": "rejected", "candidate_id": candidate_id, "message": "Candidate rejected."}


def archive_candidate(
    candidate_id: str,
    reason: str | None = None,
    *,
    candidate_path: Path | None = None,
) -> dict[str, Any]:
    candidate, pool = _find_candidate(candidate_id, candidate_path)
    _mark_candidate(candidate, "archived", reason)
    save_candidate_pool(pool, candidate_path)
    return {"status": "archived", "candidate_id": candidate_id, "message": "Candidate archived."}


def candidate_to_source(candidate: dict[str, Any]) -> dict[str, Any]:
    name = str(candidate.get("name") or candidate.get("candidate_id") or "Discovered Source").strip()
    url = str(candidate.get("url") or "").strip()
    score = _as_int(candidate.get("score"))
    source: dict[str, Any] = {
        "source_id": _source_id(name, url),
        "source_type": str(candidate.get("source_type") or "blog").strip(),
        "name": name,
        "category": str(candidate.get("category") or "uncategorized").strip(),
        "trust_score": _trust_score(score),
        "status": "active",
        "urls": _source_urls(url),
        "watch_keywords": _watch_keywords(candidate),
        "note": str(candidate.get("reason") or "Approved from source discovery candidate.").strip(),
        "priority": _priority(score),
        "discovery_method": _discovery_method(candidate),
    }
    if url:
        source["url"] = url
    return source


def _find_candidate(candidate_id: str, path: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    pool = load_candidate_pool(path)
    for candidate in pool.get("candidates", []):
        if isinstance(candidate, dict) and candidate.get("candidate_id") == candidate_id:
            return candidate, pool
    raise ValueError(f"Candidate not found: {candidate_id}")


def _mark_candidate(candidate: dict[str, Any], status: str, reason: str | None) -> None:
    candidate["status"] = status
    candidate[f"{status}_at"] = _now_iso()
    if reason:
        candidate["review_reason"] = reason


def _save_source_config(config: dict[str, Any], path: Path | None) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required to write sources.yaml")
    source_path = path or default_sources_path()
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _find_duplicate_source(source: dict[str, Any], sources: list[Any]) -> dict[str, Any] | None:
    source_id = str(source.get("source_id") or "")
    urls = _all_urls(source)
    for existing in sources:
        if not isinstance(existing, dict):
            continue
        if source_id and str(existing.get("source_id") or "") == source_id:
            return existing
        if urls & _all_urls(existing):
            return existing
    return None


def _all_urls(source: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    primary = _normalize_url(source.get("url"))
    if primary:
        urls.add(primary)
    raw_urls = source.get("urls")
    if isinstance(raw_urls, dict):
        urls.update(normalized for value in raw_urls.values() if (normalized := _normalize_url(value)))
    elif isinstance(raw_urls, list):
        urls.update(normalized for value in raw_urls if (normalized := _normalize_url(value)))
    return urls


def _source_urls(url: str) -> dict[str, str]:
    if not url:
        return {}
    if "github.com" in url.lower():
        return {"github": url}
    if "youtube.com" in url.lower() or "youtu.be" in url.lower():
        return {"youtube": url}
    return {"primary": url}


def _watch_keywords(candidate: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for value in (candidate.get("name"), candidate.get("source_id")):
        if value:
            values.append(str(value))
    signals = candidate.get("signals")
    if isinstance(signals, dict):
        keywords = signals.get("keywords")
        if isinstance(keywords, list):
            values.extend(str(item) for item in keywords if item)
    return _unique(values)


def _discovery_method(candidate: dict[str, Any]) -> str:
    method = str(candidate.get("discovery_method") or "source_discovery").strip()
    discovered_from = candidate.get("discovered_from")
    if isinstance(discovered_from, dict) and discovered_from.get("name"):
        return f"Approved candidate from {discovered_from['name']} via {method}."
    return f"Approved candidate via {method}."


def _source_id(name: str, url: str) -> str:
    seed = _normalize_url(url) or name.strip().lower()
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    slug = _slugify(name or seed)[:42].strip("_")
    return f"src_{slug}_{digest}" if slug else f"src_{digest}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return re.sub(r"_+", "_", slug)


def _normalize_url(value: Any) -> str:
    return str(value or "").strip().lower().rstrip("/")


def _trust_score(score: int) -> int:
    if score >= 80:
        return 8
    if score >= 65:
        return 7
    if score >= 45:
        return 6
    return 5


def _priority(score: int) -> int:
    if score <= 0:
        return 3
    return max(3, min(10, round(score / 10)))


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = value.strip()
        key = clean.lower()
        if clean and key not in seen:
            result.append(clean)
            seen.add(key)
    return result


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
