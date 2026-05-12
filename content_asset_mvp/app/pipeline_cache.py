"""Per-stage incremental cache for the media pipeline.

Wraps expensive deterministic stages (TTS, audio mastering, word-level
alignment, subtitle translation) so that re-running ``--render-video`` on
an unchanged ``chinese_script.md`` skips the network/GPU work and reuses
the previous artifacts.

Design notes
------------

*   Cache lives at ``<output_dir>/<content_id>/.cache/<stage>.json``. Each
    stage gets exactly one manifest file with the latest ``key -> outputs``
    entry (we don't keep history — a stale upstream invalidates the entry
    and we just re-run).
*   ``key`` is a SHA256 of (stage name, sorted JSON of inputs). Inputs
    can be plain values *or* file path strings; for files we hash the
    file content rather than the path so renaming the artifact dir
    doesn't blow the cache.
*   ``lookup`` validates the listed outputs still exist on disk; if any
    are missing the entry is treated as a miss (someone manually deleted
    the artifact, so honor that).
*   Cache writes are best-effort. If we fail to read/write the manifest
    we silently fall back to "miss" — caching is a perf optimization,
    never a correctness gate.

Usage::

    cache = StageCache(writer.output_dir)
    key = cache.key("tts", inputs={"text": script_text, "model": "doubao-zh"})
    hit = cache.lookup("tts", key, expected_outputs=["voice.wav"])
    if hit:
        return hit["status"]
    # ... do real work ...
    cache.store("tts", key, outputs=["voice.wav"], status=tts_status)

The caller is responsible for owning the ``output_dir`` — files listed in
``outputs`` are interpreted relative to it, and ``stage_subdir`` is used
to resolve them through the same archive layout the rest of the pipeline
uses (so ``voice.wav`` correctly resolves to ``04_audio/voice.wav``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact_writer import stage_subdir

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheHit:
    stage: str
    key: str
    outputs: list[str]
    status: dict[str, Any]
    stored_at: str


class StageCache:
    """File-backed per-stage cache for the media pipeline."""

    def __init__(self, output_dir: Path, *, enabled: bool = True) -> None:
        self.output_dir = output_dir
        self.enabled = enabled
        self.cache_dir = output_dir / ".cache"

    def _stage_path(self, stage: str) -> Path:
        # Stage names map 1:1 to a manifest file. Disallow path separators
        # so a malformed stage tag can't escape the .cache dir.
        if "/" in stage or ".." in stage:
            raise ValueError(f"invalid stage name: {stage!r}")
        return self.cache_dir / f"{stage}.json"

    def key(self, stage: str, *, inputs: dict[str, Any]) -> str:
        """Compute the cache key for a stage given its inputs.

        Any value in ``inputs`` whose key ends with ``_path`` is interpreted
        as a path to a file and hashed by content. The plain ``path`` key
        is *not* auto-hashed — caller controls whether path semantics or
        content semantics matter.
        """
        normalized: dict[str, Any] = {}
        for name, value in inputs.items():
            if name.endswith("_path") and value:
                file_path = Path(str(value))
                normalized[name] = {
                    "name": file_path.name,
                    "sha256": _hash_file(file_path),
                }
            else:
                normalized[name] = value
        payload = json.dumps(
            {"stage": stage, "inputs": normalized},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def lookup(
        self,
        stage: str,
        key: str,
        *,
        expected_outputs: list[str],
    ) -> CacheHit | None:
        """Return a cache hit when key matches and all outputs exist on disk."""
        if not self.enabled:
            return None
        try:
            entry = self._read_entry(stage)
        except Exception as exc:  # noqa: BLE001
            logger.debug("cache read failed for stage=%s: %s", stage, exc)
            return None
        if not entry or entry.get("key") != key:
            return None
        outputs = list(entry.get("outputs") or [])
        for relative in outputs:
            if not _resolved_artifact(self.output_dir, relative).exists():
                logger.debug(
                    "cache miss: expected output %s not present for stage=%s",
                    relative,
                    stage,
                )
                return None
        # Some stages care about a strict superset; let the caller assert
        # they got the outputs they expected by passing ``expected_outputs``.
        for relative in expected_outputs:
            if relative not in outputs:
                return None
        return CacheHit(
            stage=stage,
            key=key,
            outputs=outputs,
            status=dict(entry.get("status") or {}),
            stored_at=str(entry.get("stored_at") or ""),
        )

    def store(
        self,
        stage: str,
        key: str,
        *,
        outputs: list[str],
        status: dict[str, Any],
    ) -> None:
        """Persist a successful run so the next call can short-circuit."""
        if not self.enabled:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            entry = {
                "stage": stage,
                "key": key,
                "outputs": outputs,
                "status": status,
                "stored_at": _utc_now(),
            }
            path = self._stage_path(stage)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(entry, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)
        except Exception as exc:  # noqa: BLE001
            logger.debug("cache write failed for stage=%s: %s", stage, exc)

    def invalidate(self, stage: str | None = None) -> None:
        """Drop one stage's cache (or all of them when ``stage`` is None)."""
        if not self.cache_dir.exists():
            return
        if stage is None:
            for child in self.cache_dir.glob("*.json"):
                child.unlink(missing_ok=True)
            return
        self._stage_path(stage).unlink(missing_ok=True)

    def _read_entry(self, stage: str) -> dict[str, Any] | None:
        path = self._stage_path(stage)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


def _hash_file(path: Path) -> str:
    """Return SHA256 of file content; empty string when the file is missing."""
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    # 1 MiB chunks — fine for voice.wav (~MB scale) and we don't expect
    # to hash multi-GB inputs.
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolved_artifact(output_dir: Path, relative: str) -> Path:
    """Resolve a cached output path through the Tier B stage layout."""
    return stage_subdir(output_dir, relative)


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
