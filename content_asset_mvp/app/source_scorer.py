from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


POSITIVE_KEYWORDS = {
    "ai": 12,
    "agent": 10,
    "agents": 10,
    "llm": 10,
    "automation": 9,
    "automate": 8,
    "saas": 8,
    "indie": 7,
    "micro saas": 8,
    "github": 7,
    "open source": 7,
    "project": 6,
    "developer tool": 6,
    "workflow": 5,
    "founder": 5,
    "startup": 5,
    "product": 4,
}

NEGATIVE_KEYWORDS = {
    "coupon": -15,
    "casino": -25,
    "crypto price": -18,
    "wallpaper": -12,
    "recipe": -12,
    "celebrity": -15,
    "sports": -12,
    "gaming": -8,
}


def score_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Score a candidate source using transparent local rules."""
    signals = _normalize_signals(candidate.get("signals"))
    score = 20
    reasons: list[str] = []
    text = _candidate_text(candidate)

    for keyword, points in POSITIVE_KEYWORDS.items():
        if keyword in text:
            score += points
            reasons.append(f"+{points} keyword:{keyword}")

    for keyword, points in NEGATIVE_KEYWORDS.items():
        if keyword in text:
            score += points
            reasons.append(f"{points} low_signal:{keyword}")

    trust_score = _as_int(_get_nested(candidate, ("discovered_from", "trust_score")), default=0)
    if trust_score >= 9:
        score += 18
        reasons.append("+18 high_trust_seed")
    elif trust_score >= 7:
        score += 10
        reasons.append("+10 trusted_seed")

    feedback_adjustment = _feedback_adjustment(_get_nested(candidate, ("discovered_from", "feedback_weight")))
    if feedback_adjustment:
        score += feedback_adjustment
        reasons.append(f"{feedback_adjustment:+d} source_feedback_weight")

    stars = _as_int(signals.get("stars"), default=0)
    forks = _as_int(signals.get("forks"), default=0)
    if stars >= 10_000:
        score += 16
        reasons.append("+16 github_stars_10000")
    elif stars >= 1_000:
        score += 12
        reasons.append("+12 github_stars_1000")
    elif stars >= 100:
        score += 6
        reasons.append("+6 github_stars_100")
    if forks >= 1_000:
        score += 8
        reasons.append("+8 github_forks_1000")
    elif forks >= 100:
        score += 4
        reasons.append("+4 github_forks_100")

    views = _as_int(signals.get("views"), default=0)
    likes = _as_int(signals.get("likes"), default=0)
    comments = _as_int(signals.get("comments"), default=0)
    if views >= 250_000:
        score += 12
        reasons.append("+12 youtube_views_250000")
    elif views >= 50_000:
        score += 8
        reasons.append("+8 youtube_views_50000")
    elif views >= 10_000:
        score += 4
        reasons.append("+4 youtube_views_10000")
    if likes >= 10_000:
        score += 8
        reasons.append("+8 youtube_likes_10000")
    elif likes >= 1_000:
        score += 5
        reasons.append("+5 youtube_likes_1000")
    if comments >= 500:
        score += 4
        reasons.append("+4 youtube_comments_500")

    updated_at = str(signals.get("updated_at") or "")
    if _updated_recently(updated_at, days=180):
        score += 8
        reasons.append("+8 recently_updated")
    elif updated_at:
        score += 2
        reasons.append("+2 has_update_signal")

    if not candidate.get("url"):
        score -= 20
        reasons.append("-20 missing_url")
    if not reasons:
        reasons.append("baseline_only")

    score = max(0, min(100, score))
    decision = decision_for_score(score)
    return {
        "score": score,
        "decision": decision,
        "score_reasons": reasons,
    }


def score_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        result = score_candidate(candidate)
        item = dict(candidate)
        item["score"] = result["score"]
        item["decision"] = result["decision"]
        signals = _normalize_signals(item.get("signals"))
        signals["score_reasons"] = result["score_reasons"]
        item["signals"] = signals
        scored.append(item)
    return scored


def decision_for_score(score: int) -> str:
    if score >= 72:
        return "approve_candidate"
    if score >= 42:
        return "review"
    return "reject"


def _candidate_text(candidate: dict[str, Any]) -> str:
    parts = [
        candidate.get("name"),
        candidate.get("url"),
        candidate.get("category"),
        candidate.get("source_type"),
        candidate.get("reason"),
        candidate.get("discovery_method"),
    ]
    signals = candidate.get("signals")
    if isinstance(signals, dict):
        parts.extend(str(value) for value in signals.values())
    return " ".join(str(part) for part in parts if part).lower()


def _normalize_signals(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _get_nested(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _feedback_adjustment(value: Any) -> int:
    try:
        weight = float(value or 0)
    except (TypeError, ValueError):
        return 0
    # Source feedback is intentionally small so it cannot dominate intrinsic candidate quality.
    return int(round(max(-0.2, min(0.2, weight)) * 20))


def _updated_recently(value: str, *, days: int) -> bool:
    if not value:
        return False
    normalized = value.removesuffix("Z") + "+00:00" if value.endswith("Z") else value
    try:
        updated_at = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - updated_at.astimezone(timezone.utc)
    return age.days <= days
