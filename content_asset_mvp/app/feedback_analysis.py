from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .platform_publish import PLATFORMS
from .publish_board import load_all_publish_tasks


BASE_METRIC_KEYS = ["views", "likes", "comments", "favorites", "shares"]
EXTENDED_METRIC_KEYS = [
    "completion_rate",
    "followers",
    "private_messages",
    "coins",
    "search_hits",
]
FEEDBACK_METRIC_KEYS = BASE_METRIC_KEYS + EXTENDED_METRIC_KEYS
TIME_WINDOW_LABELS = ["1h", "24h", "7d"]

PLATFORM_SCORE_RULES: dict[str, list[dict[str, Any]]] = {
    "douyin": [
        {"label": "完播", "weight": 0.35, "primary": ["completion_rate"], "proxy": ["views"]},
        {"label": "互动", "weight": 0.40, "primary": ["likes", "comments", "shares"]},
        {"label": "转粉", "weight": 0.25, "primary": ["followers"], "proxy": ["likes", "comments", "shares"]},
    ],
    "kuaishou": [
        {"label": "评论", "weight": 0.40, "primary": ["comments"]},
        {"label": "完播", "weight": 0.30, "primary": ["completion_rate"], "proxy": ["views"]},
        {"label": "信任感", "weight": 0.30, "primary": ["favorites", "shares"]},
    ],
    "wechat_channels": [
        {"label": "转发", "weight": 0.40, "primary": ["shares"]},
        {"label": "点赞", "weight": 0.30, "primary": ["likes"]},
        {"label": "完播", "weight": 0.30, "primary": ["completion_rate"], "proxy": ["views"]},
    ],
    "bilibili": [
        {"label": "收藏", "weight": 0.25, "primary": ["favorites"]},
        {"label": "投币", "weight": 0.25, "primary": ["coins"], "proxy": ["likes"]},
        {"label": "评论", "weight": 0.25, "primary": ["comments"]},
        {"label": "完播", "weight": 0.25, "primary": ["completion_rate"], "proxy": ["views"]},
    ],
    "xiaohongshu": [
        {"label": "收藏", "weight": 0.40, "primary": ["favorites"]},
        {"label": "搜索", "weight": 0.30, "primary": ["search_hits"], "proxy": ["comments"]},
        {"label": "私信", "weight": 0.30, "primary": ["private_messages"], "proxy": ["shares"]},
    ],
}


def generate_feedback_report(output_dir: Path, report_path: Path | None = None) -> dict[str, Any]:
    tasks = load_all_publish_tasks(output_dir)
    report = analyze_feedback(tasks)
    destination = report_path or Path(__file__).resolve().parents[1] / "data" / "feedback_report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    report["report_path"] = str(destination)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def load_feedback_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def analyze_feedback(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    task_scores = [score_publish_task(task) for task in tasks]
    data_task_scores = [item for item in task_scores if item["has_metrics"]]
    platform_scores = _platform_scores(data_task_scores)
    return {
        "schema_version": 1,
        "generated_at": _utc_now(),
        "total_tasks": len(task_scores),
        "data_tasks": len(data_task_scores),
        "task_scores": task_scores,
        "platform_scores": platform_scores,
        "best_platforms": platform_scores[:3],
        "best_tasks": sorted(data_task_scores, key=lambda item: item["performance_score"], reverse=True)[:5],
        "weak_tasks": _weak_tasks(data_task_scores),
        "time_window_summary": _time_window_summary(tasks),
        "content_insights": _content_insights(data_task_scores),
        "platform_insights": _platform_insights(platform_scores),
        "source_weight_suggestions": _source_weight_suggestions(data_task_scores),
        "notes": _report_notes(len(task_scores), len(data_task_scores)),
    }


def score_publish_task(task: dict[str, Any]) -> dict[str, Any]:
    platform = str(task.get("platform") or "")
    metric_source = _metric_source_for_task(task)
    metrics = normalize_metrics(metric_source.get("metrics"))
    rules = PLATFORM_SCORE_RULES.get(platform, [])
    performance_score, components = _score_metrics(platform, metrics)
    has_metrics = any(metrics.get(key, 0) > 0 for key in FEEDBACK_METRIC_KEYS)
    return {
        "task_id": str(task.get("task_id") or ""),
        "content_id": str(task.get("content_id") or ""),
        "title": str(task.get("title") or task.get("content_id") or ""),
        "platform": platform,
        "platform_name": str(task.get("platform_name") or PLATFORMS.get(platform, {}).get("platform_name", platform)),
        "status": str(task.get("status") or ""),
        "metrics": metrics,
        "metric_source": metric_source,
        "has_metrics": has_metrics,
        "performance_score": performance_score if has_metrics else 0.0,
        "score_breakdown": {
            "components": components,
            "proxy_used": any(component["proxy"] for component in components),
            "summary": _breakdown_summary(components),
        },
    }


def _metric_source_for_task(task: dict[str, Any]) -> dict[str, Any]:
    snapshots = _snapshot_candidates_for_task(task)
    if snapshots:
        latest_snapshot = snapshots[-1]
        return {
            "type": "snapshot",
            "label": str(latest_snapshot.get("label") or "custom"),
            "captured_at": str(latest_snapshot.get("captured_at") or ""),
            "metrics": latest_snapshot.get("metrics"),
        }
    metrics_latest = normalize_metrics(task.get("metrics_latest"))
    legacy_metrics = normalize_metrics(task.get("metrics"))
    if isinstance(task.get("metrics_latest"), dict) and (_has_metric_data(metrics_latest) or not _has_metric_data(legacy_metrics)):
        return {"type": "metrics_latest", "label": "latest", "captured_at": "", "metrics": task.get("metrics_latest")}
    return {"type": "metrics", "label": "legacy", "captured_at": "", "metrics": task.get("metrics")}


def _snapshot_candidates_for_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots = task.get("metric_snapshots")
    if not isinstance(snapshots, list):
        return []
    return [snapshot for snapshot in snapshots if isinstance(snapshot, dict)]


def _score_metrics(platform: str, metrics: dict[str, float]) -> tuple[float, list[dict[str, Any]]]:
    rules = PLATFORM_SCORE_RULES.get(platform, [])
    components = [_score_component(rule, metrics) for rule in rules]
    return round(sum(component["weighted_score"] for component in components), 2), components


def normalize_metrics(value: Any) -> dict[str, float]:
    source = value if isinstance(value, dict) else {}
    metrics: dict[str, float] = {}
    for key in FEEDBACK_METRIC_KEYS:
        metrics[key] = _metric_value(source.get(key), rate=key == "completion_rate")
    return metrics


def _has_metric_data(metrics: dict[str, float]) -> bool:
    return any(metrics.get(key, 0) > 0 for key in FEEDBACK_METRIC_KEYS)


def _score_component(rule: dict[str, Any], metrics: dict[str, float]) -> dict[str, Any]:
    primary_fields = list(rule.get("primary", []))
    proxy_fields = list(rule.get("proxy", []))
    fields = primary_fields
    proxy = False
    if not _fields_have_data(metrics, primary_fields) and proxy_fields:
        fields = proxy_fields
        proxy = True
    raw_value = sum(metrics.get(field, 0.0) for field in fields)
    score = _fields_score(metrics, fields, raw_value)
    weight = float(rule.get("weight", 0))
    return {
        "label": str(rule.get("label", "")),
        "weight": weight,
        "fields": fields,
        "raw_value": round(raw_value, 4),
        "score": round(score, 2),
        "weighted_score": round(score * weight, 2),
        "proxy": proxy,
        "proxy_reason": _proxy_reason(rule, fields) if proxy else "",
    }


def _fields_score(metrics: dict[str, float], fields: list[str], raw_value: float) -> float:
    if not fields or raw_value <= 0:
        return 0.0
    if fields == ["completion_rate"]:
        rate = raw_value * 100 if raw_value <= 1 else raw_value
        return min(100.0, max(0.0, rate))
    if fields == ["views"]:
        return _log_score(raw_value, full_scale=10000)
    views = metrics.get("views", 0.0)
    count_score = _log_score(raw_value, full_scale=1000)
    if views > 0:
        rate_score = min(100.0, (raw_value / views) * 1000)
        return max(count_score, rate_score)
    return count_score


def _log_score(value: float, *, full_scale: float) -> float:
    if value <= 0:
        return 0.0
    return min(100.0, math.log10(value + 1) / math.log10(full_scale + 1) * 100)


def _fields_have_data(metrics: dict[str, float], fields: list[str]) -> bool:
    return any(metrics.get(field, 0.0) > 0 for field in fields)


def _platform_scores(task_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in task_scores:
        grouped[task["platform"]].append(task)
    scores = []
    for platform, items in grouped.items():
        avg_score = sum(item["performance_score"] for item in items) / len(items)
        scores.append(
            {
                "platform": platform,
                "platform_name": PLATFORMS.get(platform, {}).get("platform_name", platform),
                "task_count": len(items),
                "average_score": round(avg_score, 2),
                "best_task_id": max(items, key=lambda item: item["performance_score"])["task_id"],
            }
        )
    return sorted(scores, key=lambda item: item["average_score"], reverse=True)


def _time_window_summary(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    latest_captured_at: dict[str, str] = {}
    for task in tasks:
        platform = str(task.get("platform") or "")
        for snapshot in _snapshot_candidates_for_task(task):
            label = str(snapshot.get("label") or "")
            if label not in TIME_WINDOW_LABELS:
                continue
            metrics = normalize_metrics(snapshot.get("metrics"))
            if not any(metrics.get(key, 0) > 0 for key in FEEDBACK_METRIC_KEYS):
                continue
            score, _ = _score_metrics(platform, metrics)
            grouped[label].append(score)
            captured_at = str(snapshot.get("captured_at") or "")
            if captured_at > latest_captured_at.get(label, ""):
                latest_captured_at[label] = captured_at
    summary = []
    for label in TIME_WINDOW_LABELS:
        scores = grouped.get(label, [])
        if not scores:
            continue
        summary.append(
            {
                "label": label,
                "task_count": len(scores),
                "average_score": round(sum(scores) / len(scores), 2),
                "latest_captured_at": latest_captured_at.get(label, ""),
            }
        )
    return summary


def _weak_tasks(task_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    weak = [item for item in task_scores if item["performance_score"] < 35]
    return sorted(weak or task_scores, key=lambda item: item["performance_score"])[:5]


def _content_insights(task_scores: list[dict[str, Any]]) -> list[str]:
    if not task_scores:
        return ["暂无足够表现数据。请先在发布看板录入播放、互动、收藏、转发等指标。"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in task_scores:
        grouped[task["content_id"]].append(task)
    ranked = sorted(
        (
            (
                content_id,
                sum(item["performance_score"] for item in items) / len(items),
                max(items, key=lambda item: item["performance_score"]),
            )
            for content_id, items in grouped.items()
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    best_content_id, avg_score, best_task = ranked[0]
    insights = [
        f"综合表现最好的是 {best_content_id}，平均分 {avg_score:.1f}，其中 {best_task['platform_name']} 单平台表现最高。",
    ]
    if len(ranked) > 1:
        weak_content_id, weak_avg, _ = ranked[-1]
        insights.append(f"{weak_content_id} 当前平均分 {weak_avg:.1f}，建议复盘选题钩子、封面标题和发布时间。")
    return insights


def _platform_insights(platform_scores: list[dict[str, Any]]) -> list[str]:
    if not platform_scores:
        return ["暂无平台表现数据。"]
    best = platform_scores[0]
    insights = [f"{best['platform_name']} 当前平均分最高：{best['average_score']}，可优先复用其标题和互动设计。"]
    if len(platform_scores) > 1:
        weak = platform_scores[-1]
        insights.append(f"{weak['platform_name']} 当前平均分最低：{weak['average_score']}，建议先做小样本 A/B 验证。")
    return insights


def _source_weight_suggestions(task_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not task_scores:
        return [
            {
                "scope": "source_pool",
                "suggestion": "暂不调整源池权重，等待至少 3 条有数据发布任务。",
                "reason": "当前没有可用表现数据。",
            }
        ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in task_scores:
        grouped[task["content_id"]].append(task)
    suggestions = []
    for content_id, items in sorted(grouped.items()):
        avg_score = sum(item["performance_score"] for item in items) / len(items)
        if avg_score >= 70:
            action = "提高同类来源优先级"
        elif avg_score < 35:
            action = "降低同类来源权重或延后复采"
        else:
            action = "保持权重，继续观察"
        suggestions.append(
            {
                "content_id": content_id,
                "average_score": round(avg_score, 2),
                "suggestion": action,
                "reason": "基于该内容在已录入平台任务上的平均表现分。",
            }
        )
    return sorted(suggestions, key=lambda item: item["average_score"], reverse=True)[:8]


def _breakdown_summary(components: list[dict[str, Any]]) -> str:
    if not components:
        return "该平台暂无评分规则。"
    proxy_labels = [component["label"] for component in components if component["proxy"]]
    if proxy_labels:
        return "、".join(proxy_labels) + " 使用代理指标，后续录入真实扩展指标后会自动优先采用。"
    return "全部采用当前可用的直接指标。"


def _proxy_reason(rule: dict[str, Any], fields: list[str]) -> str:
    label = str(rule.get("label", ""))
    return f"当前没有{label}直接指标，暂用 {', '.join(fields)} 作为 proxy。"


def _report_notes(total_tasks: int, data_tasks: int) -> list[str]:
    if total_tasks == 0:
        return ["未发现 publish_tasks.json。请先在发布看板刷新全部发布任务。"]
    if data_tasks == 0:
        return ["已发现发布任务，但暂无表现指标。请先在发布看板录入 views/likes/comments/favorites/shares 等数据。"]
    if data_tasks < 3:
        return ["当前有数据任务少于 3 条，报告可用于检查链路，但不建议直接调整源池权重。"]
    return ["报告基于发布看板已录入表现指标生成。"]


def _metric_value(value: Any, *, rate: bool = False) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if number < 0:
        return 0.0
    if rate and number > 1:
        return min(number, 100.0)
    return number


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
