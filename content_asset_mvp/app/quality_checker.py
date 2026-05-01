from __future__ import annotations

from typing import Any

from .artifact_writer import ArtifactWriter
from .db import Database
from .llm_client import LLMClient


def check_quality(
    meta: dict[str, Any],
    analysis: dict[str, Any],
    score: dict[str, Any],
    risk_report: dict[str, Any],
    writer: ArtifactWriter,
    llm: LLMClient,
    db: Database,
) -> dict[str, Any]:
    response = llm.generate("quality", {"meta": meta, "analysis": analysis, "score": score, "risk_report": risk_report})
    quality = response.content
    if not isinstance(quality, dict):
        raise RuntimeError("quality response must be JSON-compatible")

    writer.write_json("quality_check.json", quality)
    notes = [
        "# 人工审核记录",
        "",
        f"- content_id: {writer.output_dir.name}",
        f"- source_url: {meta.get('source_url', '')}",
        f"- title: {meta.get('title', '')}",
        f"- score: {score.get('total_score')}",
        f"- decision: {score.get('decision')}",
        f"- risk_level: {risk_report.get('risk_level')}",
        f"- quality_score: {quality.get('quality_score')}",
        f"- analysis_basis: {analysis.get('analysis_basis', 'unknown')}",
        f"- factual_confidence: {analysis.get('factual_confidence', 'unknown')}",
        "",
        "## 自动检查结论",
        "",
        f"- ready_for_human_review: {quality.get('ready_for_human_review')}",
        f"- issues: {', '.join(quality.get('issues', [])) if quality.get('issues') else 'None'}",
        f"- fix_suggestions: {', '.join(quality.get('fix_suggestions', [])) if quality.get('fix_suggestions') else 'None'}",
        "",
        "## 人工填写",
        "",
        "- 选题是否值得做：",
        "- 脚本是否可用：",
        "- 主要修改原因：",
        "- 风险判断是否准确：",
        "- 发布前必须补充：",
    ]
    path = writer.write_markdown("review_notes.md", "\n".join(notes))
    db.record_model_run(writer.output_dir.name, "quality", response.provider, response.model, "succeeded")
    db.record_artifact(writer.output_dir.name, "review_notes", str(path))
    return quality

