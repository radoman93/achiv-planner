from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.core.celery_app import celery_app
from app.core.logging import logger
from app.scraper.spiders import icy_veins_spider, reddit_spider, youtube_spider


@dataclass
class FallbackResult:
    achievement_id: str
    icy_veins_found: bool = False
    reddit_posts: list[dict[str, Any]] = field(default_factory=list)
    youtube_videos: list[dict[str, Any]] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


async def run_fallback_sources(achievement_id: str, achievement_name: str) -> FallbackResult:
    result = FallbackResult(achievement_id=str(achievement_id))

    icy_task = asyncio.create_task(
        icy_veins_spider.check_and_scrape(achievement_name, str(achievement_id))
    )
    reddit_task = asyncio.create_task(
        reddit_spider.search_achievement(achievement_name, str(achievement_id))
    )
    youtube_task = asyncio.create_task(
        youtube_spider.search_achievement(achievement_name, str(achievement_id))
    )

    icy, reddit_res, yt = await asyncio.gather(
        icy_task, reddit_task, youtube_task, return_exceptions=True
    )

    if isinstance(icy, Exception):
        result.errors["icy_veins"] = str(icy)
    else:
        result.icy_veins_found = icy is not None

    if isinstance(reddit_res, Exception):
        result.errors["reddit"] = str(reddit_res)
    else:
        result.reddit_posts = reddit_res or []

    if isinstance(yt, Exception):
        result.errors["youtube"] = str(yt)
    else:
        result.youtube_videos = yt or []

    logger.info(
        "fallback.complete",
        achievement_id=str(achievement_id),
        icy_veins=result.icy_veins_found,
        reddit_posts=len(result.reddit_posts),
        youtube_videos=len(result.youtube_videos),
        errors=list(result.errors.keys()),
    )
    return result


@celery_app.task(name="pipeline.scrape.fallback", queue="normal")
def run_fallback_task(achievement_id: str, achievement_name: str) -> dict:
    result = asyncio.run(run_fallback_sources(achievement_id, achievement_name))
    # Chain: trigger LLM enrichment
    celery_app.send_task(
        "pipeline.llm.enrich",
        args=[str(achievement_id)],
        queue="llm_enrichment",
    )
    return {
        "achievement_id": str(achievement_id),
        "icy_veins_found": result.icy_veins_found,
        "reddit_posts": len(result.reddit_posts),
        "youtube_videos": len(result.youtube_videos),
    }
