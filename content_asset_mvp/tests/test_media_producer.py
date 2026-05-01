from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.artifact_writer import ArtifactWriter
from app.main import main
from app.media_producer import build_bilingual_srt, build_caption_segments, build_srt, extract_voiceover_text, render_video_package, resolve_ffmpeg, split_sentences


SCRIPT = """# 标题

测试标题

# 口播稿

第一句测试。第二句继续！

# 分镜建议

画面建议
"""


def test_extract_voiceover_text_from_chinese_script() -> None:
    assert extract_voiceover_text(SCRIPT) == "第一句测试。第二句继续！"


def test_build_srt_from_chinese_sentences() -> None:
    sentences = split_sentences("第一句测试。第二句继续！")
    srt = build_srt(sentences, 6.0)

    assert "1\n00:00:00,000 -->" in srt
    assert "第一句测试。" in srt
    assert "第二句继续！" in srt


def test_build_bilingual_srt_from_caption_segments() -> None:
    sentences = split_sentences("第一句测试。第二句继续！")
    segments = build_caption_segments(sentences, 6.0)
    srt = build_bilingual_srt(segments, ["First test sentence.", "Second sentence continues!"])

    assert "第一句测试。\nFirst test sentence." in srt
    assert "第二句继续！\nSecond sentence continues!" in srt


def test_offline_render_generates_final_video(tmp_path: Path) -> None:
    writer = ArtifactWriter(tmp_path / "output", tmp_path / "workspace", "demo")
    pytest.importorskip("subprocess")
    try:
        resolve_ffmpeg(writer)
    except FileNotFoundError:
        pytest.skip("ffmpeg is not available")
    writer.write_markdown("chinese_script.md", SCRIPT)

    result = render_video_package("demo", writer, force_mock=True)

    video_path = Path(result.video_path)
    assert result.status == "succeeded"
    assert video_path.exists()
    assert video_path.stat().st_size > 0
    assert writer.output_path("subtitles.srt").exists()
    assert writer.output_path("subtitles.zh.srt").exists()
    assert writer.output_path("subtitles.en.srt").exists()
    assert writer.output_path("subtitles.bilingual.srt").exists()
    assert writer.output_path("subtitle_translation_status.json").exists()
    assert writer.output_path("tts_status.json").exists()
    assert writer.output_path("render_status.json").exists()
    translation_status = json.loads(writer.output_path("subtitle_translation_status.json").read_text(encoding="utf-8"))
    render_status = json.loads(writer.output_path("render_status.json").read_text(encoding="utf-8"))
    assert translation_status["mode"] == "mock_placeholder"
    assert render_status["subtitle_mode"] == "bilingual"


def test_cli_render_video_runs_against_temp_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output_dir = tmp_path / "output"
    workspace_dir = tmp_path / "workspace"
    package_dir = output_dir / "demo_cli"
    package_dir.mkdir(parents=True)
    (package_dir / "chinese_script.md").write_text(SCRIPT, encoding="utf-8")

    exit_code = main(
        [
            "--render-video",
            "demo_cli",
            "--video-mock",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
        ]
    )

    assert exit_code == 0
    assert "final_video.mp4" in capsys.readouterr().out
    assert (package_dir / "final_video.mp4").stat().st_size > 0
