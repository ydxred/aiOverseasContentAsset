from __future__ import annotations

from app.source_manager import filter_sources, generate_discovery_links, load_sources, source_stats


def test_loads_sources_yaml() -> None:
    sources = load_sources()

    assert sources
    assert all(source["source_id"] for source in sources)


def test_pieter_levels_exists_as_creator() -> None:
    sources = load_sources()
    pieter = next(source for source in sources if source["source_id"] == "pieter_levels")

    assert pieter["source_type"] == "creator"
    assert "levelsio" in pieter["watch_keywords"]


def test_source_stats_are_non_zero() -> None:
    stats = source_stats(load_sources())

    assert stats["total_sources"] > 0
    assert stats["active_sources"] > 0
    assert stats["by_type"]["creator"] > 0
    assert stats["high_trust_sources"] > 0


def test_filters_by_type_category_and_status() -> None:
    sources = load_sources()
    creators = filter_sources(sources, source_type="creator", category="indie_business", status="active")

    assert any(source["source_id"] == "pieter_levels" for source in creators)


def test_discovery_links_for_creator_and_keyword() -> None:
    sources = load_sources()
    pieter = next(source for source in sources if source["source_id"] == "pieter_levels")
    keyword = next(source for source in sources if source["source_type"] == "keyword")

    creator_links = generate_discovery_links(pieter)
    keyword_links = generate_discovery_links(keyword)

    assert any(link["label"] == "x" for link in creator_links)
    assert any(link["label"] == "projects" for link in creator_links)
    assert {link["label"] for link in keyword_links} == {"GitHub", "YouTube", "Google"}
