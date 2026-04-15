# Phase 0 — Repository & Infrastructure Bootstrap

Complete all tasks in this phase before starting Phase 1.
After each task, verify acceptance criteria pass and update docs/progress.md.

---

## TASK 0.1 — Monorepo Structure

Create the full repository directory structure exactly as follows:

```
/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── scraper/
│   │   ├── pipeline/
│   │   ├── router_engine/
│   │   └── services/
│   ├── tests/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── public/
│   ├── Dockerfile
│   └── .env.example
├── nginx/
│   ├── nginx.conf
│   └── ssl/
├── docs/
├── docker-compose.yml
├── docker-compose.dev.yml
└── README.md
```

Each directory under `backend/app/` must contain an `__init__.py`.
`requirements.txt` must include: fastapi, uvicorn, sqlalchemy, alembic, asyncpg,
celery, redis, playwright, beautifulsoup4, scrapy, anthropic, python-jose,
passlib, bcrypt, pydantic-settings, structlog, sentry-sdk, slowapi, httpx.
`frontend/` must be initialized as a Next.js 14 project with TypeScript, Tailwind, and App Router.
Write a stub `README.md` with project name and one-line description.
Write a stub `docker-compose.yml` that will be filled in TASK 0.2.

**Acceptance:**
- `docker-compose up` starts without YAML parse errors (services can be stubs)
- All Python packages in requirements.txt are valid and installable
- Next.js project scaffolding is complete (`npm run dev` starts without errors)
- All `__init__.py` files exist in backend directories

---

## TASK 0.2 — Docker Compose Full Stack Definition

Write the complete `docker-compose.yml` defining all services:

**Services to define:**
- `postgres` — image: pgvector/pgvector:pg16, persistent volume for data, health check
- `redis` — image: redis:7-alpine, persistent volume, health check
- `backend` — built from backend/Dockerfile, depends_on postgres+redis (healthy), mounts .env
- `celery-worker` — same image as backend, command: celery worker, 4 queues: high_priority,normal,llm_enrichment,sync
- `celery-beat` — same image as backend, command: celery beat
- `flower` — same image as backend, command: celery flower, port 5555, basic auth via env vars
- `frontend` — built from frontend/Dockerfile, depends_on backend
- `nginx` — image: nginx:alpine, mounts nginx/nginx.conf, ports 80+443, depends_on frontend+backend

**Requirements:**
- All services on a shared Docker network named `wow_optimizer_network`
- Postgres data volume named `postgres_data`
- Redis data volume named `redis_data`
- Raw storage volume mounted at `/raw_storage` in backend + celery services
- All secrets via environment variables — never hardcoded
- `.env.example` lists every variable with a description comment

Write `docker-compose.dev.yml` as an override that: mounts source code as volumes for hot reload,
exposes postgres on port 5432 and redis on port 6379 to localhost, disables nginx (direct port access).

**Acceptance:**
- `docker-compose up` starts all services
- Postgres health check passes before backend starts
- Redis health check passes before backend starts
- `docker-compose -f docker-compose.yml -f docker-compose.dev.yml up` works for dev mode

---

## TASK 0.3 — PostgreSQL Schema Migration System

Set up Alembic and write the initial migration creating all tables.

**Setup:**
- Initialize Alembic in `backend/`
- Configure `alembic.ini` and `env.py` to use the async SQLAlchemy engine from app config
- Enable pgvector extension in the first migration via `CREATE EXTENSION IF NOT EXISTS vector`

**Tables to create in the initial migration:**

`zones`
- id (UUID, PK), name (varchar 255, not null), expansion (varchar 100), continent (varchar 100)
- requires_flying (bool, default false), flying_condition (text)
- has_portal (bool, default false), portal_from (varchar 255)
- created_at, updated_at (timestamps)

`achievements`
- id (UUID, PK), blizzard_id (integer, unique, not null, indexed)
- name (varchar 500, not null), description (text), how_to_complete (text)
- category (varchar 255), subcategory (varchar 255), expansion (varchar 100)
- patch_introduced (varchar 50), points (integer, default 0)
- is_account_wide (bool, default false), is_meta (bool, default false)
- is_legacy (bool, default false), is_faction_specific (bool, default false)
- faction (varchar 50), is_class_restricted (bool, default false), allowed_classes (JSONB)
- zone_id (UUID, FK → zones, nullable), estimated_minutes (integer)
- requires_flying (bool), requires_group (bool, default false), min_group_size (integer)
- is_seasonal (bool, default false), seasonal_event (varchar 255)
- seasonal_start (date), seasonal_end (date)
- last_scraped_at (timestamp), staleness_score (float, default 1.0)
- confidence_score (float, default 0.0), manually_verified (bool, default false)
- created_at, updated_at

`achievement_criteria`
- id (UUID, PK), achievement_id (UUID, FK → achievements, indexed)
- blizzard_criteria_id (integer), description (text)
- required_amount (integer), criteria_type (varchar 100)
- created_at, updated_at

`achievement_dependencies`
- id (UUID, PK)
- required_achievement_id (UUID, FK → achievements)
- dependent_achievement_id (UUID, FK → achievements)
- dependency_type (varchar 50) — 'hard' or 'soft'
- confidence (float, default 1.0)
- created_at
- UNIQUE constraint on (required_achievement_id, dependent_achievement_id)

`guides`
- id (UUID, PK), achievement_id (UUID, FK → achievements, indexed)
- source_type (varchar 50) — 'wowhead_guide', 'icy_veins', 'reddit', 'youtube', 'manual'
- source_url (text), raw_content (text), processed_content (JSONB)
- steps (JSONB), extracted_zone (varchar 255)
- requires_flying_extracted (bool), requires_group_extracted (bool)
- min_group_size_extracted (integer), estimated_minutes_extracted (integer)
- confidence_score (float), confidence_flags (JSONB)
- patch_version_detected (varchar 50)
- scraped_at (timestamp), processed_at (timestamp)
- embedding (vector(1536))
- created_at, updated_at

`comments`
- id (UUID, PK), achievement_id (UUID, FK → achievements, indexed)
- source_url (text), author (varchar 255)
- raw_text (text), comment_date (timestamp)
- upvotes (integer, default 0)
- recency_score (float), vote_score (float), combined_score (float)
- comment_type (varchar 100)
- patch_version_mentioned (varchar 50)
- is_processed (bool, default false), is_contradictory (bool, default false)
- created_at

`users`
- id (UUID, PK), email (varchar 255, unique, indexed)
- hashed_password (varchar 255, nullable)
- battlenet_id (varchar 255, unique, nullable)
- battlenet_token (text, nullable), battlenet_token_expires_at (timestamp)
- battlenet_region (varchar 10)
- priority_mode (varchar 50, default 'completionist')
- session_duration_minutes (integer, default 120)
- solo_only (bool, default false)
- tier (varchar 50, default 'free')
- is_active (bool, default true)
- created_at, updated_at

`characters`
- id (UUID, PK), user_id (UUID, FK → users, indexed)
- name (varchar 255, not null), realm (varchar 255, not null)
- faction (varchar 50), class (varchar 50), race (varchar 50)
- level (integer), region (varchar 10)
- flying_unlocked (JSONB) — map of expansion → bool
- current_expansion (varchar 100)
- last_synced_at (timestamp)
- created_at, updated_at

`user_achievement_state`
- id (UUID, PK)
- character_id (UUID, FK → characters, indexed)
- achievement_id (UUID, FK → achievements, indexed)
- completed (bool, default false)
- completed_at (timestamp, nullable)
- criteria_progress (JSONB)
- UNIQUE constraint on (character_id, achievement_id)
- INDEX on (character_id, completed)

`routes`
- id (UUID, PK), user_id (UUID, FK → users, indexed)
- character_id (UUID, FK → characters, indexed)
- mode (varchar 50), status (varchar 50, default 'active')
- total_estimated_minutes (integer)
- overall_confidence (float)
- session_duration_minutes (integer)
- solo_only (bool)
- created_at, updated_at, archived_at

`route_stops`
- id (UUID, PK), route_id (UUID, FK → routes, indexed)
- achievement_id (UUID, FK → achievements)
- session_number (integer), sequence_order (integer)
- zone_id (UUID, FK → zones, nullable)
- estimated_minutes (integer)
- confidence_tier (varchar 50)
- guide_id (UUID, FK → guides, nullable)
- is_seasonal (bool, default false), days_remaining (integer)
- completed (bool, default false), skipped (bool, default false)
- completed_at (timestamp)
- INDEX on (route_id, session_number, sequence_order)

`route_steps`
- id (UUID, PK), route_stop_id (UUID, FK → route_stops, indexed)
- sequence_order (integer), description (text)
- step_type (varchar 50) — 'travel', 'interact', 'kill', 'collect', 'talk', 'wait'
- location (varchar 255), source_reference (text)
- created_at

`pipeline_runs`
- id (UUID, PK), started_at (timestamp), completed_at (timestamp)
- achievements_processed (integer), achievements_errored (integer)
- phases_completed (JSONB), error_log (JSONB)
- created_at

`patch_events`
- id (UUID, PK), achievement_id (UUID, FK → achievements, indexed)
- patch_version (varchar 50), detected_at (timestamp)
- source_url (text), created_at

**Acceptance:**
- `alembic upgrade head` runs without errors
- All tables exist with correct columns, types, and constraints
- pgvector extension is enabled
- All foreign keys and indexes exist
- `alembic downgrade base` cleanly removes everything

---

## TASK 0.4 — Nginx Configuration

Write `nginx/nginx.conf` with the following requirements:

**Routing:**
- `location /api/` → proxy to `http://backend:8000/` (strip the /api prefix)
- `location /flower/` → proxy to `http://flower:5555/`
- `location /` → proxy to `http://frontend:3000/`

**WebSocket support:**
- Set `Upgrade` and `Connection` headers on all proxy locations
- Required for future real-time sync updates

**SSL:**
- HTTP on port 80 redirects to HTTPS on port 443
- SSL certificate paths stubbed at `/etc/nginx/ssl/cert.pem` and `/etc/nginx/ssl/key.pem`
- Include a comment explaining Certbot will replace these stubs
- TLS 1.2 and 1.3 only

**Performance:**
- Gzip compression enabled for text/html, text/css, application/javascript, application/json
- `client_max_body_size 10M` (for future file uploads)
- Proxy timeouts: read 60s, connect 10s

**Rate limiting:**
- Define a rate limit zone: 100 requests/minute per IP on `/api/`
- Return 429 with JSON body when limit hit

**Security headers** on all responses:
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`

**Acceptance:**
- Nginx starts without configuration errors
- Proxy routing reaches correct upstream services
- Rate limiting returns 429 under load
- Security headers present on responses
- Gzip confirmed active via Content-Encoding header
