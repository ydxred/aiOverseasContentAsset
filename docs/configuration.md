# 配置参考

所有配置通过 `content_asset_mvp/.env` 注入。运行时通过 `python-dotenv` 加载。

## 总开关

| 变量 | 说明 | 示例 |
|---|---|---|
| `CONTENT_ASSET_MOCK` | 总开关。`true` = 无外部依赖（无 API、无 PG、无 ffmpeg） | `false` |
| `CONTENT_ASSET_PROVIDER` | 默认 LLM provider（被 task-type 路由覆盖） | `openai` |
| `CONTENT_ASSET_MODEL` | LLM 默认模型 | `gpt-4o-mini` |

## LLM 提供方

每个 task type 可以独立路由；这里是凭据。

| 变量 | 用途 |
|---|---|
| `OPENAI_API_KEY` | OpenAI GPT-4o / gpt-4o-mini / Whisper / tts-1 |
| `ANTHROPIC_API_KEY` | Claude Sonnet 4.6（rewrite 默认走这里） |
| `GOOGLE_API_KEY` | Gemini |
| `DEEPSEEK_API_KEY` | DeepSeek |
| `QWEN_API_KEY` | 阿里云 DashScope（含 CosyVoice TTS） |
| `ARK_API_KEY` | Volcengine 火山方舟（Doubao chat） |

## PostgreSQL

```bash
DATABASE_URL=postgresql://content_asset:<pw>@localhost:5432/content_asset_mvp
```

留空 → DB 操作全部 no-op。

## GitHub（仅 GitHub 链路需要）

| 变量 | 用途 |
|---|---|
| `GITHUB_TOKEN` | PAT，绕 rate limit + 读私仓 |

## YouTube（仅 YouTube 链路需要）

| 变量 | 用途 |
|---|---|
| `YOUTUBE_API_KEY` | YouTube Data v3 |

## TTS 提供方

### MiniMax 国内（推荐主路径）

```bash
MINIMAX_API_KEY=sk-api-...
MINIMAX_VOICE_ID="Chinese (Mandarin)_Wise_Women"    # 含空格必须双引号
MINIMAX_MODEL=speech-02-hd                          # speech-02-hd / speech-2.6-hd
MINIMAX_VOLUME=0.80                                 # 0.80 for 02-hd, 1.5 for 2.6-hd
# 可选
MINIMAX_GROUP_ID=                                   # 部分接口需要
```

### Volcengine Doubao

```bash
VOLC_APPID=1238395279
VOLC_ACCESS_TOKEN=...                               # 注意：开通新服务后要重新生成
VOLC_SECRET_KEY=...                                 # 高级 API 签名用
VOLC_TTS_VOICE=zh_female_xiaoxue_uranus_bigtts      # 覆盖默认音色
VOLC_TTS_CLUSTER=volcano_tts
CONTENT_ASSET_TTS_DOUBAO_CONTEXT="像跟好朋友聊天的语气..."  # V3 only, emotion hint
```

### GPT-SoVITS 本地（零样本克隆）

```bash
GPTSOVITS_API_URL=http://127.0.0.1:9880
GPTSOVITS_REF_AUDIO=/abs/path/to/voice_reference.wav
GPTSOVITS_PROMPT_TEXT="参考音频的逐字转写文本"        # 含中文必须双引号
GPTSOVITS_TEXT_SPLIT=cut5                            # cut0 / cut1 / ... / cut5
```

### TTS 控制开关

```bash
CONTENT_ASSET_TTS_PROVIDER=auto                      # auto | minimax | doubao | dashscope | gptsovits | openai
CONTENT_ASSET_TTS_VOICE=<override>                   # 全局 voice 覆盖
CONTENT_ASSET_TTS_SSML=1                             # 0 关闭 SSML（仅对支持的 provider）
CONTENT_ASSET_TTS_DENOISE=1                          # mastering 阶段是否加 afftdn 降噪
```

## Mastering 微调（极少改）

`audio_mastering.py` 里硬编码的目标：

| 常量 | 默认 | 说明 |
|---|---|---|
| `TARGET_LOUDNESS_LUFS` | -14.0 | 抖音 / B站 mobile 默认渲染目标 |
| `TARGET_TRUE_PEAK_DBTP` | -1.5 | TP 安全余量 |
| `TARGET_LRA_LU` | 9.0 | 目标动态范围 |
| `CLEAN_GAIN_MAX_BOOST_DB` | 14.0 | clean_gain 最大线性放大量 |
| `PASSTHROUGH_LOUDNESS_LUFS_MIN` | -16.0 | 大于此值 → 不再加 gain |

## 音乐（可选）

`bgm_mixer.py` 默认在 `content_asset_mvp/assets/bgm/` 找一个匹配 mood 的 BGM。
没有素材 → 跳过 BGM 混音。

## Tests

```bash
python -m pytest                  # 全套
python -m pytest tests/test_video_director.py
python -m compileall app tests    # 仅 syntax 检查
```

## 完整 .env.example

见 [content_asset_mvp/.env.example](../content_asset_mvp/.env.example)。

