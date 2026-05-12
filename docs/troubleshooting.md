# 故障排查

## 安装阶段

### `ModuleNotFoundError: No module named 'torch'`

```bash
# 没装 torch
pip install --index-url https://download.pytorch.org/whl/cu124 torch torchaudio
```

### `nvidia-smi` 不识别 GPU

WSL2 主机端要装 Windows NVIDIA driver 566+。然后 WSL 内部 `nvidia-smi` 应该能看到。

### Playwright headless 启不来（GitHub 截图功能）

```bash
playwright install chromium
playwright install-deps
```

### 中文字幕显示成方块

```bash
sudo apt install fonts-noto-cjk fonts-wqy-zenhei
fc-cache -fv
```

## LLM 阶段

### `psycopg.OperationalError: connection refused`

PostgreSQL 没启或密码错。两种处理：

```bash
# 启 PG
sudo systemctl start postgresql

# 或者直接降级到 no-op（.env 留空 DATABASE_URL）
```

### `RuntimeError: rewrite response must include script and titles`

LLM 返回 JSON 不符 schema。常见原因：
- LLM API 限流，返回了空 response
- prompt 太长触发 truncation

修复：
```bash
# 看 raw response
ls output/<id>/01_analysis/*_raw.json
# 重跑只这一个 stage
python -m app.main --content-id <id> --rerun rewrite
```

### 选题分数低（decision: archive）

`score.json` 里 `total_score < 60` → 系统不推荐做。可强制继续：

```bash
python -m app.main --github-url "..." --force-continue
```

但建议先看 `01_analysis/opportunity_engine.json` 里各维度分，理解为什么低分。

## TTS 阶段

### Doubao 报 `parameter license not found`

AppID 没绑对应 SKU 的 license：

1. 控制台开通对应 SKU（声音复刻 / 大模型语音合成）
2. **重新生成 Access Token**（旧 token 不带新权限）
3. 更新 `VOLC_ACCESS_TOKEN`

### MiniMax 报 `Invalid token`

key 格式不对或不是国内站的。国内站 key 是 `sk-api-...`（含 sk-api- 前缀的国内 platform key）。
不是 JWT。

### GPT-SoVITS API 启动失败

```bash
tail -50 /tmp/gptsovits_api.log
```

常见原因：
- `os` 没 import — 看具体错
- CUDA OOM — 关其他 GPU 进程
- 模型路径错 — `tts_infer.yaml` 里 `custom:` 段 path

### TTS 输出静音

`tts_status.json` 里 `mode: offline_silence` → 所有 provider 都 fail。
看 `fallback_attempts` 里每个的 error message。

### TTS 拉长 13+ 倍 real-time

只发生在 GPT-SoVITS 首次调用（JIT 编译），第二次开始就 0.5x real-time 正常。

## 音频 Mastering

### LUFS 远低于 -14（例如 -19.99）

原因：输入太冷 + max_boost 卡住。

```python
# audio_mastering.py
CLEAN_GAIN_MAX_BOOST_DB = 14.0  # 默认 10，bump 到 14
```

bump 后要 cache invalidate：在 `media_producer.py` 改 mastering `ffmpeg_version_pin`。

### LRA 被压扁（< 1.5 LU）

输入 LUFS 太高导致 loudnorm 触发 dynamic 模式。降 TTS 端的 vol，让输入 LUFS 在 -20 到 -16 之间。

### 听感「ai 味重」/「灰尘感」

不是音色问题，是**底噪没去净**。打开 mastering 端 denoise：

```bash
CONTENT_ASSET_TTS_DENOISE=1  # 默认开
```

`_DENOISE_PREFIX = "highpass=f=70,afftdn=nr=10:nf=-38"` 在 gain 前应用。

## 字幕 Stage

### `whisperx` 报 wav2vec2 模型下载失败

```bash
HF_ENDPOINT=https://hf-mirror.com python -m app.main --render-video <id>
```

### 字幕时间戳偏移

WhisperX 对齐失败回退到了句级时间。原因常是 voice.mp3 和原 text 不匹配（克隆音色读错字）。
重新跑：

```bash
rm output/<id>/05_subtitle/subtitle_word_alignment.json
python -m app.main --render-video <id>
```

## Remotion 渲染

### `Failed to launch browser`

```bash
cd content_asset_mvp/video_engine/remotion
npm rebuild puppeteer
# 或
npm run render -- --browser-executable=$(which google-chrome)
```

### 卡在 Bundling

```bash
rm -rf content_asset_mvp/video_engine/remotion/.next
npm run preview  # 重新 bundle
```

### 中文字符渲染断字

webfont 没加载。检查 `video_engine/remotion/public/fonts/` 下有没有 NotoSansCJK / 思源黑体。

### Remotion 渲染慢（> 5 min）

正常。1920×1080 × 30fps × 3min = 5400 帧，每帧 ~50ms = 4-5 min。
要快：换 H264 hardware encode（NVENC）：

```bash
cd content_asset_mvp/video_engine/remotion
npm run render -- --codec=h264 --encoding-max-rate=8M
```

## Pipeline 总体

### `--rerun rewrite` 报 `analysis.json not found`

GitHub 链路 → analysis 文件叫 `github_analysis.json`。

### 缓存命中但拿到错误音频

cache key 没包含某个变量。看 `media_producer.py::tts_inputs` 字典。
强制失效：

```bash
rm output/<id>/.cache/tts.json
# 或全局
python -m app.main --render-video <id> --no-cache
```

### 渲染挂在 Remotion 但音频已完成

`ps -ef | grep node` 看进程。Kill 它：

```bash
pkill -f "node.*remotion"
# 然后 --render-video 重跑（TTS 缓存命中，只重 Remotion）
```

## 环境变量（.env）问题

### bash 报 `command not found` 当 source .env

中文值没加引号：

```bash
# 错
GPTSOVITS_PROMPT_TEXT=当前 然后 ...

# 对
GPTSOVITS_PROMPT_TEXT="当前 然后 ..."
```

### 加引号但 Python 拿到的值还带引号

Python `os.getenv()` 默认会保留引号。检查方式：

```python
import os
print(repr(os.getenv("MINIMAX_VOICE_ID")))
# 应该是 "Chinese..."而不是 "\"Chinese...\""
```

如果带引号，是 bash `source .env` 把字符串当 literal 传过去了。手动 strip：

```python
value = (os.getenv("VAR") or "").strip("\"'")
```

或者用 `python-dotenv` 加载（已经在 config.py 用）。

## Web 控制台

### 端口被占

```bash
sudo lsof -i :8000
kill <pid>
```

### Windows 浏览器访问 WSL IP 不通

```bash
# 临时方案
hostname -I | awk '{print $1}'
# 启动 web 绑全网卡
python -m app.web --host 0.0.0.0
```

WSL2 自带 localhost 转发 → `127.0.0.1:8000` 一般直接通。

## 数据丢失

### `output/<id>` 不小心删了

如果有 git tracked 副本 → `git checkout HEAD -- output/<id>`。
没 git → 只能从 PG 拿 metadata 重建，但音视频文件丢了就是丢了。

### `data/sources.yaml` 误改

```bash
git diff data/sources.yaml      # 看改动
git checkout HEAD -- data/sources.yaml  # 回滚
```

## 升级

### Pull 上游 → 配置 / schema 改了

```bash
cd content_asset_mvp
git pull
pip install -r requirements.txt  # 装新依赖

# DB schema 升级
python -m app.main --init-db --upgrade
# 或手动：
psql -U content_asset content_asset_mvp -f migrations/00X_*.sql
```

## 升级 Python 3.10 → 3.12

```bash
# 删旧 venv
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

