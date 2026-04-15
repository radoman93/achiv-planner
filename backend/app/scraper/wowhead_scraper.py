from __future__ import annotations

import asyncio
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup

from app.core.celery_app import celery_app
from app.core.logging import logger
from app.scraper import raw_storage

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
]

MIN_DELAY = 2.5
MAX_DELAY = 5.0
CLOUDFLARE_PAUSE_KEY = "scraper:wowhead:cloudflare_pause_until"
CLOUDFLARE_BLOCK_COUNTER_KEY = "scraper:wowhead:cloudflare_blocks"


@dataclass
class CommentData:
    text: str
    author: Optional[str]
    date: Optional[str]
    upvotes: int = 0


@dataclass
class WowheadAchievementData:
    achievement_id: int
    name: Optional[str] = None
    category_breadcrumb: list[str] = field(default_factory=list)
    zone_tags: list[str] = field(default_factory=list)
    related_quest_ids: list[int] = field(default_factory=list)
    related_npc_ids: list[int] = field(default_factory=list)
    has_guide: bool = False
    guide_html: Optional[str] = None
    comments: list[CommentData] = field(default_factory=list)
    related_achievement_ids: list[int] = field(default_factory=list)
    faction: Optional[str] = None
    scrape_status: str = "success"


class BrowserPool:
    """Maintains a pool of Playwright browser instances for concurrent scraping."""

    def __init__(self, size: int = 3):
        self.size = size
        self._playwright = None
        self._browsers: list = []
        self._sem = asyncio.Semaphore(size)
        self._lock = asyncio.Lock()
        self._initialized = False
        self._last_request_at = 0.0

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            for _ in range(self.size):
                browser = await self._playwright.chromium.launch(headless=True)
                self._browsers.append(browser)
            self._initialized = True

    async def close(self) -> None:
        async with self._lock:
            for b in self._browsers:
                try:
                    await b.close()
                except Exception:
                    pass
            self._browsers.clear()
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            self._initialized = False

    @asynccontextmanager
    async def acquire(self):
        await self.initialize()
        async with self._sem:
            # Enforce minimum interval between requests
            async with self._lock:
                now = time.time()
                elapsed = now - self._last_request_at
                min_interval = MIN_DELAY
                if elapsed < min_interval:
                    await asyncio.sleep(min_interval - elapsed)
                self._last_request_at = time.time()
            browser = random.choice(self._browsers)
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport=random.choice(VIEWPORTS),
            )
            try:
                yield context
            finally:
                await context.close()


_pool: Optional[BrowserPool] = None


def get_pool() -> BrowserPool:
    global _pool
    if _pool is None:
        _pool = BrowserPool(size=3)
    return _pool


async def _check_cloudflare_pause() -> bool:
    from app.core.redis import get_redis_client

    redis = get_redis_client()
    try:
        val = await redis.get(CLOUDFLARE_PAUSE_KEY)
        if not val:
            return False
        try:
            until = float(val)
        except ValueError:
            return False
        return time.time() < until
    finally:
        await redis.close()


async def _record_cloudflare_block() -> None:
    from app.core.redis import get_redis_client

    redis = get_redis_client()
    try:
        count = await redis.incr(CLOUDFLARE_BLOCK_COUNTER_KEY)
        await redis.expire(CLOUDFLARE_BLOCK_COUNTER_KEY, 600)
        if count >= 5:
            until = time.time() + 3600
            await redis.set(CLOUDFLARE_PAUSE_KEY, str(until), ex=3600)
            await redis.delete(CLOUDFLARE_BLOCK_COUNTER_KEY)
            logger.critical("wowhead.cloudflare_pause_triggered", until=until)
    finally:
        await redis.close()


async def _reset_cloudflare_counter() -> None:
    from app.core.redis import get_redis_client

    redis = get_redis_client()
    try:
        await redis.delete(CLOUDFLARE_BLOCK_COUNTER_KEY)
    finally:
        await redis.close()


def _is_cloudflare_challenge(html: str) -> bool:
    markers = ["Just a moment...", "Checking your browser", "cf-browser-verification", "cf-challenge"]
    return any(m in html for m in markers)


def _parse_html(achievement_id: int, html: str, url: str) -> WowheadAchievementData:
    soup = BeautifulSoup(html, "html.parser")
    data = WowheadAchievementData(achievement_id=achievement_id)

    title_el = soup.select_one("h1.heading-size-1")
    if title_el:
        data.name = title_el.get_text(strip=True)

    breadcrumb = [a.get_text(strip=True) for a in soup.select(".breadcrumb a")]
    data.category_breadcrumb = breadcrumb

    for infobox_line in soup.select(".infobox-data-line, .infobox li"):
        text = infobox_line.get_text(" ", strip=True)
        lower = text.lower()
        if lower.startswith("location") or lower.startswith("zone"):
            zones = [a.get_text(strip=True) for a in infobox_line.select("a")]
            data.zone_tags.extend(zones)
        if "alliance" in lower and "only" in lower:
            data.faction = "Alliance"
        elif "horde" in lower and "only" in lower:
            data.faction = "Horde"

    for link in soup.select('a[href*="/quest="]'):
        href = link.get("href", "")
        try:
            qid = int(href.split("/quest=")[1].split("/")[0].split("#")[0].split("?")[0])
            if qid not in data.related_quest_ids:
                data.related_quest_ids.append(qid)
        except (ValueError, IndexError):
            continue
    for link in soup.select('a[href*="/npc="]'):
        href = link.get("href", "")
        try:
            nid = int(href.split("/npc=")[1].split("/")[0].split("#")[0].split("?")[0])
            if nid not in data.related_npc_ids:
                data.related_npc_ids.append(nid)
        except (ValueError, IndexError):
            continue
    for link in soup.select('a[href*="/achievement="]'):
        href = link.get("href", "")
        try:
            aid = int(href.split("/achievement=")[1].split("/")[0].split("#")[0].split("?")[0])
            if aid != achievement_id and aid not in data.related_achievement_ids:
                data.related_achievement_ids.append(aid)
        except (ValueError, IndexError):
            continue

    guide_tab = soup.select_one('a[data-tab="guide"]') or soup.select_one('a[href="#guide"]')
    data.has_guide = guide_tab is not None
    guide_div = soup.select_one("#guide") or soup.select_one(".guide-container")
    if guide_div:
        data.guide_html = str(guide_div)

    return data


async def _extract_comments(page) -> list[CommentData]:
    comments: list[CommentData] = []
    # Click through "Load more" style pagination a bounded number of times
    for _ in range(20):
        load_more = await page.query_selector('a.comment-load-more, button.comment-load-more')
        if not load_more:
            break
        try:
            await load_more.click()
            await page.wait_for_timeout(1200)
        except Exception:
            break

    elements = await page.query_selector_all(".comment, .comments-comment")
    for el in elements:
        try:
            text_el = await el.query_selector(".comment-body, .comments-comment-body")
            text = (await text_el.inner_text()).strip() if text_el else ""
            author_el = await el.query_selector(".comment-author, .comments-comment-author")
            author = (await author_el.inner_text()).strip() if author_el else None
            date_el = await el.query_selector(".comment-date, time")
            date = (await date_el.get_attribute("datetime")) if date_el else None
            if not date and date_el:
                date = (await date_el.inner_text()).strip()
            rating_el = await el.query_selector(".comment-rating, .rating")
            rating_txt = (await rating_el.inner_text()).strip() if rating_el else "0"
            try:
                upvotes = int("".join(c for c in rating_txt if c.isdigit() or c == "-") or 0)
            except ValueError:
                upvotes = 0
            if text:
                comments.append(CommentData(text=text, author=author, date=date, upvotes=upvotes))
        except Exception as exc:  # noqa: BLE001
            logger.debug("wowhead.comment_parse_skipped", error=str(exc))
            continue
    return comments


async def scrape_achievement(achievement_id: int) -> Optional[WowheadAchievementData]:
    if await _check_cloudflare_pause():
        logger.warning("wowhead.scrape_skipped_cloudflare_pause", achievement_id=achievement_id)
        return None

    url = f"https://www.wowhead.com/achievement={achievement_id}"
    pool = get_pool()

    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    async with pool.acquire() as context:
        page = await context.new_page()
        try:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_selector("#main-contents", timeout=15000)
            except Exception as exc:
                logger.warning("wowhead.timeout", achievement_id=achievement_id, error=str(exc))
                html = await page.content()
                if _is_cloudflare_challenge(html):
                    await _record_cloudflare_block()
                    logger.warning("wowhead.cloudflare_blocked", achievement_id=achievement_id)
                    data = WowheadAchievementData(achievement_id=achievement_id)
                    data.scrape_status = "cloudflare_blocked"
                    return None
                data = WowheadAchievementData(achievement_id=achievement_id)
                data.scrape_status = "timeout"
                return None

            final_url = page.url
            title = (await page.title()) or ""
            if "Not Found" in title or "/error" in final_url:
                logger.info("wowhead.not_found", achievement_id=achievement_id)
                return None

            html = await page.content()
            if _is_cloudflare_challenge(html):
                await _record_cloudflare_block()
                logger.warning("wowhead.cloudflare_blocked", achievement_id=achievement_id)
                return None

            await _reset_cloudflare_counter()

            raw_storage.store_raw(
                "wowhead",
                str(achievement_id),
                html,
                metadata={"url": url},
            )

            data = _parse_html(achievement_id, html, url)

            if data.has_guide:
                try:
                    await page.click('a[data-tab="guide"]', timeout=3000)
                    await page.wait_for_timeout(800)
                    guide_el = await page.query_selector("#guide, .guide-container")
                    if guide_el:
                        data.guide_html = await guide_el.inner_html()
                except Exception:
                    pass

            data.comments = await _extract_comments(page)
            return data
        finally:
            await page.close()


# ---- Celery task wrapper ----

@celery_app.task(
    name="pipeline.scrape.wowhead",
    queue="normal",
    bind=True,
    max_retries=3,
    default_retry_delay=86400,
)
def scrape_wowhead_task(self, achievement_id: int) -> dict:
    """Celery sync wrapper around the async scraper."""
    try:
        result = asyncio.run(scrape_achievement(achievement_id))
    except Exception as exc:
        logger.exception("wowhead.scrape_task_error", achievement_id=achievement_id)
        raise self.retry(exc=exc)

    if result is None:
        return {"achievement_id": achievement_id, "status": "skipped_or_not_found"}

    # Chain: trigger comment processing
    celery_app.send_task(
        "pipeline.comments.process",
        args=[str(achievement_id)],
        queue="normal",
    )
    return {
        "achievement_id": achievement_id,
        "status": result.scrape_status,
        "name": result.name,
        "comment_count": len(result.comments),
    }
