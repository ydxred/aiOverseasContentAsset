from __future__ import annotations

import ast
import json
import re
from typing import Any

from .artifact_writer import ArtifactWriter
from .db import Database
from .llm_client import LLMClient


def _coerce_dict_like(value: Any) -> Any:
    """Some LLM deployments return a Python ``dict`` stringified as a
    flat ``str`` (e.g. ``"{'## 为什么突然值得关注': '...'}"``). Downstream
    code branches only handle native ``dict``, so we try to rescue such
    strings back into a dict *once* here. The previous fix in this file
    only handled the ``isinstance(value, dict)`` branch — we repeatedly
    shipped a ``{'...': '...'}`` literal into ``chinese_script.md`` and
    eventually into burned subtitles. Attempting ``ast.literal_eval``
    first (safe, Python-only literals) and falling back to ``json.loads``
    catches both Python-style and JSON-style dict strings without ever
    executing code.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "{[":
        return value
    try:
        return ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        pass
    try:
        return json.loads(stripped)
    except (ValueError, TypeError):
        return value


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
    # 两套 voiceover heading family 都要识别 ——
    #   A) youtube/rewrite: 钩子 → 故事 → 做到 → 还能 → 感慨（叙事化）
    #   B) github/github_rewrite: 为什么值得关注 → 海外发生了什么 →
    #      它解决什么问题 → 对中文用户启发 → 边界（项目解读）
    # 之前只匹配 A，导致 GitHub 链路（task_type=github_rewrite）的合规
    # markdown 输出永远走 fallback，被塞进"## 海外发生了什么"的 summary
    # 占位符 → chinese_script.md 出现 # 标题 重复两次的灾难。
    voiceover_families = (
        ["## 钩子", "## 故事是怎么发生的", "## 它到底怎么做到的", "## 它还能干什么", "## 一点感慨"],
        [
            "## 为什么突然值得关注",
            "## 海外发生了什么",
            "## 它解决什么问题",
            "## 对中文用户/开发者/创作者/创业者的启发",
            "## 边界：不承诺收益、不夸大、不照搬",
        ],
    )
    # LLMs sometimes return the whole script as a dict-shaped string instead
    # of an actual dict — rescue it once at the entry point so every
    # downstream branch sees the real structure.
    script = _coerce_dict_like(script)
    if isinstance(script, dict):
        return _script_dict_to_markdown(script)

    script_text = str(script)
    starts_with_brace = script_text.lstrip().startswith("{")

    # 完整 markdown payload (有 # 标题 + # 口播稿 + 任一 family 的 5 段)
    # 直接返回；不带显式 # 标题 但有 # 口播稿 + 5 段也接受，把首个 # 标题
    # 起手补成"# 标题\n\n<llm 起的真正标题>"。
    for family in voiceover_families:
        if (
            "# 口播稿" in script_text
            and all(h in script_text for h in family)
            and not starts_with_brace
        ):
            if "# 标题" in script_text:
                return script_text
            first_heading_match = re.match(r"\s*#\s+(.+?)\s*\n", script_text)
            if first_heading_match and not first_heading_match.group(1).strip().startswith("标题"):
                llm_title = first_heading_match.group(1).strip()
                rest = script_text[first_heading_match.end():]
                return f"# 标题\n\n{llm_title}\n\n{rest.lstrip()}"
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
        # Rescue dict-shaped strings (e.g. "{'## ...': '...'}") back into
        # real dicts so the branches below don't str() them into the file.
        value = _coerce_dict_like(value)
        if isinstance(value, list):
            body = "\n".join(f"- {item}" for item in value)
        elif isinstance(value, dict):
            body = _nested_dict_to_markdown_body(value)
        else:
            body = str(value).strip()
        sections.append(f"{heading}\n\n{body or '待补充'}")
    return "\n\n".join(sections)


def _nested_dict_to_markdown_body(data: dict[str, Any]) -> str:
    # LLMs often emit voiceover/shot sections as a nested dict with Markdown
    # headings as keys ("## 为什么突然值得关注": "..."). Without this expansion
    # the outer dict would get str()'d into a one-line {'## ...': '...'} blob
    # that breaks both human review and any downstream voiceover extractor.
    parts: list[str] = []
    for raw_key, raw_value in data.items():
        key = str(raw_key).strip()
        if not key:
            continue
        heading = key if key.startswith("#") else f"## {key}"
        coerced = _coerce_dict_like(raw_value)
        if isinstance(coerced, list):
            body = "\n".join(f"- {item}" for item in coerced)
        elif isinstance(coerced, dict):
            body = _nested_dict_to_markdown_body(coerced)
        else:
            body = str(coerced).strip()
        parts.append(f"{heading}\n\n{body or '待补充'}")
    return "\n\n".join(parts)


def _voiceover_bucket(script: dict[str, Any]) -> dict[str, Any]:
    for key in ("# 口播稿", "口播稿", "script", "正文"):
        value = _coerce_dict_like(script.get(key))
        if isinstance(value, dict):
            return value
    return {}


def _structured_voiceover_from_dict(script: dict[str, Any]) -> str:
    # Some LLM responses keep the subsection headings at the top level, others
    # wrap them inside a "# 口播稿" dict. Merge both so we find them either way.
    search: dict[str, Any] = {**script, **_voiceover_bucket(script)}
    sections = [
        ("为什么突然值得关注", ["为什么突然值得关注", "why_now", "## 为什么突然值得关注"]),
        ("海外发生了什么", ["海外发生了什么", "what_happened_overseas", "## 海外发生了什么"]),
        ("它解决什么问题", ["它解决什么问题", "problem_solved", "## 它解决什么问题"]),
        (
            "对中文用户/开发者/创作者/创业者的启发",
            [
                "对中文用户/开发者/创作者/创业者的启发",
                "启发",
                "insight",
                "## 对中文用户/开发者/创作者/创业者的启发",
            ],
        ),
        (
            "边界：不承诺收益、不夸大、不照搬",
            [
                "边界：不承诺收益、不夸大、不照搬",
                "边界",
                "boundary",
                "## 边界：不承诺收益、不夸大、不照搬",
            ],
        ),
    ]
    bodies: list[str] = []
    for title, keys in sections:
        value: Any = ""
        for key in keys:
            if key in search:
                value = search[key]
                break
        value = _coerce_dict_like(value)
        if isinstance(value, list):
            body = "\n".join(f"- {item}" for item in value)
        elif isinstance(value, dict):
            body = _nested_dict_to_markdown_body(value)
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

