# Phase 6 — Background Jobs & Sync

Depends on: Phase 4 (API) and Phase 2 (scraping pipeline) fully complete.
Can run in parallel with Phase 5 (Frontend).
After each task, verify acceptance criteria and update docs/progress.md.

---

## TASK 6.1 — Achievement Sync Job

**File: `backend/app/services/sync_service.py`**
**File: `backend/app/pipeline/sync_tasks.py`**

**Celery task:**
`@celery_app.task(queue='sync', bind=True) sync_character_achievements(self, character_id: str, job_id: str)`

This task is triggered by `POST /api/characters/{id}/sync`.

**Pre-flight checks:**
1. Load Character from DB — if not found, fail with clear error message
2. Load User — verify Battle.net token exists and is not expired
3. If token expired: call `battlenet_client.refresh_token(user)` — if refresh fails, mark job as `failed` with reason `token_expired`, stop
4. Set Redis key `sync:lock:{character_id}` with TTL 3600 — if key already exists when task starts, abort (duplicate sync prevention)

**Progress tracking:**
Throughout the task, update Redis key `sync:progress:{job_id}` with:
```json
{
  "status": "in_progress",
  "processed": 0,
  "total": 0,
  "percent": 0,
  "started_at": "ISO timestamp"
}
```
Update `processed` count after every 50 achievements to avoid Redis write overhead.

**Sync steps:**

1. **Fetch from Blizzard:**
   - Call `battlenet_client.fetch_character_achievements(character, region)`
   - Response contains list of: `{achievement_id, completed_timestamp, criteria: [{id, amount}]}`
   - Store total count in progress tracker

2. **Diff against existing state:**
   - Load all existing `UserAchievementState` rows for this character (single query)
   - Build a dict: `{blizzard_achievement_id: state_row}`

3. **Process completions:**
   For each achievement in Blizzard response:
   - Look up Achievement by `blizzard_id` — if not found in our DB, skip (log the ID)
   - If state row doesn't exist: INSERT with `completed=True`, `completed_at=timestamp`
   - If state row exists and not completed but Blizzard says completed: UPDATE `completed=True`, `completed_at`
   - If state row has partial criteria: UPDATE `criteria_progress` JSON with latest amounts
   - Batch updates: collect all changes, write in batches of 100

4. **Handle newly completed achievements:**
   - For any achievement that transitions from incomplete to complete:
     - Check if it was a prerequisite for anything in the user's active route
     - If yes: dispatch `reoptimizer.mark_complete()` for the route (async, don't block sync)
   - Collect list of newly completed achievement IDs

5. **Update character record:**
   - Update `character.last_synced_at = now()`
   - Recalculate and update `character.achievement_completion_pct`
   - Update completion stats by expansion in a JSON field `character.stats_cache`

6. **Finalize progress:**
   Update Redis progress key to:
   ```json
   {
     "status": "completed",
     "processed": 847,
     "total": 847,
     "percent": 100,
     "completed_at": "ISO timestamp",
     "newly_completed_count": 3,
     "newly_completed_ids": ["uuid", "uuid", "uuid"]
   }
   ```

7. **Cleanup:**
   Delete `sync:lock:{character_id}` from Redis
   Set progress key TTL to 1 hour (for late polling)

**Error handling:**
- If Blizzard API returns 404 (character not found): mark job failed with reason `character_not_found`
- If Blizzard API rate limits: Celery auto-retry with exponential backoff (max 5 retries)
- If DB write fails: Celery retry (task is idempotent — duplicate writes are safe due to upsert)

**Acceptance:**
- Sync correctly inserts new completions not previously in DB
- Sync correctly updates partial criteria progress
- Progress Redis key updates as sync proceeds (verify with test that polls during sync)
- Lock key prevents concurrent syncs for same character
- Sync correctly identifies newly completed achievements and queues route update
- Character `last_synced_at` updated on completion
- On Blizzard 404, job status shows `failed` with clear reason

---

## TASK 6.2 — Scheduled Scrape Coordinator

**File: `backend/app/pipeline/scrape_coordinator.py`**

**Celery Beat task:**
`@celery_app.task(queue='high_priority') coordinate_scrapes()`
Scheduled: every 6 hours

**Purpose:** select the 50 most stale achievements and dispatch them for re-scraping. Never queue an achievement that's already queued.

**Staleness scoring:**
Staleness score is stored on Achievement as a float 0.0-1.0.
Score is calculated as:
- Base: `days_since_scrape / 30` (capped at 1.0) — an achievement not scraped in 30 days has staleness 1.0
- Multipliers that increase score: `* 1.5` if `patch_event` flagged within last 7 days, `* 1.3` if seasonal event opening within 14 days, `* 1.2` if confidence_score < 0.4 (low confidence data needs more frequent verification)
- Cap at 1.0

**Coordinator steps:**

1. **Check already-queued achievements:**
   - Redis set `scrape:queued` stores achievement IDs currently in the scrape queue
   - Achievements in this set are excluded from selection

2. **Select top 50 by staleness:**
   ```sql
   SELECT id, blizzard_id, staleness_score
   FROM achievements
   WHERE id NOT IN (queued set from Redis)
   ORDER BY staleness_score DESC
   LIMIT 50
   ```

3. **Dispatch each:**
   - `staleness_score > 0.8`: dispatch to `high_priority` queue
   - `staleness_score <= 0.8`: dispatch to `normal` queue
   - For each dispatched task: add achievement_id to Redis `scrape:queued` set with TTL 24h (auto-removes if task doesn't complete)
   - The scrape task itself removes achievement_id from `scrape:queued` on completion

4. **Log coordinator run:**
   ```json
   {
     "run_at": "ISO timestamp",
     "dispatched_count": 50,
     "high_priority_count": 12,
     "normal_count": 38,
     "skipped_already_queued": 8
   }
   ```
   Store in Redis key `scrape:coordinator:last_run` and append to a coordinator log (keep last 100 runs).

**Staleness score update:**
After each successful scrape+enrichment cycle, update achievement's `staleness_score` to 0.0 and `last_scraped_at` to now.

**Acceptance:**
- Coordinator selects 50 achievements, excluding already-queued ones
- High-staleness achievements go to high_priority queue (verified via Flower)
- Achievements added to `scrape:queued` set and removed on task completion
- Log entry created for each coordinator run
- Running coordinator twice in rapid succession doesn't double-queue achievements

---

## TASK 6.3 — Seasonal Window Monitor

**File: `backend/app/pipeline/seasonal_monitor.py`**

**Celery Beat task:**
`@celery_app.task(queue='high_priority') monitor_seasonal_windows()`
Scheduled: daily at 06:00 UTC

**Purpose:** detect seasonal events opening soon, trigger re-scrapes, and generate the daily seasonal status report consumed by the dashboard.

**Step 1 — Detect opening events (within 48 hours):**
```sql
SELECT DISTINCT seasonal_event, MIN(seasonal_start) as opens_at
FROM achievements
WHERE is_seasonal = TRUE
  AND seasonal_start BETWEEN NOW() AND NOW() + INTERVAL '48 hours'
GROUP BY seasonal_event
```

For each event found:
- Log: "Seasonal event '{event_name}' opens in {hours} hours"
- Fetch all achievements for this event
- For each: set `staleness_score = 1.0`, dispatch scrape task to `high_priority` queue
- This ensures seasonal achievement guides are fresh when the event opens

**Step 2 — Detect active events (currently open):**
```sql
SELECT DISTINCT seasonal_event, MIN(seasonal_start) as opens_at, MAX(seasonal_end) as closes_at
FROM achievements
WHERE is_seasonal = TRUE
  AND seasonal_start <= NOW()
  AND seasonal_end >= NOW()
GROUP BY seasonal_event
```

**Step 3 — Generate daily seasonal status report:**

Compute and store in Redis key `seasonal:daily_report` (TTL 25 hours):
```json
{
  "generated_at": "ISO timestamp",
  "active_events": [
    {
      "event_name": "Hallow's End",
      "opens_at": "2026-10-18",
      "closes_at": "2026-11-01",
      "days_remaining": 14,
      "achievement_count": 14,
      "is_critical": false
    }
  ],
  "opening_soon": [
    {
      "event_name": "Day of the Dead",
      "opens_at": "2026-11-01",
      "hours_until_open": 36
    }
  ],
  "upcoming_30_days": [...]
}
```

This report is consumed by:
- Dashboard seasonal banner (read directly from Redis — no DB query needed per request)
- `GET /api/achievements/seasonal` endpoint (falls back to DB if Redis key missing)

**Step 4 — Archive old seasonal data:**
For events that ended more than 7 days ago:
- These achievements don't need frequent scraping
- Set their `staleness_score` back to normal cadence
- Log count archived

**Acceptance:**
- Monitor correctly identifies events opening within 48 hours using simulated date
- High-priority re-scrapes dispatched for opening events
- Daily report correctly populated in Redis
- Dashboard banner reads from Redis report (verify by checking Redis key after monitor runs)
- Active event detection correct for mid-event simulated date
- Year-wrap events (e.g., Feast of Winter Veil: Dec 16 - Jan 2) correctly detected
