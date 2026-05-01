from __future__ import annotations

from typing import Any

from .artifact_writer import ArtifactWriter


def score_topic(analysis: dict[str, Any], writer: ArtifactWriter) -> dict[str, Any]:
    domestic = _score_value(analysis.get("domestic_value"), default=5)
    commercial = _score_value(analysis.get("commercial_value"), default=5)
    spread = _score_value(analysis.get("short_video_suitability"), default=6)
    practical = 7
    freshness = 7
    risk = 3 if analysis.get("risk_points") else 1
    total = round(domestic * 2.5 + commercial * 2.5 + spread * 2.0 + practical * 1.5 + freshness * 1.0 + (10 - risk) * 0.5)

    if total >= 85:
        decision = "process"
    elif total >= 70:
        decision = "review"
    elif total >= 50:
        decision = "archive"
    else:
        decision = "discard"

    score = {
        "total_score": total,
        "decision": decision,
        "reason": "Mock-aware weighted score based on domestic value, commercial value, spreadability, practicality, freshness, and risk.",
        "best_format": analysis.get("content_formats", ["short_video"]),
        "must_review": True,
        "dimensions": {
            "domestic_scarcity": domestic,
            "commercial_value": commercial,
            "spreadability": spread,
            "practicality": practical,
            "freshness": freshness,
            "risk_level": risk,
        },
    }
    writer.write_json("score.json", score)
    return score


def _score_value(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return 8 if value else 2
    if isinstance(value, (int, float)):
        return _clamp_score(round(float(value)))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            return _clamp_score(round(float(stripped)))
        except ValueError:
            # Real LLMs sometimes explain instead of scoring. Treat explanatory
            # non-empty values as medium signal instead of failing the pipeline.
            return default
    return default


def _clamp_score(value: int) -> int:
    return max(0, min(10, value))

