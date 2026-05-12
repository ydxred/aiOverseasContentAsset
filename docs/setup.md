# 安装与首次运行

## 1. 系统要求

| 项 | 推荐 | 最低 |
|---|---|---|
| OS | Ubuntu 24.04 LTS（WSL2 OK）| Linux / macOS |
| Python | 3.12 | 3.10 |
| Node.js | 20 LTS | 18 |
| RAM | 16 GB | 8 GB |
| GPU | NVIDIA RTX ≥ 8 GB VRAM | 无 GPU 也可（mock + 云 TTS） |
| 磁盘 | 50 GB（模型 + 视频缓存）| 20 GB |
| PostgreSQL | 16+ | 可选 |

## 2. 系统依赖

### Ubuntu 24.04 / WSL2

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip \
                    git ffmpeg postgresql-client-16 \
                    build-essential

# Node.js 20 (NodeSource)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

### WSL2 GPU 加速（可选，用于本地 GPT-SoVITS）

主机端装 NVIDIA Windows driver 566+，WSL 里：

```bash
sudo apt install -y nvidia-cuda-toolkit
nvidia-smi  # 确认能看到 GPU + driver 版本
```

## 3. 仓库克隆

```bash
git clone https://github.com/ydxred/aiOverseasContentAsset.git
cd aiOverseasContentAsset
```

## 4. Python 环境

```bash
cd content_asset_mvp
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

主要依赖：
- `anthropic`、`openai`、`google-genai` — LLM SDK
- `faster-whisper` — 字幕转写
- `whisperx` — 词级对齐
- `psycopg[binary]` — PostgreSQL 驱动
- `yt-dlp` — YouTube 抓取
- `playwright`（可选）— GitHub 截图
- `requests` — TTS HTTP

## 5. Remotion 环境

```bash
cd video_engine/remotion
npm install
# 验证：
npm run preview  # 应该启动 Remotion Studio 在 http://127.0.0.1:3000
cd ../..
```

## 6. 配置 .env

```bash
cp .env.example .env
# 编辑 .env，按 docs/configuration.md 填入需要的 API key
```

最小可用配置（仅 mock）：

```bash
CONTENT_ASSET_MOCK=true
```

最小真实配置（GitHub + 文本流水线，无视频）：

```bash
DATABASE_URL=postgresql://content_asset:<pw>@localhost:5432/content_asset_mvp
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
```

加上视频生产（任选一个 TTS）：

```bash
MINIMAX_API_KEY=sk-api-...
MINIMAX_VOICE_ID=Chinese\ \(Mandarin\)_Wise_Women
```

详细配置项 → [configuration.md](configuration.md)

## 7. PostgreSQL 初始化（可选）

```bash
sudo -u postgres psql
> CREATE USER content_asset WITH PASSWORD 'content_asset_local_2026';
> CREATE DATABASE content_asset_mvp OWNER content_asset;
> \q

psql -U content_asset -d content_asset_mvp -f migrations/001_init.sql
```

或者直接跑 init 命令：

```bash
python -m app.main --init-db
```

不想用 PostgreSQL → `.env` 留空 `DATABASE_URL`，所有 DB 调用 no-op。

## 8. 验证 mock 模式

```bash
source .venv/bin/activate
python -m app.main --github-url "https://github.com/browser-use/browser-use" --mock --stage analysis
```

期望输出：`output/gh_browser-use_browser-use/01_analysis/github_analysis.json` 生成成功，没有 traceback。

## 9. 第一个真实视频

```bash
python -m app.main --github-url "https://github.com/browser-use/browser-use"
```

完整跑约 10-15 分钟（依赖 LLM API 延迟 + Remotion 渲染速度）。产物在 `output/gh_browser-use_browser-use/07_render_output/final_video.mp4`。

## 10. Web 控制台

```bash
python -m app.web --host 0.0.0.0 --port 8000
```

Windows 浏览器访问：`http://127.0.0.1:8000`。

在 WSL2 下 `127.0.0.1` 默认通；不通的话用 `hostname -I | awk '{print $1}'` 拿 WSL IP。

## 11. 本地 GPT-SoVITS（可选）

如果你想用本地 GPU 跑零样本声音克隆：

```bash
cd /root/projects
git clone https://github.com/RVC-Boss/GPT-SoVITS.git
cd GPT-SoVITS

# 独立 venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cu124 torch torchaudio
pip install -r requirements.txt

# 下载预训练模型（约 4.5 GB）
wget -q https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/pretrained_models.zip
wget -q https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/G2PWModel.zip
wget -q https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/nltk_data.zip
unzip -q -o pretrained_models.zip -d GPT_SoVITS
unzip -q -o G2PWModel.zip -d GPT_SoVITS/text
unzip -q -o nltk_data.zip -d ~/

# 改 config 用 V2Pro + cuda + half
# 见 GPT_SoVITS/configs/tts_infer.yaml 的 custom: 段
# 设 version: v2Pro, device: cuda, is_half: true

# 启动 API server
python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

确认能跑：

```bash
curl -X POST http://127.0.0.1:9880/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"你好测试","text_lang":"zh","ref_audio_path":"<your_ref.wav>","prompt_lang":"zh","prompt_text":"<ref text>","media_type":"wav"}' \
  --output test.wav
```

然后 pipeline 端 `.env` 设：

```bash
GPTSOVITS_API_URL=http://127.0.0.1:9880
GPTSOVITS_REF_AUDIO=/abs/path/to/your_ref.wav
GPTSOVITS_PROMPT_TEXT="参考音频对应的逐字转写"
```

## 12. 常见坑

| 问题 | 解决 |
|---|---|
| `ModuleNotFoundError: No module named 'torch'` | GPT-SoVITS 那条 venv 没装 torch — 见 setup.md 第 11 节 |
| `psycopg.OperationalError` | DATABASE_URL 错或 PG 没启 — `.env` 留空降级到 no-op |
| `ffmpeg: command not found` | `sudo apt install ffmpeg` |
| Remotion 渲染卡死 | `npm install` 没跑完，或 Chrome 沙箱问题。强制 `npm run render:douyin -- --browser-executable=$(which google-chrome)` |
| 中文字幕乱码 | 装 `fonts-noto-cjk`：`sudo apt install fonts-noto-cjk` |
| GPU OOM during GPT-SoVITS | 关 Chrome / Edge 释放显存；或换更小的 chunk_length |
| `parameter license not found` (Volcengine) | AppID 没绑对应 SKU 的 license — 见 [tts_providers.md](tts_providers.md) |

