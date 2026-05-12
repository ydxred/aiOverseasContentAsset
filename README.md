# 海外 AI 信号 · 自动化内容资产生产系统

> 把海外 AI 项目自动转成「中文叙事短视频」的工程化 pipeline。  
> 12 个 stage / 53 个 Python 模块 / 21,000+ 行代码 / 端到端可观测。

定位（**不是泛 AI 视频，不是 AI 赚钱教程**）：

```
海外 AI 商业机会  +  AI 工具 / CLI / 开源项目解读  +  中文叙事视频资产
```

支持的内容类型：
- `ai_tool_explainer` — AI 工具解读
- `ai_cli_agent` — CLI Agent 解读
- `github_open_source_project` — 开源仓库拆解
- `overseas_ai_startup_case` — 海外 AI 创业案例
- `product_hunt_new_product` — Product Hunt 新品
- `ai_business_model_observation` — 商业模式观察
- `overseas_info_gap_story` — 信息差故事
- `creator_portrait` — 独立创作者素描

---

## 一句话演示

```bash
cd content_asset_mvp
source .venv/bin/activate
python -m app.main --github-url "https://github.com/browser-use/browser-use" --auto-close-loop
```

→ 6-10 分钟后得到 `output/gh_browser-use_browser-use/07_render_output/final_video.mp4`：1920×1080 / 中文字幕 / 真人音色 / BGM / 全自动。

---

## 1. Pipeline 全景

```
┌─────────────────────────────────────────────────────────────────┐
│  Source Discovery (GitHub / YouTube / Product Hunt / 候选池)    │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓
   meta + readme → analysis(LLM) → score → risk_check → rewrite
                                                          ↓
                              ┌───────── chinese_script.md
                              ↓
                   ┌──────────┴──────────────────────────────┐
                   │       Media Production Sub-Pipeline       │
                   │  ──────────────────────────────────────  │
                   │   TTS(MiniMax/Doubao/GPT-SoVITS)         │
                   │   → audio_mastering(loudnorm + limiter)   │
                   │   → bgm_mixer                             │
                   │   → whisperx(word-level subtitle align)   │
                   │   → subtitle_engine(.ass)                 │
                   │   → video_director(shot list)             │
                   │   → remotion_renderer(1920x1080 mp4)      │
                   │   → visual_qc + video_self_review         │
                   └────────────────────┬──────────────────────┘
                                        ↓
                            ┌─────── final_video.mp4
                            ↓
              publish_review(人工 approve) → platform_publish
                                                  ↓
              feedback_collector → feedback_analysis → source_feedback
              （点赞/评论/完播率回写到选题打分权重）
```

每个 stage 产物落盘到 `output/<content_id>/`，**任意 stage 可单独重跑**（`--rerun analysis|score|risk|rewrite|quality`），失败时不会污染上下游。

详细架构 → [docs/architecture.md](docs/architecture.md)

---

## 2. 快速开始

### 2.1 系统要求

- WSL2 Ubuntu 24.04（或 Linux / macOS）
- Python 3.12+
- Node.js 20+（Remotion 需要）
- ffmpeg
- PostgreSQL 16+（可选，mock 模式无须）
- NVIDIA GPU（可选，用于本地 GPT-SoVITS 推理）

### 2.2 安装

```bash
git clone https://github.com/ydxred/aiOverseasContentAsset.git
cd aiOverseasContentAsset/content_asset_mvp

# Python 环境
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Remotion 环境
cd video_engine/remotion && npm install && cd ../..

# 配置
cp .env.example .env
# 编辑 .env 填入你的 API key — 详见 docs/configuration.md
```

### 2.3 初始化 PostgreSQL（仅真实模式）

```bash
createdb content_asset_mvp
psql content_asset_mvp -f migrations/001_init.sql
```

或在 `.env` 留空 `DATABASE_URL` 跑 **mock 模式**——无 DB、无 yt-dlp、无 API key 也能跑通。

### 2.4 第一个视频

```bash
# 纯 mock，验证流水线
python -m app.main --github-url "https://github.com/browser-use/browser-use" --mock

# 真实模式，端到端
python -m app.main --github-url "https://github.com/browser-use/browser-use"

# 已有 review package，单独跑视频生成
python -m app.main --render-video gh_browser-use_browser-use
```

详细 setup → [docs/setup.md](docs/setup.md)

---

## 3. 常用命令

```bash
# 列出全部 CLI 子命令
python -m app.main --help

# 选题候选池（discovery 模式）
python -m app.main --auto-close-loop --auto-mock-discovery --auto-video-mock

# 重跑单个 stage（基于现有产物）
python -m app.main --content-id <id> --rerun rewrite --mock

# 提前停在某个 stage（meta | transcript | clean | analysis | score | risk | rewrite | quality）
python -m app.main --url "..." --mock --stage analysis

# 启动 Web 控制台（选题板、成片库、反馈板）
python -m app.web --host 0.0.0.0 --port 8000
```

---

## 4. TTS 提供方对比

支持四个 provider，按优先级：

| Provider | 模式 | 适用 | 像度 | 接入复杂度 |
|---|---|---|---|---|
| **MiniMax `speech-02-hd` / `speech-2.6-hd`** | API + 声音克隆 | 中文最自然商用 TTS | 75-85%（克隆） | ⭐ |
| **Doubao Uranus V3 (BigTTS 2.0)** | API + context_texts 情感 | 系统音色丰富 | N/A | ⭐⭐ |
| **GPT-SoVITS V2Pro** | 本地 GPU 零样本 | 8GB VRAM 可跑 | 80-90%（克隆） | ⭐⭐⭐ |
| **OpenAI gpt-4o-mini-tts** | API | 多语种 | N/A | ⭐ |

提供方路由在 `app/tts_engine.py` 里。详细对比 + 声音克隆经验 → [docs/tts_providers.md](docs/tts_providers.md) | [docs/voice_cloning_lessons.md](docs/voice_cloning_lessons.md)

---

## 5. 关键设计选择

### 5.1 Stage-based artifact pipeline
每个 stage 读写 `output/<content_id>/<NN>_<stage>/` 下的 JSON / Markdown / 媒体文件。
**文件系统是真理来源**，PostgreSQL 只是 recorder。这让任意 stage 都能独立重跑，调试时不用反复跑全流程。

### 5.2 Mock 模式优先
`--mock` 或 `CONTENT_ASSET_MOCK=true` 让所有外部依赖（API key、yt-dlp、ffmpeg、PostgreSQL）变成可选。
**Web 控制台和 60%+ 测试用例只在 mock 下跑**——零配置即可上手。

### 5.3 LLM 输出用严格 JSON Schema
analysis / rewrite / risk 都用 `response_format` 强制 JSON Schema。
非严格 prompt 会被模型悄悄丢字段，曾导致 GitHub 链路 markdown fallback。

### 5.4 失败要可见
TTS 拿不到密钥时落盘 `tts_status.json` 写明原因（不是悄悄 silence）；
字幕烧入失败回退到无字幕视频并在 `render_status.json` 记 reason。
**降级要明显，永不静默**。

### 5.5 内容定位是硬约束
所有 prompt 强制：不承诺收益、不照搬路径、不夸大成熟度、不做中外对比。
违反这条 = 内容不合格，无论数据多漂亮。

---

## 6. 目录结构

```
.
├── README.md                         ← 你正在看的
├── CLAUDE.md                         ← AI 协作约定
├── docs/                             ← 详细文档
│   ├── architecture.md
│   ├── setup.md
│   ├── configuration.md
│   ├── tts_providers.md
│   ├── voice_cloning_lessons.md
│   ├── web_console.md
│   ├── feedback_loop.md
│   └── troubleshooting.md
├── content_asset_mvp/                ← 主代码包
│   ├── app/                          ← 业务逻辑（53 模块）
│   ├── prompts/                      ← LLM prompt 库
│   ├── video_engine/remotion/        ← Remotion 渲染器
│   ├── scripts/                      ← 单次性脚本（声音克隆等）
│   ├── tests/                        ← pytest
│   ├── data/                         ← 选题 / 反馈 / 模板配置
│   ├── migrations/                   ← PostgreSQL schema
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md                     ← MVP 自身的 README（旧版）
├── project_packages/                 ← 历史快照包
└── 海外内容资产自动生产系统*.md     ← 中文设计文档
```

---

## 7. 这个项目的故事

两周从想法到第一条视频。中间踩了 6 个坑：

1. **rewriter 默认走"分析师腔"** → 改成「讲述者腔」（短句、反问、口语连词）后留存预期才回来
2. **关键词抽词器把 9万2千 拆成 2千** → 修复 `_CN_NUM_UNIT_RE` 复合数字
3. **5 个 TTS 克隆方案逐个失败** → 接受 few-shot 物理上限是 80-90% 像
4. **必剪曼波拿不到 API** → 路径 A（手动导出）成为长期策略
5. **音频 mastering max_boost 卡在 10 dB** → 提到 14 dB 让 GPT-SoVITS 的 -26 LUFS 输出能拉到 -14
6. **`.env` 里中文 prompt 没引号** → 被 bash 当命令执行报错

每个坑都进了 `docs/troubleshooting.md`。

---

## 8. 协议 & 致谢

MIT License。基于这些优秀开源项目：

- [Remotion](https://www.remotion.dev/) — React 视频渲染
- [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) — 本地零样本声音克隆
- [WhisperX](https://github.com/m-bain/whisperX) — 词级字幕对齐
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — 高性能 Whisper 推理
- [ffmpeg](https://ffmpeg.org/) — 音视频处理
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — YouTube 抓取
- [anthropic-sdk-python](https://github.com/anthropics/anthropic-sdk-python) — Claude SDK
- [OpenAI Python](https://github.com/openai/openai-python) — OpenAI SDK

商业服务调用：MiniMax、Volcengine Doubao、阿里云 DashScope CosyVoice。

---

## 9. Roadmap

- [ ] 抖音 / B 站 / 视频号 发布 API 集成
- [ ] 自动封面 A/B 测试
- [ ] Hashtag 推荐器接入选题打分
- [ ] 多语种字幕（en/ja 同步导出）
- [ ] 自动剪辑 reaction / 反应类视频（多 source 拼接）
- [ ] CosyVoice 3 全量 fine-tune（需 16+ GB GPU）

---

发现 bug / 想加内容类型？欢迎 issue / PR。

