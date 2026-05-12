from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_writer import stage_subdir


PLATFORMS = {
    "douyin": {
        "platform_name": "抖音",
        "priority": 1,
        "publish_stage": "primary",
        "content_fit": "为什么火、海外工具观察、项目故事",
        "video_length": "30-90 秒",
        "key_metrics": ["完播", "互动", "转粉"],
        "focus": "开头 3 秒",
        "style": "强钩子，强反差，突出为什么火、项目故事和开头 3 秒。",
        "tag_seed": ["AI工具", "效率工具", "自动化", "科技趋势"],
        "notes": ["标题和封面要突出一个明确钩子。", "开头 3 秒必须讲清为什么值得关注。", "避免夸大免费额度、工具效果或商业结果。"],
    },
    "kuaishou": {
        "platform_name": "快手",
        "priority": 4,
        "publish_stage": "secondary",
        "content_fit": "接地气、海外案例、观察感",
        "video_length": "30-120 秒",
        "key_metrics": ["完播", "评论", "信任感"],
        "focus": "话说人话",
        "style": "口语化，接地气，像给朋友解释，多讲观察和边界。",
        "tag_seed": ["实用工具", "AI自动化", "AI观察", "经验分享"],
        "notes": ["简介建议保留口语感，少堆概念。", "话说人话，避免过多英文术语。", "首评可以引导观众补充使用体验。"],
    },
    "wechat_channels": {
        "platform_name": "微信视频号",
        "priority": 2,
        "publish_stage": "primary",
        "content_fit": "泛人群、转发价值、商业认知",
        "video_length": "1-3 分钟",
        "key_metrics": ["转发", "点赞", "完播"],
        "focus": "稳重、有观点",
        "style": "克制可信，强调观点、来源、核查和适用边界。",
        "tag_seed": ["AI观察", "工具解读", "海外AI", "科技解读"],
        "notes": ["表达要克制，避免标题党。", "观点要稳，适合被转发给泛人群。", "建议在简介中保留来源和核查提醒。"],
    },
    "bilibili": {
        "platform_name": "B站",
        "priority": 3,
        "publish_stage": "primary",
        "content_fit": "深度拆解、工具解读、复盘",
        "video_length": "3-8 分钟",
        "key_metrics": ["收藏", "投币", "评论", "完播"],
        "focus": "信息密度",
        "style": "信息完整，强调信息密度，交代来源、背景和待核查点。",
        "tag_seed": ["AI", "开源项目", "工具测评", "技术观察"],
        "notes": ["简介可以更完整，说明资料来源与核查限制。", "适合补充参考链接、版本信息或来源截图。", "如果内容不足 3 分钟，建议作为短拆解或合集素材。"],
    },
    "xiaohongshu": {
        "platform_name": "小红书",
        "priority": 99,
        "publish_stage": "deferred",
        "content_fit": "工具清单、项目笔记、方法论",
        "video_length": "30-90 秒/图文",
        "key_metrics": ["收藏", "搜索", "私信"],
        "focus": "标题和封面",
        "style": "先滞后处理，只保留可复制发布包；当前不作为口播和导演层的核心风格。",
        "tag_seed": ["AI工具", "工具清单", "效率方法", "项目笔记"],
        "notes": ["当前阶段小红书先滞后处理。", "只保留发布包字段，不作为主投放平台。", "后续如果做图文/笔记化，再单独适配。"],
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

# Older analysis.json files (and any LLM run before the prompt fix) embed
# internal alignment hints like ``(对应 key_moments[1])`` inside main_points
# / facts_to_check entries. They were never meant for the audience but they
# leak straight into the platform copy_block and look like a bug. Strip
# them defensively so old archives keep producing publishable copy.
_META_ANNOTATION_RE = re.compile(
    r"\s*[(（]\s*对应\s*key[_\- ]?moments?\s*\[?\s*\d+\s*\]?\s*[)）]"
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def generate_platform_publish_package(content_id: str, package_dir: Path) -> dict[str, Any]:
    # All inputs were moved into Tier B stage subdirs (00_source/, 01_analysis/,
    # 02_script/, 08_qc/, 09_publish/) -- ``stage_subdir`` resolves them with a
    # legacy flat fallback so half-migrated candidates still work.
    meta = _read_json(stage_subdir(package_dir, "meta.json"))
    analysis = _read_json(stage_subdir(package_dir, "analysis.json")) or _read_json(
        stage_subdir(package_dir, "github_analysis.json")
    )
    risk_report = _read_json(stage_subdir(package_dir, "risk_report.json"))
    quality_check = _read_json(stage_subdir(package_dir, "quality_check.json"))
    publish_review = _read_json(stage_subdir(package_dir, "publish_review.json"))
    render_status = _read_json(stage_subdir(package_dir, "render_status.json"))
    director_plan = _read_json(stage_subdir(package_dir, "director_plan.json"))
    script_text = _read_text(stage_subdir(package_dir, "chinese_script.md"))

    context = _build_context(content_id, meta, analysis, risk_report, quality_check, publish_review, render_status, script_text, director_plan)
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
        if not stage_subdir(package_dir, "final_video.mp4").exists():
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
    director_plan: dict[str, Any],
) -> dict[str, Any]:
    script_title = _extract_section(script_text, "标题").splitlines()[0:1]
    title = _clean_text(script_title[0]) if script_title else ""
    title = title or _clean_text(str(meta.get("title") or analysis.get("core_topic") or content_id))
    # ``voiceover`` keeps the original line breaks because we want
    # ``_hook_paragraph`` to grab the script's lead paragraph (the actual
    # hook) instead of the first 4-char rhetorical opener like "你相信吗？".
    voiceover_raw = _strip_meta_annotations(
        str(director_plan.get("voiceover") or "")
    ) or _extract_section(script_text, "口播稿")
    voiceover = _clean_text(voiceover_raw)
    hook = _hook_paragraph(voiceover_raw, max_chars=130)
    summary = hook or _strip_meta_annotations(
        _clean_text(str(analysis.get("summary") or ""))
    )
    # main_points: 优先从 chinese_script.md 的核心三段（故事/它怎么做到/它还能干什么）
    # 提炼，每段抽一句最能代表这段叙事的话。这把"轻量级本地代码代理"这种老
    # analysis.main_points 文案从发布文案里挤出去——之前发布包跟成片完全两个故事。
    # 只有当脚本三段都没拿到内容时才回落到 analysis.main_points。
    script_main_points = _main_points_from_script(script_text)
    if script_main_points:
        main_points = script_main_points
    else:
        main_points = _as_text_list(analysis.get("main_points"))
    risks = _collect_risks(analysis, risk_report, quality_check, publish_review)
    needs_manual_check = _needs_manual_check(analysis, publish_review)
    source_name = str(meta.get("author") or meta.get("channel_title") or meta.get("full_name") or "")
    source_url = str(meta.get("source_url") or meta.get("webpage_url") or meta.get("html_url") or "")
    topic_text = _clean_text(str(analysis.get("core_topic") or title))
    hashtag_keywords = _resolve_hashtag_keywords(analysis, topic_text, main_points, meta)
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
        "topic": topic_text,
        "hashtag_keywords": hashtag_keywords,
        "content_type": str(analysis.get("content_type") or ""),
        "director_style": str((director_plan.get("style") or {}).get("version") or ""),
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
        "priority": config["priority"],
        "publish_stage": config["publish_stage"],
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
    raw_title = context["title"]
    topic = _trim(context["topic"], 28)
    # B 站 / 其他中文短视频平台用 LLM 提炼的中文 topic 兜底，避免直接打英文原标
    # （早期 chinese_script.md "# 标题" 段没填，``context["title"]`` 会回落到
    # ``meta.title`` 的英文，看起来像 raw asset）。
    chinese_title = raw_title if _is_mostly_chinese(raw_title) else context["topic"]
    title = _trim(chinese_title, 44)
    content_type = context.get("content_type", "")
    if content_type == "ai_cli_agent":
        developer_angle = f"开发者为什么关注 {topic}？"
    elif content_type == "github_open_source_project":
        developer_angle = f"{topic}：一个开源 AI 项目观察"
    else:
        developer_angle = f"{topic} 为什么突然火？"
    if platform == "douyin":
        return _trim(developer_angle, 38)
    if platform == "kuaishou":
        return _trim(f"海外 AI 工具观察：{topic}", 42)
    if platform == "wechat_channels":
        return _trim(f"{topic}：一次海外 AI 机会观察", 44)
    if platform == "bilibili":
        return _trim(f"{title}｜为什么火、解决什么问题与边界", 72)
    if platform == "xiaohongshu":
        return _trim(f"{topic}｜海外 AI 工具笔记", 36)
    return title


def _platform_description(platform: str, context: dict[str, Any]) -> str:
    summary = context["summary"] or _first_sentence(context["voiceover"]) or context["topic"]
    points = "；".join(context["main_points"][:3])
    source = _source_line(context)
    if platform == "douyin":
        return _trim(f"{summary}\n\n关键不是跟风，是看懂这个方向为什么突然变热。", 220)
    if platform == "kuaishou":
        return _trim(f"{summary}\n\n我把它到底解决什么、普通人能看懂什么趋势，拆成几个点。{points or context['topic']}。", 260)
    if platform == "wechat_channels":
        return _trim(f"{summary}\n\n{source}\n这类工具还早，但它代表 AI 从回答问题走向执行任务。", 300)
    if platform == "bilibili":
        return _trim(
            f"{summary}\n\n主要看点：{points or context['topic']}。\n{source}\n这期重点不是教程，而是拆它为什么火、解决什么问题，以及这个方向对中文用户有什么启发。",
            700,
        )
    if platform == "xiaohongshu":
        return _trim(
            f"{summary}\n\n小红书当前先滞后处理，这里只保留备用发布文案。",
            320,
        )
    return summary


def _platform_hashtags(platform: str, context: dict[str, Any]) -> list[str]:
    # 优先用 LLM 给的 hashtag_keywords（每条 ≤6 字、不含 #/空格），
    # 其次拼平台 tag_seed。从前面 5 个截掉，避免 hashtag 队列过长。
    tags: list[str] = []
    for kw in context.get("hashtag_keywords") or []:
        cleaned = _normalize_hashtag(kw)
        if cleaned and len(cleaned) <= 8:
            tags.append(cleaned)
    tags.extend(PLATFORMS[platform]["tag_seed"])
    if context["source_type"] == "github_repo":
        tags.append("GitHub")
    deduped: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if tag and tag not in seen:
            seen.add(tag)
            deduped.append(tag)
    return deduped[:6]


def _normalize_hashtag(value: str) -> str:
    """Strip leading ``#`` and any whitespace/punct so the tag stays a single token."""
    text = re.sub(r"^[#＃\s]+", "", str(value or ""))
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text)


# Common Chinese function words / connectors we don't want as standalone hashtags.
_TOPIC_STOPWORDS: frozenset[str] = frozenset(
    [
        "的", "了", "和", "与", "在", "为", "对", "中", "上", "下", "及",
        "以", "或", "而", "于", "等", "如", "是", "也", "都", "就", "把",
        "向", "从", "到", "用", "给", "让", "被", "应用", "应用场景", "中的",
        "中的应用", "趋势", "方向", "案例", "故事", "解读",
    ]
)


def _resolve_hashtag_keywords(
    analysis: dict[str, Any],
    topic_text: str,
    main_points: list[str],
    meta: dict[str, Any],
) -> list[str]:
    """Return 3-5 short hashtag-friendly keywords.

    Order of preference:
      1. ``analysis.hashtag_keywords`` — once the LLM prompt update lands,
         this is the authoritative list (per-topic, ≤6 chars each).
      2. Tokens cut out of ``core_topic`` — drop stopwords / connector
         characters, keep 2-6 char Chinese segments and any latin words.
      3. Salient names from ``main_points`` (Peter, OpenClaw, Dropbox …).
      4. Channel / author name from ``meta`` as a last-ditch token.
    Anything that survives is normalised through ``_normalize_hashtag`` so
    we never ship a tag containing whitespace or punctuation.
    """
    candidates: list[str] = []

    raw = analysis.get("hashtag_keywords")
    if isinstance(raw, list):
        for kw in raw:
            cleaned = _normalize_hashtag(str(kw))
            if cleaned and len(cleaned) <= 8:
                candidates.append(cleaned)

    if not candidates:
        candidates.extend(_split_topic_into_tokens(topic_text))
        candidates.extend(_extract_proper_nouns(main_points))
        for fallback in (
            meta.get("channel_title"),
            meta.get("author"),
            meta.get("full_name"),
        ):
            token = _normalize_hashtag(str(fallback or ""))
            if token and 2 <= len(token) <= 8:
                candidates.append(token)
                break

    deduped: list[str] = []
    seen: set[str] = set()
    for token in candidates:
        if token and token not in seen and token not in _TOPIC_STOPWORDS:
            seen.add(token)
            deduped.append(token)
        if len(deduped) >= 5:
            break
    return deduped


# High-frequency Chinese tokens that read well as standalone hashtags.
# When they appear inside ``core_topic`` we lift them out as their own tag,
# instead of keeping the whole topic phrase as a single (then truncated)
# hashtag.
_TOPIC_KEYWORD_TOKENS: tuple[str, ...] = (
    "AI Agent", "智能体", "自动化", "生产力", "效率工具",
    "开源", "开发者", "工具链", "开源项目", "海外AI", "海外",
    "趋势", "技术趋势", "项目笔记", "工具测评", "信息差",
    "个人生活", "个人生产力", "操作系统", "终端", "命令行",
    "Agent", "Copilot", "GitHub", "ChatGPT", "Claude",
)


def _split_topic_into_tokens(topic: str) -> list[str]:
    """Cut a Chinese-mixed topic phrase into tag-sized fragments.

    Strategy:
      1. Pull out latin product / brand words (``AI``, ``GitHub``, ``Claude``).
      2. Iterate ``_TOPIC_KEYWORD_TOKENS`` and lift each one out if it
         appears as a substring — gives "AI 在个人生活自动化中的应用"
         the tags ["AI", "个人生活", "自动化"].
      3. Skip noise / connector chars; we never break Chinese into
         arbitrary 2-grams since that often produces meaningless tags.
    """
    if not topic:
        return []
    tokens: list[str] = []
    for latin in re.findall(r"[A-Za-z][A-Za-z0-9+.-]{0,7}", topic):
        if 2 <= len(latin) <= 8:
            tokens.append(latin)
    for kw in _TOPIC_KEYWORD_TOKENS:
        if kw in topic and kw not in tokens:
            tokens.append(kw)
    return tokens


def _extract_proper_nouns(points: list[str]) -> list[str]:
    """Pull product/person names (English camel case + capitalised words) out of main_points."""
    nouns: list[str] = []
    for point in points:
        for match in re.findall(r"[A-Z][A-Za-z0-9]{1,15}", point):
            if 2 <= len(match) <= 12:
                nouns.append(match)
    return nouns


def _platform_cover_text(platform: str, context: dict[str, Any]) -> str:
    topic = _trim(context["topic"], 14)
    if platform == "douyin":
        return _trim(f"{topic}\n为什么火", 22)
    if platform == "kuaishou":
        return _trim(f"{topic}\n海外观察", 22)
    if platform == "wechat_channels":
        return _trim(f"{topic}\n机会观察", 22)
    if platform == "bilibili":
        return _trim(f"{topic}\n为什么值得关注", 28)
    if platform == "xiaohongshu":
        return _trim(f"{topic}\nAI 工具笔记", 22)
    return topic


def _platform_pinned_comment(platform: str, context: dict[str, Any]) -> str:
    manual = "如果你用过类似工具，欢迎补充真实体验，我会继续追这个方向。" if not context["needs_manual_check"] else "这类海外项目变化很快，评论区欢迎补充最新版本和真实体验。"
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
    if PLATFORMS[platform].get("publish_stage") == "deferred":
        return False
    if context["review_status"] == "rejected":
        return False
    if context["risk_pass"] is False or context["quality_pass"] is False:
        return False
    if platform == "bilibili":
        return bool(context["main_points"] or context["summary"])
    return bool(context["title"])


def _suitability_reason(platform: str, context: dict[str, Any], suitable: bool) -> str:
    if not suitable:
        if PLATFORMS[platform].get("publish_stage") == "deferred":
            return "小红书当前先滞后处理，只保留发布包字段，不作为主投放平台。"
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
                f"- priority: {asset['priority']}",
                f"- publish_stage: {asset['publish_stage']}",
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
        return [
            _strip_meta_annotations(_clean_text(str(item)))
            for item in value
            if _clean_text(str(item))
        ]
    if isinstance(value, str) and value.strip():
        return [_strip_meta_annotations(_clean_text(value))]
    return []


def _strip_meta_annotations(text: str) -> str:
    """Remove internal LLM alignment hints like ``(对应 key_moments[2])``."""
    return _META_ANNOTATION_RE.sub("", text).rstrip(" 。.,;；、")


def _is_mostly_chinese(text: str) -> bool:
    """True when the title reads as a Chinese sentence (≥50% CJK chars).

    Used to fall back to ``topic`` (which is always LLM-rewritten Chinese)
    on platforms like Bilibili / Douyin where an English original title
    looks alien next to the rest of the copy.
    """
    cleaned = re.sub(r"\s+", "", text)
    if not cleaned:
        return False
    cjk = len(_CJK_RE.findall(cleaned))
    return cjk * 2 >= len(cleaned)


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


def _main_points_from_script(script_text: str) -> list[str]:
    """Extract 3 narrative bullets from the canonical script's core sections.

    Each section's first declarative sentence gets pulled — that's typically
    the strongest factual claim of that section. We avoid grabbing the
    section's last sentence (often a transitional "我们继续看...") and
    bullet-list lines (those are 分镜建议 / 屏幕文字, not voiceover).

    Returns at most 3 bullets, each ≤ 60 Chinese chars. Returns empty list
    when the script doesn't have these sections — caller falls back to
    analysis.main_points so we never ship blank descriptions.
    """
    if not script_text:
        return []
    section_titles = ("故事是怎么发生的", "它到底怎么做到的", "它还能干什么")
    bullets: list[str] = []
    for title in section_titles:
        block = _extract_section(script_text, title)
        if not block:
            continue
        # First non-bullet, non-heading sentence ≥ 8 chars.
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(("-", "*", "+", "•")):
                continue
            sentence = re.split(r"[。！？!?]", line)[0].strip()
            if len(sentence) >= 8:
                bullets.append(_clean_text(sentence)[:60])
                break
        if len(bullets) >= 3:
            break
    return bullets


def _hook_paragraph(text: str, *, max_chars: int = 130) -> str:
    """Return the script's lead paragraph (the hook), trimmed to ``max_chars``.

    The previous ``_first_sentence`` would happily slice "你相信吗？Peter 在摩洛哥时
    AI 自动修复了 bug" into just "你相信吗？" — losing every concrete fact in the
    process. Platform descriptions then read like SEO filler. Instead we grab the
    full first line / paragraph (which by convention in chinese_script.md is the
    hook block, ~50–80 chars), and only fall back to a sentence-bounded cut when
    the hook overruns ``max_chars``.
    """
    if not text:
        return ""
    # Split on the first blank line / line-break — the hook section is one
    # paragraph by convention. ``str.split`` works regardless of platform-specific
    # line endings since we already strip earlier.
    first_block = re.split(r"\n\s*\n|\n", text, maxsplit=1)[0].strip()
    first_block = _clean_text(first_block)
    if not first_block:
        return ""
    if len(first_block) <= max_chars:
        return first_block
    cut = first_block[:max_chars]
    # Prefer to break at a sentence terminator so we never end mid-clause.
    for delim in "。！？!?":
        idx = cut.rfind(delim)
        if idx > max_chars * 0.4:
            return cut[: idx + 1]
    return _trim(first_block, max_chars)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _trim(text: str, limit: int) -> str:
    text = _clean_text(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
