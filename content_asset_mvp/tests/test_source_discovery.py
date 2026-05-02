from __future__ import annotations

import json
from pathlib import Path

import app.source_discovery as source_discovery
from app.source_discovery import discover_sources, load_candidate_pool, merge_candidates
from app.source_scorer import score_candidate


def test_mock_discovery_generates_candidates(tmp_path: Path) -> None:
    source_path = _write_sources(tmp_path)
    candidate_path = tmp_path / "candidate_sources.json"

    result = discover_sources(mock=True, source_path=source_path, candidate_path=candidate_path)

    assert result["discovered_count"] > 0
    assert result["candidate_count"] > 0
    pool = load_candidate_pool(candidate_path)
    names = {candidate["name"] for candidate in pool["candidates"]}
    assert "Photo AI" in names
    assert "browser-use/browser-use" in names


def test_candidate_dedupe_uses_url(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate_sources.json"
    candidate = {
        "candidate_id": "cand_one",
        "name": "Photo AI",
        "url": "https://photoai.com/",
        "score": 80,
        "decision": "approve_candidate",
        "status": "new",
    }

    first = merge_candidates([candidate], candidate_path)
    second = merge_candidates([{**candidate, "candidate_id": "cand_two", "score": 90}], candidate_path)

    assert first["new_count"] == 1
    assert second["new_count"] == 0
    assert second["updated_count"] == 1
    assert len(load_candidate_pool(candidate_path)["candidates"]) == 1


def test_scorer_rates_pieter_ai_github_candidate_high() -> None:
    scored = score_candidate(
        {
            "name": "levelsio AI agent GitHub project",
            "url": "https://github.com/levelsio/ai-project",
            "source_type": "github_repo",
            "category": "indie_business",
            "reason": "AI SaaS automation project from Pieter Levels.",
            "discovered_from": {"trust_score": 10},
            "signals": {"stars": 1500, "forks": 120, "updated_at": "2026-04-01T00:00:00Z"},
        }
    )

    assert scored["score"] >= 72
    assert scored["decision"] == "approve_candidate"


def test_candidate_sources_json_structure_is_written(tmp_path: Path) -> None:
    source_path = _write_sources(tmp_path)
    candidate_path = tmp_path / "candidate_sources.json"

    discover_sources(mock=True, limit=3, source_path=source_path, candidate_path=candidate_path)

    data = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert list(data.keys()) == ["candidates"]
    assert isinstance(data["candidates"], list)
    assert data["candidates"]
    required = {
        "candidate_id",
        "source_id",
        "source_type",
        "name",
        "url",
        "category",
        "discovered_from",
        "discovery_method",
        "reason",
        "signals",
        "score",
        "decision",
        "status",
        "created_at",
    }
    assert required.issubset(data["candidates"][0])


def test_mock_discovery_includes_youtube_candidates(tmp_path: Path) -> None:
    source_path = _write_youtube_sources(tmp_path)
    candidate_path = tmp_path / "candidate_sources.json"

    discover_sources(mock=True, source_path=source_path, candidate_path=candidate_path)

    pool = load_candidate_pool(candidate_path)
    assert any(candidate["source_type"] == "youtube_video" for candidate in pool["candidates"])


def test_mock_discovery_includes_non_youtube_github_candidates(tmp_path: Path) -> None:
    source_path = _write_web_sources(tmp_path)
    candidate_path = tmp_path / "candidate_sources.json"

    discover_sources(mock=True, source_path=source_path, candidate_path=candidate_path)

    pool = load_candidate_pool(candidate_path)
    source_types = {candidate["source_type"] for candidate in pool["candidates"]}
    assert {"product_launch", "community_thread", "newsletter_issue", "blog_article"}.issubset(source_types)
    assert any(candidate["decision"] in {"approve_candidate", "review"} for candidate in pool["candidates"] if candidate["source_type"] == "product_launch")


def test_real_hacker_news_discovery_writes_community_candidate(tmp_path: Path, monkeypatch) -> None:
    source_path = _write_hn_sources(tmp_path)
    candidate_path = tmp_path / "candidate_sources.json"

    def fake_http_json(url: str, *, user_agent: str) -> dict[str, object]:
        assert "hn.algolia.com" in url
        return {
            "hits": [
                {
                    "objectID": "123",
                    "title": "Show HN: AI agent workflow for developers",
                    "url": "https://example.com/agent-workflow",
                    "points": 220,
                    "num_comments": 80,
                    "author": "founder",
                    "created_at": "2026-05-01T00:00:00Z",
                }
            ]
        }

    monkeypatch.setattr(source_discovery, "_http_json", fake_http_json)

    result = discover_sources(mock=False, source_path=source_path, candidate_path=candidate_path)

    assert result["errors"] == []
    pool = load_candidate_pool(candidate_path)
    candidate = next(candidate for candidate in pool["candidates"] if candidate["source_type"] == "community_thread")
    assert candidate["signals"]["platform"] == "hacker_news"
    assert candidate["signals"]["points"] == 220
    assert candidate["decision"] == "approve_candidate"


def test_real_youtube_discovery_writes_video_candidate(tmp_path: Path, monkeypatch) -> None:
    source_path = _write_youtube_sources(tmp_path)
    candidate_path = tmp_path / "candidate_sources.json"

    class FakeSettings:
        youtube_api_key = "test-youtube-key"

    def fake_youtube_api_json(base_url: str, params: dict[str, str]) -> dict[str, object]:
        assert params["key"] == "test-youtube-key"
        if base_url == source_discovery.YOUTUBE_SEARCH_URL:
            return {"items": [{"id": {"videoId": "abc123"}}]}
        return {
            "items": [
                {
                    "id": "abc123",
                    "snippet": {
                        "title": "AI coding workflow for solo founders",
                        "description": "A practical English demo.",
                        "channelTitle": "Creator Lab",
                        "channelId": "channel_1",
                        "publishedAt": "2026-04-20T00:00:00Z",
                        "thumbnails": {"high": {"url": "https://img.youtube.com/abc123.jpg"}},
                    },
                    "statistics": {"viewCount": "120000", "likeCount": "4500", "commentCount": "600"},
                }
            ]
        }

    monkeypatch.setattr(source_discovery, "load_settings", lambda: FakeSettings())
    monkeypatch.setattr(source_discovery, "_youtube_api_json", fake_youtube_api_json)

    result = discover_sources(mock=False, source_path=source_path, candidate_path=candidate_path)

    assert result["errors"] == []
    pool = load_candidate_pool(candidate_path)
    candidate = next(candidate for candidate in pool["candidates"] if candidate["source_type"] == "youtube_video")
    assert candidate["url"] == "https://www.youtube.com/watch?v=abc123"
    assert candidate["signals"]["channel_title"] == "Creator Lab"
    assert candidate["signals"]["views"] == 120000
    assert candidate["decision"] in {"approve_candidate", "review"}


def test_real_youtube_discovery_without_key_records_skip(tmp_path: Path, monkeypatch) -> None:
    source_path = _write_youtube_sources(tmp_path)
    candidate_path = tmp_path / "candidate_sources.json"

    class FakeSettings:
        youtube_api_key = None

    monkeypatch.setattr(source_discovery, "load_settings", lambda: FakeSettings())

    result = discover_sources(mock=False, source_path=source_path, candidate_path=candidate_path)

    assert result["errors"][0]["status"] == "skipped"
    assert "YouTube Data API key is not configured" in result["errors"][0]["error"]


def _write_sources(tmp_path: Path) -> Path:
    source_path = tmp_path / "sources.yaml"
    source_path.write_text(
        """
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
      github: https://github.com/levelsio
    watch_keywords:
      - levelsio
      - Photo AI
      - Nomad List
      - Remote OK
    discovery_method: Track creator products.
  - source_id: github_ai_project_keyword
    source_type: keyword
    name: GitHub AI Project Discovery
    category: ai_projects
    trust_score: 7
    status: active
    urls: {}
    watch_keywords:
      - AI agent framework language:Python stars:>1000
    discovery_method: Generate GitHub search links.
""".strip(),
        encoding="utf-8",
    )
    return source_path


def _write_youtube_sources(tmp_path: Path) -> Path:
    source_path = tmp_path / "youtube_sources.yaml"
    source_path.write_text(
        """
sources:
  - source_id: fireship_youtube
    source_type: youtube_channel
    name: Fireship
    category: developer_trends
    trust_score: 8
    status: active
    urls:
      youtube: https://www.youtube.com/@Fireship
    watch_keywords:
      - AI coding
      - developer tools
      - productivity automation
    discovery_method: Track fast-moving developer videos.
""".strip(),
        encoding="utf-8",
    )
    return source_path


def _write_web_sources(tmp_path: Path) -> Path:
    source_path = tmp_path / "web_sources.yaml"
    source_path.write_text(
        """
sources:
  - source_id: product_hunt
    source_type: product_hunt
    name: Product Hunt
    category: new_tools
    trust_score: 7
    status: active
    urls:
      website: https://www.producthunt.com/
      ai: https://www.producthunt.com/categories/artificial-intelligence
    watch_keywords:
      - AI tools
      - launch
  - source_id: hacker_news
    source_type: community
    name: Hacker News
    category: tech_trends
    trust_score: 8
    status: active
    urls:
      website: https://news.ycombinator.com/
      newest: https://news.ycombinator.com/newest
    watch_keywords:
      - Show HN AI
  - source_id: latent_space
    source_type: newsletter
    name: Latent Space
    category: ai_engineering
    trust_score: 8
    status: active
    urls:
      newsletter: https://www.latent.space/
    watch_keywords:
      - AI engineering
  - source_id: yc_blog
    source_type: blog
    name: YC Blog
    category: startup
    trust_score: 9
    status: active
    urls:
      website: https://www.ycombinator.com/blog
    watch_keywords:
      - AI startup
""".strip(),
        encoding="utf-8",
    )
    return source_path


def _write_hn_sources(tmp_path: Path) -> Path:
    source_path = tmp_path / "hn_sources.yaml"
    source_path.write_text(
        """
sources:
  - source_id: hacker_news
    source_type: community
    name: Hacker News
    category: tech_trends
    trust_score: 8
    status: active
    urls:
      website: https://news.ycombinator.com/
    watch_keywords:
      - Show HN AI agent
    discovery_method: Watch Show HN and Launch HN threads.
""".strip(),
        encoding="utf-8",
    )
    return source_path
