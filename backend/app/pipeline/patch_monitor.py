from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import feedparser
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logging import logger
from app.core.redis import get_redis_client
from app.models.achievement import Achievement
from app.models.pipeline import PatchEvent

RSS_SOURCES = [
    ("blizzard_news", "https://worldofwarcraft.blizzard.com/en-us/news/"),
    ("wowhead_news", "https://www.wowhead.com/news/rss"),
]
PATCH_TEXT_REGEX = re.compile(r"(\d+\.\d+(?:\.\d+)?)")
WOWHEAD_ACHIEVEMENT_REGEX = re.compile(r"achievement=(\d+)")
PATCH_KEYWORDS = ["patch", "hotfix", "update notes"]

LAST_RUN_KEY = "patch_monitor:last_run"
PROCESSED_URLS_KEY = "patch_monitor:processed_urls"
USER_AGENT = "Mozilla/5.0 (compatible; WoWAchievementOptimizer/1.0)"


def _entry_published(entry: Any) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None) or entry.get(attr)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _is_patch_article(title: str, summary: str) -> bool:
    blob = f"{title} {summary}".lower()
    return any(kw in blob for kw in PATCH_KEYWORDS)


async def _fetch_article(url: str) -> str:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        article = soup.find("article") or soup.body
        return article.get_text(" ", strip=True) if article else ""


def _extract_patch_version(text: str) -> str | None:
    m = PATCH_TEXT_REGEX.search(text)
    return m.group(1) if m else None


async def _load_achievement_name_index(session: AsyncSession) -> tuple[re.Pattern[str], dict[str, Achievement]]:
    q = await session.execute(select(Achievement).where(Achievement.is_legacy == False))  # noqa: E712
    achievements = list(q.scalars().all())
    by_lower_name = {a.name.lower(): a for a in achievements if a.name}
    # Build an alternation regex (escape + anchor on word boundaries, limit to reasonable names)
    names = sorted(by_lower_name.keys(), key=len, reverse=True)
    if not names:
        return re.compile("(?!x)x"), {}
    escaped = [re.escape(n) for n in names if len(n) >= 4]
    pattern = re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)
    return pattern, by_lower_name


async def _get_achievement_by_blizzard_id(session: AsyncSession, bid: int) -> Achievement | None:
    q = await session.execute(select(Achievement).where(Achievement.blizzard_id == bid))
    return q.scalar_one_or_none()


async def monitor_patches_async() -> dict[str, Any]:
    redis = get_redis_client()
    results: dict[str, Any] = {"articles_processed": 0, "matches": 0, "events": []}
    try:
        last_run_raw = await redis.get(LAST_RUN_KEY)
        last_run: datetime | None = None
        if last_run_raw:
            try:
                last_run = datetime.fromisoformat(last_run_raw)
            except ValueError:
                last_run = None

        async with AsyncSessionLocal() as session:
            name_regex, name_index = await _load_achievement_name_index(session)

            for source_name, rss_url in RSS_SOURCES:
                try:
                    async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": USER_AGENT}) as client:
                        resp = await client.get(rss_url)
                        resp.raise_for_status()
                        feed = feedparser.parse(resp.text)
                except Exception as exc:
                    logger.warning("patch_monitor.fetch_failed", source=source_name, error=str(exc))
                    continue

                for entry in feed.entries:
                    pub = _entry_published(entry)
                    if last_run and pub and pub <= last_run:
                        continue

                    title = entry.get("title", "") or ""
                    summary = entry.get("summary", "") or ""
                    if not _is_patch_article(title, summary):
                        continue

                    url = entry.get("link")
                    if not url:
                        continue
                    if await redis.sismember(PROCESSED_URLS_KEY, url):
                        continue

                    try:
                        body = await _fetch_article(url)
                    except Exception as exc:
                        logger.warning("patch_monitor.article_fetch_failed", url=url, error=str(exc))
                        continue

                    results["articles_processed"] += 1
                    await redis.sadd(PROCESSED_URLS_KEY, url)
                    await redis.expire(PROCESSED_URLS_KEY, 60 * 60 * 24 * 30)

                    full_text = f"{title}\n{body}"
                    patch_version = _extract_patch_version(title) or _extract_patch_version(full_text)

                    matched: set[str] = set()
                    # Match achievement IDs via wowhead link pattern
                    id_matches = {int(m) for m in WOWHEAD_ACHIEVEMENT_REGEX.findall(full_text)}
                    # Match by name
                    for nm in name_regex.findall(full_text):
                        matched.add(nm.lower())

                    # Resolve to Achievement rows
                    target_achievements: list[Achievement] = []
                    for bid in id_matches:
                        ach = await _get_achievement_by_blizzard_id(session, bid)
                        if ach:
                            target_achievements.append(ach)
                    for nm in matched:
                        ach = name_index.get(nm)
                        if ach and ach not in target_achievements:
                            target_achievements.append(ach)

                    for ach in target_achievements:
                        event = PatchEvent(
                            id=uuid4(),
                            achievement_id=ach.id,
                            patch_version=patch_version,
                            detected_at=datetime.now(timezone.utc),
                            source_url=url,
                        )
                        session.add(event)
                        ach.staleness_score = 1.0
                        celery_app.send_task(
                            "pipeline.scrape.wowhead",
                            args=[ach.blizzard_id],
                            queue="high_priority",
                        )
                        logger.info(
                            "patch_monitor.match",
                            achievement=ach.name,
                            patch_version=patch_version,
                            url=url,
                        )
                        results["matches"] += 1
                        results["events"].append(
                            {"achievement_id": str(ach.id), "patch_version": patch_version, "url": url}
                        )

            await session.commit()

        await redis.set(LAST_RUN_KEY, datetime.now(timezone.utc).isoformat())
    finally:
        await redis.close()

    return results


@celery_app.task(name="pipeline.patch.monitor", queue="high_priority")
def monitor_patches() -> dict[str, Any]:
    return asyncio.run(monitor_patches_async())
