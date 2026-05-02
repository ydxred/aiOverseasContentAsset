from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


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

    def generate_json(self, task_type: str, payload: dict[str, Any]) -> LLMResponse:
        if self.mock or self.provider == "mock":
            content = self._mock_content(task_type, payload)
            if not isinstance(content, dict):
                raise RuntimeError(f"Mock task '{task_type}' did not return JSON")
            return LLMResponse(provider="mock", model="mock-content-asset-v1", content=content)
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

    def _openai_chat(self, task_type: str, payload: dict[str, Any], *, expect_json: bool) -> tuple[str, dict[str, int]]:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI provider.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is required for OpenAI provider.") from exc

        client = OpenAI(api_key=self.openai_api_key)
        system_prompt = (
            "You are a content asset production assistant. Return concise, production-ready output. "
            "If JSON is requested, return only valid JSON with no markdown fence."
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
            "Analyze overseas AI business opportunities, AI tools/CLI/open-source projects, and Chinese narrative video asset potential. "
            "Include content_type using one of: ai_tool_explainer, ai_cli_agent, github_open_source_project, overseas_ai_startup_case, "
            "product_hunt_new_product, ai_business_model_observation, overseas_info_gap_story. Also include core_topic, summary, why_now, "
            "china_gap, narrative_value, business_insight, main_points, interesting_angles, domestic_value, commercial_value, "
            "short_video_suitability, content_formats, opportunity_dimensions, facts_to_check, risk_points. Do not promise income or provide gray-market paths."
        ),
        "risk": "Include pass, risk_level, copyright_risk, factual_risk, platform_risk, issues, must_fix, must_review.",
        "rewrite": (
            "Write in Simplified Chinese. Return JSON with script and titles. "
            "script must be markdown with # 标题 and # 口播稿, and the voiceover must use these second-level sections: "
            "## 为什么突然值得关注, ## 海外发生了什么, ## 它解决什么问题, ## 对中文用户/开发者/创作者/创业者的启发, "
            "## 边界：不承诺收益、不夸大、不照搬. Also include # 分镜建议, # 屏幕文字, # 风险点, # 待核查内容. "
            "titles must be 3-5 Chinese options about why it is hot, overseas AI tool observation, developer attention, or AI business opportunity teardown."
        ),
        "quality": "Include pass, quality_score, issues, fix_suggestions, ready_for_human_review.",
        "github_analysis": (
            "你正在为中文观众制作“海外 AI 工具/CLI/开源项目解读”，不是泛 AI 视频或赚钱教程。请基于 GitHub metadata、README 和图片/截图状态，"
            "输出中文 JSON，字段包括 content_type, content_positioning, core_topic, summary, why_now, project_positioning, main_points, audience_value, "
            "china_gap, narrative_value, business_insight, opportunity_dimensions, domestic_value, commercial_value, short_video_suitability, content_formats, facts_to_check, risk_points. "
            "明确区分已从仓库资料确认的信息和仍需人工核查的信息，不把 star 或演示能力夸大成商业结果。"
        ),
        "youtube_candidate_analysis": (
            "你正在从 source discovery 的 YouTube 候选项生成中文选题审核包。优先使用 transcript.full_text，"
            "不论 transcript.language 是英语、阿语、西语、日语还是其他语言，都要先理解/翻译其含义，再生成中文解读；"
            "如果 transcript 为空，只能使用 title, description, stats, channel, published_at, thumbnail, url 等元数据，"
            "不能假设已经下载音频或看过完整视频。"
            "输出中文 JSON，字段包括 content_type, content_positioning, core_topic, summary, why_now, china_gap, narrative_value, business_insight, "
            "main_points, interesting_angles, opportunity_dimensions, domestic_value, commercial_value, short_video_suitability, content_formats, "
            "facts_to_check, risk_points, analysis_basis, transcript_status, factual_confidence。表达要保守，明确脚本是基于字幕还是仅基于元数据。"
        ),
        "github_rewrite": (
            "Write in Simplified Chinese for an AI project explainer. Return JSON with script and titles. "
            "script must be markdown with # 标题 and # 口播稿, and the voiceover must use these second-level sections: "
            "## 为什么突然值得关注, ## 海外发生了什么, ## 它解决什么问题, ## 对中文用户/开发者/创作者/创业者的启发, "
            "## 边界：不承诺收益、不夸大、不照搬. Also include # 分镜建议, # 屏幕文字, # 风险点, # 待核查内容. "
            "titles must be 3-5 Chinese options about why it is hot, overseas AI tool observation, developer attention, or AI business opportunity teardown. "
            "Do not exaggerate stars, production readiness, income, or business outcomes."
        ),
    }
    payload_text = json.dumps(payload, ensure_ascii=False, default=str)
    return f"Task: {task_type}\n{schema_hints.get(task_type, '')}\n{json_instruction}\nInput JSON:\n{payload_text}"


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

