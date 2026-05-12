from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.source_discovery import load_candidate_pool
from app.source_review import approve_candidate, archive_candidate, candidate_to_source, reject_candidate


def test_approve_candidate_writes_source_and_preserves_top_level_fields(tmp_path: Path) -> None:
    candidate_path = _write_candidates(tmp_path)
    sources_path = _write_sources(tmp_path)

    result = approve_candidate("cand_browser_use", candidate_path=candidate_path, sources_path=sources_path)

    data = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    assert result["status"] == "approved"
    assert data["search_queries"] == [{"query": "AI agent", "reason": "seed"}]
    assert len(data["sources"]) == 2
    added = data["sources"][1]
    assert added["source_id"].startswith("src_browser_use_browser_use_")
    assert added["urls"]["github"] == "https://github.com/browser-use/browser-use"
    assert added["status"] == "active"

    candidate = load_candidate_pool(candidate_path)["candidates"][0]
    assert candidate["status"] == "approved"
    assert candidate["approved_source_id"] == added["source_id"]


def test_duplicate_approve_does_not_append_source(tmp_path: Path) -> None:
    candidate_path = _write_candidates(tmp_path)
    sources_path = _write_sources(tmp_path)

    first = approve_candidate("cand_browser_use", candidate_path=candidate_path, sources_path=sources_path)
    second = approve_candidate("cand_browser_use", candidate_path=candidate_path, sources_path=sources_path)

    data = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    assert first["status"] == "approved"
    assert second["status"] == "approved_existing"
    assert len(data["sources"]) == 2
    assert load_candidate_pool(candidate_path)["candidates"][0]["status"] == "approved_existing"


def test_reject_and_archive_update_status_and_reason(tmp_path: Path) -> None:
    candidate_path = _write_candidates(tmp_path)

    reject_candidate("cand_browser_use", "too noisy", candidate_path=candidate_path)
    archive_candidate("cand_photo_ai", "already tracked elsewhere", candidate_path=candidate_path)

    by_id = {item["candidate_id"]: item for item in load_candidate_pool(candidate_path)["candidates"]}
    assert by_id["cand_browser_use"]["status"] == "rejected"
    assert by_id["cand_browser_use"]["review_reason"] == "too noisy"
    assert by_id["cand_photo_ai"]["status"] == "archived"
    assert by_id["cand_photo_ai"]["review_reason"] == "already tracked elsewhere"


def test_candidate_to_source_maps_expected_fields() -> None:
    source = candidate_to_source(_candidate("cand_browser_use"))

    assert source["source_id"].startswith("src_browser_use_browser_use_")
    assert source["source_type"] == "github_repo"
    assert source["name"] == "browser-use/browser-use"
    assert source["category"] == "ai_projects"
    assert source["trust_score"] == 8
    assert source["priority"] == 9
    assert source["watch_keywords"][:2] == ["browser-use/browser-use", "github_ai_project_keyword"]
    assert "Approved candidate from GitHub AI Project Discovery" in source["discovery_method"]


def test_candidate_to_source_maps_youtube_url() -> None:
    source = candidate_to_source(
        {
            **_candidate("cand_youtube", url="https://www.youtube.com/watch?v=abc123"),
            "source_type": "youtube_video",
            "name": "AI coding workflow for solo founders",
        }
    )

    assert source["source_type"] == "youtube_video"
    assert source["urls"]["youtube"] == "https://www.youtube.com/watch?v=abc123"


def _write_candidates(tmp_path: Path) -> Path:
    candidate_path = tmp_path / "candidate_sources.json"
    candidate_path.write_text(
        json.dumps({"candidates": [_candidate("cand_browser_use"), _candidate("cand_photo_ai", url="https://photoai.com/")]}, indent=2),
        encoding="utf-8",
    )
    return candidate_path


def _write_sources(tmp_path: Path) -> Path:
    sources_path = tmp_path / "sources.yaml"
    sources_path.write_text(
        """
search_queries:
  - query: AI agent
    reason: seed
sources:
  - source_id: pieter_levels
    source_type: creator
    name: Pieter Levels / levelsio
    category: indie_business
    trust_score: 10
    status: active
    urls:
      website: https://levels.io/
      projects: https://nomadlist.com/
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return sources_path


def _candidate(candidate_id: str, *, url: str = "https://github.com/browser-use/browser-use") -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "source_id": "github_ai_project_keyword",
        "source_type": "github_repo",
        "name": "browser-use/browser-use" if "github.com" in url else "Photo AI",
        "url": url,
        "category": "ai_projects",
        "discovered_from": {"name": "GitHub AI Project Discovery", "source_id": "github_ai_project_keyword"},
        "discovery_method": "source_discovery",
        "reason": "AI agent browser automation project suitable for Chinese explainer content.",
        "signals": {"stars": 8500, "keywords": ["AI agent", "automation"]},
        "score": 86,
        "decision": "approve_candidate",
        "status": "new",
    }
