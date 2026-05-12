"""Word-level subtitle alignment via faster-whisper.

Why this exists
---------------
Our subtitle pipeline historically estimated segment timing by evenly
splitting the total audio duration across sentences. That puts subtitles
visually "close enough" to the voiceover but the word boundaries are off
by up to 400-800ms — too loose for hook-cut timing or karaoke-style
highlights. WhisperX / faster-whisper's ``word_timestamps=True`` gives us
per-character start/end in the 20-40ms range, accurate enough to drive
word-level animations and to claim subtitle quality ``100/100`` in
``build_video_quality_report``.

Fallback behaviour
------------------
This module is a soft dependency. If any of the following fails we return
``None`` and let the caller stick with estimated timing (subtitle_quality
stays at its 80 baseline):

1. faster-whisper not installed
2. GPU unavailable (no CUDA, no cublas/cudnn)
3. Audio file missing / unreadable
4. Model download fails

The point is: WhisperX is an *upgrade* path, not a blocker. A failed
alignment must never break the render pipeline.
"""

from __future__ import annotations

import ctypes
import importlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CUDA runtime discovery.
#
# ``faster-whisper`` delegates to ``ctranslate2``'s C++ layer, which
# ``dlopen``s ``libcublas.so.12`` / ``libcudnn*.so.9`` at model-load time.
# If the venv was built with ``pip install nvidia-cublas-cu12
# nvidia-cudnn-cu12`` those ``.so`` files sit under ``nvidia/*/lib/`` but
# are *not* on ``LD_LIBRARY_PATH``. Pre-loading them into the process with
# ``ctypes.CDLL(..., RTLD_GLOBAL)`` makes them discoverable to the later
# ``dlopen``, no shell environment surgery required.
# ---------------------------------------------------------------------------

_CUDA_LIB_CANDIDATES = (
    ("nvidia.cublas.lib", "libcublas.so.12"),
    ("nvidia.cublas.lib", "libcublasLt.so.12"),
    ("nvidia.cudnn.lib", "libcudnn.so.9"),
    ("nvidia.cudnn.lib", "libcudnn_ops.so.9"),
    ("nvidia.cudnn.lib", "libcudnn_cnn.so.9"),
    ("nvidia.cuda_nvrtc.lib", "libnvrtc.so.12"),
)


def _preload_cuda_runtime() -> dict[str, Any]:
    """Best-effort CUDA .so preload. Returns a status dict for diagnostics."""
    loaded: list[str] = []
    failed: list[str] = []
    for module_name, so_name in _CUDA_LIB_CANDIDATES:
        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            failed.append(f"{module_name} not installed")
            continue
        lib_dirs = getattr(mod, "__path__", None) or []
        hit = False
        for lib_dir in lib_dirs:
            candidate = Path(lib_dir) / so_name
            if candidate.exists():
                try:
                    ctypes.CDLL(str(candidate), mode=ctypes.RTLD_GLOBAL)
                    loaded.append(so_name)
                    hit = True
                    break
                except OSError as exc:
                    failed.append(f"{so_name}: {exc}")
        if not hit and so_name not in loaded:
            failed.append(f"{so_name} not found under {module_name}")
    return {"loaded": loaded, "failed": failed}


# ---------------------------------------------------------------------------


@dataclass
class WordTiming:
    word: str
    start: float
    end: float
    probability: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "word": self.word,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "probability": round(self.probability, 4),
        }


@dataclass
class AlignmentSegment:
    start: float
    end: float
    text: str
    words: list[WordTiming]

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
            "words": [w.as_dict() for w in self.words],
        }


@dataclass
class AlignmentResult:
    segments: list[AlignmentSegment]
    audio_duration_seconds: float
    model_name: str
    device: str
    compute_type: str
    language: str
    language_probability: float
    elapsed_seconds: float

    def word_count(self) -> int:
        return sum(len(s.words) for s in self.segments)

    def average_confidence(self) -> float:
        total = self.word_count()
        if total == 0:
            return 0.0
        return sum(w.probability for s in self.segments for w in s.words) / total

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "model": self.model_name,
            "device": self.device,
            "compute_type": self.compute_type,
            "language": self.language,
            "language_probability": round(self.language_probability, 4),
            "audio_duration_seconds": round(self.audio_duration_seconds, 3),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "realtime_factor": (
                round(self.audio_duration_seconds / self.elapsed_seconds, 2)
                if self.elapsed_seconds > 0
                else 0.0
            ),
            "word_count": self.word_count(),
            "average_confidence": round(self.average_confidence(), 4),
            "segments": [s.as_dict() for s in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AlignmentResult":
        """Rehydrate an AlignmentResult from its ``as_dict()`` payload.

        Used by ``pipeline_cache`` to restore a previous run from
        ``subtitle_word_alignment.json`` without re-running faster-whisper.
        """
        segments: list[AlignmentSegment] = []
        for seg in data.get("segments") or []:
            words = [
                WordTiming(
                    word=str(w.get("word", "")),
                    start=float(w.get("start") or 0.0),
                    end=float(w.get("end") or 0.0),
                    probability=float(w.get("probability") or 0.0),
                )
                for w in (seg.get("words") or [])
            ]
            segments.append(
                AlignmentSegment(
                    start=float(seg.get("start") or 0.0),
                    end=float(seg.get("end") or 0.0),
                    text=str(seg.get("text", "")),
                    words=words,
                )
            )
        return cls(
            segments=segments,
            audio_duration_seconds=float(data.get("audio_duration_seconds") or 0.0),
            model_name=str(data.get("model", "")),
            device=str(data.get("device", "")),
            compute_type=str(data.get("compute_type", "")),
            language=str(data.get("language", "")),
            language_probability=float(data.get("language_probability") or 0.0),
            elapsed_seconds=float(data.get("elapsed_seconds") or 0.0),
        )


# ---------------------------------------------------------------------------


def align_voice_words(
    audio_path: Path,
    *,
    language: str = "zh",
    model_name: str = "large-v3",
    prefer_gpu: bool = True,
    beam_size: int = 5,
    vad_filter: bool = True,
) -> AlignmentResult | None:
    """Run word-level Whisper alignment on ``audio_path``.

    Returns ``None`` on any failure so the caller can fall back to the
    estimated-timing path without crashing the render.
    """
    if not audio_path.exists():
        logger.warning("whisperx_aligner: audio path missing: %s", audio_path)
        return None

    # Try to lazy-import faster-whisper first; it also surfaces if the venv
    # doesn't have it installed at all.
    try:
        from faster_whisper import WhisperModel  # noqa: WPS433 — lazy by design
    except ImportError as exc:
        logger.info("whisperx_aligner: faster-whisper not installed (%s)", exc)
        return None

    cuda_status = _preload_cuda_runtime() if prefer_gpu else {"loaded": [], "failed": ["prefer_gpu=False"]}
    device = "cuda" if prefer_gpu and cuda_status["loaded"] else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    try:
        t_start = time.time()
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        t_loaded = time.time()
        logger.info(
            "whisperx_aligner: model %s loaded on %s/%s in %.1fs (cuda_preload=%s)",
            model_name, device, compute_type, t_loaded - t_start, cuda_status,
        )

        segments_iter, info = model.transcribe(
            str(audio_path),
            language=language,
            word_timestamps=True,
            beam_size=beam_size,
            vad_filter=vad_filter,
        )
        segments: list[AlignmentSegment] = []
        for seg in segments_iter:
            words = [
                WordTiming(
                    word=str(w.word),
                    start=float(w.start or 0.0),
                    end=float(w.end or 0.0),
                    probability=float(w.probability or 0.0),
                )
                for w in (seg.words or [])
            ]
            segments.append(
                AlignmentSegment(
                    start=float(seg.start or 0.0),
                    end=float(seg.end or 0.0),
                    text=str(seg.text or "").strip(),
                    words=words,
                )
            )
        elapsed = time.time() - t_loaded
    except Exception as exc:  # noqa: BLE001 — soft dependency, never fatal
        logger.warning("whisperx_aligner: transcription failed: %r", exc)
        # If GPU blew up, try once more on CPU with int8 before giving up.
        if device == "cuda":
            logger.info("whisperx_aligner: retrying on CPU/int8")
            return align_voice_words(
                audio_path,
                language=language,
                model_name=model_name,
                prefer_gpu=False,
                beam_size=beam_size,
                vad_filter=vad_filter,
            )
        return None

    return AlignmentResult(
        segments=segments,
        audio_duration_seconds=float(info.duration),
        model_name=model_name,
        device=device,
        compute_type=compute_type,
        language=str(info.language),
        language_probability=float(info.language_probability),
        elapsed_seconds=elapsed,
    )
