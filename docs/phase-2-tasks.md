# Phase 2 — Scraping Pipeline

Depends on: Phase 0 and Phase 1 fully complete.
Complete all tasks before starting Phase 3.
After each task, verify acceptance criteria and update docs/progress.md.

---

## TASK 2.1 — Blizzard API Client

**File: `backend/app/scraper/blizzard_client.py`**

Implement a Python client for the Battle.net API using httpx (async).

**Authentication:**
- Client credentials OAuth2 flow for non-user-specific calls
- Token endpoint: `https://{region}.battle.net/oauth/token`
- Cache the token in Redis until 60 seconds before expiry
- Region defaults to 'us', configurable

**Methods to implement:**

`async get_all_achievements(region='us') -> list[dict]`:
- Endpoint: `https://{region}.api.blizzard.com/data/wow/achievement/index`
- Namespace: `static-{region}`
- Locale: `en_US`
- Returns paginated list — handle pagination automatically
- Returns list of `{id, name, description, points, category, ...}`
- Cache full response in Redis for 24 hours (key: `blizzard:achievements:index:{region}`)

`async get_achievement_detail(achievement_id: int, region='us') -> dict`:
- Endpoint: `https://{region}.api.blizzard.com/data/wow/achievement/{id}`
- Returns full detail including criteria array
- Cache in Redis for 6 hours (key: `blizzard:achievement:{id}:{region}`)

`async get_achievement_categories(region='us') -> list[dict]`:
- Endpoint: `https://{region}.api.blizzard.com/data/wow/achievement-category/index`
- Cache 24 hours

`async get_character_achievements(realm: str, character_name: str, token: str, region='us') -> dict`:
- User-specific endpoint using user's Battle.net token (not client credentials)
- Endpoint: `https://{region}.api.blizzard.com/profile/wow/character/{realm}/{character_name}/achievements`
- Returns completion status and criteria progress
- Do NOT cache (user-specific live data)

**Rate limiting:**
- Max 100 requests/second (Blizzard's limit)
- Implement token bucket rate limiter using Redis
- On 429 response: wait for `Retry-After` header value, then retry
- On 503 response: exponential backoff, max 5 retries
- Log every rate limit hit with achievement_id and timestamp

**Acceptance:**
- `get_all_achievements()` returns complete list (5000+ achievements expected)
- Rate limiter correctly throttles to 100 req/sec
- 429 responses handled with correct wait time
- Redis caching verified — second call returns cached response without HTTP request
- `get_character_achievements()` returns valid data with test credentials

---

## TASK 2.2 — Raw Storage Client

**File: `backend/app/scraper/raw_storage.py`**

Implement a filesystem-based raw content storage client.

**Storage path structure:**
`{RAW_STORAGE_PATH}/{source}/{achievement_id}/{timestamp}.html`

Sources: `wowhead`, `icy_veins`, `reddit`, `youtube`, `blizzard`

**Methods to implement:**

`store_raw(source: str, achievement_id: str, content: str, metadata: dict = None) -> str`:
- Writes content to correct path
- Creates directories if they don't exist
- Timestamp format: `YYYYMMDD_HHMMSS_ffffff` (microseconds for uniqueness)
- Also writes a `.meta.json` sidecar with: source, achievement_id, scraped_at, url, content_length, metadata dict
- Returns the full file path written

`get_raw(source: str, achievement_id: str, latest: bool = True) -> tuple[str, dict] | None`:
- If `latest=True`: returns content of most recent file + its metadata
- If `latest=False`: returns list of all available (timestamp, path) tuples
- Returns None if no files exist for this source+achievement

`raw_exists(source: str, achievement_id: str, max_age_hours: int = 720) -> bool`:
- Returns True if a raw file exists and is newer than max_age_hours
- Used by pipeline to skip re-scraping fresh content

`list_achievements_with_raw(source: str) -> list[str]`:
- Returns list of achievement_ids that have raw storage for this source

`cleanup_old_raw(max_age_days: int = 90)`:
- Deletes raw files older than max_age_days
- Logs count of files deleted per source
- Preserves the most recent file per source/achievement even if older than threshold

**Acceptance:**
- Store and retrieve cycle works with HTML content
- `raw_exists` correctly returns False for files older than max_age_hours
- `raw_exists` returns True for fresh files
- Cleanup deletes old files but preserves most recent per achievement
- Concurrent writes don't corrupt each other (use atomic write pattern: write to temp, rename)

---

## TASK 2.3 — Playwright Wowhead Scraper

**File: `backend/app/scraper/wowhead_scraper.py`**

Implement a Playwright-based scraper for Wowhead achievement pages.

**Setup:**
- Use `playwright.async_api`
- Maintain a browser pool (3 browser instances) to allow concurrent scraping
- User agent rotation — maintain a list of 10 real Chrome/Firefox user agents, rotate per request
- Viewport randomization — vary between common resolutions

**Main function:**
`async scrape_achievement(achievement_id: int) -> WowheadAchievementData | None`

**URL:** `https://www.wowhead.com/achievement={achievement_id}`

**Extraction steps:**
1. Navigate to page, wait for `#main-contents` to be present (timeout: 15s)
2. Detect Cloudflare challenge — if present, log the achievement_id as `cloudflare_blocked` and return None (do not crash)
3. Detect 404 — if page title contains "Not Found" or URL redirected to error page, return None with status `not_found`
4. Extract fields:
   - Page title (achievement name from `h1.heading-size-1`)
   - Category breadcrumb text (`.breadcrumb` links)
   - Zone tags from the infobox (look for "Location" or "Zone" labels)
   - Related quests — Wowhead relation box with quest IDs and names
   - Related NPCs — Wowhead relation box with NPC IDs and names
   - Whether guide tab exists (`a[data-tab="guide"]` present)
   - Guide HTML content if tab exists (click tab, wait for content, extract)
   - All comments — paginate through all comment pages:
     - Comment text, author, date, upvote count
     - Handle "Load more comments" button
   - Related achievements from sidebar (IDs and names)
   - Faction requirement if listed in infobox
5. Store raw HTML via `raw_storage.store_raw('wowhead', achievement_id, html)`
6. Return structured `WowheadAchievementData` dataclass

**Rate limiting:**
- Random delay between 2.5-5 seconds between requests
- Track request timestamps per domain, enforce minimum interval
- If 5 consecutive Cloudflare blocks detected, pause all Wowhead scraping for 1 hour

**WowheadAchievementData dataclass fields:**
`achievement_id, name, category_breadcrumb, zone_tags, related_quest_ids, related_npc_ids, has_guide, guide_html, comments (list of CommentData), related_achievement_ids, faction, scrape_status ('success'|'not_found'|'cloudflare_blocked'|'timeout')`

**CommentData dataclass fields:**
`text, author, date, upvotes`

**Celery task wrapper:**
`@celery_app.task(queue='normal') scrape_wowhead_task(achievement_id: int)`:
- Calls `scrape_achievement`
- On success: triggers comment processing task and stores structured data to DB guides table
- On failure: logs error, marks achievement for retry after 24h
- Max retries: 3

**Acceptance:**
- Correctly extracts guide and comments from 10 different achievement pages (test with IDs: 1, 6, 45, 500, 1000, 2000, 3000, 5000, 8000, 14153)
- 404 handling returns None without crash
- Cloudflare detection logs correctly without crash
- Raw HTML stored before parsing
- Random delays confirmed via request timestamp logs
- Comment pagination retrieves all comments (verify against Wowhead manually for one achievement)

---

## TASK 2.4 — Scrapy Spiders for Fallback Sources

**Directory: `backend/app/scraper/spiders/`**

Implement three fallback source scrapers.

**Spider 1: Icy Veins (`icy_veins_spider.py`)**

`check_and_scrape(achievement_name: str, achievement_id: str) -> str | None`:
- Search URL: `https://www.icy-veins.com/wow/search?q={achievement_name}`
- Fetch search results page
- Look for achievement-specific guide link in results
- If found: fetch the guide page, extract main content (`article.page-content`)
- Strip navigation, ads, related articles — keep only guide body
- Store via raw_storage with source='icy_veins', confidence base = 0.75
- Return raw content or None if no guide found

**Spider 2: Reddit (`reddit_spider.py`)**

`search_achievement(achievement_name: str, achievement_id: str) -> list[dict]`:
- Use Reddit's public JSON API (no auth required): `https://www.reddit.com/r/wow+wowachievements/search.json?q={achievement_name}&sort=relevance&limit=5&restrict_sr=1`
- Filter results: score > 10, created within last 4 years
- For each matching post: extract title, selftext, top 10 comments (fetch post JSON)
- Store each post via raw_storage with source='reddit', confidence base = 0.50
- Return list of `{title, body, top_comments, score, created_utc, url}`

`headers = {'User-Agent': 'WoWAchievementOptimizer/1.0 (contact@yourdomain.com)'}` — required by Reddit

**Spider 3: YouTube (`youtube_spider.py`)**

`search_achievement(achievement_name: str, achievement_id: str) -> list[dict]`:
- Use YouTube Data API v3 search endpoint
- API key from `YOUTUBE_API_KEY` env var
- Query: `{achievement_name} wow achievement guide`
- Max 5 results, type=video
- For each video: fetch video details (title, description, view count, published date)
- Filter: view count > 1000, published within last 4 years
- Store via raw_storage with source='youtube', confidence base = 0.35
- Return list of `{video_id, title, description, view_count, published_at, url}`

**Orchestration function:**
`async run_fallback_sources(achievement_id: str, achievement_name: str) -> FallbackResult`:
- Runs all three spiders concurrently via asyncio.gather
- Combines results
- Returns `FallbackResult` with sources found and their raw content paths

**Celery task:**
`@celery_app.task(queue='normal') run_fallback_task(achievement_id: str, achievement_name: str)`:
- Calls run_fallback_sources
- Triggers LLM enrichment task on completion

**Acceptance:**
- Icy Veins spider correctly finds and extracts guide for a known achievement (test: "Glory of the Raider")
- Reddit spider returns posts with score > 10 and correct subreddit filtering
- YouTube spider returns filtered results with descriptions
- All three run concurrently without blocking each other
- Raw storage populated with correct source tags
- Confidence base scores attached to stored metadata

---

## TASK 2.5 — Comment Processing Pipeline

**File: `backend/app/pipeline/comment_processor.py`**

**Celery task:**
`@celery_app.task(queue='normal') process_comments_task(achievement_id: str)`

**Processing steps per comment:**

1. **Recency score** — exponential decay:
   - `days_old = (now - comment_date).days`
   - `recency_score = exp(-days_old / 180)` (half-life 180 days)
   - Clamp to [0.0, 1.0]

2. **Vote score normalization:**
   - Get median upvote count for all comments on this achievement
   - `vote_score = upvotes / (upvotes + median)` (Wilson score approximation)
   - Achievements with < 3 comments: use absolute score instead

3. **Combined score:**
   - `combined_score = (recency_score * 0.4) + (vote_score * 0.6)`

4. **Patch version detection:**
   - Regex patterns to detect: `patch \d+\.\d+`, `in \d+\.\d+`, `as of \d+\.\d+`, expansion names (Shadowlands, Dragonflight, The War Within, etc.)
   - Store first detected version in `patch_version_mentioned`

5. **Comment type classification** (keyword-based, not LLM):
   - `route_tip`: contains "go to", "start at", "then", "next", "first", "coordinates", "waypoint"
   - `bug_report`: contains "broken", "bugged", "doesn't work", "not working", "fixed"
   - `correction`: contains "wrong", "outdated", "no longer", "actually", "incorrect"
   - `time_estimate`: contains "takes", "minutes", "hours", "quick", "fast", "long"
   - `group_note`: contains "group", "party", "raid", "solo", "alone", "friends"
   - `general`: default if no above keywords match
   - A comment can have multiple types — store as JSON array

6. **Contradiction detection:**
   - Check all comments on achievement for conflicting solo/group claims:
     - Comment A says "can be done solo" AND Comment B says "requires group"
   - If contradiction found: set `is_contradictory = True` on both comments
   - Set achievement `confidence_score` to max(current, 0.5) — cap at medium confidence
   - Log achievement_id to pipeline monitoring

7. **Batch processing:**
   - Load all comments for the achievement at once (not one by one)
   - Process as a batch — needed for contradiction detection and vote normalization
   - Upsert all processed comments to DB in a single transaction

**Acceptance:**
- Recency scores are higher for recent comments (verify with comments from 2024 vs 2020)
- Vote normalization produces scores between 0 and 1
- Patch version detection correctly extracts "10.2" from "as of patch 10.2"
- Contradiction detection flags comments with conflicting solo/group claims
- Batch upsert works for achievements with 200+ comments
- Processing 20 achievements completes without error

---

## TASK 2.6 — LLM Enrichment Task

**File: `backend/app/pipeline/llm_enrichment.py`**

**Celery task:**
`@celery_app.task(queue='llm_enrichment', rate_limit='50/m') enrich_achievement_task(achievement_id: str)`

**Input gathering:**
Load from raw_storage and DB for this achievement:
- Wowhead guide HTML (convert to plain text, strip HTML tags)
- Top 20 comments by combined_score
- Icy Veins guide text if available
- Reddit post text if available
- Blizzard API description and criteria text

**Prompt construction:**
Build a prompt that includes all source text and requests extraction of this exact JSON schema:
```json
{
  "primary_zone": "string or null",
  "secondary_zones": ["string"] or [],
  "instance_name": "string or null",
  "requires_flying": true/false/null,
  "requires_group": true/false,
  "min_group_size": integer or null,
  "estimated_minutes": integer or null,
  "estimated_minutes_range": [min, max] or null,
  "prerequisites_mentioned": ["string"],
  "steps": [
    {
      "order": integer,
      "description": "string",
      "location": "string or null",
      "step_type": "travel|interact|kill|collect|talk|wait|other",
      "source_excerpt": "3-5 words from source this was extracted from"
    }
  ],
  "community_tips": ["string"],
  "confidence_flags": ["string describing what was uncertain or inferred"]
}
```

**Prompt requirements (include these instructions verbatim in the prompt):**
- "Return null for any field where the information is not present in the provided sources"
- "Do not infer or guess — only extract what is explicitly stated"
- "source_excerpt must be 3-5 words that appear verbatim in the source text"
- "confidence_flags should list every field where you were uncertain or had to choose between conflicting sources"

**Claude API call:**
- Model: `claude-sonnet-4-20250514`
- Max tokens: 2000
- Temperature: 0 (deterministic extraction)
- Include all source text in user message

**Validation before storage:**
- Parse JSON response
- Verify `source_excerpt` values actually appear in source text (substring check) — if not, null that step's source_excerpt and add to confidence_flags
- Verify estimated_minutes is reasonable (1 to 480) — if outside range, null it
- Verify zones mentioned exist in zones table — if not, add to confidence_flags

**Calculate final confidence score:**
- Start at base score from highest-confidence source used
- Subtract 0.1 for each confidence_flag
- Subtract 0.2 if no steps extracted
- Subtract 0.15 if primary_zone is null
- Clamp to [0.1, 1.0]

**Storage:**
- Create Guide record with all extracted fields
- Update Achievement record: estimated_minutes, requires_flying, requires_group, min_group_size, confidence_score, last_scraped_at

**Acceptance:**
- Enrichment produces valid JSON for 10 test achievements
- Null fields appear for thin achievements rather than invented content
- source_excerpt validation correctly catches fabricated excerpts
- Confidence score correctly lower for achievements with many confidence_flags
- Achievement record updated after enrichment
- LLM rate limit of 50/min enforced by Celery

---

## TASK 2.7 — Pipeline Orchestrator

**File: `backend/app/pipeline/orchestrator.py`**

**Main orchestration task:**
`@celery_app.task(queue='high_priority') run_full_pipeline(force_rescrape: bool = False)`

**Phase 1 — Skeleton pass:**
1. Call `blizzard_client.get_all_achievements()`
2. For each returned achievement:
   - Check if it exists in DB by `blizzard_id`
   - If new: insert Achievement record, flag as `needs_scrape = True`
   - If existing: compare name, description, points — if changed, flag `needs_scrape = True`, log the change
   - If missing from API but in DB: mark `is_legacy = True`
3. Log totals: new, updated, legacy-marked, unchanged

**Phase 2-4 — Per-achievement scraping:**
For each achievement flagged `needs_scrape` (or all if `force_rescrape=True`):
1. Check `raw_storage.raw_exists('wowhead', achievement_id, max_age_hours=720)` — skip if fresh and not force
2. Determine queue: `high_priority` if `staleness_score > 0.8` or `patch_event` flagged, else `normal`
3. Dispatch `scrape_wowhead_task.apply_async(queue=queue_name)`
4. Track dispatched task IDs

**Dependency tracking between phases:**
- Wowhead scrape task on completion triggers `process_comments_task`
- Comment processing on completion checks: does achievement have fallback sources? If confidence < 0.5, dispatch `run_fallback_task`
- Fallback task on completion (or if skipped) dispatches `enrich_achievement_task`
- Implement this chain using Celery's `link` parameter on task dispatch

**Pipeline run logging:**
Create `PipelineRun` record at start. Update throughout:
- `achievements_processed` incremented per completed achievement
- `achievements_errored` incremented per failed achievement
- `phases_completed` JSON updated as phases finish
- `completed_at` set when all dispatched tasks finish (use Celery chord or manual tracking via Redis counter)

**Error rate monitoring:**
After processing each batch of 50 achievements:
- Calculate error rate: `errors / (processed + errors)`
- If error rate > 0.10: log critical alert, write to `pipeline_runs.error_log`
- Continue processing — do not abort

**Acceptance:**
- Full pipeline run on 50 achievements completes in correct phase order
- New achievements in Blizzard API get inserted
- Changed achievements get re-scrape flag set
- Pipeline log shows accurate processed/errored counts
- Celery task chain correctly flows scrape → comments → fallback → enrichment
- Error in one achievement doesn't prevent others from processing

---

## TASK 2.8 — Patch Monitoring Task

**File: `backend/app/pipeline/patch_monitor.py`**

**Celery Beat task:**
`@celery_app.task(queue='high_priority') monitor_patches()`
Scheduled: daily at 04:00 UTC

**RSS sources to monitor:**
- Official WoW patch notes: `https://worldofwarcraft.blizzard.com/en-us/news/` (filter for "patch notes" articles)
- Wowhead news: `https://www.wowhead.com/news/rss` (filter for patch/hotfix articles)

**Processing:**
1. Fetch both RSS feeds via httpx
2. Parse with `feedparser` library
3. Filter entries published since last monitor run (store last run timestamp in Redis)
4. For each new entry:
   - Extract article full text (fetch URL, parse body)
   - Search for achievement mentions:
     - Match achievement names from DB (use a compiled regex alternation of all achievement names, case-insensitive)
     - Match achievement IDs in pattern `achievement=(\d+)` (Wowhead links)
   - For each match: extract matched achievement_id or look up by name

**For each matched achievement:**
1. Create `PatchEvent` record: achievement_id, patch_version (extracted from article title/text), source_url, detected_at
2. Set `achievement.staleness_score = 1.0` (maximum stale)
3. Dispatch `scrape_wowhead_task` to `high_priority` queue
4. Log: achievement name, patch version detected, source URL

**Store last run state:**
- Redis key: `patch_monitor:last_run` — timestamp of last successful run
- Redis key: `patch_monitor:processed_urls` — set of article URLs already processed (TTL: 30 days)

**Acceptance:**
- Monitor correctly identifies achievement mentions in simulated patch note HTML
- Correctly deduplicates URLs already processed
- PatchEvent records created for matched achievements
- High-priority re-scrape dispatched for affected achievements
- Last run timestamp updated after each successful run
