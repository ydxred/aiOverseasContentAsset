# Windows / WSL2 Handoff Notes

## 当前项目状态

项目目标：海外内容机会发现 -> 中文内容资产生产 -> 高质量视频生成 -> 多平台发布包 -> 反馈反哺。

当前已完成到 v6 可验证切片 + 项目内 Skills + shot_list 驱动 Remotion + 视频自审：

- 后端主项目：`content_asset_mvp/`
- 当前主分支：`main`
- 视频链路：`video_pipeline_v6_slice`
- 当前主渲染：Remotion（DouyinExplainer），失败时 FFmpeg fallback
- 渲染由 `director_plan/shot_list` 驱动，`directorPlan` prop 已经传入 Remotion 组件
- Skills 注册表：`app/skill_registry.py` -> 每次渲染产出 `skill_registry.json`
- 视频自审：`app/video_self_review.py` -> 渲染后抽帧 + 检查，输出 `video_self_review.json` 和 `self_review_frames/`
- 视觉风格：`AI Lab Terminal`（黑底 + GitHub Dark 配色 + JetBrains Mono + Jupyter cell label + 终端窗口 chrome），规范见 `content_asset_mvp/assets/visual_style_guide.json`
- BGM 自动混音：`app/bgm_mixer.py` -> 从 `content_asset_mvp/assets/bgm/` 选最新 BGM 文件叠到 `final_video.mp4`，响度归一到 -14 LUFS（抖音/B 站/YouTube 投放标准），输出 `final_video_with_bgm.mp4` + `bgm_mix_status.json`
- TTS 真人声接入：`app/tts_engine.py` 改造为 provider 分发（DashScope CosyVoice > OpenAI tts-1 > silent fallback）。优先用 `QWEN_API_KEY` 调 DashScope `cosyvoice-v3-flash` + `longanyang` 男声，中文播报节奏 ~5 字/秒。输出 mp3 后流水线用 `probe_audio_duration` 拿真实时长反推字幕和镜头时间，字幕同步**自动按真实音频对齐**。换音色：`.env` 加 `CONTENT_ASSET_TTS_VOICE=longhuhu_v3`（女声 v3）/`longanhuan`（欢快男）/`longyingmu_v3`（年轻），重渲染即生效，无需改代码
- **新候选 TTS：火山豆包语音 2.0（BigTTS）已通鉴权**。AppID/Token 写入 `.env` 的 `VOLC_APPID/VOLC_ACCESS_TOKEN`，endpoint `https://openspeech.bytedance.com/api/v1/tts`，鉴权头 `Authorization: Bearer;<token>`。Smoke test：`bash content_asset_mvp/scripts/run_probe_volc_tts.sh`，样本落到 `output/_probe/volc_tts_sample.mp3`。规格：**24kHz / 160kbps mp3 / 首包 333ms**，明显高于 DashScope flash（16kHz/64kbps）。下一步是音色定调后写 doubao provider 接进 `tts_engine.py`，把 DashScope 降级为 fallback。同一组凭证可直接复用到「音视频字幕生成 / 自动字幕打轴」（ASR），下一步配合做字级时间戳对齐
- 双版本（9:16 + 16:9）：`compositions/LandscapeExplainer.tsx` + `app/remotion_renderer.py orientation` 参数。`main.py --render-video <id> --render-landscape` 同时产出 `final_video.mp4`（竖屏抖音）和 `final_video_landscape.mp4`（B 站/YouTube 横屏）。也支持只跑横屏 demo：`bash content_asset_mvp/scripts/render_landscape_demo.sh <id>`
- 样片：`quality_smoke_browser_use`
- 最近 WSL Ubuntu 真实渲染结果：
  - `render_engine_actual`: remotion（不再是 ffmpeg fallback）
  - `duration_seconds`: 62.736
  - `resolution`: 1080x1920
  - `shot_count`: 14
  - `evidence_count`: 5（全部来自 browser-use 聚焦截图）
  - `video_self_review.pass`: true，issues=0、warnings=0

## 已同步 GitHub

仓库：

```text
https://github.com/ydxred/OverseasContentAsset-Automated-Production-System.git
```

建议到 Windows 机器后优先从 GitHub clone，而不是只依赖压缩包。

```bash
git clone https://github.com/ydxred/OverseasContentAsset-Automated-Production-System.git
cd OverseasContentAsset-Automated-Production-System
```

## 建议 Windows 环境

强烈建议使用 WSL2 Ubuntu，不建议纯 Windows Python 环境直接跑。

推荐配置：

- Windows 物理机：RTX 4070
- WSL2 Ubuntu 24.04
- 内存分配：16GB 起，最好 24-32GB
- CPU：8 核以上
- 磁盘预留：150GB+
- Node：20 或 22
- Python：3.12
- PostgreSQL：本机或 Docker 均可
- FFmpeg：优先安装带 NVENC 的版本

`.wslconfig` 建议示例：

```ini
[wsl2]
memory=24GB
processors=12
swap=8GB
```

## WSL2 初始化命令

> 重要踩坑：项目仓库放在 Windows F: 盘，从 WSL 看到的是 `/mnt/f/...`。
> 不要在 Windows 端用 `python -m venv .venv` 创建 venv 给 WSL 用：那是 Windows venv，
> 解释器指向 `C:\Python...\python.exe`，在 Linux 里跑会直接 hang。
> 一定要在 WSL Ubuntu 内部、用 Linux 的 `python3` 单独建 venv。

推荐做法：把 Linux venv 放在 WSL 家目录而不是 `/mnt/f`，跨文件系统更稳：

```bash
# 在 WSL Ubuntu 内
sudo apt-get install -y python3-venv ffmpeg
python3 -m venv ~/venv-content-mvp
~/venv-content-mvp/bin/pip install --upgrade pip
~/venv-content-mvp/bin/pip install -r "/mnt/f/kaifa/OverseasContentAsset Automated Production System/content_asset_mvp/requirements.txt"
```

之后所有 Python 命令都用 `~/venv-content-mvp/bin/python`。

最小验证用例（不装 LLM/浏览器/whisper 重依赖）只需要：

```bash
~/venv-content-mvp/bin/pip install pytest PyYAML python-dotenv 'psycopg[binary]'
```

进入项目目录跑命令时，统一加 `PYTHONPATH=.`：

```bash
cd "/mnt/f/kaifa/OverseasContentAsset Automated Production System/content_asset_mvp"
PYTHONPATH=. ~/venv-content-mvp/bin/python -m pytest tests/test_v6_video_pipeline.py
```

安装 Playwright 浏览器（用于 browser_agent / snapshotter）：

```bash
~/venv-content-mvp/bin/python -m playwright install chromium
```

安装 Remotion 依赖（必须在 WSL 内执行，否则 `@rspack` 拿不到 Linux 原生绑定）：

```bash
cd "/mnt/f/kaifa/OverseasContentAsset Automated Production System/content_asset_mvp/video_engine/remotion"
npm install --no-audit --no-fund
./node_modules/.bin/remotion versions
```

如果 npm 国外源被墙，可以加 `--registry=https://registry.npmmirror.com`。

## 环境变量

在 `content_asset_mvp/.env` 创建本地配置。不要提交 `.env`。

至少需要：

```dotenv
OPENAI_API_KEY=...
YOUTUBE_API_KEY=...
DATABASE_URL=postgresql://user:password@localhost:5432/content_asset
CONTENT_ASSET_PROVIDER=openai
CONTENT_ASSET_MODEL=gpt-5.4
```

可选：

```dotenv
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...
DEEPSEEK_API_KEY=...
QWEN_API_KEY=...           # ← 同时也是 DashScope key，TTS 会自动用
ARK_API_KEY=...
ARK_MODEL=doubao-seed-2-0-pro-260215
CONTENT_ASSET_TTS_VOICE=longanyang   # 可选，DashScope CosyVoice v3 音色
CONTENT_ASSET_TTS_MODEL=cosyvoice-v3-flash   # 可选

# 火山豆包语音 2.0 + 字幕打轴（共用一组凭证，下一步要接进 tts_engine）
VOLC_APPID=1238395279
VOLC_ACCESS_TOKEN=...
VOLC_SECRET_KEY=...                   # SDK / 双向流式才用，HTTP unary 不需要
VOLC_TTS_CLUSTER=volcano_tts
```

TTS 音色推荐：

DashScope CosyVoice（当前 default）：
- `longanyang` - 默认，稳重成熟男声（适合 AI 科技博主）
- `longanhuan` - 欢快男声
- `longhuhu_v3` - 女声 v3
- `longyingmu_v3` - 年轻女声 v3

注意 v3-flash 模型只接受 v3 音色，老的 `longxiaochun` 等 v1/v2 音色会返回 error code 418。

火山豆包 BigTTS（已通鉴权，待接入）：
- 默认探针音色：`zh_male_M392_conversation_wvae_bigtts`（对话男声）
- 100+ 音色可选，定调后再选 3-5 候选试音
- 输出规格：24kHz mp3 / 160kbps / 首包 333ms，工业级播客音质

## 数据库

如果用 PostgreSQL：

```bash
createdb content_asset
python -m app.main --init-db
```

如果临时只验证视频，可先不连数据库，部分 Web/状态功能会降级。

## 核心验证命令

检查 Python 配置：

```bash
python - <<'PY'
from app.config import load_settings
s = load_settings()
print("mock=", s.mock)
print("openai_key_present=", bool(s.openai_api_key))
print("youtube_key_present=", bool(s.youtube_api_key))
print("provider=", s.provider)
PY
```

检查 FFmpeg：

```bash
.venv/bin/ffmpeg -version
```

检查 Remotion：

```bash
cd video_engine/remotion
./node_modules/.bin/remotion versions
cd ../..
```

跑测试（最快的一组，不依赖 LLM/浏览器/whisper）：

```bash
PYTHONPATH=. ~/venv-content-mvp/bin/python -m pytest tests/test_v6_video_pipeline.py
```

跑完整媒体生产测试（需要 ffmpeg + psycopg）：

```bash
PYTHONPATH=. ~/venv-content-mvp/bin/python -m pytest tests/test_media_producer.py
```

最近一次 WSL Linux 实跑：`6 + 17` 全过。

重渲染样片（强制 mock TTS，不调外部 API）：

```bash
bash scripts/render_v6.sh quality_smoke_browser_use --video-mock
```

检查结果：

```text
output/quality_smoke_browser_use/final_video.mp4
output/quality_smoke_browser_use/cover.png
output/quality_smoke_browser_use/render_manifest.v6.json
output/quality_smoke_browser_use/render_status.json
output/quality_smoke_browser_use/remotion_status.json
output/quality_smoke_browser_use/remotion_props.json     # 已包含 directorPlan + 14 个 shot
output/quality_smoke_browser_use/visual_qc_report.json
output/quality_smoke_browser_use/video_self_review.json  # 新：抽帧自审
output/quality_smoke_browser_use/self_review_frames/     # 新：抽出来的 3 张校验帧
output/quality_smoke_browser_use/skill_registry.json     # 新：本次实际用到的 Skills
```

## Web 启动

```bash
python -m app.web
```

打开 Web 后重点看：

- `/videos` 成片库
- `/outputs/quality_smoke_browser_use`
- `/publish-board`
- `/feedback-board`

## 当前视频链路关键产物

每个资源一个目录：

```text
content_asset_mvp/output/<content_id>/
```

关键产物：

```text
final_video.mp4                # 9:16 抖音竖屏（含真人声 TTS，不含 BGM）
final_video_with_bgm.mp4       # 9:16 抖音竖屏 + 真人声 + BGM 投放版（响度 -14 LUFS）
final_video_landscape.mp4      # 16:9 B 站/YouTube 横屏（仅在 --render-landscape 时生成）
voice.mp3                      # DashScope CosyVoice 真人声原始 mp3（QWEN_API_KEY 配置时）
voice.wav                      # 静音占位（fallback 时输出，正常情况只有 voice.mp3）
voice_mastered.mp3             # 母带处理后的人声（响度归一前的中间产物）
platform_renders/douyin/final_video.mp4    # 同上竖屏的中间产物
platform_renders/bilibili/final_video.mp4  # 同上横屏的中间产物
video_render_manifest.json
render_manifest.v6.json
render_status.json
landscape_render_status.json
bgm_mix_status.json
tts_status.json                # 新：记录用了哪个 TTS provider（dashscope/openai/silent）
director_plan.json
shot_list.json
edit_decisions.json
visual_asset_pack.json
subtitle_plan.json
audio_mastering_status.json
remotion_status.json
visual_qc_report.json
video_self_review.json
skill_registry.json
platform_publish_package.json
```

## BGM 替换 / 自定义

默认 BGM 是 `content_asset_mvp/assets/bgm/ai_lab_ambient.mp3`，是用 ffmpeg
合成的占位 ambient（drone + texture），**不是给最终发布用的**，只是验证混音管线。

替换为自己的 BGM：

```bash
# 把任意 royalty-free 的 .mp3/.wav/.m4a 丢到这里
cp /path/to/your_bgm.mp3 content_asset_mvp/assets/bgm/

# 下次渲染会自动选最新 mtime 的文件作为 BGM
```

**找 BGM 的合规来源**：

- Pixabay Music（CC0，可商用）
- 抖音剪映音乐库（"无版权""国创音乐计划"标签）
- 网易云音乐"独立音乐人"开放授权专区
- YouTube Audio Library（注意是"Royalty-free"标签那一类）
- 不要从抖音/B站/YouTube 视频里直接扒 BGM——会被两边平台的指纹库识别为侵权。

也可以临时只跑混音步骤（不重做整片）：

```bash
~/venv-content-mvp/bin/python content_asset_mvp/scripts/rerun_bgm_mix.py \
    content_asset_mvp/output/<content_id>
```

混音参数 (`scripts/mix_bgm_into_video.sh`)：

- 整片响度归一到 **-14 LUFS**，true peak ≤ **-1 dBFS**（抖音/B 站/YouTube 投放标准）
- BGM fade-in 0.6s / fade-out 1.4s
- 检测到非静音的 voice 轨时，BGM 自动 sidechain duck（衰减约 6dB），让人声永远在前
- 输出 AAC 192kbps stereo 48kHz

## 下一步开发重点

1-4 已落地，现在的瓶颈在“画面真的好看 + 自审能拦住差片”。

已完成：

1. ✅ Remotion 真实主渲染 + FFmpeg fallback。
2. ✅ `directorPlan/shot_list` 驱动 `DouyinExplainer` 的镜头节奏。
3. ✅ Remotion 输出 `platform_renders/douyin/final_video.mp4` 和 `cover.png`。
4. ✅ Skills 注册表 + 视频自审 `video_self_review.json`。
5. ✅ AI Lab Terminal 视觉系统（黑底 GitHub Dark + JetBrains Mono + Jupyter cell label + 终端 chrome）。
6. ✅ BGM 自动混音 + 响度归一到 -14 LUFS，输出 `final_video_with_bgm.mp4`。
7. ✅ 16:9 横屏 composition (`LandscapeExplainer`) + `--render-landscape` 双版本输出。骨架已通，跑出 1920×1080 / 30fps demo。

下一步建议顺序（按 ROI 排）：

8. **TTS 接入 + 字幕精准对齐**——目前 voice.mp3 是静音占位，整片是"视觉 + BGM"的 PPT 感。2026 年环境下接火山方舟/讯飞 v2/Azure 中文 TTS 工程量是 1-2 天（不是一周），加 stable-ts 句级对齐。这是从 70 分跨到 85 分的硬门槛。
9. **横屏 shot 模板打磨**——纯文字 shot 右侧目前空白，需要装饰元素；`SplitLandscape` caption hint 在 evidence/repo 都显示 `// REPO OVERVIEW`，要按 visual_type 动态化；左右栏比例可以调成 36/64 让截图更大。
10. **真 BGM 接入**——drone 是占位，目前的 ffmpeg lavfi 合成在 2026 年环境下属于反例。优先选 Suno API / Pixabay Music / 抖音剪映音乐库 royalty-free 库，然后 `cp <真.mp3> content_asset_mvp/assets/bgm/` 即可。
11. **新增 2-3 套镜头模板**：`StackTraceCard`（错误/坑点）、`DiffCard`（对比）、`DataChartShot`（雷达/折线，需要 LLM 输出结构化数据点）。
12. 把 `video_self_review` 升级为像素级检查（已经做了一部分，可继续：OCR 字幕识别、镜头切点节奏检查）。
13. 内容选题 / 脚本质量提升——目前一个测试样本 `quality_smoke_browser_use`，需要更多样本验证 LLM 写脚本的稳定性。

## 迁移注意事项

- 不要提交 `.env`。
- 不要提交 `node_modules/`。
- 不要提交 `content_asset_mvp/output/`、`workspace/`、`logs/`。
- 压缩包只用于迁移参考，正式协作以 GitHub 为准。
- Windows 机器上第一次跑视频可能慢，确认 Remotion/Playwright/FFmpeg 都安装后再判断性能。

## 当前机器限制

当前 Ubuntu 虚拟机：

- 8 核虚拟 CPU
- 7.7GB 内存
- 无 NVIDIA GPU
- VMware 虚拟显卡

适合开发验证，不适合批量工业级渲染。RTX 4070 物理机更适合后续视频生产。
