# Phase 1 — Backend Foundation

Depends on: Phase 0 fully complete.
Complete all tasks before starting Phase 2.
After each task, verify acceptance criteria and update docs/progress.md.

---

## TASK 1.1 — FastAPI Application Core

Set up the FastAPI application entry point and core infrastructure.

**File: `backend/app/main.py`**
- Create FastAPI app instance with title, description, version
- Mount CORS middleware — allow origin from `FRONTEND_URL` env var, allow credentials, all methods, all headers
- Mount request logging middleware — log method, path, status code, duration in ms as structured JSON
- Mount global exception handler — catch unhandled exceptions, return `{"error": "internal_server_error", "request_id": "..."}` with 500 status
- Add request ID middleware — generate UUID per request, attach to request state, include in all log lines and response headers as `X-Request-ID`

**File: `backend/app/core/config.py`**
Using Pydantic Settings, define all configuration:
- `DATABASE_URL` (async postgres URL)
- `REDIS_URL`
- `SECRET_KEY` (JWT signing)
- `ALGORITHM` (default: HS256)
- `ACCESS_TOKEN_EXPIRE_MINUTES` (default: 30)
- `REFRESH_TOKEN_EXPIRE_DAYS` (default: 7)
- `BATTLENET_CLIENT_ID`, `BATTLENET_CLIENT_SECRET`
- `ANTHROPIC_API_KEY`
- `FRONTEND_URL`
- `RAW_STORAGE_PATH` (default: /raw_storage)
- `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`
- `SENTRY_DSN` (optional)
- `ENVIRONMENT` (default: development)
Fail fast on startup if any required variable is missing.

**File: `backend/app/core/database.py`**
- Async SQLAlchemy engine using asyncpg
- Session factory (AsyncSession)
- `get_db()` dependency that yields a session and closes it after request
- `check_db_health()` async function that runs `SELECT 1`

**File: `backend/app/core/redis.py`**
- Async Redis connection pool
- `get_redis()` dependency
- `check_redis_health()` async function

**Health check endpoint: `GET /api/health`**
Returns:
```json
{
  "status": "ok",
  "db": "ok",
  "redis": "ok",
  "version": "0.1.0"
}
```
If any check fails, return 503 with the failing service marked "error".

**Startup validation:**
On app startup, verify DB and Redis connections. Log success or failure. Do not crash on failed connections — log the error and continue (the health endpoint will report degraded status).

**Acceptance:**
- `GET /api/health` returns 200 with all services ok when stack is running
- Returns 503 when postgres is stopped
- Request ID appears in response headers and log output
- CORS headers present on responses from allowed origin
- Missing required env var causes clear startup error message

---

## TASK 1.2 — SQLAlchemy Models

Write all SQLAlchemy ORM models in `backend/app/models/`.

**Requirements:**
- Use SQLAlchemy 2.0 declarative style with `DeclarativeBase`
- Use `Mapped` and `mapped_column` type annotations throughout
- All primary keys are UUID, generated server-side with `default=uuid4`
- All timestamps use `datetime` with `timezone=True`
- `created_at` defaults to `func.now()`, `updated_at` auto-updates via `onupdate=func.now()`
- JSONB columns use `JSON` type with postgresql dialect
- pgvector column uses `Vector(1536)` from `pgvector.sqlalchemy`

**Files to create:**
- `backend/app/models/__init__.py` — exports all models
- `backend/app/models/base.py` — DeclarativeBase and shared mixins (TimestampMixin with created_at/updated_at)
- `backend/app/models/zone.py` — Zone model
- `backend/app/models/achievement.py` — Achievement, AchievementCriteria, AchievementDependency models
- `backend/app/models/content.py` — Guide, Comment models
- `backend/app/models/user.py` — User, Character models
- `backend/app/models/progress.py` — UserAchievementState model
- `backend/app/models/route.py` — Route, RouteStop, RouteStep models
- `backend/app/models/pipeline.py` — PipelineRun, PatchEvent models

**Relationships to define:**
- `Achievement.zone` → Zone (many-to-one)
- `Achievement.criteria` → AchievementCriteria (one-to-many)
- `Achievement.guides` → Guide (one-to-many)
- `Achievement.comments` → Comment (one-to-many)
- `Achievement.dependencies` → AchievementDependency (one-to-many, foreign_keys=[required_achievement_id])
- `Achievement.dependents` → AchievementDependency (one-to-many, foreign_keys=[dependent_achievement_id])
- `User.characters` → Character (one-to-many)
- `Character.achievement_states` → UserAchievementState (one-to-many)
- `Route.stops` → RouteStop (one-to-many, ordered by session_number, sequence_order)
- `RouteStop.steps` → RouteStep (one-to-many, ordered by sequence_order)

Include `__repr__` on each model showing id and primary identifying field (name, etc.).

**Acceptance:**
- All models import without errors from `backend/app/models`
- A test script can insert and retrieve one record for each model
- Relationships load correctly (no DetachedInstanceError on access)
- No circular import issues

---

## TASK 1.3 — Authentication System

Implement full JWT authentication in `backend/app/core/auth.py` and `backend/app/api/auth.py`.

**JWT utilities (`backend/app/core/auth.py`):**
- `create_access_token(user_id, expires_delta)` → signed JWT
- `create_refresh_token(user_id)` → signed JWT with longer expiry
- `verify_token(token)` → decoded payload or raises HTTPException 401
- `get_password_hash(password)` → bcrypt hash
- `verify_password(plain, hashed)` → bool
- `get_current_user(token, db)` → User ORM object or 401
  - Injectable as FastAPI dependency via `Depends(get_current_user)`
- `get_current_active_user` — wraps get_current_user, also checks `is_active`

**Endpoints (`POST /api/auth/register`):**
- Body: `{email, password}`
- Validate email format, password minimum 8 chars
- Check email not already registered
- Hash password, create User record
- Return access token + refresh token in httpOnly cookies
- Return `{user_id, email, tier}` in body

**`POST /api/auth/login`:**
- Body: `{email, password}`
- Verify credentials
- Return access + refresh tokens in httpOnly cookies
- Return `{user_id, email, tier}` in body

**`POST /api/auth/refresh`:**
- Reads refresh token from httpOnly cookie
- Validates it, issues new access token
- Returns new access token in cookie

**`POST /api/auth/logout`:**
- Clears both token cookies
- Returns `{message: "logged out"}`

**Cookie settings:**
- `httpOnly=True`, `secure=True` (False in development), `samesite='lax'`
- Access token cookie: `max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60`
- Refresh token cookie: `max_age = REFRESH_TOKEN_EXPIRE_DAYS * 86400`

**Acceptance:**
- Full register → login → refresh → logout flow works end to end
- Protected route returns 401 without valid token
- Protected route returns 200 with valid token in cookie
- Expired token returns 401
- Invalid token returns 401

---

## TASK 1.4 — Battle.net OAuth Integration

Implement Battle.net OAuth2 in `backend/app/api/auth_battlenet.py` and `backend/app/services/battlenet.py`.

**OAuth flow:**

`GET /api/auth/battlenet?region=eu` (or us, kr, tw):
- Generate state parameter, store in Redis with 10-minute TTL
- Build Battle.net authorization URL with scopes: `wow.profile`
- Redirect user to Battle.net

`GET /api/auth/battlenet/callback?code=&state=&region=`:
- Validate state against Redis (prevent CSRF)
- Exchange code for access token via Battle.net token endpoint
- Fetch Battle.net account ID from `https://{region}.battle.net/oauth/userinfo`
- Check if user with this battlenet_id exists — if yes, log them in; if no, create new User
- Store battlenet_token and battlenet_token_expires_at on User
- Fetch character list (see below)
- Issue JWT tokens in httpOnly cookies
- Redirect to `{FRONTEND_URL}/onboarding` for new users, `/dashboard` for returning

**Battle.net service (`backend/app/services/battlenet.py`):**

`fetch_character_list(user, region)`:
- Call `https://{region}.api.blizzard.com/profile/user/wow`
- Parse WoW accounts → realms → characters
- For each character: upsert Character record (name, realm, level, class, race, faction)
- Return list of Character objects

`fetch_character_achievements(character, region)`:
- Call `https://{region}.api.blizzard.com/profile/wow/character/{realm}/{name}/achievements`
- Parse completion data
- Return structured achievement completion list

`refresh_battlenet_token(user)`:
- Check if token is within 5 minutes of expiry
- If so, use refresh token grant to get new token
- Update User record

**Acceptance:**
- Full OAuth round-trip completes (may need test with real Battle.net app credentials)
- State validation correctly rejects mismatched state
- New user created on first OAuth login
- Existing user logged in on subsequent OAuth login
- Character list populated after OAuth completion
- Token refresh works when token is near expiry

---

## TASK 1.5 — Celery Configuration

Configure Celery with four queues and Celery Beat scheduling.

**File: `backend/app/core/celery_app.py`:**
- Create Celery instance with Redis broker and backend
- Configure four queues: `high_priority`, `normal`, `llm_enrichment`, `sync`
- Set `task_default_queue = 'normal'`
- Set `task_routes`:
  - `pipeline.scrape.*` → `normal` (overrideable to `high_priority`)
  - `pipeline.llm.*` → `llm_enrichment`
  - `pipeline.sync.*` → `sync`
- Configure `task_serializer = 'json'`, `result_serializer = 'json'`
- Set `task_acks_late = True` (tasks re-queued if worker dies)
- Set `worker_prefetch_multiplier = 1` (fair distribution)
- Set result expiry to 24 hours

**Celery Beat schedule (`backend/app/core/celery_beat_schedule.py`):**
Define periodic tasks:
- `blizzard-skeleton-pass` — runs daily at 03:00 UTC, calls pipeline orchestrator Phase 1
- `scrape-coordinator` — runs every 6 hours, dispatches stale achievement scrapes
- `patch-monitor` — runs daily at 04:00 UTC
- `seasonal-window-monitor` — runs daily at 06:00 UTC

**Worker entry point (`backend/celery_worker.py`):**
- Import celery app
- Auto-discover tasks from: `app.pipeline`, `app.scraper`, `app.services`

**Flower configuration:**
- Basic auth via `FLOWER_USER` and `FLOWER_PASSWORD` env vars
- Persistent state in Redis

**Rate limiting on llm_enrichment queue:**
- Max 50 tasks per minute (respect Anthropic API rate limits)
- Configure via `task_annotations` on LLM tasks

**Acceptance:**
- `celery -A celery_worker worker --loglevel=info -Q high_priority,normal,llm_enrichment,sync` starts without errors
- `celery -A celery_worker inspect active` shows workers on all queues
- `celery -A celery_worker beat --loglevel=info` starts without errors
- Flower dashboard accessible at port 5555 with basic auth
- A test task dispatched to each queue executes successfully
