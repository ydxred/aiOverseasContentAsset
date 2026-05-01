# Content Asset MVP

第一版系统骨架实现一条克制的内容资产流水线：

```text
URL -> meta/audio placeholder -> transcript -> analysis -> score -> risk_report
-> chinese_script -> title_options -> review_notes
```

现在也支持 GitHub AI 项目解读链路：

```text
GitHub repo URL -> github_meta/readme/images/snapshot_status
-> github_analysis -> chinese_script -> title_options -> review_notes
```

审核包生成后可以继续生产竖屏视频：

```text
chinese_script.md -> voice.wav/mp3 -> subtitles.srt -> final_video.mp4
```

默认支持 mock / dry-run 跑通，不需要真实 API key 或 PostgreSQL 即可生成审核包。真实模式第一版已接入 PostgreSQL、yt-dlp、ffmpeg、OpenAI Whisper 和 OpenAI LLM provider。

## 安装

```bash
cd content_asset_mvp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

如需真实下载和转写，请安装 `yt-dlp`、`ffmpeg`，并配置 `.env` 中的 `DATABASE_URL` 与模型 API key。

## 配置

PostgreSQL 示例：

```env
DATABASE_URL=postgresql://content_asset:password@localhost:5432/content_asset_mvp
```

初始化数据库：

```bash
python -m app.main --init-db
```

mock 模式下可以不配置 `DATABASE_URL`，数据库写入会自动跳过，`--init-db --mock` 会给出跳过说明而不会尝试连接数据库。

## 运行

最小 mock 命令：

```bash
python -m app.main --url "https://youtube.com/watch?v=xxx" --mock
```

真实链路命令：

```bash
python -m app.main --url "https://youtube.com/watch?v=xxx"
```

GitHub 项目解读 mock 命令：

```bash
python -m app.main --github-url "https://github.com/owner/repo" --mock
```

GitHub 项目解读真实抓取命令：

```bash
python -m app.main --github-url "https://github.com/owner/repo"
```

真实 GitHub 链路会访问 GitHub 公共 API / raw README 页面，输出：

```text
github_meta.json
readme.md
readme_images.json
snapshot_status.json
github_analysis.json
chinese_script.md
title_options.md
review_notes.md
```

如果 GitHub API 限流或没有 token，系统会在 `github_meta.json` 的 `api_errors` 中记录原因，并尽量降级使用 raw README。可选配置 `GITHUB_TOKEN` 提高公共 API 限额。

截图能力是可选增强：如果没有安装 Playwright 或本机浏览器不可用，GitHub 主链路不会失败，会写出 `snapshot_status.json`，状态为 `skipped` 并说明原因。

自动源发现 mock 命令：

```bash
python -m app.main --discover-sources --discovery-mock
```

自动发现流程是：

```text
sources.yaml 种子源 -> 自动发现 -> 规则评分 -> data/candidate_sources.json -> Web 人工审核
```

发现到的新源不会直接进入正式 `data/sources.yaml`，只会写入候选池 `data/candidate_sources.json`。候选包含来源、发现方式、信号、评分和决策，可以用 `--discovery-limit N` 限制本次处理的候选数量；真实轻量 discovery 会尽量使用 GitHub 公共 API，遇到限流会记录错误并继续。

候选源审核闭环支持 CLI 和 Web：

```bash
python -m app.main --approve-candidate "<candidate_id>"
python -m app.main --reject-candidate "<candidate_id>" --review-reason "不适合当前选题池"
python -m app.main --archive-candidate "<candidate_id>" --review-reason "暂缓观察"
```

批准会把候选源转换为正式 source 并追加到 `data/sources.yaml` 的 `sources` 列表，同时保留 `search_queries` 等已有顶层字段；如果正式源池里已经存在相同 `source_id` 或 URL，不会重复追加，候选会标记为 `approved_existing`。拒绝和归档只更新候选池状态与原因，不会写正式源池。

真实模式会尝试：

```text
yt-dlp 拉取元数据
ffmpeg/yt-dlp 提取音频
OpenAI Whisper 转写音频
OpenAI LLM 生成分析、风控、脚本和质检 JSON
PostgreSQL 记录内容、artifact、模型运行和任务数据
```

如果缺少外部依赖或配置，命令会报出明确错误；不会把失败伪装成成功。

指定目录：

```bash
python -m app.main --url "https://youtube.com/watch?v=xxx" --mock --output-dir output --workspace-dir workspace
```

只跑到分析阶段：

```bash
python -m app.main --url "https://youtube.com/watch?v=xxx" --mock --stage analysis
```

重新生成脚本：

```bash
python -m app.main --content-id "<content_id>" --mock --rerun rewrite
```

从已有审核包生成完整视频：

```bash
python -m app.main --render-video "<content_id>"
```

强制离线验证链路，不调用真实 TTS：

```bash
python -m app.main --render-video "<content_id>" --video-mock
```

视频生成会读取 `output/<content_id>/chinese_script.md` 中的 `# 口播稿`，输出 `voice.wav` 或 `voice.mp3`、`subtitles.srt`、`tts_status.json`、`render_status.json` 和 `final_video.mp4`。真实模式优先使用 OpenAI TTS；如果没有配置 key、请求失败，或使用 `--video-mock`，系统会用 ffmpeg 生成离线静音音频，并在 `tts_status.json` 记录原因，保证可以继续渲染视频验证完整链路。字幕烧录失败时会降级生成无字幕视频，并在 `render_status.json` 记录原因。

## Web 控制台

启动浏览器操作界面：

```bash
python -m app.web --host 127.0.0.1 --port 8000
```

打开：

```text
http://127.0.0.1:8000
```

系统状态页：

```text
http://127.0.0.1:8000/status
```

当前 Web 控制台支持：

```text
输入 URL 并运行 mock / 真实流水线
输入 GitHub repo URL 生成 AI 项目解读审核包
选择运行到指定阶段
查看审核包列表
查看 review_notes、chinese_script、analysis、score、risk_report、github_meta、readme、github_analysis、snapshot_status 等 artifacts
对已有 content_id 重跑 analysis / score / risk / rewrite / quality
查看源池管理：人物源、项目源、社区源、关键词发现入口和 discovery links
查看候选源审核：候选统计、score、status、reason、signals、来源和链接，并可运行 mock discovery、批准、拒绝或归档候选
在审核包详情页点击“生成视频”，从 chinese_script.md 生成 final_video.mp4；默认勾选离线 TTS fallback
查看系统状态：mock 默认状态、DATABASE_URL、psql、yt-dlp、ffmpeg、输出目录、审核包数量
```

源池管理页：

```text
http://127.0.0.1:8000/source-manager
```

候选源审核页：

```text
http://127.0.0.1:8000/source-discovery
```

## 源池管理

`data/sources.yaml` 是只读源池配置，Web 侧通过 `/source-manager` 展示统计、按类型分组的源、关键词、信任分、优先级和发现链接。代码侧可使用 `app.source_manager` 加载规范化源列表、按 `source_type` / `category` / `status` 过滤、统计源池，以及为人物源和关键词源生成 discovery links。

当前支持的 `source_type`：

```text
creator          高价值人物源，例如 Pieter Levels、Greg Isenberg、Rob Walling
youtube_channel  YouTube 频道源
github_org       GitHub 组织或账号
github_trending  GitHub 趋势/搜索入口
product_hunt     Product Hunt 新产品入口
newsletter       Newsletter / podcast feed
blog             官方博客或高质量长文源
community        Hacker News、Indie Hackers 等社区
keyword          可生成 GitHub / YouTube / Google 搜索的关键词组
```

手动添加人物源时，在 `sources` 下新增一项即可。建议至少填写：

```yaml
- source_id: example_creator
  source_type: creator
  name: Example Creator
  category: indie_business
  trust_score: 8
  status: active
  urls:
    x: https://x.com/example
    website: https://example.com/
    projects: https://example.com/projects
  watch_keywords:
    - Example Creator
    - Example Project
  note: Why this source matters.
  priority: 8
  discovery_method: Track X posts, project launches, interviews, and changelogs.
```

人物源重要，是因为高价值创作者通常比平台热榜更早暴露真实产品实验、收入信号、失败复盘和市场迁移。系统先把 Pieter Levels / levelsio 这类源作为固定观察对象，再用关键词与项目源扩散，可以减少随机刷推荐流带来的噪声。

## mock 与真实模式差异

```text
mock 模式：
- 不需要 DATABASE_URL、yt-dlp、ffmpeg 或 API key
- 使用内置样例 transcript 和 LLM 输出
- 数据库写入自动跳过

真实模式：
- DATABASE_URL 使用 PostgreSQL，初始化命令为 python -m app.main --init-db
- 下载依赖 yt-dlp；音频提取依赖 ffmpeg
- 转写与 LLM provider 当前支持 OpenAI，需要 OPENAI_API_KEY
- metadata 成功但音频失败时会保留 meta.json，并标记 metadata_ready_audio_failed
```

## 常见错误

```text
yt-dlp is required for real download mode
安装 yt-dlp，或使用 --mock。

ffmpeg is required to extract audio
安装 ffmpeg。系统仍会保存 meta.json，但后续真实转写会因为缺少 audio_path 失败。

OPENAI_API_KEY is required
在 .env 配置 OPENAI_API_KEY，或使用 --mock。

Skipped database initialization
当前处于 mock 模式或未配置 DATABASE_URL。mock 可继续运行；真实持久化需要 PostgreSQL。

PostgreSQL operation failed
检查 DATABASE_URL、数据库是否启动、账号权限和 migrations/001_init.sql 是否已执行。
```

测试：

```bash
python -m pytest
python -m compileall app tests
```
