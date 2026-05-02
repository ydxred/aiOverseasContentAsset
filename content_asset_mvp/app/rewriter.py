from __future__ import annotations

from typing import Any

from .artifact_writer import ArtifactWriter
from .db import Database
from .llm_client import LLMClient


def rewrite_script(
    meta: dict[str, Any],
    analysis: dict[str, Any],
    score: dict[str, Any],
    risk_report: dict[str, Any],
    writer: ArtifactWriter,
    llm: LLMClient,
    db: Database,
) -> dict[str, Any]:
    response = llm.generate("rewrite", {"meta": meta, "analysis": analysis, "score": score, "risk_report": risk_report})
    content = response.content
    if not isinstance(content, dict):
        raise RuntimeError("rewrite response must include script and titles")

    script = _normalize_script(content.get("script", ""), meta, analysis)
    titles = _normalize_titles(content.get("titles"), meta, analysis)
    script_path = writer.write_markdown("chinese_script.md", script)
    title_markdown = "# 标题候选\n\n" + "\n".join(f"{idx}. {title}" for idx, title in enumerate(titles, start=1))
    title_path = writer.write_markdown("title_options.md", title_markdown)
    db.record_model_run(writer.output_dir.name, "rewrite", response.provider, response.model, "succeeded")
    db.record_artifact(writer.output_dir.name, "chinese_script", str(script_path))
    db.record_artifact(writer.output_dir.name, "title_options", str(title_path))
    return {"script_path": str(script_path), "title_options_path": str(title_path), "titles": titles}


def _normalize_script(script: Any, meta: dict[str, Any], analysis: dict[str, Any]) -> str:
    required = ["# 标题", "# 口播稿", "## 为什么突然值得关注", "## 海外发生了什么", "## 它解决什么问题", "## 对中文用户/开发者/创作者/创业者的启发", "## 边界：不承诺收益、不夸大、不照搬"]
    if isinstance(script, dict):
        return _script_dict_to_markdown(script)

    script_text = str(script)
    if all(heading in script_text for heading in required) and not script_text.lstrip().startswith("{"):
        return script_text

    title = meta.get("title") or analysis.get("core_topic") or "海外内容解读"
    summary = script_text.strip() or str(analysis.get("summary", ""))
    points = analysis.get("main_points", [])
    risks = analysis.get("risk_points", [])
    facts = analysis.get("facts_to_check", [])
    why_now = analysis.get("why_now") or "这个选题最近值得关注，是因为它反映了海外 AI 工具、开源项目或商业机会的新变化。"
    china_gap = analysis.get("china_gap") or "中文用户需要的是背景、来源和适用边界，而不是照搬海外说法。"
    business_insight = analysis.get("business_insight") or "可以观察问题定义、产品位置和用户需求，但不能把观察讲成收益承诺。"
    point_lines = "\n".join(f"- {point}" for point in points) if points else "- 补充核心观点"
    risk_lines = "\n".join(f"- {risk}" for risk in risks) if risks else "- 暂无明显风险"
    fact_lines = "\n".join(f"- {fact}" for fact in facts) if facts else "- 暂无"
    return (
        f"# 标题\n\n{title}\n\n"
        "# 口播稿\n\n"
        "## 为什么突然值得关注\n\n"
        f"{why_now}\n\n"
        "## 海外发生了什么\n\n"
        f"{summary}\n\n"
        "## 它解决什么问题\n\n"
        f"{point_lines}\n\n"
        "## 对中文用户/开发者/创作者/创业者的启发\n\n"
        f"{china_gap}\n\n{business_insight}\n\n"
        "## 边界：不承诺收益、不夸大、不照搬\n\n"
        "这条内容只能作为海外 AI 工具和商业机会观察，发布前需要补充来源核查；不承诺收益，不夸大效果，也不照搬原内容路径。\n\n"
        "# 分镜建议\n\n"
        "1. 标题页：为什么这个海外 AI 选题突然值得关注\n"
        "2. 信息页：海外发生了什么，来源依据是什么\n"
        "3. 拆解页：它解决的问题、中文语境的启发和边界\n\n"
        "# 屏幕文字\n\n"
        f"{point_lines}\n\n"
        "# 风险点\n\n"
        f"{risk_lines}\n\n"
        "# 待核查内容\n\n"
        f"{fact_lines}"
    )


def _script_dict_to_markdown(script: dict[str, Any]) -> str:
    structured_voiceover = _structured_voiceover_from_dict(script)
    aliases = {
        "# 标题": ["# 标题", "标题", "title"],
        "# 口播稿": ["# 口播稿", "口播稿", "script", "正文"],
        "# 分镜建议": ["# 分镜建议", "分镜建议", "分镜", "shot_suggestions"],
        "# 屏幕文字": ["# 屏幕文字", "屏幕文字", "screen_text"],
        "# 风险点": ["# 风险点", "风险点", "risks", "边界", "boundary"],
        "# 待核查内容": ["# 待核查内容", "待核查内容", "facts_to_check"],
    }
    sections: list[str] = []
    for heading, keys in aliases.items():
        value: Any = ""
        for key in keys:
            if key in script:
                value = script[key]
                break
        if heading == "# 口播稿" and structured_voiceover:
            value = structured_voiceover
        if isinstance(value, list):
            body = "\n".join(f"- {item}" for item in value)
        else:
            body = str(value).strip()
        sections.append(f"{heading}\n\n{body or '待补充'}")
    return "\n\n".join(sections)


def _structured_voiceover_from_dict(script: dict[str, Any]) -> str:
    sections = [
        ("为什么突然值得关注", ["为什么突然值得关注", "why_now"]),
        ("海外发生了什么", ["海外发生了什么", "what_happened_overseas"]),
        ("它解决什么问题", ["它解决什么问题", "problem_solved"]),
        ("对中文用户/开发者/创作者/创业者的启发", ["对中文用户/开发者/创作者/创业者的启发", "启发", "insight"]),
        ("边界：不承诺收益、不夸大、不照搬", ["边界：不承诺收益、不夸大、不照搬", "边界", "boundary"]),
    ]
    bodies: list[str] = []
    for title, keys in sections:
        value: Any = ""
        for key in keys:
            if key in script:
                value = script[key]
                break
        if isinstance(value, list):
            body = "\n".join(f"- {item}" for item in value)
        else:
            body = str(value).strip()
        if body:
            bodies.append(f"## {title}\n\n{body}")
    return "\n\n".join(bodies)


def _normalize_titles(titles: Any, meta: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
    if isinstance(titles, list):
        normalized = [str(title).strip() for title in titles if str(title).strip()]
        if normalized:
            return normalized
    core = str(analysis.get("core_topic") or meta.get("title") or "海外内容").strip()
    return [
        f"{core} 为什么突然值得关注？",
        f"海外 AI 工具观察：{core}",
        f"{core}，中文用户应该怎么看？",
    ]

