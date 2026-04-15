from __future__ import annotations

from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from app.core.logging import logger
from app.scraper import raw_storage

CONFIDENCE_BASE = 0.75
SEARCH_URL = "https://www.icy-veins.com/wow/search?q={q}"
USER_AGENT = "Mozilla/5.0 (compatible; WoWAchievementOptimizer/1.0)"


async def check_and_scrape(achievement_name: str, achievement_id: str) -> Optional[str]:
    headers = {"User-Agent": USER_AGENT}
    url = SEARCH_URL.format(q=quote_plus(achievement_name))
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("icy_veins.search_failed", achievement_id=achievement_id, error=str(exc))
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        # Find first achievement-related guide result
        guide_link = None
        for a in soup.select("a"):
            href = a.get("href", "")
            title = a.get_text(" ", strip=True).lower()
            if not href or "/wow/" not in href:
                continue
            if achievement_name.lower() in title or "achievement" in title:
                if href.startswith("/"):
                    href = "https://www.icy-veins.com" + href
                guide_link = href
                break

        if not guide_link:
            return None

        try:
            guide_resp = await client.get(guide_link)
            guide_resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("icy_veins.fetch_failed", url=guide_link, error=str(exc))
            return None

        gsoup = BeautifulSoup(guide_resp.text, "html.parser")
        article = gsoup.select_one("article.page-content") or gsoup.select_one("#main")
        if not article:
            return None

        # Strip ads / nav / related
        for sel in ["nav", ".ads", ".ad", ".related", ".sidebar", "script", "style"]:
            for el in article.select(sel):
                el.decompose()

        content = str(article)
        raw_storage.store_raw(
            "icy_veins",
            str(achievement_id),
            content,
            metadata={
                "url": guide_link,
                "confidence_base": CONFIDENCE_BASE,
                "achievement_name": achievement_name,
            },
        )
        return content
