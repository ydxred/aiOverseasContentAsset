from __future__ import annotations

from pathlib import Path

from app.artifact_writer import ArtifactWriter
from app.video_director import assign_scene_timing, build_director_plan, build_quality_checklist, collect_visual_assets, write_director_artifacts


SCRIPT = """# 标题

Browser-Use：AI驱动的网页自动化工具

# 口播稿

随着AI技术的飞速发展，网页自动化需求与日俱增。

# 分镜建议

展示项目截图。
"""


def test_build_director_plan_rewrites_to_domestic_short_video_style(tmp_path: Path) -> None:
    writer = ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "demo")
    writer.write_json(
        "github_meta.json",
        {
            "full_name": "browser-use/browser-use",
            "stars": 91548,
            "description": "Make websites accessible for AI agents.",
        },
    )

    plan = build_director_plan("demo", SCRIPT, writer)

    assert plan.style["version"] == "video_director_v4"
    assert plan.style["edit_template"] == "github_tool_explainer_v4"
    assert len(plan.scenes) == 5
    assert plan.scenes[0].motion == "slow_push"
    assert plan.scenes[0].highlight == "stars"
    assert plan.scenes[1].scene_id == "context"
    # This SCRIPT has no "## 钩子 / ## 故事…" headings under `# 口播稿`, so
    # `_extract_script_sections` is empty — voiceovers resolve to topic-aware
    # ``fallback_lines`` instead of legacy hard-coded "操作网页 …" template prose.
    assert "先看个反差" in plan.scenes[0].voiceover
    assert "browser-use" in plan.scenes[0].voiceover.lower()
    assert any(k in ("browser-use", "GitHub", "9.2 万") for k in plan.scenes[0].subtitle_keywords)
    assert "更值得看的是" in plan.voiceover
    assert "看到这里你会发现" in plan.voiceover
    assert "不承诺收益" not in plan.voiceover
    assert "小红书" in plan.style["deferred_platforms"]
    assert "小红书" not in plan.style["target_platforms"]
    assert "Make websites" not in plan.voiceover
    assert "随着AI技术的飞速发展" not in plan.voiceover


def test_collect_visual_assets_prefers_snapshots_and_readme_images(tmp_path: Path) -> None:
    writer = ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "demo")
    browser_asset = writer.workspace_path("browser_agent_assets/source.png")
    snapshot = writer.workspace_path("snapshots/repo.png")
    readme_image = writer.workspace_path("images/readme.png")
    browser_asset.parent.mkdir(parents=True)
    snapshot.parent.mkdir(parents=True)
    readme_image.parent.mkdir(parents=True)
    browser_asset.write_bytes(b"browser")
    snapshot.write_bytes(b"snapshot")
    readme_image.write_bytes(b"readme")
    writer.write_json("browser_agent_assets.json", {"assets": [{"workspace_path": str(browser_asset), "role": "browser_source_screenshot"}]})
    writer.write_json("snapshot_status.json", {"screenshots": [{"workspace_path": str(snapshot)}]})
    writer.write_json("readme_images.json", {"images": [{"workspace_path": str(readme_image)}]})

    assets = collect_visual_assets(writer)

    assert [asset["role"] for asset in assets] == ["browser_source_screenshot", "repo_snapshot", "readme_image"]


def test_assign_scene_timing_and_write_director_artifacts(tmp_path: Path) -> None:
    writer = ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "demo")
    plan = build_director_plan("demo", SCRIPT, writer)
    timed = assign_scene_timing(plan, 50.0)
    write_director_artifacts(writer, timed)
    checklist = build_quality_checklist(timed)

    assert timed.scenes[0].start == 0.0
    assert timed.scenes[-1].end == 50.0
    assert checklist["style_version"] == "video_director_v4"
    assert len(timed.shots) >= len(timed.scenes) * 2
    assert timed.shots[0].visual_type == "impact_title_card"
    context_visuals = [s.visual_type for s in timed.shots if s.scene_id == "context"]
    assert "story_beat_card" in context_visuals
    assert "signal_pulse_card" in context_visuals
    assert timed.shots[0].duration > 0
    assert timed.shots[0].purpose
    assert writer.output_path("director_plan.json").exists()
    assert writer.output_path("shot_list.json").exists()
    assert writer.output_path("edit_decisions.json").exists()
    assert writer.output_path("visual_asset_pack.json").exists()
    assert writer.output_path("director_script.md").exists()
    assert writer.output_path("director_quality_checklist.json").exists()
