"""One-shot migration: flat candidate dir -> 10 lifecycle subdirs.

Rewrites every ``output/<content_id>/`` directory in-place by moving each
recognised file/folder under the matching stage subdir (00_source ...
09_publish) and dropping a ``MANIFEST.json`` summarising what landed where.

Usage:

    python -m scripts.archive_legacy_output                # whole output tree
    python -m scripts.archive_legacy_output yt_9d1a160bbcab # one candidate
    python -m scripts.archive_legacy_output --dry-run      # preview only

The migration is idempotent - re-running on an already-migrated dir is a
cheap no-op that just refreshes ``MANIFEST.json``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.artifact_writer import STAGE_DIRS, STAGE_MAP, stage_for  # noqa: E402

DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output"


def _candidate_dirs(output_root: Path, only: str | None) -> list[Path]:
    if only:
        candidate = output_root / only
        return [candidate] if candidate.is_dir() else []
    return sorted(p for p in output_root.iterdir() if p.is_dir())


def _migrate_candidate(candidate_dir: Path, *, dry_run: bool) -> dict[str, object]:
    moves: list[tuple[str, str]] = []
    skipped: list[str] = []
    for entry in sorted(candidate_dir.iterdir()):
        name = entry.name
        if name in STAGE_DIRS or name == "MANIFEST.json" or name == "pipeline.json":
            continue
        stage = stage_for(name)
        if stage is None:
            skipped.append(name)
            continue
        target_dir = candidate_dir / stage
        target = target_dir / name
        if entry == target:
            continue
        if target.exists():
            # Don't clobber: keep the staged copy, drop the legacy one only
            # if the legacy is a regular file (directory clobbers stay loud).
            if entry.is_file():
                if not dry_run:
                    entry.unlink()
                moves.append((name, f"{stage}/{name} (kept staged, removed legacy)"))
            else:
                skipped.append(f"{name} (target exists, manual review needed)")
            continue
        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(target))
        moves.append((name, f"{stage}/{name}"))
    manifest = _build_manifest(candidate_dir, moves, skipped)
    if not dry_run:
        manifest_path = candidate_dir / "MANIFEST.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return manifest


def _build_manifest(
    candidate_dir: Path,
    moves: list[tuple[str, str]],
    skipped: list[str],
) -> dict[str, object]:
    stages: dict[str, list[str]] = {stage: [] for stage in STAGE_DIRS}
    flat_extras: list[str] = []
    for entry in sorted(candidate_dir.iterdir()):
        if entry.name == "MANIFEST.json":
            continue
        if entry.is_dir() and entry.name in stages:
            stages[entry.name] = sorted(child.name for child in entry.iterdir())
            continue
        flat_extras.append(entry.name)
    return {
        "schema_version": 1,
        "content_id": candidate_dir.name,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "stage_layout": {stage: stages[stage] for stage in STAGE_DIRS},
        "flat_extras": sorted(flat_extras),
        "migration": {
            "moved": [{"file": src, "to": dst} for src, dst in moves],
            "skipped": skipped,
        },
        "stage_map_size": len(STAGE_MAP),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content_id", nargs="?", default=None)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    output_root = Path(args.output_root).resolve()
    if not output_root.is_dir():
        print(f"output root not found: {output_root}", file=sys.stderr)
        return 2

    candidates = _candidate_dirs(output_root, args.content_id)
    if not candidates:
        target = args.content_id or "<all>"
        print(f"no candidate directories matched: {target}", file=sys.stderr)
        return 1

    for candidate in candidates:
        manifest = _migrate_candidate(candidate, dry_run=args.dry_run)
        moved = manifest["migration"]["moved"]  # type: ignore[index]
        skipped = manifest["migration"]["skipped"]  # type: ignore[index]
        print(
            f"[{candidate.name}] moved={len(moved)} skipped={len(skipped)}"
            f" extras_left_flat={len(manifest['flat_extras'])}"  # type: ignore[index]
            f" {'(dry-run)' if args.dry_run else ''}"
        )
        if skipped:
            for name in skipped:
                print(f"  - skipped: {name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
