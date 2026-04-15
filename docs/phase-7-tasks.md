# Phase 7 — Hardening & Deployment

Depends on: All previous phases complete.
This is the final phase before the product is production-ready.
After each task, verify acceptance criteria and update docs/progress.md.

---

## TASK 7.1 — Error Handling & Logging

**File: `backend/app/core/logging.py`**
**File: `backend/app/core/sentry.py`**

**Structured logging setup with structlog:**

Configure structlog in `logging.py`:
- Output format: JSON in production, colored console in development (based on ENVIRONMENT env var)
- Processors chain: add timestamp, add log level, add request_id from context var, add service name, JSON serializer
- Bind logger to FastAPI request context — request_id flows through all log calls within a request

**Log levels and what goes where:**
- `DEBUG`: internal routing engine decisions (cluster choices, dependency resolution steps)
- `INFO`: request lifecycle, task starts/completions, sync progress milestones
- `WARNING`: rate limit hits, low confidence data detected, retry attempts
- `ERROR`: API call failures, DB errors, LLM API errors, task failures
- `CRITICAL`: pipeline error rate > 10%, DB connection lost, Redis connection lost

**What must be logged (structured fields, not strings):**

Every HTTP request:
```json
{
  "event": "request_completed",
  "request_id": "uuid",
  "method": "GET",
  "path": "/api/routes/generate",
  "user_id": "uuid or null",
  "status_code": 200,
  "duration_ms": 847
}
```

Every scraper run:
```json
{
  "event": "scrape_completed",
  "achievement_id": "uuid",
  "blizzard_id": 12345,
  "source": "wowhead",
  "success": true,
  "duration_ms": 3241,
  "guide_found": true,
  "comment_count": 47
}
```

Every LLM call:
```json
{
  "event": "llm_enrichment_completed",
  "achievement_id": "uuid",
  "model": "claude-sonnet-4-20250514",
  "prompt_tokens": 2847,
  "completion_tokens": 891,
  "duration_ms": 4102,
  "confidence_score": 0.72,
  "confidence_flags_count": 2,
  "steps_extracted": 7
}
```

Every Celery task:
```json
{
  "event": "celery_task_completed",
  "task_name": "scrape_wowhead_task",
  "task_id": "celery-uuid",
  "queue": "normal",
  "duration_ms": 5421,
  "success": true,
  "retries": 0
}
```

**Log rotation:**
Configure in Docker Compose — backend service logs via Docker's json-file logging driver:
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "100m"
    max-file: "5"
```
This keeps max 500MB of logs per service and auto-rotates.

**Sentry integration (`backend/app/core/sentry.py`):**
- Initialize Sentry SDK on app startup if `SENTRY_DSN` env var is set
- Sample rate: 1.0 for errors, 0.1 for performance traces
- Attach user_id to Sentry scope when authenticated requests fail
- Ignore 401 and 404 errors (not bugs — expected user errors)
- Configure before_send hook to scrub PII: mask email addresses, remove auth tokens from exception data

**Frontend error boundary:**
- Create `frontend/components/error-boundary.tsx`
- Catches React rendering errors, shows friendly "Something went wrong" UI
- Log to console in development
- Send to Sentry in production via `Sentry.captureException()`

**Acceptance:**
- All log lines are valid JSON in production mode
- `request_id` traces through: HTTP request log → DB query log → task dispatch log
- Sentry captures a manually triggered test exception with user context attached
- PII scrubbing verified: exception with email address in message has email masked in Sentry
- Log rotation confirmed: generating > 100MB of logs triggers rotation
- Frontend error boundary catches and displays React render errors gracefully

---

## TASK 7.2 — Rate Limiting & Security

**File: `backend/app/core/rate_limiter.py`**
**File: `backend/app/core/security_headers.py`**

**Rate limiting with slowapi:**

Configure limits as decorators on route handlers:

| Endpoint | Limit | Scope |
|---|---|---|
| `POST /api/auth/login` | 10/minute | per IP |
| `POST /api/auth/register` | 5/minute | per IP |
| `GET /api/achievements` | 100/minute | per IP (public) |
| `GET /api/achievements/search` | 60/minute | per IP |
| `POST /api/routes/generate` (free tier) | 5/day | per user_id |
| `POST /api/routes/generate` (pro tier) | 50/day | per user_id |
| `POST /api/routes/{id}/reoptimize` | 24/day (10 free) | per user_id |
| `POST /api/characters/{id}/sync` | 10/day | per character_id |
| All other authenticated endpoints | 300/minute | per user_id |

**Rate limit response format:**
```json
{
  "data": null,
  "error": {
    "code": "rate_limited",
    "message": "Too many requests. Try again in 47 seconds.",
    "retry_after_seconds": 47
  }
}
```
Return 429 status.

**Tier-aware rate limiting:**
For endpoints with different limits per tier, create a custom key function:
```python
def tier_key(request: Request) -> str:
    user = request.state.user  # set by auth middleware
    if user and user.tier == 'pro':
        return f"pro:{user.id}"
    elif user:
        return f"free:{user.id}"
    return f"anon:{request.client.host}"
```

**Security headers middleware (`security_headers.py`):**
Add to every response:
```
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
Content-Security-Policy: default-src 'self'; img-src 'self' https://wow.zamimg.com data:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'
```
Note: CSP `unsafe-inline` needed for Next.js inline scripts — document this as a known trade-off.

**CORS validation:**
Restrict to `FRONTEND_URL` env var — no wildcard in production.
For development: allow localhost:3000.

**Input validation hardening:**
- All request bodies validated by Pydantic (already enforced by FastAPI)
- Add explicit max length validators: achievement search query max 200 chars, character name max 12 chars
- Add payload size limit: reject bodies > 1MB (FastAPI middleware)
- Verify all UUIDs are valid UUIDs before DB query (Pydantic UUID type handles this)

**SQL injection note:**
SQLAlchemy ORM + parameterized queries already prevent SQL injection.
Audit any raw SQL (should be none — document this in a security notes file).

**Acceptance:**
- Rate limit correctly triggers and returns 429 with retry_after_seconds for all defined endpoints
- Pro tier users get higher limits than free tier users (verify with test)
- Login rate limit prevents brute force (10 attempts then blocked for remainder of minute)
- Security headers present on all API responses (verify with curl)
- CSP header present and correctly formed
- CORS rejects requests from non-allowed origins

---

## TASK 7.3 — Database Performance

**File: `backend/alembic/versions/add_performance_indexes.py`** (new migration)

**Add composite indexes:**

```sql
-- Most common query: all uncompleted achievements for a character
CREATE INDEX idx_user_achievement_state_character_incomplete
ON user_achievement_state (character_id, achievement_id)
WHERE completed = FALSE;

-- Route stop retrieval ordered by session and sequence
CREATE INDEX idx_route_stops_route_session_sequence
ON route_stops (route_id, session_number, sequence_order);

-- Achievement browsing by expansion and zone
CREATE INDEX idx_achievements_expansion_zone
ON achievements (expansion, zone_id);

-- Comment retrieval by achievement, sorted by score
CREATE INDEX idx_comments_achievement_score
ON comments (achievement_id, combined_score DESC);

-- Guide retrieval by achievement and confidence
CREATE INDEX idx_guides_achievement_confidence
ON guides (achievement_id, confidence_score DESC);

-- Seasonal achievement window queries
CREATE INDEX idx_achievements_seasonal_dates
ON achievements (seasonal_start, seasonal_end)
WHERE is_seasonal = TRUE;

-- Staleness score ordering for scrape coordinator
CREATE INDEX idx_achievements_staleness
ON achievements (staleness_score DESC)
WHERE is_legacy = FALSE;
```

**Materialized view for character stats:**
```sql
CREATE MATERIALIZED VIEW character_completion_stats AS
SELECT
    c.id AS character_id,
    COUNT(uas.id) FILTER (WHERE uas.completed = TRUE) AS total_completed,
    COUNT(uas.id) AS total_eligible,
    ROUND(COUNT(uas.id) FILTER (WHERE uas.completed = TRUE)::numeric / NULLIF(COUNT(uas.id), 0) * 100, 1) AS completion_pct,
    SUM(a.points) FILTER (WHERE uas.completed = TRUE) AS total_points,
    jsonb_object_agg(
        a.expansion,
        jsonb_build_object(
            'completed', COUNT(uas.id) FILTER (WHERE uas.completed = TRUE),
            'total', COUNT(uas.id)
        )
    ) AS by_expansion
FROM characters c
LEFT JOIN user_achievement_state uas ON uas.character_id = c.id
LEFT JOIN achievements a ON a.id = uas.achievement_id
GROUP BY c.id;

CREATE UNIQUE INDEX ON character_completion_stats (character_id);
```

Create a function to refresh this view:
```sql
CREATE OR REPLACE FUNCTION refresh_character_stats(char_id UUID)
RETURNS VOID AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY character_completion_stats;
END;
$$ LANGUAGE plpgsql;
```

Call this function at the end of every sync job.

**Database connection pooling:**
Configure SQLAlchemy engine pool in `backend/app/core/database.py`:
```python
engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,  # recycle connections every 30 minutes
    pool_pre_ping=True,  # verify connections before use
)
```

**Query performance audit:**
Write and run EXPLAIN ANALYZE for these 5 queries. If any shows a sequential scan on a table with > 1000 rows, add a covering index:
1. Fetch all uncompleted achievements for a character (used by route generator)
2. Fetch route with all stops and steps (used by GET /api/routes/{id})
3. Achievement search query (full-text)
4. Seasonal achievement active window query
5. Top comments by score for an achievement

Document results in `docs/query-performance.md`.

**Acceptance:**
- All indexes created via migration (verify with `\d achievements` in psql)
- Materialized view exists and refreshes without error
- Materialized view refresh via `refresh_character_stats()` completes in < 1 second for 1000 achievements
- EXPLAIN ANALYZE confirms index scans (not sequential scans) for all 5 audited queries
- Connection pool configured and `pool_pre_ping` working (broken connections auto-reconnected)

---

## TASK 7.4 — Deployment Scripts

**Files:**
- `deploy.sh`
- `backup.sh`
- `restore.sh`
- `health_check.sh`

---

**`deploy.sh`:**
```bash
#!/bin/bash
set -e  # exit on any error

echo "[deploy] Starting deployment $(date)"

# Pull latest code
git pull origin main

# Build changed images only
docker-compose build --no-cache backend frontend

# Run database migrations (non-destructive forward-only)
docker-compose run --rm backend alembic upgrade head

# Zero-downtime restart:
# 1. Start new backend container (Docker Compose handles this)
# 2. Wait for health check to pass
# 3. Old container removed automatically

docker-compose up -d --remove-orphans

# Wait for backend health
echo "[deploy] Waiting for backend health check..."
for i in {1..30}; do
    if curl -sf http://localhost/api/health > /dev/null 2>&1; then
        echo "[deploy] Backend healthy"
        break
    fi
    sleep 2
done

# Verify frontend is up
if ! curl -sf http://localhost > /dev/null 2>&1; then
    echo "[deploy] ERROR: Frontend not responding"
    exit 1
fi

echo "[deploy] Deployment complete $(date)"
```

---

**`backup.sh`:**
```bash
#!/bin/bash
set -e

BACKUP_DIR="/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="wow_optimizer_${TIMESTAMP}.sql.gz"

mkdir -p $BACKUP_DIR

echo "[backup] Starting database backup: $FILENAME"

docker-compose exec -T postgres pg_dump \
    -U ${POSTGRES_USER} \
    ${POSTGRES_DB} \
    | gzip > "${BACKUP_DIR}/${FILENAME}"

echo "[backup] Backup complete: ${BACKUP_DIR}/${FILENAME}"
echo "[backup] Size: $(du -sh ${BACKUP_DIR}/${FILENAME} | cut -f1)"

# Keep only last 30 backups
ls -t ${BACKUP_DIR}/*.sql.gz | tail -n +31 | xargs -r rm
echo "[backup] Old backups pruned. Total backups: $(ls ${BACKUP_DIR}/*.sql.gz | wc -l)"
```

Add to crontab: `0 2 * * * /path/to/backup.sh >> /var/log/wow-backup.log 2>&1`

---

**`restore.sh`:**
```bash
#!/bin/bash
set -e

if [ -z "$1" ]; then
    echo "Usage: ./restore.sh /path/to/backup.sql.gz"
    exit 1
fi

BACKUP_FILE=$1

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "[restore] WARNING: This will overwrite the current database!"
read -p "Type 'yes' to continue: " confirm
if [ "$confirm" != "yes" ]; then
    echo "[restore] Aborted."
    exit 0
fi

echo "[restore] Stopping backend services..."
docker-compose stop backend celery-worker celery-beat

echo "[restore] Restoring from: $BACKUP_FILE"
gunzip -c "$BACKUP_FILE" | docker-compose exec -T postgres psql \
    -U ${POSTGRES_USER} \
    -d ${POSTGRES_DB}

echo "[restore] Running migrations to ensure schema is current..."
docker-compose run --rm backend alembic upgrade head

echo "[restore] Restarting services..."
docker-compose start backend celery-worker celery-beat

echo "[restore] Restore complete. Verify application at http://localhost"
```

---

**`health_check.sh`:**
```bash
#!/bin/bash

PASS=0
FAIL=0

check() {
    local name=$1
    local url=$2
    local expected=$3

    response=$(curl -sf -o /dev/null -w "%{http_code}" "$url" 2>/dev/null)
    if [ "$response" = "$expected" ]; then
        echo "✓ $name ($response)"
        PASS=$((PASS + 1))
    else
        echo "✗ $name (expected $expected, got $response)"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== WoW Achievement Optimizer Health Check ==="
echo "$(date)"
echo ""

check "Nginx (port 80)"        "http://localhost/"              200
check "Backend API Health"     "http://localhost/api/health"    200
check "Frontend"               "http://localhost/"              200
check "Flower Dashboard"       "http://localhost/flower/"       200

# Check Docker services
echo ""
echo "=== Docker Services ==="
docker-compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || echo "docker-compose not available"

echo ""
echo "=== Summary ==="
echo "Passed: $PASS | Failed: $FAIL"

if [ $FAIL -gt 0 ]; then
    exit 1
fi
```

---

**README.md — Deployment section:**
Add a "Deployment" section to the root README with:
- Prerequisites (Docker, Docker Compose, git)
- Initial setup steps (clone, copy .env.example to .env, fill in values)
- First deploy: `docker-compose up -d` + `docker-compose run --rm backend alembic upgrade head`
- Subsequent deploys: `./deploy.sh`
- Setting up cron for backups
- SSL setup with Certbot

**Acceptance:**
- `deploy.sh` runs without errors on a clean pull
- `deploy.sh` runs Alembic migrations before restarting containers
- `backup.sh` creates a valid gzipped SQL file
- `restore.sh` restores from backup file correctly (test on a test database)
- `restore.sh` aborts without 'yes' confirmation
- `health_check.sh` returns exit 0 when all services healthy, exit 1 when any service down
- Old backups pruned correctly after 30 files
- Crontab entry documented in README

---

## TASK 7.5 — Environment & Secrets Management

**Files:**
- `backend/.env.example` (update with all variables)
- `frontend/.env.example`
- `backend/app/core/startup_validator.py`
- `.pre-commit-config.yaml`

---

**`backend/.env.example` — complete with documentation comments:**
```bash
# === DATABASE ===
# PostgreSQL connection string (asyncpg driver)
DATABASE_URL=postgresql+asyncpg://user:password@postgres:5432/wow_optimizer

# === REDIS ===
REDIS_URL=redis://redis:6379/0

# === SECURITY ===
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=your-secret-key-minimum-32-chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# === BATTLE.NET API ===
# Register at: https://develop.battle.net/
BATTLENET_CLIENT_ID=your-battlenet-client-id
BATTLENET_CLIENT_SECRET=your-battlenet-client-secret

# === ANTHROPIC API ===
# Get from: https://console.anthropic.com/
ANTHROPIC_API_KEY=sk-ant-...

# === YOUTUBE API ===
# Get from: https://console.cloud.google.com/
YOUTUBE_API_KEY=your-youtube-api-key

# === FRONTEND ===
FRONTEND_URL=https://yourdomain.com

# === STORAGE ===
RAW_STORAGE_PATH=/raw_storage

# === CELERY ===
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# === FLOWER MONITORING ===
FLOWER_USER=admin
FLOWER_PASSWORD=change-this-password

# === POSTGRES (for docker-compose internal use) ===
POSTGRES_USER=wow_optimizer
POSTGRES_PASSWORD=change-this-password
POSTGRES_DB=wow_optimizer

# === MONITORING (optional) ===
# Leave empty to disable Sentry
SENTRY_DSN=

# === ENVIRONMENT ===
# 'development' or 'production'
ENVIRONMENT=production
```

---

**`backend/app/core/startup_validator.py`:**

Write a function `validate_startup_config()` called in FastAPI's `lifespan` startup event.

Required variables (fail fast if missing):
- `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`
- `BATTLENET_CLIENT_ID`, `BATTLENET_CLIENT_SECRET`
- `ANTHROPIC_API_KEY`
- `FRONTEND_URL`

Optional variables (log warning if missing but continue):
- `YOUTUBE_API_KEY` — warn "YouTube fallback scraping disabled"
- `SENTRY_DSN` — warn "Error tracking disabled"

Validation checks (beyond just presence):
- `SECRET_KEY` must be at least 32 characters — fail if shorter
- `ANTHROPIC_API_KEY` must start with `sk-ant-` — fail if not
- `FRONTEND_URL` must be a valid URL — fail if not
- `ENVIRONMENT` must be 'development' or 'production' — fail if neither

On failure: log a clear error with the variable name and requirement, then raise `SystemExit(1)`.

---

**`.pre-commit-config.yaml`:**
```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks
        name: Detect secrets

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: check-added-large-files
        args: ['--maxkb=1000']
      - id: check-merge-conflict
      - id: detect-private-key
```

Install with: `pip install pre-commit && pre-commit install`

**Secrets in logs/errors:**
Audit all log statements and exception handlers. Ensure:
- `ANTHROPIC_API_KEY` never appears in logs (replace with `sk-ant-...` in any log output)
- `SECRET_KEY` never appears in logs
- `BATTLENET_CLIENT_SECRET` never appears in logs
- Auth tokens never appear in error responses to client
Add a `scrub_secrets(text: str) -> str` utility function that redacts known secret patterns.

**`.gitignore` additions:**
```
.env
.env.local
*.env
/raw_storage/
/backups/
*.sql.gz
```

**Acceptance:**
- Starting backend without `SECRET_KEY` set produces clear error: "SECRET_KEY is required and must be at least 32 characters"
- Starting backend without `ANTHROPIC_API_KEY` produces clear error
- Starting backend with missing optional `YOUTUBE_API_KEY` produces warning but starts normally
- Pre-commit hook catches a test file containing a fake API key pattern
- `.env` file correctly gitignored (verify `git status` doesn't show it)
- No secrets appear in any log line (audit logs from a test run)
- `scrub_secrets()` correctly redacts API key patterns from test strings
