from __future__ import annotations

from enum import Enum
from typing import Any


class ContentType(str, Enum):
    AI_TOOL_EXPLAINER = "ai_tool_explainer"
    AI_CLI_AGENT = "ai_cli_agent"
    GITHUB_OPEN_SOURCE_PROJECT = "github_open_source_project"
    OVERSEAS_AI_STARTUP_CASE = "overseas_ai_startup_case"
    PRODUCT_HUNT_NEW_PRODUCT = "product_hunt_new_product"
    AI_BUSINESS_MODEL_OBSERVATION = "ai_business_model_observation"
    OVERSEAS_INFO_GAP_STORY = "overseas_info_gap_story"


CONTENT_POSITIONING = (
    "海外 AI 商业机会、AI 工具/CLI/开源项目解读与中文叙事视频资产；"
    "重点是解读、叙事、观察和拆解，不承诺收益，不提供灰产路径。"
)

CONTENT_TYPE_VALUES = [item.value for item in ContentType]

OPPORTUNITY_DIMENSIONS = {
    "why_now": "为什么现在值得关注",
    "problem_intensity": "解决问题强度",
    "china_gap": "中文稀缺度",
    "narrative_value": "叙事价值",
    "video_potential": "视频化潜力",
    "business_insight": "商业启发",
    "audience_fit": "受众匹配",
    "evidence_completeness": "资料完整度",
    "risk_control": "风险控制",
}


def normalize_analysis_positioning(analysis: dict[str, Any], *, source_type: str = "", default_content_type: str | None = None) -> dict[str, Any]:
    """Backfill positioning fields without removing legacy analysis keys."""
    content_type = _content_type(analysis, source_type=source_type, default_content_type=default_content_type)
    dimensions = _dimension_scores(analysis)
    analysis.setdefault("content_type", content_type)
    analysis.setdefault("content_positioning", CONTENT_POSITIONING)
    analysis.setdefault("opportunity_dimensions", dimensions)
    analysis.setdefault("why_now", _why_now(analysis, content_type))
    analysis.setdefault("china_gap", _china_gap(analysis))
    analysis.setdefault("narrative_value", _narrative_value(analysis, content_type))
    analysis.setdefault("business_insight", _business_insight(analysis, content_type))
    analysis.setdefault("risk_control", _risk_control(analysis))
    return analysis


def default_dimension_scores(analysis: dict[str, Any]) -> dict[str, int]:
    return _dimension_scores(analysis)


def _content_type(analysis: dict[str, Any], *, source_type: str, default_content_type: str | None) -> str:
    value = str(analysis.get("content_type") or default_content_type or "").strip()
    if value in CONTENT_TYPE_VALUES:
        return value
    formats = " ".join(str(item) for item in analysis.get("content_formats", []) if item)
    text = " ".join(
        str(part)
        for part in [
            source_type,
            analysis.get("core_topic"),
            analysis.get("summary"),
            analysis.get("project_positioning"),
            formats,
        ]
        if part
    ).lower()
    if source_type == "github_repo" or "github" in text or "open source" in text or "开源" in text:
        return ContentType.GITHUB_OPEN_SOURCE_PROJECT.value
    if "cli" in text or "command line" in text or "agent" in text or "开发者工具" in text:
        return ContentType.AI_CLI_AGENT.value
    if "product hunt" in text or "launch" in text or "new product" in text:
        return ContentType.PRODUCT_HUNT_NEW_PRODUCT.value
    if "startup" in text or "founder" in text or "创业" in text:
        return ContentType.OVERSEAS_AI_STARTUP_CASE.value
    if "business model" in text or "商业模式" in text or "pricing" in text:
        return ContentType.AI_BUSINESS_MODEL_OBSERVATION.value
    if "tool" in text or "workflow" in text or "工具" in text:
        return ContentType.AI_TOOL_EXPLAINER.value
    return ContentType.OVERSEAS_INFO_GAP_STORY.value


def _dimension_scores(analysis: dict[str, Any]) -> dict[str, int]:
    domestic = _score_value(analysis.get("domestic_value"), default=6)
    commercial = _score_value(analysis.get("commercial_value"), default=6)
    video = _score_value(analysis.get("short_video_suitability"), default=6)
    risks = analysis.get("risk_points")
    facts = analysis.get("facts_to_check")
    main_points = analysis.get("main_points")
    evidence = 8 if isinstance(facts, list) and facts else 6
    risk_control = 6 if risks else 8
    narrative = 8 if isinstance(main_points, list) and len(main_points) >= 2 else 6
    return {
        "why_now": _score_value(analysis.get("why_now_score"), default=7),
        "problem_intensity": _score_value(analysis.get("problem_intensity"), default=commercial),
        "china_gap": _score_value(analysis.get("china_gap_score"), default=domestic),
        "narrative_value": _score_value(analysis.get("narrative_value_score"), default=narrative),
        "video_potential": _score_value(analysis.get("video_potential"), default=video),
        "business_insight": _score_value(analysis.get("business_insight_score"), default=commercial),
        "audience_fit": _score_value(analysis.get("audience_fit"), default=domestic),
        "evidence_completeness": _score_value(analysis.get("evidence_completeness"), default=evidence),
        "risk_control": _score_value(analysis.get("risk_control"), default=risk_control),
    }


def _why_now(analysis: dict[str, Any], content_type: str) -> str:
    if analysis.get("why_now"):
        return str(analysis["why_now"])
    topic = str(analysis.get("core_topic") or "这个海外 AI 选题")
    if content_type == ContentType.GITHUB_OPEN_SOURCE_PROJECT.value:
        return f"{topic} 近期值得关注，因为它反映了海外开发者工具链和开源 AI 项目的变化。"
    return f"{topic} 近期值得关注，因为它提供了观察海外 AI 工具、产品和商业机会的新样本。"


def _china_gap(analysis: dict[str, Any]) -> str:
    if analysis.get("china_gap"):
        return str(analysis["china_gap"])
    return "中文语境下需要补充来源、背景、适用边界和本地用户能理解的叙事。"


def _narrative_value(analysis: dict[str, Any], content_type: str) -> str:
    if analysis.get("narrative_value"):
        return str(analysis["narrative_value"])
    if content_type == ContentType.AI_CLI_AGENT.value:
        return "适合拆成“开发者为什么关注这个 CLI / agent、它改变了什么工作流”的叙事。"
    return "适合拆成“为什么火、海外发生了什么、解决什么问题、中文用户得到什么启发”的叙事。"


def _business_insight(analysis: dict[str, Any], content_type: str) -> str:
    if analysis.get("business_insight"):
        return str(analysis["business_insight"])
    if content_type == ContentType.GITHUB_OPEN_SOURCE_PROJECT.value:
        return "观察开源项目背后的开发者需求、生态位置和可能的产品化方向，不等同于商业成功。"
    return "观察海外 AI 产品如何定义问题、获取用户和形成差异化，不给收益承诺。"


def _risk_control(analysis: dict[str, Any]) -> str:
    if analysis.get("risk_control"):
        return str(analysis["risk_control"])
    risks = analysis.get("risk_points")
    if isinstance(risks, list) and risks:
        return "发布前核查事实、来源边界和夸大表达，避免收益承诺或照搬路径。"
    return "保留事实核查和来源边界提醒，避免把观察表达成确定结论。"


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
            return default
    return default


def _clamp_score(value: int) -> int:
    return max(0, min(10, value))
