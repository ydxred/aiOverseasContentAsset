from __future__ import annotations

from typing import Any

from .artifact_writer import ArtifactWriter
from .db import Database
from .llm_client import LLMClient
from .rewriter import _normalize_script, _normalize_titles


def analyze_github_project(
    meta: dict[str, Any],
    readme_markdown: str,
    readme_images: dict[str, Any],
    snapshot_status: dict[str, Any],
    writer: ArtifactWriter,
    llm: LLMClient,
    db: Database,
) -> dict[str, Any]:
    payload = {
        "github_meta": meta,
        "readme_markdown": _truncate(readme_markdown, 18_000),
        "readme_images": readme_images,
        "snapshot_status": snapshot_status,
    }
    response = llm.generate("github_analysis", payload)
    analysis = response.content
    if not isinstance(analysis, dict):
        raise RuntimeError("github_analysis response must be JSON-compatible")

    analysis_path = writer.write_json("github_analysis.json", analysis)
    db.record_model_run(writer.output_dir.name, "github_analysis", response.provider, response.model, "succeeded")
    db.record_artifact(writer.output_dir.name, "github_analysis", str(analysis_path))

    rewrite_response = llm.generate(
        "github_rewrite",
        {
            "github_meta": meta,
            "github_analysis": analysis,
            "readme_images": readme_images,
            "snapshot_status": snapshot_status,
        },
    )
    rewrite = rewrite_response.content
    if not isinstance(rewrite, dict):
        raise RuntimeError("github_rewrite response must include script and titles")

    script = _normalize_script(rewrite.get("script", ""), meta, analysis)
    titles = _normalize_titles(rewrite.get("titles"), meta, analysis)
    script_path = writer.write_markdown("chinese_script.md", script)
    title_markdown = "# 标题候选\n\n" + "\n".join(f"{idx}. {title}" for idx, title in enumerate(titles, start=1))
    title_path = writer.write_markdown("title_options.md", title_markdown)
    review_path = writer.write_markdown("review_notes.md", _review_notes(meta, analysis, snapshot_status))

    db.record_model_run(writer.output_dir.name, "github_rewrite", rewrite_response.provider, rewrite_response.model, "succeeded")
    db.record_artifact(writer.output_dir.name, "chinese_script", str(script_path))
    db.record_artifact(writer.output_dir.name, "title_options", str(title_path))
    db.record_artifact(writer.output_dir.name, "review_notes", str(review_path))
    return analysis


def _review_notes(meta: dict[str, Any], analysis: dict[str, Any], snapshot_status: dict[str, Any]) -> str:
    facts = analysis.get("facts_to_check") or []
    risks = analysis.get("risk_points") or []
    fact_lines = "\n".join(f"- {item}" for item in facts) if facts else "- README、star、release 信息发布前再人工复核一次"
    risk_lines = "\n".join(f"- {item}" for item in risks) if risks else "- 暂无明显风险"
    return "\n".join(
        [
            "# GitHub 项目解读审核记录",
            "",
            f"- content_id: {meta.get('content_id', '')}",
            f"- repo: {meta.get('full_name', meta.get('title', ''))}",
            f"- source_url: {meta.get('source_url', '')}",
            f"- stars: {meta.get('stars', '-')}",
            f"- forks: {meta.get('forks', '-')}",
            f"- snapshot_status: {snapshot_status.get('status', '-')}",
            "",
            "## 自动分析结论",
            "",
            f"- core_topic: {analysis.get('core_topic', '')}",
            f"- audience_value: {analysis.get('audience_value', '')}",
            "",
            "## 风险点",
            "",
            risk_lines,
            "",
            "## 待核查内容",
            "",
            fact_lines,
            "",
            "## 人工填写",
            "",
            "- 项目是否值得做成中文解读：",
            "- 技术描述是否准确：",
            "- 是否需要补充同类项目对比：",
            "- 发布前必须补充：",
        ]
    )


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[README truncated for LLM input]"
