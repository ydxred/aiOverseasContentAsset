from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .feedback_analysis import analyze_feedback, load_feedback_report
from .publish_board import load_all_publish_tasks
from .source_manager import default_sources_path, load_sources

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


SCHEMA_VERSION = 1
MIN_TOTAL_SCORED_TASKS = 3
MIN_SOURCE_SCORED_TASKS = 3
HIGH_SCORE_THRESHOLD = 70.0
LOW_SCORE_THRESHOLD = 35.0
MAX_WEIGHT_DELTA = 0.05


def default_source_feedback_report_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "source_feedback_report.json"


def default_source_feedback_audit_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "source_feedback_audit.json"


def generate_source_feedback_report(
    output_dir: Path,
    report_path: Path | None = None,
    *,
    feedback_report_path: Path | None = None,
    sources_path: Path | None = None,
) -> dict[str, Any]:
    destination = report_path or default_source_feedback_report_path()
    feedback_report = _load_or_analyze_feedback(output_dir, feedback_report_path)
    sources = load_sources(sources_path)
    source_index = _source_index(sources)
    packages = _load_package_sources(output_dir, source_index)
    suggestions = _build_suggestions(feedback_report.get("task_scores", []), packages)
    total_scored_tasks = sum(1 for task in feedback_report.get("task_scores", []) if isinstance(task, dict) and task.get("has_metrics"))
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "total_scored_tasks": total_scored_tasks,
        "source_suggestions": suggestions,
        "notes": _report_notes(total_scored_tasks, suggestions),
        "report_path": str(destination),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def load_source_feedback_report(path: Path | None = None) -> dict[str, Any]:
    report_path = path or default_source_feedback_report_path()
    if not report_path.exists():
        return {}
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def apply_source_feedback(
    output_dir: Path,
    *,
    dry_run: bool = True,
    report_path: Path | None = None,
    feedback_report_path: Path | None = None,
    sources_path: Path | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    source_path = sources_path or default_sources_path()
    destination = report_path or default_source_feedback_report_path()
    audit_destination = audit_path or default_source_feedback_audit_path()
    report = generate_source_feedback_report(
        output_dir,
        destination,
        feedback_report_path=feedback_report_path,
        sources_path=source_path,
    )
    application = {
        "dry_run": dry_run,
        "report_path": str(destination),
        "sources_path": str(source_path),
        "audit_path": str(audit_destination),
        "applied_count": 0,
        "changes": [],
        "message": "dry-run only; sources.yaml was not modified.",
    }
    if dry_run:
        return {"report": report, "application": application}
    if yaml is None:
        raise RuntimeError("PyYAML is required to write source feedback")
    if not source_path.exists():
        raise FileNotFoundError(f"Sources file not found: {source_path}")

    data = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise RuntimeError("sources.yaml must contain a sources list")
    by_id = {str(source.get("source_id") or ""): source for source in data["sources"] if isinstance(source, dict)}
    for suggestion in report.get("source_suggestions", []):
        if not isinstance(suggestion, dict):
            continue
        if suggestion.get("action") not in {"increase", "decrease"}:
            continue
        source_key = str(suggestion.get("source_key") or "")
        source = by_id.get(source_key)
        if source is None:
            continue
        delta = _bounded_float(suggestion.get("recommended_weight_delta"), -MAX_WEIGHT_DELTA, MAX_WEIGHT_DELTA)
        old_weight = _safe_float(source.get("feedback_weight"), 0.0)
        new_weight = _bounded_float(old_weight + delta, -0.2, 0.2)
        source["feedback_weight"] = round(new_weight, 3)
        application["changes"].append(
            {
                "source_key": source_key,
                "source_name": source.get("name", source_key),
                "old_feedback_weight": round(old_weight, 3),
                "new_feedback_weight": source["feedback_weight"],
                "delta": round(delta, 3),
                "reason": suggestion.get("reasons", []),
            }
        )

    application["applied_count"] = len(application["changes"])
    if application["applied_count"]:
        application["message"] = "sources.yaml updated with conservative feedback_weight changes."
        source_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    else:
        application["message"] = "No eligible source feedback changes; sources.yaml was not modified."
    audit = _load_audit(audit_destination)
    audit.setdefault("records", []).append(
        {
            "generated_at": _utc_now(),
            "dry_run": False,
            "report_path": str(destination),
            "sources_path": str(source_path),
            "changes": application["changes"],
        }
    )
    audit_destination.parent.mkdir(parents=True, exist_ok=True)
    audit_destination.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"report": report, "application": application}


def _load_or_analyze_feedback(output_dir: Path, feedback_report_path: Path | None) -> dict[str, Any]:
    if feedback_report_path:
        loaded = load_feedback_report(feedback_report_path)
        if loaded:
            return loaded
    return analyze_feedback(load_all_publish_tasks(output_dir))


def _source_index(sources: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(source.get("source_id") or ""): source for source in sources}
    github_owner: dict[str, dict[str, Any]] = {}
    youtube_name: dict[str, dict[str, Any]] = {}
    for source in sources:
        urls = source.get("urls") if isinstance(source.get("urls"), dict) else {}
        github_url = str(urls.get("github") or source.get("url") or "")
        owner = _github_owner(github_url)
        if owner:
            github_owner[owner.lower()] = source
        youtube_url = str(urls.get("youtube") or "")
        if youtube_url:
            youtube_name[_clean_name(str(source.get("name") or ""))] = source
    return {"by_id": by_id, "github_owner": github_owner, "youtube_name": youtube_name}


def _load_package_sources(output_dir: Path, source_index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    packages: dict[str, dict[str, Any]] = {}
    if not output_dir.exists():
        return packages
    for package_dir in sorted(path for path in output_dir.iterdir() if path.is_dir()):
        meta = _read_json(package_dir / "meta.json")
        youtube_candidate = _read_json(package_dir / "youtube_candidate.json")
        github_meta = _read_json(package_dir / "github_meta.json")
        platform_package = _read_json(package_dir / "platform_publish_package.json")
        source = _source_from_package(package_dir.name, meta, youtube_candidate, github_meta, platform_package, source_index)
        if source:
            packages[package_dir.name] = source
    return packages


def _source_from_package(
    content_id: str,
    meta: dict[str, Any],
    youtube_candidate: dict[str, Any],
    github_meta: dict[str, Any],
    platform_package: dict[str, Any],
    source_index: dict[str, Any],
) -> dict[str, Any]:
    candidate_source = _source_from_candidate(youtube_candidate, source_index)
    if candidate_source:
        return candidate_source

    source_type = str(meta.get("source_type") or github_meta.get("source_type") or "")
    if source_type == "github_repo":
        owner = str(github_meta.get("owner") or meta.get("owner") or "").strip()
        matched = source_index["github_owner"].get(owner.lower()) if owner else None
        if matched:
            return _source_ref(
                str(matched.get("source_id") or ""),
                str(matched.get("source_type") or "github_org"),
                str(matched.get("name") or owner),
            )
        full_name = str(github_meta.get("full_name") or meta.get("full_name") or meta.get("title") or owner or content_id)
        return _source_ref(f"github:{owner or full_name}", "github_repo", full_name)

    if source_type == "youtube_video":
        channel_title = str(meta.get("channel_title") or meta.get("author") or "").strip()
        matched = source_index["youtube_name"].get(_clean_name(channel_title)) if channel_title else None
        if matched:
            return _source_ref(
                str(matched.get("source_id") or ""),
                str(matched.get("source_type") or "youtube_channel"),
                str(matched.get("name") or channel_title),
            )
        channel_id = str(meta.get("channel_id") or "").strip()
        key = f"youtube_channel:{channel_id}" if channel_id else f"youtube_channel:{channel_title or content_id}"
        return _source_ref(key, "youtube_channel", channel_title or key)

    package_source_type = str(platform_package.get("source_type") or source_type or "unknown")
    source_url = str(meta.get("source_url") or meta.get("webpage_url") or "").strip()
    key = source_url or content_id
    return _source_ref(key, package_source_type, str(meta.get("title") or key))


def _source_from_candidate(candidate: dict[str, Any], source_index: dict[str, Any]) -> dict[str, Any]:
    discovered_from = candidate.get("discovered_from") if isinstance(candidate.get("discovered_from"), dict) else {}
    source_id = str(discovered_from.get("source_id") or candidate.get("source_id") or "").strip()
    if not source_id:
        return {}
    source = source_index["by_id"].get(source_id, {})
    return _source_ref(
        source_id,
        str(discovered_from.get("source_type") or source.get("source_type") or candidate.get("source_type") or "unknown"),
        str(discovered_from.get("name") or source.get("name") or source_id),
    )


def _build_suggestions(task_scores: Any, package_sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = [task for task in task_scores if isinstance(task, dict)]
    total_scored = sum(1 for task in tasks if task.get("has_metrics"))
    grouped: dict[str, dict[str, Any]] = {}
    for content_id, source in package_sources.items():
        source_key = source["source_key"]
        grouped.setdefault(
            source_key,
            {
                **source,
                "related_content_ids": [],
                "tasks": [],
            },
        )
        grouped[source_key]["related_content_ids"].append(content_id)
    for task in tasks:
        content_id = str(task.get("content_id") or "")
        source = package_sources.get(content_id)
        if not source:
            continue
        grouped.setdefault(
            source["source_key"],
            {
                **source,
                "related_content_ids": [],
                "tasks": [],
            },
        )
        if content_id and content_id not in grouped[source["source_key"]]["related_content_ids"]:
            grouped[source["source_key"]]["related_content_ids"].append(content_id)
        grouped[source["source_key"]]["tasks"].append(task)

    if not grouped:
        return [
            {
                "source_key": "source_pool",
                "source_type": "unknown",
                "source_name": "source_pool",
                "related_content_ids": [],
                "avg_performance_score": 0.0,
                "success_count": 0,
                "failure_count": 0,
                "recommended_weight_delta": 0.0,
                "action": "insufficient_data",
                "reasons": ["没有找到可关联到源池的发布任务。"],
                "evidence_tasks": [],
            }
        ]

    suggestions = []
    for item in grouped.values():
        scored_tasks = [task for task in item["tasks"] if task.get("has_metrics")]
        avg_score = sum(float(task.get("performance_score") or 0) for task in scored_tasks) / len(scored_tasks) if scored_tasks else 0.0
        success_count = sum(1 for task in scored_tasks if float(task.get("performance_score") or 0) >= HIGH_SCORE_THRESHOLD)
        failure_count = sum(1 for task in scored_tasks if float(task.get("performance_score") or 0) < LOW_SCORE_THRESHOLD)
        action, delta, reasons = _recommendation(total_scored, scored_tasks, avg_score, success_count, failure_count)
        suggestions.append(
            {
                "source_key": item["source_key"],
                "source_type": item["source_type"],
                "source_name": item["source_name"],
                "related_content_ids": sorted(set(item["related_content_ids"])),
                "avg_performance_score": round(avg_score, 2),
                "success_count": success_count,
                "failure_count": failure_count,
                "recommended_weight_delta": delta,
                "action": action,
                "reasons": reasons,
                "evidence_tasks": _evidence_tasks(item["tasks"]),
            }
        )
    return sorted(suggestions, key=lambda item: (item["action"] == "insufficient_data", -abs(item["recommended_weight_delta"]), item["source_key"]))


def _recommendation(
    total_scored: int,
    scored_tasks: list[dict[str, Any]],
    avg_score: float,
    success_count: int,
    failure_count: int,
) -> tuple[str, float, list[str]]:
    if total_scored < MIN_TOTAL_SCORED_TASKS:
        return "insufficient_data", 0.0, [f"全局有数据任务少于 {MIN_TOTAL_SCORED_TASKS} 条，只生成审计建议，不调权。"]
    if len(scored_tasks) < MIN_SOURCE_SCORED_TASKS:
        return "insufficient_data", 0.0, [f"该源关联的有数据任务少于 {MIN_SOURCE_SCORED_TASKS} 条。"]
    if avg_score >= HIGH_SCORE_THRESHOLD and success_count >= 2:
        return "increase", MAX_WEIGHT_DELTA, ["该源关联内容平均表现较高，且至少 2 条任务达到高分阈值。"]
    if avg_score < LOW_SCORE_THRESHOLD and failure_count >= 2:
        return "decrease", -MAX_WEIGHT_DELTA, ["该源关联内容平均表现偏低，且至少 2 条任务低于弱表现阈值。"]
    return "keep", 0.0, ["表现尚未形成稳定方向，保持权重继续观察。"]


def _evidence_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence = []
    for task in tasks[:8]:
        evidence.append(
            {
                "task_id": str(task.get("task_id") or ""),
                "content_id": str(task.get("content_id") or ""),
                "platform": str(task.get("platform") or ""),
                "has_metrics": bool(task.get("has_metrics")),
                "performance_score": round(float(task.get("performance_score") or 0), 2),
            }
        )
    return evidence


def _source_ref(source_key: str, source_type: str, source_name: str) -> dict[str, Any]:
    return {
        "source_key": source_key,
        "source_type": source_type,
        "source_name": source_name,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _load_audit(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "records": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": SCHEMA_VERSION, "records": []}
    return data if isinstance(data, dict) else {"schema_version": SCHEMA_VERSION, "records": []}


def _report_notes(total_scored_tasks: int, suggestions: list[dict[str, Any]]) -> list[str]:
    if total_scored_tasks == 0:
        return ["当前没有带指标的发布任务，所有源池建议均按数据不足处理。"]
    if total_scored_tasks < MIN_TOTAL_SCORED_TASKS:
        return ["当前有数据任务少于 3 条，仅生成审计建议，不建议写入源池。"]
    if all(item.get("action") in {"keep", "insufficient_data"} for item in suggestions):
        return ["没有发现足够稳定的来源表现差异，建议继续观察。"]
    return ["报告基于发布表现和输出包来源元数据生成；写入源池前建议人工复核证据任务。"]


def _github_owner(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "github.com":
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    return parts[0] if parts else ""


def _clean_name(value: str) -> str:
    return " ".join(value.lower().strip().split())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bounded_float(value: Any, lower: float, upper: float) -> float:
    return min(upper, max(lower, _safe_float(value)))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
