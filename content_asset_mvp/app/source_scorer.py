from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# Used to count chapter markers / topic anchors in a YouTube description.
# Catches both "(00:00)" timestamp markers (Peter Yang style) and bare
# "00:00 Topic" lines (default YouTube chapter format). 4+ matches is the
# floor YouTube itself uses to render a chapter timeline on the player.
_TIMESTAMP_RE = re.compile(r"(?:^|[\s(\[])(\d{1,2}:\d{2}(?::\d{2})?)\b")


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
    "product hunt": 8,
    "launch": 7,
    "show hn": 8,
    "hacker news": 7,
    "newsletter": 5,
    "blog": 4,
    "article": 4,
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


def estimate_visual_capacity(candidate: dict[str, Any]) -> dict[str, Any]:
    """Predict how many *distinct* visual assets we'll be able to assemble for
    this candidate before we commit to producing a video.

    The video pipeline currently mints 48 shots / ~200s and the rubric demands
    asset_diversity ≥ 6 *real* asset types to score above 80. If a candidate's
    source surface only supports 2 natural assets (a long-form blog post with
    one hero image, say), pushing it through the pipeline guarantees a
    "one image stretched across 3 minutes" video — that's the codex regression
    the user surfaced. Capacity is computed up-front so:

      1. ``score_candidate`` can deduct 8 points when capacity < 4 (drops the
         candidate from approve_candidate to review, flagging human attention).
      2. ``main.py`` can short-circuit ``--auto-close-loop`` to skip thin
         candidates instead of wasting a TTS run.
      3. The candidate JSON now carries ``visual_capacity_estimate`` and
         ``visual_capacity_sources`` so the source_review board shows it.

    Returns dict with ``estimate`` (int), ``sources`` (list[str], named
    surfaces we can actually capture), ``confidence`` ("high"/"medium"/"low").
    """
    source_type = str(candidate.get("source_type") or "").lower()
    signals = _normalize_signals(candidate.get("signals"))
    sources: list[str] = []
    confidence = "medium"

    if source_type == "github_repo":
        # ``visual_evidence_hunt`` always tries 8 focused capture points.
        # Issues / contributors / commits exist on every repo regardless of
        # README quality, so the floor is 8 *unique* surfaces. If the README
        # actually has images we add up to 4 more from ``readme_images`` (the
        # collector caps at 12 but realistically only the first 4 read well).
        sources.extend([
            "repo_overview", "readme_demos", "quickstart",
            "cli", "releases", "issues", "contributors", "commits",
        ])
        readme_image_hint = _as_int(signals.get("readme_image_count"), default=-1)
        if readme_image_hint > 0:
            sources.append("readme_images")
            confidence = "high"
        elif readme_image_hint == 0:
            confidence = "high"  # we KNOW the README is image-light
        # Stars: more stars usually means richer demos / releases / issues
        if _as_int(signals.get("stars"), default=0) >= 5_000:
            sources.append("active_pulse")
    elif source_type == "youtube_video":
        # Calibrated against yt_9d1a160bbcab regression: the old default
        # claimed 7-8 capacity (5 video frames + avatar + thumbnail), but
        # the actual pipeline doesn't download the source video — the only
        # thing we reliably ship is the thumbnail (URL is in meta) and
        # whatever we synthesise. The result was a 40-minute single-person
        # talking-head video being scored as if we had 8 distinct surfaces,
        # then producing 60 shots all using the same Peter half-body still.
        #
        # New rule: budget per *real* extractable surface, gated by the
        # signals we actually persist on meta.
        sources.append("thumbnail")  # always available — it's just a URL

        # Description chapters double as cue points. Each chapter gives us
        # a topical anchor we can either screenshot (if the host downloads
        # the video later) or replace with B-roll. We count up to 4 because
        # past that, frames become repetitive in a talking-head context.
        description = str(signals.get("description") or "")
        chapter_count = len(_TIMESTAMP_RE.findall(description))
        chapter_credit = min(chapter_count, 4) if chapter_count >= 2 else 0
        for i in range(chapter_credit):
            sources.append(f"chapter_{i + 1}")

        # ``audio_path``/``subtitles`` only exist when we actually downloaded
        # the source video (most candidates in our pipeline are
        # ``metadata_only_candidate``, so this branch rarely fires).
        if signals.get("audio_path") or signals.get("subtitles"):
            sources.extend(["video_frame_intro", "video_frame_mid", "video_frame_outro"])

        # Rich social proof → we can grab a comment screenshot. Keep this
        # narrow: pure view counts don't translate into visual variety.
        if _as_int(signals.get("comments"), default=0) >= 50:
            sources.append("comment_screenshot")

        # Talking-head penalty: long single-person interviews look identical
        # frame-to-frame. ``duration`` is in seconds when present; when
        # absent we fall back to the description-length heuristic (long
        # transcripts → likely long interview, < 4 chapters → not segmented).
        duration_s = _as_int(signals.get("duration"), default=0)
        is_long_interview = (
            duration_s >= 1500  # 25 minutes
            or (duration_s == 0 and len(description) >= 1500 and chapter_count < 4)
        )
        if is_long_interview and chapter_count < 4:
            # Strip back to the irreducible minimum (thumbnail) so the
            # score gate hits the thin path.
            sources = ["thumbnail"]
            confidence = "low"
        elif chapter_count >= 4 or signals.get("audio_path") or signals.get("subtitles"):
            confidence = "high"
        else:
            confidence = "medium"
    elif source_type in ("product_hunt", "show_hn", "hacker_news_show"):
        sources.extend([
            "launch_page_hero", "website_landing", "product_screenshot",
            "team_section", "feature_grid",
        ])
        if signals.get("demo_video_url"):
            sources.extend(["demo_frame_intro", "demo_frame_mid", "demo_frame_outro"])
            confidence = "high"
    elif source_type in ("blog", "newsletter", "community", "hacker_news"):
        # Pure-text sources are the riskiest. We can do hero + 1 inline figure
        # + author headshot — anything beyond is conjecture and usually ends
        # up being a recycled stock image.
        sources.extend(["article_hero", "author_avatar"])
        if signals.get("hero_image_url"):
            sources.append("inline_figure_1")
        if signals.get("has_diagrams"):
            sources.append("inline_figure_2")
        confidence = "low"
    else:
        sources.extend(["primary_screenshot"])
        confidence = "low"

    return {
        "estimate": len(sources),
        "sources": sources,
        "confidence": confidence,
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

    votes = _as_int(signals.get("votes"), default=0)
    points = _as_int(signals.get("points"), default=0)
    if votes >= 300:
        score += 10
        reasons.append("+10 product_votes_300")
    elif votes >= 100:
        score += 6
        reasons.append("+6 product_votes_100")
    if points >= 200:
        score += 10
        reasons.append("+10 community_points_200")
    elif points >= 50:
        score += 6
        reasons.append("+6 community_points_50")

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

    # Visual capacity gate — penalise thin candidates that can't sustain a
    # 3-minute video. Calibrated so a long single-person YouTube interview
    # with no chapters (the yt_9d1a160bbcab regression) lands in ``review``
    # rather than ``approve_candidate``: it had a +18 trust seed and +12
    # for views ≥ 250k, so the visual penalty needed to be ≥ 18 points to
    # actually move the decision band. Old gate (-8 only at <4) was too soft.
    capacity = estimate_visual_capacity(candidate)
    estimate = capacity["estimate"]
    if estimate >= 8:
        score += 5
        reasons.append(f"+5 visual_capacity_{estimate}_rich")
    elif estimate >= 6:
        score += 2
        reasons.append(f"+2 visual_capacity_{estimate}")
    elif estimate >= 4:
        reasons.append(f"+0 visual_capacity_{estimate}_borderline")
    elif estimate >= 2:
        score -= 18
        reasons.append(f"-18 visual_capacity_{estimate}_thin")
    else:
        # estimate == 0 or 1 (e.g. 40-min talking-head with no chapters)
        score -= 30
        reasons.append(f"-30 visual_capacity_{estimate}_starved")

    if not reasons:
        reasons.append("baseline_only")

    score = max(0, min(100, score))
    decision = decision_for_score(score)
    return {
        "score": score,
        "decision": decision,
        "score_reasons": reasons,
        "visual_capacity_estimate": capacity["estimate"],
        "visual_capacity_sources": capacity["sources"],
        "visual_capacity_confidence": capacity["confidence"],
    }


def score_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        result = score_candidate(candidate)
        item = dict(candidate)
        item["score"] = result["score"]
        item["decision"] = result["decision"]
        # Top-level visual capacity so the candidate review board / opportunity
        # engine can show "这条能撑起 N 张差异化素材" without re-deriving.
        item["visual_capacity_estimate"] = result["visual_capacity_estimate"]
        item["visual_capacity_sources"] = result["visual_capacity_sources"]
        item["visual_capacity_confidence"] = result["visual_capacity_confidence"]
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
