from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


# 文档 §3.1 明确推荐"中文短视频口播用 Claude Sonnet"。当前 .env
# 默认 gpt-4o-mini，对 130 行 rewrite 硬约束 prompt 服从度不够，
# 反复产出"AI 真神奇 / 一点感慨"软泛收尾。把 task_type=rewrite 路由
# 到 Claude Sonnet 4.6 是单点最高 ROI 的 LLM 升级 —— ANTHROPIC_API_KEY
# 已经在 .env 配好，但旧代码 generate_json() 只走 OpenAI 分支，等于
# key 浪费。其它 task 仍走 OpenAI，因为它们依赖 strict json_schema
# response_format（Anthropic Messages API 不支持同等强度的 schema 锁）。
_ANTHROPIC_REWRITE_MODEL = "claude-sonnet-4-6"


# JSON Schemas used with OpenAI's strict json_schema response format.
# When ``strict`` is true the model is *forced* to populate every
# property in ``properties`` (`additionalProperties` is locked to false
# and every key listed in ``required`` must be returned). Without this
# we kept seeing gpt-4o-mini / gpt-4o silently dropping ``key_moments``
# even though the prompt screamed "必须先做" — the model just doesn't
# treat narrative instructions as a binding contract.

_KEY_MOMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["timestamp_seconds", "original_quote", "chinese_translation", "why_it_matters"],
    "properties": {
        "timestamp_seconds": {"type": "integer"},
        "original_quote": {"type": "string"},
        "chinese_translation": {"type": "string"},
        "why_it_matters": {"type": "string"},
    },
}

_YOUTUBE_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    # OpenAI strict mode forces every property listed here to be returned.
    # We deliberately keep the surface narrow to the fields downstream
    # consumers actually read — extra LLM-invented fields are fine to
    # drop, missing required fields would crash the rewriter.
    "required": [
        "key_moments",
        "summary",
        "core_topic",
        "content_type",
        "why_now",
        "china_gap",
        "narrative_value",
        "business_insight",
        "main_points",
        "hashtag_keywords",
        "facts_to_check",
        "risk_points",
    ],
    "properties": {
        "key_moments": {
            "type": "array",
            "items": _KEY_MOMENT_SCHEMA,
        },
        "summary": {"type": "string"},
        "core_topic": {"type": "string"},
        "content_type": {"type": "string"},
        "why_now": {"type": "string"},
        "china_gap": {"type": "string"},
        "narrative_value": {"type": "string"},
        "business_insight": {"type": "string"},
        "main_points": {"type": "array", "items": {"type": "string"}},
        # 4-6 个简短中文标签关键词，每条 ≤6 字，给 hashtag 用，避免把
        # core_topic 整句当 hashtag 被截成 "#XXX中…"。
        "hashtag_keywords": {"type": "array", "items": {"type": "string"}},
        "facts_to_check": {"type": "array", "items": {"type": "string"}},
        "risk_points": {"type": "array", "items": {"type": "string"}},
    },
}

_REWRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["script", "titles"],
    "properties": {
        # script must be a markdown string, NOT a nested object — we
        # have been bitten repeatedly by LLMs returning script as a
        # dict that downstream code then str()'s into the file.
        "script": {"type": "string"},
        "titles": {"type": "array", "items": {"type": "string"}},
    },
}


# Strict schema for the lightweight ``flow_steps`` task that the
# video_director uses to turn a single mechanism-scene voiceover into a
# 3-5 node flow chart. The schema is intentionally tight:
#
# - Exactly one ``steps`` array (no commentary fields the model can use
#   to leak back into prose).
# - Each step is a string with no nested object — keeps the output trivially
#   parseable and prevents the LLM from inventing extra keys we'd ignore
#   downstream.
# - We rely on the prompt to enforce length / count constraints
#   (3-5 items, ≤12 chars each); the schema enforces shape so when the
#   model violates length we can defensively trim instead of crashing.
_FLOW_STEPS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["steps"],
    "properties": {
        "steps": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


def _strict_schema_for(task_type: str) -> dict[str, Any] | None:
    if task_type == "youtube_candidate_analysis":
        return _YOUTUBE_ANALYSIS_SCHEMA
    # rewrite + github_rewrite 共用一份 schema —— 两条链路都要 ``script``
    # (markdown) + ``titles`` (array of str)，下游 _normalize_script /
    # _normalize_titles 也是同一对函数。
    if task_type in ("rewrite", "github_rewrite"):
        return _REWRITE_SCHEMA
    if task_type == "flow_steps":
        return _FLOW_STEPS_SCHEMA
    return None


@dataclass
class LLMResponse:
    provider: str
    model: str
    content: dict[str, Any] | str
    prompt_version: str = "v1"
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate: float = 0.0


class LLMClient:
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        mock: bool,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
        google_api_key: str | None = None,
    ):
        self.provider = provider
        self.model = model
        self.mock = mock
        self.openai_api_key = openai_api_key
        self.anthropic_api_key = anthropic_api_key
        self.google_api_key = google_api_key

    def generate(self, task_type: str, payload: dict[str, Any]) -> LLMResponse:
        if self.mock or self.provider == "mock":
            return LLMResponse(provider="mock", model="mock-content-asset-v1", content=self._mock_content(task_type, payload))

        if self.provider == "openai":
            return self.generate_json(task_type, payload)
        if self.provider == "anthropic" and not self.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for Anthropic provider")
        if self.provider == "gemini" and not self.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY is required for Gemini provider")

        raise NotImplementedError(
            f"Provider '{self.provider}' is configured but full LLM execution is intentionally minimal in MVP v1. "
            "Use --mock for dry-run or extend LLMClient.generate for production calls."
        )

    def _route_provider_for_task(self, task_type: str) -> str:
        # rewrite + github_rewrite 是中文叙事短视频口播稿的产出点 ——
        # 文档 §3.1 明确推荐 Claude Sonnet。其它 task（analysis / risk
        # / quality / flow_steps / youtube_candidate_analysis）走 OpenAI
        # 是因为它们用了 strict response_format=json_schema，OpenAI 这
        # 一侧实现得更稳。**两个 rewrite 必须一起路由,否则 GitHub 链路
        # 写出来的 chinese_script.md 仍然是 4o-mini 软泛产物**。
        if task_type in ("rewrite", "github_rewrite") and self.anthropic_api_key:
            return "anthropic"
        return "openai"

    def generate_json(self, task_type: str, payload: dict[str, Any]) -> LLMResponse:
        if self.mock or self.provider == "mock":
            content = self._mock_content(task_type, payload)
            if not isinstance(content, dict):
                raise RuntimeError(f"Mock task '{task_type}' did not return JSON")
            return LLMResponse(provider="mock", model="mock-content-asset-v1", content=content)
        routed = self._route_provider_for_task(task_type)
        if routed == "anthropic":
            text, usage = self._anthropic_chat(task_type, payload, expect_json=True)
            return LLMResponse(
                provider="anthropic",
                model=_ANTHROPIC_REWRITE_MODEL,
                content=_parse_json_with_repair(text),
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )
        if self.provider != "openai":
            raise NotImplementedError(f"JSON generation is not implemented for provider '{self.provider}'")
        text, usage = self._openai_chat(task_type, payload, expect_json=True)
        return LLMResponse(
            provider="openai",
            model=self.model,
            content=_parse_json_with_repair(text),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    def generate_markdown(self, task_type: str, payload: dict[str, Any]) -> LLMResponse:
        if self.mock or self.provider == "mock":
            return LLMResponse(provider="mock", model="mock-content-asset-v1", content=str(self._mock_content(task_type, payload)))
        if self.provider != "openai":
            raise NotImplementedError(f"Markdown generation is not implemented for provider '{self.provider}'")
        text, usage = self._openai_chat(task_type, payload, expect_json=False)
        return LLMResponse(
            provider="openai",
            model=self.model,
            content=text,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    def _anthropic_chat(self, task_type: str, payload: dict[str, Any], *, expect_json: bool) -> tuple[str, dict[str, int]]:
        # Claude Sonnet 4.6 路径，目前只为 task_type=rewrite 启用。Sonnet 在
        # 长 prompt 服从度上明显强于 gpt-4o-mini —— 这是为什么 yt_9d1a160bbcab
        # 的"AI 真神奇"软泛叙事会被换 LLM 修复，而不是再叠 prompt。
        if not self.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for Anthropic provider.")
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError("anthropic package is required for Anthropic provider.") from exc

        client = Anthropic(api_key=self.anthropic_api_key)
        # 同 OpenAI 路径的 system prompt，去掉 "JSON-only" 那段 —— 因为
        # 我们用 tool_use 模式拿结构化输出，不再依赖 Claude 的 markdown
        # 自律。这避免了一类很恶心的 bug：Claude 在 script 这种长
        # markdown string 里随手用 ASCII 双引号 ("a")，破坏外层 JSON
        # 的引号配对。tool_use 让 SDK 直接返回 dict，整段绕过 JSON
        # parse。
        system_prompt = (
            "你是中文短视频内容生产助手。除非字段明确说要保留原语言引文，所有 value 必须用简体中文输出。"
            "禁止把 dict 字面量序列化成 string。"
            "**transcript 里写到的内容（人名、地名、数字、动作）就是事实依据，可以也应该原文照引——这正是分析的核心**。"
            "只在 transcript 没写到的内容上保持保守，不要凭空编造。"
        )
        user_prompt = _build_prompt(task_type, payload, expect_json=expect_json)

        kwargs: dict[str, Any] = {
            "model": _ANTHROPIC_REWRITE_MODEL,
            "max_tokens": 8192,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        # 走 strict schema 的 task 用 tool_use 锁定输出形状。Anthropic
        # input_schema 不接受 OpenAI 特有的 ``strict`` keyword，需要 strip
        # —— 但 ``additionalProperties`` / ``required`` / ``properties``
        # 是 JSON Schema 标准字段，可以原样复用。
        schema = _strict_schema_for(task_type) if expect_json else None
        if schema is not None:
            tool_name = f"submit_{task_type}".replace("-", "_")
            kwargs["tools"] = [{
                "name": tool_name,
                "description": f"Submit the {task_type} result.",
                "input_schema": schema,
            }]
            kwargs["tool_choice"] = {"type": "tool", "name": tool_name}

        try:
            response = client.messages.create(**kwargs)
        except Exception as exc:
            raise RuntimeError(f"Anthropic generation failed for task '{task_type}': {exc}") from exc

        usage_obj = getattr(response, "usage", None)
        usage = {
            "input_tokens": int(getattr(usage_obj, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage_obj, "output_tokens", 0) or 0),
        }

        # 优先取 tool_use block：那里 ``input`` 已经是结构化 dict，
        # ``json.dumps`` 把它再编码成文本，外层 _parse_json_with_repair
        # 会还原成 dict —— 全流程没人需要解析 LLM 自己写的 JSON。
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                tool_input = getattr(block, "input", None)
                if isinstance(tool_input, dict):
                    return json.dumps(tool_input, ensure_ascii=False), usage

        # No tool_use → 走文本 fallback（无 strict schema 的 task）。
        text_blocks = [block.text for block in response.content if hasattr(block, "text")]
        return "".join(text_blocks), usage

    def _openai_chat(self, task_type: str, payload: dict[str, Any], *, expect_json: bool) -> tuple[str, dict[str, int]]:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI provider.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is required for OpenAI provider.") from exc

        client = OpenAI(api_key=self.openai_api_key)
        # System prompt walks a fine line: it has to keep gpt-4o-mini from
        # slipping into English (which it does whenever the system role is
        # all English), but it must NOT scare the model away from quoting
        # transcript content. An earlier draft included "所有数字、人名、
        # 地名必须有依据，不要编造" — the model interpreted this as
        # "avoid quoting names/numbers" and shipped empty key_moments
        # plus an English-only summary. The current wording explicitly
        # marks transcript text as a trusted source so the model is
        # encouraged to lift Morocco / 80% / fitness pal etc. verbatim.
        system_prompt = (
            "你是中文短视频内容生产助手。除非字段明确说要保留原语言引文，所有 value 必须用简体中文输出。"
            "If JSON is requested, return only valid JSON with no markdown fence. "
            "禁止把 dict 字面量序列化成 string。"
            "**transcript 里写到的内容（人名、地名、数字、动作）就是事实依据，可以也应该原文照引——这正是分析的核心**。"
            "只在 transcript 没写到的内容上保持保守，不要凭空编造。"
        )
        user_prompt = _build_prompt(task_type, payload, expect_json=expect_json)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if expect_json:
            schema = _strict_schema_for(task_type)
            if schema is not None:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": task_type.replace("-", "_"),
                        "strict": True,
                        "schema": schema,
                    },
                }
            else:
                kwargs["response_format"] = {"type": "json_object"}
        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise RuntimeError(f"OpenAI generation failed for task '{task_type}': {exc}") from exc

        text = response.choices[0].message.content or ""
        usage_obj = getattr(response, "usage", None)
        usage = {
            "input_tokens": int(getattr(usage_obj, "prompt_tokens", 0) or 0),
            "output_tokens": int(getattr(usage_obj, "completion_tokens", 0) or 0),
        }
        return text, usage

    def _mock_content(self, task_type: str, payload: dict[str, Any]) -> dict[str, Any] | str:
        if task_type == "analysis":
            return {
                "content_type": "ai_business_model_observation",
                "content_positioning": "海外 AI 商业机会、AI 工具/CLI/开源项目解读与中文叙事视频资产",
                "core_topic": "AI agents reduce the cost of research and drafting",
                "summary": "The source argues that AI agents help content teams move faster, but human review remains critical.",
                "why_now": "AI agent 工具正在从演示走向具体工作流，海外团队开始把它放进研究、整理和初稿环节。",
                "china_gap": "中文内容常把它讲成泛 AI 生产力，需要补充海外语境、适用边界和事实依据。",
                "narrative_value": "适合拆成为什么火、海外团队怎么用、它解决什么问题和中文创作者能学到什么。",
                "business_insight": "启发在于内容团队如何重组流程，而不是承诺确定结果。",
                "main_points": [
                    "Research and first drafts can be automated.",
                    "Editorial judgment still decides whether a topic is worth publishing.",
                    "Fact checking and audience adaptation are required before release.",
                ],
                "interesting_angles": ["AI content production is an editorial workflow, not just a video factory."],
                "domestic_value": 8,
                "commercial_value": 7,
                "short_video_suitability": 8,
                "content_formats": ["ai_business_model_observation", "short_video_script", "knowledge_card"],
                "opportunity_dimensions": {
                    "why_now": 8,
                    "problem_intensity": 7,
                    "china_gap": 8,
                    "narrative_value": 8,
                    "video_potential": 8,
                    "business_insight": 7,
                    "audience_fit": 8,
                    "evidence_completeness": 6,
                    "risk_control": 7,
                },
                "facts_to_check": ["Specific productivity claims need source verification."],
                "risk_points": ["May sound like generic AI productivity advice without concrete examples."],
            }
        if task_type == "risk":
            return {
                "pass": True,
                "risk_level": "low",
                "copyright_risk": 2,
                "factual_risk": 3,
                "platform_risk": 2,
                "issues": ["Avoid implying guaranteed income or productivity results."],
                "must_fix": ["Mark unverified numeric claims as pending verification."],
                "must_review": True,
            }
        if task_type == "rewrite":
            return {
                "script": (
                    "# 标题\n\nAI 内容生产真正改变的不是视频，而是选题和初稿\n\n"
                    "# 口播稿\n\n"
                    "## 为什么突然值得关注\n\n"
                    "如果你以为 AI 内容生产就是自动剪视频，那很容易做成低质模板号。\n\n"
                    "真正值得关注的变化，是海外团队开始把 AI agent 放进研究、整理和初稿环节。"
                    "一个小团队可以更快看完海外资料，提炼观点，再判断它对中文用户有没有价值。\n\n"
                    "## 海外发生了什么\n\n"
                    "但这里最关键的不是自动化，而是审核。选题值不值得做、事实有没有依据、"
                    "表达像不像中文原创，这些都需要人工把关。\n\n"
                    "## 它解决什么问题\n\n"
                    "它解决的是资料处理和初稿组织的问题，不是替人完成判断。\n\n"
                    "## 对中文用户/开发者/创作者/创业者的启发\n\n"
                    "第一阶段最该验证的不是能不能一键生成视频，而是能不能稳定产出可审核的中文脚本。\n\n"
                    "## 边界：不承诺收益、不夸大、不照搬\n\n"
                    "这只是海外 AI 工作流观察，具体效果要看团队能力、来源质量和审核标准。\n\n"
                    "# 分镜建议\n\n"
                    "1. 标题页：AI 内容生产的真正变化\n"
                    "2. 对比页：自动剪视频 vs 研究和初稿降本\n"
                    "3. 流程页：海外链接 -> 转写 -> 分析 -> 风控 -> 中文脚本\n\n"
                    "# 屏幕文字\n\n"
                    "- 不做低质搬运\n"
                    "- 先验证脚本质量\n"
                    "- 人工审核后再发布\n\n"
                    "# 风险点\n\n"
                    "- 不使用原视频画面作为发布素材\n"
                    "- 不承诺结果或效率提升\n\n"
                    "# 待核查内容\n\n"
                    "- 任何具体效率提升数字都需要补充来源\n"
                ),
                "titles": [
                    "AI 内容生产，真正该自动化的是哪一步？",
                    "别急着自动剪视频，先把中文脚本做对",
                    "海外内容重构成中文脚本的正确打开方式",
                ],
            }
        if task_type == "quality":
            return {
                "pass": True,
                "quality_score": 82,
                "issues": ["示例稿仍需要补充真实案例。"],
                "fix_suggestions": ["发布前加入一个已核查的行业案例。"],
                "ready_for_human_review": True,
            }
        if task_type == "flow_steps":
            # Mock returns an empty list so tests / dry-runs fall through
            # to the heuristic extractor (or the typography fallback) —
            # we never want a mock ``flow_steps`` to accidentally polute
            # a render with stub data ("Step 1 mock").
            return {"steps": []}
        if task_type == "github_analysis":
            meta = payload.get("github_meta", {})
            repo_name = meta.get("full_name") or meta.get("title") or "mock/repo"
            return {
                "content_type": "github_open_source_project",
                "content_positioning": "海外 AI 工具/CLI/开源项目解读与中文叙事视频资产",
                "core_topic": f"{repo_name} 是一个值得观察的 AI 开源项目",
                "summary": "该项目围绕 AI agent / developer workflow 展开，README 展示了清晰的使用场景和较强的中文解读价值。",
                "why_now": "海外开发者正在集中讨论 AI agent 如何进入真实开发工作流，开源项目能提供可核查的一手材料。",
                "china_gap": "中文用户需要把 README、release、license 和维护状态拆成可理解的项目观察。",
                "narrative_value": "适合讲清项目为什么火、开发者为什么关注、解决什么问题和发布前要核查什么。",
                "business_insight": "可观察开发者需求和工具生态位置，但 star 数不代表商业成功。",
                "project_positioning": "面向开发者的 AI 工具或框架，可作为海外开源趋势观察案例。",
                "main_points": [
                    "项目热度可以通过 stars、forks、issues 与 release 节奏综合判断。",
                    "README 中的功能描述适合转成中文用户能理解的应用场景。",
                    "发布前需要区分官方已实现能力和社区讨论中的预期能力。",
                ],
                "audience_value": "适合给中文 AI 开发者解释项目解决什么问题、为什么最近值得关注、是否值得试用。",
                "domestic_value": 8,
                "commercial_value": 7,
                "short_video_suitability": 8,
                "content_formats": ["github_open_source_project", "ai_cli_agent", "short_video_script", "technical_card"],
                "opportunity_dimensions": {
                    "why_now": 8,
                    "problem_intensity": 7,
                    "china_gap": 8,
                    "narrative_value": 8,
                    "video_potential": 8,
                    "business_insight": 7,
                    "audience_fit": 8,
                    "evidence_completeness": 8,
                    "risk_control": 7,
                },
                "facts_to_check": ["stars/forks 是否为抓取时最新值", "README 功能是否对应当前 release", "许可证与商用限制"],
                "risk_points": ["不要把项目热度等同于生产可用性。", "避免夸大未发布功能。"],
            }
        if task_type == "youtube_candidate_analysis":
            meta = payload.get("meta", {})
            title = meta.get("title") or "YouTube 候选视频"
            stats = meta.get("stats", {}) if isinstance(meta.get("stats"), dict) else {}
            transcript = payload.get("transcript", {}) if isinstance(payload.get("transcript"), dict) else {}
            has_transcript = bool(str(transcript.get("full_text") or "").strip())
            transcript_language = str(transcript.get("language") or "")
            is_english = transcript_language in {"", "en", "en-US", "en-GB"}
            basis = "transcript" if has_transcript and is_english else "transcript_any_language" if has_transcript else "metadata_only"
            confidence = "higher_transcript_based" if has_transcript else "low_metadata_only"
            return {
                "content_type": "overseas_info_gap_story",
                "content_positioning": "海外 AI 商业机会与工具观察的中文叙事视频资产",
                "core_topic": f"{title} 的可中文化解读价值",
                "summary": (
                    f"该候选已优先使用 YouTube 字幕文本生成初步解读，字幕语言为 {transcript_language or 'unknown'}。"
                    "系统会把可用语言字幕作为事实依据，再重构成中文解读。"
                    if has_transcript
                    else "该候选没有可用 YouTube 字幕，只使用标题、简介和互动数据生成初步解读，事实完整性较低，具体观点需人工复核。"
                ),
                "why_now": "该候选提供了近期海外 AI 工具、开发者工作流或创业讨论的观察入口。",
                "china_gap": "中文脚本需要把字幕或元数据中的信息转成来源清楚、边界明确的中文解读。",
                "narrative_value": "适合围绕为什么火、海外发生了什么和中文用户应该如何理解来组织。",
                "business_insight": "可用于观察海外产品和创作者如何定义问题，但不能替代事实核查。",
                "main_points": [
                    "任意可用语言的字幕文本是本次分析的主要依据。" if has_transcript else "标题和简介显示这是一个可转成中文短视频的海外 AI / creator 话题。",
                    f"当前可见互动数据：views={stats.get('views', 0)}, likes={stats.get('likes', 0)}, comments={stats.get('comments', 0)}。",
                    "脚本应标明来源为 YouTube 字幕，并继续核查关键事实。" if has_transcript else "由于没有字幕，脚本应采用“元数据解读 + 待核查提醒”的保守表达。",
                ],
                "interesting_angles": ["用海外视频元数据先筛选选题，再决定是否人工补充原片事实。"],
                "domestic_value": 7,
                "commercial_value": 6,
                "short_video_suitability": 8,
                "content_formats": ["overseas_info_gap_story", "short_video_script", "topic_review_card"],
                "opportunity_dimensions": {
                    "why_now": 7,
                    "problem_intensity": 6,
                    "china_gap": 7,
                    "narrative_value": 8,
                    "video_potential": 8,
                    "business_insight": 6,
                    "audience_fit": 7,
                    "evidence_completeness": 8 if has_transcript else 4,
                    "risk_control": 7 if has_transcript else 5,
                },
                "facts_to_check": (
                    ["字幕中的关键工具、案例和数字是否能找到外部来源", "非中文/英文字幕的翻译理解是否准确", "发布时间和频道背景"]
                    if has_transcript
                    else ["原视频具体论点", "简介中提到的工具或案例是否真实", "发布时间和频道背景"]
                ),
                "risk_points": [
                    "不要使用原视频音频或画面作为发布素材。",
                    "字幕可能自动生成或不完整，关键事实仍需复核。" if has_transcript else "不能把标题和简介推断成完整视频内容。",
                ],
                "analysis_basis": basis,
                "transcript_status": payload.get("transcript_status", {}),
                "factual_confidence": confidence,
            }
        if task_type == "github_rewrite":
            meta = payload.get("github_meta", {})
            analysis = payload.get("github_analysis", {})
            repo_name = meta.get("full_name") or meta.get("title") or "这个 AI 项目"
            return {
                "script": (
                    f"# 标题\n\n{repo_name}：一个值得关注的海外 AI 开源项目\n\n"
                    "# 口播稿\n\n"
                    "## 为什么突然值得关注\n\n"
                    f"今天看一个 GitHub 上的 AI 项目：{repo_name}。\n\n"
                    f"它的核心看点是：{analysis.get('project_positioning', '把 AI 能力嵌入开发者工作流')}。\n\n"
                    "## 海外发生了什么\n\n"
                    "判断一个项目值不值得关注，不能只看 star 数。更重要的是 README 是否讲清楚真实场景、"
                    "issue 和 release 是否还在更新，以及它解决的问题是不是中文开发者也会遇到。\n\n"
                    "## 它解决什么问题\n\n"
                    "这个项目适合做成中文解读的原因，是它能帮助我们观察海外 AI 工具链正在往哪里走。\n\n"
                    "## 对中文用户/开发者/创作者/创业者的启发\n\n"
                    "中文开发者可以借它观察工具链变化、API 设计和开源生态，而不是只追逐热度。\n\n"
                    "## 边界：不承诺收益、不夸大、不照搬\n\n"
                    "但发布前要核查版本、许可证和官方文档，避免把演示能力讲成稳定能力。\n\n"
                    "# 分镜建议\n\n"
                    "1. 仓库首页：项目名、star、主要语言\n"
                    "2. README 截图：核心功能和典型用法\n"
                    "3. 对比页：它解决的问题 vs 现有方案\n\n"
                    "# 屏幕文字\n\n"
                    "- 先看解决什么问题\n"
                    "- 再看热度和维护状态\n"
                    "- 最后核查 license / release\n\n"
                    "# 风险点\n\n"
                    "- 不把 star 数解读成商业成功\n"
                    "- 不承诺项目稳定可用于生产\n\n"
                    "# 待核查内容\n\n"
                    "- README 功能是否与最新 release 一致\n"
                    "- license 是否允许目标使用方式\n"
                ),
                "titles": [
                    f"{repo_name} 为什么突然值得关注？",
                    "别只看 star，解读 AI 开源项目要看这三点",
                    f"一个 GitHub AI 项目，中文开发者该怎么看？",
                ],
            }
        return {"status": "mocked", "task_type": task_type}


def _build_prompt(task_type: str, payload: dict[str, Any], *, expect_json: bool) -> str:
    json_instruction = "Return only valid JSON." if expect_json else "Return markdown."
    schema_hints = {
        "analysis": (
            "Analyze overseas AI business opportunities, AI tools/CLI/open-source projects, indie creator portraits, "
            "and Chinese narrative video asset potential. "
            "Include content_type using one of: ai_tool_explainer, ai_cli_agent, github_open_source_project, "
            "overseas_ai_startup_case, product_hunt_new_product, ai_business_model_observation, "
            "overseas_info_gap_story, creator_portrait. "
            "Use creator_portrait when the source is centered on a single indie creator / solo founder / individual "
            "(e.g. Pieter Levels, Greg Isenberg, Rob Walling) and the narrative is about the *person's* projects, "
            "trajectory, or build-in-public signals — not about a specific tool/repo. "
            "Also include core_topic, summary, why_now, china_gap, narrative_value, business_insight, main_points, "
            "interesting_angles, domestic_value, commercial_value, short_video_suitability, content_formats, "
            "opportunity_dimensions, facts_to_check, risk_points. Do not promise income or provide gray-market paths."
        ),
        "risk": "Include pass, risk_level, copyright_risk, factual_risk, platform_risk, issues, must_fix, must_review.",
        "rewrite": (
            "你在写一条**纯叙事**的中文短视频口播稿，目的是把 analysis.key_moments 里的真实场景"
            "讲成一个让人想看完的故事。**这不是分析报告，不是行业评论，不是给中国市场提建议**——"
            "你只负责讲故事 + 一点点态度，让观众自己有感受。\n\n"
            "【风格定位】\n"
            "- 口语：跟朋友讲，不要书面语。'这玩意'、'离谱'、'狠'、'真的假的'都可以用，"
            "  '具有重要意义'、'引发广泛关注'、'值得我们深入思考'一律不许。\n"
            "- **可以夸张但要客观**：修辞放飞（'这玩意把这哥们整段操作都接管了'、'这操作太狠了'），"
            "  但事实数字 / 人名 / 动作必须能在 key_moments 里找到原文。"
            "  夸的是修辞，不是把'几分钟'编成'30 秒'。\n"
            "- 注意力窗口 < 3 秒——开头必须扣住人，不要铺垫。\n\n"
            "【风控红线 — 抖音 / B 站审核会盯的，必须避开】\n"
            "- 不做中国 vs 海外的对比、对立、暗示落后或追赶。**完全不写'中国'、'国内'、'国外'比较，"
            "  也不写'这给我们的启示'、'值得我们学习'**。讲的是这条 key_moments 里**当事主角**的故事，"
            "  跟群体、地区、国家无关。\n"
            "- 不涉及政治、地缘、民族、宗教、性别、收入差距、对立群体。\n"
            "- 不承诺收益、不暗示'你也能这样赚钱'、不写'抓住风口'之类创业鸡汤。\n"
            "- 不引导用户开放自己电脑权限给 AI（避免被解读为安全风险鼓励）。\n"
            "- 不写'颠覆 / 取代 / 干掉 XX 行业 / 让 XX 失业'这种激化矛盾的判断。\n"
            "- '可以夸张'指对单个 AI 动作的描绘（'离谱'、'神操作'），不是对人群、行业、国家。\n\n"
            "【硬性要求】\n"
            "1. 开头第 1 句必须直接进 analysis.key_moments[0] 或 [1] 里的**具体场景 + 主角名 + 动作**，"
            "  不许用'随着/近期/最近/在如今/在数字化时代'开头。**主角名以 key_moments 原文为准**——"
            "  如果是 Peter 就写 Peter，如果是 OpenAI / Anthropic / 项目作者就用对应名字，"
            "  绝对**不要把上一条视频的主角名带进来**。\n"
            "2. 整篇口播至少引用 3 条 key_moments 的具体事实，保留人名、地名、数字、产品名不改写。\n"
            "3. 口播总字数 800-1200 中文字，对应 2 分 30 秒到 3 分 30 秒。每个 ## 小节 150-260 字，"
            "  '## 故事是怎么发生的' 和 '## 它到底怎么做到的' 这两节最长。\n"
            "4. **句子长度控制**：每句不超过 35 个中文字，长句必须拆成 2-3 个短句，便于切字幕。"
            "  完整句号之间最好不超过 25-30 字。\n"
            "5. **保留所有产品名 / 项目名 / 工具名原文**：例如 npm、Git、CLI、API、SDK、Docker、"
            "  以及 key_moments 里实际出现的具体产品名（如 Cursor、Claude、Codex、Aider 等等），"
            "  一律不要翻译成普通名词（'代码库' / '网盘' / '密码管理器' 都不许）。\n"
            "6. 引用 key_moments 时讲完整动作链——至少包含（a）当时主角在做什么大事，"
            "  （b）AI / 工具 / 项目执行了哪几步，（c）结果是什么。**动作链里的所有人名 / 地名 / "
            "  产品名必须从当前 key_moments 里取，禁止从历史训练数据里脑补一个故事**。\n\n"
            "【事实硬约束】\n"
            "- 不许把视频标题里的数字（如 'in 40 Minutes'）改写成片中具体动作的时长。\n"
            "- 任何百分比 / 金额 / 用户数 / 时长都要在 analysis.key_moments 里找得到原文。\n"
            "- 不确定的数字宁可写'很快' / '几分钟' / '一小段时间'，不要编。\n"
            "- **如果当前 key_moments 里没有 Peter / 摩洛哥 / Dropbox / 1Password / Philips Hue 这些"
            "  词，就一个都不许出现在你的口播里**。这些词是历史样本里的，**不是这条候选的**。\n\n"
            "【禁用词库 — 出现即不合格】\n"
            "- '随着 AI 技术的快速发展' / 'AI 正在改变生活' / '广泛应用' / '潜力巨大' / '市场空间广阔'\n"
            "- '中国 / 国内 / 国外' 的对比句、'对中国用户的启示' / '值得我们借鉴' / '推动行业发展'\n"
            "- '具有重要意义' / '引发广泛关注' / '值得我们深入思考' / '展现了无限可能'\n"
            "- '颠覆' / '取代' / '干掉' XX 行业、XX 群体的论断\n\n"
            "【输出格式】\n"
            "返回 JSON，字段 script 和 titles。\n"
            "- script 必须是 **Markdown 字符串**（不是对象！不是 Python dict 的 str 化！），"
            "  严格包含以下顺序的一级/二级标题（注意：**没有'对中文用户启发'和'边界声明'两节了，删掉了**）：\n"
            "  # 标题\n"
            "  # 口播稿\n"
            "    ## 钩子\n"
            "    ## 故事是怎么发生的\n"
            "    ## 它到底怎么做到的\n"
            "    ## 它还能干什么\n"
            "    ## 一点感慨\n"
            "  # 分镜建议\n"
            "  # 屏幕文字\n"
            "  # 风险点\n"
            "  # 待核查内容\n"
            "  每个 ## 小节 150-260 字。\n"
            "  - '## 钩子' 用 1-2 个最反常识 / 最有画面感的真实场景把人钩住，不解释、不铺垫。\n"
            "  - '## 故事是怎么发生的' 把主角是谁、当时在哪、发生了什么完整讲清，多个动作链按时间顺序串联。\n"
            "  - '## 它到底怎么做到的' 拆解 AI 的执行机制（开浏览器 / 访问文件系统 / 调 API / 控制硬件），不抽象成'AI 强大'。\n"
            "  - '## 它还能干什么' 把其他 key_moments 里的场景列出来（智能家居、密码管理、健康追踪等）。\n"
            "  - '## 一点感慨' 收尾——可以有自己的感叹、可以放个反差句、可以问观众一句"
            "  ('你会让 AI 接管你电脑吗？')，但**不要说教、不要给中国市场提建议、不要承诺未来**。\n"
            "- titles 是 3-5 个中文短标题，每个带具体钩子（数字 / 反常识 / 疑问句），不要标题党到失实。\n\n"
            "**再次强调：script 的 value 类型是 str（markdown），不是 dict。**"
        ),
        "quality": "Include pass, quality_score, issues, fix_suggestions, ready_for_human_review.",
        "flow_steps": (
            "你正在为一个中文短视频生成**信息图模板的步骤标签**。这是后期渲染时用的"
            "「STEP 1 / STEP 2 / STEP 3」流程图节点文本，不是口播。\n\n"
            "【输入】\n"
            "- voiceover：当前 mechanism 场景的中文口播稿（讲 AI 工具/项目是怎么做到的）。\n"
            "- subtitle_keywords：从口播里抽出的实词（人名、产品名、工具名）。\n\n"
            "【任务】\n"
            "从 voiceover 里抽出 **3 到 5 个具体动作步骤**，每步是一个独立的"
            "动作短语（动词 + 具体对象），按 voiceover 里出现的时间顺序排列，"
            "用最少的字讲清「AI 干了哪几件事」。\n\n"
            "【硬性约束】\n"
            "1. 每步**必须 ≤ 12 个字符**（中文字 1 个字符，英文/数字按字符数）。\n"
            "2. 每步**必须包含一个具体名词**：产品名（WhatsApp / Git / Dropbox / "
            "   Twitter / Philips / Sonos / GitHub / Slack 等）、文件类型（推文 / "
            "   邮件 / 日历 / 护照 / 代码 / bug / 仓库）、或工具/界面（浏览器 / "
            "   终端 / API / URL）。**不要写「AI 处理信息」「实现自动化」这种没具体对象的抽象判断**。\n"
            "3. 每步**必须包含一个动作动词**（识别 / 访问 / 提取 / 上传 / 修复 / "
            "   提交 / 回复 / 启动 / 控制 / 打开 / 拍 / 拽 / 填 / 发送 / 唤醒）。\n"
            "4. 严格按 voiceover 实际写到的事实——**不要从训练数据补步骤**。\n"
            "   如果 voiceover 没提某个工具，**绝对不要**把它写进 steps 里。\n"
            "5. 一段口播提供的素材如果不足 3 个干净步骤，**返回空数组 []**——"
            "   宁可 fallback 到默认模板，也不要凑数。\n\n"
            "【正确示例】（仅展示格式，不要复用其中名词）\n"
            "  voiceover 提到了 WhatsApp / Git / Twitter →\n"
            "  ✅ ['拍照传 WhatsApp', 'AI 识别 bug', '提交 Git 修复', 'Twitter 回复']\n\n"
            "【错误示例】\n"
            "  ❌ ['AI 处理任务', '智能完成', '高效工作']  ← 抽象 / 没具体名词\n"
            "  ❌ ['Peter 看到 bug 之后立刻让 AI 帮忙修复并提交']  ← 太长且不是步骤\n"
            "  ❌ ['1Password 密码', 'Dropbox 文件']  ← voiceover 没提就编出来的工具\n\n"
            "【输出】JSON 对象，字段 steps，类型 array of string。"
        ),
        "github_analysis": (
            "你正在为中文观众制作“海外 AI 工具/CLI/开源项目解读”，不是泛 AI 视频或赚钱教程。请基于 GitHub metadata、README 和图片/截图状态，"
            "输出中文 JSON，字段包括 content_type, content_positioning, core_topic, summary, why_now, project_positioning, main_points, audience_value, "
            "china_gap, narrative_value, business_insight, opportunity_dimensions, domestic_value, commercial_value, short_video_suitability, content_formats, facts_to_check, risk_points. "
            "明确区分已从仓库资料确认的信息和仍需人工核查的信息，不把 star 或演示能力夸大成商业结果。"
        ),
        "youtube_candidate_analysis": (
            "你在为中文短视频账号分析一条海外 YouTube 视频，要把它变成抖音/B 站可看的'海外 AI 信号解读'。\n"
            "**所有字段的 value 必须用简体中文**（key_moments.original_quote 例外，那里保留原语言）。\n\n"
            "【输入】transcript.transcript_lines 是原视频逐句字幕，每行格式 `[Ns] text`，N 是该段落开始的秒数。"
            "优先以这些字幕为事实源头；transcript 空才退回 title/description/stats/channel，analysis_basis 标 metadata_only。\n\n"
            "【第一步 — 必须先做，不允许跳过】\n"
            "**仔细阅读 transcript_lines 的每一行**，从中挑出 4-6 个**完整故事场景**，填入 key_moments 数组。"
            "key_moments 数组**绝不能为空**，否则整个分析失败。\n\n"
            "每个 key_moment 是一个**完整动作链**，不是孤立一句。每条必须包含：\n"
            "  - timestamp_seconds: 该动作链开始时的 `[Ns]` 数字\n"
            "  - original_quote: **把这个动作链涉及的连续 2-6 行 transcript 拼起来**（用空格连接），"
            "保留所有动作步骤、地点、产品名、数字。**不要只抽 1 行就交差**——孤立一句话失去上下文，"
            "中文观众根本听不懂。如果 transcript 里说 'find my passport in my file system'，**必须**把"
            "前后讲'要去航司网站办值机'和'最后真的把值机办成了'的连续行也一起拼进来，否则光看一行只会困惑"
            "'电脑里怎么会有护照'。\n"
            "  - chinese_translation: **不是逐字翻译，是讲给一个不懂英语的中文观众听的故事**。\n"
            "    必须包含：（a）当时**当前候选视频里的主角**在做什么大场景（值机？修 bug？记账？做项目？）；"
            "（b）AI / 工具 / 项目具体执行了哪几步动作；（c）保留所有产品名 / 项目名（视频里实际出现的，"
            "如 npm、Git、API、Cursor、Claude、Codex 等等）和地名。**绝对不要把产品名翻译成普通名词**"
            "（如 Git 不能写成'代码库'，npm 不能写成'包管理器'）。\n"
            "  - why_it_matters: 一句话说明为什么这条能抓中国观众（具体场景/反常识/强冲突）\n\n"
            "【方法论示例 — 不是要复用其中的人名地名】\n"
            "假设 transcript 段是：`[T1] X 在做某个大场景，是个终极考验 [T2] 它实际上需要先做某个琐碎前置 "
            "[T3] 它最后通过某个具体动作链解决了`。\n"
            "❌ 错的抽法（孤立单行 + 字面翻译）：\n"
            "  只抽 [T2] 那一行，把英文字面机翻成中文。中文观众一脸懵：为什么要做这个琐碎前置？\n"
            "✅ 对的抽法（完整场景 + 故事化翻译）：\n"
            "  把 [T1][T2][T3] 拼成一段 original_quote；chinese_translation 还原成"
            "'<视频里的主角> 在做 <大场景>——它自己 <具体动作 1>，<具体动作 2>，最后 <结果>'。\n"
            "**关键：把示例里 ``X / <主角> / <大场景>`` 这些占位符替换成 transcript 里**实际出现**的人名、"
            "地名、产品名。绝对不许把训练数据里别的视频的主角名（如 Peter / 摩洛哥 / Dropbox / 1Password / "
            "Philips Hue）带到这条候选里——这些词除非 transcript 自己出现，否则一个都不能写。\n\n"
            "【第二步 — 其他字段全部基于 key_moments 写】\n"
            "summary（中文，2-3 句）：必须引用至少 1 条 key_moments 的具体事实（人名+场景+数字）。\n"
            "why_now / china_gap / business_insight：每个字段都要在中文表达里至少嵌入 1 个 key_moments 的具体细节。\n"
            "main_points（中文数组，3-5 条）：每条都必须能在 key_moments 里找到依据，"
            "但**输出文本本身不要包含 '(对应 key_moments[N])' 之类内部对齐标注**——这是给观众看的成片文案，"
            "标注会原样出现在标题/简介里，看起来像 bug。对齐关系只在内部保证。\n"
            "hashtag_keywords（中文数组，4-6 条）：给抖音/B 站/小红书做 hashtag 用的简短关键词，每条 ≤6 字，"
            "**只输出关键词本身，不要带 # 号、不要写完整短语**。例：✅['AI自动化','个人生产力','海外AI','开发者工具']；"
            "❌['AI在个人生活自动化中的应用','#AI工具']。优先包含 1 个**当前候选**的核心人物或产品名（从 transcript 里取）。\n"
            "facts_to_check（中文数组）：列 key_moments 里可能误译或需补证的具体点。\n\n"
            "【禁用词库 — 一律不得出现】\n"
            "- '随着 AI 技术的快速发展' / 'AI 技术日益成熟' / '广阔的市场前景' / '未来前景广阔'\n"
            "- '中国在 ... 起步阶段' / '政策和市场的双重促进' / '市场空间广阔'\n"
            "- 'transcript 里没出现过的关于中国 / 政策 / 市场的论断'\n"
            "- '值得关注其潜力与风险' / '具有重要意义' / '引发广泛讨论' 这类无信息套话\n\n"
            "【事实约束 — 区分'真金句'和'捏造'】\n"
            "✅ 鼓励引用：transcript 原文里**已经出现过的**任何具体人、地、事、数字、产品名（这些是视频的灵魂，必须保留）。\n"
            "❌ 禁止编造：transcript 里**没出现过的**具体动作时长 / 完成时间 / 数量。\n"
            "⚠️ 视频标题里的数字（如 'Run His Life in 40 Minutes' 中的 40）**通常**指视频时长 / 采访时长，"
            "**不要**把它误读成片中说话者完成某动作的耗时。如不确定，干脆不引用这个数字。\n"
            "✅ 当不确定具体数字时，写'很快'、'几分钟'、'一段时间'等模糊表达，宁可保守也不编造。\n\n"
            "【输出】中文 JSON 对象，字段：content_type, content_positioning, core_topic, summary, why_now, china_gap, narrative_value, business_insight, "
            "key_moments, main_points, hashtag_keywords, interesting_angles, opportunity_dimensions, domestic_value, commercial_value, short_video_suitability, content_formats, "
            "facts_to_check, risk_points, analysis_basis, transcript_status, factual_confidence。\n"
            "value 必须是 str/array/number/object，**禁止**把对象 str() 成字面量字符串。"
        ),
        "github_rewrite": (
            "你在写一条**讲述者口吻**的中文短视频口播稿，介绍一个海外 GitHub 开源项目。"
            "**这不是 PR description、不是技术博客、不是 README 翻译**——你像跟朋友讲一个你"
            "刚刷到的项目，让对方 3 秒内被钩住、3 分钟内听完、听完之后想去搜一下。\n\n"
            "【风格定位 — 这是这条 prompt 的灵魂，违反就重写】\n"
            "- **口语**：句子像说话，不像写字。'有意思的是'、'离谱的是'、'你猜怎么着'、'对，就是这样'、"
            "  '说白了'、'这事说穿了'、'真的'都可以用。**'传统的 X 工具需要开发者手动…'、"
            "  '它的核心定位写在 README 里…'、'README 中提到了…'、'这个项目揭示了…'、'项目方自己做了…' "
            "  这种书面引用腔一律不许出现**。\n"
            "- **短句**：单句不超过 30 个中文字，能拆就拆。'这个项目用 Python 写、基于 Playwright 构建、"
            "  支持对接多种主流大模型' 这种顿号串句必须拆成 3 句。\n"
            "- **反差和钩子**：每个 ## 小节开头第一句必须是反差 / 数字 / 反问 / 具体动作之一，"
            "  不许用'让我们来看看…'、'接下来我们看…'、'值得注意的是…'起句。\n"
            "- **保留所有产品名 / 项目名 / 工具名 / 命令行原文**：例如 Python、Playwright、LLM、API、"
            "  pip install、GitHub、Star、Fork、CLI、SDK，以及 github_meta 里实际出现的项目名、"
            "  README 里实际出现的工具链名（不要把 Playwright 翻译成'测试框架'，不要把 LLM 翻译成"
            "  '大语言模型'再翻一次，凡是英文短词原文保留）。\n\n"
            "【风控红线 — 抖音 / B 站审核会盯的，必须避开】\n"
            "- 不写'中国 vs 海外'对比、不写'值得我们学习 / 借鉴 / 反思'、不写'国内还在 / 国外已经'、"
            "  不写'这给我们的启示'。这条片讲的是**项目本身**，不是给中国市场提建议。\n"
            "- 不承诺收益。不写'你也能靠这个赚钱'、'抓住风口'、'下一个独角兽'、'月入 X 万'。\n"
            "- 不夸大成熟度。Star 多 ≠ 生产可用，必须在'## 一点感慨'之前留一句保留。\n"
            "- 不写'颠覆 / 取代 / 干掉 XX 行业 / 让 XX 失业'。\n"
            "- 不涉及政治、地缘、民族、宗教、性别、对立群体。\n\n"
            "【硬性事实约束】\n"
            "1. 数字（star 数、fork 数、版本号、发布日期）必须以 github_meta 字段为准，"
            "  **绝对不要从训练数据里脑补**。如果 github_meta 没给具体数字，写'好几万'、'最近'，不要编。\n"
            "2. 项目名、作者 / 团队名、技术栈名以 github_meta 和 github_analysis 为准。"
            "  README 里没写的工具不要硬塞进口播。\n"
            "3. 应用场景（## 它还能干什么）只能列 github_analysis.main_points 或 README 实际提到的"
            "  场景，不要补一些训练数据里别的项目的功能。\n"
            "4. 把数字读成口语：92,631 → '9 万 2 千 star'，'10,496 forks' → '一万多 fork'，"
            "  '0.12.6 (2026-04)' → '上个月还在更新'，不要直接把 ASCII 数字喊出来。\n\n"
            "【禁用词库 — 出现即不合格】\n"
            "- '随着 AI 技术的快速发展' / 'AI 正在改变…' / '潜力巨大' / '广阔的市场前景' / "
            "  '具有重要意义' / '引发广泛关注' / '值得我们深入思考' / '展现了无限可能'\n"
            "- 'README 中提到了' / 'README 中展示了' / '项目方自己做了' / '官方表示' / "
            "  '该项目揭示了…机会' / '这是项目潜在的商业化方向之一'（书面引用腔）\n"
            "- '中国 / 国内 / 国外' 对比 / '对中国用户的启示' / '推动行业发展'\n"
            "- '颠覆 / 取代 / 干掉' XX 行业、XX 群体的论断\n\n"
            "【输出格式】\n"
            "返回 JSON，字段 script（markdown 字符串） 和 titles（数组）。\n"
            "**script 必须是 str，不是 dict**。**禁止**用 ## 为什么突然值得关注 / ## 海外发生了什么 / "
            "## 它解决什么问题 / ## 对中文用户/开发者/创作者/创业者的启发 / ## 边界 这套旧 heading"
            "（这套是分析报告腔，已废）。**必须**用以下叙事结构：\n"
            "  # 标题\n"
            "  # 口播稿\n"
            "    ## 钩子\n"
            "    ## 故事是怎么发生的\n"
            "    ## 它到底怎么做到的\n"
            "    ## 它还能干什么\n"
            "    ## 一点感慨\n"
            "  # 分镜建议\n"
            "  # 屏幕文字\n"
            "  # 风险点\n"
            "  # 待核查内容\n\n"
            "每个 ## 小节 150-260 中文字，全文 800-1200 字（约 3 分钟）。各小节要点：\n"
            "- '## 钩子'（80-160 字）：1-2 句话扔出最反常识的事实——通常是数字（'9 万 2 千 star'）"
            "  + 一句反问或反差（'你跟它说话，它真的去用浏览器'）。**不解释、不铺垫、不报项目名介绍**。\n"
            "- '## 故事是怎么发生的'（150-220 字）：项目什么时候上线、谁做的、起飞速度大概是什么概念。"
            "  这一段的事实必须从 github_meta（published_at / stars / forks / topics）里取。\n"
            "- '## 它到底怎么做到的'（200-260 字）：拆机制——AI 收到自然语言任务，怎么转化成"
            "  浏览器操作？基于哪个底层（Playwright）？跟传统脚本的区别在哪（**用对比但不用'传统的 X 工具'**"
            "  这种引用腔，改成'以前你要写脚本一步一步点；现在你说话它去点'）？\n"
            "- '## 它还能干什么'（150-220 字）：把 main_points 里的应用场景串成画面感强的句子。"
            "  '帮你比价机票'、'自动填表单'、'监控网页变化'，每个场景一句。\n"
            "- '## 一点感慨'（80-160 字）：留一个反差句或开放问题（'你会让 AI 替你打开浏览器吗？'）。"
            "  顺手提一句保留意见（'star 高不等于稳定，复杂任务还是会翻车'），但**不要写'对中国市场的建议'、"
            "  '值得我们学习'、'未来一定会…'**。\n\n"
            "【titles 字段】\n"
            "5 个中文短标题，每个 ≤ 22 字，必须满足以下分布：\n"
            "- 至少 1 个**数字钩子型**（含具体数字 + 项目名/动作，例：'9 万 star 的项目，让 AI 自己开浏览器'）\n"
            "- 至少 1 个**反问型**（例：'AI 真的能自己点网页了？这个项目说能'）\n"
            "- 至少 1 个**反差型**（例：'一行 pip 装好，AI 替你订机票'）\n"
            "- 不要标题党到失实。不要'震惊'、'颠覆'、'取代'。\n"
            "- 不要写'…的拆解 / 解读 / 观察 / 分析'这种文章式标题。"
        ),
    }
    # Compact transcript-heavy payloads. A 40-minute YouTube transcript
    # serialised as a list of {start, end, text} JSON objects expands to
    # ~135 KB / 35K tokens; that drowns the actual instructions (which
    # end up as ~1% of the prompt) and gpt-4o-mini routinely returns an
    # English summary with an empty key_moments array. Replace
    # transcript.segments with a "[Ns] text" line-per-segment block —
    # the same information, ~64% smaller, and visually obvious to the
    # model where each timestamp lives.
    if task_type == "youtube_candidate_analysis" and isinstance(payload.get("transcript"), dict):
        payload = _compact_youtube_payload(payload)

    payload_text = json.dumps(payload, ensure_ascii=False, default=str)
    return f"Task: {task_type}\n{schema_hints.get(task_type, '')}\n{json_instruction}\nInput JSON:\n{payload_text}"


def _compact_youtube_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Collapse the bulky transcript dict into a compact timestamped
    block while preserving everything else verbatim. Keeping the rest
    untouched matters because downstream code reads channel stats,
    candidate metadata, etc. directly off the same payload."""
    transcript = payload.get("transcript") or {}
    segments = transcript.get("segments") if isinstance(transcript, dict) else None
    if not isinstance(segments, list) or not segments:
        return payload

    lines: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        try:
            start = int(float(seg.get("start") or seg.get("offset") or 0))
        except (TypeError, ValueError):
            start = 0
        lines.append(f"[{start}s] {text}")

    compact_block = "\n".join(lines)
    new_transcript = {
        "language": transcript.get("language"),
        "source": transcript.get("source"),
        "status": transcript.get("status"),
        "segment_count": len(lines),
        "transcript_lines": compact_block,
    }
    new_payload = dict(payload)
    new_payload["transcript"] = new_transcript
    return new_payload


def _parse_json_with_repair(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
    if candidate is not None:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenAI returned invalid JSON and extraction failed: {exc}") from exc
    raise RuntimeError("OpenAI returned invalid JSON and no JSON object could be extracted.")

