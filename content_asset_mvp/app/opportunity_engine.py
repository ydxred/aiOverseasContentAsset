from __future__ import annotations

from typing import Any

from .artifact_writer import ArtifactWriter
from .content_positioning import normalize_analysis_positioning


def evaluate_opportunity(content_id: str, analysis: dict[str, Any], score: dict[str, Any], writer: ArtifactWriter) -> dict[str, Any]:
    analysis = normalize_analysis_positioning(analysis)
    dimensions = score.get("opportunity_dimensions") or analysis.get("opportunity_dimensions") or {}
    result = {
        "content_id": content_id,
        "status": "skipped",
        "reason": "Full opportunity engine is reserved for future source monitoring and topic gap detection; this draft preserves the new content positioning signals.",
        "content_type": analysis.get("content_type"),
        "content_positioning": analysis.get("content_positioning"),
        "opportunity_score": score.get("total_score", 0),
        "opportunity_dimensions": dimensions,
        "why_now": analysis.get("why_now"),
        "problem_intensity": dimensions.get("problem_intensity"),
        "china_gap": analysis.get("china_gap"),
        "narrative_value": analysis.get("narrative_value"),
        "video_potential": dimensions.get("video_potential"),
        "business_insight": analysis.get("business_insight"),
        "audience_fit": dimensions.get("audience_fit"),
        "evidence_completeness": dimensions.get("evidence_completeness"),
        "risk_control": analysis.get("risk_control"),
        "decision": score.get("decision", "review"),
        "recommended_asset_types": analysis.get("content_formats", ["short_video_script"]),
        "review_required": True,
    }
    writer.write_json("opportunity_engine.json", result)
    return result

