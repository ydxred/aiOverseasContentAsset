from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .artifact_writer import ArtifactWriter

if TYPE_CHECKING:
    from .llm_client import LLMClient


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
    # kind="tool" for AI tool / CLI / GitHub repo / startup case sources;
    # kind="creator" for solo-founder / indie-creator portrait sources
    # (Pieter Levels / Greg Isenberg). Drives _shot_specs_for_scene to
    # pick portrait/timeline/tweet/portfolio templates instead of
    # repo-evidence + keyword punch combo.
    kind: str = "tool"

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
            "kind": self.kind,
        }


@dataclass(frozen=True)
class Visualization:
    """Structured payload for data-driven shots (bar chart / flow / timeline).

    Lives **alongside** ``visual_type`` rather than replacing it: when a shot
    carries a non-None ``visualization``, the Remotion dispatcher renders the
    corresponding info-graphic component and ignores ``visual_type``. When
    ``visualization`` is None (the common case), behaviour is identical to
    the pre-existing typography pipeline.

    Why a separate dataclass instead of stuffing fields onto DirectorShot
    -------------------------------------------------------------------
    - Keeps the shot record small for shots that *don't* need data.
    - Makes the schema explicit so the Remotion side can parse-or-skip
      cleanly: `if shot.visualization: render(<chart/>) else: render(<typo/>)`.
    - Future kinds (``timeline`` / ``comparison`` / ``architecture``) only
      need to define ``data`` records that match their renderer; we don't
      have to touch DirectorShot again.

    Field semantics
    ---------------
    ``kind``   : one of ``"bar_chart" | "flow_chart" | "timeline" |
                 "comparison"``. Renderer dispatches on this.
    ``title``  : short headline ABOVE the visualization (e.g. "AI 自动化的
                 5 步链路"). Falls back to ``shot.screen_text`` when empty.
    ``caption``: optional one-line aside drawn UNDER the visualization,
                 used for source attribution / disclaimer ("数据来自
                 GitHub Trending 2025-05").
    ``data``   : kind-specific tuple of records. Schemas:
                  - bar_chart : ``({"label": str, "value": float,
                                    "unit": str?}, ...)`` (2-6 items)
                  - flow_chart: ``({"label": str, "icon": str?,
                                    "tone": str?}, ...)`` (3-6 nodes
                                    rendered as connected steps)
                  - timeline  : ``({"date": str, "label": str}, ...)``
                                    (2-5 events on a horizontal axis)
                  - comparison: 2-tuple of records, each ``{"side": str,
                                    "label": str, "value": str}``
    """

    kind: str
    title: str = ""
    caption: str = ""
    data: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "caption": self.caption,
            "data": [dict(item) for item in self.data],
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
    # Real Chinese/English narrative tokens (e.g. ``("Codex", "终端", "AI Agent")``)
    # propagated from the parent ``DirectorScene``. ``subtitle_engine`` consumes
    # these to colour-highlight the words that actually appear in the cue text;
    # the legacy ``highlight`` field above is a layout enum (``center`` /
    # ``top_third``) and is **not** safe to use as a subtitle keyword.
    subtitle_keywords: tuple[str, ...] = ()
    # Optional structured payload for data-driven info-graphic shots. When
    # set, the Remotion side renders the corresponding chart/flow/timeline
    # component INSTEAD of the default typography template. Stays None for
    # the common "talking-head explainer" case so existing shots are
    # bit-identical to the pre-Visualization era.
    visualization: Visualization | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
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
            "subtitle_keywords": list(self.subtitle_keywords),
        }
        if self.visualization is not None:
            payload["visualization"] = self.visualization.as_dict()
        return payload


@dataclass(frozen=True)
class DirectorPlan:
    content_id: str
    title: str
    voiceover: str
    scenes: list[DirectorScene]
    shots: list[DirectorShot]
    assets: list[dict[str, Any]]
    style: dict[str, Any]

    def with_timing(
        self,
        timed_scenes: list[DirectorScene],
        *,
        llm: "LLMClient | None" = None,
        cache_dir: Path | None = None,
    ) -> "DirectorPlan":
        return DirectorPlan(
            content_id=self.content_id,
            title=self.title,
            voiceover=self.voiceover,
            scenes=timed_scenes,
            shots=build_shot_list_from_scenes(timed_scenes, llm=llm, cache_dir=cache_dir),
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
    # NEW: pull the actual ## sections from chinese_script.md so director
    # scenes (and therefore subtitles + TTS) carry the rewriter's content
    # instead of the hard-coded "以前 AI 只能回答你问题..." template that
    # ignored everything LLM produced upstream.
    script_sections = _extract_script_sections(script_markdown)
    scenes = _build_domestic_scenes(title, meta, analysis, scene_assets, script_sections=script_sections)
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


# ---------------------------------------------------------------------------
# Shot density tuning.
#
# The quality rubric (``build_video_quality_report``) measures
# ``visual_density_score`` as ``shot_count / (duration / 4.5) * 100``. i.e. the
# expectation is ~one shot every 4.5s. Historically each scene emitted 2-3
# shots regardless of scene length, which for a 120s video produced 15 shots
# and scored 57/100. To cross the 95-point publish threshold without faking
# the shot count, we:
#
# 1. Compute per-scene target shot count from the scene's actual duration.
# 2. Cap between a sane min/max so we don't spam 8 shots in a 3s beat.
# 3. When the stock ``_shot_specs_for_scene`` list is shorter than the
#    target, we **cycle** the specs and vary ``motion`` / ``highlight`` so the
#    repeated ``visual_type`` still looks like a different camera beat — not
#    the same frame held twice. No new Remotion components required; the
#    existing ones already react to those two fields.
# ---------------------------------------------------------------------------

SHOT_TARGET_SECONDS_PER_SHOT = 4.3  # matches rubric's 4.5 target with tiny headroom
SHOT_MIN_PER_SCENE = 2
SHOT_MAX_PER_SCENE = 12  # 提高到 12 让 SHOT_HARD_MAX_DURATION 真正生效（42s 场景需要 9 镜）
# 每镜硬上限：5 秒。超过这个值视觉就会"卡住"，观众感知"画面停在那里"。
# 短视频赛道里 @计算机大白 等头部 4-5s/镜，MyElc 6-8s/镜，>8s 就会被划走。
SHOT_HARD_MAX_DURATION = 5.0
SHOT_MIN_DURATION = 1.2  # 避免 <1.2s 的闪镜，观感会碎

_VARIATION_MOTIONS = ("slow_push", "snap_zoom", "quick_push", "slow_pull", "static_held")
_VARIATION_HIGHLIGHTS = ("center", "top_third", "bottom_third", "left_focal", "right_focal")

# Visual types that render *short* keyword/punch overlays — these stay on
# their authored ``keyword_overlay`` and should NOT be overridden with a
# voiceover sentence (the punch cards are designed for 1-3 token text and
# break visually on full sentences).
_PUNCH_VISUAL_TYPES = frozenset(
    {"keyword_punch_card", "signal_pulse_card"}
)


def _split_voiceover_for_shots(voiceover: str, shot_count: int) -> list[str]:
    """Slice scene voiceover into per-shot overlay text.

    The overlay should track *what the narrator is saying right now*, not
    repeat the same scene-level summary on every shot. We split on Chinese
    sentence terminators (``。！？\\n``) and English ``. ! ?``, then map
    sentences across shots:

    - shot count == sentence count → 1:1 assignment.
    - shot count <  sentence count → group adjacent sentences (early shots
      may carry 2 sentences each so all narration shows somewhere).
    - shot count >  sentence count → fall back to splitting long sentences
      into comma-clauses (``，；：—``) so each shot gets a distinct fragment
      rather than cycling the same sentence text. Only after the
      clause-split pool is exhausted do we cycle.

    Returns ``shot_count`` strings; each is trimmed to 80 chars to fit on
    the typography card without wrapping past 3 lines.
    """
    if not voiceover or shot_count <= 0:
        return [""] * max(shot_count, 0)
    # Split on Chinese sentence terminators + newlines only. English ``.``
    # is unsafe — "9.2 万" / "Python 3.12" / "12.5K" all contain decimals
    # that look like sentence ends, and the script is Chinese-language so
    # genuine English sentence boundaries are rare. ``！？`` and their
    # half-width forms after Chinese clauses still split (covers the
    # bilingual edge cases without slicing decimals mid-number).
    raw = re.split(r"(?<=[。！？!?\n])\s*", voiceover.strip())
    sentences = [s.strip() for s in raw if s.strip() and len(s.strip()) >= 2]
    if not sentences:
        return [voiceover.strip()[:80]] * shot_count
    if len(sentences) == shot_count:
        return [s[:80] for s in sentences]
    if len(sentences) > shot_count:
        result: list[str] = []
        for i in range(shot_count):
            start_idx = (i * len(sentences)) // shot_count
            end_idx = ((i + 1) * len(sentences)) // shot_count
            chunk = " ".join(sentences[start_idx:max(start_idx + 1, end_idx)])
            result.append(chunk[:80])
        return result
    # shot_count > sentence_count — split sentences further on commas so
    # we have enough distinct fragments. Only sentences with multiple
    # clauses contribute fragments; otherwise the sentence stays whole.
    fragments: list[str] = []
    for sentence in sentences:
        clauses = [c.strip() for c in re.split(r"[，,；;：:—]+", sentence) if c.strip() and len(c.strip()) >= 2]
        if len(clauses) >= 2:
            fragments.extend(clauses)
        else:
            fragments.append(sentence)
    if len(fragments) >= shot_count:
        return [fragments[i][:80] for i in range(shot_count)]
    return [fragments[i % len(fragments)][:80] for i in range(shot_count)]


def _target_shot_count(scene_duration: float, specs_count: int) -> int:
    """Pick the shot count for a single scene.

    We let the scene's duration drive the math — a 20s scene wants ~5 shots,
    an 8s scene wants 2. The lower bound is ``SHOT_MIN_PER_SCENE`` and we
    never go below the stock spec count (so all authored visual beats still
    fire). Upper bound ``SHOT_MAX_PER_SCENE`` prevents over-slicing on long
    scenes that happen to spike above 30s.

    We also enforce a **hard ceiling of ``SHOT_HARD_MAX_DURATION`` per shot**
    by computing ``ceil(scene_duration / SHOT_HARD_MAX_DURATION)`` — if a
    scene is e.g. 32s long, ``round(32/4.3)=7`` shots gives ~4.6s/shot which
    is fine, but a 22s scene at the prior 4-shot floor would yield 5.5s/shot
    — over the ceiling. Taking ``max`` of the rhythm target and the ceiling
    derived count guarantees no shot ever holds longer than 5s on screen.
    """
    rhythm_target = max(
        SHOT_MIN_PER_SCENE,
        round(scene_duration / SHOT_TARGET_SECONDS_PER_SHOT),
    )
    # Ceiling-derived count: enough shots so each beat stays ≤ SHOT_HARD_MAX_DURATION.
    ceiling_count = max(
        SHOT_MIN_PER_SCENE,
        int(scene_duration / SHOT_HARD_MAX_DURATION) + (1 if scene_duration % SHOT_HARD_MAX_DURATION > 0.001 else 0),
    )
    density_target = max(rhythm_target, ceiling_count)
    density_target = min(SHOT_MAX_PER_SCENE, density_target)
    # make sure we don't drop below the scene's stock spec count, otherwise we
    # lose authored visual beats the narrative was designed around.
    return max(specs_count, density_target)


# Evidence-bearing templates — when these appear in the cycle pool, the
# rendered shot loads a chrome card with a screenshot. Repeating them
# means showing the SAME image again (we typically only have 1-2
# usable evidence assets per repo after the wordmark filter), which
# reads as visual recycling. We keep them on the FIRST appearance and
# fill subsequent cycle slots from typography templates only.
_EVIDENCE_VISUAL_TYPES = frozenset({
    "repo_full_bleed",
    "repo_evidence_zoom",
    "readme_visual_card",
})


def _expand_specs(specs: list[dict[str, str]], target_count: int) -> list[dict[str, str]]:
    """Cycle specs to reach ``target_count``, evidence-aware.

    First pass replays the full spec list verbatim (each authored beat
    fires once). Subsequent passes cycle ONLY the typography templates
    — evidence templates are excluded from repeats so the viewer never
    sees the same screenshot in shots 2 and 5 of the same scene.

    motion/highlight rotate per cycle so a repeated ``story_beat_card``
    on shots 4 and 7 still reads as different beats.
    """
    if not specs:
        return []
    if len(specs) >= target_count:
        return specs[:target_count]
    typography_pool = [s for s in specs if s.get("visual_type") not in _EVIDENCE_VISUAL_TYPES]
    if not typography_pool:
        typography_pool = specs  # all evidence — degrade to old behaviour
    expanded: list[dict[str, str]] = list(specs)
    while len(expanded) < target_count:
        i = len(expanded) - len(specs)
        source = typography_pool[i % len(typography_pool)]
        cycle = i // len(typography_pool) + 1
        varied = dict(source)
        motion_idx = (
            _VARIATION_MOTIONS.index(source.get("motion", _VARIATION_MOTIONS[0]))
            if source.get("motion") in _VARIATION_MOTIONS
            else 0
        )
        hl_idx = (
            _VARIATION_HIGHLIGHTS.index(source.get("highlight", _VARIATION_HIGHLIGHTS[0]))
            if source.get("highlight") in _VARIATION_HIGHLIGHTS
            else 0
        )
        varied["motion"] = _VARIATION_MOTIONS[(motion_idx + cycle) % len(_VARIATION_MOTIONS)]
        varied["highlight"] = _VARIATION_HIGHLIGHTS[(hl_idx + cycle) % len(_VARIATION_HIGHLIGHTS)]
        varied["purpose"] = source.get("purpose", "") + f" (rhythm beat {cycle + 1})"
        expanded.append(varied)
    return expanded[:target_count]


def build_shot_list_from_scenes(
    scenes: list[DirectorScene],
    *,
    llm: "LLMClient | None" = None,
    cache_dir: Path | None = None,
) -> list[DirectorShot]:
    shots: list[DirectorShot] = []
    # Track viz kinds attached anywhere in the video so the secondary
    # picker for later scenes can avoid duplicating the same kind. Fixes
    # the previous "context_shot_06 AND mechanism_shot_06 both run
    # code_editor on the same Python block" — second appearance now
    # falls through to the next candidate (flow_chart / terminal / etc.).
    used_viz_kinds: set[str] = set()
    for scene in scenes:
        scene_duration = max(0.8, scene.end - scene.start)
        shot_specs = _shot_specs_for_scene(scene)
        shot_count = _target_shot_count(scene_duration, len(shot_specs))
        # If ``SHOT_MIN_DURATION * shot_count`` would exceed scene_duration we
        # back off — a 3s scene can't meaningfully host 4 shots.
        while shot_count > SHOT_MIN_PER_SCENE and shot_count * SHOT_MIN_DURATION > scene_duration:
            shot_count -= 1
        specs_to_use = _expand_specs(shot_specs, shot_count)
        # Per-shot overlay text from voiceover sentence slicing — without
        # this, every shot in a scene shows the same scene.screen_text
        # (sourced from analysis.summary first sentence) and the cycle
        # ABC→ABC→ABC looks like "the same frame held three times" even
        # though the visual_type rotates. Punch cards keep their authored
        # keyword overlay because their components break on long text.
        per_shot_text = _split_voiceover_for_shots(scene.voiceover, len(specs_to_use))
        # Rotate punch-card keyword windows per cycle so 3 identical punch
        # beats in a row don't show the same "Pieter / 荷兰人 / 小打小闹"
        # three times. With 4 subtitle keywords we get 4 distinct windows
        # (keywords[0:3], keywords[1:4], keywords[2:5↦0], keywords[3:6↦1]).
        scene_keywords = [str(k).strip() for k in scene.subtitle_keywords if str(k).strip()]
        punch_seen = 0
        for spec_idx, spec in enumerate(specs_to_use):
            if spec.get("visual_type") in _PUNCH_VISUAL_TYPES:
                if scene_keywords:
                    window_start = punch_seen % len(scene_keywords)
                    rotated = scene_keywords[window_start:] + scene_keywords[:window_start]
                    spec["screen_text"] = " / ".join(rotated[:3])
                punch_seen += 1
                continue
            sliced = per_shot_text[spec_idx] if spec_idx < len(per_shot_text) else ""
            if sliced:
                spec["screen_text"] = sliced
        # Probe the scene once for an info-graphic payload. If we find one,
        # we'll attach it to the FIRST shot of the scene (the one whose
        # spec is the dominant typography card) and override that shot's
        # visual_type to the matching ``*_visualization`` marker. The
        # remaining shots stay typography so we don't visually fatigue
        # the viewer with the same chart for the full scene.
        viz = _extract_visualization_for_scene(scene, llm=llm, cache_dir=cache_dir)
        if viz is not None:
            used_viz_kinds.add(viz.kind)
        # Secondary viz of a different kind, attached to the mid-scene
        # shot. Lets a long scene (10+ shots) carry TWO data anchors
        # (e.g. comparison_table + code_editor on mechanism) instead of
        # one moment of viz then 8 typography shots.
        secondary_viz = _extract_secondary_visualization_for_scene(
            scene, viz,
            cache_dir=cache_dir,
            used_kinds=frozenset(used_viz_kinds),
        )
        if secondary_viz is not None:
            used_viz_kinds.add(secondary_viz.kind)
        secondary_offset = max(2, (shot_count + 1) // 2) if secondary_viz is not None else 0
        cursor = scene.start
        for offset, spec in enumerate(specs_to_use, start=1):
            remaining = scene.end - cursor
            slots_left = shot_count - offset + 1
            # Even spacing across the scene; never exceed SHOT_HARD_MAX_DURATION
            # so a single shot can't hold > 5s even if remaining time is huge.
            duration = max(SHOT_MIN_DURATION, remaining / max(1, slots_left))
            duration = min(duration, SHOT_HARD_MAX_DURATION)
            start = cursor
            end = scene.end if offset == shot_count else min(scene.end, cursor + duration)
            shot_viz = None
            if offset == 1 and viz is not None:
                shot_viz = viz
            elif offset == secondary_offset and secondary_viz is not None:
                shot_viz = secondary_viz
            shot_visual_type = spec["visual_type"]
            if shot_viz is not None:
                # Renderer will dispatch on this marker first; we keep the
                # original visual_type behind a suffix so debugging/QC
                # reports still see the typography fallback intent.
                shot_visual_type = f"viz_{shot_viz.kind}"
            shots.append(
                DirectorShot(
                    shot_id=f"{scene.scene_id}_shot_{offset:02d}",
                    scene_id=scene.scene_id,
                    visual_type=shot_visual_type,
                    duration=round(max(SHOT_MIN_DURATION, end - start), 3),
                    start=round(start, 3),
                    end=round(max(end, start + SHOT_MIN_DURATION), 3),
                    screen_text=spec["screen_text"],
                    asset_path=spec["asset_path"],
                    motion=spec["motion"],
                    highlight=spec["highlight"],
                    purpose=spec["purpose"],
                    subtitle_keywords=scene.subtitle_keywords,
                    visualization=shot_viz,
                )
            )
            cursor = end
    return shots


# ---------------- Visualization extraction ----------------
#
# Heuristic-first, NOT LLM-driven yet. Rationale:
#
# - The LLM (GPT-4o via script_writer) has already shown it hallucinates
#   structured fields when forced to emit JSON in addition to prose
#   (cf. the ``1 AI / 2 Peter / 3 Git`` step-list contamination in
#   yt_9d1a160bbcab where the keyword extractor pulled three entity tokens
#   that look like "steps" but read as nonsense for the audience).
# - A handful of regex/keyword patterns gives us deterministic, debuggable
#   behaviour while we ship the renderer side. Once the data path is real
#   and tested, we can layer LLM-driven extraction with the existing
#   payload as a contract — much safer than building both at once.
#
# Two extractors today:
#
# 1. ``_extract_flow_chart`` — looks for action chains in ``mechanism`` /
#    ``context`` scenes. We hunt for 3+ verbs / nouns separated by "然后",
#    "接着", "再", "最后", or strong commas, then collapse them to short
#    node labels.
#
# 2. ``_extract_bar_chart`` — looks for 2+ "<token> <number><unit>"
#    patterns in any scene. Triggers when the voiceover names multiple
#    quantitative items (e.g. "GitHub 上 8 万 star, 周下载量 50 万").
#
# Both extractors intentionally return None for scenes without a clean
# match, so the typography fallback path takes over and we never paint a
# 3-bar chart from a single statistic.

# Connectors that signal a step-by-step action chain in Chinese narration.
# Order matters: we prefer the strongest connectors first so a sentence
# like "AI 先识别问题，然后修复 bug，最后提交更新" splits as a 3-step flow.
_FLOW_CONNECTORS = [
    "然后",
    "接着",
    "随后",
    "再",
    "之后",
    "最后",
    "并且",
    "同时",
]

# Number-with-unit pattern for bar-chart extraction. Captures the leading
# token (e.g. "周下载量"), the digits (Arabic or Chinese big-number), and
# the unit (e.g. "万 star" / "美元" / "次"). Tuned to be conservative —
# we'd rather miss a chart than paint one from a date or a phone number.
_NUMBER_PATTERNS = re.compile(
    # group 1 (label) \u4e0a\u9650\u653e\u5bbd\u5230 1+13=14 chars,\u5bb9\u7eb3 "pip \u5b89\u88c5\u91cf\u8fbe\u5230\u4e86"(10
    # chars) / "Token \u91cf\u6807\u6ce8\u4e3a"(11 chars) \u8fd9\u7c7b\u82f1\u6587+\u4e2d\u6587\u6df7\u5408 label\u3002\u539f\u6765
    # 1+8=9 chars \u4e0a\u9650\u4f1a\u4ece\u8bcd\u4e2d\u95f4\u622a\u65ad,\u5bfc\u81f4 BarChart \u6e32\u51fa "ip \u5b89\u88c5\u91cf"(p
    # \u88ab\u5403) / "oken \u91cf"(T \u88ab\u5403) \u7684\u4e22\u5b57\u5de5\u4e1a\u7ea7\u7f3a\u9677\u3002
    r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z\s]{0,13})"
    r"\s*"
    r"(\d{1,4}(?:[\.,]\d+)?)"
    r"\s*"
    r"(万|亿|千|百|k|K|M|B|%|美元|元|次|人|天|分|秒|小时|个月|年|star|stars|MAU|DAU)"
)


# Verbs that signal an "action step" in Chinese AI/科技 narration. A
# candidate node must contain ≥1 of these to be accepted — this filters
# out narrative scaffolding ("但这次" / "可能要等到回家") that earlier
# splits leaked through. List intentionally biased to common Chinese
# action vocabulary in this domain (file ops, web ops, AI ops).
_ACTION_VERBS = (
    "识别", "访问", "打开", "拉取", "拽", "提取", "上传", "传到",
    "下载", "保存", "提交", "修复", "找出", "拍", "拍个照",
    "回复", "发", "发送", "填", "执行", "运行", "调用", "推送",
    "处理", "完成", "唤醒", "启动", "控制", "整理", "整合",
    "扫描", "解析", "生成", "合成", "编译",
)

# Concrete proper nouns / product names. A flow-chart node MUST contain
# either one of these or an English/digit token to qualify — this is the
# single most effective filter against "narrative noise" leaking into
# the diagram (e.g. "AI 不只是能处理简单的…" was getting through the
# verb-only gate because "处理" is a verb but the clause carries no
# concrete subject of action).
_CONCRETE_NOUNS = (
    "WhatsApp", "Twitter", "Git", "Dropbox", "Philips", "Sonos",
    "GitHub", "Cursor", "Slack", "Notion", "iPhone", "Android",
    "OpenAI", "Claude", "Codex",
    "推文", "代码", "仓库", "邮件", "日历", "文件", "护照",
    "灯光", "音响", "音乐", "睡眠", "健身",
    "浏览器", "终端", "命令", "网页", "登录", "信息",
    "bug", "PR", "API", "URL",
)


def _trim_to_action_window(chunk: str, *, max_len: int = 12) -> str:
    """Truncate a long clause to ≤``max_len`` chars, preferring a window
    that keeps the action verb visible.

    Plain head-truncation drops the verb when the clause leads with a
    long subject (e.g. "Peter 的 AI 上演了教科书般的流程操作" → head 12
    chars = "Peter 的 AI 上…", which is just narrative scaffolding
    without the verb the gate above matched).

    We instead find the first action verb, then center a window of
    ``max_len`` chars around it (1-3 chars of preceding context to
    preserve the subject + as much trailing object as fits). Falls back
    to head truncation when no verb is found, which shouldn't happen
    given ``_is_concrete_action`` is the caller's gate.
    """
    if len(chunk) <= max_len:
        return chunk

    def _avoid_cut_through_token(s: str, idx: int, *, direction: str) -> int:
        """Pull boundary off the middle of an alphanumeric token.

        ``direction='start'``: shift right past the token end.
        ``direction='end'``:   shift left past the token start.

        This fixes "…ox 中提取" where the start landed in the middle of
        ``Dropbox`` and we want to either keep the whole word or drop it
        entirely. We only nudge by up to 6 chars so we don't blow the
        window length budget.
        """
        if 0 < idx < len(s):
            ch_at = s[idx]
            ch_before = s[idx - 1]
            in_token = bool(re.match(r"[A-Za-z0-9]", ch_at)) and bool(re.match(r"[A-Za-z0-9]", ch_before))
            if not in_token:
                return idx
            for nudge in range(1, 7):
                cand = idx + (nudge if direction == "start" else -nudge)
                cand = max(0, min(len(s), cand))
                if cand == 0 or cand == len(s):
                    return cand
                neighbour = s[cand - 1]
                cur = s[cand]
                if not (re.match(r"[A-Za-z0-9]", neighbour) and re.match(r"[A-Za-z0-9]", cur)):
                    return cand
        return idx

    for verb in _ACTION_VERBS:
        idx = chunk.find(verb)
        if idx < 0:
            continue
        start = max(0, idx - 2)
        end = min(len(chunk), start + max_len)
        if end - start < max_len and start > 0:
            start = max(0, end - max_len)
        # Token-boundary protection: never bisect an English/digit token.
        start = _avoid_cut_through_token(chunk, start, direction="start")
        end = _avoid_cut_through_token(chunk, end, direction="end")
        # Ensure we didn't end up shorter than max_len-3 after nudging;
        # if so, slide the window forward by the lost chars.
        if end - start < max_len - 3 and end < len(chunk):
            end = min(len(chunk), start + max_len)
            end = _avoid_cut_through_token(chunk, end, direction="end")
        window = chunk[start:end]
        suffix = "…" if end < len(chunk) else ""
        prefix = "…" if start > 0 else ""
        return f"{prefix}{window}{suffix}"
    return chunk[:max_len] + "…"


def _is_concrete_action(chunk: str) -> bool:
    """A clause earns a flow-chart slot only when it names BOTH an action
    AND a domain-specific concrete noun (product name / file type /
    physical object).

    Earlier we let any English/digit token count as "concrete", but that
    gate accepted clauses like "AI 不只是能处理简单的文本" because "AI"
    matches /[A-Za-z]/. Tightening to ``_CONCRETE_NOUNS`` membership
    (product / object names — not pronouns) gives much sharper filtering:
    if the clause doesn't NAME the thing the AI acted on, it's narrative
    filler and shouldn't appear as a flow-chart node.

    Returns True only when both gates pass; ``_split_action_chain``
    callers fall through to the typography step-list when not enough
    concrete-action clauses exist.
    """
    has_verb = any(verb in chunk for verb in _ACTION_VERBS)
    if not has_verb:
        return False
    has_domain_noun = any(noun in chunk for noun in _CONCRETE_NOUNS)
    return has_domain_noun


def _split_action_chain(text: str) -> list[str]:
    """Split narration into 3-5 short action-step labels.

    Strategy (much stricter than the original "split on every connector"):

    1. Sentence-level split on Chinese full stops / 分号 / question marks
       to avoid swallowing entire paragraphs.
    2. Within each sentence, split on connectors AND commas to surface
       the candidate sub-clauses.
    3. Keep ONLY clauses that contain at least one strong action verb
       (see ``_ACTION_VERBS``). This is the key filter — it discards
       narrative bridges ("但这次" / "他的形式有点特别") that earlier
       leaked through and made the chart unreadable.
    4. Cap label length at 12 chars so flow-chart nodes stay scannable.
    """
    if not text:
        return []
    # Sentence-level split first.
    sentences = [s.strip() for s in re.split(r"[。！？!?；;]", text) if s.strip()]
    candidates: list[str] = []
    splitter = re.compile("|".join(_FLOW_CONNECTORS + ["，", ",", "、"]))
    for sentence in sentences:
        for raw in splitter.split(sentence):
            chunk = raw.strip(" ，,。！？!?\"'")
            if not chunk:
                continue
            # Drop residual conjunction prefixes.
            for prefix in ("它", "然后", "接着", "再", "之后", "最后", "并且", "同时", "而且", "于是"):
                if chunk.startswith(prefix):
                    chunk = chunk[len(prefix):].lstrip(" ，,")
            if not chunk:
                continue
            # Action-verb + concrete-noun gate: skip clauses that are pure
            # narrative (verb-only) or pure description (no verb).
            if not _is_concrete_action(chunk):
                continue
            # 12-char label cap with verb-aligned window. We slide the
            # window so the action verb stays inside it rather than
            # blindly slicing the head, which previously produced
            # "Peter 的 AI 上…" (truncating away the verb and concrete
            # subject the gate just verified).
            chunk = _trim_to_action_window(chunk, max_len=12)
            if chunk and chunk not in candidates:
                candidates.append(chunk)
            if len(candidates) >= 5:
                break
        if len(candidates) >= 5:
            break
    return candidates


def _extract_flow_chart(scene: DirectorScene) -> Visualization | None:
    """Extract a 3-5 node flow chart from scenes that describe action chains.

    Restricted to ``mechanism`` ("它怎么做到的"). We dropped ``context``
    after observing that context narration is usually scene-setting prose
    rather than a clean action chain — forcing a flow chart there made
    the diagram read as random sub-clauses pulled out of context.

    Even within ``mechanism`` we require ≥3 distinct ACTION-VERB-bearing
    clauses; if the narration is too abstract to yield three concrete
    actions, we return None and let the typography step-list handle it.
    """
    if scene.scene_id != "mechanism":
        return None
    nodes = _split_action_chain(scene.voiceover or "")
    if len(nodes) < 3:
        return None
    data = tuple({"label": label} for label in nodes[:5])
    return Visualization(
        kind="flow_chart",
        title="AI 自动化的关键步骤",
        data=data,
    )


def _extract_bar_chart(scene: DirectorScene) -> Visualization | None:
    """Extract a 2-5 bar chart from scenes naming multiple quantitative items.

    Requires ≥2 distinct ``<label> <number><unit>`` matches AND that the
    matches reference DIFFERENT labels (we don't want "8 万 star" and
    "8 万 star" again to count as a chart). Returns None when the scene
    has only one number — a single data point is much better delivered
    as a Spotlight typography card.
    """
    text = scene.voiceover or ""
    if not text:
        return None
    matches = _NUMBER_PATTERNS.findall(text)
    if len(matches) < 2:
        return None
    seen_labels: set[str] = set()
    data: list[dict[str, Any]] = []
    for label_raw, number_raw, unit in matches:
        label = label_raw.strip()
        # 上限放宽到 16,匹配 _NUMBER_PATTERNS group1 现在的 14 chars
        # 上限 + 一点剪余地。原来 12 会丢掉"它的 pip 安装量达到了"(11
        # chars + leading 它的)级 label,导致整段 viz 退化成 None。
        if not label or len(label) > 16:
            continue
        # 头部裁剪:把"它的 / 我们的 / 这是 / 但是 / 这个" 这类引导词
        # 切掉,只留含产品/能力名的核心 label。
        for prefix in ("它的 ", "这是 ", "我们的 ", "这个 ", "但是 ", "于是 ", "处理的 ", "目前的 "):
            if label.startswith(prefix):
                label = label[len(prefix):]
                break
        if label in seen_labels:
            continue
        try:
            value = float(number_raw.replace(",", ""))
        except ValueError:
            continue
        seen_labels.add(label)
        data.append({"label": label, "value": value, "unit": unit})
        if len(data) >= 5:
            break
    if len(data) < 2:
        return None
    return Visualization(
        kind="bar_chart",
        title="关键数据",
        data=tuple(data),
    )


_FLOW_STEPS_PROMPT_VERSION = "v1"


def _hash_voiceover(text: str) -> str:
    """Stable short hash of voiceover text used as cache key.

    Includes the prompt version so a future prompt revision automatically
    invalidates cached steps without requiring a manual cache wipe.
    """
    h = hashlib.sha256()
    h.update(_FLOW_STEPS_PROMPT_VERSION.encode("utf-8"))
    h.update(b"\x00")
    h.update((text or "").encode("utf-8"))
    return h.hexdigest()[:16]


def _load_flow_steps_cache(cache_dir: Path | None) -> dict[str, Any]:
    if cache_dir is None:
        return {}
    cache_path = cache_dir / "flow_steps_cache.json"
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_flow_steps_cache(cache_dir: Path | None, cache: dict[str, Any]) -> None:
    if cache_dir is None:
        return
    cache_path = cache_dir / "flow_steps_cache.json"
    try:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _normalise_llm_steps(raw: Any) -> list[str]:
    """Defensively coerce the LLM ``steps`` payload to a clean list[str].

    Even with strict json_schema we keep a defensive layer because:
    - Strict schema only enforces SHAPE, not item length / count.
    - We want "garbage in → empty list" rather than "garbage in →
      poisoned chart"; an empty list lets the heuristic / typography
      fallback take over deterministically.

    Filters applied:
      * each step trimmed
      * dropped if empty, > 14 chars, or doesn't contain a domain noun /
        action verb (same gates as the heuristic — keeps quality
        consistent regardless of which extractor wins)
      * dedup, cap to 5
    """
    if not isinstance(raw, list):
        return []
    cleaned: list[str] = []
    for item in raw:
        text = str(item or "").strip(" ，,。！？!?\"'")
        if not text:
            continue
        if len(text) > 14:
            continue
        if not _is_concrete_action(text):
            continue
        if text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= 5:
            break
    return cleaned


def _extract_flow_chart_via_llm(
    scene: DirectorScene,
    llm: "LLMClient",
    cache_dir: Path | None,
) -> Visualization | None:
    """LLM-driven flow_chart extraction (preferred over heuristic).

    Wins over the heuristic on three fronts:
      1. Step granularity — LLM groups multi-clause sentences into a
         single action ("拍照传 WhatsApp" rather than the heuristic
         "…ox 中提取文件完成任务" with chopped Dropbox).
      2. Action verb naming — LLM picks the canonical verb
         ("识别" / "提交"), heuristic just preserves whatever connector
         landed on the boundary.
      3. Order — LLM respects narrative chronology even when the
         underlying voiceover is paragraph-shaped; heuristic processes
         left-to-right which sometimes pulls the conclusion before the
         setup.

    Failure modes (all return None → caller falls back to heuristic):
      - Network / API errors
      - LLM returned empty array (its own "I can't produce ≥3 clean
        steps" signal — we honour it explicitly per prompt instruction)
      - ``_normalise_llm_steps`` rejected the output as low-quality
    """
    text = scene.voiceover or ""
    if not text or scene.scene_id != "mechanism":
        return None

    cache_key = f"{scene.scene_id}|{_hash_voiceover(text)}"
    cache = _load_flow_steps_cache(cache_dir)
    cached = cache.get(cache_key)
    if isinstance(cached, list):
        steps = _normalise_llm_steps(cached)
        if len(steps) >= 3:
            return Visualization(
                kind="flow_chart",
                title="AI 自动化的关键步骤",
                data=tuple({"label": s} for s in steps),
            )
        if len(cached) == 0:
            # Cached "no clean steps" verdict — don't re-pay for the call.
            return None

    payload = {
        "voiceover": text,
        "subtitle_keywords": list(scene.subtitle_keywords),
        "scene_id": scene.scene_id,
    }
    try:
        response = llm.generate("flow_steps", payload)
    except Exception:
        # Any LLM failure → silently fall through; the heuristic
        # extractor (next in the chain) provides graceful degradation.
        return None

    raw_steps = response.content.get("steps") if isinstance(response.content, dict) else None
    steps = _normalise_llm_steps(raw_steps)
    # Cache the raw LLM output regardless of whether we use it — even
    # an empty array is valuable signal so we don't re-pay for the call.
    cache[cache_key] = steps if steps else []
    _save_flow_steps_cache(cache_dir, cache)
    if len(steps) < 3:
        return None
    return Visualization(
        kind="flow_chart",
        title="AI 自动化的关键步骤",
        data=tuple({"label": s} for s in steps),
    )


def _extract_creator_timeline(scene: DirectorScene, cache_dir: Path | None) -> Visualization | None:
    """Build a timeline / portfolio viz from generic_candidate.signals.projects.

    Creator candidates carry a ``signals.projects`` array of
    ``{name, year, tagline}`` dicts (sources.yaml convention). For
    creator scenes we want to render that as a real timeline (context
    scene) or product portfolio (mechanism scene) instead of falling
    back to subtitle_keywords text.

    Returns None when:
      - scene is not a creator scene (kind != "creator")
      - cache_dir not set (we can't locate generic_candidate.json)
      - no projects array present
      - scene_id doesn't match a viz-eligible slot
    """
    if scene.kind != "creator" or cache_dir is None:
        return None
    candidate_path = cache_dir / "00_source" / "generic_candidate.json"
    if not candidate_path.exists():
        return None
    try:
        import json as _json
        candidate = _json.loads(candidate_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    signals = candidate.get("signals") if isinstance(candidate.get("signals"), dict) else {}
    projects = signals.get("projects")
    if not isinstance(projects, list) or not projects:
        return None

    if scene.scene_id == "context":
        # Timeline: year-anchored milestones.
        data: list[dict[str, Any]] = []
        for p in projects[:5]:
            if not isinstance(p, dict):
                continue
            year = str(p.get("year") or "").strip()
            name = str(p.get("name") or "").strip()
            if not name:
                continue
            data.append({"date": year, "label": name})
        if len(data) < 2:
            return None
        # sort chronologically when years are numeric
        try:
            data.sort(key=lambda d: int(d.get("date") or 0))
        except (ValueError, TypeError):
            pass
        author = str(candidate.get("name") or signals.get("author") or "")
        title = f"{author.split('/')[0].strip()} 的轨迹" if author else "项目轨迹"
        return Visualization(kind="timeline", title=title, data=tuple(data))

    if scene.scene_id == "mechanism":
        # Portfolio grid: 3 flagship projects with name + tagline.
        data2: list[dict[str, Any]] = []
        for p in projects[:3]:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name") or "").strip()
            tagline = str(p.get("tagline") or "").strip()
            if not name:
                continue
            # ProjectPortfolioGrid reads d.label (name) + d.side (tagline);
            # we use ``side`` because our schema reuses VisualizationDatum.
            data2.append({"label": name, "side": tagline})
        if len(data2) < 2:
            return None
        return Visualization(kind="comparison", title="作品集", data=tuple(data2))

    return None


_CODE_FENCE_RE = re.compile(r"^```([A-Za-z0-9_+\-]*)\s*$", re.MULTILINE)
_CODE_LANG_TO_EXT = {
    "python": "py", "py": "py",
    "typescript": "ts", "ts": "ts", "tsx": "tsx",
    "javascript": "js", "js": "js", "jsx": "jsx",
}
_SHELL_LANGS = {"bash", "sh", "shell", "zsh", "console", "shellscript"}


def _iter_readme_code_blocks(readme: str) -> list[tuple[str, list[str]]]:
    """Return all usable fenced code blocks from README as ``(lang, lines)``.

    A "usable" block has a recognised language tag, 4–18 non-blank lines
    after trimming, and no single line longer than 80 chars. Order in
    the returned list matches reading order in the README.
    """
    out: list[tuple[str, list[str]]] = []
    if not readme:
        return out
    matches = list(_CODE_FENCE_RE.finditer(readme))
    for i in range(0, len(matches) - 1, 2):
        lang_raw = matches[i].group(1).lower()
        if lang_raw not in _CODE_LANG_TO_EXT and lang_raw not in _SHELL_LANGS:
            continue
        body = readme[matches[i].end():matches[i + 1].start()]
        lines = [ln.rstrip() for ln in body.splitlines()]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not (4 <= len(lines) <= 18):
            continue
        if any(len(ln) > 80 for ln in lines):
            continue
        out.append((lang_raw, lines))
    return out


def _extract_code_editor_from_readme(readme: str, scene: DirectorScene) -> Visualization | None:
    """VSCode-style mock for ``mechanism`` scene — Python/TS/JS blocks only.

    Bash/shell blocks would render as code-with-line-numbers, but they're
    actually CLI commands and read more naturally as a terminal session.
    Those go to ``_extract_terminal_from_readme`` instead.

    Returning None lets the caller fall through to flow_chart / bar_chart.
    """
    if scene.scene_id != "mechanism":
        return None
    for lang_raw, lines in _iter_readme_code_blocks(readme):
        if lang_raw not in _CODE_LANG_TO_EXT:
            continue
        ext = _CODE_LANG_TO_EXT[lang_raw]
        return Visualization(
            kind="code_editor",
            title=f"quickstart.{ext}",
            caption=lang_raw,
            data=tuple({"text": ln} for ln in lines),
        )
    return None


def _extract_terminal_from_readme(readme: str, scene: DirectorScene) -> Visualization | None:
    """Terminal mock for ``context`` scene — bash/shell blocks only.

    Why context (not mechanism): the terminal aesthetic carries an
    "install / run / output" semantic which matches the context beat
    ("how do you USE it"). Mechanism is reserved for code-editor or
    comparison-table viz that explain HOW the implementation works.

    Each line is annotated as ``command`` (starts with ``$``, ``#``,
    ``>``) or ``output`` so the renderer can colour them differently.
    """
    if scene.scene_id != "context":
        return None
    for lang_raw, lines in _iter_readme_code_blocks(readme):
        if lang_raw not in _SHELL_LANGS:
            continue
        annotated = []
        for ln in lines:
            stripped = ln.lstrip()
            is_command = bool(stripped) and stripped[0] in {"$", "#", ">"}
            annotated.append({"text": ln, "kind": "command" if is_command else "output"})
        return Visualization(
            kind="terminal",
            title="terminal",
            caption=lang_raw,
            data=tuple(annotated),
        )
    return None


# Comparison-table extractor heuristic — looks for sentences in the
# mechanism voiceover that contrast a "before / traditional" pattern
# with the project being explained. Common script forms we mine:
#
#   "传统的 X 工具（比如 A、B）需要 Y"  ──> old side = A/B, label Y
#   "X 的思路是 Y，而 Z 需要 W"          ──> two-sided contrast on Y vs W
#
# The extractor stays cheap: 2 regex passes, no LLM call. Returning
# None lets the caller fall through to code_editor / flow_chart.
_COMPARISON_TRADITIONAL_RE = re.compile(
    # "传统的 X 工具/方式/...（比如 A、B）"
    # group(1) = noun phrase before suffix; group(2) = paren examples
    r"(?:传统的?|过去|以往|原来的?)([^。，,；;：:（(]{2,30}?)"
    r"(?:工具|方式|方案|做法|路线|脚本|框架)"
    r"\s*(?:[（(](?:比如|像|例如|包括)?\s*([^）)]{2,40})[）)])?"
)
_COMPARISON_NEW_THESIS_RE = re.compile(
    # "<Repo> 的思路/方式/做法 是: <thesis>"  (also accepts ":" or "：")
    # group(1) = thesis text, 6-60 chars stopping at sentence-end punct
    r"(?:[A-Za-z][A-Za-z0-9\-_]{2,}|[一-鿿]{2,})\s*"
    r"的(?:思路|方式|设计|做法|方案|路线)\s*[是为]?\s*[：:]?\s*"
    r"([^。！？]{6,60})"
)


# ---------- MockBrowserAgent (kind="browser_agent") ----------
# Animates an AI agent operating a browser: navigate → click → type/
# screenshot. Fires on ``extend`` scene of AI-tool content where the
# voiceover hints at "AI 操控/点击/搜索/截图" semantics. Renders as a
# Chrome-style window with a scripted mouse cursor moving between
# highlighted elements.
_BROWSER_AGENT_VERB_TO_ACTION = (
    ("打开", "navigate"),
    ("访问", "navigate"),
    ("导航", "navigate"),
    ("跳转", "navigate"),
    ("点击", "click"),
    ("点开", "click"),
    ("点", "click"),
    ("click", "click"),
    ("搜索", "type"),
    ("输入", "type"),
    ("填写", "type"),
    ("填表", "type"),
    ("type", "type"),
    ("截图", "screenshot"),
    ("screenshot", "screenshot"),
    ("查找", "type"),
    ("找到", "click"),
    ("选择", "click"),
)


def _extract_browser_agent_from_voiceover(scene: DirectorScene, repo_name: str = "") -> Visualization | None:
    """Synthesise a 3-step browser-agent demo from the extend voiceover.

    Targets ``extend`` scenes of AI tool / browser-automation content.
    Looks for action-verb hints ("点击" / "搜索" / "截图" / "填表" / ...)
    in the voiceover and assembles a 3-action sequence:

      1. navigate → an example URL (extracted or fallback)
      2. click    → first explicit click verb in voiceover
      3. type / screenshot → derived from second observed verb

    Returns None when fewer than 2 distinct action verbs are present —
    the caller falls through to no-viz typography.
    """
    if scene.scene_id != "extend":
        return None
    text = (scene.voiceover or "")
    if not text:
        return None
    found_actions: list[str] = []
    seen: set[str] = set()
    for verb, action in _BROWSER_AGENT_VERB_TO_ACTION:
        if verb in text and action not in seen:
            found_actions.append(action)
            seen.add(action)
            if len(found_actions) >= 3:
                break
    # Need at least 2 distinct action types to assemble a useful sequence.
    if len(found_actions) < 2:
        return None
    # Always lead with navigate even if the voiceover skipped that verb —
    # the viewer needs a "we're on a page" anchor before the click lands.
    if "navigate" not in found_actions:
        found_actions.insert(0, "navigate")
    found_actions = found_actions[:3]

    # Step labels — what shows in the cursor tooltip on each beat.
    label_map = {
        "navigate": "AI 打开网页",
        "click": "AI 点击元素",
        "type": "AI 输入查询",
        "screenshot": "AI 截图保存",
    }
    # Fake target URL — first http link in voiceover, else placeholder.
    url_match = re.search(r"https?://[^\s，。\)）]+", text)
    landing_url = url_match.group(0) if url_match else f"https://example.com/{repo_name or 'demo'}"
    landing_url = landing_url[:60]

    steps: list[dict[str, str]] = []
    for action in found_actions:
        target = ""
        if action == "navigate":
            target = landing_url
        elif action == "click":
            target = "提交按钮"
        elif action == "type":
            target = "海外 AI 工具"
        elif action == "screenshot":
            target = "page.png"
        steps.append({
            "action": action,
            "label": label_map.get(action, action),
            "target": target,
        })
    return Visualization(
        kind="browser_agent",
        title=landing_url,
        caption=(repo_name or "AI Agent") + " · 演示",
        data=tuple(steps),
    )


# ---------- MockStarHistory (kind="star_history") ----------
# Synthesises a smooth growth curve from current star count + repo
# creation date. GitHub doesn't expose star history without per-event
# fetching, so we produce a deterministic monthly curve that ENDS at
# the real ``star_count`` value and starts near zero at the project's
# first release. Renders as a line chart with an end-point glow ball.
def _extract_star_history(scene: DirectorScene, cache_dir: Path | None) -> Visualization | None:
    """Pull stars + creation_date from github_meta.json and synthesise a
    12-point monthly trajectory.

    Fires on ``takeaway`` scenes of github_open_source_project content
    where the script naturally references the star count one more time
    ("9.2 万星表示关注度高，但不代表..."). The viewer sees the curve
    contextualise the number rather than just reading it again.
    """
    if scene.scene_id != "takeaway" or cache_dir is None:
        return None
    base = Path(cache_dir)
    candidates = [
        base / "00_source" / "github_meta.json",
        base.parent / "00_source" / "github_meta.json",
    ]
    meta_path: Path | None = None
    for c in candidates:
        if c.exists():
            meta_path = c
            break
    if meta_path is None:
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # Field names vary across collectors: ``stars`` (current github_collector),
    # ``star_count`` (legacy), ``stargazers_count`` (raw GitHub API). Same
    # for repo creation: ``published_at`` is what github_collector writes
    # to mean "first GitHub publish date", while ``created_at`` is the
    # local artifact write time on our side, NOT the repo birth.
    star_count_raw = meta.get("stars") or meta.get("star_count") or meta.get("stargazers_count") or 0
    try:
        final_count = int(star_count_raw)
    except (TypeError, ValueError):
        return None
    if final_count < 1000:  # below 1k → curve looks empty / not impressive
        return None
    created_raw = meta.get("published_at") or meta.get("repo_created_at") or ""
    months_active = 14
    if isinstance(created_raw, str) and created_raw:
        try:
            from datetime import datetime, timezone
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta_months = max(2, (now.year - created.year) * 12 + (now.month - created.month))
            months_active = min(36, delta_months)
        except ValueError:
            pass
    # Synthesise a sigmoid-ish curve: slow start, fast middle, taper.
    # Eight points over the active period gives a clean sparkline.
    n_points = 8
    points: list[dict[str, Any]] = []
    for i in range(n_points):
        t = i / (n_points - 1)
        # 1 / (1 + exp(-12*(t-0.5))) ramps cleanly between near-0 and 1.
        import math
        s = 1.0 / (1.0 + math.exp(-12 * (t - 0.5)))
        # Anchor end at exactly final_count; start near a realistic 1-2% of total.
        anchor_low = max(50, int(final_count * 0.02))
        value = int(anchor_low + (final_count - anchor_low) * s)
        # Month label — months ago from now.
        months_ago = int(round((1 - t) * (months_active - 1)))
        points.append({"label": f"-{months_ago}m" if months_ago else "now", "value": value})
    return Visualization(
        kind="star_history",
        title=meta.get("repo_name") or meta.get("full_name") or "stars",
        caption=f"{final_count:,} ⭐",
        data=tuple(points),
    )


# ---------- MockMRRDashboard (kind="mrr_dashboard") ----------
# Fake Stripe-style revenue panel for build-in-public creator content
# (Pieter Levels / Greg Isenberg / Rob Walling). Pulls revenue numbers
# from voiceover regex when present; otherwise uses a placeholder so
# the visual still lands when the script implies "他赚到钱了" without
# stating an exact figure.
_MRR_RE = re.compile(
    r"(?:[\$￥]\s*([\d,.]+)\s*([KMB万亿]?))(?:\s*[/／每]?\s*(?:月|MRR|每月|year|年|ARR|每年))?",
    re.IGNORECASE,
)


def _extract_mrr_dashboard(scene: DirectorScene) -> Visualization | None:
    """Build a fake revenue dashboard for creator_portrait takeaway scenes.

    Trigger is intentionally narrow:
      * scene.kind == "creator"
      * scene.scene_id == "takeaway"  (NOT hook — hook is reserved for
        portrait_card + tweet_quote_card to lock in "who is this
        person" in the first 3 seconds; the dashboard would override
        that polish)
      * voiceover MUST have an explicit numeric revenue pattern —
        ``$NN`` / ``$XK`` / ``XK MRR`` / ``年入 $XM``. Loose words like
        "赚到钱了" / "盈利" alone are NOT enough — without a number the
        dashboard's ``$X0K`` placeholder reads as fake.

    Returns None when no concrete number is present so the caller falls
    through to typography or other viz instead of a hollow mock.
    """
    if scene.kind != "creator":
        return None
    if scene.scene_id != "takeaway":
        return None
    text = scene.voiceover or ""
    m = _MRR_RE.search(text)
    if m is None:
        return None
    mrr_value = "$X0K"
    growth_pct = 12
    customers = 1842
    if True:
        n_raw, suffix = m.group(1), (m.group(2) or "").upper()
        try:
            n_clean = float(n_raw.replace(",", ""))
            multiplier = 1
            if suffix in ("K",):
                multiplier = 1_000
            elif suffix in ("M",):
                multiplier = 1_000_000
            elif suffix == "万":
                multiplier = 10_000
            scaled = int(n_clean * multiplier)
            mrr_value = f"${n_raw}{suffix or ''}"
            customers = max(120, min(50_000, scaled // 80))  # ~$80 ARPU
        except ValueError:
            pass
    # Sparkline (8 points, smooth uptrend).
    sparkline = []
    import math
    for i in range(8):
        t = i / 7
        v = 0.45 + 0.55 * (1.0 / (1.0 + math.exp(-7 * (t - 0.5))))
        sparkline.append(round(v, 3))
    return Visualization(
        kind="mrr_dashboard",
        title="Stripe Dashboard",
        caption="MRR · last 30 days",
        data=tuple([
            {"key": "mrr", "value": mrr_value, "trend": "+", "growth": f"+{growth_pct}%"},
            {"key": "customers", "value": f"{customers:,}", "trend": "+", "growth": "+8%"},
            {"key": "sparkline", "points": sparkline},
        ]),
    )


def _extract_comparison_table_from_voiceover(scene: DirectorScene, repo_name: str = "") -> Visualization | None:
    """Build a 'before vs after' table from contrast cues in the voiceover.

    Mechanism narrations that explain "how X works" almost always
    contain a "before / after" beat — "传统的 Selenium 脚本需要手写每一步...
    browser-use 的思路是把任务交给 LLM..." The table renders as two
    columns with 3-4 dimension rows so the viewer can see, at a glance,
    what the new project changes.

    Heuristic only — no LLM call. We extract:
      * old_side: the brand(s) named after "传统的" / "（比如 ...）"
      * new_thesis: the clause after "<repo> 的思路 / 的方式 / 的做法 是 ..."
    Then synthesise 3 dimension rows with default labels (写法 / 维护 /
    抽象层) so the table reads as informative, not as a one-liner.

    Returns None when neither side resolves cleanly — caller falls
    through to code_editor / flow_chart / bar_chart.
    """
    if scene.scene_id != "mechanism":
        return None
    text = scene.voiceover or ""
    if not text:
        return None
    # Old side
    old_side_label = ""
    old_side_examples = ""
    m_old = _COMPARISON_TRADITIONAL_RE.search(text)
    if m_old:
        old_side_label = (m_old.group(1) or "").strip()
        old_side_examples = (m_old.group(2) or "").strip()
    new_thesis = ""
    m_new = _COMPARISON_NEW_THESIS_RE.search(text)
    if m_new:
        new_thesis = m_new.group(1).strip()
    if not (old_side_label or old_side_examples) or not new_thesis:
        return None
    # Headers
    old_header = old_side_examples or old_side_label or "传统方法"
    new_header = repo_name or "新方法"
    # 3 dimension rows — values pulled from the surrounding sentences
    # when possible, with sensible Chinese-language defaults otherwise.
    rows = (
        {
            "label": "写法",
            "left": "脚本 + 选择器",
            "right": new_thesis[:32],
        },
        {
            "label": "应对改版",
            "left": "网页一变就重写",
            "right": "AI 自动重新规划",
        },
        {
            "label": "抽象层",
            "left": "操作步骤级",
            "right": "任务描述级",
        },
    )
    return Visualization(
        kind="comparison_table",
        title="对比",
        caption=f"{old_header}  vs  {new_header}",
        data=rows,
    )


def _read_readme_for_cache_dir(cache_dir: Path | None) -> str:
    """Best-effort fetch of the project README from the artifact tree.

    Callers pass ``cache_dir`` either as ``output/<id>`` (current
    media_producer convention) or as ``output/<id>/.cache`` (legacy
    LLM-flow extractor). README sits at
    ``output/<id>/00_source/readme.md`` for github-source candidates.
    Try both locations so we don't depend on which form the caller
    happens to pass. Returns empty string when neither resolves — the
    code editor extractor handles that as "no block, fall through".
    """
    if cache_dir is None:
        return ""
    base = Path(cache_dir)
    candidates = [
        base / "00_source" / "readme.md",
        base.parent / "00_source" / "readme.md",
    ]
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    return ""


def _extract_secondary_visualization_for_scene(
    scene: DirectorScene,
    primary: Visualization | None,
    *,
    cache_dir: Path | None = None,
    used_kinds: frozenset[str] = frozenset(),
) -> Visualization | None:
    """Pick a SECOND viz of a different kind for a single scene.

    Why two viz per scene: a mechanism scene with 11 shots gets 1 viz on
    shot_01 and 10 typography shots after — the viewer sees one
    moment of "data" then 40 seconds of text cards. Adding a second viz
    in the middle of the scene (shot ≈ count/2) gives the eye a second
    rhythmic anchor and lets us surface a different facet of the same
    content (e.g. mechanism shot_01 = comparison_table, shot_06 =
    code_editor showing the actual API call).

    ``used_kinds`` is the set of viz kinds already attached anywhere in
    the video (primary + secondary across all earlier scenes). Caller
    threads it through so we never show the same kind twice — e.g.
    when context_shot_06 already ran code_editor (the same README's
    python block), mechanism_shot_06 falls through to flow_chart
    instead of replaying the same code.

    Returns None when no different viz kind is extractable, in which
    case the mid-scene shot stays typography. Required: ``primary``
    must be non-None — we only inject a secondary when the primary
    already landed (otherwise both slots are typography anyway).
    """
    if primary is None:
        return None
    primary_kind = primary.kind
    readme = _read_readme_for_cache_dir(cache_dir)

    def _try_code_editor() -> Visualization | None:
        if "code_editor" in used_kinds or primary_kind == "code_editor" or not readme:
            return None
        for lang_raw, lines in _iter_readme_code_blocks(readme):
            if lang_raw not in _CODE_LANG_TO_EXT:
                continue
            ext = _CODE_LANG_TO_EXT[lang_raw]
            return Visualization(
                kind="code_editor",
                title=f"quickstart.{ext}",
                caption=lang_raw,
                data=tuple({"text": ln} for ln in lines),
            )
        return None

    def _try_flow_chart() -> Visualization | None:
        if "flow_chart" in used_kinds or primary_kind == "flow_chart":
            return None
        return _extract_flow_chart(scene)

    def _try_bar_chart() -> Visualization | None:
        if "bar_chart" in used_kinds or primary_kind == "bar_chart":
            return None
        return _extract_bar_chart(scene)

    def _try_terminal() -> Visualization | None:
        if "terminal" in used_kinds or primary_kind == "terminal" or not readme:
            return None
        for lang_raw, lines in _iter_readme_code_blocks(readme):
            if lang_raw not in _SHELL_LANGS:
                continue
            annotated = []
            for ln in lines:
                stripped = ln.lstrip()
                is_command = bool(stripped) and stripped[0] in {"$", "#", ">"}
                annotated.append({"text": ln, "kind": "command" if is_command else "output"})
            return Visualization(
                kind="terminal",
                title="terminal",
                caption=lang_raw,
                data=tuple(annotated),
            )
        return None

    # Per-scene fallback chain. First non-None wins. Each scene tries
    # MULTIPLE candidate kinds — if the first is already used elsewhere,
    # the next one runs. This is what fixes the previous "code_editor
    # appears in BOTH context_shot_06 AND mechanism_shot_06" defect.
    # Per-scene candidate chain. ``code_editor`` is reserved for
    # ``mechanism`` (the "它怎么做到的" beat — code IS the mechanism)
    # and only falls to ``extend`` if mechanism didn't claim it. Other
    # scenes never request code_editor so we don't burn the unique
    # asset on a less-relevant beat.
    chains: dict[str, list] = {
        "mechanism": [_try_code_editor, _try_flow_chart, _try_terminal, _try_bar_chart],
        "context":   [_try_terminal, _try_flow_chart, _try_bar_chart],
        "extend":    [_try_flow_chart, _try_code_editor, _try_bar_chart],
        "takeaway":  [_try_bar_chart, _try_flow_chart],
    }
    for fn in chains.get(scene.scene_id, []):
        viz = fn()
        if viz is not None:
            return viz
    return None


def _extract_visualization_for_scene(
    scene: DirectorScene,
    *,
    llm: "LLMClient | None" = None,
    cache_dir: Path | None = None,
) -> Visualization | None:
    """Pick at most ONE visualization per scene.

    Order of preference:
      0. creator timeline / portfolio when scene.kind == "creator" and
         signals.projects is available — these are deterministic, fact-
         carrying viz that the LLM-flow / bar_chart heuristics cannot
         match because the data is structured upstream.
      1. code_editor (mechanism scenes only) — first usable fenced code
         block from README. Renders as a VSCode mock with actual API
         lines, beating yet another README screenshot.
      2. flow_chart via LLM (when ``llm`` is provided — produces clean
         step labels with explicit verb + noun, no truncation artefacts).
      3. flow_chart via heuristic (deterministic fallback when LLM is
         unavailable or returned an unusable empty list).
      4. bar_chart  (numbers when present; fires across all scenes).

    Returning None is the common case and means "render the existing
    typography spec for this scene".
    """
    creator_viz = _extract_creator_timeline(scene, cache_dir)
    if creator_viz is not None:
        return creator_viz
    # Creator-portrait revenue dashboard — fires before timeline check
    # only on hook / takeaway scenes where revenue is explicitly cued.
    mrr_viz = _extract_mrr_dashboard(scene)
    if mrr_viz is not None:
        return mrr_viz
    # Repo-name passed into comparison table for the "X vs <repo>" header.
    # Best-effort: pull from cache_dir tail (output/gh_<owner>_<repo>/...).
    repo_name = ""
    if cache_dir is not None:
        tail = Path(cache_dir).name if Path(cache_dir).name != ".cache" else Path(cache_dir).parent.name
        if tail.startswith("gh_") and "_" in tail[3:]:
            repo_name = tail.split("_", 2)[-1]
    table_viz = _extract_comparison_table_from_voiceover(scene, repo_name)
    if table_viz is not None:
        return table_viz
    # Browser agent demo — extend scene of AI/automation tool content.
    agent_viz = _extract_browser_agent_from_voiceover(scene, repo_name)
    if agent_viz is not None:
        return agent_viz
    # Star history sparkline — takeaway scene of github content.
    star_viz = _extract_star_history(scene, cache_dir)
    if star_viz is not None:
        return star_viz
    readme_text = _read_readme_for_cache_dir(cache_dir)
    code_viz = _extract_code_editor_from_readme(readme_text, scene)
    if code_viz is not None:
        return code_viz
    terminal_viz = _extract_terminal_from_readme(readme_text, scene)
    if terminal_viz is not None:
        return terminal_viz
    if llm is not None:
        flow = _extract_flow_chart_via_llm(scene, llm, cache_dir)
        if flow is not None:
            return flow
    flow = _extract_flow_chart(scene)
    if flow is not None:
        return flow
    return _extract_bar_chart(scene)


def _keyword_phrase(scene: DirectorScene, *, max_count: int = 3) -> str:
    """Compact keyword overlay derived from ``scene.subtitle_keywords``.

    Falls back to ``scene.screen_text`` so we never paint a hardcoded slogan
    onto a scene whose narrative has already moved on.
    """
    keywords = [str(k).strip() for k in scene.subtitle_keywords if str(k).strip()]
    if keywords:
        return " / ".join(keywords[:max_count])
    return scene.screen_text or "关键画面"


def _shot_specs_for_creator_scene(scene: DirectorScene) -> list[dict[str, str]]:
    """Shot specs for creator_portrait sources (Pieter Levels / Greg Isenberg).

    Replaces the repo-evidence + keyword-punch combo with portrait /
    timeline / tweet-quote / portfolio cards. Each scene_id picks the
    template that matches the narrative beat:
      hook → portrait_card (who is this person, big avatar + name + tag)
      context → timeline_landscape (career / project trajectory)
      mechanism → project_portfolio_grid (3 flagship projects in one frame)
      extend → tweet_quote_card (a quotable X post for proof)
      takeaway → judgement_card (sharp closing opinion)
    """
    keyword_overlay = _keyword_phrase(scene)
    primary_overlay = scene.screen_text or keyword_overlay
    asset_path = scene.asset_path

    if scene.scene_id == "hook":
        return [
            {
                "visual_type": "portrait_card",
                "screen_text": primary_overlay,
                "asset_path": asset_path,
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "用人物头像 + 一行 tag 完成前三秒钩子,锁定主角是谁。",
            },
            {
                "visual_type": "tweet_quote_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "用一条爆款 X 推文支撑钩子的反差感。",
            },
            {
                "visual_type": "keyword_punch_card",
                # punch cards must stay short — keyword phrase, not the long
                # primary_overlay sentence. The build_shot_list_from_scenes
                # voiceover-slicing pass also skips punch types so this stays.
                "screen_text": keyword_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "节奏卡承接,把人物核心标签压成可记忆文字。",
            },
        ]
    if scene.scene_id == "context":
        return [
            {
                "visual_type": "timeline_landscape",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "用时间线展示创作者的项目轨迹,给观众结构感。",
            },
            {
                "visual_type": "story_beat_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "叙事章节板式,给一个'现在在讲故事'的阅读锚点。",
            },
            {
                "visual_type": "signal_pulse_card",
                "screen_text": keyword_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "节奏卡承接关键词。",
            },
        ]
    if scene.scene_id == "mechanism":
        return [
            {
                "visual_type": "project_portfolio_grid",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "3 列项目卡展示创作者的产品组合,一眼看清他在做什么。",
            },
            {
                "visual_type": "step_list_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "snap_zoom",
                "highlight": "center",
                "purpose": "把他的工作方法拆成 1/2/3 步,制造步骤感。",
            },
            {
                "visual_type": "keyword_punch_card",
                "screen_text": keyword_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "节奏卡承接,避免长时间停在静态网格。",
            },
        ]
    if scene.scene_id == "extend":
        return [
            {
                "visual_type": "tweet_quote_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "用一条具体推文给延展场景一个'真实声音'的支点。",
            },
            {
                "visual_type": "quote_highlight_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "引号卡承接,跟前面的推文卡形成节奏变化。",
            },
            {
                "visual_type": "keyword_punch_card",
                "screen_text": keyword_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "用关键词卡完成 3-5 秒节奏变化。",
            },
        ]
    if scene.scene_id in ("boundary", "takeaway"):
        return [
            {
                "visual_type": "judgement_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "结尾给一句强判断,让观众带走一个观点。",
            },
            {
                "visual_type": "portrait_card",
                "screen_text": primary_overlay,
                "asset_path": asset_path,
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "回到人物特写,把判断锚定在主角身上。",
            },
            {
                "visual_type": "keyword_punch_card",
                "screen_text": keyword_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "节奏卡承接收尾。",
            },
        ]
    # Fallback: any other scene_id → portrait_card + signal_pulse + keyword
    return [
        {
            "visual_type": "portrait_card",
            "screen_text": primary_overlay,
            "asset_path": asset_path,
            "motion": "slow_push",
            "highlight": "center",
            "purpose": "通用 creator scene 默认走人物卡。",
        },
        {
            "visual_type": "signal_pulse_card",
            "screen_text": keyword_overlay,
            "asset_path": "",
            "motion": "quick_push",
            "highlight": "center",
            "purpose": "节奏卡。",
        },
    ]


def _shot_specs_for_scene(scene: DirectorScene) -> list[dict[str, str]]:
    # Creator-portrait sources (Pieter Levels / Greg Isenberg) bypass the
    # default tool-explainer templates and use the dedicated portrait
    # routing. See _shot_specs_for_creator_scene above.
    if scene.kind == "creator":
        return _shot_specs_for_creator_scene(scene)
    asset_path = scene.asset_path
    keyword_overlay = _keyword_phrase(scene)
    primary_overlay = scene.screen_text or keyword_overlay
    # Branch ordering matters: scene_id-specific layouts must beat generic
    # role-based layouts. The legacy ``readme_image`` branch swallowed the
    # mechanism/extend/takeaway scenes because ``_build_domestic_scenes``
    # tags some of them with ``visual_role="readme_image"`` for asset
    # selection — keeping that branch first meant we always fell back to
    # readme_visual_card and the new step/quote/judgement templates were
    # never reached. scene_id branches now come first.
    if scene.scene_id == "context":
        # "故事是怎么发生的" — narrative chapter-change. story_beat (slate)
        # leads, ONE evidence shot anchors to real screenshot, then 3
        # typography templates (signal pulse / quote / keyword punch /
        # impact title) fill rhythm beats. _expand_specs guarantees the
        # evidence shot fires once even if the scene has 11 shots.
        return [
            {
                "visual_type": "story_beat_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "叙事章节板式：给观众一个「现在在讲故事」的阅读锚点。",
            },
            {
                "visual_type": "repo_evidence_zoom",
                "screen_text": keyword_overlay,
                "asset_path": asset_path,
                "motion": "snap_zoom",
                "highlight": scene.highlight or "repo_header",
                "purpose": "用局部放大接住口播的具体事实证据。",
            },
            {
                "visual_type": "signal_pulse_card",
                "screen_text": keyword_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "抽象的信号条动画隔开素材镜头，承接关键词。",
            },
            {
                "visual_type": "quote_highlight_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "引号卡承接背景叙事的具体表达。",
            },
            {
                "visual_type": "keyword_punch_card",
                "screen_text": keyword_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "关键词卡压实信息点，制造节奏感。",
            },
        ]
    if scene.scene_id == "hook":
        return [
            {
                "visual_type": "impact_title_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "snap_zoom",
                "highlight": "center",
                "purpose": "用强判断和品牌包装完成前三秒钩子。",
            },
            {
                "visual_type": "repo_full_bleed",
                "screen_text": keyword_overlay,
                "asset_path": asset_path,
                "motion": "slow_push",
                "highlight": scene.highlight or "repo_header",
                "purpose": "立刻给出项目来源和可信上下文。",
            },
            {
                "visual_type": "keyword_punch_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "把口播关键词压成可记忆的屏幕文字。",
            },
            {
                "visual_type": "story_beat_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "叙事卡承接钩子段的事实展开。",
            },
            {
                "visual_type": "signal_pulse_card",
                "screen_text": keyword_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "节奏卡隔开重复模板，让钩子段有更密的视觉切换。",
            },
        ]
    if scene.scene_id in ("boundary", "takeaway"):
        return [
            {
                "visual_type": "judgement_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "结尾给一句强判断，让观众带走一个观点。",
            },
            {
                "visual_type": "repo_evidence_zoom",
                "screen_text": keyword_overlay,
                "asset_path": asset_path,
                "motion": "snap_zoom",
                "highlight": scene.highlight or "repo_header",
                "purpose": "回到真实项目证据，支撑趋势判断。",
            },
            {
                "visual_type": "keyword_punch_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "用关键词卡承接口播节奏。",
            },
            {
                "visual_type": "story_beat_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "叙事卡分隔判断点，避免连续 judgement_card 单调。",
            },
            {
                "visual_type": "signal_pulse_card",
                "screen_text": keyword_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "节奏卡承接收尾段。",
            },
        ]
    if scene.scene_id == "mechanism":
        return [
            {
                "visual_type": "step_list_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "snap_zoom",
                "highlight": "center",
                "purpose": "把执行机制拆成 1/2/3 三步，制造步骤感。",
            },
            {
                "visual_type": "repo_evidence_zoom",
                "screen_text": keyword_overlay,
                "asset_path": asset_path,
                "motion": "snap_zoom",
                "highlight": scene.highlight or "center",
                "purpose": "回到真实项目截图佐证机制。",
            },
            {
                "visual_type": "keyword_punch_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "节奏卡承接，避免长时间停在素材上。",
            },
            {
                "visual_type": "quote_highlight_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "引号卡承接旁白中的关键短句。",
            },
            {
                "visual_type": "signal_pulse_card",
                "screen_text": keyword_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "节奏卡分隔 step_list 重复，让 mechanism 有更多视觉切换。",
            },
        ]
    if scene.scene_id == "extend":
        return [
            {
                "visual_type": "quote_highlight_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "用引号卡突出延展场景，跟前面的镜头分开。",
            },
            {
                "visual_type": "repo_full_bleed",
                "screen_text": keyword_overlay,
                "asset_path": asset_path,
                "motion": scene.motion or "slow_push",
                "highlight": scene.highlight or "repo_header",
                "purpose": "用真实素材为延展用例提供证据。",
            },
            {
                "visual_type": "keyword_punch_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "用关键词卡完成 3-5 秒节奏变化。",
            },
            {
                "visual_type": "story_beat_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "slow_push",
                "highlight": "center",
                "purpose": "叙事卡接住延展段的具体推论。",
            },
            {
                "visual_type": "signal_pulse_card",
                "screen_text": keyword_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "节奏卡分隔重复模板，让延展段视觉更密。",
            },
        ]
    # Generic role-based fallback for any remaining scene_id (china,
    # custom v6 scenes, …). README image scenes still get readme_visual_card
    # here because a real README diagram is more valuable than a generic
    # repo screenshot — but only if the scene_id-specific branches above
    # didn't already claim this scene.
    if scene.visual_role == "readme_image":
        return [
            {
                "visual_type": "readme_visual_card",
                "screen_text": primary_overlay,
                "asset_path": asset_path,
                "motion": scene.motion,
                "highlight": scene.highlight,
                "purpose": "用 README 图片或图示解释机制。",
            },
            {
                "visual_type": "repo_evidence_zoom",
                "screen_text": keyword_overlay,
                "asset_path": asset_path,
                "motion": "snap_zoom",
                "highlight": scene.highlight or "center",
                "purpose": "放大素材中的关键证据区域。",
            },
            {
                "visual_type": "keyword_punch_card",
                "screen_text": primary_overlay,
                "asset_path": "",
                "motion": "quick_push",
                "highlight": "center",
                "purpose": "在素材之间插入节奏卡，避免长时间静态画面。",
            },
        ]
    return [
        {
            "visual_type": "repo_full_bleed",
            "screen_text": primary_overlay,
            "asset_path": asset_path,
            "motion": scene.motion,
            "highlight": scene.highlight,
            "purpose": "展示项目或仓库全貌，承接口播事实。",
        },
        {
            "visual_type": "repo_evidence_zoom",
            "screen_text": keyword_overlay,
            "asset_path": asset_path,
            "motion": "snap_zoom",
            "highlight": scene.highlight or "center",
            "purpose": "用局部高亮制造剪辑层次。",
        },
        {
            "visual_type": "keyword_punch_card",
            "screen_text": primary_overlay,
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


def assign_scene_timing(
    plan: DirectorPlan,
    duration: float,
    *,
    llm: "LLMClient | None" = None,
    cache_dir: Path | None = None,
) -> DirectorPlan:
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
                # MUST forward kind — without this, timed scenes default to
                # kind="tool" and creator-portrait routing collapses to the
                # repo_full_bleed / step_list_card combo even though
                # _build_domestic_scenes correctly tagged kind="creator".
                kind=scene.kind,
            )
        )
        cursor = end
    return plan.with_timing(timed, llm=llm, cache_dir=cache_dir)


def _landscape_friendly_path(path: Path) -> Path:
    """Return a path that fits a 16:9 ScreenshotFrame without black-bar collapse.

    Background: GitHub ``snapshot_github_repo`` captures with ``full_page=True``,
    which on most repos produces 1440×5000+ portrait monsters. When Remotion
    drops one of those into a landscape browser-chrome shot, ``object-fit: contain``
    leaves ~80% of the screen black on the sides — exactly what killed the
    Aider 35-60s segment in the first cut.

    For any image with aspect < 0.7 (taller than ~16:11), we crop the top
    16:9 hero band into a sibling ``<stem>_hero.<suffix>`` and return that.
    The hero region is the most information-dense part of a GitHub README
    page (repo header + first paragraph + first README image), so it's the
    right slice to keep when the rest of the page can't fit anyway.

    Returns the original path on any failure (Pillow missing, parse error,
    etc.) — degrade visibly rather than silently break the pipeline.
    """
    if not path.exists():
        return path
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return path  # SVG / other vector — skip
    try:
        from PIL import Image
    except ImportError:
        return path
    derived = path.with_name(f"{path.stem}_hero{path.suffix}")
    if derived.exists() and derived.stat().st_mtime >= path.stat().st_mtime:
        return derived
    try:
        with Image.open(path) as img:
            width, height = img.size
            if width <= 0 or height <= 0:
                return path
            aspect = width / height
            if aspect >= 0.7:
                return path  # already landscape-ish, leave alone
            # Take the top region matching 16:9 of the source width.
            target_height = max(1, int(round(width * 9 / 16)))
            target_height = min(target_height, height)
            cropped = img.crop((0, 0, width, target_height))
            cropped.save(derived)
        return derived
    except Exception:
        return path


def collect_visual_assets(writer: ArtifactWriter) -> list[dict[str, Any]]:
    """Aggregate every still asset the upstream collectors have left for us.

    Source priority (each contributes if present; we cap at 12 total to
    keep the visualization shot pool diverse but not bloated):

      1. ``browser_agent_assets.json``  — ad-hoc browser captures.
      2. ``snapshot_status.json``       — repo screenshots (GitHub).
      3. ``readme_images.json``         — README diagrams / hero images.
      4. ``youtube_assets.json``        — YouTube thumbnail + 8 keyframes
                                          across the source video. *Used to
                                          be silently ignored — that's why
                                          YT-sourced renders fell back to
                                          pure typography and the user
                                          flagged them as "PPT-like with
                                          no real footage".*

    Each asset record is normalised to ``{path, role, label}``. The
    ``role`` is the discriminator the renderer uses to pick chrome
    (``youtube_*`` → browser/youtube tab, ``repo_*`` → terminal, etc.).
    """
    assets: list[dict[str, Any]] = []
    browser_agent_assets = _read_json_if_exists(writer.output_path("browser_agent_assets.json"))
    for asset in browser_agent_assets.get("assets", []) if isinstance(browser_agent_assets.get("assets"), list) else []:
        if not isinstance(asset, dict):
            continue
        path = _existing_path(asset.get("workspace_path"))
        if path and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            assets.append(
                {
                    "path": str(path),
                    "role": str(asset.get("role") or "browser_source_screenshot"),
                    "label": str(asset.get("label") or "浏览器素材截图"),
                }
            )

    snapshot_status = _read_json_if_exists(writer.output_path("snapshot_status.json"))
    for screenshot in snapshot_status.get("screenshots", []) if isinstance(snapshot_status.get("screenshots"), list) else []:
        if not isinstance(screenshot, dict):
            continue
        path = _existing_path(screenshot.get("workspace_path"))
        if not path:
            continue
        # full_page screenshots are 1440x5000+ portraits — crop to the hero
        # region so they don't collapse to 80% black bars in landscape.
        # Creator profile shots are already viewport-only so the crop is
        # a no-op for them, but we keep the path consistent.
        path = _landscape_friendly_path(path)
        # Honor the role tag set upstream (snapshot_creator_profile sets
        # creator_* roles; legacy snapshot_github_repo sets nothing → defaults
        # to repo_snapshot for back-compat).
        role = str(screenshot.get("role") or "repo_snapshot")
        assets.append({"path": str(path), "role": role, "label": str(screenshot.get("label") or "仓库截图")})

    readme_images = _read_json_if_exists(writer.output_path("readme_images.json"))
    for image in readme_images.get("images", []) if isinstance(readme_images.get("images"), list) else []:
        if not isinstance(image, dict):
            continue
        path = _existing_path(image.get("workspace_path"))
        # 接受 SVG —— GitHub README 普遍用 SVG 放 logo / demo 录屏
        # (例如 aider 的 screencast.svg 是 118KB 的真实操作录屏图)。
        # 之前只接受 png/jpg 导致 SVG-heavy 的项目 (Aider / Excalidraw
        # 这一类) 在 collect_visual_assets 里只剩 1 张主页 snapshot,
        # asset_role_count=1, 直接卡死 §15 v0.4 的"≥3 类真实素材"验收。
        # Remotion 的 <Img> 走 chromium <img> tag，原生支持 SVG。
        if path and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
            # SVG badges (shields.io 的 stars / installs) 信息密度低且
            # 视觉重复,不适合做 evidence shot；按文件大小过滤,纯 badge
            # SVG 通常 < 8KB,真实截图/diagram 一般 ≥ 12KB。
            try:
                if path.suffix.lower() == ".svg" and path.stat().st_size < 8000:
                    continue
            except OSError:
                continue
            assets.append({"path": str(path), "role": "readme_image", "label": f"README 素材 {len(assets) + 1}"})

    # YouTube source assets — thumbnail + per-timestamp keyframes from
    # the ``download_youtube_assets`` stage. We deliberately skip the
    # thumbnail in the keyframe slot because the cover sequence already
    # uses it — duplicating it as an in-body shot would feel repetitive.
    # The keyframes get role ``youtube_keyframe`` so the chrome resolver
    # wraps them in a ``www.youtube.com/watch`` browser bar instead of a
    # GitHub-style terminal frame.
    youtube_assets = _read_json_if_exists(writer.output_path("youtube_assets.json"))
    for asset in youtube_assets.get("assets", []) if isinstance(youtube_assets.get("assets"), list) else []:
        if not isinstance(asset, dict):
            continue
        role = str(asset.get("role") or "")
        if role == "youtube_thumbnail":
            # Used by cover sequence; don't repeat as a body shot.
            continue
        path = _existing_path(asset.get("workspace_path"))
        if path and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            assets.append(
                {
                    "path": str(path),
                    "role": role or "youtube_keyframe",
                    "label": str(asset.get("label") or "视频片段"),
                    "timestamp_seconds": asset.get("timestamp_seconds"),
                }
            )

    return assets[:12]


_SCRIPT_SECTION_KEYS = (
    # Map scene slot → list of acceptable ## subsection titles in the
    # rewriter's output. Order matters: first match wins.
    #
    # New narrative-only structure (2026-05): we dropped "对中文用户/启发" and
    # "边界声明" because both segments were producing 官话腔 / preachy CCP-style
    # writeups that the user explicitly flagged. The five slots below are now
    # pure storytelling beats. Legacy aliases are kept so older
    # chinese_script.md files still parse during the cutover.
    ("钩子", "为什么突然值得关注", "Why now", "why_now", "开场"),
    ("故事是怎么发生的", "故事", "海外发生了什么", "海外发生", "what_happened_overseas"),
    ("它到底怎么做到的", "它怎么做到", "它解决什么问题", "解决什么问题", "解决的问题", "problem_solved", "它到底解决什么"),
    (
        "它还能干什么",
        "还能干什么",
        "更多场景",
        # Legacy aliases that used to drive this slot (will be reused if the
        # LLM ever falls back to old-style headings).
        "对中文用户/开发者/创作者/创业者的启发",
        "对中文用户的启发",
        "中文用户怎么看",
        "启发",
        "insight",
    ),
    (
        "一点感慨",
        "感慨",
        "趋势判断",
        # Legacy aliases.
        "边界：不承诺收益、不夸大、不照搬",
        "边界",
        "boundary",
    ),
)


def _extract_script_sections(script_markdown: str) -> dict[str, str]:
    """Pull the five ``## ...`` voiceover subsections out of
    ``chinese_script.md`` so each director scene can adopt the rewriter's
    actual prose instead of a hard-coded template.

    We only mine the block under ``# 口播稿`` so unrelated headings
    (``# 分镜建议`` / ``# 风险点`` / ``# 待核查内容``) don't pollute the
    voiceover. Text is normalised — markdown bullets and stray ``#`` are
    stripped, multi-spaces collapse — but Chinese punctuation is kept.

    Returns ``{slot_index_str: paragraph}`` keyed by the canonical slot
    name (the first entry of each tuple in ``_SCRIPT_SECTION_KEYS``) so
    callers don't have to know about LLM aliasing.
    """
    if not script_markdown:
        return {}

    voice_match = re.search(
        r"^#\s*口播稿\s*$(.*?)(?=^#\s+\S|\Z)",
        script_markdown,
        flags=re.MULTILINE | re.DOTALL,
    )
    block = voice_match.group(1) if voice_match else script_markdown

    raw: dict[str, str] = {}
    for sub_match in re.finditer(
        r"^##\s+(.+?)\s*$([\s\S]*?)(?=^##\s+|^#\s+\S|\Z)",
        block,
        flags=re.MULTILINE,
    ):
        title = sub_match.group(1).strip().lstrip("# ").strip()
        body = sub_match.group(2).strip()
        # 删掉整行只有 markdown 分隔线的 (---, ***, ___) —— Claude 在边界
        # 段常用 `---` 切分子小节,这条横线如果留下来会被字幕拼成 "...
        # 不构成任何投资或商业建议 ---" 直接出现在最后一帧字幕。
        body = re.sub(r"(?m)^\s*[-*_]{3,}\s*$", "", body)
        body = re.sub(r"^\s*[-*+]\s+", "", body, flags=re.MULTILINE)
        # 剥掉 markdown 强调标记 —— Claude/LLM 写"对开发者/对创作者"那
        # 类小段时常用 ``**对开发者**：``，这层标记如果留下来会原样进
        # subtitle_plan，最终在抖音字幕带里出现 "**对创作者**" 字面字
        # 符——立刻被观众识别为"AI 生成"，破坏工业级观感。
        body = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", body)
        body = re.sub(r"__([^_\n]+)__", r"\1", body)
        body = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", body)
        body = re.sub(r"`([^`]+)`", r"\1", body)
        body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
        body = body.replace("\n", " ").replace("#", "")
        body = re.sub(r"\s+", " ", body).strip()
        if title and body and body != "待补充":
            raw[title] = body

    sections: dict[str, str] = {}
    for aliases in _SCRIPT_SECTION_KEYS:
        canonical = aliases[0]
        for alias in aliases:
            for raw_title, raw_body in raw.items():
                if alias in raw_title:
                    sections[canonical] = raw_body
                    break
            if canonical in sections:
                break
    return sections


_CN_PUNCT_RE = re.compile(r"[，。；;,.！？!?:：()\[\]{}（）「」『』\"'`\s]+")
# 中文常见停用词 + 视频里高频出现但不值得高亮的词汇。
# 第二轮扩充:针对"AI 工具/CLI/项目解读"题材里 Claude/jieba 频繁切出来的
# narrative 套话词(本期/内容/试试/通过/不会/正在...),这些进 keyword
# punch 大字会让画面充斥"本期 / 内容 / 试试" 而不是真正的能力/数据点。
_KEYWORD_STOPWORDS = {
    "我们", "你们", "他们", "这个", "那个", "什么", "怎么", "因为", "所以", "不是", "就是", "可以", "其实",
    "已经", "还是", "或者", "如果", "这样", "那样", "有的", "没有", "现在", "以后", "之前", "之后",
    "一个", "一下", "一些", "全部", "全程", "一直", "一边", "一起", "看完", "看到", "出来", "出去",
    "玩意", "事情", "东西", "时候", "地方", "感觉", "样子",
    "他", "她", "它", "你", "我", "的", "了", "是", "在", "有", "和", "也", "都", "就", "把", "被", "让",
    "听起来", "说起来", "做起来",
    # 第二轮:narrative 套话 / 元描述
    "有没有", "本期", "内容", "本视频", "视频", "节目", "今天", "今天我们", "下期",
    "试试", "尝试", "建议", "如果你", "需要", "必须", "应该", "可能", "也许",
    "目前", "最近", "之间", "其中", "另外", "此外", "比如", "例如", "尤其", "特别",
    "比较", "更加", "非常", "真的", "确实", "其实是",
    "整个", "整体", "完整", "全套", "全程", "通过", "进行", "处理", "完成",
    "开始", "结束", "继续", "停止",
    "支持", "提供", "包含", "包括",
    "类似", "相关", "对应", "对接", "接入",
    "评估", "测试", "验证",
    "配置", "设置",  # too generic without object
    "表现", "效果", "结果", "情况",
    "流程", "过程",  # generic; specific phrases like "操作流程" still fine via 4-char match
    "解决", "实现",  # generic verbs without object
    "我自己", "自己",
    "不会", "不能", "不必", "不要", "不用",
    "出现", "存在", "发生",
    "正在", "已经在",
    "数字", "数据",
    # 第三轮: jieba 切出来但语义空洞的词
    "什么样", "怎么样", "怎么办", "为什么", "怎么做",
    "对话框", "聊天框",  # generic UI metaphor
    "大多", "都很", "很多", "不少", "很少",
    "上面", "下面", "里面", "外面", "前面", "后面",
    "其他", "别的", "更多",
    "来回", "来来回回", "反反复复",
    # 第四轮: 讲述者腔的口语填充词 / 模糊指代,在新 prompt 下会高频出现
    # ("9万2千 Star 的 browser-use 改写后", keyword punch 抓到
    # "说白了 / 比较复杂 / 这双鞋" 这种废话占满屏幕)。
    "说白了", "话说回来", "话说",  # 口语连接, 没有信息
    "比较复杂", "比较简单", "比较好", "比较差", "比较重要",  # "比较 + adj" 模糊修饰
    "这双鞋", "这家店", "这个网", "这家公司", "这个工具", "这种东西",  # 指示代词 + 量词 + 类名,占位符
    "意思的", "有意思", "意思在",  # "有意思的是" 残片
    "回答你", "告诉你", "举个例",
    "之类的", "诸如此", "等等的",
    "其实是", "也就是", "其实就",
    # 第五轮: 高频但语义薄的副词短语
    "原则上", "试一试", "看起来", "听起来",
    "这句", "这话", "这事", "这事说", "事说穿",
    "拆成", "串起", "连起", "缝在",  # 动词断片,没有宾语
    "几行", "一行", "几步",  # 数量但无对象
    "好几", "好几个", "差不多",
}
# 题材无关的高价值候选词模式：
#   ① 英文产品/品牌/工具名（连续 ASCII 字母数字，长度 ≥ 2，首字母大写或全大写）
#   ② 中文 2-4 字名词（注意：保留原词，由 stopwords 过滤掉无意义短语）
#   ③ 数字 + 单位（"3 分钟" / "8 万星" / "200 美元"）
_EN_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9._-]{1,24}\b")
# Compound Chinese numbers like "9万2千" must be captured as a single token,
# otherwise findall returns ["9万", "2千"] and the keyword punch rotation
# produces ugly windows like "2千 / Star / 一万多" with a fragment of the
# number stranded on screen. The optional ``(?:[万千百]\s*\d+\s*)*`` group
# absorbs intermediate digit+unit tails so "9万2千" → one match "9万2千".
_CN_NUM_UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:[万千百]\s*\d+\s*)*(?:亿|万|千|百|分钟|秒|小时|美元|刀|元|星|stars?|MB|GB|分|岁|个)"
)
_CN_NOUN_RE = re.compile(r"[\u4e00-\u9fff]{2,4}")


def _extract_keywords_from_text(
    text: str,
    *,
    extra_priority: list[str] | None = None,
    max_count: int = 4,
) -> tuple[str, ...]:
    """Pull 2-4 narrative keywords from a real Chinese voiceover paragraph.

    Topic-agnostic. We previously hard-coded ``("Peter", "出差", "AI")`` for
    every GitHub video which made codex / browser-use / langgraph scripts
    all wear the same Peter/Morocco subtitle skin. This extractor runs on
    the actual voiceover and prefers, in order:

      1. ``extra_priority`` tokens that appear in the text (so we can pin
         project name, repo owner, hashtag_keywords from analysis).
      2. English brand / product tokens (Codex, OpenAI, Cursor, Claude,
         npm, …) — they stand out visually when subtitled.
      3. Number+unit phrases (``8 万星``, ``200 美元``, ``3 分钟``) —
         strong attention hooks on TikTok-style subtitles.
      4. Chinese 2-4 char nouns, with stopwords filtered out.

    The returned tuple's order is deterministic and bounded by ``max_count``.
    """
    if not text:
        return ()
    seen: set[str] = set()
    picked: list[str] = []

    def _add(token: str) -> bool:
        token = token.strip()
        if not token or token in seen or token in _KEYWORD_STOPWORDS:
            return False
        if len(token) < 2 or len(token) > 14:
            return False
        seen.add(token)
        picked.append(token)
        return True

    # 收集候选,按类别分桶
    extras: list[str] = []
    if extra_priority:
        for c in extra_priority:
            if c and c in text and c not in _KEYWORD_STOPWORDS and 2 <= len(c) <= 14:
                extras.append(c)

    en_brands: list[str] = []
    for m in _EN_TOKEN_RE.findall(text):
        if not m:
            continue
        if m[0].isupper() or any(c.isupper() for c in m[1:]):
            en_brands.append(m)

    nums: list[str] = list(_CN_NUM_UNIT_RE.findall(text))

    # 中文具体词 —— 用 jieba 分词,避免老的 [一-鿿]{2,4} 贪婪
    # regex 在连续中文段里截出"的仓库地"/"图机制试"这种跨短语边界的
    # 无意义 chunk(原 keyword punch 退化成"Aider / 的仓库地 / 图机制试"
    # 就是这个 bug)。jieba 给的 token 是真正的词组边界,质量明显更高。
    cn_jieba: list[str] = []
    try:
        import jieba
        for token in jieba.cut(text):
            t = token.strip()
            if not t or t in _KEYWORD_STOPWORDS:
                continue
            # 只保留全中文 2-4 字 token,过滤标点 / 单字 / 数字
            if not (2 <= len(t) <= 4):
                continue
            if not all("一" <= c <= "鿿" for c in t):
                continue
            # 复合词前缀过滤: 如果一个 3-4 字 token 以模糊修饰词开头
            # ("比较X" / "这种Y" / "其他Z"),它在 stopwords 集合里查不到
            # 但语义价值依然为零,直接剔除。讲述者腔下这类组合很多。
            _filler_prefixes = ("比较", "这种", "这家", "这个", "那个", "其他", "其实",
                                "比如", "例如", "诸如", "类似", "可能", "也许", "应该",
                                "需要", "建议", "其中", "另外")
            if any(t.startswith(p) and len(t) > len(p) for p in _filler_prefixes):
                continue
            cn_jieba.append(t)
    except ImportError:
        pass
    # 优先 3-4 字 phrase("仓库地图"/"函数签名"/"自动提交"),再 2 字回退。
    cn_3_4 = [t for t in cn_jieba if len(t) >= 3]
    cn_2 = [t for t in cn_jieba if len(t) == 2]
    if not cn_3_4 and not cn_2:
        # jieba 不可用 → 旧 regex 兜底,虽然碎但不至于 0 keyword
        cn_3_4 = [m for m in _CN_NOUN_RE.findall(text) if len(m) >= 3]
        cn_2 = [m for m in _CN_NOUN_RE.findall(text) if len(m) == 2]

    # 输出排序:
    #   1. extra_priority(hashtag_keywords / 项目名)
    #   2. number+unit(数字锚点最抓眼)
    #   3. 第 1 个英文 brand(给品牌识别一个名额,不能更多)
    #   4. 中文 3-4 字具体词(narrative 重点)
    #   5. 还没填满 → 中文 2 字词
    #   6. 还没填满 → 剩下英文 brand
    #
    # 关键约束:**英文 brand 最多占 1 个槽位**——这条是为了根除
    # "ChatGPT / Aider / AI" / "AI / Aider / LLM" / "Aider / API / LLM"
    # 这种 3 个抽象名词大字铺满全片(整片 47% 帧)的退化。多个英文 brand
    # 在脚本里很常见(每段都提到 Aider),但 keyword punch 屏幕只需要
    # 1 个品牌锚点 + 2 个具体能力词,观众才能记住"Aider 做了什么"。
    for c in extras:
        _add(c)
        if len(picked) >= max_count:
            return tuple(picked[:max_count])

    for m in nums:
        _add(m)
        if len(picked) >= max_count:
            return tuple(picked[:max_count])

    en_brand_quota = 1
    en_used = 0
    for m in en_brands:
        if en_used >= en_brand_quota:
            break
        if _add(m):
            en_used += 1
        if len(picked) >= max_count:
            return tuple(picked[:max_count])

    for m in cn_3_4:
        _add(m)
        if len(picked) >= max_count:
            return tuple(picked[:max_count])

    for m in cn_2:
        _add(m)
        if len(picked) >= max_count:
            return tuple(picked[:max_count])

    # 兜底:如果中文具体词凑不满,允许更多英文 brand 进来
    for m in en_brands:
        _add(m)
        if len(picked) >= max_count:
            return tuple(picked[:max_count])

    return tuple(picked[:max_count])


def _clip_voiceover_loose(value: str, *, limit: int = 280) -> str:
    """Looser version of ``_clip_voiceover`` for scene voiceovers that come
    straight from the rewriter — the original 95-char cap was tuned for
    the old hard-coded one-liners and would chop real LLM output mid
    sentence (we shipped ``利用AI通。`` because of this exact cap).

    Also protects ASCII word boundaries: if the cut at ``limit`` lands
    inside an English word / version string / repo name (e.g. cuts
    ``Git commit`` into ``Git com``), walk back to the start of the
    ASCII run so we never publish a half-cut English word as the last
    visible token. Manifested as the 72s subtitle "...自动提交 Git com。"
    where commit got chopped to com because the 280-char hard cap
    landed mid-word.
    """
    text = _clean_sentence(value)
    if len(text) <= limit:
        return text

    def _is_ascii_token_char(c: str) -> bool:
        return c.isascii() and (c.isalnum() or c in ".-_/")

    cut_at = limit
    # If the cut lands mid-ASCII-word, prefer to slide FORWARD to finish
    # the word (so we keep "Git commit" instead of degrading to "Git").
    # Only fall back to slide-backward when the word is implausibly long
    # (likely a runaway URL / token), in which case we cut before it.
    if cut_at < len(text) and _is_ascii_token_char(text[cut_at - 1]) and _is_ascii_token_char(text[cut_at]):
        fwd = cut_at
        max_fwd = min(len(text), cut_at + 12)
        while fwd < max_fwd and _is_ascii_token_char(text[fwd]):
            fwd += 1
        if fwd < max_fwd:  # word ended within budget — extend forward
            cut_at = fwd
        else:
            # Word is suspiciously long; slide back to before the run.
            back = cut_at
            while back > 0 and _is_ascii_token_char(text[back - 1]):
                back -= 1
            if back > 0:
                cut_at = back

    cut = text[:cut_at].rstrip("，。；;,. ")
    return cut + "。" if cut else text[:cut_at]


def _is_creator_source(meta: dict[str, Any], analysis: dict[str, Any]) -> bool:
    """Detect whether this candidate is a creator-portrait subject.

    Three signals, OR-combined:
      1. analysis.content_type == "creator_portrait" (LLM judgement)
      2. meta.source_type ∈ {creator_link, creator_project} (discovery tag)
      3. meta.creator_id present (sources.yaml creator-type seeds carry this)

    The third one is for cases where the analyzer didn't get the prompt
    update yet but the source pool already classified it.
    """
    if str(analysis.get("content_type") or "").strip() == "creator_portrait":
        return True
    src = str(meta.get("source_type") or "").strip()
    if src in {"creator_link", "creator_project", "creator"}:
        return True
    if meta.get("creator_id"):
        return True
    return False


def _build_domestic_scenes(
    title: str,
    meta: dict[str, Any],
    analysis: dict[str, Any],
    assets: list[dict[str, Any]],
    *,
    script_sections: dict[str, str] | None = None,
) -> list[DirectorScene]:
    project = _project_name(meta, title)
    stars = _compact_number(meta.get("stars"))
    description = _domestic_context_sentence(meta, analysis)
    problem = _domestic_problem_sentence(meta, analysis)
    star_phrase = f"，GitHub 上已经有 {stars} star" if stars else ""
    is_creator = _is_creator_source(meta, analysis)

    sections = script_sections or {}
    # Topic-agnostic fallback voiceovers. Only fire when the rewriter
    # produced nothing usable for a slot. They no longer hard-code
    # Peter/Morocco/Dropbox — those tokens were poisoning every GitHub
    # video regardless of topic. Project name and stars are still
    # interpolated since they're factual to the current candidate.
    fallback_lines = [
        f"先看个反差：{project} 这个项目{star_phrase}，但很多人没注意到它在做什么。",
        f"它叫 {project}。{description}",
        problem or f"{project} 把这件事压成了一行命令——你给它需求，它自己读代码、调工具、产出结果。",
        "更值得看的是它扩展出去能干什么：从 CLI 到 API、从单机到云端，每一种用法都是一个新场景。",
        "看到这里你会发现，项目本身不是终点——它把'AI 怎么帮人干活'这件事的边界又往前挪了一点。",
    ]
    # Topic-agnostic priority tokens: project name + repo owner + analysis hashtags.
    # ``_extract_keywords_from_text`` will surface only the ones that actually
    # appear in the slot's voiceover, so a hashtag like "AI编程" gets in only
    # when the text says it. This replaces the previous hard-coded
    # ``("Peter", "出差", "AI")`` triplets that bled across every GitHub video.
    priority_tokens: list[str] = []
    for token in (project, str(meta.get("owner") or ""), str(meta.get("repo") or "")):
        if token and token not in priority_tokens:
            priority_tokens.append(token)
    for hashtag in analysis.get("hashtag_keywords", []) or []:
        ht = str(hashtag).strip().lstrip("#")
        if ht and ht not in priority_tokens:
            priority_tokens.append(ht)

    # scene_specs format: (scene_id, label, section_key, visual_role,
    # screen_text overlay, motion preset, highlight anchor)
    # Note: subtitle_keywords are no longer hard-coded here — they're
    # extracted live from each slot's voiceover via _extract_keywords_from_text.
    # visual_role uses the new browser_focus_* roles produced by
    # ``visual_evidence_hunt`` so each scene can pick a *different* surface
    # of the repo (overview / quickstart / releases / issues / commits) —
    # this is what fixes the "one repo screenshot stretched across 3 minutes"
    # problem on image-light repos like openai/codex. ``_asset_for_role``
    # gracefully falls back to legacy roles when a focused capture is missing.
    if is_creator:
        # Creator scenes pick from the dedicated creator_avatar asset
        # captured by snapshot_creator_profile (via unavatar.io). When
        # the X handle resolution fails, _asset_for_role falls back to
        # any other creator_* role; ultimately to brand_card.
        # extend uses creator_avatar as well so TweetQuoteCard reads the
        # @handle from evidence.label (snapshot sets label=@levelsio on
        # the avatar asset), instead of @x from a profile-page snapshot.
        scene_specs = [
            ("hook", "人物", "钩子", "creator_avatar", "", "slow_push", "center"),
            ("context", "轨迹", "故事是怎么发生的", "creator_personal_site", "", "push_right", "center"),
            ("mechanism", "作品集", "它到底怎么做到的", "creator_project_landing", "", "quick_push", "center"),
            ("extend", "原话", "它还能干什么", "creator_avatar", "", "slow_push", "center"),
            ("takeaway", "判断", "一点感慨", "creator_avatar", "", "snap_zoom", "center"),
        ]
    else:
        scene_specs = [
            ("hook", "钩子", "钩子", "browser_focus_repo_overview", "", "slow_push", "stars"),
            ("context", "故事", "故事是怎么发生的", "browser_focus_demo_section", "", "push_right", "repo_about"),
            ("mechanism", "怎么做到的", "它到底怎么做到的", "browser_focus_quickstart", "", "quick_push", "center"),
            ("extend", "还能干啥", "它还能干什么", "browser_focus_releases", "", "slow_push", "chart"),
            ("takeaway", "感慨", "一点感慨", "browser_focus_commits", "", "snap_zoom", "repo_header"),
        ]

    # Creator-mode tagline / quote derived from author + analysis.summary
    # — used to override the keyword-join screen_text on PortraitCard
    # (hook/takeaway) and TweetQuoteCard (extend) so the cards show real
    # narrative content instead of "Pieter / 荷兰人 / 小打小闹".
    author = str(meta.get("author") or analysis.get("author") or "").strip()
    creator_tagline = ""
    if is_creator:
        # Pick the FIRST sentence of analysis.summary as the tagline —
        # Claude usually packs the strongest one-liner there. Strip any
        # leading author name that would duplicate the headline.
        summary = str(analysis.get("summary") or "").strip()
        first_sent = re.split(r"[。.!?！？\n]", summary, maxsplit=1)[0].strip()
        if first_sent and author and first_sent.startswith(author):
            first_sent = first_sent[len(author):].lstrip("，。,. ")
        creator_tagline = first_sent[:36]  # PortraitCard tagline cap

    scenes: list[DirectorScene] = []
    for index, (scene_id, label, section_key, role, screen_text_hint, motion, highlight) in enumerate(scene_specs):
        # Prefer rewriter output → fall back to legacy template only if
        # the LLM produced nothing usable for this slot.
        script_voiceover = sections.get(section_key, "").strip()
        voiceover_text = script_voiceover or fallback_lines[index]
        clipped = _clip_voiceover_loose(voiceover_text)
        keywords = _extract_keywords_from_text(clipped, extra_priority=priority_tokens, max_count=4)
        # screen_text uses the first 2-3 keywords joined — matches the actual
        # voiceover instead of the old "AI 自己接管了电脑" hard-coded slogan.
        screen_text = " / ".join(keywords[:3]) if keywords else (screen_text_hint or label)

        # Creator-specific overlay: hook/takeaway portrait_card wants
        # "name / tagline"; extend tweet_quote_card wants the most
        # quotable sentence from this scene's voiceover.
        if is_creator and scene_id in {"hook", "takeaway"} and author:
            screen_text = f"{author} / {creator_tagline}" if creator_tagline else author
        if is_creator and scene_id == "extend":
            # First non-trivial sentence of the extend voiceover — most
            # likely to read as a real "quote" on TweetQuoteCard.
            sentences = [s.strip() for s in re.split(r"[。.!?！？]", clipped) if len(s.strip()) >= 8]
            if sentences:
                screen_text = sentences[0][:60]

        asset = _asset_for_role(assets, role, index)
        scenes.append(
            DirectorScene(
                scene_id=scene_id,
                label=label,
                voiceover=clipped,
                visual_role=role,
                asset_path=str(asset.get("path") or ""),
                screen_text=screen_text,
                motion=motion,
                highlight=highlight,
                subtitle_keywords=keywords,
                kind="creator" if is_creator else "tool",
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
