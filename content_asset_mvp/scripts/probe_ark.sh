#!/usr/bin/env bash
# Minimal ARK probe to verify endpoint, key, and model name actually work.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

KEY=$(grep -E '^ARK_API_KEY=' .env | head -1 | cut -d= -f2- | tr -d '\r')
MODEL=$(grep -E '^ARK_MODEL=' .env | head -1 | cut -d= -f2- | tr -d '\r')

echo "MODEL=$MODEL"
echo "KEY_LEN=${#KEY}"
echo "KEY_PREFIX=${KEY:0:6}..."

BODY=$(MODEL="$MODEL" python3 -c '
import json, os
print(json.dumps({
    "model": os.environ["MODEL"],
    "messages": [{"role": "user", "content": "reply with exactly: ok"}],
    "max_tokens": 10,
}))
')

echo "==> POST to ark.cn-beijing.volces.com ..."
curl -sS -X POST "https://ark.cn-beijing.volces.com/api/v3/chat/completions" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  --max-time 30 \
  -d "$BODY" \
  -w "\n--HTTP-STATUS-%{http_code}--\n"
