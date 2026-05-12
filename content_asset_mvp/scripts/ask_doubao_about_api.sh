#!/usr/bin/env bash
# Use ARK_API_KEY to ask Doubao about ByteDance's own "Generate Pure Music"
# (生成纯音乐) API. Doubao-1.5-pro should know its sibling products.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

if [ -f .env ]; then
  KEY=$(grep -E '^ARK_API_KEY=' .env | head -1 | cut -d= -f2-)
  MODEL=$(grep -E '^ARK_MODEL=' .env | head -1 | cut -d= -f2-)
fi
KEY="${KEY:-}"
MODEL="${MODEL:-doubao-1-5-pro-32k-250115}"

if [ -z "$KEY" ]; then
  echo "ERR: no ARK_API_KEY in .env" >&2
  exit 1
fi

QUESTION="$(cat <<'PROMPT'
我在火山引擎控制台想调用「音视频理解与处理 → 生成纯音乐」这个 API（doc 路径 https://www.volcengine.com/docs/84992/2100970）。请用纯中文严谨回答以下问题，不要客套不要寒暄，每一项给精确技术答案：

1. 这个 API 的 SAMI namespace 名字是什么？（例如 GenerateMusic / PureMusicGen / 类似的精确字符串）
2. 调用 endpoint 完整 URL 是什么？是 sami.bytedance.com/api/v1/invoke 还是 sami.bytedance.com/api/v1/submit ？同步还是异步？
3. payload JSON 必填字段都有哪些？分别是什么类型，举一个 prompt 完整 JSON 示例。是否支持指定 duration（秒）、style/genre、bpm、mood？
4. 鉴权用的是 appkey + token，还是 access_key + secret_key 签名？token 是怎么获取的（在火山控制台哪个位置）？
5. 输出格式是什么？是直接返回 mp3/wav 二进制（base64），还是返回 task_id 然后异步轮询查 URL？
6. 这个产品的鉴权 credentials 跟「火山方舟（Ark）大模型」的 ARK_API_KEY 是同一套吗？还是必须单独在「音视频理解与处理」产品页面开通另外拿一对 AppKey + AccessToken？
7. 单首生成的计费大约是多少元？是按时长还是按次？

如果你不能确定某一项，直接说「不确定」，不要瞎编。我只要 1-7 这 7 条，每条 1-3 句话即可。
PROMPT
)"

BODY=$(MODEL="$MODEL" QUESTION="$QUESTION" python3 -c '
import json, os
print(json.dumps({
    "model": os.environ["MODEL"],
    "messages": [{"role": "user", "content": os.environ["QUESTION"]}],
    "temperature": 0.1,
    "max_tokens": 2500,
}))
')

echo "==> asking model=$MODEL ..."
RESP_FILE=/tmp/doubao_resp.json
HTTP_STATUS=$(curl -sS -X POST "https://ark.cn-beijing.volces.com/api/v3/chat/completions" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  --max-time 90 \
  -d "$BODY" \
  -o "$RESP_FILE" \
  -w "%{http_code}")
echo "HTTP_STATUS=$HTTP_STATUS  size=$(wc -c < "$RESP_FILE")"
cat "$RESP_FILE" | python3 -c "
import json, sys
d = json.load(sys.stdin)
if 'error' in d:
    print('ERROR:', json.dumps(d['error'], ensure_ascii=False, indent=2))
    sys.exit(1)
choices = d.get('choices', [])
if not choices:
    print('NO CHOICES, full response:', json.dumps(d, ensure_ascii=False, indent=2)[:2000])
    sys.exit(1)
print('---ANSWER---')
print(choices[0]['message']['content'])
print('---USAGE---')
print(d.get('usage'))
"
