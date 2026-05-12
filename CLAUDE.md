# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project scope (read this first)

This is a Chinese-language content asset pipeline targeting one narrow positioning — **not** generic AI video, **not** AI-money tutorials:

```
海外 AI 商业机会 + AI 工具/CLI/开源项目解读 + 中文叙事视频资产
```

The system explains, narrates, observes, and dissects: *why* something is hot overseas, *what* it solves, and *what* it implies for Chinese users/devs/creators/founders. All outputs must avoid revenue promises, preserve fact-check + source boundary risk control, and never repackage overseas cases as "do this and copy".

Supported content types: `ai_tool_explainer`, `ai_cli_agent`, `github_open_source_project`, `overseas_ai_startup_case`, `product_hunt_new_product`, `ai_business_model_observation`, `overseas_info_gap_story`, `creator_portrait`.

`creator_portrait` is for solo-founder / indie-creator narratives (Pieter Levels, Greg Isenberg, Rob Walling) where the story is about the person's trajectory, build-in-public signals, or project portfolio — not a specific tool/repo. Visual templates: `portrait_card` (avatar + tagline), `timeline_landscape` (year-anchored milestones), `tweet_quote_card` (X/Twitter post + handle + likes), `project_portfolio_grid` (3 projects in one frame).

## Working directory

Almost everything lives under `content_asset_mvp/`. Run all commands from there unless a path explicitly says otherwise:

```bash
cd content_asset_mvp
```

The repo root holds design docs (`*.md` in Chinese), `project_packages/`, and the Remotion engine under `content_asset_mvp/video_engine/remotion/`.

## Common commands

Setup:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Init Postgres schema (real mode only — mock mode auto-skips):
```bash
python -m app.main --init-db
```

Run pipelines (mock works without DB / yt-dlp / ffmpeg / API keys):
```bash
# YouTube URL → review package
python -m app.main --url "https://youtube.com/watch?v=..." --mock

# GitHub repo → review package
python -m app.main --github-url "https://github.com/owner/repo" --mock

# From candidate pool
python -m app.main --candidate-id "<candidate_id>" --mock

# Auto: discover → select → package → render in one go
python -m app.main --auto-close-loop --auto-mock-discovery --auto-video-mock

# Render video from an existing review package
python -m app.main --render-video "<content_id>"            # real TTS
python -m app.main --render-video "<content_id>" --video-mock  # offline ffmpeg silent fallback

# Re-run one stage on existing artifacts (analysis | score | risk | rewrite | quality)
python -m app.main --content-id "<content_id>" --rerun rewrite --mock

# Stop early at a stage (meta | transcript | clean | analysis | score | risk | rewrite | quality | all)
python -m app.main --url "..." --mock --stage analysis
```

Web console (browse review packages, run mock pipelines, source/feedback boards):
```bash
python -m app.web --host 127.0.0.1 --port 8000
# http://127.0.0.1:8000
```

Tests:
```bash
python -m pytest                 # full suite
python -m pytest tests/test_video_director.py            # one file
python -m pytest tests/test_video_director.py::test_name # one test
python -m compileall app tests   # syntax-only smoke check
```

Remotion (called by the Python renderer; rarely run directly):
```bash
cd video_engine/remotion
npm install
npm run preview                  # interactive Remotion preview
npm run render:douyin            # one-off render
```

## High-level architecture

The system is a **stage-based artifact pipeline**: each stage reads from and writes JSON/markdown files under `output/<content_id>/`, optionally records rows in Postgres, and the next stage reads those files. This means every stage is independently re-runnable (`--rerun <stage>`) and the filesystem is the source of truth — Postgres is a recorder, not a controller.

### Pipeline stages (`app/main.py` orchestrates)

```
URL/repo/candidate
  → meta (downloader.py / github_collector.py / youtube_analyzer.py / generic_candidate.py)
  → transcript (transcriber.py — faster-whisper or OpenAI Whisper; youtube_transcript.py)
  → clean (cleaner.py)
  → analysis (analyzer.py / github_analyzer.py — LLM with strict JSON schema)
  → score (scorer.py)
  → risk (risk_checker.py — LLM)
  → rewrite (rewriter.py — LLM produces chinese_script.md + title_options.md)
  → quality (quality_checker.py)
  → publish_review.json
```

After review, video production is a separate sub-pipeline driven by `--render-video`:

```
chinese_script.md
  → tts_engine.py (Volcengine / DashScope / Doubao / OpenAI TTS, with offline ffmpeg silent fallback)
  → audio_mastering.py + bgm_mixer.py
  → whisperx_aligner.py (word-level timing)
  → subtitle_engine.py (.srt / .ass, optional bilingual burn-in)
  → video_director.py (LLM-driven shot list, flow charts, evidence assets)
  → render_manifest.py (writes Remotion props JSON)
  → remotion_renderer.py (shells out to Node/Remotion)
  → final_video.mp4 (+ optional final_video_portrait.mp4)
  → visual_qc.py + video_self_review.py
```

After publishing, a feedback loop exists:

```
publish_board.py / platform_publish.py → publish_tasks.json (manual metric entry)
  → feedback_analysis.py → data/feedback_report.json
  → source_feedback.py → data/source_feedback_report.json (optional weight write-back to sources.yaml)
```

### Key cross-cutting modules

- **`config.py`** — single `Settings` dataclass loaded from `.env`. `mock` is the master switch; many modules check `settings.mock` to gate real network/disk calls.
- **`llm_client.py`** — wraps OpenAI/Anthropic/Google providers. Uses **strict JSON Schema** (`response_format`) for analysis/rewrite/risk because non-strict mode silently drops required fields. When adding a new LLM-output field, update both the prompt and the schema.
- **`artifact_writer.py`** — `ArtifactWriter` is the canonical way to read/write files under `output/<content_id>/` and `workspace/<content_id>/`. Don't `open()` paths directly — go through the writer so layout stays consistent.
- **`db.py`** — `Database` no-ops in mock mode and when `DATABASE_URL` is unset. Real mode uses `psycopg`. Schema lives in `migrations/001_init.sql`.
- **`pipeline_cache.py`** — per-stage incremental cache (TTS / audio mastering / word alignment / subtitle translation). `--no-cache` forces a clean re-render. The LLM flow-chart extractor (`video_director.py`) also uses its own cache keyed by content hash.
- **`source_manager.py` / `source_discovery.py` / `source_review.py`** — source-pool lifecycle. `data/sources.yaml` is the formal pool (read-only from the app's perspective). Discovery writes candidates to `data/candidate_sources.json`; only `approve_candidate` promotes one into `sources.yaml`.

### Mock vs real

`--mock` (or `CONTENT_ASSET_MOCK=true`) makes every external dependency optional: no DB, no yt-dlp, no ffmpeg, no API keys. Mock LLM returns canned outputs. Tests run in mock by default. When debugging real-mode failures, **never silently fall back to mock-shaped data** — surface the error.

### Video pipeline visual modes

`video_director.py` builds a shot list with three visual modes mixed roughly 60/30/10:

- **Pure Typography** (~60%) — text-only motion shots
- **Live Card with Assets** (~30%) — real screenshots/keyframes (browser chrome + Ken Burns) routed via `EvidenceShowcaseLandscape`
- **Infographic** (~10%) — LLM-extracted flow charts

`collect_visual_assets` reads keyframes from `youtube_assets.json` (collected by `youtube_asset_collector.py`) and Playwright-captured screenshots from `visual_evidence_hunt`. Routing happens in the Remotion dispatcher — `repo_*` visual types must reach the evidence component, not get dropped to typography (this has been a recurring bug).

### TTS provider notes

There is real history here: Volcengine TTS hit quota errors, BigTTS 2.0 V3 was evaluated against CosyVoice. **DashScope is the current preferred provider over Doubao** for cost and quota reasons. `tts_engine.py` writes `tts_status.json` with the provider used and the reason for any fallback to offline silence — read that file before assuming TTS "worked".

## Coding conventions specific to this repo

- **Match existing prose style.** User-facing strings, log messages, README sections, and most comments are in **Chinese**. Code identifiers and module-level docstrings stay in English. Don't translate one to the other unless asked.
- **Independent and direct in feedback** (per `.cursor/rules/objective-direct-feedback.mdc`): if a user's plan is wrong, say so and propose a better path. Don't agree to ship something you'd predict will flop on Chinese platforms. Safety/compliance reminders should be natural and contextual, not boilerplate disclaimers.
- **No revenue promises, no copy-this-template framing.** Even when a script reads dry, this is a non-negotiable product positioning, not a content-style preference.
- **Never break mock mode.** Adding an external dependency (network, binary, API key) must include a mock branch — many tests and the entire web console rely on mock running with zero external setup.
- **LLM JSON outputs use strict schema.** When changing analyzer/rewriter outputs, update both the prompt in `prompts/*.md` and the schema constants in `llm_client.py`. Non-strict prompts silently drop fields.
- **Failures must surface.** When metadata succeeds but audio fails, the system marks `metadata_ready_audio_failed` rather than pretending it worked. When subtitle burn-in fails, it falls back to no-subtitle video and records the reason in `render_status.json`. Preserve this pattern: degrade visibly, never silently.

## Environment notes

- Runs on WSL2 (Ubuntu) on Windows; `start-wsl-app.ps1` is the host launcher.
- Output and workspace directories are gitignored along with `*.mp4 *.mp3 *.wav *.srt`. Don't commit generated media.
- `.env` is gitignored; reference `.env.example` for the full key list (OpenAI, Anthropic, Google, YouTube, DeepSeek, Qwen, Volcengine ARK, Volcengine TTS).
