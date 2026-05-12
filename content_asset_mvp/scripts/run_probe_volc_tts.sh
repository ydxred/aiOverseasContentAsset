#!/usr/bin/env bash
# Wrapper to load .env and run the probe (avoids PowerShell quoting hell).
set -uo pipefail
cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
source .env
set +a

bash scripts/probe_volc_tts.sh
