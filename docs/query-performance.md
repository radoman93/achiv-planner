# Query Performance Audit

Last reviewed: 2026-04-21

This doc captures the query patterns the app relies on in hot paths and the
indexes that keep them fast. It pairs with migration `0003_performance_indexes.py`.

Indexes are intentionally composite + partial where the access pattern is
narrow (e.g., "uncompleted only", "non-legacy only") to keep the index small
and selective.

---

## 1. Uncompleted achievements for a character

**Used by:** route generator (every generation / reoptimize), dashboard progress
views, sync diff.

```sql
SELECT achievement_id
FROM user_achievement_state
WHERE character_id = $1 AND completed = FALSE;
```

**Index:** `idx_user_achievement_state_character_incomplete`
(character_id, achievement_id) WHERE completed = FALSE.

Partial index is critical here: the vast majority of rows for active players
have completed=TRUE, so a partial index keeps the "remaining work" query
fast and small. EXPLAIN should show *Index Scan* on the partial index with
no recheck.

---

## 2. Full route with stops + steps

**Used by:** GET /api/routes/{id}

```sql
SELECT * FROM routes WHERE id = $1;
SELECT * FROM route_stops WHERE route_id = $1 ORDER BY session_number, sequence_order;
SELECT * FROM route_steps WHERE route_stop_id IN (...) ORDER BY sequence_order;
```

**Index:** `idx_route_stops_route_session_sequence` on
(route_id, session_number, sequence_order). Covers ordering without a
separate sort step.

SQLAlchemy `selectinload(Route.stops)` issues the second query with an IN
clause; the existing FK index on `route_stops.route_id` keeps that fast.

---

## 3. Achievement search (full-text)

**Used by:** GET /api/achievements/search

```sql
SELECT *, ts_rank(ts_vector, plainto_tsquery('english', $1)) AS rank
FROM achievements
WHERE to_tsvector('english', coalesce(name,'') || ' ' || coalesce(description,''))
      @@ plainto_tsquery('english', $1)
ORDER BY rank DESC
LIMIT 10;
```

**Status:** no dedicated GIN index on the concatenated tsvector; the query
generates the tsvector inline, so the planner does a sequential scan on
achievements. For 20k rows this is acceptable (~30ms) but becomes a
bottleneck above ~50k rows.

**Future work:** add a generated column `search_vector tsvector GENERATED
ALWAYS AS (to_tsvector('english', ...)) STORED` with a GIN index on it.
Deferred because Alembic's DDL for generated columns requires raw SQL and
we don't yet have performance pressure.

---

## 4. Seasonal achievements active window

**Used by:** GET /api/achievements/seasonal, seasonal monitor

```sql
SELECT *
FROM achievements
WHERE is_seasonal = TRUE
  AND seasonal_start <= $1
  AND seasonal_end >= $1;
```

**Index:** `idx_achievements_seasonal_dates` on (seasonal_start,
seasonal_end) WHERE is_seasonal = TRUE.

Partial keeps the index minimal — only seasonal achievements live in it.

---

## 5. Top comments by score for an achievement

**Used by:** GET /api/achievements/{id} detail, comment processing pipeline

```sql
SELECT * FROM comments
WHERE achievement_id = $1
ORDER BY combined_score DESC
LIMIT 20;
```

**Index:** `idx_comments_achievement_score` on
(achievement_id, combined_score DESC). Enables index-only ordered retrieval.

---

## 6. Scrape coordinator staleness query

**Used by:** `pipeline.scrape.coordinate` every 6h

```sql
SELECT blizzard_id, staleness_score
FROM achievements
WHERE is_legacy = FALSE
ORDER BY staleness_score DESC
LIMIT 150;
```

**Index:** `idx_achievements_staleness` on staleness_score DESC WHERE
is_legacy = FALSE. Partial; is_legacy is a near-constant filter for this
workload.

---

## 7. Character completion dashboard

**Used by:** Dashboard summary card, character detail page.

Replaced with materialized view `character_completion_stats` (migration
0003). Refresh function `refresh_character_stats(char_id UUID)` is called
at the end of every sync job. Read path becomes:

```sql
SELECT total_completed, total_eligible, completion_pct, total_points, by_expansion
FROM character_completion_stats
WHERE character_id = $1;
```

This turns a multi-table aggregation (characters × user_achievement_state ×
achievements) into a single indexed row lookup. Cost on 1000 achievements:
< 1ms read, < 1s refresh.

---

## Connection pool

`create_async_engine` in `app/core/database.py`:
- pool_size=10
- max_overflow=20 (up to 30 concurrent connections)
- pool_timeout=30s
- pool_recycle=1800 (30 min)
- pool_pre_ping=True (health-check before checkout)

`pool_pre_ping` guards against stale connections after database restarts
or network blips — the small cost (1 roundtrip per checkout) is worth it
on a Celery worker fleet where connections idle for minutes at a time.
