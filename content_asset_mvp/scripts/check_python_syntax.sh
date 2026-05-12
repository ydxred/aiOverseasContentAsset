#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read()); print("ok:", sys.argv[1])' "$1"
