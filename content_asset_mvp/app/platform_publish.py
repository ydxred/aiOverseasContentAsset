from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLATFORMS = {
    "douyin": {
        "platform_name": "抖音",
        "content_fit": "强钩子、强反差、项目故事",
        "video_length": "30-90 秒",
        "key_metrics": ["完播", "互动", "转粉"],
        "focus": "开头 3 秒",
        "style": "强钩子，强反差，突出项目故事和开头 3 秒。",
        "tag_seed": ["AI工具", "效率工具", "自动化", "科技趋势"],
        "notes": ["标题和封面要突出一个明确钩子。", "开头 3 秒必须讲清反差或收益点。", "避免夸大收益、免费额度或工具效果。"],
    },
    "kuaishou": {
        "platform_name": "快手",
        "content_fit": "接地气、赚钱案例、实操感",
        "video_length": "30-120 秒",
        "key_metrics": ["完播", "评论", "信任感"],
        "focus": "话说人话",
        "style": "口语化，接地气，像给朋友解释，多讲实操感。",
        "tag_seed": ["实用工具", "AI自动化", "普通人学AI", "经验分享"],
        "notes": ["简介建议保留口语感，少堆概念。", "话说人话，避免过多英文术语。", "首评可以引导观众补充使用体验。"],
    },
    "wechat_channels": {
        "platform_name": "微信视频号",
        "content_fit": "泛人群、转发价值、商业认知",
        "video_length": "1-3 分钟",
        "key_metrics": ["转发", "点赞", "完播"],
        "focus": "稳重、有观点",
        "style": "克制可信，强调观点、来源、核查和适用边界。",
        "tag_seed": ["AI观察", "工具评测", "效率提升", "科技解读"],
        "notes": ["表达要克制，避免标题党。", "观点要稳，适合被转发给泛人群。", "建议在简介中保留来源和核查提醒。"],
    },
    "bilibili": {
        "platform_name": "B站",
        "content_fit": "深度拆解、教程、复盘",
        "video_length": "3-8 分钟",
        "key_metrics": ["收藏", "投币", "评论", "完播"],
        "focus": "信息密度",
        "style": "信息完整，强调信息密度，交代来源、背景和待核查点。",
        "tag_seed": ["AI", "开源项目", "工具测评", "技术观察"],
        "notes": ["简介可以更完整，说明资料来源与核查限制。", "适合补充参考链接、版本信息或来源截图。", "如果内容不足 3 分钟，建议作为短拆解或合集素材。"],
    },
    "xiaohongshu": {
        "platform_name": "小红书",
        "content_fit": "工具清单、项目笔记、方法论",
        "video_length": "30-90 秒/图文",
        "key_metrics": ["收藏", "搜索", "私信"],
        "focus": "标题和封面",
        "style": "笔记感，标题和封面清楚，强调工具清单、项目笔记或方法论沉淀。",
        "tag_seed": ["AI工具", "工具清单", "效率方法", "项目笔记"],
        "notes": ["标题和封面要像可收藏的笔记。", "适合补充步骤、清单或方法论。", "避免过度营销，保留真实使用限制。"],
    },
}

REQUIRED_INPUTS = [
    "meta.json",
    "analysis.json",
    "github_analysis.json",
    "chinese_script.md",
    "risk_report.json",
    "quality_check.json",
    "publish_review.json",
    "render_status.json",
]

LOW_CONFIDENCE_HINTS = ("low", "低", "metadata_only", "元数据", "缺乏转录")


def generate_platform_publish_package(content_id: str, package_dir: Path) -> dict[str, Any]:
    meta = _read_json(package_dir / "meta.json")
    analysis = _read_json(package_dir / "analysis.json") or _read_json(package_dir / "github_analysis.json")
    risk_report = _read_json(package_dir / "risk_report.json")
    quality_check = _read_json(package_dir / "quality_check.json")
    publish_review = _read_json(package_dir / "publish_review.json")
    render_status = _read_json(package_dir / "render_status.json")
    script_text = _read_text(package_dir / "chinese_script.md")

    context = _build_context(content_id, meta, analysis, risk_report, quality_check, publish_review, render_status, script_text)
    platforms = {platform: _build_platform_asset(platform, context) for platform in PLATFORMS}
    package = {
        "schema_version": 1,
        "content_id": content_id,
        "generated_at": _utc_now(),
        "source_type": meta.get("source_type", ""),
        "source_url": meta.get("source_url") or meta.get("webpage_url") or meta.get("html_url") or "",
        "publish_review_status": publish_review.get("status", "pending"),
        "factual_confidence": analysis.get("factual_confidence", "unknown"),
        "inputs": {filename: (package_dir / filename).exists() for filename in REQUIRED_INPUTS},
        "platforms": platforms,
    }

    (package_dir / "platform_publish_package.json").write_text(
        json.dumps(package, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (package_dir / "platform_publish_package.md").write_text(_render_markdown(package), encoding="utf-8")
    return package


def generate_platform_publish_packages_all(output_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not output_dir.exists():
        return results
    for package_dir in sorted(path for path in output_dir.iterdir() if path.is_dir()):
        if not (package_dir / "final_video.mp4").exists():
            continue
        results.append(generate_platform_publish_package(package_dir.name, package_dir))
    return results


def _build_context(
    content_id: str,
    meta: dict[str, Any],
    analysis: dict[str, Any],
    risk_report: dict[str, Any],
    quality_check: dict[str, Any],
    publish_review: dict[str, Any],
    render_status: dict[str, Any],
    script_text: str,
) -> dict[str, Any]:
    script_title = _extract_section(script_text, "标题").splitlines()[0:1]
    title = _clean_text(script_title[0]) if script_title else ""
    title = title or _clean_text(str(meta.get("title") or analysis.get("core_topic") or content_id))
    voiceover = _extract_section(script_text, "口播稿")
    summary = _clean_text(str(analysis.get("summary") or ""))
    main_points = _as_text_list(analysis.get("main_points"))
    risks = _collect_risks(analysis, risk_report, quality_check, publish_review)
    needs_manual_check = _needs_manual_check(analysis, publish_review)
    source_name = str(meta.get("author") or meta.get("channel_title") or meta.get("full_name") or "")
    source_url = str(meta.get("source_url") or meta.get("webpage_url") or meta.get("html_url") or "")
    return {
        "content_id": content_id,
        "title": title,
        "voiceover": voiceover,
        "summary": summary,
        "main_points": main_points,
        "risks": risks,
        "needs_manual_check": needs_manual_check,
        "review_status": str(publish_review.get("status") or "pending"),
        "factual_confidence": str(analysis.get("factual_confidence") or "unknown"),
        "source_type": str(meta.get("source_type") or ""),
        "source_name": source_name.strip(),
        "source_url": source_url,
        "render_status": str(render_status.get("status") or "unknown"),
        "risk_pass": risk_report.get("pass"),
        "quality_pass": quality_check.get("pass"),
        "topic": _clean_text(str(analysis.get("core_topic") or title)),
    }


def _build_platform_asset(platform: str, context: dict[str, Any]) -> dict[str, Any]:
    config = PLATFORMS[platform]
    title = _platform_title(platform, context)
    description = _platform_description(platform, context)
    hashtags = _platform_hashtags(platform, context)
    cover_text = _platform_cover_text(platform, context)
    pinned_comment = _platform_pinned_comment(platform, context)
    publish_notes = list(config["notes"]) + _common_publish_notes(context)
    manual_review_risks = _manual_review_risks(context)
    suitable = _platform_suitable(platform, context)
    suitability_reason = _suitability_reason(platform, context, suitable)
    copy_block = _copy_block(title, description, hashtags, pinned_comment)
    return {
        "platform_name": config["platform_name"],
        "content_fit": config["content_fit"],
        "video_length": config["video_length"],
        "key_metrics": config["key_metrics"],
        "focus": config["focus"],
        "suitable": suitable,
        "suitability_reason": suitability_reason,
        "title": title,
        "description": description,
        "hashtags": hashtags,
        "cover_text": cover_text,
        "pinned_comment": pinned_comment,
        "publish_notes": publish_notes,
        "manual_review_risks": manual_review_risks,
        "copy_block": copy_block,
    }


def _platform_title(platform: str, context: dict[str, Any]) -> str:
    title = _trim(context["title"], 44)
    topic = _trim(context["topic"], 28)
    if platform == "douyin":
        return _trim(f"别只看热闹，{topic}真正要核查的是这点", 38)
    if platform == "kuaishou":
        return _trim(f"{topic}，普通人先看懂这几个点", 42)
    if platform == "wechat_channels":
        return _trim(f"{topic}：一次克制的中文解读", 44)
    if platform == "bilibili":
        return _trim(f"{title}｜来源、看点和发布前核查提醒", 72)
    if platform == "xiaohongshu":
        return _trim(f"{topic}｜值得收藏的工具笔记", 36)
    return title


def _platform_description(platform: str, context: dict[str, Any]) -> str:
    summary = context["summary"] or _first_sentence(context["voiceover"]) or context["topic"]
    points = "；".join(context["main_points"][:3])
    source = _source_line(context)
    manual = "发布前必须人工核查：事实依据、来源上下文和版权边界。" if context["needs_manual_check"] else "已生成发布草稿，仍建议发布前做最终人工复核。"
    if platform == "douyin":
        return _trim(f"{summary}\n\n关键不是跟风发布，而是先看清它到底解决什么问题。{manual}", 260)
    if platform == "kuaishou":
        return _trim(f"{summary}\n\n我把重点整理成几个好懂的点：{points or context['topic']}。{manual}", 280)
    if platform == "wechat_channels":
        return _trim(f"{summary}\n\n{source}\n本条为中文解读草稿，不承诺自动发布或工具效果。{manual}", 320)
    if platform == "bilibili":
        return _trim(
            f"{summary}\n\n主要看点：{points or context['topic']}。\n{source}\n核查提醒：{manual}\n欢迎在评论区补充一手使用经验或来源修正。",
            700,
        )
    if platform == "xiaohongshu":
        return _trim(
            f"{summary}\n\n笔记重点：{points or context['topic']}。\n适合先收藏，再对照来源和自己的场景判断是否值得试用。{manual}",
            320,
        )
    return summary


def _platform_hashtags(platform: str, context: dict[str, Any]) -> list[str]:
    tags = list(PLATFORMS[platform]["tag_seed"])
    topic = re.sub(r"[^\w\u4e00-\u9fff]+", "", context["topic"])
    if topic:
        tags.insert(0, _trim(topic, 12))
    if context["source_type"] == "github_repo":
        tags.append("GitHub")
    return list(dict.fromkeys(tag for tag in tags if tag))[:6]


def _platform_cover_text(platform: str, context: dict[str, Any]) -> str:
    topic = _trim(context["topic"], 14)
    if platform == "douyin":
        return _trim(f"{topic}\n别急着跟风", 22)
    if platform == "kuaishou":
        return _trim(f"{topic}\n先看懂再用", 22)
    if platform == "wechat_channels":
        return _trim(f"{topic}\n克制解读", 22)
    if platform == "bilibili":
        return _trim(f"{topic}\n来源与核查清单", 28)
    if platform == "xiaohongshu":
        return _trim(f"{topic}\n工具笔记", 22)
    return topic


def _platform_pinned_comment(platform: str, context: dict[str, Any]) -> str:
    manual = "本条基于现有资料生成草稿，发布前必须人工核查关键事实与版权边界。" if context["needs_manual_check"] else "这是一份发布草稿，欢迎补充来源、版本变化和实际使用体验。"
    if platform == "bilibili":
        return f"{manual} 如发现信息过期或表述不准确，请在评论区指出具体来源。"
    if platform == "wechat_channels":
        return f"{manual} 评论区欢迎补充更可靠的一手资料。"
    if platform == "xiaohongshu":
        return f"{manual} 如果你用过类似工具，可以补充真实体验，我会继续整理成清单。"
    return manual


def _common_publish_notes(context: dict[str, Any]) -> list[str]:
    notes = ["本模块只生成发布资产，不会自动发布到任何平台。"]
    if context["needs_manual_check"]:
        notes.append("发布前必须人工核查：审核状态未通过或 factual_confidence 偏低。")
    if context["render_status"] != "succeeded":
        notes.append(f"render_status={context['render_status']}，发布前确认 final_video.mp4 可正常播放。")
    return notes


def _manual_review_risks(context: dict[str, Any]) -> list[str]:
    risks = list(context["risks"])
    if context["needs_manual_check"]:
        risks.insert(0, "发布前必须人工核查：publish_review 未 approved 或 factual_confidence 偏低。")
    if context["source_url"]:
        risks.append(f"核对来源链接与原始上下文：{context['source_url']}")
    return list(dict.fromkeys(risks)) or ["发布前做最终人工复核。"]


def _platform_suitable(platform: str, context: dict[str, Any]) -> bool:
    if context["review_status"] == "rejected":
        return False
    if context["risk_pass"] is False or context["quality_pass"] is False:
        return False
    if platform == "bilibili":
        return bool(context["main_points"] or context["summary"])
    return bool(context["title"])


def _suitability_reason(platform: str, context: dict[str, Any], suitable: bool) -> str:
    if not suitable:
        if context["review_status"] == "rejected":
            return "发布审核为 rejected，不适合发布。"
        if context["risk_pass"] is False or context["quality_pass"] is False:
            return "风控或质检未通过，只能作为待修改草稿。"
        return "素材信息不足，暂不适合该平台。"
    return f"适合生成{PLATFORMS[platform]['platform_name']}草稿；{PLATFORMS[platform]['style']}"


def _copy_block(title: str, description: str, hashtags: list[str], pinned_comment: str) -> str:
    topic_line = " ".join(f"#{tag}" for tag in hashtags)
    return "\n".join(
        [
            "【标题】",
            title,
            "",
            "【简介】",
            description,
            "",
            "【话题】",
            topic_line,
            "",
            "【首评/置顶评论】",
            pinned_comment,
        ]
    )


def _render_markdown(package: dict[str, Any]) -> str:
    lines = [
        "# 多平台发布包",
        "",
        f"- content_id: {package['content_id']}",
        f"- generated_at: {package['generated_at']}",
        f"- publish_review_status: {package['publish_review_status']}",
        f"- factual_confidence: {package['factual_confidence']}",
        "",
    ]
    for platform, asset in package["platforms"].items():
        lines.extend(
            [
                f"## {asset['platform_name']} ({platform})",
                "",
                f"- suitable: {asset['suitable']}",
                f"- suitability_reason: {asset['suitability_reason']}",
                f"- cover_text: {asset['cover_text']}",
                f"- hashtags: {', '.join(asset['hashtags'])}",
                "",
                "### Copy Block",
                "",
                "```",
                asset["copy_block"],
                "```",
                "",
                "### 发布注意事项",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in asset["publish_notes"])
        lines.extend(["", "### 需要人工确认的风险点", ""])
        lines.extend(f"- {item}" for item in asset["manual_review_risks"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _extract_section(markdown: str, heading: str) -> str:
    match = re.search(rf"^#\s+{re.escape(heading)}\s*$", markdown, flags=re.MULTILINE)
    if not match:
        return ""
    next_match = re.search(r"^#\s+", markdown[match.end() :], flags=re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(markdown)
    return markdown[match.end() : end].strip()


def _collect_risks(
    analysis: dict[str, Any],
    risk_report: dict[str, Any],
    quality_check: dict[str, Any],
    publish_review: dict[str, Any],
) -> list[str]:
    items: list[str] = []
    for source, key in [
        (analysis, "facts_to_check"),
        (analysis, "risk_points"),
        (risk_report, "issues"),
        (risk_report, "must_fix"),
        (risk_report, "must_review"),
        (quality_check, "issues"),
        (quality_check, "fix_suggestions"),
    ]:
        items.extend(_as_text_list(source.get(key)))
    if publish_review.get("review_note"):
        items.append(str(publish_review["review_note"]))
    return list(dict.fromkeys(_clean_text(item) for item in items if _clean_text(item)))


def _needs_manual_check(analysis: dict[str, Any], publish_review: dict[str, Any]) -> bool:
    if publish_review.get("status") != "approved":
        return True
    confidence = str(analysis.get("factual_confidence") or "")
    return any(hint in confidence.lower() for hint in LOW_CONFIDENCE_HINTS)


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean_text(str(item)) for item in value if _clean_text(str(item))]
    if isinstance(value, str) and value.strip():
        return [_clean_text(value)]
    return []


def _source_line(context: dict[str, Any]) -> str:
    parts = []
    if context["source_name"]:
        parts.append(f"来源：{context['source_name']}")
    if context["source_url"]:
        parts.append(f"链接：{context['source_url']}")
    return "；".join(parts) if parts else "来源：输出包内 meta / analysis / script 文件。"


def _first_sentence(text: str) -> str:
    match = re.search(r"[^。！？!?；;\n]+[。！？!?；;]?", text)
    return _clean_text(match.group(0)) if match else ""


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _trim(text: str, limit: int) -> str:
    text = _clean_text(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
