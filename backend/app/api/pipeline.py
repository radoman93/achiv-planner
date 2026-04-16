import asyncio
import random

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.celery_app import celery_app

router = APIRouter()


@router.get("/debug-comments/{achievement_id}")
async def debug_comments(achievement_id: int):
    """Scrape a single achievement and return comment HTML structure for debugging."""
    from playwright.async_api import async_playwright

    url = f"https://www.wowhead.com/achievement={achievement_id}"
    result = {"url": url, "comment_selectors_found": {}, "sample_html": ""}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
        )
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector("#main-contents", timeout=15000)
            # Try multiple ways to load comments
            tab_clicked = False
            for tab_sel in ['#tab-comments', 'a[href="#comments"]', 'a[data-tab="comments"]',
                            'li.tabs-comments', '.tabs a:has-text("Comments")', 'a:has-text("Comments")']:
                try:
                    tab = await page.query_selector(tab_sel)
                    if tab:
                        await tab.click()
                        tab_clicked = True
                        result["tab_clicked"] = tab_sel
                        await page.wait_for_timeout(5000)
                        break
                except Exception:
                    continue

            if not tab_clicked:
                # Try navigating with #comments hash
                await page.goto(f"{url}#comments", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(5000)
                result["tab_clicked"] = "hash navigation"

            # Try many possible comment selectors
            selectors = [
                ".comment", ".comments-comment", ".comment-list",
                ".commentlist", "#comments", ".comment-body",
                ".comments", "[class*=comment]", ".listview-row",
                ".text", ".c-comment", "#tab-comments",
            ]
            for sel in selectors:
                count = len(await page.query_selector_all(sel))
                if count > 0:
                    result["comment_selectors_found"][sel] = count

            # Re-check selectors after clicking tab
            for sel in selectors:
                count = len(await page.query_selector_all(sel))
                if count > 0:
                    result["comment_selectors_found"][sel + " (after click)"] = count

            # Get the comments tab/section HTML
            comments_section = await page.query_selector("#tab-comments, #comments, .comment-list, .commentlist")
            if comments_section:
                result["sample_html"] = (await comments_section.inner_html())[:5000]
            else:
                # Get all elements with "comment" in class name
                els = await page.query_selector_all("[class*=comment]")
                if els:
                    samples = []
                    for el in els[:3]:
                        outer = await el.evaluate("el => el.outerHTML")
                        samples.append(outer[:500])
                    result["sample_html"] = "\n---\n".join(samples)
                else:
                    # Last resort: dump the page HTML around where comments might be
                    full_html = await page.content()
                    # Find "comment" keyword in HTML
                    idx = full_html.lower().find("comment")
                    if idx > 0:
                        result["sample_html"] = full_html[max(0, idx-200):idx+2000]
                    else:
                        # Dump raw page HTML snippets around comment-related content
                    full_html = await page.content()
                    result["sample_html"] = "No comment elements found. Page length: " + str(len(full_html))
                    # Find ALL occurrences of "comment" in HTML attributes
                    import re
                    classes = re.findall(r'class="([^"]*comment[^"]*)"', full_html, re.IGNORECASE)
                    result["comment_classes"] = list(set(classes))[:20]
                    ids = re.findall(r'id="([^"]*comment[^"]*)"', full_html, re.IGNORECASE)
                    result["comment_ids"] = list(set(ids))[:20]
                    # Find tab-related elements
                    tabs = re.findall(r'(?:data-tab|class)="([^"]*(?:tab|comment)[^"]*)"', full_html, re.IGNORECASE)
                    result["tab_attrs"] = list(set(tabs))[:20]

            result["page_title"] = await page.title()
        finally:
            await page.close()
            await browser.close()

    return JSONResponse(result)


@router.post("/trigger/full")
async def trigger_full_pipeline():
    result = celery_app.send_task("pipeline.orchestrator.run_full_pipeline")
    return JSONResponse({"task_id": result.id, "status": "queued"})


@router.post("/trigger/skeleton")
async def trigger_skeleton_pass():
    result = celery_app.send_task("pipeline.orchestrator.blizzard_skeleton_pass")
    return JSONResponse({"task_id": result.id, "status": "queued"})


@router.post("/trigger/scrape")
async def trigger_scrape_coordinator():
    result = celery_app.send_task("pipeline.orchestrator.scrape_coordinator")
    return JSONResponse({"task_id": result.id, "status": "queued"})


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    result = celery_app.AsyncResult(task_id)
    return JSONResponse({
        "task_id": task_id,
        "status": result.status,
        "result": str(result.result) if result.ready() else None,
    })
