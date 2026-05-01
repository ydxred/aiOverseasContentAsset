from __future__ import annotations

import html
import importlib.util
import re
import shutil
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from .artifact_writer import ArtifactWriter
from .config import load_settings
from .downloader import check_download_dependencies, make_content_id
from .feedback_analysis import analyze_feedback, generate_feedback_report, load_feedback_report
from .github_auth import github_auth_status
from .github_collector import make_github_content_id
from .main import build_parser, run_pipeline
from .platform_accounts import init_platform_accounts, update_platform_account
from .platform_publish import PLATFORMS, generate_platform_publish_package
from .publish_adapter import dry_run_publish_task, dry_run_ready_publish_tasks, latest_attempts_by_task
from .publish_board import (
    METRIC_KEYS,
    PRIORITIES,
    STATUSES,
    filter_and_sort_publish_tasks,
    generate_publish_tasks_all,
    load_all_publish_tasks,
    update_publish_task,
)
from .publish_review import load_publish_review, update_publish_review
from .source_discovery import candidate_stats, discover_sources, load_candidate_pool
from .source_feedback import generate_source_feedback_report, load_source_feedback_report
from .source_manager import generate_discovery_links, group_sources_by_type, load_sources, source_stats
from .source_review import approve_candidate, archive_candidate, reject_candidate
from .youtube_analyzer import make_youtube_candidate_content_id

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


CONTENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
ARTIFACT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
DISPLAY_ARTIFACTS = [
    "auto_run_summary.json",
    "github_analysis.json",
    "github_meta.json",
    "youtube_candidate.json",
    "youtube_transcript.json",
    "readme.md",
    "readme_images.json",
    "snapshot_status.json",
    "review_notes.md",
    "chinese_script.md",
    "quality_check.json",
    "publish_review.json",
    "risk_report.json",
    "score.json",
    "analysis.json",
    "opportunity_engine.json",
    "media_job.json",
    "voice.wav",
    "voice.mp3",
    "subtitles.srt",
    "subtitles.zh.srt",
    "subtitles.en.srt",
    "subtitles.bilingual.srt",
    "subtitle_translation_status.json",
    "tts_status.json",
    "render_status.json",
    "final_video.mp4",
    "platform_publish_package.json",
    "platform_publish_package.md",
    "publish_tasks.json",
    "distribution.json",
    "feedback_template.json",
    "title_options.md",
    "meta.json",
    "transcript_clean.json",
    "transcript.json",
]


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7fb;
      --card: #ffffff;
      --text: #172033;
      --muted: #637083;
      --line: #dce1ea;
      --accent: #2854d8;
      --danger: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 20px 28px;
      background: #111827;
      color: #fff;
    }}
    header a {{ color: #dbeafe; margin-right: 16px; text-decoration: none; }}
    main {{ max-width: 1180px; margin: 24px auto; padding: 0 20px 40px; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 20px;
      margin-bottom: 18px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
    }}
    label {{ display: block; font-weight: 650; margin: 12px 0 6px; }}
    input[type="text"], input[type="number"], select, textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 11px 12px;
      font-size: 15px;
    }}
    textarea {{ min-height: 96px; resize: vertical; }}
    button, .button {{
      display: inline-block;
      border: 0;
      border-radius: 10px;
      background: var(--accent);
      color: #fff;
      padding: 10px 14px;
      margin-top: 14px;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
    }}
    button.secondary {{ background: #475569; }}
    button.danger {{ background: var(--danger); }}
    button:disabled {{ background: #94a3b8; cursor: not-allowed; }}
    .actions form {{ display: inline-block; margin-right: 8px; }}
    .actions input[type="text"] {{ width: 180px; margin-right: 6px; }}
    .muted {{ color: var(--muted); }}
    .error {{ color: var(--danger); white-space: pre-wrap; }}
    .warning {{ color: var(--danger); font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .item {{ padding: 12px; border: 1px solid var(--line); border-radius: 10px; background: #fbfcff; }}
    .artifact-list a {{ display: inline-block; margin: 0 10px 10px 0; }}
    .video-player {{ width: 100%; max-height: 720px; background: #020617; border-radius: 12px; }}
    .video-list {{ display: grid; gap: 18px; }}
    .video-card {{
      display: grid;
      grid-template-columns: minmax(260px, 360px) minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }}
    .video-card video {{ margin-top: 0; }}
    .video-main h2 {{ margin-top: 0; margin-bottom: 8px; }}
    .video-actions a, .video-actions form {{ display: inline-block; margin-right: 10px; }}
    .video-actions form button {{ margin-top: 8px; }}
    .platform-summary {{ margin-top: 14px; border-top: 1px solid var(--line); padding-top: 12px; }}
    .platform-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin-top: 12px; }}
    .platform-card textarea {{ min-height: 170px; font-size: 13px; line-height: 1.45; }}
    details {{ margin-top: 10px; }}
    summary {{ cursor: pointer; color: var(--accent); }}
    @media (max-width: 760px) {{
      .video-card {{ grid-template-columns: 1fr; }}
    }}
    .pill {{ display: inline-block; padding: 3px 8px; margin: 0 6px 6px 0; border-radius: 999px; background: #eef2ff; color: #3730a3; font-size: 13px; }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: #0f172a;
      color: #e5e7eb;
      padding: 16px;
      border-radius: 12px;
      overflow: auto;
      line-height: 1.5;
    }}
  </style>
</head>
<body>
  <header>
    <strong>Content Asset MVP</strong>
    <nav style="margin-top: 8px;">
      <a href="/">运行流水线</a>
      <a href="/github">GitHub 项目解读</a>
      <a href="/sources">源池/选题入口</a>
      <a href="/source-manager">源池管理</a>
      <a href="/source-discovery">候选源审核</a>
      <a href="/outputs">审核包列表</a>
      <a href="/videos">成片库</a>
      <a href="/publish-board">发布看板</a>
      <a href="/feedback-board">反馈看板</a>
      <a href="/platform-accounts">账号配置</a>
      <a href="/status">系统状态</a>
    </nav>
  </header>
  <main>{body}</main>
</body>
</html>"""


def _read_json(path: Path) -> dict[str, Any]:
    import json

    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _read_yaml(path: Path) -> dict[str, Any]:
    if yaml is None or not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _git_status_short(root_dir: Path) -> str:
    if shutil.which("git") is None:
        return "git 不可用"
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=root_dir,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"检查失败：{exc}"
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        return message.splitlines()[0] if message else "非 git 仓库"
    status = result.stdout.strip()
    return status if status else "clean"


def list_output_packages(output_dir: Path) -> list[Path]:
    if not output_dir.exists():
        return []
    return sorted((p for p in output_dir.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)


def list_rendered_videos(output_dir: Path) -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = []
    for package_dir in list_output_packages(output_dir):
        video_path = package_dir / "final_video.mp4"
        if not video_path.exists():
            continue
        meta = _read_json(package_dir / "meta.json")
        render_status = _read_json(package_dir / "render_status.json")
        tts_status = _read_json(package_dir / "tts_status.json")
        translation_status = _read_json(package_dir / "subtitle_translation_status.json")
        publish_review = _read_json(package_dir / "publish_review.json")
        videos.append(
            {
                "content_id": package_dir.name,
                "title": meta.get("title") or package_dir.name,
                "source_type": meta.get("source_type", "-"),
                "source_url": meta.get("source_url") or meta.get("webpage_url") or "",
                "size_bytes": video_path.stat().st_size,
                "tts_mode": tts_status.get("mode", "-"),
                "subtitle_mode": render_status.get("subtitle_mode", "-"),
                "translation_mode": translation_status.get("mode", "-"),
                "duration_seconds": render_status.get("duration_seconds", "-"),
                "publish_status": publish_review.get("status", "pending"),
                "platform_package_exists": (package_dir / "platform_publish_package.json").exists(),
            }
        )
    return videos


def safe_artifact_path(output_dir: Path, content_id: str, filename: str) -> Path:
    if not CONTENT_ID_RE.fullmatch(content_id):
        raise ValueError("Invalid content id")
    if not ARTIFACT_RE.fullmatch(filename):
        raise ValueError("Invalid artifact filename")
    package_dir = (output_dir / content_id).resolve()
    artifact_path = (package_dir / filename).resolve()
    if output_dir.resolve() not in artifact_path.parents:
        raise ValueError("Invalid artifact path")
    return artifact_path


def _summary_html(package_dir: Path) -> str:
    meta = _read_json(package_dir / "meta.json")
    if meta.get("source_type") == "github_repo":
        github_meta = _read_json(package_dir / "github_meta.json")
        analysis = _read_json(package_dir / "github_analysis.json")
        fields = [
            ("content_id", package_dir.name),
            ("repo", github_meta.get("full_name") or meta.get("title", "-")),
            ("source_url", meta.get("source_url", "-")),
            ("stars", github_meta.get("stars", "-")),
            ("forks", github_meta.get("forks", "-")),
            ("open_issues", github_meta.get("open_issues", "-")),
            ("core_topic", analysis.get("core_topic", "-")),
        ]
        cards = "".join(f"<div class='item'><div class='muted'>{_escape(k)}</div><strong>{_escape(v)}</strong></div>" for k, v in fields)
        return f"<div class='grid'>{cards}</div>"
    score = _read_json(package_dir / "score.json")
    risk = _read_json(package_dir / "risk_report.json")
    quality = _read_json(package_dir / "quality_check.json")
    transcript_status = _read_json(package_dir / "youtube_transcript.json")
    fields = [
        ("content_id", package_dir.name),
        ("title", meta.get("title", "-")),
        ("source_url", meta.get("source_url", "-")),
        ("transcript", transcript_status.get("status", "-")),
        ("score", score.get("total_score", "-")),
        ("decision", score.get("decision", "-")),
        ("risk_level", risk.get("risk_level", "-")),
        ("quality_score", quality.get("quality_score", "-")),
    ]
    cards = "".join(f"<div class='item'><div class='muted'>{_escape(k)}</div><strong>{_escape(v)}</strong></div>" for k, v in fields)
    return f"<div class='grid'>{cards}</div>"


class WebHandler(BaseHTTPRequestHandler):
    server: "ContentAssetWebServer"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self._send_html(self._home())
                return
            if parsed.path == "/github":
                self._send_html(self._github())
                return
            if parsed.path == "/outputs":
                self._send_html(self._outputs())
                return
            if parsed.path == "/videos":
                self._send_html(self._videos())
                return
            if parsed.path == "/publish-board":
                self._send_html(self._publish_board(parse_qs(parsed.query)))
                return
            if parsed.path == "/feedback-board":
                self._send_html(self._feedback_board())
                return
            if parsed.path == "/platform-accounts":
                self._send_html(self._platform_accounts())
                return
            if parsed.path == "/sources":
                self._send_html(self._sources())
                return
            if parsed.path == "/source-manager":
                self._send_html(self._source_manager())
                return
            if parsed.path == "/source-discovery":
                self._send_html(self._source_discovery())
                return
            if parsed.path == "/status":
                self._send_html(self._status())
                return
            if parsed.path.startswith("/outputs/"):
                content_id = unquote(parsed.path.removeprefix("/outputs/")).strip("/")
                self._send_html(self._output_detail(content_id))
                return
            if parsed.path.startswith("/artifact/"):
                parts = parsed.path.split("/", 3)
                if len(parts) != 4:
                    raise ValueError("Artifact path is incomplete")
                content_id = unquote(parts[2])
                filename = unquote(parts[3])
                artifact_html = self._artifact(content_id, filename)
                if artifact_html is not None:
                    self._send_html(artifact_html)
                return
            self._send_html(_layout("Not Found", "<div class='card'>页面不存在。</div>"), HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_html(_layout("Error", f"<div class='card error'>{_escape(exc)}</div>"), HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        try:
            if parsed.path == "/run":
                self._run(form)
                return
            if parsed.path == "/rerun":
                self._rerun(form)
                return
            if parsed.path == "/render-video":
                self._render_video(form)
                return
            if parsed.path == "/publish-review":
                self._publish_review(form)
                return
            if parsed.path == "/platform-publish-package":
                self._platform_publish_package(form)
                return
            if parsed.path == "/publish-board/refresh":
                self._publish_board_refresh()
                return
            if parsed.path == "/feedback-board/refresh":
                self._feedback_board_refresh()
                return
            if parsed.path == "/feedback-board/source-feedback":
                self._source_feedback_refresh()
                return
            if parsed.path == "/publish-task":
                self._publish_task(form)
                return
            if parsed.path == "/publish-dry-run":
                self._publish_dry_run(form)
                return
            if parsed.path == "/publish-dry-run-ready":
                self._publish_dry_run_ready()
                return
            if parsed.path == "/platform-accounts":
                self._platform_accounts_update(form)
                return
            if parsed.path == "/discover-sources":
                self._discover_sources(form)
                return
            if parsed.path == "/auto-close-loop":
                self._auto_close_loop(form)
                return
            if parsed.path == "/candidate/approve":
                self._candidate_approve(form)
                return
            if parsed.path == "/candidate/reject":
                self._candidate_reject(form)
                return
            if parsed.path == "/candidate/archive":
                self._candidate_archive(form)
                return
            if parsed.path == "/candidate/package":
                self._candidate_package(form)
                return
            self._send_html(_layout("Not Found", "<div class='card'>页面不存在。</div>"), HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_html(_layout("Run Failed", f"<div class='card'><h2>运行失败</h2><p class='error'>{_escape(exc)}</p></div>"), HTTPStatus.BAD_REQUEST)

    def _home(self) -> str:
        body = """<div class="card">
  <h1>运行内容资产流水线</h1>
  <p class="muted">输入一个海外内容 URL，先用 mock 模式跑通审核包；关闭 mock 后会走真实下载、转写和模型接口。</p>
  <p class="muted">真实模式需要完成 .env、PostgreSQL、yt-dlp、ffmpeg 和 API key 配置；可以先打开“系统状态”检查本机依赖。</p>
  <form method="post" action="/auto-close-loop">
    <input type="hidden" name="mock_discovery" value="1">
    <button type="submit">一键跑完整闭环（mock discovery）</button>
  </form>
  <form method="post" action="/run">
    <label>内容 URL</label>
    <input type="text" name="url" placeholder="https://youtube.com/watch?v=xxx">
    <label>GitHub repo URL（可选，填写后走 AI 项目解读链路）</label>
    <input type="text" name="github_url" placeholder="https://github.com/owner/repo">
    <label>运行到阶段</label>
    <select name="stage">
      <option value="all">完整流水线</option>
      <option value="analysis">只跑到分析</option>
      <option value="score">只跑到评分</option>
      <option value="risk">只跑到风控</option>
      <option value="rewrite">只跑到脚本</option>
      <option value="quality">跑到质检</option>
    </select>
    <label><input type="checkbox" name="mock" checked> 使用 mock 模式</label>
    <button type="submit">开始生成审核包</button>
  </form>
</div>"""
        return _layout("运行流水线", body)

    def _github(self) -> str:
        body = """<div class="card">
  <h1>GitHub AI 项目解读</h1>
  <p class="muted">输入公开 GitHub 仓库 URL，系统会抓取 metadata、README、README 图片素材，并生成中文项目解读审核包。截图能力为可选项，没有 Playwright 时会自动跳过。</p>
  <form method="post" action="/run">
    <label>GitHub repo URL</label>
    <input type="text" name="github_url" placeholder="https://github.com/owner/repo" required>
    <label><input type="checkbox" name="mock" checked> 使用 mock 模式</label>
    <button type="submit">生成 GitHub 解读审核包</button>
  </form>
</div>"""
        return _layout("GitHub 项目解读", body)

    def _status(self) -> str:
        settings = load_settings(force_mock=True)
        deps = check_download_dependencies()
        fields = [
            ("mock 默认状态", "开启，Web 表单默认勾选 mock；取消勾选才会走真实链路"),
            ("DATABASE_URL", "已配置" if settings.database_url else "未配置"),
            ("psql", "可用" if shutil.which("psql") else "不可用"),
            ("yt-dlp", "可用" if deps["yt-dlp"] else "不可用"),
            ("ffmpeg", "可用" if deps["ffmpeg"] else "不可用"),
            ("Playwright 截图", "可用" if importlib.util.find_spec("playwright") else "未安装；GitHub 链路会跳过截图"),
            ("GitHub 认证", github_auth_status()),
            ("OpenAI API key", "已配置" if settings.openai_api_key else "未配置"),
            ("Claude API key", "已配置" if settings.anthropic_api_key else "未配置"),
            ("Gemini API key", "已配置" if settings.google_api_key else "未配置"),
            ("YouTube Data API key", "已配置" if settings.youtube_api_key else "未配置"),
            ("DeepSeek API key", "已配置" if settings.deepseek_api_key else "未配置"),
            ("Qwen API key", "已配置" if settings.qwen_api_key else "未配置"),
            ("Ark API key", "已配置" if settings.ark_api_key else "未配置"),
            ("Ark model", settings.ark_model or "未配置"),
            ("git status --short", _git_status_short(settings.root_dir)),
            ("输出目录", str(settings.output_dir)),
            ("最近审核包数量", str(len(list_output_packages(settings.output_dir)))),
        ]
        cards = "".join(
            f"<div class='item'><div class='muted'>{_escape(name)}</div><strong>{_escape(value)}</strong></div>"
            for name, value in fields
        )
        body = f"""<div class="card">
  <h1>系统状态</h1>
  <p class="muted">这里仅检查本机配置是否具备进入真实链路的条件；mock 模式不依赖数据库、API key 或外部二进制。</p>
  <div class="grid">{cards}</div>
</div>"""
        return _layout("系统状态", body)

    def _sources(self) -> str:
        data_dir = self.server.root_dir / "data"
        topic_data = _read_yaml(data_dir / "topic_clusters.yaml")
        sources_data = _read_yaml(data_dir / "sources.yaml")
        sources = load_sources(data_dir / "sources.yaml")
        queries = sources_data.get("search_queries", [])
        clusters = topic_data.get("topic_clusters", [])

        source_items = []
        for source in sources:
            name = source.get("name", "Untitled")
            url = source.get("url", "#")
            category = source.get("category", "-")
            note = source.get("note", "")
            trust = source.get("trust_score", "-")
            source_items.append(
                "<div class='item'>"
                f"<a href='{_escape(url)}' target='_blank' rel='noreferrer'><strong>{_escape(name)}</strong></a>"
                f"<div class='muted'>{_escape(category)} · trust { _escape(trust) }</div>"
                f"<p>{_escape(note)}</p>"
                "</div>"
            )

        query_items = []
        for item in queries:
            if not isinstance(item, dict):
                continue
            query = item.get("query", "")
            if not query:
                continue
            youtube_search = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp=CAI%253D"
            google_video_search = f"https://www.google.com/search?q={quote_plus(query + ' site:youtube.com/watch')}"
            query_items.append(
                "<div class='item'>"
                f"<strong>{_escape(query)}</strong>"
                f"<p class='muted'>{_escape(item.get('reason', ''))}</p>"
                f"<a href='{_escape(youtube_search)}' target='_blank' rel='noreferrer'>YouTube 英文搜索</a> "
                f"<a href='{_escape(google_video_search)}' target='_blank' rel='noreferrer'>Google 视频搜索</a>"
                "</div>"
            )

        github_queries = [
            "AI agent framework language:Python stars:>1000",
            "LLM developer tools stars:>500",
            "AI coding assistant stars:>500",
        ]
        github_items = []
        for query in github_queries:
            search_url = f"https://github.com/search?q={quote_plus(query)}&type=repositories&s=updated&o=desc"
            github_items.append(
                "<div class='item'>"
                f"<strong>{_escape(query)}</strong>"
                "<p class='muted'>按最近更新寻找可解读的海外 AI 开源项目。</p>"
                f"<a href='{_escape(search_url)}' target='_blank' rel='noreferrer'>GitHub 搜索</a>"
                "</div>"
            )

        cluster_items = []
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            keywords = cluster.get("search_keywords", []) or []
            keyword_links = []
            for keyword in keywords:
                url = f"https://www.youtube.com/results?search_query={quote_plus(str(keyword))}&sp=CAI%253D"
                keyword_links.append(f"<a href='{_escape(url)}' target='_blank' rel='noreferrer'>{_escape(keyword)}</a>")
            cluster_items.append(
                "<div class='item'>"
                f"<strong>{_escape(cluster.get('name', cluster.get('id', '-')))}</strong>"
                f"<p class='muted'>{_escape(cluster.get('description', ''))}</p>"
                + " ".join(keyword_links)
                + "</div>"
            )

        body = f"""<div class="card">
  <h1>源池/选题入口</h1>
  <p class="muted">不要从 YouTube 首页找。直接从这些英文白名单源和英文搜索词进入，可以绕开中文推荐流。</p>
  <p class="muted">使用建议：先点英文搜索词，按上传日期筛最近内容；看到合适视频后复制 URL 回到“运行流水线”。</p>
  <p><a class="button" href="/source-manager">打开源池管理视图</a></p>
</div>
<div class="card">
  <h2>GitHub AI 项目入口</h2>
  <div class="grid">{''.join(github_items)}</div>
</div>
<div class="card">
  <h2>英文搜索词</h2>
  <div class="grid">{''.join(query_items)}</div>
</div>
<div class="card">
  <h2>主题簇</h2>
  <div class="grid">{''.join(cluster_items)}</div>
</div>
<div class="card">
  <h2>白名单源</h2>
  <div class="grid">{''.join(source_items)}</div>
</div>"""
        return _layout("源池/选题入口", body)

    def _source_manager(self) -> str:
        sources = load_sources(self.server.root_dir / "data" / "sources.yaml")
        stats = source_stats(sources)
        stats_cards = [
            ("源总数", stats["total_sources"]),
            ("active 源", stats["active_sources"]),
            ("高信任源", stats["high_trust_sources"]),
            ("类型数", len(stats["by_type"])),
        ]
        stat_html = "".join(
            f"<div class='item'><div class='muted'>{_escape(label)}</div><strong>{_escape(value)}</strong></div>"
            for label, value in stats_cards
        )
        type_html = "".join(
            f"<span class='pill'>{_escape(source_type)}: {_escape(count)}</span>"
            for source_type, count in stats["by_type"].items()
        )
        groups = []
        for source_type, items in group_sources_by_type(sources).items():
            source_items = []
            for source in items:
                links = generate_discovery_links(source)
                link_html = " ".join(
                    f"<a href='{_escape(link['url'])}' target='_blank' rel='noreferrer'>{_escape(link['label'])}</a>"
                    for link in links
                )
                keyword_html = " ".join(f"<span class='pill'>{_escape(keyword)}</span>" for keyword in source.get("watch_keywords", []))
                source_items.append(
                    "<div class='item'>"
                    f"<strong>{_escape(source.get('name', '-'))}</strong>"
                    f"<div class='muted'>{_escape(source.get('category', '-'))} · trust {_escape(source.get('trust_score', '-'))} · priority {_escape(source.get('priority', '-'))} · {_escape(source.get('status', '-'))}</div>"
                    f"<p>{_escape(source.get('note', ''))}</p>"
                    f"<p>{keyword_html}</p>"
                    f"<p>{link_html}</p>"
                    f"<p class='muted'>{_escape(source.get('discovery_method', ''))}</p>"
                    "</div>"
                )
            groups.append(
                "<div class='card'>"
                f"<h2>{_escape(source_type)}</h2>"
                f"<div class='grid'>{''.join(source_items)}</div>"
                "</div>"
            )
        body = f"""<div class="card">
  <h1>源池管理</h1>
  <p class="muted">只读管理视图，用来集中查看人物源、项目源、社区源和关键词发现入口。编辑源池请修改 data/sources.yaml。</p>
  <div class="grid">{stat_html}</div>
  <p>{type_html}</p>
</div>
{''.join(groups)}"""
        return _layout("源池管理", body)

    def _source_discovery(self) -> str:
        pool = load_candidate_pool(self.server.root_dir / "data" / "candidate_sources.json")
        candidates = [item for item in pool.get("candidates", []) if isinstance(item, dict)]
        stats = candidate_stats(candidates)
        stat_cards = [
            ("候选源总数", stats["total_candidates"]),
            ("approve_candidate", stats["by_decision"].get("approve_candidate", 0)),
            ("review", stats["by_decision"].get("review", 0)),
            ("reject", stats["by_decision"].get("reject", 0)),
        ]
        stat_html = "".join(
            f"<div class='item'><div class='muted'>{_escape(label)}</div><strong>{_escape(value)}</strong></div>"
            for label, value in stat_cards
        )
        status_html = "".join(
            f"<span class='pill'>{_escape(status)}: {_escape(count)}</span>"
            for status, count in stats["by_status"].items()
        )

        groups: list[str] = []
        for decision in ("approve_candidate", "review", "reject"):
            items = [item for item in candidates if item.get("decision") == decision]
            if not items:
                continue
            card_items = []
            for item in sorted(items, key=lambda candidate: int(candidate.get("score", 0)), reverse=True):
                signals = item.get("signals", {})
                if isinstance(signals, dict):
                    signal_html = " ".join(
                        f"<span class='pill'>{_escape(key)}: {_escape(value)}</span>"
                        for key, value in signals.items()
                        if key != "score_reasons"
                    )
                    score_reasons = signals.get("score_reasons", [])
                else:
                    signal_html = ""
                    score_reasons = []
                reason_html = " ".join(f"<span class='pill'>{_escape(reason)}</span>" for reason in score_reasons)
                discovered_from = item.get("discovered_from", {})
                if not isinstance(discovered_from, dict):
                    discovered_from = {}
                actions_html = _candidate_actions_html(item, self.server.output_dir)
                card_items.append(
                    "<div class='item'>"
                    f"<a href='{_escape(item.get('url', '#'))}' target='_blank' rel='noreferrer'><strong>{_escape(item.get('name', '-'))}</strong></a>"
                    f"<div class='muted'>score {_escape(item.get('score', 0))} · {_escape(item.get('status', '-'))} · {_escape(item.get('source_type', '-'))}</div>"
                    f"<p>{_escape(item.get('reason', ''))}</p>"
                    f"<p class='muted'>review reason: {_escape(item.get('review_reason', '-'))}</p>"
                    f"<p class='muted'>from {_escape(discovered_from.get('name', item.get('source_id', '-')))} · {_escape(item.get('discovery_method', ''))}</p>"
                    f"<p>{signal_html}</p>"
                    f"<p>{reason_html}</p>"
                    f"{actions_html}"
                    "</div>"
                )
            groups.append(
                "<div class='card'>"
                f"<h2>{_escape(decision)}</h2>"
                f"<div class='grid'>{''.join(card_items)}</div>"
                "</div>"
            )

        empty_html = "<div class='card'><p class='muted'>候选池为空。可以先运行 mock discovery。</p></div>" if not candidates else ""
        body = f"""<div class="card">
  <h1>候选源审核</h1>
  <p class="muted">自动发现结果只进入 candidate_sources.json 候选池，不会直接写入正式 sources.yaml。这里用于人工查看、筛选和后续确认。</p>
  <form method="post" action="/discover-sources">
    <button type="submit">运行真实 discovery</button>
  </form>
  <form method="post" action="/discover-sources">
    <input type="hidden" name="mock" value="1">
    <button class="secondary" type="submit">运行 mock discovery</button>
  </form>
  <form method="post" action="/auto-close-loop">
    <button type="submit">一键完整闭环（真实 discovery）</button>
  </form>
  <form method="post" action="/auto-close-loop">
    <input type="hidden" name="mock_discovery" value="1">
    <button class="secondary" type="submit">一键完整闭环（mock discovery）</button>
  </form>
  <div class="grid">{stat_html}</div>
  <p>{status_html}</p>
</div>
{empty_html}
{''.join(groups)}"""
        return _layout("候选源审核", body)

    def _outputs(self) -> str:
        packages = list_output_packages(self.server.output_dir)
        if not packages:
            body = "<div class='card'><h1>审核包列表</h1><p class='muted'>还没有生成审核包。</p></div>"
            return _layout("审核包列表", body)
        items = []
        for package_dir in packages:
            meta = _read_json(package_dir / "meta.json")
            title = meta.get("title") or package_dir.name
            items.append(
                "<div class='item'>"
                f"<a href='/outputs/{_escape(package_dir.name)}'><strong>{_escape(title)}</strong></a>"
                f"<div class='muted'>{_escape(package_dir.name)}</div>"
                "</div>"
            )
        body = f"<div class='card'><h1>审核包列表</h1><div class='grid'>{''.join(items)}</div></div>"
        return _layout("审核包列表", body)

    def _videos(self) -> str:
        videos = list_rendered_videos(self.server.output_dir)
        if not videos:
            body = "<div class='card'><h1>成片库</h1><p class='muted'>还没有生成 final_video.mp4。</p><p><a class='button' href='/publish-board'>打开发布看板</a></p></div>"
            return _layout("成片库", body)
        items = []
        for video in videos:
            content_id = str(video["content_id"])
            source_url = str(video.get("source_url") or "")
            source_link = (
                f"<a href='{_escape(source_url)}' target='_blank' rel='noreferrer'>原始来源</a>"
                if source_url
                else "<span class='muted'>无原始来源</span>"
            )
            duration = video.get("duration_seconds", "-")
            if isinstance(duration, (int, float)):
                duration = f"{duration:.1f}s"
            size_mb = float(video.get("size_bytes", 0)) / 1024 / 1024
            package_dir = self.server.output_dir / content_id
            platform_package = _read_json(package_dir / "platform_publish_package.json")
            platform_ready = bool(platform_package)
            platform_assets_html = ""
            if platform_ready:
                platform_assets_html = (
                    "<details class='platform-summary'><summary><strong>展开五平台发布文案</strong>（直接复制粘贴）</summary>"
                    f"{_platform_assets_grid(platform_package)}"
                    "</details>"
                )
            items.append(
                "<div class='card video-card'>"
                "<div class='video-preview'>"
                f"<video class='video-player' controls preload='metadata' src='/artifact/{_escape(content_id)}/final_video.mp4'></video>"
                "</div>"
                "<div class='video-main'>"
                f"<h2>{_escape(video.get('title', content_id))}</h2>"
                f"<div class='muted'>{_escape(content_id)} · {_escape(video.get('source_type', '-'))} · {size_mb:.1f} MB · {duration}</div>"
                "<p>"
                f"<span class='pill'>TTS: {_escape(video.get('tts_mode', '-'))}</span>"
                f"<span class='pill'>字幕: {_escape(video.get('subtitle_mode', '-'))}</span>"
                f"<span class='pill'>翻译: {_escape(video.get('translation_mode', '-'))}</span>"
                f"<span class='pill'>审核: {_escape(video.get('publish_status', 'pending'))}</span>"
                f"<span class='pill'>平台发布包: {_escape('已生成' if platform_ready else '未生成')}</span>"
                "</p>"
                "<div class='video-actions'>"
                f"{source_link}"
                f"<a href='/outputs/{_escape(content_id)}'>查看审核包</a>"
                f"<a href='/artifact/{_escape(content_id)}/final_video.mp4'>打开视频文件</a>"
                "<a href='/publish-board'>发布看板</a>"
                f"{_platform_package_form(content_id, '/videos', '刷新发布包' if platform_ready else '生成发布包')}"
                "</div>"
                f"{platform_assets_html}"
                "</div>"
                "</div>"
            )
        body = f"""<div class="card">
  <h1>成片库</h1>
  <p class="muted">这里按审核包归档所有成片。左侧预览视频，右侧查看状态和发布资产；五平台长文案默认折叠，展开后可直接复制粘贴。</p>
</div>
<div class="video-list">{''.join(items)}</div>"""
        return _layout("成片库", body)

    def _platform_accounts(self) -> str:
        accounts_path = self.server.data_dir / "platform_accounts.yaml"
        accounts = init_platform_accounts(accounts_path)
        cards = []
        for account in accounts:
            platform = str(account.get("platform") or "")
            publish_url = str(account.get("publish_url") or "")
            publish_link = (
                f"<a href='{_escape(publish_url)}' target='_blank' rel='noreferrer'>打开发布入口</a>"
                if publish_url
                else "<span class='muted'>未配置发布入口</span>"
            )
            cards.append(
                f"""<div class="card">
  <h2>{_escape(account.get("platform_name", platform))}</h2>
  <p>
    <span class="pill">platform: {_escape(platform)}</span>
    <span class="pill">enabled: {_escape(account.get("enabled"))}</span>
    <span class="pill">auto_publish_enabled: {_escape(account.get("auto_publish_enabled"))}</span>
  </p>
  <p><strong>账号：</strong>{_escape(account.get("display_name", ""))} · <code>{_escape(account.get("account_id", ""))}</code> · {publish_link}</p>
  <p class="muted">登录方式：{_escape(account.get("login_method", ""))}；优先级：{_escape(account.get("default_priority", ""))}</p>
  <p class="muted">{_escape(account.get("notes", ""))}</p>
  <form method="post" action="/platform-accounts">
    <input type="hidden" name="platform" value="{_escape(platform)}">
    <div class="grid">
      <div>
        <label>account_id</label>
        <input type="text" name="account_id" value="{_escape(account.get("account_id", ""))}">
      </div>
      <div>
        <label>display_name</label>
        <input type="text" name="display_name" value="{_escape(account.get("display_name", ""))}">
      </div>
      <div>
        <label>login_method</label>
        <input type="text" name="login_method" value="{_escape(account.get("login_method", ""))}">
      </div>
      <div>
        <label>default_priority</label>
        <input type="number" min="1" name="default_priority" value="{_escape(account.get("default_priority", 99))}">
      </div>
    </div>
    <label>publish_url</label>
    <input type="text" name="publish_url" value="{_escape(account.get("publish_url", ""))}">
    <label>notes</label>
    <textarea name="notes">{_escape(account.get("notes", ""))}</textarea>
    <label><input type="checkbox" name="enabled" {_checked(account.get("enabled"))}> 启用该平台账号</label>
    <label><input type="checkbox" name="auto_publish_enabled" {_checked(account.get("auto_publish_enabled"))}> 允许后续真实自动发布使用该账号</label>
    <button type="submit">保存非敏感配置</button>
  </form>
</div>"""
            )
        body = f"""<div class="card">
  <h1>平台账号配置中心</h1>
  <p class="muted">这里保存五个平台的非敏感发布配置：账号标识、显示名、启用状态、发布入口和备注。不要填写密码、cookie、token 或 API key。</p>
  <p class="muted">Dry-run 只要求账号 enabled；真正自动发布的适配器后续还需要显式开启 auto_publish_enabled，并接入人工确认或平台授权。</p>
  <p><code>{_escape(accounts_path)}</code></p>
</div>
{''.join(cards)}"""
        return _layout("账号配置", body)

    def _publish_board(self, query: dict[str, list[str]] | None = None) -> str:
        query = query or {}
        tasks = load_all_publish_tasks(self.server.output_dir)
        latest_attempts = latest_attempts_by_task(self.server.output_dir)
        selected_status = _form_value(query, "status", "")
        selected_platform = _form_value(query, "platform", "")
        selected_sort = _form_value(query, "sort", "recommended")
        status_counts = {status: 0 for status in STATUSES}
        platform_counts = {platform: 0 for platform in PLATFORMS}
        for task in tasks:
            status = str(task.get("status") or "pending_review")
            platform = str(task.get("platform") or "")
            if status in status_counts:
                status_counts[status] += 1
            if platform in platform_counts:
                platform_counts[platform] += 1
        status_summary = "".join(f"<span class='pill'>{_escape(status)}: {_escape(count)}</span>" for status, count in status_counts.items())
        platform_summary = "".join(
            f"<span class='pill'>{_escape(PLATFORMS[platform]['platform_name'])}: {_escape(platform_counts[platform])}</span>"
            for platform in PLATFORMS
        )
        visible_tasks = filter_and_sort_publish_tasks(
            tasks,
            status=selected_status,
            platform=selected_platform,
            sort_by=selected_sort,
        )
        task_cards = "".join(_publish_task_card(task, latest_attempts.get(str(task.get("task_id") or ""))) for task in visible_tasks)
        status_options = '<option value="">全部状态</option>' + "".join(
            _select_option(status, status, selected_status) for status in STATUSES
        )
        platform_options = '<option value="">全部平台</option>' + "".join(
            _select_option(platform, PLATFORMS[platform]["platform_name"], selected_platform) for platform in PLATFORMS
        )
        sort_options = "".join(
            _select_option(value, label, selected_sort)
            for value, label in [
                ("recommended", "运营优先级：状态 -> 优先级 -> 排期 -> 平台"),
                ("scheduled_at", "排期时间优先"),
                ("priority", "优先级优先"),
                ("platform", "平台分组"),
                ("performance", "表现数据优先"),
            ]
        )
        empty_html = "<p class='muted'>还没有 publish_tasks.json。请先刷新全部发布任务，系统会基于已有 platform_publish_package.json 补齐每个平台的发布任务。</p>"
        body = f"""<div class="card">
  <h1>发布审核与排期中心</h1>
  <p class="muted">每个成片的每个平台是一条独立任务；这里只做人工审核、排期、发布记录和指标录入，不会自动发布。</p>
  <form method="post" action="/publish-board/refresh">
    <button type="submit">刷新全部发布任务</button>
  </form>
  <form method="post" action="/publish-dry-run-ready">
    <button class="secondary" type="submit">Dry-run 所有 ready/scheduled</button>
  </form>
  <p>{status_summary}</p>
  <p>{platform_summary}</p>
</div>
<div class="card">
  <h2>排序与筛选</h2>
  <form method="get" action="/publish-board">
    <div class="grid">
      <label>状态筛选
        <select name="status">{status_options}</select>
      </label>
      <label>平台筛选
        <select name="platform">{platform_options}</select>
      </label>
      <label>排序方式
        <select name="sort">{sort_options}</select>
      </label>
    </div>
    <button type="submit">应用排序/筛选</button>
    <a class="button secondary" href="/publish-board">重置</a>
  </form>
  <p class="muted">当前显示 {len(visible_tasks)} / {len(tasks)} 条任务。默认排序把最该处理的任务排在前面：ready、scheduled、pending_review 优先，再看 urgent/high 优先级和排期时间。</p>
</div>
<div class="video-list">{task_cards or empty_html}</div>"""
        return _layout("发布看板", body)

    def _feedback_board(self) -> str:
        report_path = self.server.data_dir / "feedback_report.json"
        report = load_feedback_report(report_path)
        source_feedback_path = self.server.data_dir / "source_feedback_report.json"
        source_feedback = load_source_feedback_report(source_feedback_path)
        if not report:
            report = analyze_feedback(load_all_publish_tasks(self.server.output_dir))
            report["report_path"] = str(report_path)
        best_platform = _first_label(report.get("best_platforms"), "platform_name")
        best_task = _first_label(report.get("best_tasks"), "task_id")
        fields = [
            ("总任务数", report.get("total_tasks", 0)),
            ("有数据任务数", report.get("data_tasks", 0)),
            ("最佳平台", best_platform or "暂无"),
            ("最佳视频", best_task or "暂无"),
        ]
        stat_html = "".join(
            f"<div class='item'><div class='muted'>{_escape(label)}</div><strong>{_escape(value)}</strong></div>"
            for label, value in fields
        )
        no_data_html = ""
        if int(report.get("data_tasks") or 0) == 0:
            no_data_html = """<div class="card">
  <h2>还没有可分析的数据</h2>
  <p class="muted">请先打开发布看板，刷新发布任务，并在已发布任务中录入 views、likes、comments、favorites、shares 等表现数据。录入后回到这里点击“刷新反馈报告”。</p>
  <p><a class="button" href="/publish-board">去发布看板录入数据</a></p>
</div>"""
        body = f"""<div class="card">
  <h1>平台表现评分与反馈看板</h1>
  <p class="muted">基于 publish_tasks.json 中的发布指标计算平台表现分，并给出内容复盘、平台策略和源池权重建议。报告文件：<code>{_escape(report.get("report_path", report_path))}</code></p>
  <form method="post" action="/feedback-board/refresh">
    <button type="submit">刷新反馈报告</button>
  </form>
  <form method="post" action="/feedback-board/source-feedback">
    <button class="secondary" type="submit">生成源池反馈建议</button>
  </form>
  <div class="grid">{stat_html}</div>
  <p>{_feedback_notes_html(report.get("notes", []))}</p>
</div>
{no_data_html}
<div class="card">
  <h2>最佳平台</h2>
  {_feedback_platforms_html(report.get("best_platforms", []))}
</div>
<div class="card">
  <h2>最佳视频</h2>
  {_feedback_tasks_html(report.get("best_tasks", []))}
</div>
<div class="card">
  <h2>弱表现任务</h2>
  {_feedback_tasks_html(report.get("weak_tasks", []))}
</div>
<div class="card">
  <h2>内容洞察</h2>
  {_feedback_list_html(report.get("content_insights", []))}
</div>
<div class="card">
  <h2>平台洞察</h2>
  {_feedback_list_html(report.get("platform_insights", []))}
</div>
<div class="card">
  <h2>源池权重建议</h2>
  {_feedback_source_suggestions_html(report.get("source_weight_suggestions", []))}
</div>
<div class="card">
  <h2>源池反馈建议</h2>
  <p class="muted">默认只生成 dry-run 建议报告，不会自动修改 sources.yaml；数据不足时会标记 insufficient_data 或 keep。</p>
  <p class="muted">报告文件：<code>{_escape(source_feedback.get("report_path", source_feedback_path))}</code></p>
  {_source_feedback_suggestions_html(source_feedback.get("source_suggestions", []))}
</div>"""
        return _layout("反馈看板", body)

    def _output_detail(self, content_id: str) -> str:
        if not CONTENT_ID_RE.fullmatch(content_id):
            raise ValueError("Invalid content id")
        package_dir = self.server.output_dir / content_id
        if not package_dir.exists():
            raise FileNotFoundError(f"Output package not found: {content_id}")
        artifact_links = []
        for filename in DISPLAY_ARTIFACTS:
            if (package_dir / filename).exists():
                artifact_links.append(f"<a href='/artifact/{_escape(content_id)}/{_escape(filename)}'>{_escape(filename)}</a>")
        image_report = _read_json(package_dir / "readme_images.json")
        image_items = []
        images = image_report.get("images", [])
        if isinstance(images, list):
            for image in images:
                if not isinstance(image, dict):
                    continue
                label = image.get("workspace_path") or image.get("source_url")
                if label:
                    image_items.append(f"<li>{_escape(label)} · {_escape(image.get('status', '-'))}</li>")
        images_html = f"<div class='card'><h2>README 图片素材</h2><ul>{''.join(image_items)}</ul></div>" if image_items else ""
        publish_review_html = _publish_review_html(package_dir, content_id)
        platform_publish_html = _platform_publish_html(package_dir, content_id)
        video_html = ""
        if (package_dir / "final_video.mp4").exists():
            video_html = f"""<div class="card video-card">
  <h2>成片预览</h2>
  <video class="video-player" controls preload="metadata" src="/artifact/{_escape(content_id)}/final_video.mp4"></video>
  <p><a href="/artifact/{_escape(content_id)}/final_video.mp4">打开视频文件</a> · <a href="/videos">返回成片库</a></p>
</div>"""
        body = f"""<div class="card">
  <h1>{_escape(content_id)}</h1>
  {_summary_html(package_dir)}
</div>
<div class="card artifact-list">
  <h2>Artifacts</h2>
  {''.join(artifact_links)}
</div>
{images_html}
{video_html}
{publish_review_html}
{platform_publish_html}
<div class="card">
  <h2>生成视频</h2>
  <p class="muted">从 chinese_script.md 的“口播稿”生成真实中文配音、中文字幕、英文字幕、双语字幕和 final_video.mp4；双语字幕默认烧录进视频。</p>
  <p class="muted">不勾选“使用离线 TTS fallback”时会优先调用 OpenAI TTS；如果接口、网络或配额失败，会自动降级为静音音频并在 tts_status.json 记录原因。</p>
  <form method="post" action="/render-video">
    <input type="hidden" name="content_id" value="{_escape(content_id)}">
    <label><input type="checkbox" name="video_mock"> 使用离线 TTS fallback</label>
    <button type="submit">生成视频</button>
  </form>
</div>
<div class="card">
  <h2>重跑阶段</h2>
  <form method="post" action="/rerun">
    <input type="hidden" name="content_id" value="{_escape(content_id)}">
    <label>阶段</label>
    <select name="stage">
      <option value="analysis">analysis</option>
      <option value="score">score</option>
      <option value="risk">risk</option>
      <option value="rewrite">rewrite</option>
      <option value="quality">quality</option>
    </select>
    <label><input type="checkbox" name="mock" checked> 使用 mock 模式</label>
    <button type="submit">重跑</button>
  </form>
</div>"""
        return _layout(content_id, body)

    def _artifact(self, content_id: str, filename: str) -> str | None:
        artifact_path = safe_artifact_path(self.server.output_dir, content_id, filename)
        if not artifact_path.exists():
            raise FileNotFoundError(f"Artifact not found: {filename}")
        if artifact_path.suffix.lower() == ".mp4":
            self._send_file(artifact_path, "video/mp4")
            return None
        content = artifact_path.read_text(encoding="utf-8")
        body = f"""<div class="card">
  <a href="/outputs/{_escape(content_id)}">返回审核包</a>
  <h1>{_escape(filename)}</h1>
  <pre>{_escape(content)}</pre>
</div>"""
        return _layout(filename, body)

    def _run(self, form: dict[str, list[str]]) -> None:
        url = _form_value(form, "url", "")
        github_url = _form_value(form, "github_url", "")
        stage = _form_value(form, "stage", "all")
        mock = "mock" in form
        if github_url:
            content_id = make_github_content_id(github_url)
            args = ["--github-url", github_url]
        elif url:
            content_id = make_content_id(url)
            args = ["--url", url, "--stage", stage]
        else:
            raise ValueError("Missing URL or GitHub repo URL")
        if mock:
            args.append("--mock")
        exit_code = run_pipeline(build_parser().parse_args(args))
        if exit_code != 0:
            raise RuntimeError(f"Pipeline exited with code {exit_code}")
        self._redirect(f"/outputs/{content_id}")

    def _rerun(self, form: dict[str, list[str]]) -> None:
        content_id = _form_value(form, "content_id")
        stage = _form_value(form, "stage", "rewrite")
        if not CONTENT_ID_RE.fullmatch(content_id):
            raise ValueError("Invalid content id")
        args = ["--content-id", content_id, "--rerun", stage]
        if "mock" in form:
            args.append("--mock")
        exit_code = run_pipeline(build_parser().parse_args(args))
        if exit_code != 0:
            raise RuntimeError(f"Pipeline exited with code {exit_code}")
        self._redirect(f"/outputs/{content_id}")

    def _render_video(self, form: dict[str, list[str]]) -> None:
        content_id = _form_value(form, "content_id")
        if not CONTENT_ID_RE.fullmatch(content_id):
            raise ValueError("Invalid content id")
        args = ["--render-video", content_id]
        if "video_mock" in form:
            args.append("--video-mock")
        exit_code = run_pipeline(build_parser().parse_args(args))
        if exit_code != 0:
            raise RuntimeError(f"Video render exited with code {exit_code}")
        self._redirect(f"/outputs/{content_id}")

    def _publish_review(self, form: dict[str, list[str]]) -> None:
        content_id = _form_value(form, "content_id")
        status = _form_value(form, "review_status")
        note = _form_value(form, "review_note", "")
        if not CONTENT_ID_RE.fullmatch(content_id):
            raise ValueError("Invalid content id")
        package_dir = self.server.output_dir / content_id
        if not package_dir.exists():
            raise FileNotFoundError(f"Output package not found: {content_id}")
        update_publish_review(package_dir, status, note)
        self._redirect(f"/outputs/{content_id}")

    def _platform_publish_package(self, form: dict[str, list[str]]) -> None:
        content_id = _form_value(form, "content_id")
        return_to = _form_value(form, "return_to", f"/outputs/{content_id}")
        if not CONTENT_ID_RE.fullmatch(content_id):
            raise ValueError("Invalid content id")
        package_dir = self.server.output_dir / content_id
        if not package_dir.exists():
            raise FileNotFoundError(f"Output package not found: {content_id}")
        generate_platform_publish_package(content_id, package_dir)
        self._redirect(return_to if return_to in {"/videos", f"/outputs/{content_id}"} else f"/outputs/{content_id}")

    def _publish_board_refresh(self) -> None:
        generate_publish_tasks_all(self.server.output_dir)
        self._redirect("/publish-board")

    def _feedback_board_refresh(self) -> None:
        generate_feedback_report(self.server.output_dir, self.server.data_dir / "feedback_report.json")
        self._redirect("/feedback-board")

    def _source_feedback_refresh(self) -> None:
        generate_source_feedback_report(
            self.server.output_dir,
            self.server.data_dir / "source_feedback_report.json",
            feedback_report_path=self.server.data_dir / "feedback_report.json",
            sources_path=self.server.data_dir / "sources.yaml",
        )
        self._redirect("/feedback-board")

    def _publish_task(self, form: dict[str, list[str]]) -> None:
        task_id = _form_value(form, "task_id")
        status = _form_value(form, "status", "pending_review")
        priority = _form_value(form, "priority", "normal")
        if status not in STATUSES:
            raise ValueError("Invalid publish task status")
        if priority not in PRIORITIES:
            raise ValueError("Invalid publish task priority")
        metrics = {key: _form_metric(form, key) for key in METRIC_KEYS}
        updates = {
            "status": status,
            "priority": priority,
            "scheduled_at": _form_value(form, "scheduled_at", ""),
            "account": _form_value(form, "account", ""),
            "publish_url": _form_value(form, "publish_url", ""),
            "published_at": _form_value(form, "published_at", ""),
            "metrics": metrics,
            "note": _form_value(form, "note", ""),
        }
        update_publish_task(self.server.output_dir, task_id, updates)
        self._redirect("/publish-board")

    def _publish_dry_run(self, form: dict[str, list[str]]) -> None:
        task_id = _form_value(form, "task_id")
        accounts_path = self.server.data_dir / "platform_accounts.yaml"
        init_platform_accounts(accounts_path)
        dry_run_publish_task(self.server.output_dir, accounts_path, task_id)
        self._redirect("/publish-board")

    def _publish_dry_run_ready(self) -> None:
        accounts_path = self.server.data_dir / "platform_accounts.yaml"
        init_platform_accounts(accounts_path)
        dry_run_ready_publish_tasks(self.server.output_dir, accounts_path)
        self._redirect("/publish-board")

    def _platform_accounts_update(self, form: dict[str, list[str]]) -> None:
        platform = _form_value(form, "platform")
        updates = {
            "account_id": _form_value(form, "account_id", ""),
            "display_name": _form_value(form, "display_name", ""),
            "enabled": "enabled" in form,
            "auto_publish_enabled": "auto_publish_enabled" in form,
            "login_method": _form_value(form, "login_method", ""),
            "publish_url": _form_value(form, "publish_url", ""),
            "notes": _form_value(form, "notes", ""),
            "default_priority": _form_int(form, "default_priority") or 99,
        }
        update_platform_account(self.server.data_dir / "platform_accounts.yaml", platform, updates)
        self._redirect("/platform-accounts")

    def _discover_sources(self, form: dict[str, list[str]]) -> None:
        discover_sources(mock="mock" in form)
        self._redirect("/source-discovery")

    def _auto_close_loop(self, form: dict[str, list[str]]) -> None:
        args = [
            "--auto-close-loop",
            "--output-dir",
            str(self.server.output_dir),
            "--workspace-dir",
            str(self.server.workspace_dir),
            "--mock",
        ]
        if "mock_discovery" in form:
            args.append("--auto-mock-discovery")
        before = {package.name for package in list_output_packages(self.server.output_dir)}
        exit_code = run_pipeline(build_parser().parse_args(args))
        if exit_code != 0:
            raise RuntimeError(f"Auto close loop exited with code {exit_code}")
        content_id = _latest_auto_run_content_id(self.server.output_dir, before)
        self._redirect(f"/outputs/{content_id}")

    def _candidate_approve(self, form: dict[str, list[str]]) -> None:
        approve_candidate(_form_value(form, "candidate_id"))
        self._redirect("/source-discovery")

    def _candidate_reject(self, form: dict[str, list[str]]) -> None:
        reject_candidate(_form_value(form, "candidate_id"), _form_value(form, "review_reason", ""))
        self._redirect("/source-discovery")

    def _candidate_archive(self, form: dict[str, list[str]]) -> None:
        archive_candidate(_form_value(form, "candidate_id"), _form_value(form, "review_reason", ""))
        self._redirect("/source-discovery")

    def _candidate_package(self, form: dict[str, list[str]]) -> None:
        candidate_id = _form_value(form, "candidate_id")
        candidate_path = self.server.root_dir / "data" / "candidate_sources.json"
        pool = load_candidate_pool(candidate_path)
        candidate = _find_candidate_for_web(pool, candidate_id)
        content_id = _candidate_package_content_id(candidate)
        args = [
            "--candidate-id",
            candidate_id,
            "--candidate-path",
            str(candidate_path),
            "--output-dir",
            str(self.server.output_dir),
            "--workspace-dir",
            str(self.server.workspace_dir),
            "--mock",
        ]
        exit_code = run_pipeline(build_parser().parse_args(args))
        if exit_code != 0:
            raise RuntimeError(f"Candidate package generation exited with code {exit_code}")
        self._redirect(f"/outputs/{content_id}")

    def _send_html(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, path: Path, content_type: str) -> None:
        payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("web: " + format % args + "\n")


class ContentAssetWebServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler]) -> None:
        settings = load_settings(force_mock=True)
        self.root_dir = settings.root_dir
        self.data_dir = settings.root_dir / "data"
        self.output_dir = settings.output_dir
        self.workspace_dir = settings.workspace_dir
        super().__init__(server_address, handler_class)


def _form_value(form: dict[str, list[str]], key: str, default: str | None = None) -> str:
    values = form.get(key)
    if not values:
        if default is not None:
            return default
        raise ValueError(f"Missing form field: {key}")
    return values[0].strip()


def _form_int(form: dict[str, list[str]], key: str) -> int:
    value = _form_value(form, key, "0")
    try:
        return max(0, int(value or 0))
    except ValueError:
        return 0


def _form_metric(form: dict[str, list[str]], key: str) -> int | float:
    value = _form_value(form, key, "0")
    if key == "completion_rate":
        try:
            return max(0.0, float(value or 0))
        except ValueError:
            return 0.0
    try:
        return max(0, int(value or 0))
    except ValueError:
        return 0


def _checked(value: Any) -> str:
    return "checked" if bool(value) else ""


def _metric_input_html(key: str, value: Any) -> str:
    step = " step='0.01'" if key == "completion_rate" else ""
    hint = "（0-1 或 0-100）" if key == "completion_rate" else ""
    return f"""<label>{_escape(key)}{_escape(hint)}</label>
    <input type="number" min="0"{step} name="{_escape(key)}" value="{_escape(value)}">"""


def _publish_task_card(task: dict[str, Any], latest_attempt: dict[str, Any] | None = None) -> str:
    metrics = task.get("metrics") if isinstance(task.get("metrics"), dict) else {}
    risks = task.get("manual_review_risks") if isinstance(task.get("manual_review_risks"), list) else []
    risks_html = "".join(f"<li>{_escape(item)}</li>" for item in risks if str(item).strip())
    metrics_summary = " · ".join(f"{key}: {metrics.get(key, 0)}" for key in METRIC_KEYS)
    publish_url = str(task.get("publish_url") or "")
    publish_link = (
        f"<a href='{_escape(publish_url)}' target='_blank' rel='noreferrer'>发布链接</a>"
        if publish_url
        else "<span class='muted'>未填写发布链接</span>"
    )
    status_options = "".join(_select_option(status, status, str(task.get("status") or "pending_review")) for status in STATUSES)
    priority_options = "".join(_select_option(priority, priority, str(task.get("priority") or "normal")) for priority in PRIORITIES)
    metric_inputs = "".join(_metric_input_html(key, metrics.get(key, 0)) for key in METRIC_KEYS)
    if latest_attempt:
        attempt_status = latest_attempt.get("status", "-")
        attempt_at = latest_attempt.get("created_at", "-")
        attempt_error = latest_attempt.get("error", "")
        latest_attempt_html = (
            "<p>"
            f"<strong>最近 dry-run：</strong>{_escape(attempt_status)} · {_escape(attempt_at)}"
            + (f" · <span class='error'>{_escape(attempt_error)}</span>" if attempt_error else "")
            + "</p>"
        )
    elif task.get("last_attempt_status"):
        latest_attempt_html = f"""<p><strong>最近 dry-run：</strong>{_escape(task.get("last_attempt_status"))} · {_escape(task.get("last_attempt_at", ""))}</p>"""
    else:
        latest_attempt_html = "<p class='muted'>最近 dry-run：暂无</p>"
    return f"""<div class="card">
  <h2>{_escape(task.get("title") or task.get("content_id"))}</h2>
  <p>
    <span class="pill">{_escape(task.get("platform_name") or task.get("platform"))}</span>
    <span class="pill">状态: {_escape(task.get("status", "pending_review"))}</span>
    <span class="pill">优先级: {_escape(task.get("priority", "normal"))}</span>
    <span class="pill">适合: {_escape(task.get("suitable"))}</span>
  </p>
  <p class="muted">{_escape(task.get("content_id"))} · {_escape(task.get("task_id"))}</p>
  <p><strong>排期：</strong>{_escape(task.get("scheduled_at") or "未排期")} · <strong>账号：</strong>{_escape(task.get("account") or "未填写")} · {publish_link}</p>
  <p><strong>关键指标：</strong>{_escape(metrics_summary)}</p>
  {latest_attempt_html}
  <form method="post" action="/publish-dry-run">
    <input type="hidden" name="task_id" value="{_escape(task.get("task_id"))}">
    <button class="secondary" type="submit">Dry-run 发布检查</button>
  </form>
  <h3>风险提示</h3>
  <ul>{risks_html or "<li>发布前做最终人工复核。</li>"}</ul>
  <form method="post" action="/publish-task">
    <input type="hidden" name="task_id" value="{_escape(task.get("task_id"))}">
    <div class="grid">
      <div>
        <label>status</label>
        <select name="status">{status_options}</select>
      </div>
      <div>
        <label>priority</label>
        <select name="priority">{priority_options}</select>
      </div>
      <div>
        <label>scheduled_at</label>
        <input type="text" name="scheduled_at" placeholder="2026-05-02 20:00" value="{_escape(task.get("scheduled_at", ""))}">
      </div>
      <div>
        <label>account</label>
        <input type="text" name="account" value="{_escape(task.get("account", ""))}">
      </div>
      <div>
        <label>publish_url</label>
        <input type="text" name="publish_url" value="{_escape(task.get("publish_url", ""))}">
      </div>
      <div>
        <label>published_at</label>
        <input type="text" name="published_at" placeholder="2026-05-02 21:00" value="{_escape(task.get("published_at", ""))}">
      </div>
      {metric_inputs}
    </div>
    <label>note</label>
    <textarea name="note">{_escape(task.get("note", ""))}</textarea>
    <button type="submit">保存任务</button>
  </form>
</div>"""


def _first_label(items: Any, key: str) -> str:
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return str(items[0].get(key) or "")
    return ""


def _feedback_notes_html(notes: Any) -> str:
    if not isinstance(notes, list):
        return ""
    return " ".join(f"<span class='pill'>{_escape(note)}</span>" for note in notes if str(note).strip())


def _feedback_platforms_html(platforms: Any) -> str:
    if not isinstance(platforms, list) or not platforms:
        return "<p class='muted'>暂无平台表现数据。</p>"
    cards = []
    for platform in platforms:
        if not isinstance(platform, dict):
            continue
        cards.append(
            "<div class='item'>"
            f"<strong>{_escape(platform.get('platform_name', platform.get('platform', '-')))}</strong>"
            f"<p><span class='pill'>平均分: {_escape(platform.get('average_score', 0))}</span>"
            f"<span class='pill'>任务数: {_escape(platform.get('task_count', 0))}</span></p>"
            f"<p class='muted'>最佳任务：{_escape(platform.get('best_task_id', '-'))}</p>"
            "</div>"
        )
    return f"<div class='grid'>{''.join(cards)}</div>"


def _feedback_tasks_html(tasks: Any) -> str:
    if not isinstance(tasks, list) or not tasks:
        return "<p class='muted'>暂无任务表现数据。</p>"
    cards = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        breakdown = task.get("score_breakdown") if isinstance(task.get("score_breakdown"), dict) else {}
        proxy = "有代理指标" if breakdown.get("proxy_used") else "直接指标"
        cards.append(
            "<div class='item'>"
            f"<strong>{_escape(task.get('title') or task.get('content_id') or '-')}</strong>"
            f"<p><span class='pill'>{_escape(task.get('platform_name', task.get('platform', '-')))}</span>"
            f"<span class='pill'>评分: {_escape(task.get('performance_score', 0))}</span>"
            f"<span class='pill'>{_escape(proxy)}</span></p>"
            f"<p class='muted'>{_escape(task.get('task_id', '-'))}</p>"
            f"<p>{_escape(breakdown.get('summary', ''))}</p>"
            "</div>"
        )
    return f"<div class='grid'>{''.join(cards)}</div>"


def _feedback_list_html(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "<p class='muted'>暂无。</p>"
    return "<ul>" + "".join(f"<li>{_escape(item)}</li>" for item in items if str(item).strip()) + "</ul>"


def _feedback_source_suggestions_html(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "<p class='muted'>暂无源池权重建议。</p>"
    cards = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("content_id") or item.get("scope") or "source_pool"
        cards.append(
            "<div class='item'>"
            f"<strong>{_escape(title)}</strong>"
            f"<p><span class='pill'>平均分: {_escape(item.get('average_score', '-'))}</span></p>"
            f"<p>{_escape(item.get('suggestion', ''))}</p>"
            f"<p class='muted'>{_escape(item.get('reason', ''))}</p>"
            "</div>"
        )
    return f"<div class='grid'>{''.join(cards)}</div>"


def _source_feedback_suggestions_html(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "<p class='muted'>暂无源池反馈建议。点击“生成源池反馈建议”后会写入 dry-run 报告。</p>"
    cards = []
    for item in items:
        if not isinstance(item, dict):
            continue
        reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
        evidence = item.get("evidence_tasks") if isinstance(item.get("evidence_tasks"), list) else []
        reason_html = "".join(f"<li>{_escape(reason)}</li>" for reason in reasons if str(reason).strip())
        evidence_html = "".join(
            "<li>"
            f"{_escape(task.get('task_id', '-'))} · {_escape(task.get('platform', '-'))} · "
            f"score {_escape(task.get('performance_score', 0))} · metrics {_escape(task.get('has_metrics', False))}"
            "</li>"
            for task in evidence
            if isinstance(task, dict)
        )
        related = ", ".join(str(content_id) for content_id in item.get("related_content_ids", []) if str(content_id).strip())
        cards.append(
            "<div class='item'>"
            f"<strong>{_escape(item.get('source_name') or item.get('source_key') or '-')}</strong>"
            f"<p><span class='pill'>{_escape(item.get('action', '-'))}</span>"
            f"<span class='pill'>类型: {_escape(item.get('source_type', '-'))}</span>"
            f"<span class='pill'>平均分: {_escape(item.get('avg_performance_score', 0))}</span>"
            f"<span class='pill'>建议调整: {_escape(item.get('recommended_weight_delta', 0))}</span></p>"
            f"<p class='muted'>source_key: {_escape(item.get('source_key', '-'))}</p>"
            f"<p class='muted'>关联内容：{_escape(related or '-')}</p>"
            f"<h4>原因</h4><ul>{reason_html or '<li>暂无。</li>'}</ul>"
            f"<h4>证据任务</h4><ul>{evidence_html or '<li>暂无。</li>'}</ul>"
            "</div>"
        )
    return f"<div class='grid'>{''.join(cards)}</div>"


def _select_option(value: str, label: str, selected_value: str) -> str:
    selected = " selected" if value == selected_value else ""
    return f"<option value='{_escape(value)}'{selected}>{_escape(label)}</option>"


def _publish_review_html(package_dir: Path, content_id: str) -> str:
    analysis = _read_json(package_dir / "analysis.json")
    transcript = _read_json(package_dir / "youtube_transcript.json")
    risk = _read_json(package_dir / "risk_report.json")
    quality = _read_json(package_dir / "quality_check.json")
    review = load_publish_review(package_dir)

    analysis_transcript = analysis.get("transcript_status") if isinstance(analysis.get("transcript_status"), dict) else {}
    transcript_status = str(transcript.get("status") or analysis_transcript.get("status") or "-")
    analysis_basis = str(analysis.get("analysis_basis") or "-")
    factual_confidence = str(analysis.get("factual_confidence") or "-")
    warning_html = ""
    if _needs_manual_source_check(factual_confidence, transcript_status):
        warning_html = "<p class='warning'>需人工核查原视频/资料后再发布</p>"

    fields = [
        ("publish_review", review.get("status", "pending")),
        ("updated_at", review.get("updated_at") or "-"),
        ("transcript 状态", _transcript_label(transcript, transcript_status)),
        ("analysis_basis", analysis_basis),
        ("factual_confidence", factual_confidence),
        ("risk 结论", _risk_conclusion(risk)),
        ("quality 结论", _quality_conclusion(quality)),
    ]
    cards = "".join(f"<div class='item'><div class='muted'>{_escape(k)}</div><strong>{_escape(v)}</strong></div>" for k, v in fields)
    pending_items = _pending_check_items(analysis, risk, quality)
    pending_html = (
        "<ul>" + "".join(f"<li>{_escape(item)}</li>" for item in pending_items) + "</ul>"
        if pending_items
        else "<p class='muted'>暂无自动提取的待核查项。</p>"
    )
    current_note = review.get("review_note") or ""
    status_options = "".join(
        _status_option(value, label)
        for value, label in [
            ("approved", "approved - 已人工确认可发布"),
            ("needs_revision", "needs_revision - 需修改后再审"),
            ("rejected", "rejected - 不发布"),
        ]
    )
    return f"""<div class="card">
  <h2>发布前审核</h2>
  <p class="muted">这里只记录人工发布决策，不会真的发布到任何平台。metadata-only 或字幕异常内容不能视为可直接发布。</p>
  {warning_html}
  <div class="grid">{cards}</div>
  <h3>待核查项</h3>
  {pending_html}
  <form method="post" action="/publish-review">
    <input type="hidden" name="content_id" value="{_escape(content_id)}">
    <label>审核结论</label>
    <select name="review_status" required>
      <option value="">选择审核结论</option>
      {status_options}
    </select>
    <label>审核备注</label>
    <textarea name="review_note" placeholder="记录人工核查来源、修改意见或拒绝原因">{_escape(current_note)}</textarea>
    <button type="submit">保存发布审核</button>
  </form>
</div>"""


def _platform_publish_html(package_dir: Path, content_id: str) -> str:
    package = _read_json(package_dir / "platform_publish_package.json")
    if not package:
        return f"""<div class="card">
  <h2>多平台发布包</h2>
  <p class="muted">生成抖音、快手、微信视频号、B站可复制粘贴的发布文案草稿；这里只生成发布资产，不会自动发布。</p>
  {_platform_package_form(content_id, f"/outputs/{content_id}", "生成发布包")}
</div>"""
    generated_at = package.get("generated_at", "-")
    return f"""<div class="card">
  <h2>多平台发布包</h2>
  <p class="muted">已生成 platform_publish_package.json / platform_publish_package.md，生成时间：{_escape(generated_at)}。这里只生成发布资产，不会自动发布。</p>
  {_platform_package_form(content_id, f"/outputs/{content_id}", "刷新发布包")}
  {_platform_assets_grid(package)}
</div>"""


def _platform_assets_grid(package: dict[str, Any]) -> str:
    platforms = package.get("platforms", {})
    cards = []
    for platform in PLATFORMS:
        asset = platforms.get(platform)
        if not isinstance(asset, dict):
            continue
        notes = asset.get("publish_notes", [])
        risks = asset.get("manual_review_risks", [])
        notes_html = "".join(f"<li>{_escape(item)}</li>" for item in notes if str(item).strip())
        risks_html = "".join(f"<li>{_escape(item)}</li>" for item in risks if str(item).strip())
        cards.append(
            f"""<div class="item platform-card">
  <h3>{_escape(asset.get("platform_name", platform))}</h3>
  <p><span class="pill">suitable: {_escape(asset.get("suitable"))}</span></p>
  <p><span class="pill">适合: {_escape(asset.get("content_fit", ""))}</span><span class="pill">长度: {_escape(asset.get("video_length", ""))}</span><span class="pill">重点: {_escape(asset.get("focus", ""))}</span></p>
  <p class="muted">{_escape(asset.get("suitability_reason", ""))}</p>
  <label>可复制发布文案</label>
  <textarea readonly>{_escape(asset.get("copy_block", ""))}</textarea>
  <p><strong>封面文案：</strong>{_escape(asset.get("cover_text", ""))}</p>
  <h4>发布注意事项</h4>
  <ul>{notes_html}</ul>
  <h4>需要人工确认的风险点</h4>
  <ul>{risks_html}</ul>
</div>"""
        )
    return f"<div class=\"platform-grid\">{''.join(cards)}</div>"


def _platform_package_form(content_id: str, return_to: str, label: str) -> str:
    return f"""<form method="post" action="/platform-publish-package">
  <input type="hidden" name="content_id" value="{_escape(content_id)}">
  <input type="hidden" name="return_to" value="{_escape(return_to)}">
  <button type="submit">{_escape(label)}</button>
</form>"""


def _status_option(value: str, label: str) -> str:
    return f"<option value='{_escape(value)}'>{_escape(label)}</option>"


def _needs_manual_source_check(factual_confidence: str, transcript_status: str) -> bool:
    return "low" in factual_confidence.lower() or transcript_status.lower() in {"error", "skipped"}


def _transcript_label(transcript: dict[str, Any], status: str) -> str:
    details = transcript.get("reason") or transcript.get("message") or transcript.get("language") or ""
    return f"{status} ({details})" if details else status


def _risk_conclusion(risk: dict[str, Any]) -> str:
    if not risk:
        return "-"
    passed = _pass_label(risk.get("pass"))
    parts = [passed, f"risk_level={risk.get('risk_level', '-')}"]
    if risk.get("must_review") is not None:
        parts.append(f"must_review={risk.get('must_review')}")
    return " · ".join(parts)


def _quality_conclusion(quality: dict[str, Any]) -> str:
    if not quality:
        return "-"
    passed = _pass_label(quality.get("pass"))
    parts = [passed, f"quality_score={quality.get('quality_score', '-')}"]
    if quality.get("ready_for_human_review") is not None:
        parts.append(f"ready_for_human_review={quality.get('ready_for_human_review')}")
    return " · ".join(parts)


def _pass_label(value: Any) -> str:
    if value is True:
        return "pass"
    if value is False:
        return "blocked"
    return "unknown"


def _pending_check_items(analysis: dict[str, Any], risk: dict[str, Any], quality: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for key, source in [
        ("facts_to_check", analysis),
        ("must_fix", risk),
        ("issues", quality),
        ("fix_suggestions", quality),
    ]:
        value = source.get(key)
        if isinstance(value, list):
            items.extend(str(item) for item in value if str(item).strip())
        elif isinstance(value, str) and value.strip():
            items.append(value.strip())
    return list(dict.fromkeys(items))


def _candidate_actions_html(candidate: dict[str, Any], output_dir: Path | None = None) -> str:
    candidate_id = str(candidate.get("candidate_id") or "")
    status = str(candidate.get("status") or "new")
    package_html = _candidate_package_action_html(candidate, output_dir)
    if status in {"approved", "approved_existing", "rejected", "archived"}:
        return (
            "<div class='actions'>"
            f"<button type='button' disabled>已处理：{_escape(status)}</button>"
            f"{package_html}"
            "</div>"
        )
    hidden = f"<input type='hidden' name='candidate_id' value='{_escape(candidate_id)}'>"
    reason_input = "<input type='text' name='review_reason' placeholder='原因（可选）'>"
    return (
        "<div class='actions'>"
        f"<form method='post' action='/candidate/approve'>{hidden}<button type='submit'>批准</button></form>"
        f"<form method='post' action='/candidate/reject'>{hidden}{reason_input}<button class='danger' type='submit'>拒绝</button></form>"
        f"<form method='post' action='/candidate/archive'>{hidden}{reason_input}<button class='secondary' type='submit'>归档</button></form>"
        f"{package_html}"
        "</div>"
    )


def _candidate_package_action_html(candidate: dict[str, Any], output_dir: Path | None = None) -> str:
    if candidate.get("source_type") not in {"youtube_video", "github_repo"}:
        return ""
    content_id = str(candidate.get("review_package_content_id") or _candidate_package_content_id(candidate))
    if not content_id:
        return ""
    if output_dir is not None and (output_dir / content_id).exists():
        return f"<a class='button' href='/outputs/{_escape(content_id)}'>查看审核包</a>"
    hidden = f"<input type='hidden' name='candidate_id' value='{_escape(candidate.get('candidate_id', ''))}'>"
    return f"<form method='post' action='/candidate/package'>{hidden}<button type='submit'>生成审核包</button></form>"


def _candidate_package_content_id(candidate: dict[str, Any]) -> str:
    source_type = candidate.get("source_type")
    url = str(candidate.get("url") or "")
    if source_type == "github_repo" and url:
        try:
            return make_github_content_id(url)
        except ValueError:
            return ""
    if source_type == "youtube_video":
        return make_youtube_candidate_content_id(candidate)
    return str(candidate.get("candidate_id") or "")


def _find_candidate_for_web(pool: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    for candidate in pool.get("candidates", []):
        if isinstance(candidate, dict) and candidate.get("candidate_id") == candidate_id:
            return candidate
    raise ValueError(f"Candidate not found: {candidate_id}")


def _latest_auto_run_content_id(output_dir: Path, previous_packages: set[str] | None = None) -> str:
    previous_packages = previous_packages or set()
    packages = list_output_packages(output_dir)
    candidates = [package for package in packages if (package / "auto_run_summary.json").exists()]
    new_candidates = [package for package in candidates if package.name not in previous_packages]
    for package in new_candidates or candidates:
        summary = _read_json(package / "auto_run_summary.json")
        content_id = str(summary.get("content_id") or package.name)
        if CONTENT_ID_RE.fullmatch(content_id):
            return content_id
    raise ValueError("Auto close loop did not produce auto_run_summary.json")


def build_server(host: str, port: int) -> ContentAssetWebServer:
    return ContentAssetWebServer((host, port), WebHandler)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the content asset MVP web console.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    server = build_server(args.host, args.port)
    print(f"Web console: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down web console.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
