from __future__ import annotations

import asyncio
import json
import math
import re
import statistics
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logging import logger
from app.models.achievement import Achievement
from app.models.content import Comment

PATCH_PATTERNS = [
    re.compile(r"\bpatch\s+(\d+\.\d+(?:\.\d+)?)\b", re.IGNORECASE),
    re.compile(r"\bin\s+(\d+\.\d+(?:\.\d+)?)\b", re.IGNORECASE),
    re.compile(r"\bas\s+of\s+(\d+\.\d+(?:\.\d+)?)\b", re.IGNORECASE),
]
EXPANSION_NAMES = [
    "Shadowlands",
    "Dragonflight",
    "The War Within",
    "Battle for Azeroth",
    "Legion",
    "Warlords of Draenor",
    "Mists of Pandaria",
    "Cataclysm",
    "Wrath of the Lich King",
    "The Burning Crusade",
]
EXPANSION_REGEX = re.compile("|".join(re.escape(n) for n in EXPANSION_NAMES), re.IGNORECASE)

TYPE_KEYWORDS: dict[str, list[str]] = {
    "route_tip": ["go to", "start at", "then", "next", "first", "coordinates", "waypoint"],
    "bug_report": ["broken", "bugged", "doesn't work", "not working", "fixed"],
    "correction": ["wrong", "outdated", "no longer", "actually", "incorrect"],
    "time_estimate": ["takes", "minutes", "hours", "quick", "fast", "long"],
    "group_note": ["group", "party", "raid", "solo", "alone", "friends"],
}

SOLO_PATTERNS = [r"\bsolo(?:ed|able)?\b", r"\bby myself\b", r"\balone\b", r"\bone[- ]?shot\b"]
GROUP_PATTERNS = [r"\brequires? (?:a )?group\b", r"\bneeds? (?:a )?group\b", r"\bcan't solo\b", r"\bcannot solo\b", r"\bneed (?:a )?party\b"]
SOLO_REGEX = re.compile("|".join(SOLO_PATTERNS), re.IGNORECASE)
GROUP_REGEX = re.compile("|".join(GROUP_PATTERNS), re.IGNORECASE)


def _recency_score(comment_date: datetime | None) -> float:
    if not comment_date:
        return 0.0
    now = datetime.now(timezone.utc)
    if comment_date.tzinfo is None:
        comment_date = comment_date.replace(tzinfo=timezone.utc)
    days_old = (now - comment_date).days
    if days_old < 0:
        days_old = 0
    return max(0.0, min(1.0, math.exp(-days_old / 180.0)))


def _vote_score(upvotes: int, median: float, use_absolute: bool) -> float:
    if use_absolute:
        # normalize small-count fallback to [0,1] via logistic
        return max(0.0, min(1.0, upvotes / (upvotes + 10) if upvotes >= 0 else 0.0))
    if upvotes + median <= 0:
        return 0.0
    return max(0.0, min(1.0, upvotes / (upvotes + median)))


def _detect_patch(text: str) -> str | None:
    for pattern in PATCH_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1)
    m = EXPANSION_REGEX.search(text)
    if m:
        return m.group(0)
    return None


def _classify(text: str) -> list[str]:
    lower = text.lower()
    types: list[str] = []
    for kind, keywords in TYPE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            types.append(kind)
    if not types:
        types.append("general")
    return types


def _find_contradictions(comments: list[Comment]) -> set[UUID]:
    solo_ids: list[UUID] = []
    group_ids: list[UUID] = []
    for c in comments:
        text = c.raw_text or ""
        has_solo = bool(SOLO_REGEX.search(text))
        has_group = bool(GROUP_REGEX.search(text))
        if has_solo and not has_group:
            solo_ids.append(c.id)
        elif has_group and not has_solo:
            group_ids.append(c.id)
    if solo_ids and group_ids:
        return set(solo_ids) | set(group_ids)
    return set()


async def _process_for_achievement(session: AsyncSession, achievement_id: str) -> dict:
    try:
        ach_uuid = UUID(str(achievement_id))
    except ValueError:
        logger.warning("comments.invalid_achievement_id", achievement_id=str(achievement_id))
        return {"status": "invalid_id"}

    result = await session.execute(
        select(Comment).where(Comment.achievement_id == ach_uuid)
    )
    comments: list[Comment] = list(result.scalars().all())
    if not comments:
        return {"status": "no_comments", "count": 0}

    upvotes = [c.upvotes or 0 for c in comments]
    use_absolute = len(comments) < 3
    median = float(statistics.median(upvotes)) if upvotes else 0.0

    contradictory_ids = _find_contradictions(comments)

    for c in comments:
        rec = _recency_score(c.comment_date)
        vote = _vote_score(c.upvotes or 0, median, use_absolute)
        combined = rec * 0.4 + vote * 0.6
        c.recency_score = rec
        c.vote_score = vote
        c.combined_score = combined
        c.patch_version_mentioned = _detect_patch(c.raw_text or "")
        types = _classify(c.raw_text or "")
        c.comment_type = json.dumps(types)
        c.is_contradictory = c.id in contradictory_ids
        c.is_processed = True

    if contradictory_ids:
        ach_q = await session.execute(
            select(Achievement).where(Achievement.id == ach_uuid)
        )
        ach = ach_q.scalar_one_or_none()
        if ach is not None:
            ach.confidence_score = max(ach.confidence_score or 0.0, 0.5)
            if (ach.confidence_score or 0.0) > 0.5:
                ach.confidence_score = 0.5
        logger.warning(
            "comments.contradiction_detected",
            achievement_id=str(achievement_id),
            flagged=len(contradictory_ids),
        )

    await session.commit()
    return {
        "status": "ok",
        "count": len(comments),
        "contradictions": len(contradictory_ids),
    }


async def process_comments_async(achievement_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        return await _process_for_achievement(session, achievement_id)


@celery_app.task(name="pipeline.comments.process", queue="normal")
def process_comments_task(achievement_id: str) -> dict:
    res = asyncio.run(process_comments_async(achievement_id))
    # Chain: if confidence is low (or unknown), trigger fallbacks; else enrichment
    async def _decide() -> dict:
        async with AsyncSessionLocal() as session:
            try:
                ach_uuid = UUID(str(achievement_id))
            except ValueError:
                return {"name": None, "confidence": 0.0}
            q = await session.execute(
                select(Achievement).where(Achievement.id == ach_uuid)
            )
            ach = q.scalar_one_or_none()
            if ach is None:
                return {"name": None, "confidence": 0.0}
            return {"name": ach.name, "confidence": ach.confidence_score or 0.0}

    info = asyncio.run(_decide())
    if info["name"] and info["confidence"] < 0.5:
        celery_app.send_task(
            "pipeline.scrape.fallback",
            args=[str(achievement_id), info["name"]],
            queue="normal",
        )
    else:
        celery_app.send_task(
            "pipeline.llm.enrich",
            args=[str(achievement_id)],
            queue="llm_enrichment",
        )
    return res
