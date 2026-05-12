from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProjectSkill:
    skill_id: str
    label: str
    purpose: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    owner_module: str
    status: str = "active"

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "label": self.label,
            "purpose": self.purpose,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "owner_module": self.owner_module,
            "status": self.status,
        }


PROJECT_SKILLS: tuple[ProjectSkill, ...] = (
    ProjectSkill(
        skill_id="browser-evidence-capture",
        label="浏览器证据素材采集",
        purpose="用 Playwright/browser-use 抓取高清网页证据素材，供导演层和 Remotion 复用。",
        inputs=("source_url", "browser_agent_task", "snapshot_status.json"),
        outputs=("browser_agent_assets.json", "browser_agent_report.json"),
        owner_module="app.browser_agent",
    ),
    ProjectSkill(
        skill_id="remotion-shotlist-renderer",
        label="Remotion 分镜渲染",
        purpose="让 director_plan/shot_list 驱动画面节奏、素材切换和屏幕文字，而不是只轮播单张截图。",
        inputs=("director_plan.json", "shot_list.json", "subtitle_plan.json", "visual_asset_pack.json"),
        outputs=("remotion_props.json", "platform_renders/douyin/final_video.mp4", "cover.png"),
        owner_module="app.remotion_renderer",
    ),
    ProjectSkill(
        skill_id="video-self-review",
        label="视频自审",
        purpose="渲染后自动抽帧并检查清晰度、字幕/镜头/素材密度等发布前风险。",
        inputs=("final_video.mp4", "render_status.json", "shot_list.json", "visual_qc_report.json"),
        outputs=("video_self_review.json", "self_review_frames/"),
        owner_module="app.video_self_review",
    ),
    ProjectSkill(
        skill_id="bgm-mixdown",
        label="BGM 混音 + 响度归一",
        purpose="渲染后自动叠加 royalty-free BGM，混入已有音轨并归一到 -14 LUFS（抖音/B站/YouTube 投放标准）。",
        inputs=("final_video.mp4", "assets/bgm/*.mp3 或 .wav"),
        outputs=("final_video_with_bgm.mp4", "bgm_mix_status.json"),
        owner_module="app.bgm_mixer",
    ),
    ProjectSkill(
        skill_id="asr-transcription",
        label="转写能力",
        purpose="统一 OpenAI Whisper 与本地 faster-whisper 转写能力，避免脚本和主流程割裂。",
        inputs=("source_audio", "local_video_or_audio"),
        outputs=("transcript.json", "transcript_clean.json"),
        owner_module="app.transcriber",
        status="planned",
    ),
)


def list_project_skills() -> list[dict[str, Any]]:
    return [skill.as_dict() for skill in PROJECT_SKILLS]


def build_skill_registry_report(*, active_skill_ids: list[str] | None = None) -> dict[str, Any]:
    active = set(active_skill_ids or [])
    skills = []
    for skill in PROJECT_SKILLS:
        item = skill.as_dict()
        item["used_in_current_run"] = skill.skill_id in active
        skills.append(item)
    return {
        "schema_version": 1,
        "architecture_version": "project_skills_v1",
        "skills": skills,
    }
