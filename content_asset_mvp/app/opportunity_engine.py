from __future__ import annotations

from typing import Any

from .artifact_writer import ArtifactWriter


def evaluate_opportunity(content_id: str, analysis: dict[str, Any], score: dict[str, Any], writer: ArtifactWriter) -> dict[str, Any]:
    result = {
        "content_id": content_id,
        "status": "skipped",
        "reason": "Full opportunity engine is reserved for future source monitoring and topic gap detection.",
        "opportunity_score": score.get("total_score", 0),
        "decision": score.get("decision", "review"),
        "recommended_asset_types": analysis.get("content_formats", ["short_video_script"]),
        "review_required": True,
    }
    writer.write_json("opportunity_engine.json", result)
    return result

