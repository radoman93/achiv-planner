from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from app.core.logging import logger
from app.scraper import raw_storage

CONFIDENCE_BASE = 0.50
SEARCH_URL = (
    "https://www.reddit.com/r/wow+wowachievements/search.json"
    "?q={q}&sort=relevance&limit=5&restrict_sr=1"
)
HEADERS = {"User-Agent": "WoWAchievementOptimizer/1.0 (contact@yourdomain.com)"}
MIN_SCORE = 10
MAX_AGE_YEARS = 4


async def search_achievement(achievement_name: str, achievement_id: str) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * MAX_AGE_YEARS)
    async with httpx.AsyncClient(timeout=20.0, headers=HEADERS) as client:
        try:
            resp = await client.get(SEARCH_URL.format(q=quote_plus(achievement_name)))
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("reddit.search_failed", achievement_id=achievement_id, error=str(exc))
            return []

        try:
            search = resp.json()
        except json.JSONDecodeError:
            return []

        results: list[dict[str, Any]] = []
        for child in search.get("data", {}).get("children", []):
            post = child.get("data", {})
            score = int(post.get("score") or 0)
            created_utc = float(post.get("created_utc") or 0)
            created_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
            if score <= MIN_SCORE or created_dt < cutoff:
                continue

            permalink = post.get("permalink")
            post_url = f"https://www.reddit.com{permalink}.json" if permalink else None
            top_comments: list[dict[str, Any]] = []
            if post_url:
                try:
                    pr = await client.get(post_url)
                    pr.raise_for_status()
                    payload = pr.json()
                    if isinstance(payload, list) and len(payload) > 1:
                        for c in payload[1].get("data", {}).get("children", [])[:10]:
                            cd = c.get("data", {})
                            if cd.get("body"):
                                top_comments.append(
                                    {
                                        "body": cd.get("body"),
                                        "score": cd.get("score"),
                                        "author": cd.get("author"),
                                    }
                                )
                except (httpx.HTTPError, json.JSONDecodeError):
                    pass

            item = {
                "title": post.get("title"),
                "body": post.get("selftext"),
                "top_comments": top_comments,
                "score": score,
                "created_utc": created_utc,
                "url": f"https://www.reddit.com{permalink}" if permalink else post.get("url"),
            }
            raw_storage.store_raw(
                "reddit",
                str(achievement_id),
                json.dumps(item, indent=2),
                metadata={
                    "url": item["url"],
                    "confidence_base": CONFIDENCE_BASE,
                    "score": score,
                    "achievement_name": achievement_name,
                },
            )
            results.append(item)
        return results
