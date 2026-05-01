from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analyzer import analyze_content
from .artifact_writer import ArtifactWriter
from .cleaner import clean_transcript
from .config import load_settings
from .db import Database
from .distribution_adapter import create_distribution_record
from .downloader import build_local_audio_meta, fetch_metadata_and_audio, make_content_id, make_file_content_id
from .feedback_collector import create_feedback_template
from .github_analyzer import analyze_github_project
from .github_collector import collect_github_repository, make_github_content_id
from .llm_client import LLMClient
from .logger import setup_logger
from .media_producer import prepare_media_job, render_video_package
from .opportunity_engine import evaluate_opportunity
from .platform_accounts import init_platform_accounts
from .platform_publish import generate_platform_publish_package, generate_platform_publish_packages_all
from .publish_adapter import dry_run_publish_task, dry_run_ready_publish_tasks
from .publish_board import METRIC_KEYS, STATUSES, generate_publish_tasks, generate_publish_tasks_all, update_publish_task
from .publish_review import ensure_publish_review, update_publish_review
from .quality_checker import check_quality
from .rewriter import rewrite_script
from .risk_checker import check_risk
from .scorer import score_topic
from .source_discovery import discover_sources, load_candidate_pool, save_candidate_pool
from .source_review import approve_candidate, archive_candidate, reject_candidate
from .snapshotter import snapshot_github_repo
from .transcriber import transcribe
from .youtube_analyzer import analyze_youtube_candidate, build_youtube_candidate_meta, make_youtube_candidate_content_id
from .youtube_transcript import fetch_youtube_transcript


STAGE_ORDER = ["meta", "transcript", "clean", "analysis", "score", "risk", "rewrite", "quality", "all"]
AUTO_PROCESSABLE_STATUSES = {"new", "review", "pending", "queued"}
AUTO_DECISION_PRIORITY = {"approve_candidate": 3, "review": 2}
AUTO_SOURCE_TYPE_PRIORITY = {"youtube_video": 2, "github_repo": 1}
CONTENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _should_run(current: str, target: str) -> bool:
    if target == "all":
        return True
    return STAGE_ORDER.index(current) <= STAGE_ORDER.index(target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the content asset MVP pipeline.")
    parser.add_argument("--url", help="Source YouTube URL")
    parser.add_argument("--github-url", help="Source GitHub repository URL for AI project explainer packages")
    parser.add_argument("--candidate-id", help="Source discovery candidate id from data/candidate_sources.json")
    parser.add_argument("--candidate-package", type=Path, help="Path to a single candidate JSON object")
    parser.add_argument("--audio-file", help="Local audio file for validating transcription and LLM pipeline")
    parser.add_argument("--title", help="Optional title for --audio-file input")
    parser.add_argument("--content-id", help="Existing or explicit content id")
    parser.add_argument("--output-dir", help="Output directory, relative to project root unless absolute")
    parser.add_argument("--workspace-dir", help="Workspace directory, relative to project root unless absolute")
    parser.add_argument("--stage", choices=STAGE_ORDER, default="all", help="Run through this stage")
    parser.add_argument("--rerun", choices=["analysis", "score", "risk", "rewrite", "quality"], help="Rerun a stage from existing artifacts")
    parser.add_argument("--mock", action="store_true", help="Force mock mode")
    parser.add_argument("--render-video", help="Render final video from output/{content_id}/chinese_script.md and exit")
    parser.add_argument("--video-mock", action="store_true", help="Force offline TTS fallback while rendering video")
    parser.add_argument(
        "--bilingual-subtitles",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Burn bilingual Chinese/English subtitles into rendered video (default: true)",
    )
    parser.add_argument("--review-package", help="Update publish_review.json for an output package and exit")
    parser.add_argument("--review-status", choices=["approved", "needs_revision", "rejected"], help="Publish review decision")
    parser.add_argument("--review-note", default="", help="Optional note for --review-package")
    parser.add_argument("--generate-platform-package", help="Generate platform_publish_package files for one content id and exit")
    parser.add_argument("--generate-platform-packages-all", action="store_true", help="Generate platform publish packages for every rendered final_video.mp4")
    parser.add_argument("--generate-publish-tasks", help="Generate or refresh publish_tasks.json for one content id and exit")
    parser.add_argument("--generate-publish-tasks-all", action="store_true", help="Generate or refresh publish tasks for every platform publish package")
    parser.add_argument("--platform-accounts-init", action="store_true", help="Initialize data/platform_accounts.yaml with non-sensitive account templates")
    parser.add_argument("--publish-dry-run", help="Run a dry-run publish check for one publish task id")
    parser.add_argument("--publish-dry-run-ready", action="store_true", help="Run dry-run publish checks for ready/scheduled tasks with enabled accounts")
    parser.add_argument("--update-publish-task", help="Update one publish task by task_id and exit")
    parser.add_argument("--task-status", choices=STATUSES, help="New status for --update-publish-task")
    parser.add_argument("--priority", choices=["low", "normal", "high", "urgent"], help="New priority for --update-publish-task")
    parser.add_argument("--scheduled-at", help="Scheduled publish time for --update-publish-task")
    parser.add_argument("--account", help="Publishing account for --update-publish-task")
    parser.add_argument("--publish-url", help="Published URL for --update-publish-task")
    parser.add_argument("--published-at", help="Published time for --update-publish-task")
    parser.add_argument("--views", type=int, help="Views metric for --update-publish-task")
    parser.add_argument("--likes", type=int, help="Likes metric for --update-publish-task")
    parser.add_argument("--comments", type=int, help="Comments metric for --update-publish-task")
    parser.add_argument("--favorites", type=int, help="Favorites metric for --update-publish-task")
    parser.add_argument("--shares", type=int, help="Shares metric for --update-publish-task")
    parser.add_argument("--note", help="Operator note for --update-publish-task")
    parser.add_argument("--auto-close-loop", action="store_true", help="Discover, select, package, and render the best candidate")
    parser.add_argument("--auto-mock-discovery", action="store_true", help="Use deterministic mock discovery for --auto-close-loop")
    parser.add_argument(
        "--auto-video-mock",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use offline TTS fallback while auto-rendering video (default: false)",
    )
    parser.add_argument("--init-db", action="store_true", help="Initialize PostgreSQL schema and exit")
    parser.add_argument("--discover-sources", action="store_true", help="Discover candidate sources and exit")
    parser.add_argument("--discovery-mock", action="store_true", help="Use deterministic mock source discovery")
    parser.add_argument("--discovery-limit", type=int, help="Maximum discovered candidates to process")
    parser.add_argument("--approve-candidate", help="Approve a candidate source into data/sources.yaml and exit")
    parser.add_argument("--reject-candidate", help="Reject a candidate source and exit")
    parser.add_argument("--archive-candidate", help="Archive a candidate source and exit")
    parser.add_argument("--review-reason", help="Optional reason for candidate reject/archive actions")
    parser.add_argument("--candidate-path", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--sources-path", type=Path, help=argparse.SUPPRESS)
    return parser


def run_pipeline(args: argparse.Namespace) -> int:
    settings = load_settings(output_dir=args.output_dir, workspace_dir=args.workspace_dir, force_mock=args.mock)
    logger = setup_logger(settings.log_dir)
    db = Database(settings.database_url, mock=settings.mock)

    if args.init_db:
        result = db.init_schema(settings.root_dir / "migrations" / "001_init.sql")
        print(result)
        return 0

    if args.discover_sources:
        result = discover_sources(mock=args.discovery_mock, limit=args.discovery_limit)
        decisions = result["by_decision"]
        print(
            "Source discovery finished: "
            f"discovered={result['discovered_count']} "
            f"new={result['new_count']} "
            f"updated={result['updated_count']} "
            f"candidates={result['candidate_count']}"
        )
        print(
            "Decisions: "
            f"approve_candidate={decisions.get('approve_candidate', 0)} "
            f"review={decisions.get('review', 0)} "
            f"reject={decisions.get('reject', 0)}"
        )
        if result["errors"]:
            print(f"Discovery errors recorded: {len(result['errors'])}")
        return 0

    review_actions = [
        ("approve", args.approve_candidate),
        ("reject", args.reject_candidate),
        ("archive", args.archive_candidate),
    ]
    requested_actions = [(action, candidate_id) for action, candidate_id in review_actions if candidate_id]
    if len(requested_actions) > 1:
        raise SystemExit("Only one candidate review action can be used at a time")
    if requested_actions:
        action, candidate_id = requested_actions[0]
        if action == "approve":
            result = approve_candidate(candidate_id, candidate_path=args.candidate_path, sources_path=args.sources_path)
        elif action == "reject":
            result = reject_candidate(candidate_id, args.review_reason, candidate_path=args.candidate_path)
        else:
            result = archive_candidate(candidate_id, args.review_reason, candidate_path=args.candidate_path)
        print(
            "Candidate review finished: "
            f"action={action} "
            f"candidate_id={result['candidate_id']} "
            f"status={result['status']} "
            f"source_id={result.get('source_id', '-')}"
        )
        print(result["message"])
        return 0

    if args.render_video:
        return _render_video(args, settings, db)

    if args.review_package:
        return _review_package(args, settings)

    if args.generate_platform_package:
        return _generate_platform_package(args, settings)

    if args.generate_platform_packages_all:
        return _generate_platform_packages_all(settings)

    if args.generate_publish_tasks:
        return _generate_publish_tasks(args, settings)

    if args.generate_publish_tasks_all:
        return _generate_publish_tasks_all(settings)

    if args.platform_accounts_init:
        return _platform_accounts_init(settings)

    if args.publish_dry_run:
        return _publish_dry_run(args, settings)

    if args.publish_dry_run_ready:
        return _publish_dry_run_ready(settings)

    if args.update_publish_task:
        return _update_publish_task(args, settings)

    llm = LLMClient(
        provider=settings.provider,
        model=settings.model,
        mock=settings.mock,
        openai_api_key=settings.openai_api_key,
        anthropic_api_key=settings.anthropic_api_key,
        google_api_key=settings.google_api_key,
    )

    if args.auto_close_loop:
        return _run_auto_close_loop(args, settings, llm, db, logger)

    if args.candidate_id or args.candidate_package:
        return _run_candidate_entry(args, settings, llm, db, logger)

    if not args.url and not args.github_url and not args.audio_file and not args.content_id:
        raise SystemExit("--url, --github-url, --audio-file, --candidate-id, --candidate-package, or --content-id is required")

    if args.content_id:
        content_id = args.content_id
    elif args.github_url:
        content_id = make_github_content_id(args.github_url)
    elif args.audio_file:
        content_id = make_file_content_id(args.audio_file)
    else:
        content_id = make_content_id(args.url)
    writer = ArtifactWriter(settings.output_dir, settings.workspace_dir, content_id)
    logger.info("Starting pipeline content_id=%s mock=%s", content_id, settings.mock)

    if args.rerun:
        return _rerun_stage(args.rerun, writer, llm, db)

    if args.github_url:
        return _run_github_pipeline(args.github_url, writer, llm, db, settings.mock, logger)

    if not args.url and not args.audio_file:
        raise SystemExit("--url, --github-url, or --audio-file is required unless --rerun is used")

    if args.audio_file:
        meta = build_local_audio_meta(args.audio_file, writer, title=args.title)
    else:
        meta = fetch_metadata_and_audio(args.url, writer, mock=settings.mock)
    db.upsert_content(meta, status="metadata_ready")
    db.record_artifact(content_id, "meta", str(writer.output_path("meta.json")))
    if not _should_run("transcript", args.stage):
        return 0

    transcript = transcribe(meta, writer, mock=settings.mock, openai_api_key=settings.openai_api_key)
    db.record_artifact(content_id, "transcript", str(writer.output_path("transcript.json")))
    if not _should_run("clean", args.stage):
        return 0

    transcript_clean = clean_transcript(transcript, writer)
    db.record_artifact(content_id, "transcript_clean", str(writer.output_path("transcript_clean.json")))
    if not _should_run("analysis", args.stage):
        return 0

    analysis = analyze_content(meta, transcript_clean, writer, llm, db)
    if not _should_run("score", args.stage):
        return 0

    score = score_topic(analysis, writer)
    if not _should_run("risk", args.stage):
        return 0

    risk_report = check_risk(meta, analysis, writer, llm, db)
    opportunity = evaluate_opportunity(content_id, analysis, score, writer)
    db.record_topic_opportunity(content_id, opportunity)
    db.record_artifact(content_id, "opportunity_engine", str(writer.output_path("opportunity_engine.json")))
    if not _should_run("rewrite", args.stage):
        return 0

    rewrite_result = rewrite_script(meta, analysis, score, risk_report, writer, llm, db)
    media_job = prepare_media_job(content_id, rewrite_result["script_path"], writer)
    db.record_media_job(content_id, media_job)
    db.record_artifact(content_id, "media_job", str(writer.output_path("media_job.json")))
    create_distribution_record(content_id, writer)
    db.record_artifact(content_id, "distribution", str(writer.output_path("distribution.json")))
    feedback = create_feedback_template(content_id, writer)
    db.record_feedback(content_id, feedback)
    db.record_artifact(content_id, "feedback_template", str(writer.output_path("feedback_template.json")))
    if not _should_run("quality", args.stage):
        return 0

    check_quality(meta, analysis, score, risk_report, writer, llm, db)
    ensure_publish_review(writer)
    logger.info("Pipeline finished output_dir=%s", writer.output_dir)
    return 0


def _run_github_pipeline(github_url: str, writer: ArtifactWriter, llm: LLMClient, db: Database, mock: bool, logger: object) -> int:
    meta = collect_github_repository(github_url, writer, mock=mock)
    db.upsert_content(meta, status="metadata_ready")
    for artifact_type, filename in [
        ("meta", "meta.json"),
        ("github_meta", "github_meta.json"),
        ("readme", "readme.md"),
        ("readme_images", "readme_images.json"),
    ]:
        db.record_artifact(writer.output_dir.name, artifact_type, str(writer.output_path(filename)))

    snapshot_status = snapshot_github_repo(
        meta.get("html_url") or github_url,
        writer,
        skip_reason="Mock mode skips browser screenshots." if mock else None,
    )
    db.record_artifact(writer.output_dir.name, "snapshot_status", str(writer.output_path("snapshot_status.json")))

    readme_markdown = writer.output_path("readme.md").read_text(encoding="utf-8")
    readme_images = writer.read_json("readme_images.json")
    analyze_github_project(meta, readme_markdown, readme_images, snapshot_status, writer, llm, db)
    ensure_publish_review(writer)
    logger.info("GitHub pipeline finished output_dir=%s", writer.output_dir)
    return 0


def _run_candidate_entry(args: argparse.Namespace, settings: object, llm: LLMClient, db: Database, logger: object) -> int:
    candidate, pool, pool_path = _load_candidate(args, settings)
    source_type = str(candidate.get("source_type") or "")
    content_id = _candidate_content_id(candidate, explicit_content_id=args.content_id)

    writer = ArtifactWriter(settings.output_dir, settings.workspace_dir, content_id)
    logger.info("Starting candidate pipeline candidate_id=%s content_id=%s mock=%s", candidate.get("candidate_id"), content_id, settings.mock)

    if source_type == "github_repo":
        url = str(candidate.get("url") or "")
        if not url:
            raise SystemExit("GitHub candidate is missing url")
        exit_code = _run_github_pipeline(url, writer, llm, db, settings.mock, logger)
    else:
        exit_code = _run_youtube_candidate_pipeline(candidate, writer, llm, db, logger)

    if exit_code == 0 and pool is not None:
        candidate["review_package_content_id"] = content_id
        candidate["review_package_generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        save_candidate_pool(pool, pool_path)
    print(f"Candidate package generated: candidate_id={candidate.get('candidate_id', '-')} content_id={content_id}")
    print(f"Output: {writer.output_dir}")
    return exit_code


def _run_auto_close_loop(args: argparse.Namespace, settings: object, llm: LLMClient, db: Database, logger: object) -> int:
    candidate_path = args.candidate_path or settings.root_dir / "data" / "candidate_sources.json"
    discovery_result = discover_sources(
        mock=args.auto_mock_discovery,
        limit=args.discovery_limit,
        source_path=args.sources_path,
        candidate_path=candidate_path,
    )
    pool = load_candidate_pool(candidate_path)
    candidates = [candidate for candidate in pool.get("candidates", []) if isinstance(candidate, dict)]
    selected = select_auto_candidate(candidates)
    if selected is None:
        raise SystemExit("No processable youtube_video or github_repo candidate found after discovery")

    content_id = _candidate_content_id(selected, explicit_content_id=args.content_id)
    package_args = argparse.Namespace(**vars(args))
    package_args.candidate_id = selected["candidate_id"]
    package_args.candidate_package = None
    package_args.candidate_path = candidate_path
    package_args.content_id = content_id
    package_exit_code = _run_candidate_entry(package_args, settings, llm, db, logger)
    if package_exit_code != 0:
        return package_exit_code

    render_args = argparse.Namespace(**vars(args))
    render_args.render_video = content_id
    render_args.video_mock = bool(args.video_mock or args.auto_video_mock)
    render_args.bilingual_subtitles = args.bilingual_subtitles
    render_exit_code = _render_video(render_args, settings, db)
    if render_exit_code != 0:
        return render_exit_code

    writer = ArtifactWriter(settings.output_dir, settings.workspace_dir, content_id)
    final_video_path = writer.output_path("final_video.mp4")
    summary = {
        "mode": "auto_close_loop",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "candidate_id": selected.get("candidate_id"),
        "content_id": content_id,
        "source_type": selected.get("source_type"),
        "decision": selected.get("decision"),
        "score": selected.get("score"),
        "selection_reason": describe_auto_candidate_selection(selected),
        "mock_discovery": bool(args.auto_mock_discovery),
        "video_mock": bool(render_args.video_mock or settings.mock),
        "discovery": discovery_result,
        "output_dir": str(writer.output_dir),
        "final_video_path": str(final_video_path),
        "final_video_exists": final_video_path.exists(),
    }
    writer.write_json("auto_run_summary.json", summary)
    db.record_artifact(content_id, "auto_run_summary", str(writer.output_path("auto_run_summary.json")))

    print("Auto close loop finished:")
    print(f"  candidate_id={selected.get('candidate_id')}")
    print(f"  content_id={content_id}")
    print(f"  output_dir={writer.output_dir}")
    print(f"  final_video={final_video_path}")
    return 0


def select_auto_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = [candidate for candidate in candidates if _is_auto_processable_candidate(candidate)]
    if not ranked:
        return None
    return sorted(ranked, key=_auto_candidate_sort_key, reverse=True)[0]


def describe_auto_candidate_selection(candidate: dict[str, Any]) -> str:
    return (
        f"Selected {candidate.get('source_type')} candidate because it is processable, "
        f"decision={candidate.get('decision')}, score={candidate.get('score', 0)}. "
        "Auto selection prioritizes youtube_video over github_repo, then decision and score."
    )


def _is_auto_processable_candidate(candidate: dict[str, Any]) -> bool:
    source_type = str(candidate.get("source_type") or "")
    status = str(candidate.get("status") or "new")
    decision = str(candidate.get("decision") or "")
    if source_type not in AUTO_SOURCE_TYPE_PRIORITY:
        return False
    if status not in AUTO_PROCESSABLE_STATUSES:
        return False
    return decision in AUTO_DECISION_PRIORITY


def _auto_candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int, int, str]:
    source_type = str(candidate.get("source_type") or "")
    decision = str(candidate.get("decision") or "")
    return (
        AUTO_SOURCE_TYPE_PRIORITY.get(source_type, 0),
        AUTO_DECISION_PRIORITY.get(decision, 0),
        _safe_int(candidate.get("score")),
        str(candidate.get("created_at") or ""),
    )


def _candidate_content_id(candidate: dict[str, Any], *, explicit_content_id: str | None = None) -> str:
    source_type = str(candidate.get("source_type") or "")
    if explicit_content_id:
        return explicit_content_id
    if source_type == "github_repo":
        url = str(candidate.get("url") or "")
        return make_github_content_id(url) if url else str(candidate.get("candidate_id"))
    if source_type == "youtube_video":
        return make_youtube_candidate_content_id(candidate)
    raise SystemExit(f"Unsupported candidate source_type: {source_type}")


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _run_youtube_candidate_pipeline(
    candidate: dict[str, Any],
    writer: ArtifactWriter,
    llm: LLMClient,
    db: Database,
    logger: object,
) -> int:
    content_id = writer.output_dir.name
    meta = build_youtube_candidate_meta(candidate, writer)
    db.upsert_content(meta, status="metadata_ready")
    db.record_artifact(content_id, "meta", str(writer.output_path("meta.json")))
    db.record_artifact(content_id, "youtube_candidate", str(writer.output_path("youtube_candidate.json")))

    transcript_status = fetch_youtube_transcript(candidate, writer, mock=False)
    db.record_artifact(content_id, "youtube_transcript", str(writer.output_path("youtube_transcript.json")))
    db.record_artifact(content_id, "transcript_clean", str(writer.output_path("transcript_clean.json")))
    transcript_clean = writer.read_json("transcript_clean.json")

    analysis = analyze_youtube_candidate(meta, candidate, transcript_clean, transcript_status, writer, llm, db)
    score = score_topic(analysis, writer)
    db.record_artifact(content_id, "score", str(writer.output_path("score.json")))
    risk_report = check_risk(meta, analysis, writer, llm, db)
    opportunity = evaluate_opportunity(content_id, analysis, score, writer)
    db.record_topic_opportunity(content_id, opportunity)
    db.record_artifact(content_id, "opportunity_engine", str(writer.output_path("opportunity_engine.json")))
    rewrite_result = rewrite_script(meta, analysis, score, risk_report, writer, llm, db)
    media_job = prepare_media_job(content_id, rewrite_result["script_path"], writer)
    db.record_media_job(content_id, media_job)
    db.record_artifact(content_id, "media_job", str(writer.output_path("media_job.json")))
    create_distribution_record(content_id, writer)
    db.record_artifact(content_id, "distribution", str(writer.output_path("distribution.json")))
    feedback = create_feedback_template(content_id, writer)
    db.record_feedback(content_id, feedback)
    db.record_artifact(content_id, "feedback_template", str(writer.output_path("feedback_template.json")))
    check_quality(meta, analysis, score, risk_report, writer, llm, db)
    ensure_publish_review(writer)
    logger.info("YouTube candidate pipeline finished output_dir=%s", writer.output_dir)
    return 0


def _load_candidate(args: argparse.Namespace, settings: object) -> tuple[dict[str, Any], dict[str, Any] | None, Path | None]:
    if args.candidate_id and args.candidate_package:
        raise SystemExit("Only one of --candidate-id or --candidate-package can be used")
    if args.candidate_id:
        pool_path = args.candidate_path or settings.root_dir / "data" / "candidate_sources.json"
        pool = load_candidate_pool(pool_path)
        for candidate in pool.get("candidates", []):
            if isinstance(candidate, dict) and candidate.get("candidate_id") == args.candidate_id:
                return candidate, pool, pool_path
        raise SystemExit(f"Candidate not found: {args.candidate_id}")

    package_path = _resolve_project_path(args.candidate_package, settings.root_dir)
    try:
        data = json.loads(package_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid candidate package JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("--candidate-package must point to a JSON object")
    if isinstance(data.get("candidate"), dict):
        return data["candidate"], None, None
    return data, None, None


def _resolve_project_path(path: Path, root_dir: Path) -> Path:
    return path if path.is_absolute() else root_dir / path


def _rerun_stage(stage: str, writer: ArtifactWriter, llm: LLMClient, db: Database) -> int:
    meta = writer.read_json("meta.json")
    analysis = writer.read_json("analysis.json") if writer.exists("analysis.json") else {}
    score = writer.read_json("score.json") if writer.exists("score.json") else {}
    risk_report = writer.read_json("risk_report.json") if writer.exists("risk_report.json") else {}

    if stage == "analysis":
        transcript_clean = writer.read_json("transcript_clean.json")
        analyze_content(meta, transcript_clean, writer, llm, db)
        return 0
    if stage == "score":
        score_topic(analysis, writer)
        return 0
    if stage == "risk":
        check_risk(meta, analysis, writer, llm, db)
        return 0
    if stage == "rewrite":
        rewrite_result = rewrite_script(meta, analysis, score, risk_report, writer, llm, db)
        prepare_media_job(writer.output_dir.name, rewrite_result["script_path"], writer)
        check_quality(meta, analysis, score, risk_report, writer, llm, db)
        return 0
    if stage == "quality":
        check_quality(meta, analysis, score, risk_report, writer, llm, db)
        return 0
    raise SystemExit(f"Unsupported rerun stage: {stage}")


def _render_video(args: argparse.Namespace, settings: object, db: Database) -> int:
    content_id = args.render_video
    writer = ArtifactWriter(settings.output_dir, settings.workspace_dir, content_id)
    result = render_video_package(
        content_id,
        writer,
        openai_api_key=settings.openai_api_key,
        force_mock=args.video_mock or settings.mock,
        bilingual_subtitles=args.bilingual_subtitles,
    )
    media_job = result.as_media_job()
    db.record_media_job(content_id, media_job)
    for artifact_type, filename in [
        ("voice", Path(media_job["voice_path"]).name),
        ("subtitles", "subtitles.srt"),
        ("subtitles_zh", "subtitles.zh.srt"),
        ("subtitles_en", "subtitles.en.srt"),
        ("subtitles_bilingual", "subtitles.bilingual.srt"),
        ("subtitle_translation_status", "subtitle_translation_status.json"),
        ("render_status", "render_status.json"),
        ("tts_status", "tts_status.json"),
        ("final_video", "final_video.mp4"),
        ("media_job", "media_job.json"),
    ]:
        db.record_artifact(content_id, artifact_type, str(writer.output_path(filename)))
    print(f"Video rendered: {result.video_path}")
    return 0


def _review_package(args: argparse.Namespace, settings: object) -> int:
    if not args.review_status:
        raise SystemExit("--review-status is required with --review-package")
    content_id = str(args.review_package)
    if not CONTENT_ID_RE.fullmatch(content_id):
        raise SystemExit("Invalid --review-package content id")
    package_dir = settings.output_dir / content_id
    if not package_dir.exists():
        raise SystemExit(f"Output package not found: {content_id}")
    review = update_publish_review(package_dir, args.review_status, args.review_note)
    print(
        "Publish review updated: "
        f"content_id={review['content_id']} "
        f"status={review['status']} "
        f"updated_at={review['updated_at']}"
    )
    return 0


def _generate_platform_package(args: argparse.Namespace, settings: object) -> int:
    content_id = str(args.generate_platform_package)
    if not CONTENT_ID_RE.fullmatch(content_id):
        raise SystemExit("Invalid --generate-platform-package content id")
    package_dir = settings.output_dir / content_id
    if not package_dir.exists():
        raise SystemExit(f"Output package not found: {content_id}")
    package = generate_platform_publish_package(content_id, package_dir)
    print(
        "Platform publish package generated: "
        f"content_id={content_id} "
        f"platforms={len(package['platforms'])} "
        f"json={package_dir / 'platform_publish_package.json'} "
        f"markdown={package_dir / 'platform_publish_package.md'}"
    )
    return 0


def _generate_platform_packages_all(settings: object) -> int:
    packages = generate_platform_publish_packages_all(settings.output_dir)
    print(f"Platform publish packages generated: count={len(packages)} output_dir={settings.output_dir}")
    for package in packages:
        content_id = package["content_id"]
        print(f"  - {content_id}: {settings.output_dir / content_id / 'platform_publish_package.json'}")
    return 0


def _generate_publish_tasks(args: argparse.Namespace, settings: object) -> int:
    content_id = str(args.generate_publish_tasks)
    if not CONTENT_ID_RE.fullmatch(content_id):
        raise SystemExit("Invalid --generate-publish-tasks content id")
    package_dir = settings.output_dir / content_id
    if not package_dir.exists():
        raise SystemExit(f"Output package not found: {content_id}")
    tasks = generate_publish_tasks(content_id, package_dir)
    print(
        "Publish tasks generated: "
        f"content_id={content_id} "
        f"tasks={len(tasks)} "
        f"json={package_dir / 'publish_tasks.json'}"
    )
    return 0


def _generate_publish_tasks_all(settings: object) -> int:
    tasks = generate_publish_tasks_all(settings.output_dir)
    content_count = len({task["content_id"] for task in tasks})
    print(f"Publish tasks generated: contents={content_count} tasks={len(tasks)} output_dir={settings.output_dir}")
    return 0


def _platform_accounts_init(settings: object) -> int:
    accounts_path = settings.root_dir / "data" / "platform_accounts.yaml"
    accounts = init_platform_accounts(accounts_path)
    print(f"Platform account templates ready: accounts={len(accounts)} yaml={accounts_path}")
    return 0


def _publish_dry_run(args: argparse.Namespace, settings: object) -> int:
    accounts_path = settings.root_dir / "data" / "platform_accounts.yaml"
    init_platform_accounts(accounts_path)
    attempt = dry_run_publish_task(settings.output_dir, accounts_path, str(args.publish_dry_run))
    print(
        "Publish dry-run finished: "
        f"task_id={attempt['task_id']} "
        f"platform={attempt['platform']} "
        f"status={attempt['status']} "
        f"attempt_id={attempt['attempt_id']}"
    )
    print(f"Attempts: {settings.output_dir / str(attempt['task_id']).split('__')[0] / 'publish_attempts.json'}")
    if attempt.get("error"):
        print(f"Error: {attempt['error']}")
        return 1
    return 0


def _publish_dry_run_ready(settings: object) -> int:
    accounts_path = settings.root_dir / "data" / "platform_accounts.yaml"
    init_platform_accounts(accounts_path)
    attempts = dry_run_ready_publish_tasks(settings.output_dir, accounts_path)
    succeeded = sum(1 for attempt in attempts if attempt.get("status") == "succeeded")
    failed = len(attempts) - succeeded
    print(f"Publish dry-run ready finished: attempts={len(attempts)} succeeded={succeeded} failed={failed}")
    for attempt in attempts:
        print(f"  - {attempt['task_id']}: {attempt['status']} {attempt.get('error', '')}")
    return 1 if failed else 0


def _update_publish_task(args: argparse.Namespace, settings: object) -> int:
    metrics_updates = {key: getattr(args, key) for key in METRIC_KEYS if getattr(args, key) is not None}
    updates: dict[str, Any] = {}
    field_map = {
        "status": args.task_status,
        "priority": args.priority,
        "scheduled_at": args.scheduled_at,
        "account": args.account,
        "publish_url": args.publish_url,
        "published_at": args.published_at,
        "note": args.note,
    }
    updates.update({key: value for key, value in field_map.items() if value is not None})
    if metrics_updates:
        updates["metrics"] = metrics_updates
    if not updates:
        raise SystemExit("No publish task updates provided")
    task = update_publish_task(settings.output_dir, str(args.update_publish_task), updates)
    print(
        "Publish task updated: "
        f"task_id={task['task_id']} "
        f"status={task['status']} "
        f"updated_at={task['updated_at']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run_pipeline(args)
    except Exception as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

