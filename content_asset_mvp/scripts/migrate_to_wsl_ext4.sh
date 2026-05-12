#!/usr/bin/env bash
# One-time migration: move the project from Windows NTFS (/mnt/f/...) to
# WSL2 native ext4 (~/projects/...).
#
# Why
#   /mnt/f/ is the 9p-mounted Windows filesystem. Reads/writes from inside
#   WSL go through a VM boundary; the cost is small per call but devastating
#   when Node/Webpack/Remotion touches hundreds of thousands of small files.
#   Moving the project to ext4 typically gives 5-30x speedups on bundle and
#   install steps.
#
# What we keep, what we drop
#   - Source code, config, dotfiles, .env, .git → rsync as-is. Includes the
#     ~116 uncommitted files from the current dirty working tree.
#   - .venv (Windows-built Python venv won't run on Linux anyway) → rebuild.
#   - node_modules (faster to npm-install fresh than to copy 200k files
#     across 9p) → rebuild.
#   - output/ + workspace/ (rendered videos, browser-agent caches) →
#     OPTIONAL: copied if MIGRATE_OUTPUTS=1, otherwise left in /mnt/f/. We
#     default to skipping because they're regenerable and large.
#
# Run from inside WSL (Ubuntu-24.04):
#   bash /mnt/f/kaifa/OverseasContentAsset\ Automated\ Production\ System/content_asset_mvp/scripts/migrate_to_wsl_ext4.sh
#
# Optional environment variables:
#   DEST_PARENT       default: ~/projects
#   DEST_NAME         default: OverseasContentAsset
#   MIGRATE_OUTPUTS   default: 0  (set 1 to also rsync output/+workspace/)
#   FORCE             default: 0  (set 1 to overwrite an existing DEST)

set -euo pipefail

SRC='/mnt/f/kaifa/OverseasContentAsset Automated Production System'
DEST_PARENT="${DEST_PARENT:-$HOME/projects}"
DEST_NAME="${DEST_NAME:-OverseasContentAsset}"
DEST="$DEST_PARENT/$DEST_NAME"
MIGRATE_OUTPUTS="${MIGRATE_OUTPUTS:-0}"
FORCE="${FORCE:-0}"

if [[ ! -d "$SRC" ]]; then
  echo "[migrate] source not found: $SRC" >&2
  exit 1
fi
if [[ -e "$DEST" && "$FORCE" != "1" ]]; then
  echo "[migrate] destination already exists: $DEST"
  echo "  Set FORCE=1 to overwrite, or pass DEST_NAME=<other-name>." >&2
  exit 2
fi

mkdir -p "$DEST_PARENT"
[[ -e "$DEST" ]] && rm -rf "$DEST"

echo "[migrate] source : $SRC"
echo "[migrate] dest   : $DEST"
echo "[migrate] free space on dest filesystem:"
df -h "$DEST_PARENT" | tail -1

# rsync exclusions:
#   - venv / node_modules: must be rebuilt for Linux ext4 anyway.
#   - .pyc / __pycache__: rebuilt by Python on first run.
#   - .DS_Store / Thumbs.db: filesystem cruft.
#   - output/ + workspace/: large + regenerable; gated by MIGRATE_OUTPUTS.
EXCLUDES=(
  --exclude='**/.venv/'
  --exclude='**/venv/'
  --exclude='**/node_modules/'
  --exclude='**/__pycache__/'
  --exclude='**/*.pyc'
  --exclude='**/.pytest_cache/'
  --exclude='**/.mypy_cache/'
  --exclude='**/.DS_Store'
  --exclude='**/Thumbs.db'
)
if [[ "$MIGRATE_OUTPUTS" != "1" ]]; then
  EXCLUDES+=(
    --exclude='content_asset_mvp/output/'
    --exclude='content_asset_mvp/workspace/'
    --exclude='content_asset_mvp/video_engine/remotion/public/render_inputs/'
  )
fi

echo
echo "[migrate] running rsync (this can take 1-3 minutes for the .git tree)..."
START_TS=$(date +%s)
rsync -a --info=stats2 "${EXCLUDES[@]}" "$SRC/" "$DEST/"
END_TS=$(date +%s)
echo "[migrate] rsync done in $((END_TS - START_TS))s"

# Repair line endings: any shell scripts touched by Windows tools may have
# CRLF endings, which break ``set -euo pipefail`` with ``\r: invalid option``.
echo "[migrate] normalising shell-script line endings..."
find "$DEST" -type f \( -name '*.sh' -o -name '*.mjs' -o -name '*.cjs' -o -name '*.js' \) \
  -not -path '*/node_modules/*' -not -path '*/.git/*' \
  -exec sed -i 's/\r$//' {} +

# Quick sanity print.
echo
echo "[migrate] git state in destination:"
git -C "$DEST" status --short | wc -l | xargs printf '  dirty files: %s\n'
git -C "$DEST" log --oneline -3 2>/dev/null | sed 's/^/  /'

echo
echo "[migrate] DONE."
echo
echo "Next steps (run from $DEST):"
echo "  1. Python:  cd content_asset_mvp && python3 -m venv .venv && \\"
echo "             .venv/bin/pip install -r requirements.txt"
echo "  2. Node :   cd content_asset_mvp/video_engine/remotion && npm install"
echo "  3. Cursor:  in Cursor, Ctrl+Shift+P -> 'WSL: Connect to WSL'"
echo "             then File -> Open Folder -> $DEST"
echo
if [[ "$MIGRATE_OUTPUTS" != "1" ]]; then
  echo "Note: output/ and workspace/ were NOT migrated. If you need the latest"
  echo "      rendered videos for visual review, re-run with MIGRATE_OUTPUTS=1"
  echo "      or render fresh from the new location."
fi
