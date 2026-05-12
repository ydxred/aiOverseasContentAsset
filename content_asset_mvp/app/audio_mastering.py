from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

# Short-video target: integrated loudness ≈ -14 LUFS (matches what 抖音 / 视频号 /
# B 站 mobile playback actually expect). True peak ≤ -1.5 dBTP avoids any
# phone-speaker clipping after the platform's own re-encode, and LRA 9 LU keeps
# enough dynamic range for narration to feel "spoken" rather than mastered-to-flat.
#
# Why dual-pass: ``loudnorm`` in single-pass mode uses linear normalisation that
# over-shoots target by 1-3 dB and *under*-uses the LRA budget, leaving us at
# LRA ~3.8 / TP ~-4.7 (we measured this on three production renders). Dual-pass
# first runs an analysis pass (``-f null -``) to get measured_I / measured_TP /
# measured_thresh / measured_offset, then feeds them back as ``measured_*`` to
# the second pass — the filter then does precise gain matching and lands on
# the target within ±0.5 dB. This is the technique broadcast loudness tools use.
TARGET_LOUDNESS_LUFS = -14.0
TARGET_TRUE_PEAK_DBTP = -1.5
TARGET_LRA_LU = 9.0

# Mastering regime selection — in order of LRA preservation, best to worst:
#
#   1. PASSTHROUGH       (no filter)        ──> 0 dB LRA loss
#   2. PEAK_TAME         (alimiter)         ──> ~0.1 dB LRA loss
#   3. CLEAN_GAIN        (volume Xdb)       ──> 0 dB LRA loss   (NEW)
#   4. LOUDNORM_LINEAR   (loudnorm linear=true)  ──> 0.5-1 dB LRA loss
#   5. LOUDNORM_DYNAMIC  (loudnorm)         ──> 1-2 dB LRA loss (last resort)
#
# Trigger conditions (input_i = integrated LUFS, input_tp = true peak):
#
#   PASSTHROUGH:  input_i >= -19.5  AND  input_tp <= -0.4
#                 ──> already loud enough, peak-safe → leave it alone
#
#   PEAK_TAME:    input_i >= -19.5  AND  input_tp >  -0.4
#                 ──> loud enough but peaks dangerous → cap with alimiter
#
#   CLEAN_GAIN:   input_i <  -19.5  AND  (target_tp - input_tp) >= 1 dB
#                 ──> too quiet but enough TP headroom for pure linear gain
#                 → apply ``volume=Xdb`` where X = min(gain_needed,
#                   max_clean_gain_to_tp_target). This is what we needed for
#                   Doubao BigTTS 2.0 (input ~-22 LUFS / TP ~-6.7 dBTP):
#                   the loudnorm path was forcing compressive mode and
#                   eating LRA, but a flat +5 dB volume bump matches the
#                   target with zero LRA cost.
#
#   LOUDNORM_LINEAR:  input_i < -19.5  AND  small gain needed AND TP fits
#                     after linear amplification (within 6 dB headroom).
#                     loudnorm in linear mode keeps LRA mostly intact.
#
#   LOUDNORM_DYNAMIC: everything else (very quiet + low headroom).
#                     ffmpeg picks dynamic compression but we drop the
#                     LRA= constraint so it minimally compresses.
#
# We measured each regime against three production scripts; PASSTHROUGH /
# PEAK_TAME / CLEAN_GAIN preserve LRA 1:1. LOUDNORM_LINEAR loses 0.5-1 LU.
# LOUDNORM_DYNAMIC loses 1-2 LU. The CLEAN_GAIN regime was added when we
# discovered Doubao 2.0 TTS lands at -22 LUFS with -6+ dB of TP headroom —
# pure conditions for linear gain that the older threshold (-30 LUFS)
# missed.
# Passthrough threshold: source must already be near the -14 LUFS short-
# video target before we leave it alone. -19.5 was too generous — TTS
# outputs around -19 LUFS still need a 5+ dB push. Tightened to -16.0
# so mid-loudness sources fall through to clean_gain / loudnorm_linear
# regimes that DO add gain. Below this threshold we always attempt to
# lift LUFS toward target.
PASSTHROUGH_LOUDNESS_LUFS_MIN = -16.0
PASSTHROUGH_TRUE_PEAK_DBTP = -0.4

# Minimum TP headroom (dB below TP target) required to attempt clean gain.
# We need at least 1 dB so the boost is meaningful. Below this, fall
# through to loudnorm regimes.
CLEAN_GAIN_MIN_HEADROOM_DB = 1.0

# Maximum clean linear gain we'll apply. Beyond this, even if TP allows,
# we prefer loudnorm because (a) the gain is large enough that small
# transient peaks the measurement missed could clip after re-encode,
# (b) loudnorm's lookahead handles transients better than a flat volume.
#
# 10 dB ceiling chosen because Doubao narration on quiet scripts lands
# at -22 to -23 LUFS (gain_needed 8-9 dB). The previous 8 dB ceiling kept
# kicking those just-barely-too-quiet renders into the TP-capped path
# (volume=5dB landing at -17.5 LUFS instead of -14). Headroom for the
# alimiter is fine — it catches transients above -1.5 dBTP regardless of
# how high the steady-state volume push lands.
# GPT-SoVITS V2Pro 输出 ~-26 LUFS（比 MiniMax/Doubao 安静 5-12 dB），
# 14 dB max 允许 mastering 直接拉到 -14 LUFS。alimiter 0.8414 兜住 TP，
# 14 dB 线性 boost 不会产生听感失真（量化噪声 < 1 dB）。
CLEAN_GAIN_MAX_BOOST_DB = 14.0

# When loudnorm's linear path can't fit (gain > headroom), drop LRA= and
# let it run dynamic-but-no-LRA-target — same logic as before.
LINEAR_HEADROOM_THRESHOLD_DB = 6.0


def _denoise_prefix() -> str:
    """Build a denoise filter prefix that runs BEFORE gain/level work.

    Why: cloned voices (MiniMax / Doubao ICL / Fish ICL) inherit the noise
    floor of their reference recording. Even after MiniMax's built-in
    noise_reduction + an offline ffmpeg afftdn on the reference, residual
    "dust" hiss bakes into the cloned timbre and shows up as low-level
    grit in every synthesised line. Adding a SECOND afftdn pass at TTS
    output stage scrubs that without affecting voice character.

    Settings calibrated for cloned voices:
    - highpass=70: kill < 70Hz rumble (HVAC, table thump, mic plosives)
    - afftdn nr=10 (moderate strength, preserves consonants)
    - afftdn nf=-38 (treat anything below -38 dB as noise floor)
    Anything more aggressive starts robotising the voice.

    Disable via CONTENT_ASSET_TTS_DENOISE=0 when shipping non-cloned
    Doubao/CosyVoice voices that don't need extra denoise.
    """
    if os.getenv("CONTENT_ASSET_TTS_DENOISE", "1").strip() == "0":
        return ""
    return "highpass=f=70,afftdn=nr=10:nf=-38,"


def master_voice_audio(
    voice_path: Path,
    output_path: Path,
    *,
    ffmpeg: str,
) -> tuple[Path, dict[str, Any]]:
    """Normalise narration audio with two-pass loudnorm; fall back on failure."""
    status: dict[str, Any] = {
        "schema_version": 2,
        "architecture_version": "video_pipeline_v6_slice",
        "input_path": str(voice_path),
        "output_path": str(output_path),
        "fallback_path": str(voice_path),
        "target_loudness_lufs": TARGET_LOUDNESS_LUFS,
        "target_true_peak_dbtp": TARGET_TRUE_PEAK_DBTP,
        "target_lra_lu": TARGET_LRA_LU,
    }
    if not voice_path.exists():
        status.update(
            {
                "status": "fallback",
                "mode": "missing_input",
                "success": False,
                "audio_path": str(voice_path),
                "reason": f"Input audio not found: {voice_path}",
            }
        )
        return voice_path, status

    output_path.parent.mkdir(parents=True, exist_ok=True)

    measurement = _measure_loudness(ffmpeg, voice_path)
    if measurement is None:
        status.update(
            {
                "mode": "ffmpeg_loudnorm_single_pass",
                "loudnorm_pass": "single",
                "filter": (
                    f"loudnorm=I={TARGET_LOUDNESS_LUFS}:LRA={TARGET_LRA_LU}:"
                    f"TP={TARGET_TRUE_PEAK_DBTP},atrim=start=0"
                ),
            }
        )
        return _run_single_pass(ffmpeg, voice_path, output_path, status)

    status["loudnorm_measurement"] = measurement
    # Mastering decision matrix (the goal is to preserve TTS-native LRA,
    # which is ~4 LU on CosyVoice / ~5 LU on Doubao BigTTS):
    #
    #   regime         | LUFS       | TP            | filter chain
    #   ---------------|------------|---------------|--------------------------
    #   PASSTHROUGH    | >= -19.5   | <= -0.4       | atrim only
    #   PEAK_TAME      | >= -19.5   | >  -0.4       | alimiter only, no gain
    #   GAIN_LINEAR    | -25 .. -19 | <= -2.0       | dual-pass loudnorm linear
    #   GAIN_DYNAMIC   | other      | other         | dual-pass dynamic, no LRA target
    #
    # The big win is PASSTHROUGH and PEAK_TAME — neither adds gain, so
    # the ffmpeg loudnorm dynamic processor never engages and LRA stays
    # at the source value. PEAK_TAME uses a single ``alimiter`` to catch
    # isolated TT-speaker clips without compressing steady-state; in our
    # measurements it costs at most 0.2 LU LRA vs 1.5+ LU for full
    # loudnorm. Mainstream Chinese short-video platforms (抖音 / B站 /
    # 视频号) renormalize on playback, so accepting -16 LUFS source
    # instead of -14 is invisible to viewers.
    try:
        input_i = float(measurement["input_i"])
        input_tp = float(measurement["input_tp"])
    except (TypeError, ValueError, KeyError):
        input_i = -23.0
        input_tp = -1.0
    gain_needed_db = TARGET_LOUDNESS_LUFS - input_i

    if input_i >= PASSTHROUGH_LOUDNESS_LUFS_MIN and input_tp <= PASSTHROUGH_TRUE_PEAK_DBTP:
        # Loud enough + peak-safe → just resample.
        passthrough_filter = "atrim=start=0"
        status["filter"] = passthrough_filter
        status["mode"] = "ffmpeg_passthrough"
        status["loudnorm_pass"] = "skipped"
        status["gain_needed_db"] = round(gain_needed_db, 2)
        status["lra_preserve_mode"] = True
        return _run_with_filter(ffmpeg, voice_path, output_path, passthrough_filter, status)

    if input_i >= PASSTHROUGH_LOUDNESS_LUFS_MIN and input_tp > PASSTHROUGH_TRUE_PEAK_DBTP:
        # Loud enough but TP too close to 0 dBFS → cap peaks only.
        # ``alimiter limit=0.94`` ≈ -0.54 dBTP. Attack 5ms / release 50ms
        # is fast enough to catch sibilants without sticking the
        # compressor into the body of a syllable, so steady-state level
        # (and therefore LRA) is preserved.
        peak_filter = "alimiter=limit=0.94:level=disabled,atrim=start=0"
        status["filter"] = peak_filter
        status["mode"] = "ffmpeg_peak_tame"
        status["loudnorm_pass"] = "skipped"
        status["gain_needed_db"] = round(gain_needed_db, 2)
        status["lra_preserve_mode"] = True
        return _run_with_filter(ffmpeg, voice_path, output_path, peak_filter, status)

    # CLEAN_GAIN regime — quiet input with enough TP headroom for pure
    # linear amplification. We apply a flat ``volume=Xdb`` boost where X is
    # the smaller of (a) the gain needed to reach target LUFS, (b) the TP
    # ceiling minus a safety margin, (c) CLEAN_GAIN_MAX_BOOST_DB. This is
    # the LRA-preserving path for Doubao BigTTS 2.0 (which lands at -22
    # LUFS with 6+ dB of TP headroom). Source LRA passes through 1:1
    # because gain is a linear scalar.
    #
    # CLEAN_GAIN_LIMITED sub-regime — when the projected TP headroom would
    # cap the gain below what we need, we don't have to give up the
    # remaining headroom. Real audio peaks don't track linear gain 1:1
    # (crest factor varies), so the projected post-gain TP is conservative.
    # Measured on Doubao narration: +5.21 dB linear gain landed at -4.95
    # dBTP (3.45 dB unused vs the model's prediction). We apply the full
    # ``gain_needed_db`` (capped at CLEAN_GAIN_MAX_BOOST_DB) and chain an
    # ``alimiter limit=0.8414`` (≈ -1.5 dBTP) safety net to catch any
    # transient that does cross. PEAK_TAME measurements show alimiter
    # alone costs ≤0.2 LU LRA when limiting only transients, so the LRA
    # cost is small enough to be worth the +2-3 dB on integrated loudness.
    tp_headroom_db = TARGET_TRUE_PEAK_DBTP - input_tp  # negative if input TP is above target
    if (
        gain_needed_db > 0
        and tp_headroom_db >= CLEAN_GAIN_MIN_HEADROOM_DB
    ):
        clean_gain_db = min(gain_needed_db, tp_headroom_db, CLEAN_GAIN_MAX_BOOST_DB)
        gain_capped_by_tp = (
            tp_headroom_db < gain_needed_db
            and gain_needed_db <= CLEAN_GAIN_MAX_BOOST_DB
        )
        if clean_gain_db >= CLEAN_GAIN_MIN_HEADROOM_DB:
            if gain_capped_by_tp:
                # CLEAN_GAIN_LIMITED — push the full gain_needed_db, let
                # alimiter catch any transient that crosses -1.5 dBTP.
                # 0.8414 ≈ 10^(-1.5/20). ``level=disabled`` prevents the
                # auto-leveling stage from compressing steady-state.
                full_gain_db = min(gain_needed_db, CLEAN_GAIN_MAX_BOOST_DB)
                full_gain_db_rounded = round(full_gain_db, 2)
                clean_filter = (
                    f"volume={full_gain_db_rounded}dB,"
                    "alimiter=limit=0.8414:level=disabled,"
                    "atrim=start=0"
                )
                status["filter"] = clean_filter
                status["mode"] = "ffmpeg_clean_gain_limited"
                status["loudnorm_pass"] = "skipped"
                status["gain_needed_db"] = round(gain_needed_db, 2)
                status["clean_gain_applied_db"] = full_gain_db_rounded
                status["tp_headroom_db"] = round(tp_headroom_db, 2)
                status["lra_preserve_mode"] = True
                return _run_with_filter(ffmpeg, voice_path, output_path, clean_filter, status)
            clean_gain_db_rounded = round(clean_gain_db, 2)
            clean_filter = f"volume={clean_gain_db_rounded}dB,atrim=start=0"
            status["filter"] = clean_filter
            status["mode"] = "ffmpeg_clean_gain"
            status["loudnorm_pass"] = "skipped"
            status["gain_needed_db"] = round(gain_needed_db, 2)
            status["clean_gain_applied_db"] = clean_gain_db_rounded
            status["tp_headroom_db"] = round(tp_headroom_db, 2)
            status["lra_preserve_mode"] = True
            return _run_with_filter(ffmpeg, voice_path, output_path, clean_filter, status)

    preserve_lra = abs(gain_needed_db) <= LINEAR_HEADROOM_THRESHOLD_DB
    if preserve_lra:
        second_pass_filter = (
            f"loudnorm=I={TARGET_LOUDNESS_LUFS}:LRA={TARGET_LRA_LU}:TP={TARGET_TRUE_PEAK_DBTP}:"
            f"measured_I={measurement['input_i']}:measured_LRA={measurement['input_lra']}:"
            f"measured_TP={measurement['input_tp']}:measured_thresh={measurement['input_thresh']}:"
            f"offset={measurement['target_offset']}:linear=true:print_format=summary,"
            "atrim=start=0"
        )
        status["mode"] = "ffmpeg_loudnorm_dual_pass_linear"
    else:
        # No LRA target. ffmpeg's dynamic loudnorm will still bring
        # integrated loudness to target and respect the TP cap, but
        # without an LRA goal it stops applying compression once level
        # is matched. This preserves the source LRA much better than
        # passing LRA=9 with insufficient headroom.
        second_pass_filter = (
            f"loudnorm=I={TARGET_LOUDNESS_LUFS}:TP={TARGET_TRUE_PEAK_DBTP}:"
            f"measured_I={measurement['input_i']}:measured_LRA={measurement['input_lra']}:"
            f"measured_TP={measurement['input_tp']}:measured_thresh={measurement['input_thresh']}:"
            f"offset={measurement['target_offset']}:print_format=summary,"
            "atrim=start=0"
        )
        status["mode"] = "ffmpeg_loudnorm_dual_pass_lra_preserve"
    status["filter"] = second_pass_filter
    status["loudnorm_pass"] = "dual"
    status["gain_needed_db"] = round(gain_needed_db, 2)
    status["lra_preserve_mode"] = not preserve_lra
    return _run_with_filter(ffmpeg, voice_path, output_path, second_pass_filter, status)


def _run_with_filter(
    ffmpeg: str,
    voice_path: Path,
    output_path: Path,
    af_filter: str,
    status: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """Run ffmpeg with the given audio filter and populate status fields.

    Shared by all three mastering regimes (passthrough / linear /
    lra_preserve). On any error we leave the original ``voice_path`` as
    the audio path so the pipeline never silently produces a missing
    voice track.
    """
    # Prepend the denoise prefix BEFORE any gain/level work so the
    # residual hiss / "dust" from cloned voice references gets scrubbed
    # before loudnorm measures input integrated loudness. Loudness
    # measurement on a denoised signal lands on more useful numbers
    # (input_i is the speech, not the noise floor).
    denoise = _denoise_prefix()
    effective_filter = f"{denoise}{af_filter}" if denoise else af_filter
    status["denoise_prefix"] = denoise or None
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(voice_path),
        "-af",
        effective_filter,
        "-ar",
        "48000",
        "-ac",
        "2",
        str(output_path),
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise RuntimeError("ffmpeg completed but mastered audio is empty")
        final_metrics = _measure_loudness(ffmpeg, output_path) or {}
        status.update(
            {
                "status": "succeeded",
                "success": True,
                "audio_path": str(output_path),
                "stderr_tail": completed.stderr[-1200:],
                "final_loudness": final_metrics,
                "silence_metrics": _measure_silence(ffmpeg, output_path),
            }
        )
        return output_path, status
    except Exception as exc:  # pragma: no cover - depends on local ffmpeg codecs.
        status.update(
            {
                "status": "fallback",
                "mode": "ffmpeg_failed",
                "success": False,
                "audio_path": str(voice_path),
                "reason": str(exc),
            }
        )
        return voice_path, status


def _measure_silence(ffmpeg: str, audio_path: Path, *, noise_db: float = -35.0, min_silence: float = 0.4) -> dict[str, Any]:
    """Count silence pauses ≥ min_silence at noise_db threshold.

    Real human narration on Douyin/B-station averages 8-15% silent time
    (breathing pauses around 0.4-1.5s, ~ every 4-6s). TTS without SSML
    breath marks falls below 2%. We surface the ratio so the rubric can
    score "听感节奏" — the dimension that humans perceive as "像不像真人讲".
    """
    cmd = [
        ffmpeg, "-hide_banner", "-nostats", "-i", str(audio_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    except (subprocess.SubprocessError, OSError):
        return {}
    stderr = result.stderr or ""
    durations = [
        float(match.group(1))
        for match in re.finditer(r"silence_duration:\s*([\d.]+)", stderr)
    ]
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr)
    audio_duration = 0.0
    if duration_match:
        h, m, s = duration_match.groups()
        audio_duration = int(h) * 3600 + int(m) * 60 + float(s)
    total_silent = sum(durations)
    return {
        "silence_segments": len(durations),
        "total_silent_seconds": round(total_silent, 3),
        "audio_duration_seconds": round(audio_duration, 3),
        "silence_ratio": round(total_silent / audio_duration, 4) if audio_duration else 0.0,
        "noise_threshold_db": noise_db,
        "min_silence_seconds": min_silence,
    }


def _measure_loudness(ffmpeg: str, voice_path: Path) -> dict[str, Any] | None:
    """First pass: run loudnorm in measure-only mode and parse the JSON tail.

    ``ffmpeg -af loudnorm=...:print_format=json -f null -`` writes the JSON
    blob to stderr after the audio analysis completes. We only return values
    when *all* expected keys are present and finite — anything else falls
    back to single-pass mode upstream.
    """
    measure_filter = (
        f"loudnorm=I={TARGET_LOUDNESS_LUFS}:LRA={TARGET_LRA_LU}:"
        f"TP={TARGET_TRUE_PEAK_DBTP}:print_format=json"
    )
    cmd = [ffmpeg, "-hide_banner", "-nostats", "-i", str(voice_path), "-af", measure_filter, "-f", "null", "-"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
    except (subprocess.SubprocessError, OSError):
        return None
    stderr = result.stderr or ""
    match = re.search(r"\{[\s\S]*?\}", stderr.split("[Parsed_loudnorm")[-1])
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    required = ("input_i", "input_lra", "input_tp", "input_thresh", "target_offset")
    if not all(key in data for key in required):
        return None
    out: dict[str, Any] = {}
    for key in required:
        try:
            float(data[key])
        except (TypeError, ValueError):
            return None
        out[key] = str(data[key])
    return out


def _run_single_pass(
    ffmpeg: str,
    voice_path: Path,
    output_path: Path,
    status: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """Fall back to one-shot loudnorm when the measurement pass failed.

    This branch keeps the legacy ``loudnorm=I=...:LRA=...:TP=...`` behaviour
    and is intentionally the only place where the pipeline still ships an
    imprecise normalisation — anything else should go through the dual-pass
    path so we actually hit the target.
    """
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(voice_path),
        "-af",
        str(status["filter"]),
        "-ar",
        "48000",
        "-ac",
        "2",
        str(output_path),
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise RuntimeError("ffmpeg completed but mastered audio is empty")
        status.update(
            {
                "status": "succeeded",
                "success": True,
                "audio_path": str(output_path),
                "stderr_tail": completed.stderr[-1200:],
            }
        )
        return output_path, status
    except Exception as exc:  # pragma: no cover
        status.update(
            {
                "status": "fallback",
                "mode": "ffmpeg_failed",
                "success": False,
                "audio_path": str(voice_path),
                "reason": str(exc),
            }
        )
        return voice_path, status
