from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact_writer import ArtifactWriter


SCRIPT_HEADING_RE = re.compile(r"^#\s+口播稿\s*$", re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^#\s+", re.MULTILINE)
SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")


@dataclass(frozen=True)
class RenderResult:
    content_id: str
    script_path: str
    voice_path: str
    subtitle_path: str
    subtitle_zh_path: str
    subtitle_en_path: str
    subtitle_bilingual_path: str
    subtitle_translation_status_path: str
    video_path: str
    tts_status_path: str
    render_status_path: str
    status: str
    issues: list[str]

    def as_media_job(self) -> dict[str, object]:
        return {
            "content_id": self.content_id,
            "job_type": "short_video",
            "status": self.status,
            "voice_path": self.voice_path,
            "subtitle_path": self.subtitle_path,
            "subtitle_zh_path": self.subtitle_zh_path,
            "subtitle_en_path": self.subtitle_en_path,
            "subtitle_bilingual_path": self.subtitle_bilingual_path,
            "subtitle_translation_status_path": self.subtitle_translation_status_path,
            "video_path": self.video_path,
            "output_path": self.video_path,
            "cover_path": "",
            "script_path": self.script_path,
            "tts_status_path": self.tts_status_path,
            "render_status_path": self.render_status_path,
            "issues": self.issues,
        }


def prepare_media_job(content_id: str, script_path: str, writer: ArtifactWriter) -> dict[str, object]:
    result = {
        "content_id": content_id,
        "status": "skipped",
        "voice_path": "",
        "subtitle_path": "",
        "video_path": "",
        "cover_path": "",
        "script_path": script_path,
        "issues": ["MVP v1 does not generate final video assets."],
    }
    writer.write_json("media_job.json", result)
    return result


def render_video_package(
    content_id: str,
    writer: ArtifactWriter,
    *,
    openai_api_key: str | None = None,
    force_mock: bool = False,
    bilingual_subtitles: bool = True,
) -> RenderResult:
    script_path = writer.output_path("chinese_script.md")
    if not script_path.exists():
        raise FileNotFoundError(f"chinese_script.md not found for content_id={content_id}")

    script_text = extract_voiceover_text(script_path.read_text(encoding="utf-8"))
    if not script_text:
        raise ValueError("# 口播稿 section is empty")

    ffmpeg = resolve_ffmpeg(writer)
    voice_path, tts_status = synthesize_voice(
        script_text,
        writer.output_path("voice.wav"),
        ffmpeg=ffmpeg,
        openai_api_key=openai_api_key,
        force_mock=force_mock,
    )
    tts_status_path = writer.write_json("tts_status.json", tts_status)

    duration = probe_audio_duration(voice_path, ffmpeg=ffmpeg) or estimate_duration(script_text)
    sentences = split_sentences(script_text)
    segments = build_caption_segments(sentences, duration)

    subtitle_zh_path = writer.output_path("subtitles.zh.srt")
    subtitle_zh_path.write_text(build_srt_from_segments(segments, "zh"), encoding="utf-8")

    english_sentences, translation_status = translate_subtitles(
        sentences,
        openai_api_key=openai_api_key,
        force_mock=force_mock,
    )
    translation_status_path = writer.write_json("subtitle_translation_status.json", translation_status)

    subtitle_en_path = writer.output_path("subtitles.en.srt")
    subtitle_en_path.write_text(build_srt_from_segments(segments, "en", english_sentences), encoding="utf-8")

    subtitle_bilingual_path = writer.output_path("subtitles.bilingual.srt")
    subtitle_bilingual_path.write_text(build_bilingual_srt(segments, english_sentences), encoding="utf-8")

    subtitle_path = subtitle_bilingual_path if bilingual_subtitles else subtitle_zh_path
    legacy_subtitle_path = writer.output_path("subtitles.srt")
    legacy_subtitle_path.write_text(subtitle_path.read_text(encoding="utf-8"), encoding="utf-8")

    video_path = writer.output_path("final_video.mp4")
    render_status = render_vertical_video(
        voice_path,
        subtitle_path,
        video_path,
        duration=duration,
        ffmpeg=ffmpeg,
        subtitle_mode="bilingual" if bilingual_subtitles else "zh",
    )
    render_status_path = writer.write_json("render_status.json", render_status)

    issues: list[str] = []
    if tts_status.get("mode") != "openai":
        issues.append(str(tts_status.get("reason") or "OpenAI TTS unavailable; used offline fallback."))
    if translation_status.get("mode") != "openai":
        issues.append(str(translation_status.get("reason") or "OpenAI subtitle translation unavailable; used fallback."))
    if render_status.get("subtitle_burned") is False:
        issues.append(str(render_status.get("subtitle_error") or "Subtitle burn failed; rendered video without subtitles."))

    status = "succeeded" if video_path.exists() and video_path.stat().st_size > 0 else "failed"
    result = RenderResult(
        content_id=content_id,
        script_path=str(script_path),
        voice_path=str(voice_path),
        subtitle_path=str(subtitle_path),
        subtitle_zh_path=str(subtitle_zh_path),
        subtitle_en_path=str(subtitle_en_path),
        subtitle_bilingual_path=str(subtitle_bilingual_path),
        subtitle_translation_status_path=str(translation_status_path),
        video_path=str(video_path),
        tts_status_path=str(tts_status_path),
        render_status_path=str(render_status_path),
        status=status,
        issues=issues,
    )
    writer.write_json("media_job.json", result.as_media_job())
    return result


def extract_voiceover_text(markdown: str) -> str:
    match = SCRIPT_HEADING_RE.search(markdown)
    if not match:
        return ""
    next_match = NEXT_HEADING_RE.search(markdown, match.end())
    section = markdown[match.end() : next_match.start() if next_match else len(markdown)]
    lines = [line.strip() for line in section.strip().splitlines()]
    return "\n".join(line for line in lines if line).strip()


def split_sentences(text: str) -> list[str]:
    sentences = [match.group(0).strip() for match in SENTENCE_RE.finditer(text.replace("\r", "\n"))]
    return [sentence for sentence in sentences if sentence]


def build_srt(sentences: list[str], duration_seconds: float) -> str:
    segments = build_caption_segments(sentences, duration_seconds)
    return build_srt_from_segments(segments, "zh")


@dataclass(frozen=True)
class CaptionSegment:
    index: int
    start: float
    end: float
    text: str


def build_caption_segments(sentences: list[str], duration_seconds: float) -> list[CaptionSegment]:
    if not sentences:
        return []
    duration_seconds = max(duration_seconds, len(sentences) * 1.2)
    weights = [max(1, len(sentence)) for sentence in sentences]
    total_weight = sum(weights)
    cursor = 0.0
    segments: list[CaptionSegment] = []
    for index, (sentence, weight) in enumerate(zip(sentences, weights), start=1):
        segment = max(1.2, duration_seconds * weight / total_weight)
        start = cursor
        end = duration_seconds if index == len(sentences) else min(duration_seconds, cursor + segment)
        segments.append(CaptionSegment(index=index, start=start, end=end, text=sentence))
        cursor = end
    return segments


def build_srt_from_segments(segments: list[CaptionSegment], language: str, translated_sentences: list[str] | None = None) -> str:
    blocks: list[str] = []
    for offset, segment in enumerate(segments):
        text = segment.text if language == "zh" else _translated_text(translated_sentences, offset)
        blocks.append(f"{segment.index}\n{format_srt_time(segment.start)} --> {format_srt_time(segment.end)}\n{text}\n")
    if not blocks:
        return ""
    return "\n".join(blocks).rstrip() + "\n"


def build_bilingual_srt(segments: list[CaptionSegment], english_sentences: list[str]) -> str:
    blocks: list[str] = []
    for offset, segment in enumerate(segments):
        english = _translated_text(english_sentences, offset)
        blocks.append(
            f"{segment.index}\n"
            f"{format_srt_time(segment.start)} --> {format_srt_time(segment.end)}\n"
            f"{segment.text}\n"
            f"{english}\n"
        )
    if not blocks:
        return ""
    return "\n".join(blocks).rstrip() + "\n"


def _translated_text(translated_sentences: list[str] | None, offset: int) -> str:
    if translated_sentences and offset < len(translated_sentences) and translated_sentences[offset].strip():
        return translated_sentences[offset].strip()
    return f"English summary for segment {offset + 1}."


def format_srt_time(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def estimate_duration(text: str) -> float:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    other_words = len(re.findall(r"[A-Za-z0-9]+", text))
    return max(4.0, min(180.0, chinese_chars / 4.2 + other_words / 2.6 + 1.5))


def resolve_ffmpeg(writer: ArtifactWriter) -> str:
    candidates: list[Path] = [
        Path(sys.executable).resolve().parent / "ffmpeg",
        writer.output_dir.parents[1] / ".venv" / "bin" / "ffmpeg",
        writer.output_dir.parent.parent / ".venv" / "bin" / "ffmpeg",
    ]
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        candidates.append(Path(system_ffmpeg))
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    try:
        import imageio_ffmpeg

        bundled_ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if bundled_ffmpeg.exists():
            return str(bundled_ffmpeg)
    except Exception:
        pass
    raise FileNotFoundError("ffmpeg is required to render video")


def synthesize_voice(
    text: str,
    output_path: Path,
    *,
    ffmpeg: str,
    openai_api_key: str | None,
    force_mock: bool = False,
) -> tuple[Path, dict[str, Any]]:
    if not force_mock and openai_api_key:
        try:
            mp3_path = output_path.with_suffix(".mp3")
            _openai_tts(text, mp3_path, openai_api_key=openai_api_key)
            return mp3_path, {
                "status": "succeeded",
                "mode": "openai",
                "model": "gpt-4o-mini-tts/tts-1 compatible",
                "voice_path": str(mp3_path),
                "text_chars": len(text),
            }
        except Exception as exc:  # pragma: no cover - depends on network/provider availability.
            reason = f"OpenAI TTS failed: {_safe_error_message(exc)}"
    else:
        reason = "video mock mode enabled" if force_mock else "OPENAI_API_KEY is not configured"

    duration = estimate_duration(text)
    _generate_silent_audio(output_path, duration, ffmpeg=ffmpeg)
    return output_path, {
        "status": "succeeded",
        "mode": "offline_silence",
        "reason": reason,
        "voice_path": str(output_path),
        "duration_seconds": duration,
        "text_chars": len(text),
    }


def translate_subtitles(
    sentences: list[str],
    *,
    openai_api_key: str | None,
    force_mock: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    if not sentences:
        return [], {
            "status": "succeeded",
            "mode": "empty",
            "sentence_count": 0,
        }

    if not force_mock and openai_api_key:
        try:
            translations = _openai_translate_subtitles(sentences, openai_api_key=openai_api_key)
            return translations, {
                "status": "succeeded",
                "mode": "openai",
                "model": "gpt-4o-mini",
                "sentence_count": len(sentences),
            }
        except Exception as exc:  # pragma: no cover - depends on network/provider availability.
            reason = f"OpenAI subtitle translation failed: {_safe_error_message(exc)}"
    else:
        reason = "video mock mode enabled" if force_mock else "OPENAI_API_KEY is not configured"

    translations = [_fallback_english_caption(sentence, index) for index, sentence in enumerate(sentences, start=1)]
    return translations, {
        "status": "succeeded",
        "mode": "mock_placeholder" if force_mock else "fallback_placeholder",
        "reason": reason,
        "sentence_count": len(sentences),
    }


def _openai_translate_subtitles(sentences: list[str], *, openai_api_key: str) -> list[str]:
    from openai import OpenAI

    client = OpenAI(api_key=openai_api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Translate Simplified Chinese short-video subtitles into natural, concise English. "
                    "Return only JSON with key translations, an array of strings. Preserve the number and order of lines."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"sentences": sentences}, ensure_ascii=False),
            },
        ],
    )
    text = response.choices[0].message.content or ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI returned invalid translation JSON: {exc}") from exc
    translations = parsed.get("translations") if isinstance(parsed, dict) else None
    if not isinstance(translations, list):
        raise RuntimeError("OpenAI translation response missed translations list")
    cleaned = [str(item).strip() for item in translations]
    if len(cleaned) != len(sentences) or any(not item for item in cleaned):
        raise RuntimeError("OpenAI translation response length mismatch")
    return cleaned


def _fallback_english_caption(sentence: str, index: int) -> str:
    topic = "this point"
    if "AI" in sentence or "人工智能" in sentence:
        topic = "AI content production"
    elif "审核" in sentence:
        topic = "human review"
    elif "脚本" in sentence:
        topic = "the Chinese script"
    elif "视频" in sentence:
        topic = "video production"
    return f"Conservative English placeholder {index}: {topic}."


def _openai_tts(text: str, output_path: Path, *, openai_api_key: str) -> None:
    from openai import OpenAI

    client = OpenAI(api_key=openai_api_key)
    last_error: Exception | None = None
    for model in ("gpt-4o-mini-tts", "tts-1"):
        try:
            response = client.audio.speech.create(model=model, voice="alloy", input=text)
            if hasattr(response, "stream_to_file"):
                response.stream_to_file(str(output_path))
            else:
                output_path.write_bytes(response.read())
            if output_path.exists() and output_path.stat().st_size > 0:
                return
        except Exception as exc:  # pragma: no cover - depends on installed SDK/provider state.
            last_error = exc
    raise RuntimeError(last_error or "OpenAI TTS produced no output")


def _safe_error_message(exc: Exception) -> str:
    message = str(exc)
    message = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", message)
    message = re.sub(r"(?i)(api[-_ ]?key[=:]\s*)[A-Za-z0-9_-]+", r"\1***", message)
    return message[-500:]


def _generate_silent_audio(output_path: Path, duration: float, *, ffmpeg: str) -> None:
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )


def probe_audio_duration(audio_path: Path, *, ffmpeg: str) -> float | None:
    ffprobe_path = str(Path(ffmpeg).with_name("ffprobe"))
    if not Path(ffprobe_path).exists():
        ffprobe_path = shutil.which("ffprobe") or ""
    if ffprobe_path:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            try:
                return float(json.loads(result.stdout)["format"]["duration"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass
    return None


def render_vertical_video(
    voice_path: Path,
    subtitle_path: Path,
    video_path: Path,
    *,
    duration: float,
    ffmpeg: str,
    subtitle_mode: str = "bilingual",
) -> dict[str, Any]:
    status: dict[str, Any] = {
        "status": "started",
        "video_path": str(video_path),
        "voice_path": str(voice_path),
        "subtitle_path": str(subtitle_path),
        "subtitle_mode": subtitle_mode,
        "duration_seconds": duration,
        "resolution": "1080x1920",
        "subtitle_burned": True,
    }
    subtitle_filter = _subtitle_filter(subtitle_path)
    command = _video_command(ffmpeg, voice_path, video_path, duration=duration, video_filter=subtitle_filter)
    result = subprocess.run(command, capture_output=True, text=True, timeout=max(120, math.ceil(duration) + 60))
    if result.returncode == 0 and video_path.exists() and video_path.stat().st_size > 0:
        status["status"] = "succeeded"
        return status

    status["subtitle_burned"] = False
    status["subtitle_error"] = (result.stderr or result.stdout or "subtitle render failed")[-2000:]
    fallback = subprocess.run(
        _video_command(ffmpeg, voice_path, video_path, duration=duration, video_filter=None),
        capture_output=True,
        text=True,
        timeout=max(120, math.ceil(duration) + 60),
    )
    if fallback.returncode != 0:
        status["status"] = "failed"
        status["error"] = (fallback.stderr or fallback.stdout or "video render failed")[-2000:]
        raise RuntimeError(status["error"])
    status["status"] = "succeeded"
    return status


def _video_command(ffmpeg: str, voice_path: Path, video_path: Path, *, duration: float, video_filter: str | None) -> list[str]:
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=#111827:s=1080x1920:r=30",
        "-i",
        str(voice_path),
        "-t",
        f"{duration:.3f}",
    ]
    if video_filter:
        command.extend(["-vf", video_filter])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(video_path),
        ]
    )
    return command


def _subtitle_filter(subtitle_path: Path) -> str:
    escaped_path = str(subtitle_path).replace("\\", "\\\\").replace("'", "\\'")
    style = "FontName=Noto Sans CJK SC,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=2,MarginV=120"
    return f"subtitles=filename='{escaped_path}':force_style='{style}'"

