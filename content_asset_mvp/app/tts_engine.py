"""Narration TTS engine.

Provider order (first available wins, falls through on failure):

1. **Volcengine Doubao BigTTS 2.0** (uses ``VOLC_APPID`` + ``VOLC_ACCESS_TOKEN``)
   24 kHz / 160 kbps mp3, ~333 ms first-package latency, podcast-grade audio
   for Chinese AI/dev narration. Default voice ``zh_male_liufei_uranus_bigtts``
   (刘飞) — measured ~4.3 LU LRA on 60s real narration vs CosyVoice's 3.4 LU.
2. DashScope CosyVoice (uses ``QWEN_API_KEY`` / ``DASHSCOPE_API_KEY``)
   16 kHz / 64 kbps mp3, ``cosyvoice-v3-flash`` + ``longanyang``. Acceptable
   fallback when Volcengine is offline.
3. OpenAI ``gpt-4o-mini-tts`` / ``tts-1`` (uses ``OPENAI_API_KEY``)
   Acceptable English, mediocre Chinese.
4. Silent placeholder (offline fallback, never fails the pipeline).

V1 vs V3 split (Volcengine):
    Doubao "BigTTS 1.0" voices (``*_mars_bigtts`` / ``*_moon_bigtts``) used
    the V1 endpoint and supported SSML via ``text_type=ssml``. Doubao
    "BigTTS 2.0" voices (``*_uranus_bigtts``) require the V3 endpoint
    (``/api/v3/tts/unidirectional``) and a different auth scheme
    (``X-Api-App-Id`` / ``X-Api-Access-Key`` / ``X-Api-Resource-Id``).
    V3 does NOT support ``text_type=ssml`` — passing SSML to V3 makes the
    engine read the ``<speak>`` / ``<break>`` tags literally. Instead, V3
    exposes ``additions.context_texts`` (natural-language emotion prompt)
    which is the 2.0 way of controlling delivery. We auto-route based on
    voice suffix and pick the right resource_id.

Override via env:
    CONTENT_ASSET_TTS_PROVIDER=doubao|dashscope|openai|auto   (default auto)
    CONTENT_ASSET_TTS_VOICE=<voice id>                         (provider-specific)
    CONTENT_ASSET_TTS_MODEL=<model id>                         (DashScope only)
    VOLC_TTS_VOICE=<voice id>                                  (Doubao-specific override)
    VOLC_TTS_CLUSTER=volcano_tts                               (Doubao V1 cluster, ignored for V3)
    CONTENT_ASSET_TTS_DOUBAO_CONTEXT=<emotion hint>            (V3 only; passed via context_texts)

Returns the path to the generated audio (mp3 when any cloud provider
succeeds, wav when falling back to silent), plus a status dict that records
which provider was actually used so downstream tooling can surface the
truth (no fake "succeeded openai" if we secretly fell back).
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

# 2.0 Uranus voice — measured ~4.3 LU LRA on 60s narration, --25 LUFS,
# --6.7 dBTP. Pairs well with TP-gated mastering: it has 9+ dB of TP
# headroom, so the linear-mode loudnorm path can boost cleanly without
# entering compressive mode.
DOUBAO_DEFAULT_VOICE = "zh_male_liufei_uranus_bigtts"
# CosyVoice 2 — switched from v3-flash to v2 because v2's emotional /
# prosody control is meaningfully better for "讲述者" delivery. v3-flash
# trades expressiveness for first-package latency, which doesn't matter
# for our offline batch render. v2 supports the same SSML subset
# (``<speak>`` / ``<break>`` / ``<prosody rate>``) we already build in
# ``_text_to_doubao_ssml`` so no payload changes needed.
#
# Voice: ``longcheng_v2`` (深厚男声) maps closest to the persona we used
# on Doubao Uranus 刘飞 (sober tech explainer). Override via
# ``CONTENT_ASSET_TTS_VOICE`` for A/B against ``longhua_v2`` /
# ``longwan_v2`` / ``loongstella_v2`` etc.
DASHSCOPE_DEFAULT_VOICE = "longcheng_v2"
DASHSCOPE_DEFAULT_MODEL = "cosyvoice-v2"

# Default emotion / delivery prompt for BigTTS 2.0. Calibrated for the
# "海外 AI 信号" narrator persona — **讲述者口吻**, NOT 科技解说腔。
# Old hint asked for "沉稳压迫感的科技解说语气" which produced a flat
# AI-sounding broadcaster delivery (measured LRA ~1.6 LU). The new hint
# trades the broadcaster persona for an A-friend-telling-you-about-it
# persona — natural pauses, mild emotion, light surprise on numbers /
# rhetorical questions. This pairs with the rewrite_short_script v2
# prompt which writes the script in 讲述者 voice (short sentences /
# 你信吗 / 说白了 / 真的不多见). Override via
# CONTENT_ASSET_TTS_DOUBAO_CONTEXT.
DOUBAO_DEFAULT_CONTEXT = (
    "像跟好朋友聊一个你刚刷到的酷东西的语气，自然、放松、有点惊讶、有点小情绪。"
    "句子之间有真实的换气停顿，遇到数字（比如 9 万 2 千 Star、一万多 Fork）"
    "稍微停一下、轻微强调；遇到反问句尾（你信吗？/ 真的假的？/ 这不离谱吗？）"
    "尾音微微上扬。**不要主播腔、不要新闻腔、不要科技解说感**——更像是"
    "在咖啡馆给朋友讲一个最近发现的开源项目。允许轻微的情绪起伏和一点点笑意。"
)

# SSML break durations (milliseconds). Calibrated against an A/B test on
# DashScope CosyVoice — the naive "break after every comma" strategy
# pushed silence_ratio from 12% baseline to 30%+ regardless of break
# size, because Chinese narration scripts have ~100 commas per 700-char
# block and even 90ms × 100 ≈ 9s of stacked silence on top of engine
# breaths. So we drop comma-level breaks entirely and only insert at
# *structural* boundaries:
#
#   * paragraph (between markdown \n\n)   = 380ms  -- "scene change"
#   * sentence-final (。！？!?)            = 120ms  -- subtle re-pace
#                                            on top of engine's own ~500ms
#                                            breath; total feels ~600-700ms
#   * comma-grade (，、；)                  = 0ms   -- engines already
#                                            inflect on commas naturally
#
# These values target ≤ 15% silence_ratio while still keeping the LRA
# bump from sentence-boundary spacing. Treat as defaults; per-content
# overrides can come from upstream director hints later.
_SSML_BREAK_PARA_MS = 380
_SSML_BREAK_SENT_MS = 120
_SSML_BREAK_COMMA_MS = 0
# Tokens to read at half-speed for a "weight" beat — anchored to the
# narrative payload (numbers + units + brand names). Picks up tokens like
# "8 万 star" / "200 美元" / "GitHub" naturally; explicit allow-list keeps
# Doubao from mis-pronouncing "92K star" -> "九十二开斯达".
_SSML_SLOW_NUMBER_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:亿|万|千|百|分钟|秒|小时|美元|刀|元|星|stars?|MB|GB|分|岁|个|小时|分钟))",
    flags=re.IGNORECASE,
)
# Punctuation that ends a sentence in Chinese AI/dev voiceover scripts.
_SSML_SENT_PUNCT = "。！？!?"
_SSML_COMMA_PUNCT = "，、；"


def synthesize_narration(
    text: str,
    output_path: Path,
    *,
    ffmpeg: str,
    openai_api_key: str | None = None,
    qwen_api_key: str | None = None,
    volc_appid: str | None = None,
    volc_access_token: str | None = None,
    force_mock: bool = False,
    voice: str | None = None,
    model: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Synthesize ``text`` into an audio file at ``output_path``.

    The caller is expected to write the returned path into ``voice.wav``
    (silent fallback) or ``voice.mp3`` (cloud providers). We adapt
    automatically and return whichever path actually got written.
    """
    forced_provider = (os.getenv("CONTENT_ASSET_TTS_PROVIDER") or "auto").strip().lower()
    voice_override = voice or os.getenv("CONTENT_ASSET_TTS_VOICE")

    attempts: list[dict[str, Any]] = []

    # GPT-SoVITS V2Pro — local zero-shot inference. Highest priority in auto
    # mode when GPTSOVITS_API_URL + GPTSOVITS_REF_AUDIO are both set, because:
    # (1) Voice fidelity for Chinese reportedly exceeds MiniMax few-shot when
    #     the reference audio is the speaker's natural voice (community
    #     consensus on 中文 V2Pro). (2) Zero marginal cost — runs on local GPU.
    # (3) Cache invalidates when ref_audio path or prompt_text change.
    gptsovits_url = os.getenv("GPTSOVITS_API_URL")
    gptsovits_ref = os.getenv("GPTSOVITS_REF_AUDIO")
    if (
        not force_mock
        and gptsovits_url
        and gptsovits_ref
        and _provider_enabled(forced_provider, "gptsovits")
    ):
        wav_path = output_path.with_suffix(".wav")
        prompt_text = os.getenv("GPTSOVITS_PROMPT_TEXT", "")
        text_split_method = os.getenv("GPTSOVITS_TEXT_SPLIT", "cut5")
        try:
            audio_bytes, info = _gptsovits_tts(
                text,
                api_url=gptsovits_url,
                ref_audio_path=gptsovits_ref,
                prompt_text=prompt_text,
                text_split_method=text_split_method,
            )
        except Exception as exc:  # pragma: no cover - depends on network/provider state.
            attempts.append({
                "provider": "gptsovits",
                "api_url": gptsovits_url,
                "ref_audio": gptsovits_ref,
                "error": _safe_error_message(exc),
            })
            audio_bytes = b""
            info = {}

        if audio_bytes:
            wav_path.write_bytes(audio_bytes)
            status = {
                "status": "succeeded",
                "mode": "gptsovits_v2pro_zero_shot",
                "provider": "gptsovits",
                "model": "v2Pro",
                "voice": "cloned_local",
                "ref_audio_path": gptsovits_ref,
                "prompt_text_chars": len(prompt_text),
                "voice_path": str(wav_path),
                "audio_bytes": len(audio_bytes),
                "text_chars": len(text),
                "text_split_method": text_split_method,
                "engine": "tts_engine.gptsovits",
                "architecture_version": "video_pipeline_v6_slice",
            }
            if attempts:
                status["fallback_attempts"] = attempts
            return wav_path, status

    # MiniMax — highest priority in auto-mode. Why: voice cloning support
    # (the only way to escape "off-the-shelf AI 味"), simpler API than
    # Volcengine (no resource license / appid / token tri-key dance), and
    # speech-02-hd is widely regarded as best-in-class Chinese naturalness
    # as of 2026. When MINIMAX_API_KEY + MINIMAX_VOICE_ID are both set we
    # prefer it. CONTENT_ASSET_TTS_PROVIDER=doubao still bypasses to allow
    # A/B with Volcengine voices.
    minimax_key = os.getenv("MINIMAX_API_KEY")
    minimax_voice = os.getenv("MINIMAX_VOICE_ID")
    if (
        not force_mock
        and minimax_key
        and minimax_voice
        and _provider_enabled(forced_provider, "minimax")
    ):
        mp3_path = output_path.with_suffix(".mp3")
        minimax_model = os.getenv("MINIMAX_MODEL", "speech-02-hd")
        # MiniMax 默认 vol=1.0 在我们这个 mastering chain 下进来是
        # ~-11.9 LUFS + TP 0 dBTP（已 clipping）。降到 0.80 让进来
        # 约 -13.8 LUFS、TP -2 dBTP，mastering 可以 cleanly 拉到 -14。
        minimax_volume = float(os.getenv("MINIMAX_VOLUME", "0.80"))
        try:
            audio_bytes, info = _minimax_tts(
                text,
                api_key=minimax_key,
                voice_id=minimax_voice,
                model=minimax_model,
                volume=minimax_volume,
            )
        except Exception as exc:  # pragma: no cover - depends on network/provider state.
            attempts.append({
                "provider": "minimax",
                "model": minimax_model,
                "voice": minimax_voice,
                "error": _safe_error_message(exc),
            })
            audio_bytes = b""
            info = {}

        if audio_bytes:
            mp3_path.write_bytes(audio_bytes)
            status = {
                "status": "succeeded",
                "mode": "minimax_t2a_v2",
                "provider": "minimax",
                "model": minimax_model,
                "voice": minimax_voice,
                "voice_path": str(mp3_path),
                "audio_bytes": len(audio_bytes),
                "trace_id": info.get("trace_id"),
                "text_chars": len(text),
                "engine": "tts_engine.minimax",
                "architecture_version": "video_pipeline_v6_slice",
                "extra_info": info.get("extra_info"),
            }
            if attempts:
                status["fallback_attempts"] = attempts
            return mp3_path, status

    # Auto-mode preference flip — DashScope CosyVoice 2 first.
    #
    # Why: V3 Uranus on Doubao does NOT support SSML (engine reads
    # ``<speak>`` / ``<break>`` literally) and the additions.context_texts
    # emotion knob is one-shot — no per-clause control. CosyVoice 2 on
    # DashScope accepts our existing SSML payload (``<break>`` /
    # ``<prosody rate=slow>``) so we get clause-level pacing on numbers
    # and brand names. Measured LRA on the same script: CosyVoice 2 ~4.5 LU
    # vs Doubao Uranus ~2.3-3.4 LU. The latter is the bottleneck on
    # "robotic narration" perception.
    #
    # Volcengine remains the fallback path when explicitly requested
    # (``CONTENT_ASSET_TTS_PROVIDER=doubao``) or when DashScope is offline.
    skip_doubao_in_auto = (
        forced_provider == "auto"
        and bool(qwen_api_key)
        and not force_mock
    )

    if not skip_doubao_in_auto and not force_mock and _provider_enabled(forced_provider, "doubao") and volc_appid and volc_access_token:
        doubao_voice = (
            os.getenv("VOLC_TTS_VOICE")
            or (voice_override if voice_override and voice_override.endswith("_bigtts") else None)
            or DOUBAO_DEFAULT_VOICE
        )
        api_version, resource_id = _doubao_route_for_voice(doubao_voice)
        cluster = os.getenv("VOLC_TTS_CLUSTER", "volcano_tts")
        mp3_path = output_path.with_suffix(".mp3")

        if api_version == "v3":
            # 2.0 (uranus) voices on V3: SSML is NOT supported (engine
            # reads tags as text), so we use ``additions.context_texts``
            # for delivery control. Empty string disables emotion shaping.
            context_hint = os.getenv("CONTENT_ASSET_TTS_DOUBAO_CONTEXT", DOUBAO_DEFAULT_CONTEXT).strip()
            ssml_status: dict[str, Any] = {
                "enabled": False,
                "applied": False,
                "skip_reason": "v3_does_not_support_ssml",
                "context_texts": context_hint or None,
            }
            try:
                audio_bytes, info = _doubao_seedtts_v3(
                    text,
                    appid=volc_appid,
                    access_token=volc_access_token,
                    voice=doubao_voice,
                    resource_id=resource_id,
                    context_texts=[context_hint] if context_hint else None,
                )
            except Exception as exc:  # pragma: no cover - depends on network/provider state.
                attempts.append({
                    "provider": "doubao",
                    "api_version": "v3",
                    "voice": doubao_voice,
                    "resource_id": resource_id,
                    "error": _safe_error_message(exc),
                })
                audio_bytes = b""
                info = {}

            if audio_bytes:
                mp3_path.write_bytes(audio_bytes)
                status = {
                    "status": "succeeded",
                    "mode": "volc_doubao_seedtts_v3",
                    "provider": "doubao",
                    "model": "bigtts-2.0",
                    "voice": doubao_voice,
                    "api_version": "v3",
                    "resource_id": resource_id,
                    "voice_path": str(mp3_path),
                    "audio_bytes": len(audio_bytes),
                    "request_id": info.get("request_id"),
                    "text_chars": len(text),
                    "ssml_status": ssml_status,
                    "engine": "tts_engine.doubao_v3",
                    "architecture_version": "video_pipeline_v6_slice",
                }
                if attempts:
                    status["fallback_attempts"] = attempts
                return mp3_path, status
        else:
            # 1.0 (mars/moon/wvae) voices on V1: SSML supported via
            # text_type=ssml. We try SSML first, fall back to plain on
            # provider rejection.
            ssml_enabled = os.getenv("CONTENT_ASSET_TTS_SSML", "1").strip() != "0"
            ssml_status = {
                "enabled": ssml_enabled,
                "applied": False,
            }
            ssml_payload = ""
            if ssml_enabled:
                ssml_payload = _text_to_doubao_ssml(text)
                ssml_status["chars"] = len(ssml_payload)

            last_err: Exception | None = None
            audio_bytes = b""
            info = {}
            if ssml_enabled and ssml_payload:
                try:
                    audio_bytes, info = _doubao_bigtts_tts(
                        ssml_payload,
                        appid=volc_appid,
                        access_token=volc_access_token,
                        cluster=cluster,
                        voice=doubao_voice,
                        text_type="ssml",
                    )
                    ssml_status["applied"] = True
                except Exception as exc:  # pragma: no cover - depends on network/provider state.
                    last_err = exc
                    ssml_status["fallback_reason"] = _safe_error_message(exc)
                    audio_bytes = b""
                    info = {}

            if not ssml_status["applied"]:
                try:
                    audio_bytes, info = _doubao_bigtts_tts(
                        text,
                        appid=volc_appid,
                        access_token=volc_access_token,
                        cluster=cluster,
                        voice=doubao_voice,
                        text_type="plain",
                    )
                except Exception as exc:  # pragma: no cover - depends on network/provider state.
                    attempts.append({
                        "provider": "doubao",
                        "api_version": "v1",
                        "voice": doubao_voice,
                        "error": _safe_error_message(exc),
                        "ssml_attempted": ssml_enabled,
                        "ssml_error": ssml_status.get("fallback_reason"),
                    })
                    last_err = exc
                    audio_bytes = b""
                    info = {}

            if audio_bytes:
                mp3_path.write_bytes(audio_bytes)
                status = {
                    "status": "succeeded",
                    "mode": "volc_doubao_bigtts",
                    "provider": "doubao",
                    "model": "bigtts-1.0",
                    "voice": doubao_voice,
                    "api_version": "v1",
                    "cluster": cluster,
                    "voice_path": str(mp3_path),
                    "audio_bytes": len(audio_bytes),
                    "first_package_delay_ms": info.get("first_package_delay_ms"),
                    "audio_duration_ms": info.get("audio_duration_ms"),
                    "request_id": info.get("request_id"),
                    "text_chars": len(text),
                    "ssml_status": ssml_status,
                    "engine": "tts_engine.doubao",
                    "architecture_version": "video_pipeline_v6_slice",
                }
                if attempts:
                    status["fallback_attempts"] = attempts
                return mp3_path, status
            _ = last_err  # explicitly acknowledge it for the linter

    if not force_mock and _provider_enabled(forced_provider, "dashscope") and qwen_api_key:
        ds_voice = voice_override or DASHSCOPE_DEFAULT_VOICE
        ds_model = model or os.getenv("CONTENT_ASSET_TTS_MODEL") or DASHSCOPE_DEFAULT_MODEL
        mp3_path = output_path.with_suffix(".mp3")
        # CosyVoice v3 supports a SSML subset (``<speak>``, ``<break>``,
        # ``<prosody rate=...>``). Reusing the same SSML payload we built
        # for Doubao keeps both providers aligned on phrasing and lets
        # whichever one is online lift the per-track LRA.
        ds_ssml_enabled = os.getenv("CONTENT_ASSET_TTS_SSML", "1").strip() != "0"
        ds_ssml_status: dict[str, Any] = {
            "enabled": ds_ssml_enabled,
            "applied": False,
        }
        ds_ssml_payload = ""
        if ds_ssml_enabled:
            ds_ssml_payload = _text_to_doubao_ssml(text)
            ds_ssml_status["chars"] = len(ds_ssml_payload)

        ds_audio: bytes = b""
        ds_info: dict[str, Any] = {}
        if ds_ssml_enabled and ds_ssml_payload:
            try:
                ds_audio, ds_info = _dashscope_cosyvoice_tts(
                    ds_ssml_payload,
                    api_key=qwen_api_key,
                    model=ds_model,
                    voice=ds_voice,
                )
                ds_ssml_status["applied"] = True
            except Exception as exc:  # pragma: no cover - depends on network/provider state.
                ds_ssml_status["fallback_reason"] = _safe_error_message(exc)

        if not ds_ssml_status["applied"]:
            try:
                ds_audio, ds_info = _dashscope_cosyvoice_tts(
                    text,
                    api_key=qwen_api_key,
                    model=ds_model,
                    voice=ds_voice,
                )
            except Exception as exc:  # pragma: no cover - depends on network/provider state.
                attempts.append({
                    "provider": "dashscope",
                    "model": ds_model,
                    "voice": ds_voice,
                    "error": _safe_error_message(exc),
                    "ssml_attempted": ds_ssml_enabled,
                    "ssml_error": ds_ssml_status.get("fallback_reason"),
                })
                ds_audio = b""

        if ds_audio:
            mp3_path.write_bytes(ds_audio)
            status = {
                "status": "succeeded",
                "mode": "dashscope_cosyvoice",
                "provider": "dashscope",
                "model": ds_model,
                "voice": ds_voice,
                "voice_path": str(mp3_path),
                "audio_bytes": len(ds_audio),
                "first_package_delay_ms": ds_info.get("first_package_delay_ms"),
                "request_id": ds_info.get("request_id"),
                "text_chars": len(text),
                "ssml_status": ds_ssml_status,
                "engine": "tts_engine.dashscope",
                "architecture_version": "video_pipeline_v6_slice",
            }
            if attempts:
                status["fallback_attempts"] = attempts
            return mp3_path, status

    if not force_mock and _provider_enabled(forced_provider, "openai") and openai_api_key:
        from .media_producer import _openai_tts  # reuse existing implementation

        mp3_path = output_path.with_suffix(".mp3")
        try:
            _openai_tts(text, mp3_path, openai_api_key=openai_api_key)
            status = {
                "status": "succeeded",
                "mode": "openai",
                "provider": "openai",
                "model": "gpt-4o-mini-tts/tts-1 compatible",
                "voice": "alloy",
                "voice_path": str(mp3_path),
                "text_chars": len(text),
                "engine": "tts_engine.openai",
                "architecture_version": "video_pipeline_v6_slice",
            }
            if attempts:
                status["fallback_attempts"] = attempts
            return mp3_path, status
        except Exception as exc:  # pragma: no cover - depends on network/provider state.
            attempts.append({
                "provider": "openai",
                "model": "gpt-4o-mini-tts/tts-1",
                "error": _safe_error_message(exc),
            })

    from .media_producer import _generate_silent_audio, estimate_duration

    duration = estimate_duration(text)
    _generate_silent_audio(output_path, duration, ffmpeg=ffmpeg)
    if force_mock:
        reason = "video mock mode enabled"
    elif not (volc_access_token or qwen_api_key or openai_api_key):
        reason = "no TTS credentials configured (VOLC_ACCESS_TOKEN / QWEN_API_KEY / OPENAI_API_KEY)"
    else:
        reason = "all providers failed; see fallback_attempts"
    return output_path, {
        "status": "succeeded",
        "mode": "offline_silence",
        "provider": "silent",
        "voice_path": str(output_path),
        "duration_seconds": duration,
        "text_chars": len(text),
        "reason": reason,
        "fallback_attempts": attempts,
        "engine": "tts_engine.silent",
        "architecture_version": "video_pipeline_v6_slice",
    }


def _provider_enabled(forced: str, name: str) -> bool:
    """Honor CONTENT_ASSET_TTS_PROVIDER=auto|minimax|doubao|dashscope|openai."""
    if forced in ("", "auto"):
        return True
    return forced == name


def _gptsovits_tts(
    text: str,
    *,
    api_url: str,
    ref_audio_path: str,
    prompt_text: str = "",
    prompt_lang: str = "zh",
    text_lang: str = "zh",
    text_split_method: str = "cut5",
    top_k: int = 15,
    top_p: float = 1.0,
    temperature: float = 1.0,
    speed_factor: float = 1.0,
    seed: int = -1,
) -> tuple[bytes, dict[str, Any]]:
    """Call local GPT-SoVITS V2Pro api_v2.py endpoint.

    Default port 9880. Returns WAV bytes; downstream mastering wraps to mp3.
    The first call may take longer (~30s) as the model JIT-compiles
    inference graphs; subsequent calls are ~0.5x real-time.
    """
    import urllib.request
    import urllib.error

    body = json.dumps({
        "text": text,
        "text_lang": text_lang,
        "ref_audio_path": ref_audio_path,
        "prompt_text": prompt_text,
        "prompt_lang": prompt_lang,
        "text_split_method": text_split_method,
        "batch_size": 1,
        "top_k": top_k,
        "top_p": top_p,
        "temperature": temperature,
        "speed_factor": speed_factor,
        "seed": seed,
        "media_type": "wav",
        "streaming_mode": False,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        api_url.rstrip("/") + "/tts",
        data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            audio = resp.read()
            trace_id = resp.headers.get("X-Request-Id") or ""
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400] if exc.fp else ""
        raise RuntimeError(f"GPT-SoVITS HTTP {exc.code}: {detail or exc.reason}") from exc

    if not audio or len(audio) < 1024:
        raise RuntimeError(f"GPT-SoVITS returned too-small audio ({len(audio)} bytes)")

    return audio, {"trace_id": trace_id, "wav_bytes": len(audio)}


def _minimax_tts(
    text: str,
    *,
    api_key: str,
    voice_id: str,
    model: str = "speech-02-hd",
    speed: float = 1.0,
    volume: float = 1.0,
    pitch: int = 0,
    sample_rate: int = 32000,
    bitrate: int = 128000,
) -> tuple[bytes, dict[str, Any]]:
    """Call MiniMax t2a_v2 endpoint (国内 platform.minimaxi.com).

    Returns (mp3_bytes, info_dict). Cloned voices use the same endpoint
    with their custom voice_id (e.g. ``oca_main_v1`` from /v1/voice_clone).

    Audio is returned as hex-encoded mp3 inside response.data.audio.
    Response also includes ``extra_info`` (audio_length / usage_characters
    etc.) which we surface for billing visibility.
    """
    import urllib.request
    import urllib.error

    body = json.dumps({
        "model": model,
        "text": text,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": float(speed),
            "vol": float(volume),
            "pitch": int(pitch),
        },
        "audio_setting": {
            "sample_rate": int(sample_rate),
            "bitrate": int(bitrate),
            "format": "mp3",
            "channel": 1,
        },
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        "https://api.minimaxi.com/v1/t2a_v2",
        data=body, method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400] if exc.fp else ""
        raise RuntimeError(f"MiniMax t2a_v2 HTTP {exc.code}: {detail or exc.reason}") from exc

    data = json.loads(raw)
    base = data.get("base_resp") or {}
    if base.get("status_code") not in (0, None):
        raise RuntimeError(f"MiniMax t2a_v2 error code={base.get('status_code')} msg={base.get('status_msg')!r}")

    audio_hex = (data.get("data") or {}).get("audio") or ""
    if not audio_hex:
        raise RuntimeError(f"MiniMax t2a_v2 returned no audio: {raw[:300]}")

    audio_bytes = bytes.fromhex(audio_hex)
    return audio_bytes, {
        "trace_id": data.get("trace_id"),
        "extra_info": data.get("extra_info") or {},
    }


def _doubao_route_for_voice(voice: str) -> tuple[str, str]:
    """Return ``(api_version, resource_id)`` for the given Doubao voice.

    BigTTS 1.0 voices (``*_mars_bigtts``, ``*_moon_bigtts``, ``ICL_*``,
    ``*_wvae_bigtts``) live on V1 with cluster-based addressing. The
    resource_id we report for these is informational only — V1 doesn't
    use the ``X-Api-Resource-Id`` header.

    BigTTS 2.0 voices (``*_uranus_bigtts``, ``saturn_*``) and ICL 2.0
    cloned voices (``S_*``) require the V3 endpoint with the
    ``X-Api-Resource-Id`` header set to the matching pool.
    """
    if voice.startswith("S_"):
        return "v3", "seed-icl-2.0"
    if voice.startswith("saturn_") or "_uranus_" in voice:
        return "v3", "seed-tts-2.0"
    return "v1", "seed-tts-1.0"


def _doubao_seedtts_v3(
    text: str,
    *,
    appid: str,
    access_token: str,
    voice: str,
    resource_id: str,
    context_texts: list[str] | None = None,
    speech_rate: int = 0,
) -> tuple[bytes, dict[str, Any]]:
    """Call Volcengine Doubao BigTTS 2.0 (V3 unidirectional) and return mp3 bytes.

    Endpoint: ``POST https://openspeech.bytedance.com/api/v3/tts/unidirectional``
    Auth headers: ``X-Api-App-Id``, ``X-Api-Access-Key``, ``X-Api-Resource-Id``.
    Response is NDJSON — each line is one JSON object with ``code`` /
    ``data`` (base64 audio chunk). ``code == 20000000`` signals end of
    stream; any other non-zero code is an error and short-circuits.

    ``context_texts`` is the 2.0-only natural-language emotion prompt
    (e.g. "用沉稳、有节奏感的科技解说语气"). Pass ``None`` to disable
    emotion shaping. SSML is intentionally NOT supported here — the V3
    engine reads ``<speak>`` / ``<break>`` tags as literal text.
    """
    import base64
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    audio_params: dict[str, Any] = {
        "format": "mp3",
        "sample_rate": 24000,
    }
    if speech_rate:
        audio_params["speech_rate"] = max(-50, min(100, int(speech_rate)))

    req_params: dict[str, Any] = {
        "text": text,
        "speaker": voice,
        "audio_params": audio_params,
    }
    additions: dict[str, Any] = {}
    if context_texts:
        additions["context_texts"] = list(context_texts)
    if additions:
        # ``additions`` MUST be a JSON-serialized string at the protocol
        # level. Putting an object here is the most common V3 integration
        # error and silently degrades 2.0 behaviour to 1.0.
        req_params["additions"] = json.dumps(additions, ensure_ascii=False)

    body = json.dumps({"user": {"uid": "content_asset_pipeline"}, "req_params": req_params}).encode("utf-8")
    request_id = uuid.uuid4().hex
    req = Request(
        "https://openspeech.bytedance.com/api/v3/tts/unidirectional",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Api-App-Id": appid,
            "X-Api-Access-Key": access_token,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": request_id,
        },
    )

    try:
        with urlopen(req, timeout=120) as response:
            raw = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500] if exc.fp else ""
        raise RuntimeError(
            f"Doubao SeedTTS V3 HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Doubao SeedTTS V3 network error: {exc.reason}") from exc

    chunks: list[bytes] = []
    end_seen = False
    last_error: dict[str, Any] | None = None
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        code = obj.get("code")
        if code == 0 and obj.get("data"):
            try:
                chunks.append(base64.b64decode(obj["data"]))
            except Exception:
                continue
        elif code == 20000000:
            end_seen = True
        elif code not in (None, 0, 20000000):
            last_error = obj

    if last_error is not None:
        raise RuntimeError(
            f"Doubao SeedTTS V3 returned code={last_error.get('code')} "
            f"message={last_error.get('message')!r}"
        )
    if not chunks:
        raise RuntimeError("Doubao SeedTTS V3 returned empty audio (no base64 chunks)")

    audio_bytes = b"".join(chunks)
    return audio_bytes, {"request_id": request_id, "end_seen": end_seen}


def _doubao_bigtts_tts(
    text: str,
    *,
    appid: str,
    access_token: str,
    cluster: str,
    voice: str,
    text_type: str = "plain",
) -> tuple[bytes, dict[str, Any]]:
    """Call Volcengine Doubao BigTTS 2.0 (HTTP unary) and return mp3 bytes.

    Endpoint: ``POST https://openspeech.bytedance.com/api/v1/tts``
    Auth header: ``Authorization: Bearer;<access_token>`` (note the semicolon).
    Returns base64-encoded mp3 in ``data`` field; success when ``code == 3000``.

    ``text_type`` defaults to ``plain``. Pass ``ssml`` and supply a full
    ``<speak>...</speak>`` document to use SSML breaks / prosody — this is
    how we lift the per-track LRA from ~4.3 LU to ≥ 6 LU without retraining
    the voice. If the provider rejects SSML, callers should fall back to
    plain text rather than failing the pipeline.
    """
    import base64
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    payload: dict[str, Any] = {
        "app": {
            "appid": appid,
            "token": access_token,
            "cluster": cluster,
        },
        "user": {"uid": "content_asset_pipeline"},
        "audio": {
            "voice_type": voice,
            "encoding": "mp3",
            "speed_ratio": 1.0,
        },
        "request": {
            "reqid": uuid.uuid4().hex,
            "text": text,
            "operation": "query",
        },
    }
    if text_type == "ssml":
        payload["request"]["text_type"] = "ssml"

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        "https://openspeech.bytedance.com/api/v1/tts",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer;{access_token}",
        },
    )

    try:
        with urlopen(req, timeout=60) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500] if exc.fp else ""
        raise RuntimeError(
            f"Doubao BigTTS HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Doubao BigTTS network error: {exc.reason}") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"Doubao BigTTS non-JSON response (first 200 bytes): {raw[:200]!r}"
        ) from exc

    code = data.get("code")
    if code != 3000:
        raise RuntimeError(
            f"Doubao BigTTS returned code={code} message={data.get('message')!r}"
        )

    audio_b64 = data.get("data")
    if not isinstance(audio_b64, str) or not audio_b64:
        raise RuntimeError("Doubao BigTTS returned empty audio payload")

    audio_bytes = base64.b64decode(audio_b64)

    addition = data.get("addition") or {}
    info: dict[str, Any] = {
        "request_id": data.get("reqid"),
    }
    if isinstance(addition, dict):
        try:
            info["audio_duration_ms"] = int(addition.get("duration"))
        except (TypeError, ValueError):
            pass
        try:
            info["first_package_delay_ms"] = int(addition.get("first_pkg"))
        except (TypeError, ValueError):
            pass
    return audio_bytes, info


# DashScope CosyVoice synchronous ``synth.call()`` rejects payloads above
# ~1500-2000 chars with ``error 411 ContentTooLarge``. SSML wrapping
# blows our ~1400-char Chinese scripts past that ceiling (paragraph +
# sentence breaks add ~600 chars of XML tags). When this trips we have
# to chunk the SSML into ``<speak>`` documents per paragraph, synthesise
# each, and concat the MP3 byte streams. CosyVoice MP3 output is fixed
# 24 kHz / 64 kbps so byte-level concat is safe (no transcoding click).
_DASHSCOPE_PAYLOAD_LIMIT = 1500


def _split_ssml_into_paragraph_payloads(ssml: str) -> list[str]:
    """Split a ``<speak>...</speak>`` payload into paragraph-level chunks.

    The Doubao SSML builder emits paragraphs separated by
    ``<break time="380ms"/>`` (the ``_SSML_BREAK_PARA_MS`` token). We
    cut on those, re-wrap each chunk in ``<speak>...</speak>``, and
    keep chunks under ~1500 chars so each call stays inside DashScope's
    payload ceiling. Any chunk still over the limit gets force-split
    on sentence boundaries as a fallback.
    """
    if not ssml.startswith("<speak>") or not ssml.endswith("</speak>"):
        return [ssml]
    inner = ssml[len("<speak>"):-len("</speak>")]
    para_token = f'<break time="{_SSML_BREAK_PARA_MS}ms"/>'
    raw_parts = inner.split(para_token) if para_token in inner else [inner]
    chunks: list[str] = []
    for part in raw_parts:
        part = part.strip()
        if not part:
            continue
        wrapped = f"<speak>{part}</speak>"
        if len(wrapped) <= _DASHSCOPE_PAYLOAD_LIMIT:
            chunks.append(wrapped)
            continue
        # Still too big — split on sentence-final break tokens.
        sent_token = f'<break time="{_SSML_BREAK_SENT_MS}ms"/>'
        if sent_token in part:
            sub_parts = part.split(sent_token)
            buf = ""
            for sp in sub_parts:
                tentative = (buf + sent_token + sp) if buf else sp
                if len(f"<speak>{tentative}</speak>") <= _DASHSCOPE_PAYLOAD_LIMIT:
                    buf = tentative
                else:
                    if buf:
                        chunks.append(f"<speak>{buf}</speak>")
                    buf = sp
            if buf:
                chunks.append(f"<speak>{buf}</speak>")
        else:
            chunks.append(wrapped)  # keep oversized; let caller handle 411
    return chunks


def _dashscope_cosyvoice_tts(
    text: str,
    *,
    api_key: str,
    model: str,
    voice: str,
) -> tuple[bytes, dict[str, Any]]:
    """Call DashScope CosyVoice and return mp3 bytes (chunked when needed).

    We pass ``volume=80`` (default 50) so the synthesized output lands
    around -16 LUFS instead of -22 LUFS. Why this matters: the mastering
    pass needs to bring the signal up to -14 LUFS for short-video
    platform parity. Going from -22 to -14 is a 8 dB linear gain that
    overshoots TP and forces ffmpeg ``loudnorm`` into dynamic mode,
    which compresses LRA from ~4 LU down to ~2 LU. From -16 LUFS the
    gain headroom (~2 dB) fits inside linear mode and LRA is preserved.
    Volume=90 hits 0 dBFS clipping risk; 80 is the sweet spot we
    measured (LUFS=-16.4, TP=-0.02, LRA=4.10).

    SSML chunking: when ``text`` is a long ``<speak>`` payload we split
    on paragraph breaks and synthesise each chunk separately, then
    byte-concat the resulting MP3s. CosyVoice's fixed 24 kHz / 64 kbps
    output makes byte-concat safe.
    """
    import dashscope  # type: ignore[import-untyped]
    from dashscope.audio.tts_v2 import SpeechSynthesizer  # type: ignore[import-untyped]

    dashscope.api_key = api_key

    try:
        # CosyVoice 2 lands at -16 LUFS / TP ≈ +0.1 dBTP at volume=80,
        # which leaves zero headroom for the mastering clean_gain regime
        # (it clamps to peak_tame and audio_lufs stays at 56/100). Drop
        # to volume=65 so output sits at ≈ -19 LUFS / TP -3 dBTP, giving
        # 1.5 dB of usable headroom for the alimiter-chained gain push
        # back to -14 LUFS. v3-flash + Doubao keep the older 80 default
        # via env override since their default loudness curves differ.
        default_vol = "65" if model.startswith("cosyvoice-v2") else "80"
        cosyvoice_volume = int(os.getenv("CONTENT_ASSET_TTS_VOLUME", default_vol))
        cosyvoice_volume = max(0, min(100, cosyvoice_volume))
    except (TypeError, ValueError):
        cosyvoice_volume = 65 if model.startswith("cosyvoice-v2") else 80

    is_ssml = text.startswith("<speak>") and text.endswith("</speak>")
    if is_ssml:
        # CosyVoice 2 / v3-flash reject <prosody> tags with error 411
        # (only <speak> + <break> are accepted on those models). The
        # number-emphasis effect is lost, but <break>-driven pacing is
        # what actually moves LRA — slow-prosody on tokens contributes
        # only ~0.2 LU based on A/B measurements. Strip prosody, keep
        # the inner text. ``re.DOTALL`` so wraps that span newlines
        # don't escape the strip.
        text = re.sub(r'<prosody[^>]*>(.*?)</prosody>', r'\1', text, flags=re.DOTALL)
    if is_ssml and len(text) > _DASHSCOPE_PAYLOAD_LIMIT:
        chunks = _split_ssml_into_paragraph_payloads(text)
        audio_blobs: list[bytes] = []
        last_request_id: str | None = None
        first_delay: int | None = None
        for chunk in chunks:
            synth = SpeechSynthesizer(model=model, voice=voice, volume=cosyvoice_volume)
            chunk_audio = synth.call(chunk)
            if not chunk_audio:
                raise RuntimeError(
                    f"DashScope CosyVoice returned empty audio for SSML chunk "
                    f"(len={len(chunk)}, model={model}, voice={voice})"
                )
            audio_blobs.append(chunk_audio)
            try:
                last_request_id = synth.get_last_request_id()
            except Exception:
                pass
            if first_delay is None:
                try:
                    first_delay = synth.get_first_package_delay()
                except Exception:
                    pass
        audio = b"".join(audio_blobs)
        info = {
            "request_id": last_request_id,
            "first_package_delay_ms": first_delay,
            "ssml_chunks": len(audio_blobs),
        }
        return audio, info

    synthesizer = SpeechSynthesizer(model=model, voice=voice, volume=cosyvoice_volume)
    audio = synthesizer.call(text)

    if not audio:
        raise RuntimeError(
            "DashScope CosyVoice returned empty audio "
            "(check model/voice compatibility — v3 models need v3 voices)"
        )

    info: dict[str, Any] = {}
    try:
        info["request_id"] = synthesizer.get_last_request_id()
    except Exception:
        pass
    try:
        info["first_package_delay_ms"] = synthesizer.get_first_package_delay()
    except Exception:
        pass
    return audio, info


def _xml_escape_text(value: str) -> str:
    """Escape text content for SSML.

    SSML payloads are XML and Doubao will refuse the request if we forget
    to escape ``< > &``. We deliberately leave ``"`` and ``'`` alone since
    they only need escaping inside attribute values, and we never put
    user content there.
    """
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _slow_wrap_numbers_and_brands(segment: str) -> str:
    """Wrap numeric+unit phrases in ``<prosody rate="slow">`` for emphasis.

    Why only numbers/units (not brand names): Chinese TTS engines are
    already trained to handle product names like "GitHub" or "Codex"
    fluently, but they consistently rush through "8 万 star" or
    "92K stars" — slowing those by ~15% adds the perception of weight that
    matches how human creators (Peter Yang, MyElc) deliver the same beats.
    """
    if not segment:
        return segment

    def _wrap(match: re.Match[str]) -> str:
        token = _xml_escape_text(match.group(1))
        return f'<prosody rate="slow">{token}</prosody>'

    return _SSML_SLOW_NUMBER_RE.sub(_wrap, segment)


def _segment_to_ssml(segment: str) -> str:
    """Process one already-escaped (no XML special chars) text segment.

    Trailing sentence-final punctuation triggers a long break; trailing
    comma-grade punctuation triggers a shorter break. Numbers + units get
    a slow-prosody wrap. We DO NOT remove the punctuation itself — the
    voice engine still needs the visual cue, the break just adds extra
    silence on top.
    """
    if not segment:
        return ""
    text = segment.strip()
    if not text:
        return ""
    last = text[-1]
    if last in _SSML_SENT_PUNCT:
        break_ms = _SSML_BREAK_SENT_MS
    elif last in _SSML_COMMA_PUNCT:
        break_ms = _SSML_BREAK_COMMA_MS
    else:
        break_ms = 0
    body = _xml_escape_text(text)
    body = _slow_wrap_numbers_and_brands(body)
    if break_ms > 0:
        return f'{body}<break time="{break_ms}ms"/>'
    return body


# Re-export sentence/comma punctuation sets for tests that pin the
# breakpoint policy. (They live above in compiled module state.)


def _text_to_doubao_ssml(text: str) -> str:
    """Convert a Chinese narration script into Doubao-flavoured SSML.

    Strategy:
      1. Paragraphs (split by blank line) become explicit ``<break>`` boundaries.
      2. Inside each paragraph we split on ``[。！？，、；!?]`` punctuation,
         so each segment carries the punctuation it ended with.
      3. Sentence-final punctuation gets a 450ms break (audible pause).
      4. Comma-grade punctuation gets a 220ms break (subtle phrasing pause).
      5. Number+unit tokens are wrapped in slow prosody for weight.

    The returned string is always wrapped in ``<speak>...</speak>``. If
    ``text`` is empty we return an empty string so callers know to fall back.
    """
    if not text or not text.strip():
        return ""

    paragraphs = [para for para in re.split(r"\n\s*\n", text) if para.strip()]
    rendered_paragraphs: list[str] = []
    for para in paragraphs:
        # Split keeping the punctuation by using a positive lookbehind:
        # we tokenise into [non-punct...punct] segments instead of
        # dropping the punct.
        tokens = re.findall(r"[^。！？，、；!?]+[。！？，、；!?]?", para)
        rendered_segments = [
            _segment_to_ssml(token) for token in tokens if token.strip()
        ]
        rendered_paragraphs.append("".join(rendered_segments))

    joiner = f'<break time="{_SSML_BREAK_PARA_MS}ms"/>'
    inner = joiner.join(p for p in rendered_paragraphs if p)
    return f"<speak>{inner}</speak>"


def _safe_error_message(exc: Exception) -> str:
    message = str(exc)
    message = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", message)
    message = re.sub(r"(?i)(api[-_ ]?key[=:]\s*)[A-Za-z0-9_-]+", r"\1***", message)
    message = re.sub(r"(?i)(token[=:]\s*)[A-Za-z0-9_-]+", r"\1***", message)
    message = re.sub(r"Bearer;[A-Za-z0-9_-]+", "Bearer;***", message)
    return message[-500:]
