from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audio_mastering import master_voice_audio
from .artifact_writer import ArtifactWriter, stage_subdir
from .llm_client import LLMClient
from .pipeline_cache import StageCache
from .remotion_renderer import probe_remotion_renderer, render_remotion_video
from .render_manifest import build_v6_render_manifest
from .bgm_mixer import mix_bgm, write_bgm_status
from .skill_registry import build_skill_registry_report
from .subtitle_engine import build_subtitle_plan
from .tts_engine import synthesize_narration
from .video_director import assign_scene_timing, build_director_plan, write_director_artifacts
from .video_self_review import run_video_self_review
from .visual_qc import run_visual_qc


def _read_github_repo_name(meta_path: Path) -> str | None:
    """Return ``owner/repo`` (or ``owner``-only fallback) from github_meta.json.

    Returns ``None`` if the file is missing, malformed, or doesn't carry an
    obvious repo identifier — non-GitHub sources keep the existing behaviour
    where Remotion shows the fallback brand title.
    """
    try:
        if not meta_path.is_file():
            return None
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # pragma: no cover - defensive
        return None
    if not isinstance(data, dict):
        return None
    full = data.get("full_name")
    if isinstance(full, str) and "/" in full:
        return full
    owner = data.get("owner")
    repo = data.get("repo")
    if isinstance(owner, str) and isinstance(repo, str) and owner and repo:
        return f"{owner}/{repo}"
    if isinstance(repo, str) and repo:
        return repo
    return None


SCRIPT_HEADING_RE = re.compile(r"^#\s+口播稿\s*$", re.MULTILINE)
TITLE_HEADING_RE = re.compile(r"^#\s+标题\s*$", re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^#\s+", re.MULTILINE)
SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
BRAND_TEMPLATE_ID = "overseas_ai_narrative_v1"
BRAND_NAME = "Overseas AI Radar"


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
    cover_path: str
    brand_template_path: str
    visual_asset_path: str
    render_manifest_path: str
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
            "cover_path": self.cover_path,
            "brand_template_path": self.brand_template_path,
            "visual_asset_path": self.visual_asset_path,
            "render_manifest_path": self.render_manifest_path,
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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def render_video_package(
    content_id: str,
    writer: ArtifactWriter,
    *,
    openai_api_key: str | None = None,
    qwen_api_key: str | None = None,
    volc_appid: str | None = None,
    volc_access_token: str | None = None,
    force_mock: bool = False,
    bilingual_subtitles: bool = True,
    # ``final_video.mp4`` 默认就是 16:9 (1920x1080) 主成片。
    # 置 ``render_portrait=True`` 时额外渲一份 9:16 到 ``final_video_portrait.mp4``。
    # ``render_landscape`` 保留只是为了不破坏老调用方——它已经是默认行为，传 False
    # 也不会真关掉 landscape 主渲染。
    render_portrait: bool = False,
    render_landscape: bool = True,  # noqa: ARG001  (kept for backward compat)
    quality_tier: str = "release",
    use_cache: bool = True,
) -> RenderResult:
    if quality_tier not in {"draft", "release"}:
        raise ValueError(
            f"quality_tier must be 'draft' or 'release', got {quality_tier!r}"
        )
    script_path = writer.output_path("chinese_script.md")
    if not script_path.exists():
        raise FileNotFoundError(f"chinese_script.md not found for content_id={content_id}")

    script_text = extract_voiceover_text(script_path.read_text(encoding="utf-8"))
    if not script_text:
        raise ValueError("# 口播稿 section is empty")
    director_plan = build_director_plan(content_id, script_path.read_text(encoding="utf-8"), writer)
    script_text = director_plan.voiceover

    # Pull repoName off github_meta (if present) so the Remotion chrome title
    # bar shows ``github.com/owner/repo`` instead of the fallback brand string.
    repo_name = _read_github_repo_name(writer.output_path("github_meta.json"))

    ffmpeg = resolve_ffmpeg(writer)

    # Ensure all stage subdirs exist *before* any provider tries to write
    # into them. ``writer.output_path('voice.wav')`` resolves the staged
    # path but does NOT create the parent dir — so if this is a fresh
    # content_id (no prior pipeline run), the ``04_audio/`` etc. dirs
    # don't exist yet, and ``Path.write_bytes()`` from doubao /
    # dashscope / openai providers will silently fail with
    # FileNotFoundError → all caught → fall back to silent → silent's
    # ffmpeg call also fails because dir is missing → pipeline crashes.
    # Pre-creating each stage dir avoids this whole class of bug.
    for stage_name in ("04_audio", "05_subtitle", "06_render_props", "07_render_output", "08_qc"):
        (writer.output_dir / stage_name).mkdir(parents=True, exist_ok=True)

    # Incremental pipeline cache.
    #
    # We hash the upstream-deterministic inputs (script text, audio file
    # content, etc.) and cache the *status* + filesystem outputs of four
    # expensive stages: TTS, audio mastering, word-level alignment, and
    # subtitle translation. A cold render still does all the work; a
    # warm rerun on unchanged inputs hits and skips ~5+ minutes of
    # provider/GPU time.
    #
    # Note: we re-emit the ``*_status.json`` artifacts on every call (cache
    # hit or not), so downstream readers and the web console always see
    # fresh per-run files even when the underlying work was reused.
    cache = StageCache(writer.output_dir, enabled=use_cache)

    # === Stage: TTS ===
    #
    # ``synthesize_narration`` writes to either ``voice.wav`` (silent
    # fallback) or ``voice.mp3`` (cloud providers like doubao/dashscope/
    # openai). We can't pin ``outputs=['voice.wav']`` upfront — that
    # would let a silent ``voice.wav`` left over from an earlier run
    # falsely satisfy the cache check while the actual real-voice
    # ``voice.mp3`` is what downstream consumers want. So:
    #
    #   * ``outputs=`` is recorded *after* synthesis using the real
    #     filename returned by the engine.
    #   * On hit, we recover the path from ``status['voice_path']``
    #     instead of guessing.
    #   * ``expected_outputs=[]`` lets ``StageCache.lookup`` validate
    #     against whatever the previous run actually stored.
    voice_target = writer.output_path("voice.wav")
    # SSML toggle is part of the TTS contract: when on we send
    # ``<speak><break .../></speak>`` to Doubao to push per-track LRA
    # ≥ 6 LU. Bake the flag into the cache key so toggling
    # ``CONTENT_ASSET_TTS_SSML`` invalidates stale plain-text caches.
    ssml_enabled = os.getenv("CONTENT_ASSET_TTS_SSML", "1").strip() != "0"
    tts_inputs = {
        "text": script_text,
        # Encode *which* provider is reachable into the key so that
        # adding/removing keys triggers a refresh (e.g. previously we
        # fell back to silence; now OPENAI_API_KEY is present and we
        # should re-synthesize).
        "force_mock": bool(force_mock),
        "has_openai": bool(openai_api_key),
        "has_qwen": bool(qwen_api_key),
        "has_volc": bool(volc_appid and volc_access_token),
        "ssml_v1": ssml_enabled,
        # Bumped when we rerouted Doubao to V3 + uranus voice with
        # ``X-Api-Resource-Id: seed-tts-2.0`` and dropped SSML for the V3
        # path in favour of ``additions.context_texts``. Old caches were
        # built against V1 + ``M392_wvae_bigtts`` and must not be reused.
        "tts_routing_v2": True,
        # Provider preference + persona hint contribute to delivery
        # signature — when we switch primary from CosyVoice 2 (longcheng_v2)
        # back to Doubao Uranus (liufei) with a 讲述者 context_texts hint,
        # cached audio from the prior run is wrong-timbre and must be
        # invalidated. Capture both inputs so future toggles also
        # invalidate cleanly.
        "tts_persona_v2": True,
        "tts_provider_pref": (os.getenv("CONTENT_ASSET_TTS_PROVIDER") or "auto").lower(),
        "tts_doubao_context": (os.getenv("CONTENT_ASSET_TTS_DOUBAO_CONTEXT") or "")[:64],
        # Voice override (VOLC_TTS_VOICE / CONTENT_ASSET_TTS_VOICE) must
        # invalidate the cache — same script + same provider + different
        # voice = different audio. Without this key, switching liufei →
        # shuangkuaisi silently re-uses the male audio.
        "tts_voice_override": (
            os.getenv("VOLC_TTS_VOICE")
            or os.getenv("CONTENT_ASSET_TTS_VOICE")
            or ""
        ),
        # MiniMax 接入 — voice_id + model 一变就要重新合成。HAS_MINIMAX
        # 单独 surface 一下,避免新增 MINIMAX_API_KEY 后 cache 还命中旧
        # Doubao 音频。
        "has_minimax": bool(os.getenv("MINIMAX_API_KEY")),
        "minimax_voice": os.getenv("MINIMAX_VOICE_ID") or "",
        "minimax_model": os.getenv("MINIMAX_MODEL") or "speech-02-hd",
        "minimax_volume": os.getenv("MINIMAX_VOLUME") or "0.80",
        # GPT-SoVITS local zero-shot — cache must invalidate when any of
        # api_url / ref_audio path / prompt_text change because the model
        # produces different audio for the same script text with different
        # speaker conditioning.
        "has_gptsovits": bool(os.getenv("GPTSOVITS_API_URL")),
        "gptsovits_ref": os.getenv("GPTSOVITS_REF_AUDIO") or "",
        "gptsovits_prompt": (os.getenv("GPTSOVITS_PROMPT_TEXT") or "")[:64],
    }
    tts_key = cache.key("tts", inputs=tts_inputs)
    tts_hit = cache.lookup("tts", tts_key, expected_outputs=[])
    voice_path: Path | None = None
    tts_status: dict[str, Any] = {}
    if tts_hit is not None:
        cached_voice = Path(str(tts_hit.status.get("voice_path") or ""))
        # Don't trust the absolute path verbatim if the artifact got
        # archived/moved between runs — re-resolve through stage_subdir
        # using just the filename. This survives moving the output dir.
        if cached_voice.name:
            cached_voice = stage_subdir(writer.output_dir, cached_voice.name)
        if cached_voice.exists() and cached_voice.stat().st_size > 0:
            voice_path = cached_voice
            tts_status = dict(tts_hit.status)
            tts_status["voice_path"] = str(voice_path)
            tts_status["cache_hit"] = True
            tts_status.setdefault("cache_stored_at", tts_hit.stored_at)
            print(
                f"[cache] TTS hit (mode={tts_status.get('mode', '-')}, "
                f"file={voice_path.name}, skipped synthesis)"
            )
    if voice_path is None:
        voice_path, tts_status = synthesize_narration(
            script_text,
            voice_target,
            ffmpeg=ffmpeg,
            openai_api_key=openai_api_key,
            qwen_api_key=qwen_api_key,
            volc_appid=volc_appid,
            volc_access_token=volc_access_token,
            force_mock=force_mock,
        )
        # Don't cache the silent fallback — if a key gets fixed later
        # we want the next run to re-attempt real TTS, not get stuck
        # with silence forever.
        is_silent_fallback = tts_status.get("mode") == "offline_silence"
        if (
            not is_silent_fallback
            and voice_path.exists()
            and voice_path.stat().st_size > 0
        ):
            cache.store(
                "tts",
                tts_key,
                outputs=[voice_path.name],
                status=tts_status,
            )
    tts_status_path = writer.write_json("tts_status.json", tts_status)

    # === Stage: Audio mastering ===
    mastered_target = writer.output_path("voice_mastered.mp3")
    master_key = cache.key(
        "audio_master",
        # ``mastering_decision_v4`` flag forces a refresh after we added
        # the CLEAN_GAIN regime — pure ``volume=Xdb`` boost for inputs
        # that are too quiet for passthrough but have enough TP headroom
        # to amplify cleanly without compression. Old v3 caches landed
        # Doubao 2.0 (-22 LUFS, 6+ dB TP headroom) into passthrough,
        # which left it 6 dB too quiet for short-video parity. v4 brings
        # it up to ~-16 LUFS with zero LRA loss.
        inputs={"voice_path": str(voice_path), "ffmpeg_version_pin": "mastering_decision_v6_boost14"},
    )
    master_hit = cache.lookup(
        "audio_master", master_key, expected_outputs=["voice_mastered.mp3"]
    )
    if master_hit is not None:
        mastered_voice_path = stage_subdir(writer.output_dir, "voice_mastered.mp3")
        audio_mastering_status = dict(master_hit.status)
        audio_mastering_status["cache_hit"] = True
        audio_mastering_status.setdefault("cache_stored_at", master_hit.stored_at)
        print("[cache] audio mastering hit (skipped loudnorm pass)")
    else:
        mastered_voice_path, audio_mastering_status = master_voice_audio(
            voice_path,
            mastered_target,
            ffmpeg=ffmpeg,
        )
        if mastered_voice_path.exists() and mastered_voice_path.stat().st_size > 0:
            cache.store(
                "audio_master",
                master_key,
                outputs=["voice_mastered.mp3"],
                status=audio_mastering_status,
            )
    audio_mastering_status_path = writer.write_json(
        "audio_mastering_status.json", audio_mastering_status
    )

    # === Stage: Word-level subtitle alignment via faster-whisper ===
    #
    # Soft dep — if GPU / model / whisper lib is missing the aligner
    # returns ``None`` and we keep the legacy estimated timing. The
    # cache covers the success path (faster-whisper output is
    # deterministic for a given audio + model combination); a previous
    # failure is *not* cached so a fixed environment can succeed on the
    # next run without ``--no-cache``.
    word_alignment_status: dict[str, Any] = {"status": "skipped", "reason": "not_attempted"}
    word_alignment_result = None
    align_key = cache.key(
        "word_align",
        inputs={
            "voice_path": str(mastered_voice_path),
            "model": "small",
            "language": "zh",
        },
    )
    align_hit = cache.lookup(
        "word_align", align_key, expected_outputs=["subtitle_word_alignment.json"]
    )
    if align_hit is not None:
        try:
            from .whisperx_aligner import AlignmentResult

            cached_doc = json.loads(
                stage_subdir(writer.output_dir, "subtitle_word_alignment.json")
                .read_text(encoding="utf-8")
            )
            word_alignment_result = AlignmentResult.from_dict(cached_doc)
            word_alignment_status = dict(align_hit.status)
            word_alignment_status["cache_hit"] = True
            word_alignment_status.setdefault("cache_stored_at", align_hit.stored_at)
            print(
                f"[cache] word alignment hit "
                f"(words={word_alignment_status.get('word_count', '?')}, "
                f"avg_conf={word_alignment_status.get('average_confidence', '?')})"
            )
        except Exception as exc:  # noqa: BLE001
            word_alignment_result = None
            word_alignment_status = {
                "status": "error",
                "error": f"cache rehydrate failed: {exc!r}",
            }
    if word_alignment_result is None and align_hit is None:
        try:
            from .whisperx_aligner import align_voice_words

            word_alignment_result = align_voice_words(mastered_voice_path)
        except Exception as exc:  # noqa: BLE001 — aligner is soft, never block render
            word_alignment_status = {"status": "error", "error": repr(exc)}
        if word_alignment_result is not None:
            writer.write_json(
                "subtitle_word_alignment.json",
                word_alignment_result.as_dict(),
            )
            word_alignment_status = {
                "status": "ok",
                "device": word_alignment_result.device,
                "compute_type": word_alignment_result.compute_type,
                "model": word_alignment_result.model_name,
                "word_count": word_alignment_result.word_count(),
                "average_confidence": round(word_alignment_result.average_confidence(), 4),
                "realtime_factor": round(
                    word_alignment_result.audio_duration_seconds
                    / max(word_alignment_result.elapsed_seconds, 0.01),
                    2,
                ),
            }
            cache.store(
                "word_align",
                align_key,
                outputs=["subtitle_word_alignment.json"],
                status=word_alignment_status,
            )
    writer.write_json("subtitle_word_alignment_status.json", word_alignment_status)

    duration = probe_audio_duration(mastered_voice_path, ffmpeg=ffmpeg) or probe_audio_duration(voice_path, ffmpeg=ffmpeg) or estimate_duration(script_text)
    # Build a lightweight LLM client just for the ``flow_steps``
    # extraction inside the director. We always use gpt-4o-mini here
    # regardless of the upstream rewrite model — flow_steps is a 50-token
    # output structured task where mini is plenty, and forcing the
    # smaller model keeps the per-render cost in the cents range. When
    # OPENAI_API_KEY isn't available (mock / local renders) we pass
    # ``None`` and the director falls back to its heuristic extractor.
    director_llm = None
    if openai_api_key and not force_mock:
        director_llm = LLMClient(
            provider="openai",
            model="gpt-4o-mini",
            mock=False,
            openai_api_key=openai_api_key,
        )
    director_plan = assign_scene_timing(
        director_plan,
        duration,
        llm=director_llm,
        cache_dir=writer.output_dir,
    )
    write_director_artifacts(writer, director_plan)
    skill_registry_path = writer.write_json(
        "skill_registry.json",
        build_skill_registry_report(
            active_skill_ids=[
                "remotion-shotlist-renderer",
                "video-self-review",
                "browser-evidence-capture",
            ]
        ),
    )
    sentences = split_sentences(script_text)
    segments = build_caption_segments(sentences, duration)
    # Re-time captions to actual TTS pace via WhisperX word timestamps.
    # Without this the hook subtitle drifts ~2s behind voice on dense
    # English-mixed lines (Aider sample: caption still says
    # "ChatGPT 粘代码" at 3.9s while voice already moved on at 1.7s).
    if word_alignment_result is not None:
        segments = _align_caption_segments_to_whisperx(segments, word_alignment_result)
    subtitle_plan = build_subtitle_plan(segments, director_plan.as_dict())
    subtitle_plan_path = writer.write_json("subtitle_plan.json", subtitle_plan)
    title = _resolve_display_title(
        script_text=script_path.read_text(encoding="utf-8"),
        writer=writer,
        content_id=content_id,
    )
    brand_template = build_brand_template(title, content_id=content_id)
    brand_template_path = writer.write_json("brand_template.json", brand_template)
    cover_path = writer.output_path("cover.png")
    cover_status = render_cover_image(cover_path, brand_template, ffmpeg=ffmpeg)
    visual_asset_source = select_visual_asset(writer)
    visual_asset_path, visual_asset_status = prepare_visual_asset_card(
        visual_asset_source,
        writer.output_path("visual_asset_card.png"),
        ffmpeg=ffmpeg,
    )
    visual_evidence_items = collect_visual_evidence_items(writer)

    subtitle_zh_path = writer.output_path("subtitles.zh.srt")
    subtitle_zh_path.write_text(build_srt_from_segments(segments, "zh"), encoding="utf-8")

    # === Stage: Subtitle translation ===
    #
    # Translation is pure text-in/text-out and the most expensive call
    # in this stage (gpt-4o-mini with multi-second latency per call).
    # We piggy-back ``english_sentences`` onto the cached status so
    # rehydration only needs the single .json file.
    translate_key = cache.key(
        "translate",
        inputs={
            "sentences": list(sentences),
            "force_mock": bool(force_mock),
            "has_openai": bool(openai_api_key),
            "model": "gpt-4o-mini",
        },
    )
    translate_hit = cache.lookup("translate", translate_key, expected_outputs=[])
    if translate_hit is not None and translate_hit.status.get("english_sentences"):
        cached = translate_hit.status
        english_sentences = list(cached.get("english_sentences") or [])
        translation_status = {
            k: v for k, v in cached.items() if k != "english_sentences"
        }
        translation_status["cache_hit"] = True
        translation_status.setdefault("cache_stored_at", translate_hit.stored_at)
        print(
            f"[cache] subtitle translation hit "
            f"({len(english_sentences)} sentences, mode={translation_status.get('mode', '-')})"
        )
    else:
        english_sentences, translation_status = translate_subtitles(
            sentences,
            openai_api_key=openai_api_key,
            force_mock=force_mock,
        )
        # Only cache the network/openai mode — fallback placeholder is
        # cheap to re-run and we don't want stale "fallback used because
        # API key was missing" answers to win after the user fixes their
        # key.
        if (
            translation_status.get("mode") == "openai"
            and len(english_sentences) == len(sentences)
        ):
            cache_status = dict(translation_status)
            cache_status["english_sentences"] = list(english_sentences)
            cache.store(
                "translate",
                translate_key,
                outputs=[],
                status=cache_status,
            )
    translation_status_path = writer.write_json("subtitle_translation_status.json", translation_status)

    subtitle_en_path = writer.output_path("subtitles.en.srt")
    subtitle_en_path.write_text(build_srt_from_segments(segments, "en", english_sentences), encoding="utf-8")

    subtitle_bilingual_path = writer.output_path("subtitles.bilingual.srt")
    subtitle_bilingual_path.write_text(build_bilingual_srt(segments, english_sentences), encoding="utf-8")
    subtitle_ass_path = writer.output_path("subtitles.bilingual.ass")
    subtitle_ass_path.write_text(build_bilingual_ass(segments, english_sentences), encoding="utf-8")
    director_subtitle_ass_path = writer.output_path("subtitles.director.zh.ass")
    director_subtitle_ass_path.write_text(build_director_zh_ass(segments, director_plan.as_dict()), encoding="utf-8")

    subtitle_path = subtitle_bilingual_path if bilingual_subtitles else subtitle_zh_path
    director_style = str(director_plan.style.get("version") or "")
    burned_subtitle_path = director_subtitle_ass_path if director_style.startswith("video_director_v") else (subtitle_ass_path if bilingual_subtitles else subtitle_zh_path)
    burned_subtitle_mode = "director_zh" if director_style.startswith("video_director_v") else ("bilingual" if bilingual_subtitles else "zh")
    legacy_subtitle_path = writer.output_path("subtitles.srt")
    legacy_subtitle_path.write_text(subtitle_path.read_text(encoding="utf-8"), encoding="utf-8")

    project_root = Path(__file__).resolve().parents[1]
    remotion_status = probe_remotion_renderer(project_root)
    video_path = writer.output_path("final_video.mp4")
    render_status: dict[str, Any] = {}
    if remotion_status.get("runtime_available"):
        remotion_status, render_status = render_remotion_video(
            project_root=project_root,
            content_id=content_id,
            title=title,
            duration_seconds=duration,
            audio_path=mastered_voice_path,
            subtitle_plan=subtitle_plan,
            output_dir=writer.output_dir,
            final_video_path=video_path,
            cover_path=cover_path,
            evidence_image_path=visual_asset_path,
            evidence_items=visual_evidence_items,
            director_plan=director_plan.as_dict(),
            # ``final_video.mp4`` 现在默认就是 16:9 1920x1080 主成片。
            # 抖音 / B 站 / YouTube 全部直接吃这个文件。
            orientation="landscape",
            repo_name=repo_name,
            quality_tier=quality_tier,
        )
    if remotion_status.get("render_engine_actual") != "remotion":
        render_status = render_vertical_video(
            mastered_voice_path,
            burned_subtitle_path,
            video_path,
            duration=duration,
            ffmpeg=ffmpeg,
            subtitle_mode=burned_subtitle_mode,
            brand_template=brand_template,
            cover_status=cover_status,
            visual_asset_path=visual_asset_path,
            visual_asset_status=visual_asset_status,
            director_plan=director_plan.as_dict(),
        )

    # Optional 9:16 portrait render. Main ``final_video.mp4`` is 16:9 by default;
    # only when caller passes ``render_portrait=True`` do we also produce
    # ``final_video_portrait.mp4`` for platforms that demand a native vertical
    # cut. Reuses all assets already copied into the Remotion public dir so
    # the extra pass is close to zero setup cost.
    portrait_status: dict[str, Any] = {"status": "skipped", "reason": "render_portrait disabled"}
    if render_portrait and remotion_status.get("render_engine_actual") == "remotion":
        portrait_video_path = writer.output_path("final_video_portrait.mp4")
        portrait_cover_path = writer.output_path("cover_portrait.png")
        portrait_remotion_status, portrait_render_status = render_remotion_video(
            project_root=project_root,
            content_id=content_id,
            title=title,
            duration_seconds=duration,
            audio_path=mastered_voice_path,
            subtitle_plan=subtitle_plan,
            output_dir=writer.output_dir,
            final_video_path=portrait_video_path,
            cover_path=portrait_cover_path,
            evidence_image_path=visual_asset_path,
            evidence_items=visual_evidence_items,
            director_plan=director_plan.as_dict(),
            orientation="portrait",
            repo_name=repo_name,
            quality_tier=quality_tier,
        )
        portrait_status = {
            **portrait_remotion_status,
            "render_status": portrait_render_status,
            "video_path": str(portrait_video_path) if portrait_video_path.exists() else "",
            "cover_path": str(portrait_cover_path) if portrait_cover_path.exists() else "",
        }
    portrait_status_path = writer.write_json("portrait_render_status.json", portrait_status)
    # Legacy landscape_render_status.json is now redundant (主成片已是 landscape)，
    # but we still write a stub so老的消费方不会 404。内容指向主成片本身。
    legacy_landscape_status = {
        "status": "merged_into_main",
        "reason": "final_video.mp4 现在默认就是 16:9 主成片，不再生成独立 final_video_landscape.mp4",
        "video_path": str(video_path) if video_path.exists() else "",
    }
    landscape_status_path = writer.write_json(
        "landscape_render_status.json", legacy_landscape_status
    )

    remotion_status_path = writer.write_json("remotion_status.json", remotion_status)
    render_status.setdefault("video_path", str(video_path))
    render_status.setdefault("voice_path", str(mastered_voice_path))
    render_status.setdefault("subtitle_path", str(burned_subtitle_path))
    render_status.setdefault("subtitle_mode", burned_subtitle_mode)
    render_status.setdefault("duration_seconds", duration)
    # Main render is 16:9 by default. ``render_remotion_video`` already stamps
    # an accurate resolution when it actually renders; this setdefault only
    # kicks in when we fell through to the ffmpeg fallback (which still outputs
    # 1080x1920). So: Remotion path = 1920x1080; fallback = 1080x1920.
    fallback_resolution = "1920x1080" if remotion_status.get("render_engine_actual") == "remotion" else "1080x1920"
    render_status.setdefault("resolution", fallback_resolution)
    render_status.setdefault("subtitle_burned", True)
    # Subtitle timing source: ``word_level`` when WhisperX gave us per-word
    # timestamps with reasonable confidence; ``estimated`` when we fell back
    # to even-split durations. Consumed by ``build_video_quality_report`` to
    # lift subtitle_quality_score from 80 → 100 (see §14.2 of the spec).
    if word_alignment_result is not None and word_alignment_result.average_confidence() >= 0.85:
        render_status.setdefault("subtitle_timing_source", "word_level")
        render_status.setdefault("word_level_aligned", True)
        render_status.setdefault(
            "word_level_confidence",
            round(word_alignment_result.average_confidence(), 4),
        )
        render_status.setdefault("word_level_count", word_alignment_result.word_count())
    else:
        render_status.setdefault("subtitle_timing_source", "estimated")
        render_status.setdefault("word_level_aligned", False)
    render_status.setdefault("template_id", brand_template.get("template_id", BRAND_TEMPLATE_ID))
    render_status.setdefault("brand_name", brand_template.get("brand_name", BRAND_NAME))
    render_status.setdefault("cover_status", cover_status or {})
    render_status.setdefault("visual_asset_status", visual_asset_status or {"status": "missing"})
    render_status.setdefault("visual_evidence_asset_count", len(visual_evidence_items))
    # Subtitle highlight metrics — feed into build_video_quality_report so the
    # rubric can score the new subtitle_highlight dimension. We compute on the
    # subtitle_plan.json that just got rendered, not on the SRT, because the
    # plan is the canonical source of highlight_words.
    render_status.setdefault(
        "subtitle_highlight_metrics",
        _compute_subtitle_highlight_metrics(writer),
    )
    render_status.setdefault(
        "director_status",
        {
            "status": "enabled",
            "scene_count": len(director_plan.as_dict().get("scenes", [])),
            "shot_count": len(director_plan.as_dict().get("shots", [])),
            "style": director_plan.style.get("version", ""),
        },
    )
    render_status.setdefault("visual_quality", "remotion_douyin_explainer_v1" if remotion_status.get("render_engine_actual") == "remotion" else "brand_template_v1")
    generated_at = _utc_now_iso()
    video_version = str(video_path.stat().st_mtime_ns) if video_path.exists() else ""
    render_status.update(
        {
            "generated_at": generated_at,
            "video_version": video_version,
            "resource_dir": str(writer.output_dir),
            "workspace_dir": str(writer.workspace_dir),
            "output_layout": "one_resource_one_directory",
            # ``final_video.mp4`` 本身就是 landscape 主成片，保留 landscape_*
            # 字段只为兼容老消费方。
            "landscape_status": "merged_into_main",
            "landscape_video_path": str(video_path) if video_path.exists() else "",
            "landscape_status_path": str(landscape_status_path),
            "portrait_status": portrait_status.get("status"),
            "portrait_video_path": portrait_status.get("video_path") or "",
            "portrait_status_path": str(portrait_status_path),
            "orientation": "landscape",
        }
    )
    render_status_path = writer.write_json("render_status.json", render_status)
    visual_asset_pack_path = writer.output_path("visual_asset_pack.json")
    visual_asset_pack: dict[str, Any] | None = None
    if visual_asset_pack_path.exists():
        try:
            visual_asset_pack = json.loads(visual_asset_pack_path.read_text(encoding="utf-8"))
        except Exception:
            visual_asset_pack = None

    # ``collect_visual_evidence_items`` only reads browser_agent / snapshot /
    # readme artifacts — it's blind to YouTube-source evidence which lives in
    # ``remotion_props_*.json`` (keyframes, thumbnails). Merge them in so the
    # diversity metric sees what actually ends up on screen, otherwise a
    # YouTube-sourced clip scores ``real_asset_type_count=1`` even when the
    # Remotion props carry 8 distinct evidence frames across 2 roles.
    merged_evidence_items: list[dict[str, str]] = list(visual_evidence_items or [])
    for orientation_variant in ("landscape", "portrait"):
        props_candidate = writer.output_path(f"remotion_props_{orientation_variant}.json")
        if not props_candidate.exists():
            continue
        try:
            _props = json.loads(props_candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        for ev in _props.get("evidenceItems", []) or []:
            if not isinstance(ev, dict):
                continue
            role = ev.get("role")
            src = ev.get("src") or ev.get("path")
            if role and src:
                merged_evidence_items.append({"role": str(role), "src": str(src)})

    video_quality_report = build_video_quality_report(
        director_plan=director_plan.as_dict(),
        tts_status=tts_status,
        translation_status=translation_status,
        render_status=render_status,
        visual_asset_pack=visual_asset_pack,
        evidence_items=merged_evidence_items,
        audio_mastering_status=audio_mastering_status,
    )
    video_quality_report_path = writer.write_json("video_quality_report.json", video_quality_report)
    visual_qc_report = run_visual_qc(
        render_status_path=render_status_path,
        video_quality_report_path=video_quality_report_path,
        audio_mastering_status_path=audio_mastering_status_path,
        subtitle_plan_path=subtitle_plan_path,
        shot_list_path=writer.output_path("shot_list.json"),
    )
    visual_qc_report_path = writer.write_json("visual_qc_report.json", visual_qc_report)
    video_self_review = run_video_self_review(
        video_path=video_path,
        output_dir=writer.output_dir,
        ffmpeg=ffmpeg,
        director_plan=director_plan.as_dict(),
        render_status=render_status,
    )
    video_self_review_path = writer.write_json("video_self_review.json", video_self_review)
    bgm_status = mix_bgm(video_path=video_path, output_dir=writer.output_dir)
    bgm_status_path = write_bgm_status(writer.output_dir, bgm_status)
    render_manifest_v6 = build_v6_render_manifest(
        content_id=content_id,
        output_dir=writer.output_dir,
        platform="douyin",
        composition="DouyinExplainer",
        render_engine="remotion",
        fallback_engine="ffmpeg",
        audio_path=mastered_voice_path,
        subtitle_plan_path=subtitle_plan_path,
        shot_list_path=writer.output_path("shot_list.json"),
        quality_report_path=video_quality_report_path,
        outputs={
            "video_path": str(video_path),
            "cover_path": str(cover_path),
            "render_status_path": str(render_status_path),
            "remotion_status_path": str(remotion_status_path),
            "visual_qc_report_path": str(visual_qc_report_path),
            "video_self_review_path": str(video_self_review_path),
            "skill_registry_path": str(skill_registry_path),
            "bgm_status_path": str(bgm_status_path),
            "video_with_bgm_path": bgm_status.get("output_path"),
        },
        remotion_status=remotion_status,
    )
    writer.write_json("render_manifest.v6.json", render_manifest_v6)
    render_manifest = build_video_render_manifest(
        content_id=content_id,
        writer=writer,
        generated_at=generated_at,
        video_version=video_version,
        video_path=video_path,
        voice_path=mastered_voice_path,
        burned_subtitle_path=burned_subtitle_path,
        subtitle_mode=burned_subtitle_mode,
        bilingual_subtitles=bilingual_subtitles,
        duration=duration,
        ffmpeg=ffmpeg,
        brand_template=brand_template,
        director_plan=director_plan.as_dict(),
        tts_status=tts_status,
        translation_status=translation_status,
        render_status=render_status,
        video_quality_report=video_quality_report,
        audio_mastering_status=audio_mastering_status,
        remotion_status=remotion_status,
        visual_qc_report=visual_qc_report,
    )
    render_manifest_path = writer.write_json("video_render_manifest.json", render_manifest)

    issues: list[str] = []
    if tts_status.get("mode") != "openai":
        issues.append(str(tts_status.get("reason") or "OpenAI TTS unavailable; used offline fallback."))
    if translation_status.get("mode") != "openai":
        issues.append(str(translation_status.get("reason") or "OpenAI subtitle translation unavailable; used fallback."))
    if render_status.get("subtitle_burned") is False:
        issues.append(str(render_status.get("subtitle_error") or "Subtitle burn failed; rendered video without subtitles."))
    for reason in video_quality_report.get("blocking_reasons", []):
        issues.append(str(reason))

    status = "succeeded" if video_path.exists() and video_path.stat().st_size > 0 else "failed"
    result = RenderResult(
        content_id=content_id,
        script_path=str(script_path),
        voice_path=str(mastered_voice_path),
        subtitle_path=str(subtitle_path),
        subtitle_zh_path=str(subtitle_zh_path),
        subtitle_en_path=str(subtitle_en_path),
        subtitle_bilingual_path=str(subtitle_bilingual_path),
        subtitle_translation_status_path=str(translation_status_path),
        video_path=str(video_path),
        cover_path=str(cover_path),
        brand_template_path=str(brand_template_path),
        visual_asset_path=str(visual_asset_path) if visual_asset_path else "",
        render_manifest_path=str(render_manifest_path),
        tts_status_path=str(tts_status_path),
        render_status_path=str(render_status_path),
        status=status,
        issues=issues,
    )
    writer.write_json("media_job.json", result.as_media_job())
    return result


def build_video_render_manifest(
    *,
    content_id: str,
    writer: ArtifactWriter,
    generated_at: str,
    video_version: str,
    video_path: Path,
    voice_path: Path,
    burned_subtitle_path: Path,
    subtitle_mode: str,
    bilingual_subtitles: bool,
    duration: float,
    ffmpeg: str,
    brand_template: dict[str, Any],
    director_plan: dict[str, Any],
    tts_status: dict[str, Any],
    translation_status: dict[str, Any],
    render_status: dict[str, Any],
    video_quality_report: dict[str, Any] | None = None,
    audio_mastering_status: dict[str, Any] | None = None,
    remotion_status: dict[str, Any] | None = None,
    visual_qc_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    video_quality_report = video_quality_report or {}
    audio_mastering_status = audio_mastering_status or {}
    remotion_status = remotion_status or {}
    visual_qc_report = visual_qc_report or {}
    director_style = (director_plan.get("style", {}) if isinstance(director_plan, dict) else {}).get("version", "")
    shots = director_plan.get("shots", []) if isinstance(director_plan, dict) else []
    shot_count = len(shots) if isinstance(shots, list) else 0
    return {
        "schema_version": 1,
        "content_id": content_id,
        "resource_dir": str(writer.output_dir),
        "workspace_dir": str(writer.workspace_dir),
        "generated_at": generated_at,
        "video_version": video_version,
        "output_layout": {
            "rule": "one_resource_one_directory",
            "video": "final_video.mp4",
            "manifest": "video_render_manifest.json",
            "render_status": "render_status.json",
        },
        "render_parameters": {
            "duration_seconds": duration,
            "ffmpeg": ffmpeg,
            "subtitle_mode": subtitle_mode,
            "bilingual_subtitles": bilingual_subtitles,
            "template_id": brand_template.get("template_id", BRAND_TEMPLATE_ID),
            "brand_name": brand_template.get("brand_name", BRAND_NAME),
            "visual_quality": render_status.get("visual_quality", ""),
            "director_style": director_style,
            "edit_template": (director_plan.get("style", {}) if isinstance(director_plan, dict) else {}).get("edit_template", ""),
            "director_scene_count": len(director_plan.get("scenes", [])) if isinstance(director_plan.get("scenes"), list) else 0,
            "shot_count": shot_count,
            "video_quality_score": video_quality_report.get("video_quality_score", 0),
            "publish_ready": video_quality_report.get("publish_ready", False),
            "tts_mode": tts_status.get("mode", ""),
            "translation_mode": translation_status.get("mode", ""),
            "architecture_version": "video_pipeline_v6_slice",
            "render_engine_preferred": "remotion",
            "render_engine_actual": remotion_status.get("render_engine_actual", "ffmpeg"),
            "audio_mastered": audio_mastering_status.get("success") is True,
            "visual_qc_score": visual_qc_report.get("score", 0),
            "visual_qc_pass": visual_qc_report.get("pass", False),
            "orientation": render_status.get("orientation", "landscape"),
            "resolution": render_status.get("resolution", "1920x1080"),
            "quality_tier": render_status.get("quality_tier", "release"),
            "has_portrait_cut": bool(render_status.get("portrait_video_path")),
        },
        "artifacts": {
            "video_path": str(video_path),
            "voice_path": str(voice_path),
            "audio_mastering_status_path": str(writer.output_path("audio_mastering_status.json")),
            "subtitle_plan_path": str(writer.output_path("subtitle_plan.json")),
            "render_manifest_v6_path": str(writer.output_path("render_manifest.v6.json")),
            "remotion_status_path": str(writer.output_path("remotion_status.json")),
            "visual_qc_report_path": str(writer.output_path("visual_qc_report.json")),
            "subtitle_path": str(burned_subtitle_path),
            "render_status_path": str(writer.output_path("render_status.json")),
            "director_plan_path": str(writer.output_path("director_plan.json")),
            "shot_list_path": str(writer.output_path("shot_list.json")),
            "edit_decisions_path": str(writer.output_path("edit_decisions.json")),
            "visual_asset_pack_path": str(writer.output_path("visual_asset_pack.json")),
            "video_quality_report_path": str(writer.output_path("video_quality_report.json")),
            "brand_template_path": str(writer.output_path("brand_template.json")),
            "cover_path": str(writer.output_path("cover.png")),
        },
    }


_HOOK_LATIN_NAME_RE = re.compile(r"[A-Z][A-Za-z0-9]{2,}")
_HOOK_ACTION_VERBS = (
    # Tool/CLI verbs: "让/帮 X 控制/打开/修复 Y"
    "让", "帮", "跑", "去", "把", "拿", "从", "在", "控制",
    "打开", "修复", "自动", "识别", "访问", "接管", "发送", "告诉",
    # Creator-portrait verbs: "他自己写/上线/做了 X"
    "写", "上线", "做", "做出", "发布", "打造", "搭", "搭出",
    "搞", "干", "建", "造", "推出", "卖", "赚", "盈利", "运营",
    "创办", "创建", "开发", "上架", "打磨", "孵化", "拉到", "跑到",
)


def _hook_has_concrete_fact(director_plan: dict[str, Any]) -> bool:
    """Does the opening hook voiceover carry a concrete fact?

    We score a hook as "concrete" (= full 100 hook_strength) when the first
    scene's voiceover contains BOTH:
      - a proper noun anchor (English brand like ``Peter``/``OpenClaw`` or
        ≥2 CJK noun-ish characters), AND
      - an action-verb token indicating what that anchor *did*.

    This maps to the LLM prompt rule 第 1 句直接进 key_moments[0] 里的
    具体场景 + 人名 + 动作 — it is the signal the rule was actually followed.
    """
    scenes = director_plan.get("scenes") if isinstance(director_plan, dict) else None
    if not isinstance(scenes, list) or not scenes:
        return False
    hook_text = ""
    first = scenes[0] if isinstance(scenes[0], dict) else {}
    for key in ("voiceover", "hook", "text", "subtitle", "narration"):
        value = first.get(key)
        if isinstance(value, str) and value.strip():
            hook_text = value.strip()
            break
    if not hook_text:
        return False
    # Trim to first 3-ish seconds of narration (~60 CJK chars / 40 Latin chars).
    opener = hook_text[:120]
    has_name = bool(_HOOK_LATIN_NAME_RE.search(opener))
    has_action = any(verb in opener for verb in _HOOK_ACTION_VERBS)
    return has_name and has_action


def _compute_subtitle_highlight_metrics(writer: ArtifactWriter) -> dict[str, Any]:
    """Read the rendered ``subtitle_plan.json`` and compute the two metrics
    the rubric needs:

    - ``cues_with_highlight / cue_total``: subtitle coverage. Reference
      accounts highlight ~50% of cues; we set the rubric ramp at 30%.
    - ``keywords_in_text / keywords_total``: an integrity check that the
      keywords actually appear in their cue's ``text``. After the
      ``subtitle_engine._highlight_words`` rewrite this should always be
      100%, but we compute it anyway so any future regression (e.g.
      keyword serialisation truncating ``"impact_t"``) gets caught.
    """
    plan_path = writer.output_path("subtitle_plan.json")
    if not plan_path.exists():
        return {}
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    subs = plan.get("subtitles") or []
    if not subs:
        return {}
    cue_total = len(subs)
    cues_with_highlight = 0
    keywords_total = 0
    keywords_in_text = 0
    for cue in subs:
        if not isinstance(cue, dict):
            continue
        words = cue.get("highlight_words") or []
        text = str(cue.get("text") or "")
        if words:
            cues_with_highlight += 1
        for word in words:
            if not isinstance(word, str) or not word:
                continue
            keywords_total += 1
            if word in text:
                keywords_in_text += 1
    return {
        "cue_total": cue_total,
        "cues_with_highlight": cues_with_highlight,
        "keywords_total": keywords_total,
        "keywords_in_text": keywords_in_text,
    }


def build_video_quality_report(
    *,
    director_plan: dict[str, Any],
    tts_status: dict[str, Any],
    translation_status: dict[str, Any],
    render_status: dict[str, Any],
    visual_asset_pack: dict[str, Any] | None = None,
    evidence_items: list[dict[str, Any]] | None = None,
    audio_mastering_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    shots = director_plan.get("shots", []) if isinstance(director_plan, dict) else []
    assets = director_plan.get("assets", []) if isinstance(director_plan, dict) else []
    duration = float(render_status.get("duration_seconds") or 0.0)
    visual_types = {str(shot.get("visual_type")) for shot in shots if isinstance(shot, dict) and shot.get("visual_type")}
    # Real asset diversity is the union of three different asset surfaces:
    #   1. ``director_plan["assets"]`` -- legacy generic visual asset list
    #   2. ``visual_asset_pack["assets"]`` -- the curated pack written by the
    #      visual asset stage (cover, evidence, card, etc.)
    #   3. evidenceItems handed to Remotion (YouTube keyframes, thumbnails,
    #      browser screenshots, ...)
    # We previously only looked at #1, which has been empty for every
    # YouTube-source candidate -- silently downgrading every video to "diversity
    # too low" even when 8 evidence frames in 2 roles were on screen.
    real_asset_types: set[str] = set()
    for asset in assets:
        if isinstance(asset, dict) and asset.get("path") and asset.get("role"):
            real_asset_types.add(str(asset["role"]))
    if isinstance(visual_asset_pack, dict):
        for asset in visual_asset_pack.get("assets", []) or []:
            if not isinstance(asset, dict):
                continue
            role = asset.get("role") or asset.get("type") or asset.get("kind")
            if role and (asset.get("path") or asset.get("src")):
                real_asset_types.add(str(role))
        for atype in visual_asset_pack.get("asset_types", []) or []:
            if atype:
                real_asset_types.add(str(atype))
    if isinstance(evidence_items, list):
        for item in evidence_items:
            if isinstance(item, dict) and item.get("role") and item.get("src"):
                real_asset_types.add(str(item["role"]))
    shot_count = len(shots) if isinstance(shots, list) else 0
    expected_shots = max(1, int(duration / 4.5)) if duration else max(1, shot_count)
    # visual_density: pacing (shots/sec) — up to 100 when we hit target density.
    visual_density_score = min(100, int(shot_count / expected_shots * 100)) if expected_shots else 0
    asset_diversity_score = min(100, 36 + len(real_asset_types) * 24 + len(visual_types) * 6)

    # --- shot_pacing (0.08) ----------------------------------------------
    # Per-shot duration ceiling. The previous ``visual_density_score`` only
    # measured *count* — a 3-min video could ship 30 shots but with a
    # single 25s shot at the end (we shipped exactly this on yt and codex).
    # ``shot_pacing_score`` punishes any shot >5s and rewards mean ≤4.5s.
    shot_durations = [float(s.get("duration") or 0.0) for s in shots if isinstance(s, dict)]
    if shot_durations:
        max_shot = max(shot_durations)
        mean_shot = sum(shot_durations) / len(shot_durations)
        # 100 when max ≤ 5s and mean ≤ 4.5s; drops 8 points per second over.
        excess_max = max(0.0, max_shot - 5.0)
        excess_mean = max(0.0, mean_shot - 4.5)
        shot_pacing_score = max(40, int(100 - excess_max * 8 - excess_mean * 12))
    else:
        shot_pacing_score = 40
        max_shot = 0.0
        mean_shot = 0.0

    # --- subtitle (0.10) + subtitle_highlight (0.08) ---------------------
    subtitle_burned = render_status.get("subtitle_burned") is not False
    word_level_aligned = bool(
        render_status.get("word_level_aligned")
        or render_status.get("subtitle_timing_source") == "word_level"
    )
    if not subtitle_burned:
        subtitle_quality_score = 30
    elif word_level_aligned:
        subtitle_quality_score = 100
    else:
        subtitle_quality_score = 80
    # highlight 命中率：actual highlighted cues / total cues. The reference
    # accounts highlight roughly every other cue (45-65%), but for a
    # narrative video 25-40% is realistic. Score ramps linearly to 100 at
    # 30% non-empty + ≥90% in-text match. This is the dimension that lets
    # the rubric notice the "白字字幕" regression we shipped for months.
    sub_metrics = render_status.get("subtitle_highlight_metrics") or {}
    cue_total = int(sub_metrics.get("cue_total") or 0)
    cues_with_highlight = int(sub_metrics.get("cues_with_highlight") or 0)
    keywords_in_text = int(sub_metrics.get("keywords_in_text") or 0)
    keywords_total = int(sub_metrics.get("keywords_total") or 0)
    coverage = cues_with_highlight / cue_total if cue_total else 0.0
    accuracy = keywords_in_text / keywords_total if keywords_total else 1.0
    subtitle_highlight_score = max(30, min(100, int(coverage * (100 / 0.30) * accuracy)))

    # --- voice (0.08) + audio_lufs (0.06) + audio_lra (0.06) -------------
    real_voice_modes = {"volc_doubao_bigtts", "dashscope_cosyvoice", "openai"}
    real_voice_providers = {"doubao", "dashscope", "openai"}
    has_real_voice = (
        tts_status.get("mode") in real_voice_modes
        or tts_status.get("provider") in real_voice_providers
    )
    mastering = audio_mastering_status or {}
    has_mastered_voice = bool(mastering.get("success"))
    if not has_real_voice:
        voice_quality_score = 25
    elif has_mastered_voice:
        voice_quality_score = 100
    else:
        voice_quality_score = 75
    # Decode the dual-pass measurement we now record on every render.
    final_loudness = mastering.get("final_loudness") or {}

    def _f(key: str, default: float) -> float:
        try:
            return float(final_loudness.get(key, default))
        except (TypeError, ValueError):
            return default

    final_lufs = _f("input_i", 0.0)
    final_lra = _f("input_lra", 0.0)
    if final_lufs:
        # 100 when within ±1 dB of -14 LUFS. Drops 12 points per dB beyond.
        audio_lufs_score = max(40, int(100 - abs(final_lufs - (-14.0)) * 12))
    else:
        audio_lufs_score = 60  # measurement missing — neutral.
    if final_lra:
        # 100 at LRA 6+, drops 10 per LU below 6 down to floor 30.
        audio_lra_score = max(30, int(100 - max(0.0, 6.0 - final_lra) * 10))
    else:
        audio_lra_score = 50

    # --- hook (0.10) ------------------------------------------------------
    # The hook is always the first scene (scene_id="hook" in director_plan).
    # We look at shots within that scene specifically — not shots[:3] (which
    # misses the impact_title_card when the LLM put a viz_bar_chart first
    # for a stats hook) and not the full shot list (which would falsely
    # light up if an impact card appeared 80s into the video).
    #
    # Hook visual types accepted:
    #   - impact_title_card: tool/cli stats hook ("9.2 万 Star")
    #   - portrait_card / tweet_quote_card: creator-portrait hook
    #   - viz_*: any LLM-extracted visualization (bar chart of stars,
    #     timeline of releases, etc.) — these are *stronger* hooks than
    #     typography because they show, not tell.
    hook_visual_types = {"impact_title_card", "portrait_card", "tweet_quote_card"}
    hook_shots = [
        shot for shot in shots
        if isinstance(shot, dict) and shot.get("scene_id") == "hook"
    ]
    if not hook_shots:
        # Fall back to first 4 shots if no shot is tagged scene_id="hook".
        hook_shots = [s for s in shots[:4] if isinstance(s, dict)]
    has_impact_card = any(
        str(shot.get("visual_type")) in hook_visual_types
        or str(shot.get("visual_type")).startswith("viz_")
        for shot in hook_shots
    )
    hook_has_concrete_fact = _hook_has_concrete_fact(director_plan)
    if not has_impact_card:
        hook_strength_score = 55
    elif hook_has_concrete_fact:
        hook_strength_score = 100
    else:
        hook_strength_score = 75

    # Reweighted toward listener perception: subtitle_highlight + audio_lra +
    # audio_lufs + shot_pacing together account for 0.28 of the total. Without
    # these, the previous formula's mathematical ceiling was 93.8 and our
    # videos clustered at 92 regardless of how dead the actual viewing
    # experience was. Now a video with no highlights / silent voice / 25s
    # static shots will score in the 60s where it belongs.
    video_quality_score = int(
        round(
            visual_density_score * 0.20
            + asset_diversity_score * 0.20
            + shot_pacing_score * 0.08
            + subtitle_quality_score * 0.10
            + subtitle_highlight_score * 0.08
            + voice_quality_score * 0.08
            + audio_lufs_score * 0.06
            + audio_lra_score * 0.06
            + hook_strength_score * 0.14
        )
    )
    blocking_reasons: list[str] = []
    if not has_real_voice:
        blocking_reasons.append("Voice is offline silence/TTS fallback; publish requires real narration.")
    if len(real_asset_types) < 2:
        blocking_reasons.append("Visual asset diversity is too low; need at least two real asset types.")
    if shot_count < 8:
        blocking_reasons.append("Shot list is too thin for v4 industrial pacing.")
    if render_status.get("subtitle_burned") is False:
        blocking_reasons.append("Subtitle burn failed; final video is not publish-ready.")
    # Draft tier (540p / ultrafast) 是给本地预览用的，再高的质量分也不能直接发——
    # 把它算成 blocking_reason，避免有人盯着 web pill "≥95" 顺手点发布。
    if str(render_status.get("quality_tier") or "release").lower() == "draft":
        blocking_reasons.append(
            "Draft render (540p / x264 ultrafast); rerun without --draft for publish."
        )
    # 对齐 ``高质量视频生成工业级方案.md §14.2`` 发布门槛：
    #   ≥ 95 自动发布 / 80-94 人工检查 / < 80 不建议发布
    # ``publish_ready`` 对应"自动发布"档位——80-94 的中间档需要人工手动在发布
    # 看板上拍板，所以这里走 95 硬阈值，而不是直接放行 80+。
    publish_ready = not blocking_reasons and video_quality_score >= 95
    needs_human_review = (
        not blocking_reasons and 80 <= video_quality_score < 95
    )
    suggestions = [
        "Add repo screenshots plus README visuals so evidence and explanation shots do not rely on cards only.",
        "Replace offline silence with real Chinese narration before publishing.",
        "Materialize cropped evidence/card assets inside visual_asset_pack directories.",
    ]
    # Actionable next-score advice so reviewers can see where the missing
    # points live instead of staring at a single aggregate number.
    score_gap_hints: list[str] = []
    if subtitle_quality_score < 100:
        score_gap_hints.append(
            f"subtitle {subtitle_quality_score}/100 — 落地 WhisperX word-level 对齐可+{100 - subtitle_quality_score}"
        )
    if voice_quality_score < 100:
        score_gap_hints.append(
            f"voice {voice_quality_score}/100 — 打开 audio_mastering (loudnorm) 可+{100 - voice_quality_score}"
        )
    if hook_strength_score < 100:
        score_gap_hints.append(
            f"hook {hook_strength_score}/100 — 钩子段 3 秒内加具体人名+动作可+{100 - hook_strength_score}"
        )
    if visual_density_score < 100:
        score_gap_hints.append(
            f"visual_density {visual_density_score}/100 — 每 4.5s 一个 shot 可拉满"
        )
    if asset_diversity_score < 100:
        score_gap_hints.append(
            f"asset_diversity {asset_diversity_score}/100 — 增加真实素材类型可拉满"
        )
    if shot_pacing_score < 100:
        score_gap_hints.append(
            f"shot_pacing {shot_pacing_score}/100 — 当前最长镜头 {max_shot:.1f}s "
            f"均值 {mean_shot:.2f}s，目标 ≤5/4.5"
        )
    if subtitle_highlight_score < 100:
        score_gap_hints.append(
            f"subtitle_highlight {subtitle_highlight_score}/100 — 当前 highlight "
            f"覆盖 {coverage*100:.0f}% / 命中 {accuracy*100:.0f}%，目标 30%/100%"
        )
    if audio_lufs_score < 100 and final_lufs:
        score_gap_hints.append(
            f"audio_lufs {audio_lufs_score}/100 — 当前 {final_lufs:.1f} LUFS，目标 -14 ±1"
        )
    if audio_lra_score < 100:
        if final_lra:
            score_gap_hints.append(
                f"audio_lra {audio_lra_score}/100 — 当前 {final_lra:.1f} LU，目标 ≥ 6 "
                f"(从 TTS 端加 SSML 停顿/变速可拉起来)"
            )
        else:
            score_gap_hints.append(
                f"audio_lra {audio_lra_score}/100 — 缺少 final_loudness 测量，"
                f"检查 audio_mastering 是否走 dual-pass"
            )
    return {
        "schema_version": 2,
        "video_quality_score": video_quality_score,
        "score_ceiling": 100,
        "publish_threshold": 95,
        "visual_density_score": visual_density_score,
        "asset_diversity_score": asset_diversity_score,
        "shot_pacing_score": shot_pacing_score,
        "subtitle_quality_score": subtitle_quality_score,
        "subtitle_highlight_score": subtitle_highlight_score,
        "voice_quality_score": voice_quality_score,
        "audio_lufs_score": audio_lufs_score,
        "audio_lra_score": audio_lra_score,
        "hook_strength_score": hook_strength_score,
        "publish_ready": publish_ready,
        "needs_human_review": needs_human_review,
        "blocking_reasons": blocking_reasons,
        "score_gap_hints": score_gap_hints,
        "suggestions": suggestions,
        "metrics": {
            "shot_count": shot_count,
            "visual_type_count": len(visual_types),
            "real_asset_type_count": len(real_asset_types),
            "max_shot_duration_seconds": round(max_shot, 3),
            "mean_shot_duration_seconds": round(mean_shot, 3),
            "subtitle_highlight_coverage": round(coverage, 4),
            "subtitle_highlight_in_text_accuracy": round(accuracy, 4),
            "final_lufs": final_lufs,
            "final_lra": final_lra,
            "tts_mode": tts_status.get("mode", ""),
            "translation_mode": translation_status.get("mode", ""),
        },
    }


def extract_voiceover_text(markdown: str) -> str:
    match = SCRIPT_HEADING_RE.search(markdown)
    if not match:
        return ""
    next_match = NEXT_HEADING_RE.search(markdown, match.end())
    section = markdown[match.end() : next_match.start() if next_match else len(markdown)]
    lines = [clean_voiceover_line(line) for line in section.strip().splitlines()]
    return "\n".join(line for line in lines if line).strip()


def clean_voiceover_line(line: str) -> str:
    text = line.strip()
    if not text:
        return ""
    if re.match(r"^#{1,6}\s+", text):
        return ""
    text = re.sub(r"^[-*+]\s+", "", text)
    text = re.sub(r"^\d+[.)]\s+", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("#", "")
    return " ".join(text.split())


def extract_title_text(markdown: str) -> str:
    match = TITLE_HEADING_RE.search(markdown)
    if not match:
        return ""
    next_match = NEXT_HEADING_RE.search(markdown, match.end())
    section = markdown[match.end() : next_match.start() if next_match else len(markdown)]
    lines = [line.strip() for line in section.strip().splitlines() if line.strip()]
    return lines[0] if lines else ""


# Patterns that look like an internal id (and therefore must NEVER reach
# the on-screen Cover title). ``yt_9d1a160bbcab`` / ``gh_openai_codex`` /
# ``quality_smoke_browser_use`` all match — they're pipeline IDs, not titles.
_INTERNAL_ID_RE = re.compile(r"^(?:yt|gh|ph|hn|fb|gen)_[A-Za-z0-9_]{4,}$")


def _looks_like_internal_id(value: str) -> bool:
    """True when ``value`` looks like a content_id rather than human title.

    We refuse to ship anything matching this onto the Cover. Better to fall
    back to a generic Chinese label like ``"海外 AI 信号"`` than to render
    ``yt_9d1a160bbcab`` as 96-px cover text in front of viewers — which is
    exactly the regression the user just caught on yt_9d1a160bbcab.
    """
    text = (value or "").strip()
    if not text:
        return True
    if _INTERNAL_ID_RE.match(text):
        return True
    # Heuristic: an "id-like" string is mostly ASCII underscored hex/letters
    # with no whitespace and no Chinese — real titles always contain either
    # Chinese characters or at least one space.
    if " " in text:
        return False
    if any("\u4e00" <= c <= "\u9fff" for c in text):
        return False
    if "_" in text and re.match(r"^[A-Za-z0-9_]+$", text) and len(text) <= 64:
        return True
    return False


def _hook_first_sentence(markdown: str) -> str:
    """First declarative sentence of the ``## 钩子`` section, ≤ 28 CJK chars.

    Used as a Cover-title fallback when ``# 标题`` is empty. The hook
    section's lead sentence is ALWAYS designed to grab attention, so it's
    the closest thing to "human-readable title" we have besides the
    ``# 标题`` header itself.
    """
    if not markdown:
        return ""
    match = re.search(r"^##\s*钩子\s*$([\s\S]*?)(?=^##\s+|^#\s+\S|\Z)", markdown, flags=re.MULTILINE)
    if not match:
        return ""
    block = match.group(1).strip()
    for raw_line in block.splitlines():
        line = raw_line.strip().lstrip("-*+ ").strip()
        if not line or line.startswith("#"):
            continue
        sentence = re.split(r"[。！？!?]", line)[0].strip()
        if len(sentence) >= 6:
            return sentence[:28]
    return ""


def _resolve_display_title(
    *,
    script_text: str,
    writer: ArtifactWriter,
    content_id: str,
) -> str:
    """Pick the title that actually goes on screen (Cover, brand ribbon).

    Resolution order — content_id is intentionally **NOT** in this list,
    even as last resort, because the Cover renders this string at 96 px
    with a blinking cursor; ``yt_9d1a160bbcab`` is opaque to viewers and
    looks like a debug leak (which it is). We prefer a generic Chinese
    label over leaking pipeline internals.

      1. ``# 标题`` first non-empty line in the script.
      2. ``meta.title`` from the source (YouTube video title / GitHub
         full_name / etc.) — for github_repo we trim "owner/repo" → "repo".
      3. ``## 钩子`` first sentence (≤ 28 chars).
      4. Generic safe fallback ``"海外 AI 信号"`` — never the content_id.

    Each candidate is gated by ``_looks_like_internal_id`` so an
    accidentally-ID-shaped value at any layer can't sneak through.
    """
    candidates: list[str] = []

    title_from_script = extract_title_text(script_text).strip()
    if title_from_script:
        candidates.append(title_from_script)

    try:
        meta_path = writer.output_path("meta.json")
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta_title = str(meta.get("title") or "").strip()
            if meta_title:
                # github full_name "openai/codex" → display "codex" so the
                # cover doesn't read like a path. YouTube titles already
                # human-readable so we leave them.
                if meta.get("source_type") == "github_repo" and "/" in meta_title:
                    repo_only = meta_title.split("/")[-1].strip()
                    if repo_only:
                        candidates.append(repo_only)
                candidates.append(meta_title)
    except (OSError, json.JSONDecodeError):
        pass

    hook_lead = _hook_first_sentence(script_text)
    if hook_lead:
        candidates.append(hook_lead)

    for candidate in candidates:
        if candidate and not _looks_like_internal_id(candidate):
            return candidate

    # Generic Chinese label — viewer sees "海外 AI 信号" instead of "yt_xxx".
    return "海外 AI 信号"


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


MAX_CAPTION_DURATION = 6.0  # max seconds per on-screen subtitle line
MAX_CAPTION_CHARS = 32       # also splits over-long sentences by char count


def _split_for_subtitle(sentence: str) -> list[str]:
    """Break a long sentence into smaller subtitle-friendly chunks.

    Empirically subtitles longer than ~6 seconds / ~32 Chinese chars are
    hard to read on a phone screen — they wrap to multiple lines and the
    viewer has time to read past them while the narration is still on
    the previous clause. We respect natural inner breaks (Chinese / ASCII
    commas, semicolons, the enumeration mark, mid-sentence quote marks)
    when available, and only fall back to a hard char-count split if a
    clause has no inner break at all (rare with rewriter prompt #6 which
    instructs the LLM to keep clauses ≤ 35 chars).
    """
    text = sentence.strip()
    if len(text) <= MAX_CAPTION_CHARS:
        return [text]

    # First pass: split on inner punctuation we can safely break after.
    pieces = re.split(r"(?<=[，,、；;])", text)
    pieces = [p.strip() for p in pieces if p.strip()]
    if not pieces:
        pieces = [text]

    # Greedy-merge adjacent pieces while staying under the cap so we
    # don't over-fragment short clauses (e.g. avoid '比如，' becoming
    # its own subtitle).
    merged: list[str] = []
    buf = ""
    for piece in pieces:
        if not buf:
            buf = piece
            continue
        if len(buf) + len(piece) <= MAX_CAPTION_CHARS:
            buf += piece
        else:
            merged.append(buf)
            buf = piece
    if buf:
        merged.append(buf)

    # Last resort: any single chunk still too long (no inner punctuation
    # at all) gets cut by char count — but never split inside an
    # ASCII run (English word, version like ``v0.86.0``, repo name like
    # ``Aider-AI/aider``). Splitting mid-ASCII produced "Git com." in the
    # 72s frame instead of "Git commit". When the natural cut point
    # lands inside an ASCII run, walk back to the last whitespace / CJK
    # character before the run started; if none exists, walk forward
    # past the run.
    def _safe_cut(chunk: str, hard_cap: int) -> int:
        if hard_cap >= len(chunk):
            return len(chunk)
        cut = hard_cap
        # If we're about to slice inside [A-Za-z0-9.-]+, slide.
        in_ascii = lambda i: 0 <= i < len(chunk) and (
            chunk[i].isascii() and (chunk[i].isalnum() or chunk[i] in ".-_/")
        )
        if in_ascii(cut - 1) and in_ascii(cut):
            back = cut
            while back > 0 and in_ascii(back - 1):
                back -= 1
            # back now sits at the start of the ASCII run
            if back > 0:
                return back
            # ASCII run starts at index 0 — walk forward past it instead
            fwd = cut
            while fwd < len(chunk) and in_ascii(fwd):
                fwd += 1
            return min(fwd, len(chunk))
        return cut

    final: list[str] = []
    for chunk in merged:
        if len(chunk) <= MAX_CAPTION_CHARS:
            final.append(chunk)
            continue
        offset = 0
        while offset < len(chunk):
            cap = offset + MAX_CAPTION_CHARS
            cut = _safe_cut(chunk, cap)
            if cut <= offset:
                cut = min(offset + MAX_CAPTION_CHARS, len(chunk))
            final.append(chunk[offset:cut])
            offset = cut
    return final


def _align_caption_segments_to_whisperx(
    segments: list[CaptionSegment],
    alignment: Any,
) -> list[CaptionSegment]:
    """Re-time caption segments using WhisperX word timestamps so subtitles
    track actual TTS pace instead of char-weighted estimate.

    Why this exists: ``build_caption_segments`` distributes time uniformly
    across the voiceover by char weight, but Doubao TTS does NOT speak at
    uniform pace — Chinese commas pause briefly, em-dashes pause longer,
    English brand names like ``ChatGPT`` / ``Aider`` take more time per
    character than CJK syllables. Result on the Aider hook: caption
    "...ChatGPT 粘代码" still on screen at 3.94s while voice is already
    saying "复制回来" at 1.7s — ~2s subtitle drift, very obvious to the
    viewer. WhisperX gives us word-level timestamps from the actual
    rendered audio; this function maps caption chunks to those.

    Algorithm: flatten alignment words into a per-char timeline (each char
    inherits its parent word's time, evenly split). Strip non-content chars
    (punctuation/whitespace) from each caption chunk. Take the next ``n``
    chars from the timeline where ``n`` = chunk's content-char count;
    assign chunk.start = first char start, chunk.end = last char end.

    Failure modes:
      * If alignment is empty / unusable, return segments unchanged.
      * If chunk text exhausts before alignment chars, leftover chunks
        keep their original timing — better than crashing.
      * Char mismatches between caption and ASR (Aider→Aether,
        44000→四万四千) drift gradually but each segment self-anchors to
        cumulative char position, so a small mismatch in one chunk does
        not cascade more than its own length.
    """
    timeline_starts: list[float] = []
    timeline_ends: list[float] = []
    try:
        seg_iter = alignment.segments  # AlignmentResult dataclass
    except AttributeError:
        return segments

    def _is_content(c: str) -> bool:
        if c.isalnum():
            return True
        return "一" <= c <= "鿿"

    for seg in seg_iter:
        words = getattr(seg, "words", None) or []
        for w in words:
            word_text = getattr(w, "word", "") or ""
            ws = float(getattr(w, "start", 0.0) or 0.0)
            we = float(getattr(w, "end", ws) or ws)
            if we <= ws:
                we = ws + 0.05
            content = [c for c in word_text if _is_content(c)]
            if not content:
                continue
            per = (we - ws) / len(content)
            for i, _c in enumerate(content):
                timeline_starts.append(ws + i * per)
                timeline_ends.append(ws + (i + 1) * per)

    if not timeline_starts:
        return segments

    out: list[CaptionSegment] = []
    pos = 0
    total = len(timeline_starts)
    last_end = timeline_ends[-1]
    for seg in segments:
        text_n = sum(1 for c in seg.text if _is_content(c))
        if text_n == 0 or pos >= total:
            out.append(seg)
            continue
        end_pos = min(pos + text_n, total)
        new_start = timeline_starts[pos]
        new_end = timeline_ends[end_pos - 1]
        if new_end <= new_start:
            new_end = new_start + max(0.4, seg.end - seg.start)
        out.append(CaptionSegment(index=seg.index, start=new_start, end=new_end, text=seg.text))
        pos = end_pos
    # If the last subtitle ends well before audio's actual end (ASR may
    # truncate trailing silence), stretch it so the final caption stays
    # on screen until the audio actually stops.
    if out and out[-1].end < last_end:
        out[-1] = CaptionSegment(
            index=out[-1].index,
            start=out[-1].start,
            end=last_end,
            text=out[-1].text,
        )
    return out


def build_caption_segments(sentences: list[str], duration_seconds: float) -> list[CaptionSegment]:
    if not sentences:
        return []
    # Break long sentences into subtitle-friendly chunks BEFORE allocating
    # time, so timing weights match what we'll actually display. We track
    # which chunks belong to the same source sentence only for debugging
    # — timing itself is purely proportional to chunk char weight.
    chunked: list[str] = []
    for sentence in sentences:
        chunked.extend(_split_for_subtitle(sentence))
    if not chunked:
        return []

    duration_seconds = max(duration_seconds, len(chunked) * 1.0)
    weights = [max(1, len(chunk)) for chunk in chunked]
    total_weight = sum(weights)
    cursor = 0.0
    segments: list[CaptionSegment] = []
    for index, (chunk, weight) in enumerate(zip(chunked, weights), start=1):
        # Cap each subtitle line at MAX_CAPTION_DURATION so even if one
        # chunk is dense, the next subtitle still appears on schedule.
        share = max(1.0, duration_seconds * weight / total_weight)
        share = min(share, MAX_CAPTION_DURATION)
        start = cursor
        end = duration_seconds if index == len(chunked) else min(duration_seconds, cursor + share)
        segments.append(CaptionSegment(index=index, start=start, end=end, text=chunk))
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


def build_bilingual_ass(segments: list[CaptionSegment], english_sentences: list[str]) -> str:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,48,&H00FFFFFF,&H00FFFFFF,&HAA000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,90,90,210,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header.rstrip()]
    for offset, segment in enumerate(segments):
        english = _translated_text(english_sentences, offset)
        caption = f"{_ass_wrap(segment.text, 18)}\\N{{\\fs34}}{_ass_wrap(english, 30)}"
        lines.append(
            f"Dialogue: 0,{format_ass_time(segment.start)},{format_ass_time(segment.end)},Default,,0,0,0,,{caption}"
        )
    return "\n".join(lines).rstrip() + "\n"


def build_director_zh_ass(segments: list[CaptionSegment], director_plan: dict[str, Any] | None = None) -> str:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,58,&H00FFFFFF,&H00FFFFFF,&HAA000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,1,2,80,80,260,1
Style: Scene,Noto Sans CJK SC,50,&H0000D7FF,&H0000D7FF,&HAA000000,&H90000000,-1,0,0,0,100,100,0,0,1,3,1,8,70,70,125,1
Style: Shot,Noto Sans CJK SC,72,&H0000D7FF,&H0000D7FF,&HAA000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,1,5,90,90,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header.rstrip()]
    scenes = director_plan.get("scenes", []) if isinstance(director_plan, dict) else []
    shots = director_plan.get("shots", []) if isinstance(director_plan, dict) else []
    if isinstance(scenes, list):
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            screen_text = str(scene.get("screen_text") or scene.get("label") or "").strip()
            if not screen_text:
                continue
            start = float(scene.get("start") or 0.0)
            end = float(scene.get("end") or start + 1.0)
            lines.append(
                f"Dialogue: 1,{format_ass_time(start)},{format_ass_time(end)},Scene,,0,0,0,,{_ass_escape(screen_text)}"
            )
    if isinstance(shots, list):
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            shot_text = _shot_overlay_ass_text(shot)
            if not shot_text:
                continue
            start = float(shot.get("start") or 0.0)
            end = float(shot.get("end") or start + 1.0)
            lines.append(
                f"Dialogue: 2,{format_ass_time(start)},{format_ass_time(end)},Shot,,0,0,0,,{shot_text}"
            )
    for segment in segments:
        caption = _ass_wrap(segment.text, 20, max_lines=4)
        lines.append(
            f"Dialogue: 0,{format_ass_time(segment.start)},{format_ass_time(segment.end)},Default,,0,0,0,,{caption}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _shot_overlay_ass_text(shot: dict[str, Any]) -> str:
    visual_type = str(shot.get("visual_type") or "")
    if visual_type not in {"impact_title_card", "keyword_punch_card", "judgement_card"}:
        return ""
    screen_text = str(shot.get("screen_text") or "").strip()
    if not screen_text:
        return ""
    y = 605 if visual_type != "judgement_card" else 650
    return f"{{\\pos(540,{y})}}{_ass_wrap(screen_text, 11, max_lines=3)}"


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


def format_ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100)))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centis = divmod(remainder, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


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


def build_brand_template(title: str, *, content_id: str) -> dict[str, Any]:
    cover_title = _compact_text(title, max_chars=34)
    return {
        "template_id": BRAND_TEMPLATE_ID,
        "brand_name": BRAND_NAME,
        "content_id": content_id,
        "cover_title": cover_title,
        "safe_title": _ascii_overlay_text(cover_title) or "AI Opportunity Brief",
        "headline": "OVERSEAS AI RADAR",
        "subheadline": "Chinese narrative asset",
        "footer": "Observation, not income advice",
        "resolution": "1080x1920",
        "palette": {
            "background": "#0f172a",
            "panel": "#111827",
            "accent": "#38bdf8",
            "accent_secondary": "#a78bfa",
            "text": "#f8fafc",
            "muted": "#cbd5e1",
        },
        "layers": [
            "top brand bar",
            "center narrative title card",
            "left accent rail",
            "bottom source-boundary footer",
            "bilingual subtitle safe area",
        ],
    }


def render_cover_image(cover_path: Path, brand_template: dict[str, Any], *, ffmpeg: str) -> dict[str, Any]:
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    filter_chain = _brand_filter(brand_template, include_subtitle_safe_area=False)
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=#0f172a:s=1080x1920:r=1",
        "-frames:v",
        "1",
        "-vf",
        filter_chain,
        str(cover_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if result.returncode == 0 and cover_path.exists() and cover_path.stat().st_size > 0:
        return {"status": "succeeded", "cover_path": str(cover_path)}
    return {
        "status": "failed",
        "cover_path": str(cover_path),
        "error": (result.stderr or result.stdout or "cover render failed")[-1000:],
    }


def select_visual_asset(writer: ArtifactWriter) -> Path | None:
    browser_agent_assets = _read_json_if_exists(writer.output_path("browser_agent_assets.json"))
    browser_assets = browser_agent_assets.get("assets") if isinstance(browser_agent_assets, dict) else None
    if isinstance(browser_assets, list):
        for asset in browser_assets:
            if not isinstance(asset, dict):
                continue
            path = _existing_image_path(asset.get("workspace_path"))
            if path and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                return path

    snapshot_status = _read_json_if_exists(writer.output_path("snapshot_status.json"))
    screenshots = snapshot_status.get("screenshots") if isinstance(snapshot_status, dict) else None
    if isinstance(screenshots, list):
        for screenshot in screenshots:
            if not isinstance(screenshot, dict):
                continue
            path = _existing_image_path(screenshot.get("workspace_path"))
            if path:
                return path

    readme_images = _read_json_if_exists(writer.output_path("readme_images.json"))
    images = readme_images.get("images") if isinstance(readme_images, dict) else None
    if isinstance(images, list):
        for image in images:
            if not isinstance(image, dict):
                continue
            path = _existing_image_path(image.get("workspace_path"))
            if path and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                return path

    # YouTube candidates have no GitHub-style screenshots, so fall back to
    # the thumbnail / keyframes emitted by youtube_asset_collector.
    youtube_assets = _read_json_if_exists(writer.output_path("youtube_assets.json"))
    yt_assets = youtube_assets.get("assets") if isinstance(youtube_assets, dict) else None
    if isinstance(yt_assets, list):
        # Prefer the wide thumbnail as the hero card because keyframes are
        # 16:9 and the hero card uses a 936x760 portrait crop that
        # benefits from a composed frame.
        sort_key = {"youtube_thumbnail": 0, "youtube_keyframe": 1}
        for asset in sorted(
            (a for a in yt_assets if isinstance(a, dict)),
            key=lambda a: sort_key.get(str(a.get("role") or ""), 99),
        ):
            path = _existing_image_path(asset.get("workspace_path"))
            if path and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                return path
    return None


_BANNER_ASPECT_MAX = 4.0   # >4:1 horizontal banner → wordmark / shield row
_BANNER_ASPECT_MIN = 0.25  # <1:4 vertical strip   → sidebar diagram / status bar
_SVG_VIEWBOX_RE = re.compile(r"viewBox\s*=\s*[\"']\s*([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)", re.IGNORECASE)
_SVG_WIDTH_RE = re.compile(r"\bwidth\s*=\s*[\"'](\d+(?:\.\d+)?)", re.IGNORECASE)
_SVG_HEIGHT_RE = re.compile(r"\bheight\s*=\s*[\"'](\d+(?:\.\d+)?)", re.IGNORECASE)
_SVG_FILL_RE = re.compile(r"fill\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)


def _is_unusable_evidence_asset(path: Path) -> bool:
    """Return True if the asset will render as garbage inside a chrome card.

    Catches three failure modes seen in production:
      1. **Wordmark SVG** — single-fill black-on-transparent path glyphs
         (e.g. browser-use "Browser Use" 569×53 SVG, fill="#000"). On a
         dark-tech chrome background the result is invisible.
      2. **Banner aspect** — width / height ratio outside [0.25, 4.0].
         GitHub README images at those ratios are almost always logo
         stripes / shield rows / vertical sidebars, not real screenshots.
      3. **Single-fill mono SVG** — even if aspect is OK, an SVG whose
         only fill colour is a near-black or near-white solid is a
         wordmark-style asset that won't read on the chrome card.

    Returns False on any parse error so we degrade visibly rather than
    silently dropping a valid image.
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".svg":
            text = path.read_text(encoding="utf-8", errors="ignore")
            # Aspect from viewBox (preferred) or width/height attrs.
            match = _SVG_VIEWBOX_RE.search(text)
            w = h = None
            if match:
                _, _, w_raw, h_raw = match.groups()
                try:
                    w = float(w_raw)
                    h = float(h_raw)
                except ValueError:
                    w = h = None
            if w is None or h is None:
                w_match = _SVG_WIDTH_RE.search(text)
                h_match = _SVG_HEIGHT_RE.search(text)
                if w_match and h_match:
                    try:
                        w = float(w_match.group(1))
                        h = float(h_match.group(1))
                    except ValueError:
                        w = h = None
            if w and h:
                aspect = w / h
                if aspect > _BANNER_ASPECT_MAX or aspect < _BANNER_ASPECT_MIN:
                    return True
            # Mono-fill check: gather all fill values, count near-black
            # and near-white. If 80%+ of fills are mono, it's a wordmark.
            fills = [_normalise_hex(f) for f in _SVG_FILL_RE.findall(text)]
            fills = [f for f in fills if f]
            if fills:
                mono = sum(1 for f in fills if f in {"#000000", "#ffffff"})
                if mono / len(fills) >= 0.8 and len(fills) <= 3:
                    return True
            return False
        # Raster path: check aspect via Pillow.
        try:
            from PIL import Image
        except ImportError:
            return False
        with Image.open(path) as img:
            w_px, h_px = img.size
            if not w_px or not h_px:
                return False
            aspect = w_px / h_px
            if aspect > _BANNER_ASPECT_MAX or aspect < _BANNER_ASPECT_MIN:
                return True
        return False
    except Exception:
        return False


def _normalise_hex(value: str) -> str:
    """Normalise a CSS colour token to lower-case 6-digit hex, or '' on parse failure."""
    v = value.strip().lower()
    if v.startswith("#"):
        v = v[1:]
        if len(v) == 3:
            v = "".join(ch * 2 for ch in v)
        if len(v) == 6 and all(ch in "0123456789abcdef" for ch in v):
            return f"#{v}"
    return ""


def collect_visual_evidence_items(writer: ArtifactWriter) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    browser_agent_assets = _read_json_if_exists(writer.output_path("browser_agent_assets.json"))
    browser_assets = browser_agent_assets.get("assets") if isinstance(browser_agent_assets, dict) else None
    if isinstance(browser_assets, list):
        for asset in browser_assets:
            if not isinstance(asset, dict):
                continue
            path = _existing_image_path(asset.get("workspace_path"))
            if path:
                items.append(
                    {
                        "path": str(path),
                        "label": str(asset.get("label") or "浏览器证据素材"),
                        "role": str(asset.get("role") or "browser_evidence_screenshot"),
                    }
                )

    # Local import to avoid a circular ``app.video_director`` ↔ ``app.media_producer``
    # dependency at module import time.
    from .video_director import _landscape_friendly_path

    snapshot_status = _read_json_if_exists(writer.output_path("snapshot_status.json"))
    screenshots = snapshot_status.get("screenshots") if isinstance(snapshot_status, dict) else None
    if isinstance(screenshots, list):
        for screenshot in screenshots:
            if not isinstance(screenshot, dict):
                continue
            path = _existing_image_path(screenshot.get("workspace_path"))
            if path:
                # 同 video_director.collect_visual_assets：full_page 截图
                # crop 成 hero 段，避免 16:9 ScreenshotFrame 黑边塌陷。
                path = _landscape_friendly_path(path)
                items.append(
                    {
                        "path": str(path),
                        "label": str(screenshot.get("label") or "仓库截图"),
                        "role": "repo_snapshot",
                    }
                )

    readme_images = _read_json_if_exists(writer.output_path("readme_images.json"))
    images = readme_images.get("images") if isinstance(readme_images, dict) else None
    if isinstance(images, list):
        for image in images:
            if not isinstance(image, dict):
                continue
            path = _existing_image_path(image.get("workspace_path"))
            # README 图片三道过滤：
            # 1) 扩展名白名单
            # 2) SVG < 8KB → shield 徽章
            # 3) aspect > 4:1 / < 1:4 → wordmark / 长条 banner
            # 4) SVG 主色单一（fill="#000" / fill="#fff" 占绝大多数）→
            #    像 browser-use 的 "Browser Use" wordmark（569×53 / 纯黑），
            #    丢进 dark-tech chrome 卡片是黑底黑字 = 完全不可见。
            if path and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
                try:
                    if path.suffix.lower() == ".svg" and path.stat().st_size < 8000:
                        continue
                except OSError:
                    continue
                if _is_unusable_evidence_asset(path):
                    continue
                items.append(
                    {
                        "path": str(path),
                        "label": str(image.get("alt") or image.get("label") or "README 素材"),
                        "role": "readme_image",
                    }
                )

    # YouTube-sourced candidates: thumbnail + evenly-distributed keyframes
    # emitted by youtube_asset_collector.collect_youtube_assets.
    youtube_assets = _read_json_if_exists(writer.output_path("youtube_assets.json"))
    yt_assets = youtube_assets.get("assets") if isinstance(youtube_assets, dict) else None
    if isinstance(yt_assets, list):
        for asset in yt_assets:
            if not isinstance(asset, dict):
                continue
            path = _existing_image_path(asset.get("workspace_path"))
            if path and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                role = str(asset.get("role") or "youtube_keyframe")
                items.append(
                    {
                        "path": str(path),
                        "label": str(asset.get("label") or "视频画面"),
                        "role": role,
                    }
                )
    return items[:12]


def prepare_visual_asset_card(source_path: Path | None, output_path: Path, *, ffmpeg: str) -> tuple[Path | None, dict[str, Any]]:
    if source_path is None:
        return None, {"status": "missing", "reason": "No screenshot or README image was available."}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_path),
        "-vf",
        "scale=936:760:force_original_aspect_ratio=increase,crop=936:760:(iw-936)/2:0,setsar=1",
        "-frames:v",
        "1",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        return output_path, {
            "status": "succeeded",
            "source_path": str(source_path),
            "visual_asset_path": str(output_path),
            "placement": "center evidence card",
        }
    return None, {
        "status": "failed",
        "source_path": str(source_path),
        "error": (result.stderr or result.stdout or "visual asset preparation failed")[-1000:],
    }


def render_vertical_video(
    voice_path: Path,
    subtitle_path: Path,
    video_path: Path,
    *,
    duration: float,
    ffmpeg: str,
    subtitle_mode: str = "bilingual",
    brand_template: dict[str, Any] | None = None,
    cover_status: dict[str, Any] | None = None,
    visual_asset_path: Path | None = None,
    visual_asset_status: dict[str, Any] | None = None,
    director_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    brand_template = brand_template or build_brand_template("AI Opportunity Brief", content_id=video_path.parent.name)
    status: dict[str, Any] = {
        "status": "started",
        "video_path": str(video_path),
        "voice_path": str(voice_path),
        "subtitle_path": str(subtitle_path),
        "subtitle_mode": subtitle_mode,
        "duration_seconds": duration,
        "resolution": "1080x1920",
        "subtitle_burned": True,
        "template_id": brand_template.get("template_id", BRAND_TEMPLATE_ID),
        "brand_name": brand_template.get("brand_name", BRAND_NAME),
        "cover_status": cover_status or {},
        "visual_asset_status": visual_asset_status or {"status": "missing"},
        "director_status": {
            "status": "enabled" if director_plan else "disabled",
            "scene_count": len(director_plan.get("scenes", [])) if director_plan else 0,
            "shot_count": len(director_plan.get("shots", [])) if director_plan and isinstance(director_plan.get("shots"), list) else 0,
            "style": (director_plan.get("style", {}) if director_plan else {}).get("version", ""),
        },
        "visual_quality": "brand_template_v1",
        "visual_layers": brand_template.get("layers", []),
    }
    video_filter = _compose_video_filter(brand_template, subtitle_path)
    shot_assets = _director_shot_asset_paths(director_plan)
    scene_assets = shot_assets or _director_scene_asset_paths(director_plan)
    if scene_assets:
        _render_director_video(
            ffmpeg,
            voice_path,
            subtitle_path,
            video_path,
            duration=duration,
            brand_template=brand_template,
            scene_assets=scene_assets,
        )
        if video_path.exists() and video_path.stat().st_size > 0:
            status["status"] = "succeeded"
            status["director_status"]["render_mode"] = "shot_segmented_concat" if shot_assets else "segmented_concat"
            director_style = str((director_plan or {}).get("style", {}).get("version", ""))
            status["visual_quality"] = "director_v4_multi_shot" if director_style.startswith("video_director_v4") else ("director_v3_large_scene" if director_style.startswith("video_director_v3") else "brand_template_v1")
            return status

    command = _video_command(
        ffmpeg,
        voice_path,
        video_path,
        duration=duration,
        video_filter=video_filter,
        visual_asset_path=visual_asset_path,
    )
    result = subprocess.run(command, capture_output=True, text=True, timeout=max(120, math.ceil(duration) + 60))
    if result.returncode == 0 and video_path.exists() and video_path.stat().st_size > 0:
        status["status"] = "succeeded"
        return status

    status["subtitle_burned"] = False
    status["subtitle_error"] = (result.stderr or result.stdout or "subtitle render failed")[-2000:]
    fallback = subprocess.run(
        _video_command(ffmpeg, voice_path, video_path, duration=duration, video_filter=None, visual_asset_path=None),
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


def _video_command(
    ffmpeg: str,
    voice_path: Path,
    video_path: Path,
    *,
    duration: float,
    video_filter: str | None,
    visual_asset_path: Path | None = None,
    director_plan: dict[str, Any] | None = None,
) -> list[str]:
    _ = director_plan
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=#0f172a:s=1080x1920:r=30",
    ]
    if visual_asset_path:
        command.extend(["-loop", "1", "-i", str(visual_asset_path), "-i", str(voice_path)])
        audio_input_index = "2:a"
    else:
        command.extend(["-i", str(voice_path)])
        audio_input_index = "1:a"
    command.extend([
        "-t",
        f"{duration:.3f}",
    ])
    if video_filter:
        if visual_asset_path:
            command.extend(["-filter_complex", f"[0:v]{video_filter}[base];[base][1:v]overlay=72:352:format=auto[v]", "-map", "[v]", "-map", audio_input_index])
        else:
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


def _render_director_video(
    ffmpeg: str,
    voice_path: Path,
    subtitle_path: Path,
    video_path: Path,
    *,
    duration: float,
    brand_template: dict[str, Any],
    scene_assets: list[dict[str, Any]],
) -> None:
    segments_dir = video_path.parent / "director_segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []
    for index, scene in enumerate(scene_assets, start=1):
        start = float(scene.get("start") or 0.0)
        end = float(scene.get("end") or start + 1.0)
        segment_duration = max(0.8, min(duration, end) - start)
        segment_path = segments_dir / f"scene_{index:02d}.mp4"
        asset_path = scene.get("asset_path")
        command = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=#0f172a:s=1080x1920:r=30",
        ]
        if asset_path:
            command.extend(["-loop", "1", "-i", str(asset_path)])
            filter_complex = (
                f"[0:v]{_brand_filter(brand_template)}[base];"
                f"[1:v]{_asset_card_filter(scene, segment_duration)}[asset];"
                f"[base][asset]overlay={_asset_overlay_position(scene)}:format=auto[tmp];"
                f"[tmp]{_shot_style_filter(scene)}[v]"
            )
        else:
            filter_complex = f"[0:v]{_brand_filter(brand_template)},{_shot_style_filter(scene)}[v]"
        command.extend(
            [
                "-t",
                f"{segment_duration:.3f}",
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                str(segment_path),
            ]
        )
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=max(60, math.ceil(segment_duration) + 45),
        )
        segment_paths.append(segment_path)

    concat_list = segments_dir / "concat.txt"
    concat_list.write_text("\n".join(f"file '{_concat_escape(path)}'" for path in segment_paths) + "\n", encoding="utf-8")
    visual_track = segments_dir / "visual_track.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(visual_track),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=max(60, math.ceil(duration) + 45),
    )
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(visual_track),
            "-i",
            str(voice_path),
            "-t",
            f"{duration:.3f}",
            "-vf",
            _subtitle_filter(subtitle_path),
            "-map",
            "0:v",
            "-map",
            "1:a",
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
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=max(120, math.ceil(duration) + 60),
    )


def _concat_escape(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def _asset_card_filter(scene: dict[str, Any], duration: float) -> str:
    role = str(scene.get("role") or "")
    visual_type = str(scene.get("visual_type") or "")
    motion = str(scene.get("motion") or "slow_push")
    frames = max(24, int(math.ceil(duration * 30)))
    if visual_type == "repo_full_bleed":
        base = "scale=1080:1220:force_original_aspect_ratio=increase,crop=1080:1220:(iw-1080)/2:0"
    elif role == "readme_image" or visual_type == "readme_visual_card":
        base = "scale=1000:920:force_original_aspect_ratio=decrease,pad=1000:920:(ow-iw)/2:(oh-ih)/2:color=#020617"
    else:
        base = "scale=1000:920:force_original_aspect_ratio=increase,crop=1000:920:(iw-1000)/2:0"
    if motion == "snap_zoom":
        zoom = "zoompan=z='min(zoom+0.0020,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        return f"{base},{zoom}:d={frames}:s=1000x920:fps=30,setsar=1"
    if motion in {"slow_push", "quick_push", "push_right"}:
        step = "0.0014" if motion == "quick_push" else "0.0007"
        zoom = f"zoompan=z='min(zoom+{step},1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        return f"{base},{zoom}:d={frames}:s=1000x920:fps=30,setsar=1"
    return f"{base},setsar=1"


def _asset_overlay_position(scene: dict[str, Any]) -> str:
    visual_type = str(scene.get("visual_type") or "")
    if visual_type == "repo_full_bleed":
        return "0:206"
    if visual_type == "repo_evidence_zoom":
        return "40:280"
    if visual_type == "readme_visual_card":
        return "40:300"
    return "40:240"


def _shot_style_filter(scene: dict[str, Any]) -> str:
    visual_type = str(scene.get("visual_type") or "")
    highlight = str(scene.get("highlight") or "")
    styles = {
        "impact_title_card": "drawbox=x=72:y=300:w=936:h=520:color=#111827@0.92:t=fill,drawbox=x=112:y=350:w=760:h=10:color=#38bdf8@0.95:t=fill,drawbox=x=112:y=440:w=520:h=8:color=#a78bfa@0.90:t=fill,drawbox=x=112:y=560:w=820:h=180:color=#020617@0.72:t=fill",
        "keyword_punch_card": "drawbox=x=96:y=430:w=888:h=430:color=#172554@0.88:t=fill,drawbox=x=136:y=500:w=620:h=12:color=#38bdf8@0.95:t=fill,drawbox=x=136:y=610:w=770:h=100:color=#0f172a@0.86:t=fill",
        "judgement_card": "drawbox=x=72:y=360:w=936:h=620:color=#111827@0.94:t=fill,drawbox=x=112:y=420:w=14:h=460:color=#f59e0b@0.95:t=fill,drawbox=x=160:y=500:w=760:h=10:color=#f59e0b@0.92:t=fill",
        "repo_full_bleed": "drawbox=x=0:y=206:w=1080:h=6:color=#38bdf8@0.95:t=fill,drawbox=x=0:y=1426:w=1080:h=6:color=#38bdf8@0.85:t=fill",
        "repo_evidence_zoom": "drawbox=x=52:y=292:w=976:h=896:color=#38bdf8@0.22:t=6",
        "readme_visual_card": "drawbox=x=52:y=312:w=976:h=896:color=#a78bfa@0.24:t=6",
    }
    return ",".join([styles.get(visual_type, "null"), _highlight_filter(highlight)])


def _highlight_filter(highlight: str) -> str:
    boxes = {
        "stars": "drawbox=x=790:y=310:w=210:h=70:color=#38bdf8@0.60:t=6",
        "repo_about": "drawbox=x=760:y=360:w=245:h=230:color=#a78bfa@0.55:t=6",
        "repo_header": "drawbox=x=40:y=240:w=1000:h=96:color=#38bdf8@0.48:t=6",
        "center": "drawbox=x=85:y=340:w=910:h=540:color=#38bdf8@0.40:t=6",
        "chart": "drawbox=x=70:y=320:w=940:h=390:color=#38bdf8@0.40:t=6",
    }
    return boxes.get(highlight, "null")


def _director_shot_asset_paths(director_plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not director_plan:
        return []
    shots = director_plan.get("shots")
    if not isinstance(shots, list):
        return []
    selected: list[dict[str, Any]] = []
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        raw_asset_path = str(shot.get("asset_path") or "")
        asset_path = Path(raw_asset_path) if raw_asset_path else None
        selected.append(
            {
                "asset_path": asset_path if asset_path and asset_path.exists() and asset_path.is_file() else None,
                "start": float(shot.get("start") or 0.0),
                "end": float(shot.get("end") or 0.0),
                "role": str(shot.get("visual_type") or ""),
                "visual_type": str(shot.get("visual_type") or ""),
                "motion": str(shot.get("motion") or ""),
                "highlight": str(shot.get("highlight") or ""),
            }
        )
    return selected


def _director_scene_asset_paths(director_plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not director_plan:
        return []
    scenes = director_plan.get("scenes")
    if not isinstance(scenes, list):
        return []
    selected: list[dict[str, Any]] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        asset_path = Path(str(scene.get("asset_path") or ""))
        if not asset_path.exists() or not asset_path.is_file():
            continue
        selected.append(
            {
                "asset_path": asset_path,
                "start": float(scene.get("start") or 0.0),
                "end": float(scene.get("end") or 0.0),
                "role": str(scene.get("visual_role") or ""),
                "motion": str(scene.get("motion") or ""),
                "highlight": str(scene.get("highlight") or ""),
            }
        )
    return selected


def _subtitle_filter(subtitle_path: Path) -> str:
    escaped_path = str(subtitle_path).replace("\\", "\\\\").replace("'", "\\'")
    if subtitle_path.suffix.lower() == ".ass":
        return f"ass=filename='{escaped_path}'"
    style = (
        "FontName=Noto Sans CJK SC,"
        "FontSize=42,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H80000000,"
        "BorderStyle=1,"
        "Outline=2,"
        "Alignment=2,"
        "MarginL=90,"
        "MarginR=90,"
        "MarginV=240"
    )
    return f"subtitles=filename='{escaped_path}':original_size=1080x1920:force_style='{style}'"


def _ass_wrap(value: str, max_chars: int, *, max_lines: int = 2) -> str:
    text = " ".join(str(value).split())
    if len(text) <= max_chars:
        return _ass_escape(text)
    lines: list[str] = []
    current = ""
    for token in _wrap_tokens(text):
        if current and len(current) + len(token) > max_chars:
            lines.append(current.rstrip())
            current = token
        else:
            current += token
    if current:
        lines.append(current.rstrip())
    return "\\N".join(_ass_escape(line) for line in lines[:max_lines])


def _wrap_tokens(text: str) -> list[str]:
    if re.search(r"[\u4e00-\u9fff]", text):
        return re.findall(r"[A-Za-z0-9_.+-]+|.", text)
    return [token + " " for token in text.split()]


def _ass_escape(value: str) -> str:
    return str(value).replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _existing_image_path(value: object) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    if path.exists() and path.is_file():
        return path
    return None


def _compose_video_filter(brand_template: dict[str, Any], subtitle_path: Path) -> str:
    return ",".join([_brand_filter(brand_template), _subtitle_filter(subtitle_path)])


def _brand_filter(brand_template: dict[str, Any], *, include_subtitle_safe_area: bool = True) -> str:
    _ = brand_template
    filters = [
        "drawbox=x=0:y=0:w=1080:h=1920:color=#0f172a:t=fill",
        "drawbox=x=40:y=72:w=1000:h=118:color=#111827@0.94:t=fill",
        "drawbox=x=40:y=72:w=14:h=118:color=#38bdf8:t=fill",
        "drawbox=x=40:y=240:w=1000:h=920:color=#020617@0.72:t=fill",
        "drawbox=x=40:y=240:w=1000:h=6:color=#a78bfa@0.95:t=fill",
        "drawbox=x=58:y=1198:w=964:h=92:color=#111827@0.88:t=fill",
        "drawbox=x=82:y=1227:w=380:h=4:color=#38bdf8@0.95:t=fill",
        "drawbox=x=82:y=1254:w=610:h=3:color=#64748b@0.85:t=fill",
        "drawbox=x=72:y=1668:w=936:h=96:color=#111827@0.84:t=fill",
        "drawbox=x=108:y=1700:w=360:h=3:color=#64748b@0.85:t=fill",
        "drawbox=x=108:y=1726:w=520:h=3:color=#475569@0.80:t=fill",
        "drawbox=x=72:y=1808:w=936:h=8:color=#38bdf8@0.85:t=fill",
    ]
    if include_subtitle_safe_area:
        filters.append("drawbox=x=64:y=1360:w=952:h=250:color=#020617@0.38:t=fill")
    return ",".join(filters)


def _ascii_overlay_text(value: str) -> str:
    cleaned = re.sub(r"[\r\n]+", " ", value).strip()
    if not cleaned:
        return ""
    ascii_text = cleaned.encode("ascii", "ignore").decode("ascii").strip()
    if ascii_text:
        return _compact_text(ascii_text, max_chars=42)
    return "AI Opportunity Brief"


def _compact_text(value: str, *, max_chars: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "..."

