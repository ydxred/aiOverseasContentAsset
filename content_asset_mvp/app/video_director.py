from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact_writer import ArtifactWriter


@dataclass(frozen=True)
class DirectorScene:
    scene_id: str
    label: str
    voiceover: str
    visual_role: str
    asset_path: str
    screen_text: str = ""
    motion: str = "slow_push"
    highlight: str = ""
    subtitle_keywords: tuple[str, ...] = ()
    start: float = 0.0
    end: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "label": self.label,
            "voiceover": self.voiceover,
            "visual_role": self.visual_role,
            "asset_path": self.asset_path,
            "screen_text": self.screen_text,
            "motion": self.motion,
            "highlight": self.highlight,
            "subtitle_keywords": list(self.subtitle_keywords),
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True)
class DirectorShot:
    shot_id: str
    scene_id: str
    visual_type: str
    duration: float
    start: float
    end: float
    screen_text: str
    asset_path: str
    motion: str
    highlight: str
    purpose: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "scene_id": self.scene_id,
            "visual_type": self.visual_type,
            "duration": self.duration,
            "start": self.start,
            "end": self.end,
            "screen_text": self.screen_text,
            "asset_path": self.asset_path,
            "motion": self.motion,
            "highlight": self.highlight,
            "purpose": self.purpose,
        }


@dataclass(frozen=True)
class DirectorPlan:
    content_id: str
    title: str
    voiceover: str
    scenes: list[DirectorScene]
    shots: list[DirectorShot]
    assets: list[dict[str, Any]]
    style: dict[str, Any]

    def with_timing(self, timed_scenes: list[DirectorScene]) -> "DirectorPlan":
        return DirectorPlan(
            content_id=self.content_id,
            title=self.title,
            voiceover=self.voiceover,
            scenes=timed_scenes,
            shots=build_shot_list_from_scenes(timed_scenes),
            assets=self.assets,
            style=self.style,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "content_id": self.content_id,
            "title": self.title,
            "voiceover": self.voiceover,
            "scenes": [scene.as_dict() for scene in self.scenes],
            "shots": [shot.as_dict() for shot in self.shots],
            "assets": self.assets,
            "style": self.style,
        }


def build_director_plan(content_id: str, script_markdown: str, writer: ArtifactWriter) -> DirectorPlan:
    meta = _read_json_if_exists(writer.output_path("github_meta.json")) or _read_json_if_exists(writer.output_path("meta.json"))
    analysis = _read_json_if_exists(writer.output_path("github_analysis.json")) or _read_json_if_exists(writer.output_path("analysis.json"))
    title = _extract_title(script_markdown) or str(meta.get("title") or analysis.get("core_topic") or content_id)
    assets = collect_visual_assets(writer)
    scene_assets = assets or [{"path": "", "role": "brand_card", "label": "品牌信息卡"}]
    scenes = _build_domestic_scenes(title, meta, analysis, scene_assets)
    voiceover = "\n".join(scene.voiceover for scene in scenes)
    return DirectorPlan(
        content_id=content_id,
        title=title,
        voiceover=voiceover,
        scenes=scenes,
        shots=[],
        assets=assets,
        style={
            "version": "video_director_v4",
            "voiceover_style": "中国短视频 AI 工具解读编导口吻：开头先给反差和情绪判断，中段讲清事实依据，结尾给趋势判断；不写硬合规腔。",
            "rendering": "v4 多镜头 shot list + 真实素材包 + 节奏化剪辑决策 + 中文主字幕 + 品牌包装",
            "edit_template": "github_tool_explainer_v4",
            "target_platforms": ["抖音", "微信视频号", "B站", "快手"],
            "deferred_platforms": ["小红书"],
        },
    )


def write_director_artifacts(writer: ArtifactWriter, plan: DirectorPlan) -> None:
    writer.write_json("director_plan.json", plan.as_dict())
    writer.write_json("shot_list.json", build_shot_list_artifact(plan))
    writer.write_json("edit_decisions.json", build_edit_decisions(plan))
    writer.write_json("visual_asset_pack.json", build_visual_asset_pack(writer, plan))
    lines = ["# 导演层口播稿", "", plan.voiceover, "", "# 分镜"]
    for scene in plan.scenes:
        lines.extend(
            [
                "",
                f"## {scene.label}",
                f"- voiceover: {scene.voiceover}",
                f"- screen_text: {scene.screen_text}",
                f"- motion: {scene.motion}",
                f"- highlight: {scene.highlight}",
                f"- visual_role: {scene.visual_role}",
                f"- asset_path: {scene.asset_path or 'brand_card'}",
                f"- time: {scene.start:.2f}-{scene.end:.2f}",
            ]
        )
    writer.write_markdown("director_script.md", "\n".join(lines))
    writer.write_json("director_quality_checklist.json", build_quality_checklist(plan))


def build_shot_list_artifact(plan: DirectorPlan) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "content_id": plan.content_id,
        "director_style": plan.style.get("version", ""),
        "edit_template": plan.style.get("edit_template", "github_tool_explainer_v4"),
        "shot_count": len(plan.shots),
        "shots": [shot.as_dict() for shot in plan.shots],
    }


def build_edit_decisions(plan: DirectorPlan) -> dict[str, Any]:
    visual_types = [shot.visual_type for shot in plan.shots]
    return {
        "schema_version": 1,
        "content_id": plan.content_id,
        "template_id": "github_tool_explainer_v4",
        "pace_targets": {
            "shot_change_seconds": "3-5",
            "visual_type_change_seconds": "8-12",
            "minimum_shots_per_scene": 2,
            "maximum_shots_per_scene": 4,
        },
        "timeline_rules": [
            "每个 scene 拆成 2-4 个 shot，优先让 3-5 秒发生一次画面变化。",
            "每 8-12 秒切换 repo、证据、README、关键词或判断卡等视觉类型。",
            "真实素材不足时使用品牌卡和关键词 punch card 兜底，但质量报告阻断直接发布。",
        ],
        "visual_type_sequence": visual_types,
        "decisions": [
            {
                "shot_id": shot.shot_id,
                "scene_id": shot.scene_id,
                "start": shot.start,
                "end": shot.end,
                "visual_type": shot.visual_type,
                "motion": shot.motion,
                "highlight": shot.highlight,
                "purpose": shot.purpose,
            }
            for shot in plan.shots
        ],
    }


def build_visual_asset_pack(writer: ArtifactWriter, plan: DirectorPlan) -> dict[str, Any]:
    pack_dir = writer.output_path("visual_asset_pack")
    pack_dir.mkdir(parents=True, exist_ok=True)
    assets: list[dict[str, Any]] = []
    for index, asset in enumerate(plan.assets, start=1):
        role = str(asset.get("role") or "card")
        asset_id = f"asset_{index:02d}"
        asset_dir = pack_dir / asset_id
        asset_dir.mkdir(parents=True, exist_ok=True)
        assets.append(
            {
                "asset_id": asset_id,
                "asset_type": _asset_type_for_role(role),
                "role": role,
                "label": asset.get("label") or role,
                "directory": str(asset_dir),
                "source_path": str(asset.get("path") or ""),
                "derived_path": "",
                "crop_definition": {
                    "status": "planned",
                    "source_rect": "auto",
                    "target_ratio": "9:16-safe-card",
                    "notes": "v4 skeleton records crop intent; later pipeline can materialize evidence/card crops here.",
                },
            }
        )
    used_card_types = sorted({shot.visual_type for shot in plan.shots if not shot.asset_path})
    for offset, visual_type in enumerate(used_card_types, start=len(assets) + 1):
        asset_id = f"asset_{offset:02d}"
        asset_dir = pack_dir / asset_id
        asset_dir.mkdir(parents=True, exist_ok=True)
        assets.append(
            {
                "asset_id": asset_id,
                "asset_type": "card",
                "role": visual_type,
                "label": visual_type,
                "directory": str(asset_dir),
                "source_path": "",
                "derived_path": "",
                "crop_definition": {
                    "status": "synthetic_card",
                    "source_rect": "",
                    "target_ratio": "1080x1920",
                    "notes": "Brand/keyword card fallback generated at render time.",
                },
            }
        )
    return {
        "schema_version": 1,
        "content_id": plan.content_id,
        "layout_rule": "one_resource_one_directory",
        "pack_directory": str(pack_dir),
        "asset_count": len(assets),
        "asset_types": sorted({str(item.get("asset_type")) for item in assets}),
        "assets": assets,
    }


def build_quality_checklist(plan: DirectorPlan) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "content_id": plan.content_id,
        "style_version": plan.style.get("version", ""),
        "checks": [
            {"item": "开头 3 秒是否有反差或强判断", "status": "review_required"},
            {"item": "字幕是否为中文主字幕，避免机器双语堆叠", "status": "review_required"},
            {"item": "每 3-5 秒是否有 shot 级画面变化", "status": "review_required"},
            {"item": "每 8-12 秒是否切换视觉类型", "status": "review_required"},
            {"item": "是否有真实素材支撑观点", "status": "review_required"},
            {"item": "是否还存在硬合规腔或报告腔", "status": "review_required"},
        ],
        "notes": "v4 自动产物仍需人工终审，重点看 shot 节奏、真实素材密度、声音质量和画面是否像人剪。",
    }


def build_shot_list_from_scenes(scenes: list[DirectorScene]) -> list[DirectorShot]:
    shots: list[DirectorShot] = []
    for scene in scenes:
        scene_duration = max(0.8, scene.end - scene.start)
        shot_specs = _shot_specs_for_scene(scene)
        shot_count = min(4, max(2, len(shot_specs)))
        cursor = scene.start
        for offset, spec in enumerate(shot_specs[:shot_count], start=1):
            remaining = scene.end - cursor
            slots_left = shot_count - offset + 1
            duration = max(0.8, remaining / max(1, slots_left))
            start = cursor
            end = scene.end if offset == shot_count else min(scene.end, cursor + duration)
            shots.append(
                DirectorShot(
                    shot_id=f"{scene.scene_id}_shot_{offset:02d}",
                    scene_id=scene.scene_id,
                    visual_type=spec["visual_type"],
                    duration=round(max(0.8, end - start), 3),
                    start=round(start, 3),
                    end=round(max(end, start + 0.8), 3),
                    screen_text=spec["screen_text"],
                    asset_path=spec["asset_path"],
                    motion=spec["motion"],
                    highlight=spec["highlight"],
                    purpose=spec["purpose"],
                )
            )
            cursor = end
    return shots


def _shot_specs_for_scene(scene: DirectorScene) -> list[dict[str, str]]:
    asset_path = scene.asset_path
    if scene.scene_id == "hook":
        return [
            {
                "visual_type": "impact_title_card",
                "screen_text": scene.screen_text or "先给结论",
                "asset_path": "",
                "motion": "snap_zoom",
                "highlight": "center",
                "purpose": "用强判断和品牌包装完成前三秒钩子。",
            },
            {
                "visual_type": "repo_full_bleed",
                "screen_text": "真实项目，不是概念图",
                "asset_path": asset_path,
                "motion": "slow_push",
                "highlight": scene.highlight or "repo_header",
                "purpose": "立刻给出项目来源和可信上下文。",
            },
            {
                "visual_type": "keyword_punch_card",
                "screen_text": "AI Agent 正在从回答走向执行",
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "把口播关键词压成可记忆的屏幕文字。",
            },
        ]
    if scene.visual_role == "readme_image":
        return [
            {
                "visual_type": "readme_visual_card",
                "screen_text": scene.screen_text,
                "asset_path": asset_path,
                "motion": scene.motion,
                "highlight": scene.highlight,
                "purpose": "用 README 图片或图示解释机制。",
            },
            {
                "visual_type": "repo_evidence_zoom",
                "screen_text": "证据点放大看",
                "asset_path": asset_path,
                "motion": "snap_zoom",
                "highlight": scene.highlight or "center",
                "purpose": "放大素材中的关键证据区域。",
            },
            {
                "visual_type": "keyword_punch_card",
                "screen_text": "不是聊天，是执行",
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "在素材之间插入节奏卡，避免长时间静态画面。",
            },
        ]
    if scene.scene_id == "boundary":
        return [
            {
                "visual_type": "repo_evidence_zoom",
                "screen_text": scene.screen_text,
                "asset_path": asset_path,
                "motion": "snap_zoom",
                "highlight": scene.highlight or "repo_header",
                "purpose": "回到真实项目证据，支撑趋势判断。",
            },
            {
                "visual_type": "judgement_card",
                "screen_text": "方向很猛，但还早",
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "给出边界感和发布前判断。",
            },
        ]
    return [
        {
            "visual_type": "repo_full_bleed",
            "screen_text": scene.screen_text,
            "asset_path": asset_path,
            "motion": scene.motion,
            "highlight": scene.highlight,
            "purpose": "展示项目或仓库全貌，承接口播事实。",
        },
        {
            "visual_type": "repo_evidence_zoom",
            "screen_text": "关键证据",
            "asset_path": asset_path,
            "motion": "snap_zoom",
            "highlight": scene.highlight or "center",
            "purpose": "用局部高亮制造剪辑层次。",
        },
        {
            "visual_type": "keyword_punch_card",
            "screen_text": scene.screen_text,
            "asset_path": "",
            "motion": "quick_push",
            "highlight": "center",
            "purpose": "用关键词卡完成 3-5 秒节奏变化。",
        },
    ]


def _asset_type_for_role(role: str) -> str:
    if role == "repo_snapshot":
        return "repo_screenshot"
    if role == "readme_image":
        return "readme_image"
    if role in {"repo_evidence_zoom", "cropped_evidence"}:
        return "cropped_evidence"
    return "card"


def assign_scene_timing(plan: DirectorPlan, duration: float) -> DirectorPlan:
    if not plan.scenes:
        return plan
    weights = [max(1, len(scene.voiceover)) for scene in plan.scenes]
    total = sum(weights)
    cursor = 0.0
    timed: list[DirectorScene] = []
    for index, (scene, weight) in enumerate(zip(plan.scenes, weights)):
        segment = duration * weight / total
        start = cursor
        end = duration if index == len(plan.scenes) - 1 else min(duration, cursor + segment)
        timed.append(
            DirectorScene(
                scene_id=scene.scene_id,
                label=scene.label,
                voiceover=scene.voiceover,
                visual_role=scene.visual_role,
                asset_path=scene.asset_path,
                screen_text=scene.screen_text,
                motion=scene.motion,
                highlight=scene.highlight,
                subtitle_keywords=scene.subtitle_keywords,
                start=round(start, 3),
                end=round(max(end, start + 0.8), 3),
            )
        )
        cursor = end
    return plan.with_timing(timed)


def collect_visual_assets(writer: ArtifactWriter) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    snapshot_status = _read_json_if_exists(writer.output_path("snapshot_status.json"))
    for screenshot in snapshot_status.get("screenshots", []) if isinstance(snapshot_status.get("screenshots"), list) else []:
        if not isinstance(screenshot, dict):
            continue
        path = _existing_path(screenshot.get("workspace_path"))
        if path:
            assets.append({"path": str(path), "role": "repo_snapshot", "label": str(screenshot.get("label") or "仓库截图")})

    readme_images = _read_json_if_exists(writer.output_path("readme_images.json"))
    for image in readme_images.get("images", []) if isinstance(readme_images.get("images"), list) else []:
        if not isinstance(image, dict):
            continue
        path = _existing_path(image.get("workspace_path"))
        if path and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            assets.append({"path": str(path), "role": "readme_image", "label": f"README 素材 {len(assets) + 1}"})

    return assets[:8]


def _build_domestic_scenes(
    title: str,
    meta: dict[str, Any],
    analysis: dict[str, Any],
    assets: list[dict[str, Any]],
) -> list[DirectorScene]:
    project = _project_name(meta, title)
    stars = _compact_number(meta.get("stars"))
    description = _domestic_context_sentence(meta, analysis)
    problem = _domestic_problem_sentence(meta, analysis)
    china_gap = _domestic_china_sentence(meta, analysis)
    if not problem:
        problem = "它想把网页操作、填表、抓取信息这些重复动作，交给 AI 自动完成。"
    if not china_gap:
        china_gap = "对中文用户来说，重点不是照搬项目，而是看懂这个方向为什么在海外升温。"
    star_phrase = f"，GitHub 上已经有 {stars} star" if stars else ""
    lines = [
        (
            "hook",
            "开场钩子",
            f"以前 AI 只能回答你问题，现在它开始自己点网页、填表、找资料了。最近国外火起来的 {project}{star_phrase}，就是这个方向的代表。",
            "repo_snapshot",
            "AI 开始自己操作网页",
            "slow_push",
            "stars",
            ("AI", "操作网页", stars or "GitHub"),
        ),
        (
            "context",
            "海外发生了什么",
            f"简单说，以前你要自己点网页、填表、找信息；现在这类工具在做一件事：让 AI 自己走完整流程。{description}",
            "repo_snapshot",
            "从回答问题到执行任务",
            "push_right",
            "repo_about",
            ("完整流程", "AI Agent", "执行任务"),
        ),
        (
            "mechanism",
            "它到底解决什么",
            problem,
            "readme_image",
            "不是聊天，是执行",
            "quick_push",
            "center",
            ("不是聊天", "执行", "自动流程"),
        ),
        (
            "china",
            "中文用户怎么看",
            china_gap,
            "readme_image",
            "机会在工作流里",
            "slow_push",
            "chart",
            ("获客", "资料整理", "运营自动化"),
        ),
        (
            "boundary",
            "趋势判断",
            "这东西现在还不一定成熟，但方向很猛：AI Agent 终于不是 PPT 里的概念，而是开始往真实干活走了。",
            "repo_snapshot",
            "方向很猛，但还早",
            "snap_zoom",
            "repo_header",
            ("方向很猛", "真实干活", "AI Agent"),
        ),
    ]
    scenes: list[DirectorScene] = []
    for index, (scene_id, label, voiceover, role, screen_text, motion, highlight, keywords) in enumerate(lines):
        asset = _asset_for_role(assets, role, index)
        scenes.append(
            DirectorScene(
                scene_id=scene_id,
                label=label,
                voiceover=_clip_voiceover(voiceover),
                visual_role=role,
                asset_path=str(asset.get("path") or ""),
                screen_text=screen_text,
                motion=motion,
                highlight=highlight,
                subtitle_keywords=tuple(str(keyword) for keyword in keywords if keyword),
            )
        )
    return scenes


def _asset_for_role(assets: list[dict[str, Any]], role: str, offset: int) -> dict[str, Any]:
    preferred = [asset for asset in assets if asset.get("role") == role]
    if preferred:
        return preferred[offset % len(preferred)]
    if assets:
        return assets[offset % len(assets)]
    return {"path": "", "role": "brand_card"}


def _project_name(meta: dict[str, Any], fallback: str) -> str:
    full_name = str(meta.get("full_name") or meta.get("title") or fallback).strip()
    if "/" in full_name:
        return full_name.split("/")[-1]
    return full_name or "这个项目"


def _compact_number(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    if number >= 10_000:
        return f"{number / 10_000:.1f} 万".rstrip("0").rstrip(".")
    return str(number)


def _clip_voiceover(value: str) -> str:
    text = _clean_sentence(value)
    return text if len(text) <= 95 else text[:94].rstrip("，。；;,. ") + "。"


def _clean_sentence(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^[-*+]\s+", "", text)
    text = text.replace("#", "")
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    return text


def _domestic_context_sentence(meta: dict[str, Any], analysis: dict[str, Any]) -> str:
    description = _clean_sentence(meta.get("description") or "")
    topics = " ".join(str(topic).lower() for topic in meta.get("topics", []) if topic)
    source = f"{description} {topics}".lower()
    if "browser" in source and ("agent" in source or "automation" in source):
        return "它的核心看点，是把浏览器里的点击、跳转、读取页面这些动作，变成 AI Agent 可以执行的任务。"
    if "github" in source or meta.get("source_type") == "github_repo":
        return "它在海外开发者圈里的热度，说明大家正在寻找能把 AI 接到真实工作流里的工具。"
    summary = _clean_sentence(analysis.get("summary") or analysis.get("core_topic") or "")
    if summary and not _mostly_english(summary):
        return _clip_voiceover(summary)
    return "这个选题值得看，是因为它不是单个工具的小更新，而是海外 AI 应用方式的一次变化。"


def _mostly_english(value: str) -> bool:
    letters = len(re.findall(r"[A-Za-z]", value))
    chinese = len(re.findall(r"[\u4e00-\u9fff]", value))
    return letters > chinese * 2 and letters > 12


def _domestic_problem_sentence(meta: dict[str, Any], analysis: dict[str, Any]) -> str:
    source = f"{meta.get('description', '')} {' '.join(str(topic) for topic in meta.get('topics', []))}".lower()
    if "browser" in source and ("agent" in source or "automation" in source):
        return "它解决的不是聊天，而是执行：打开网页、理解页面、点按钮、填表单，把这些动作串成一个自动流程。"
    problem = _clean_sentence(analysis.get("problem_solved") or analysis.get("audience_value") or "")
    if problem and not _mostly_english(problem):
        return _clip_voiceover(problem)
    return "它想把重复、琐碎、需要人手点来点去的流程，变成 AI 可以接手的一段任务。"


def _domestic_china_sentence(meta: dict[str, Any], analysis: dict[str, Any]) -> str:
    source = f"{meta.get('description', '')} {' '.join(str(topic) for topic in meta.get('topics', []))}".lower()
    if "browser" in source and ("agent" in source or "automation" in source):
        return "对中文用户来说，最值得看的不是怎么立刻赚钱，而是这种工具会怎么改变获客、资料整理、测试和运营自动化。"
    china_gap = _clean_sentence(analysis.get("china_gap") or "")
    if china_gap and not _mostly_english(china_gap):
        return _clip_voiceover(china_gap)
    return "对中文用户来说，重点不是照搬项目，而是看懂这个方向为什么在海外升温。"


def _extract_title(markdown: str) -> str:
    match = re.search(r"^#\s+标题\s*$", markdown, flags=re.MULTILINE)
    if not match:
        return ""
    next_match = re.search(r"^#\s+", markdown[match.end() :], flags=re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(markdown)
    lines = [line.strip() for line in markdown[match.end() : end].splitlines() if line.strip()]
    return lines[0] if lines else ""


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _existing_path(value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    if path.exists() and path.is_file():
        return path
    return None
