# TTS 提供方深度对比

横向实测过 5 个 provider，下面是真实数据 + 经验。

## 一句话总结

| 场景 | 推荐 |
|---|---|
| 中文叙事，要真人感 | **MiniMax 声音克隆**（最像，云 API） |
| 完全本地 / 无外部依赖 | **GPT-SoVITS V2Pro**（需 8 GB+ VRAM） |
| 不要克隆，直接用现成主播音色 | **MiniMax `Chinese (Mandarin)_Wise_Women`** |
| 字符版便宜 + 中文 prosody 控制 | **Doubao Uranus V3**（V3 不支持 SSML，用 context_texts） |
| 多语种 + 西方语境 | **OpenAI gpt-4o-mini-tts** + `coral`/`ballad` |
| 抖音/B站「必剪曼波」 | **必剪 app 手动导出**（无 API） |

## 五档真实测试（同一脚本 989 字）

| 配置 | 时长 | LUFS | LRA | 字/秒 | 综合分 | 备注 |
|---|---|---|---|---|---|---|
| CosyVoice 2 `longcheng_v2` | 3:48 | -15.93 | 1.6 | 4.3 | 96 | 朗读腔最重 |
| Doubao 刘飞（uranus）| 2:21 | -15.38 | 2.3 | 7.0 | 97 | 节奏快 |
| Doubao 清新女生（uranus）| 2:47 | -14.64 | 2.1 | 5.9 | 97 | 偏年轻 |
| Doubao 小雪（uranus）| 3:20 | -14.55 | 2.4 | 5.0 | 97 | 叙事节奏 |
| MiniMax 02-hd + 克隆 v4_hifi | 2:12 | -15.10 | 2.7 | 7.6 | 91 | LRA 最高 |
| MiniMax 2.6-hd + 克隆 + vol 1.5 | 2:30 | -14.59 | 2.0 | — | 91 | 2.6 输出冷 |
| MiniMax 阅历姐姐 + denoise | 3:00 | -15.09 | 3.0 | — | 91 | **LRA 最高 ⭐** |
| GPT-SoVITS V2Pro + 克隆 | 2:50 | -14.73 | 2.2 | — | 91 | 本地最佳 |

> LRA（响度范围）4-8 LU = 真人朗读自然；6+ = 满分。所有 few-shot TTS 都在 1.6-3.0 之间，这就是天花板。

## 接入 1：MiniMax 国内

### 注册
1. 访问 https://platform.minimaxi.com
2. 实名认证（个人或企业）
3. 充值 ¥50-100（按字符付费，~¥0.0003/字）
4. 控制台拿 API Key（注意：`sk-api-...` 格式，不是 JWT）

### 凭据

```bash
MINIMAX_API_KEY=sk-api-...
```

### 调用（pipeline 已封装）

`app/tts_engine.py::_minimax_tts`：

```python
POST https://api.minimaxi.com/v1/t2a_v2
{
  "model": "speech-02-hd",          // or speech-2.6-hd
  "text": "...",
  "voice_setting": {
    "voice_id": "Chinese (Mandarin)_Wise_Women",  // 或克隆 voice_id
    "speed": 1.0, "vol": 0.80, "pitch": 0
  },
  "audio_setting": {
    "sample_rate": 32000, "bitrate": 128000,
    "format": "mp3", "channel": 1
  }
}
```

### MiniMax 声音克隆完整流程

**步骤 1**：上传参考音频（30 秒，干净，单声道）

```python
POST https://api.minimaxi.com/v1/files/upload
multipart: file=<your_voice.wav>, purpose=voice_clone
→ {"file": {"file_id": 397243660575132, ...}}
```

**步骤 2**：训练克隆

```python
POST https://api.minimaxi.com/v1/voice_clone
{
  "file_id": 397243660575132,
  "voice_id": "your_custom_id",
  "need_noise_reduction": true,
  "need_volume_normalization": true,
  "model": "speech-02-hd",
  "accuracy": 0.9,                   // 0-1，越高越像
  "text": "参考音频的逐字转写"        // 显著提升精度
}
→ {"demo_audio": "https://...", "base_resp": {"status_code": 0}}
```

**步骤 3**：使用

```bash
MINIMAX_VOICE_ID=your_custom_id  # 写入 .env
```

### 模型对比

| 模型 | 输出响度 | LRA | 推荐场景 |
|---|---|---|---|
| `speech-02-hd` | -11.88 LUFS (vol 1.0) | 2.7 | 一般用 vol 0.80 |
| `speech-2.6-hd` | -24.87 LUFS (vol 0.80) | 2.0 | Fluent LoRA 解耦音色，需 vol 1.5-2.0 |

### 系统音色推荐（不要克隆，直接用）

303 个系统音色里挑了几个最常用的：

| voice_id | 名称 | 适用 |
|---|---|---|
| `Chinese (Mandarin)_Wise_Women` | 阅历姐姐 | 叙事科普女声 ⭐ |
| `Chinese (Mandarin)_News_Anchor` | 新闻女声 | 严肃播报 |
| `Chinese (Mandarin)_Warm_Bestie` | 温暖闺蜜 | 聊天感 |
| `Chinese (Mandarin)_Wise_Women` | 阅历姐姐 | 自媒体科普 ⭐ |
| `Chinese (Mandarin)_Gentle_Senior` | 温柔学姐 | 温和有底气 |
| `male-qn-badao` | 霸道青年男声 | 男声叙事 |
| `audiobook_female_1` | 有声书女 | 长故事 |

## 接入 2：Volcengine Doubao

### 开通

1. https://console.volcengine.com/speech/service/19
2. 选「大模型语音合成」
3. 开通 「语音合成 2.0 字符版 后付费」
4. **重要**：开通新 SKU 后要 **重新生成 Access Token**（旧 token 不带新权限）

### 凭据

```bash
VOLC_APPID=1238395279
VOLC_ACCESS_TOKEN=...           # 服务接口认证信息里复制
VOLC_SECRET_KEY=...
```

### V3 vs V1

- BigTTS 1.0 → V1 endpoint (`api/v1/tts/text/streaming`)，支持 SSML
- BigTTS 2.0 (Uranus / SeedTTS) → V3 endpoint (`api/v3/tts/unidirectional`)，**不支持 SSML**，改用 `additions.context_texts`

`app/tts_engine.py::_doubao_route_for_voice` 自动按 voice 后缀路由：
- `*_uranus_bigtts` / `saturn_*` → V3 + `seed-tts-2.0`
- `S_*` → V3 + `seed-icl-2.0`（声音克隆 2.0）
- 其他 → V1

### context_texts 情感提示（V3 only）

```bash
CONTENT_ASSET_TTS_DOUBAO_CONTEXT="像跟好朋友聊一个你刚刷到的酷东西的语气，自然、放松、有点惊讶。"
```

代替 prosody SSML 控制 delivery。

### 声音复刻 2.0（ICL）

我们试过没跑通——AppID 需要单独绑定 `volc.seedicl.voiceclone` 资源，开通后 token 要重生成。文档不全。**不推荐**。

## 接入 3：DashScope CosyVoice 2

### 凭据

```bash
QWEN_API_KEY=sk-...
```

阿里云百炼平台 → API Key。

### 关键参数

```python
# app/tts_engine.py 默认
DASHSCOPE_DEFAULT_MODEL = "cosyvoice-v2"
DASHSCOPE_DEFAULT_VOICE = "longcheng_v2"   # 沉稳男声
```

可选 voice：`longxiaoxia_v2`（温柔女）、`longwan_v2`（知性女）、`loongstella_v2`（京腔女）等几十种。

### 注意：`<prosody>` 不支持

CosyVoice 2 同步 API 拒绝 `<prosody>` 标签会报 411。`tts_engine.py` 自动 strip 掉。
只能用 `<break>` 控制停顿。

## 接入 4：GPT-SoVITS V2Pro（本地零样本）

### 安装

见 [setup.md](setup.md) 第 11 节。

### 配置

```bash
GPTSOVITS_API_URL=http://127.0.0.1:9880
GPTSOVITS_REF_AUDIO=/abs/path/to/ref.wav
GPTSOVITS_PROMPT_TEXT="ref 对应转写文本"
GPTSOVITS_TEXT_SPLIT=cut5
```

### 启动

每次开机要手动启动 API server：

```bash
cd /root/projects/GPT-SoVITS
source .venv/bin/activate
python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

模型加载约 30 秒。之后 pipeline 的 TTS 调用自动走这里。

### 性能

RTX 4070 Laptop（8 GB VRAM）：
- 模型常驻：4-5 GB
- 推理：0.5x real-time（989 字 → 约 5-6 分钟生成）
- 输出：32kHz mono PCM WAV

### 已知问题

- 输出比 MiniMax 安静 5-12 dB → mastering 需要 14 dB max_boost（已配）
- text_split_method=cut5 会在标点处切分，长句保留度有限

## 接入 5：OpenAI

```bash
OPENAI_API_KEY=sk-...
```

`app/media_producer.py::_openai_tts` 硬编码 voice `alloy`，模型 `gpt-4o-mini-tts` → fallback `tts-1`。
要更自然 → 改成 `coral` / `ballad` / `verse` / `ash`（newer voices）。

## TTS 选型决策树

```
你账号是认真做长期内容吗？
├── 是 → 真人感重要 → MiniMax 克隆 or 必剪曼波手动导出
│         (10 条以内手动，跑通后再考虑 GPT-SoVITS 本地)
└── 否 → 系统音色就够 → MiniMax 阅历姐姐 / Doubao 小雪 / OpenAI coral
```

## Few-shot 克隆物理上限

实测 5+ 个克隆方案，结论：

> **没有 few-shot API 能做到 100% 像**。无论 MiniMax / Fish / Doubao ICL / GPT-SoVITS zero-shot，最高 80-90% 像。

要 95% 像需要：
- MiniMax 商业「声音定制」（30 min 录音 + ¥3000-5000）
- ElevenLabs Professional Voice Clone（30 min + 1-2 hr 录音 + $99/月）
- 本地全量 fine-tune CosyVoice 3 / Qwen3-TTS（需 30 min+ 数据 + 16 GB+ VRAM）

经验：早期账号不要在音色 100% 像上钻牛角尖。**选题 + 脚本风格 + 内容立场**才是观众感知差异化的核心。

