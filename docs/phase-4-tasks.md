# Phase 4 — API Layer

Depends on: Phase 1 (auth), Phase 2 (data), Phase 3 (routing engine) all complete.
Complete all tasks before starting Phase 5.
After each task, verify acceptance criteria and update docs/progress.md.

All endpoints live under `/api/` prefix (Nginx routes this to FastAPI).
All authenticated endpoints require valid JWT in httpOnly cookie.
All responses use consistent envelope: `{"data": ..., "error": null}` or `{"data": null, "error": {"code": "...", "message": "..."}}`

---

## TASK 4.1 — Achievement API Endpoints

**File: `backend/app/api/achievements.py`**

**`GET /api/achievements`** — paginated achievement browser (public, no auth required)

Query params:
- `page` (int, default 1), `per_page` (int, default 20, max 100)
- `expansion` (string, optional)
- `category` (string, optional)
- `zone_id` (UUID, optional)
- `is_seasonal` (bool, optional)
- `requires_group` (bool, optional)
- `min_points` (int, optional), `max_points` (int, optional)
- `completed` (bool, optional — requires auth, filters by character_id)
- `character_id` (UUID, optional — required if completed filter used)

Response body:
```json
{
  "data": {
    "achievements": [...],
    "total": 5432,
    "page": 1,
    "per_page": 20,
    "total_pages": 272
  }
}
```

Each achievement in list: `{id, blizzard_id, name, category, subcategory, expansion, points, zone_name, is_seasonal, requires_group, confidence_tier, is_meta}`

---

**`GET /api/achievements/{id}`** — full achievement detail (public)

Response includes:
- All achievement fields
- Guide with steps (highest confidence guide for this achievement)
- Top 5 comments by combined_score
- Criteria list
- Dependencies (what this requires, what requires this)
- Confidence tier and score
- Last scraped timestamp

---

**`GET /api/achievements/search`** — full-text search (public)

Query params: `q` (string, required, min 2 chars), `limit` (int, default 10, max 50)

Uses PostgreSQL full-text search on achievement name + description.
Returns same shape as achievements list but with `relevance_score` added per result.
Debounce is handled frontend-side — backend simply processes whatever arrives.

---

**`GET /api/achievements/seasonal`** — seasonal achievements (public)

Query params: `status` ('active'|'upcoming'|'all', default 'all'), `days_ahead` (int, default 60)

Response:
```json
{
  "data": {
    "active": [...],
    "upcoming": [
      {
        "event_name": "Hallow's End",
        "opens_at": "2026-10-18",
        "closes_at": "2026-11-01",
        "days_until_open": 186,
        "achievement_count": 14
      }
    ]
  }
}
```

---

**`GET /api/achievements/{id}/guide`** — fetch guide for achievement (public)

Returns all guides for this achievement sorted by confidence_score descending.
Includes steps, community tips, source URL, confidence tier, scraped_at.

---

**Acceptance:**
- Pagination works correctly — page 2 returns different results than page 1
- All filter combinations work without SQL errors
- Search returns relevant results for "loremaster" query
- Seasonal endpoint correctly shows active events on a test date
- Achievement detail includes guide steps and comments
- Unauthenticated `completed` filter returns 401

---

## TASK 4.2 — Character API Endpoints

**File: `backend/app/api/characters.py`**

All endpoints require authentication.

**`GET /api/characters`** — list user's characters

Response: array of `{id, name, realm, faction, class, level, region, last_synced_at, achievement_completion_pct}`
`achievement_completion_pct` = completed count / total eligible count (cached on Character model, refreshed on sync)

---

**`POST /api/characters`** — create character manually (for users without Battle.net OAuth)

Body:
```json
{
  "name": "Thrall",
  "realm": "Silvermoon",
  "faction": "horde",
  "class": "shaman",
  "race": "orc",
  "level": 80,
  "region": "eu",
  "flying_unlocked": {
    "classic": true,
    "tbc": true,
    "wrath": true,
    "cata": true,
    "mop": true,
    "wod": true,
    "legion": true,
    "bfa": true,
    "shadowlands": false,
    "dragonflight": false,
    "the_war_within": false
  }
}
```

Validate: name 2-12 chars, realm not empty, faction in ['horde', 'alliance'], class in valid WoW class list.
Returns created character.

---

**`GET /api/characters/{id}`** — character detail

Includes:
- All character fields
- Achievement stats: total_completed, total_eligible, points_earned, completion_by_expansion (JSON)
- Active route summary (route_id, mode, stops_remaining) if exists

---

**`PUT /api/characters/{id}`** — update character fields

Allows updating: level, flying_unlocked, current_expansion.
Does NOT allow changing name/realm/faction/class (those are identity).

---

**`POST /api/characters/{id}/sync`** — trigger Battle.net achievement sync

Requires user to have Battle.net OAuth connected.
Queues a Celery sync task.
Response: `{"data": {"job_id": "celery-task-uuid", "status": "queued"}}`
Returns 400 if no Battle.net token on user.
Returns 429 if sync already in progress for this character.

---

**`GET /api/characters/{id}/sync/status/{job_id}`** — poll sync progress

Response:
```json
{
  "data": {
    "status": "in_progress",
    "progress": {
      "processed": 450,
      "total": 847,
      "percent": 53
    },
    "completed_at": null,
    "error": null
  }
}
```
Status values: `queued`, `in_progress`, `completed`, `failed`
Progress stored in Redis by the sync Celery task (key: `sync:progress:{job_id}`)

---

**`PUT /api/characters/{id}/preferences`** — update play preferences

Body: `{priority_mode, session_duration_minutes, solo_only}`
Validate: mode in valid modes list, duration 30-480, solo_only boolean.

---

**Acceptance:**
- Manual character creation validates all fields correctly
- Sync endpoint correctly queues Celery task and returns job_id
- Status polling shows progress as sync task updates Redis
- Status returns `completed` after sync task finishes
- Character detail shows accurate completion percentages
- Sync returns 429 if called while previous sync is still running

---

## TASK 4.3 — Route API Endpoints

**File: `backend/app/api/routes.py`**

All endpoints require authentication.

**`POST /api/routes/generate`** — generate a new route

Body:
```json
{
  "character_id": "uuid",
  "mode": "completionist",
  "constraints": {
    "solo_only": true,
    "expansion_filter": ["dragonflight", "the_war_within"],
    "zone_filter": null,
    "exclude_achievement_ids": []
  }
}
```

Processing:
1. Validate character belongs to current user
2. Check rate limit: free tier max 5 route generations per day (Redis counter, key: `rate:routes:{user_id}:{date}`)
3. Load all uncompleted achievements for character from `user_achievement_state`
4. Apply expansion/zone filters if provided
5. Run full routing pipeline (ConstraintFilter → DependencyResolver → ZoneGraph → GeographicClusterer → SessionStructurer → SeasonalOverride → RouteAssembler)
6. For MVP: run synchronously (route generation should complete in < 10 seconds for 500 achievements)
7. Return full route object

Response: full Route object (see Route shape below)

**Route response shape:**
```json
{
  "data": {
    "id": "uuid",
    "mode": "completionist",
    "created_at": "...",
    "overall_confidence": 0.72,
    "total_estimated_minutes": 840,
    "seasonal_block": {
      "stops": [...]
    },
    "sessions": [
      {
        "session_number": 1,
        "estimated_minutes": 118,
        "primary_zone": "Icecrown",
        "stops": [
          {
            "id": "uuid",
            "achievement": {
              "id": "uuid",
              "name": "...",
              "points": 10,
              "category": "..."
            },
            "zone": {"name": "Icecrown", "expansion": "wrath"},
            "estimated_minutes": 15,
            "confidence_tier": "high",
            "is_seasonal": false,
            "steps": [
              {"order": 1, "description": "...", "step_type": "travel", "location": "..."}
            ],
            "community_tips": ["...", "..."],
            "wowhead_url": "https://www.wowhead.com/achievement=...",
            "completed": false,
            "skipped": false
          }
        ]
      }
    ],
    "blocked_pool": [
      {
        "achievement_name": "...",
        "reason": "flying_required",
        "unlocker": "Complete Draenor Pathfinder"
      }
    ]
  }
}
```

---

**`GET /api/routes/{id}`** — fetch existing route

Returns same shape as generate response.
Returns 404 if route not found or belongs to different user.

---

**`GET /api/routes`** — list user's routes

Query params: `character_id` (optional filter), `status` ('active'|'archived'|'all', default 'active')
Response: array of route summaries (no sessions/stops — just metadata)

---

**`POST /api/routes/{id}/complete/{achievement_id}`** — mark achievement complete

Calls `Reoptimizer.mark_complete()`.
Response: `{success, newly_unblocked, session_adjustments}`
Returns 404 if stop not found in this route.
Returns 409 if already marked complete.

---

**`POST /api/routes/{id}/skip/{achievement_id}`** — mark achievement skipped

Calls `Reoptimizer.mark_skipped()`.
Response: `{success, achievement_id, session_time_freed}`
Returns 409 if already skipped.

---

**`POST /api/routes/{id}/reoptimize`** — full route reoptimization

Calls `Reoptimizer.full_reoptimize()`.
Returns 429 with `retry_after_seconds` if rate limited.
Returns new route on success.

---

**`DELETE /api/routes/{id}`** — archive route

Sets status = 'archived'. Does not delete from DB.
Response: `{success: true}`

---

**Acceptance:**
- Route generation completes in < 10 seconds for character with 300 uncompleted achievements
- Rate limiting correctly blocks 6th generation attempt on free tier
- Complete endpoint correctly updates stop and returns newly unblocked achievements
- Skip endpoint moves stop to deferred pool
- Reoptimize rate limit enforced (second call returns 429 with retry_after_seconds)
- Route belongs-to-user validation works (other user's route returns 404)

---

## TASK 4.4 — User API Endpoints

**File: `backend/app/api/users.py`**

All endpoints require authentication.

**`GET /api/users/me`** — current user profile

Response:
```json
{
  "data": {
    "id": "uuid",
    "email": "user@example.com",
    "tier": "free",
    "battlenet_connected": true,
    "battlenet_region": "eu",
    "priority_mode": "completionist",
    "session_duration_minutes": 120,
    "solo_only": false,
    "created_at": "..."
  }
}
```

---

**`PUT /api/users/me`** — update user preferences

Allowed fields: `priority_mode`, `session_duration_minutes`, `solo_only`
Returns updated user object.

---

**`GET /api/users/me/stats`** — aggregate achievement statistics

Response:
```json
{
  "data": {
    "total_achievement_points": 12450,
    "total_achievements_completed": 1834,
    "total_achievements_eligible": 4521,
    "overall_completion_pct": 40.6,
    "completion_by_expansion": {
      "classic": {"completed": 145, "total": 180, "pct": 80.6},
      "the_war_within": {"completed": 23, "total": 340, "pct": 6.8}
    },
    "estimated_hours_remaining": 284,
    "achievements_completed_this_month": 12,
    "favorite_category": "Quests"
  }
}
```

`estimated_hours_remaining` = sum of `estimated_minutes` for all uncompleted eligible achievements / 60
`favorite_category` = category with most completions

Use the materialized view `character_completion_stats` (created in Phase 7 Task 7.3) for performance.
If materialized view not ready: compute on the fly with appropriate query.

---

**`DELETE /api/users/me`** — delete account (GDPR compliance)

Requires password confirmation in body: `{"password": "..."}` (or `{"confirm": true}` for Battle.net-only accounts)

Cascade deletes (in order to respect FK constraints):
1. RouteSteps for user's routes
2. RouteStops for user's routes
3. Routes belonging to user
4. UserAchievementState for user's characters
5. Characters belonging to user
6. User record

After deletion: clear auth cookies, return `{"data": {"message": "account deleted"}}`.
Log deletion event (without PII) for audit purposes.

---

**Acceptance:**
- Stats return accurate numbers verified against known test data
- Account deletion cascades correctly — no orphaned records remain
- Account deletion with wrong password returns 401
- Battle.net connected status correctly reflects whether token exists on user
- Stats `favorite_category` correctly identified
- `estimated_hours_remaining` accurate within 10% (test with known data set)
