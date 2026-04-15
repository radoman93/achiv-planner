from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.logging import logger
from app.scraper import raw_storage

CONFIDENCE_BASE = 0.35
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
MIN_VIEWS = 1000
MAX_AGE_YEARS = 4


async def search_achievement(achievement_name: str, achievement_id: str) -> list[dict[str, Any]]:
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        logger.info("youtube.skipped_no_api_key", achievement_id=achievement_id)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * MAX_AGE_YEARS)
    query = f"{achievement_name} wow achievement guide"

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            search_resp = await client.get(
                SEARCH_URL,
                params={
                    "key": api_key,
                    "q": query,
                    "maxResults": 5,
                    "type": "video",
                    "part": "snippet",
                },
            )
            search_resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("youtube.search_failed", achievement_id=achievement_id, error=str(exc))
            return []

        video_ids: list[str] = []
        for item in search_resp.json().get("items", []):
            vid = item.get("id", {}).get("videoId")
            if vid:
                video_ids.append(vid)
        if not video_ids:
            return []

        try:
            details_resp = await client.get(
                VIDEOS_URL,
                params={
                    "key": api_key,
                    "id": ",".join(video_ids),
                    "part": "snippet,statistics",
                },
            )
            details_resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("youtube.details_failed", achievement_id=achievement_id, error=str(exc))
            return []

        results: list[dict[str, Any]] = []
        for item in details_resp.json().get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            try:
                views = int(stats.get("viewCount", 0))
            except ValueError:
                views = 0
            published_at_str = snippet.get("publishedAt", "")
            try:
                published_dt = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
            except ValueError:
                published_dt = datetime.now(timezone.utc)

            if views < MIN_VIEWS or published_dt < cutoff:
                continue

            video = {
                "video_id": item.get("id"),
                "title": snippet.get("title"),
                "description": snippet.get("description"),
                "view_count": views,
                "published_at": published_at_str,
                "url": f"https://www.youtube.com/watch?v={item.get('id')}",
            }
            raw_storage.store_raw(
                "youtube",
                str(achievement_id),
                json.dumps(video, indent=2),
                metadata={
                    "url": video["url"],
                    "confidence_base": CONFIDENCE_BASE,
                    "view_count": views,
                    "achievement_name": achievement_name,
                },
            )
            results.append(video)
        return results
