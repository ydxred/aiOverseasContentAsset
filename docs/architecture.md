# 架构详解

## 总览

```
                 ┌──────────────────────────────────────────────┐
                 │              Source Discovery                │
                 │   (sources.yaml / candidate_sources.json)     │
                 └────────────────────┬─────────────────────────┘
                                      ↓
   ┌──────────────────────────────────────────────────────────────┐
   │                Stage 1-7: Review Package Generation           │
   ├──────────────────────────────────────────────────────────────┤
   │   1. meta            downloader.py / github_collector.py     │
   │   2. transcript      transcriber.py (faster-whisper / openai) │
   │   3. clean           cleaner.py                              │
   │   4. analysis        analyzer.py / github_analyzer.py        │
   │   5. score           scorer.py                               │
   │   6. risk            risk_checker.py                         │
   │   7. rewrite         rewriter.py → chinese_script.md         │
   │   8. quality         quality_checker.py                      │
   └────────────────────┬─────────────────────────────────────────┘
                        ↓
                 publish_review.json (manual approve gate)
                        ↓
   ┌──────────────────────────────────────────────────────────────┐
   │           Stage 9-12: Video Production                        │
   ├──────────────────────────────────────────────────────────────┤
   │   9. tts             tts_engine.py                           │
   │   10. audio          audio_mastering.py + bgm_mixer.py       │
   │   11. subtitle       whisperx_aligner.py + subtitle_engine.py│
   │   12. video          video_director.py + remotion_renderer.py│
   └────────────────────┬─────────────────────────────────────────┘
                        ↓
                  final_video.mp4
                        ↓
   ┌──────────────────────────────────────────────────────────────┐
   │           Post-Publish: Feedback Loop                         │
   ├──────────────────────────────────────────────────────────────┤
   │   feedback_collector → feedback_analysis → source_feedback   │
   │   (回写权重到 sources.yaml)                                  │
   └──────────────────────────────────────────────────────────────┘
```

## 产物目录约定

```
output/<content_id>/
├── 00_source/             ← 原始抓取
│   ├── meta.json
│   ├── github_meta.json       (GitHub 链路)
│   ├── readme.md              (GitHub 链路)
│   ├── readme_images.json
│   ├── snapshot_status.json
│   └── transcript*.json       (YouTube 链路)
├── 01_analysis/
│   ├── analysis.json | github_analysis.json
│   ├── score.json
│   ├── risk_report.json
│   ├── opportunity_engine.json
│   └── quality_check.json
├── 02_script/             ← 文本产物
│   ├── chinese_script.md      ← 口播稿（核心）
│   ├── title_options.md       ← 标题候选
│   ├── review_notes.md
│   ├── director_plan.json     ← 分镜规划
│   ├── director_script.md
│   ├── shot_list.json
│   └── edit_decisions.json
├── 03_visual/             ← 视觉资产
│   ├── cover.png
│   ├── visual_asset_card.png
│   ├── visual_asset_pack.json
│   ├── visual_asset_pack/      ← 切片素材
│   └── brand_template.json
├── 04_audio/              ← 音频
│   ├── voice.mp3              (TTS 输出)
│   ├── voice_mastered.mp3     (loudnorm 后)
│   ├── tts_status.json
│   ├── audio_mastering_status.json
│   └── bgm_mix_status.json
├── 05_subtitle/           ← 字幕
│   ├── subtitle_plan.json
│   ├── subtitles.srt / .ass
│   ├── subtitles.director.zh.ass
│   ├── subtitles.bilingual.ass
│   ├── subtitle_word_alignment.json
│   └── subtitle_translation_status.json
├── 06_render_props/       ← Remotion 输入
│   ├── remotion_props_landscape.json
│   ├── render_manifest.v6.json
│   └── video_render_manifest.json
├── 07_render_output/      ← 最终成片
│   ├── final_video.mp4              (无 BGM)
│   ├── final_video_with_bgm.mp4     (推荐发布版)
│   └── platform_renders/<平台>/     (各平台规格切版)
├── 08_qc/                 ← 质检
│   ├── render_status.json
│   ├── video_quality_report.json
│   ├── visual_qc_report.json
│   ├── video_self_review.json
│   ├── self_review_frames/          (3 张采样帧)
│   └── director_quality_checklist.json
├── 09_publish/            ← 发布管理
│   ├── publish_review.json           (人工 approve 状态)
│   ├── media_job.json
│   ├── distribution.json
│   ├── skill_registry.json
│   └── feedback_template.json
└── .cache/                ← 增量缓存
    ├── tts.json
    ├── audio_master.json
    ├── word_align.json
    └── translate.json
```

## 文件系统优先 vs PostgreSQL

**所有 stage 的「真理来源」都是文件系统**，PostgreSQL 只做 recorder：
- `db.record_artifact()` 写一条记录指向文件
- `db.record_model_run()` 记录 LLM 调用元数据（provider/model/cost）
- DB 挂了 → pipeline 不会停，artifact 还在磁盘

**好处**：
- 任意 stage 可以单独重跑（输入是上游 stage 的产物文件）
- 调试不用 PG，cp -r 整个 content_id 目录就能复现
- mock 模式可以完全跳过 DB 还能跑通 web 控制台

## Stage-by-Stage 拆解

### Stage 1: meta（抓取）

**入口**：
- `downloader.py` — YouTube URL（用 yt-dlp 抓 metadata + 自动下载视频 mp4）
- `github_collector.py` — GitHub repo URL（PyGithub 抓 metadata、README、images，可选 Playwright 截图）
- `generic_candidate.py` — 候选池里的 `candidate_id`（直接读 candidate_metadata.json）
- `youtube_analyzer.py` — 已经下载好 transcript 的 YouTube 重分析路径

**产物**：`00_source/meta.json` + 链路相关辅助文件

### Stage 2: transcript（YouTube 限定）

**入口**：`transcriber.py`
- 默认 faster-whisper（CPU/GPU 自适应）
- 可切 OpenAI Whisper API
- 短视频用 `youtube_transcript.py` 优先抓 YouTube 内嵌字幕（更快更准）

**产物**：`00_source/transcript.json` + 状态文件

### Stage 3: clean

**入口**：`cleaner.py` — 去除字幕里的填充词、间隔、Whisper 特有的转写瑕疵

**产物**：`00_source/transcript_clean.json`

### Stage 4: analysis（LLM）

**入口**：
- `analyzer.py` — 通用 / YouTube analysis（task_type: `analysis` 或 `youtube_candidate_analysis`）
- `github_analyzer.py` — GitHub 专用（task_type: `github_analysis`）

**实现**：调 `llm_client.generate(task_type, payload)`
- prompt 在 `app/llm_client.py` 的 `_build_prompt` 函数里（不是 prompts/*.md 文件）
- 严格 JSON Schema 输出（`response_format`）

**产物**：`01_analysis/analysis.json` 或 `github_analysis.json`

### Stage 5: score（无 LLM）

**入口**：`scorer.py` + `opportunity_engine.py`

**逻辑**：按维度加权（why_now / problem_intensity / china_gap / narrative_value / video_potential / business_insight / audience_fit / evidence_completeness / risk_control）

**产物**：`01_analysis/score.json` + `opportunity_engine.json`

### Stage 6: risk（LLM）

**入口**：`risk_checker.py` (task_type: `risk`)

**输出字段**：`pass / risk_level / copyright_risk / factual_risk / platform_risk / issues / must_fix / must_review`

### Stage 7: rewrite（LLM，核心）

**入口**：`rewriter.py` (task_type: `rewrite` 或 `github_rewrite`)

**两条叙事 family**（rewriter 都识别）：

- YouTube/rewrite: `## 钩子 → ## 故事是怎么发生的 → ## 它到底怎么做到的 → ## 它还能干什么 → ## 一点感慨`
- GitHub/github_rewrite: 用同一套讲述者腔 5 段（新版 prompt，旧的 5 段标题已废弃）

**讲述者腔硬性约束**（违反即不合格）：
- 短句：每句 ≤ 35 中文字
- 钩子段开头不许"近期/随着/在如今"起句
- 禁用"分析师腔"：「项目方表示」「README 中提到了」「项目方自己做了」
- 禁用「中外对比」「对中文用户的启示」
- 数字读成口语：92,631 → "9万2千"

**产物**：`02_script/chinese_script.md` + `title_options.md` + `review_notes.md`

### Stage 8: quality（LLM）

**入口**：`quality_checker.py` (task_type: `quality`)

**输出**：`pass / quality_score / issues / fix_suggestions / ready_for_human_review`

### Stage 9: TTS

**入口**：`tts_engine.py::synthesize_narration`

**provider 路由**：
1. GPT-SoVITS（如果 `GPTSOVITS_API_URL` + `GPTSOVITS_REF_AUDIO` 都配了）
2. MiniMax（如果 `MINIMAX_API_KEY` + `MINIMAX_VOICE_ID` 都配了）
3. DashScope CosyVoice 2（如果 `QWEN_API_KEY` 配了 + auto 模式）
4. Doubao（如果 `VOLC_APPID` + `VOLC_ACCESS_TOKEN` 配了）
5. OpenAI gpt-4o-mini-tts（如果 `OPENAI_API_KEY` 配了）
6. 静音回退

**强制单一 provider**：设 `CONTENT_ASSET_TTS_PROVIDER=minimax|doubao|dashscope|gptsovits|openai`

### Stage 10: audio_mastering

**入口**：`audio_mastering.py::master_voice_audio`

**决策矩阵**：

| Regime | 触发条件 | filter |
|---|---|---|
| PASSTHROUGH | LUFS ≥ -16, TP ≤ -0.4 | atrim only |
| PEAK_TAME | LUFS ≥ -16, TP > -0.4 | alimiter only |
| CLEAN_GAIN | -25 ≤ LUFS < -16, TP headroom ≥ gain_needed | volume= 单 db boost |
| CLEAN_GAIN_LIMITED | TP headroom < gain_needed ≤ 14 dB | volume + alimiter 兜底 |
| LOUDNORM_LINEAR | 其他 | dual-pass loudnorm linear |
| LOUDNORM_DYNAMIC | 极端情况 | dual-pass dynamic |

**denoise 前置**（克隆音色专用）：`highpass=70,afftdn=nr=10:nf=-38` 在 gain 之前应用，去掉手机录音 / 克隆音色继承的底噪。

**产物**：`04_audio/voice_mastered.mp3` + `audio_mastering_status.json`

### Stage 11: subtitle

**入口**：
- `whisperx_aligner.py` — 词级时间对齐（用 WAV2VEC2 模型）
- `subtitle_engine.py` — 渲染 `.ass`（关键词高亮、双语版）

**产物**：`05_subtitle/subtitles.director.zh.ass`（主 .ass）+ `.srt` 备用

### Stage 12: video_director + remotion

**入口**：
- `video_director.py` — LLM 出分镜列表 + 视觉资产收集 + 评估对应模板
- `render_manifest.py` — 把分镜转 Remotion props JSON
- `remotion_renderer.py` — shell out 到 Node + Remotion CLI

**3 种视觉混合（60/30/10）**：
1. 纯文字动画（StoryBeat / VariableLandscape / SignalPulse / QuoteHighlight / KeywordPunch 等模板，11 种）
2. 真实素材（YouTube 关键帧 / Playwright 截图，走 EvidenceShowcase 模板）
3. 信息图（LLM 抽出来的流程图，FlowChart / BarChart / Timeline 等）

**产物**：`07_render_output/final_video.mp4` + `final_video_with_bgm.mp4`

## 缓存 v.s. 重渲染

`app/pipeline_cache.py::StageCache` 实现 per-stage 增量缓存：

| Stage | Cache Key Includes | 强制失效方式 |
|---|---|---|
| tts | text, provider preference, voice_id, ssml_v1, persona hints | `--no-cache` 或换 voice_id |
| audio_master | voice_path, mastering version pin | `mastering_decision_v6` bump |
| word_align | mastered_voice_path, whisperx version | 换音频自动失效 |
| translate | text, target language | 换语种自动失效 |

**强制 invalidate**：`--no-cache` 标志或 bump 版本 key（媒体生产引擎里的 `ffmpeg_version_pin` 之类）

## LLM 路由

`app/llm_client.py::LLMClient`：

- `rewrite` / `github_rewrite` → Claude Sonnet 4.6（更服从长 prompt）
- `analysis` / `youtube_candidate_analysis` / `github_analysis` → GPT-4o-mini（够用且便宜）
- `risk` / `quality` → GPT-4o-mini
- `flow_steps` → GPT-4o-mini（提取信息图步骤标签）

**Mock 模式**：所有 task_type 都返回固定 JSON，不调任何真实 API。

## 反馈闭环

发布后回收数据 → 自动调权重：

```
publish_board.py / platform_publish.py
   ↓
publish_tasks.json (手动输入 likes / comments / completion_rate)
   ↓
feedback_analysis.py → data/feedback_report.json
   ↓
source_feedback.py → data/source_feedback_report.json
   ↓ (可选)
sources.yaml 权重写回
```

下一轮选题打分时，曾经爆的来源 / 主题自动加分。

