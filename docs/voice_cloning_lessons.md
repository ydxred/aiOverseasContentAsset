# 声音克隆 · 一周踩坑实录

## 0. TL;DR

- Few-shot 声音克隆永远到不了 100% 像，这是模型架构上限
- 即使给 60 秒高质量参考 + 转写文本 + accuracy 0.9，最像 85-90%
- 真要追 95%+ → 付费商用「专属克隆」或本地全量 fine-tune
- 抖音/B站要「曼波」声 → 只能必剪 app 手动导出，B站不开放 API

## 1. 跑过的方案

### MiniMax 声音克隆（few-shot API）

| 版本 | 参考 | 参数 | 像度 |
|---|---|---|---|
| oca_main_v1 | 30s | 默认 | 70% |
| oca_main_v2_clean | 30s | noise_reduction | 72% |
| oca_main_v3_pure | 30s offline-denoised | noise_reduction | 73% |
| oca_main_v4_hifi | 30s + 转写文本 | accuracy 0.9 | 78% |
| oca_voice_v5_long | 60s + 转写文本 | accuracy 0.9 | 80% |

每升级一档参数 → 像度 + 2-3%。但永远过不了 90%。

### Doubao 声音复刻 2.0 ICL

**完全没跑通**：
- `volc.seedicl.voiceclone` resource 需要单独开通 + 绑定 AppID
- 即使 AppID 开通了 license，access_token 也要重新生成（旧 token 不带新 SKU 权限）
- Volcengine 文档不全，错误消息有 typo（"fro resourceId" 而非 "for resourceId"）

经过 24 个 endpoint × resource_id × auth_style 组合的穷举探测后放弃。

### Fish Audio

API key 是从国内代理拿的（`sk-api-5-...`），公开 read 端点过，但所有 write 端点 401 "Invalid token"。
推测 key 不是原生 fish.audio 的。要走 Fish 得 fish.audio 直接注册（海外服务）。

### GPT-SoVITS V2Pro（本地零样本）

唯一**免费 + 零边际成本** + **本地可控**的方案。

- 8 GB VRAM RTX 4070 Laptop 可跑
- 推理 0.5x real-time，989 字 → 5-6 分钟
- 用 30s 参考 + 转写 zero-shot，像度 80-85%
- 全量 fine-tune（需要 30 min+ 数据）能到 90-95%，但我们 1.5 分钟样本不够

## 2. 关键 prompt：「真人感」≠「100% 像」

用户反馈「不行」「ai 味重」「灰尘感」时，常常**不是音色不够像**，而是：

1. **底噪被克隆进去了**（手机录音的电流声 / 房间混响）→ 双层降噪（offline ffmpeg + MiniMax 内置）
2. **LUFS 不达标** → mastering loudnorm 拉到 -14 ±1
3. **TP 触顶导致动态被压扁** → alimiter 兜底
4. **LRA 太低**（< 2 LU）→ 听感平、像机器播报 → 换模型 / 优化 mastering

修这些工程问题后，「ai 味」感受度下降 50%，但音色相似度本身不会变。

## 3. mastering 关键参数（针对克隆音色）

```python
# app/audio_mastering.py
CLEAN_GAIN_MAX_BOOST_DB = 14.0          # 默认 10，但 GPT-SoVITS 输出 -26 LUFS 要 14
TARGET_LOUDNESS_LUFS = -14.0            # 抖音/B站 mobile 标准
TARGET_TRUE_PEAK_DBTP = -1.5
PASSTHROUGH_LOUDNESS_LUFS_MIN = -16.0   # 大于此值不再加 gain

# denoise prefix（克隆音色专用）
_DENOISE_PREFIX = "highpass=f=70,afftdn=nr=10:nf=-38,"
```

输入信号类型 → 默认 vol 推荐：

| TTS 输出 | 默认 vol | 输入 LUFS | 终态 LUFS |
|---|---|---|---|
| MiniMax 02-hd | 1.0 (热) | -11.88 | TP clip 风险 |
| MiniMax 02-hd | **0.80** | -16 | -14.6 ✅ |
| MiniMax 2.6-hd | **1.5-2.0** | -19 | -14.6 ✅ |
| Doubao Uranus | 默认 | -22 | -15 |
| GPT-SoVITS V2Pro | 默认 | -26 | -14.7（要 14 dB max_boost）|

## 4. 数据准备：参考音频规范

### 录什么内容
- **覆盖音素**：一段 30 秒文本要包含常见辅音 + 元音组合
- **覆盖情绪**：陈述 + 反问 + 强调（参考音频里有这三种语调，克隆输出才能表达）
- **包含数字 + 英文词**（你视频里要念 9万2千、Playwright，参考音频里也要类似 token）

### 录音质量

| 设备 | 像度上限 |
|---|---|
| 手机内置麦（嘈杂环境）| 70% |
| 手机内置麦（安静房间）| 75% |
| AirPods / 入耳麦 | 80% |
| USB 电容麦 + 隔音 | 85-90%（few-shot 物理上限）|

### 后期处理

```bash
ffmpeg -y -i raw_recording.mp4 \
  -vn -ac 1 -ar 24000 \
  -af "highpass=f=80,afftdn=nr=12:nf=-25,loudnorm=I=-18:TP=-2:LRA=11,atrim=start=2:end=27" \
  ref_cleaned.wav
```

参数说明：
- `highpass=80` 去掉 80 Hz 以下电流声 / 空调嗡鸣
- `afftdn` FFT denoise，nr=12 dB 强度
- `loudnorm` 归一化到 -18 LUFS（克隆模型期望的输入水平）
- `atrim` 裁掉头尾的开机噪声 / 静音

## 5. 转写文本提升 5-10% 像度

MiniMax / GPT-SoVITS / 几乎所有支持 reference text 的 API 都建议同时传：

```python
voice_clone(
  file_id=...,
  text="参考音频的逐字转写文本，标点对齐",  # ← 关键
  accuracy=0.9,
)
```

转写工具：

```python
from faster_whisper import WhisperModel
model = WhisperModel("base", device="cpu", compute_type="int8")
segments, info = model.transcribe("ref.wav", language="zh", beam_size=5)
text = " ".join(s.text.strip() for s in segments)
```

注意：Whisper-base 中文识别有错字（"versus" / "宣聊"），手动校对一下能再提 2-3%。

## 6. 必剪 / 曼波 问题

「曼波」是 B 站必剪自己定制训练的音色，**不在任何开放 TTS 服务的音色池里**：

- ❌ MiniMax 303 个 system voice
- ❌ Doubao Uranus 池（探过 70+ 个 ID）
- ❌ Fish Audio
- ❌ GPT-SoVITS 任何开源预训练

**只能在必剪 app/web 里用**。Bilibili 没开放 API。

### 工作流（接受不自动化）

每条视频：
1. 自动生成 chinese_script.md
2. 复制纯文本，粘到必剪 → 选曼波 → 导出 mp3
3. 把 mp3 丢到 `workspace/voice_ref/` 或类似目录
4. 手动替换 `output/<id>/04_audio/voice.mp3`，跑 `--rerun` 重新对齐 + 渲染

每条视频额外 5 分钟手动。早期账号可接受。

### 自动化方案（不推荐）

抓必剪 web API → mitmproxy 捕获请求 → 反向接入。
**违 ToS**，B 站可能封号 / 限频，且协议会变。

## 7. 期望管理

| 想要 | 现实 | 替代 |
|---|---|---|
| 100% 像本人 | 不可能（few-shot 上限 90%） | 商业专属克隆 ¥3-5k，或本地全量 fine-tune |
| 完美曼波 | 必剪外没有 API | 手动导出 |
| 全自动化中文 TTS | 可以做到，但音色 80% 像 | 接受这个标准，先把内容做起来 |
| 跟原音完全 indistinguishable | 商业付费克隆也只能 95% | 现实里没人会拿你视频跟你本人对比 |

## 8. 建议路径

### Phase 1 — 内容启动期（0-10 条视频）
- TTS：MiniMax 系统音色 `Chinese (Mandarin)_Wise_Women`
- 0 配置成本，立刻开拍
- 「不是真人」对早期 0 粉账号完全不是问题

### Phase 2 — 验证选题方向（10-50 条视频）
- 如果某条选题方向起量了 → 投资人设
- TTS 升级：MiniMax 商业克隆 ¥3-5k，或本地 GPT-SoVITS V2Pro 全量 fine-tune

### Phase 3 — 自动化扩张
- 接抖音/B站发布 API
- 多 prompt 自动 AB 测
- 选题打分基于反馈自学

**不要在 Phase 1 就追 95% 像**。先把内容做出来再说。

