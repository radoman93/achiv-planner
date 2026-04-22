# WoW Achievement Route Optimizer — Project Brief

## What This Is
A web app that generates personalized, optimized achievement routes for World of Warcraft players.
Users input their character's achievement data, and the app produces an ordered, efficient route
grouped by zone, respecting dependencies, character constraints, and seasonal windows.

## Target Users
All player types — completionists, efficiency hunters, title/mount chasers, returning players,
seasonal players. The app detects or asks which mode the user is in and adjusts routing accordingly.

## Monetization Model
- **Free tier**: basic routing, limited route generations per day, single character
- **Pro tier**: full optimization modes, seasonal calendar, Battle.net sync, multi-character, saved history
- **Guild tier** (future): team coordination, shared routes, raid achievement scheduling

---

## Tech Stack

### Backend
- **Language**: Python
- **Framework**: FastAPI (async, Uvicorn)
- **Task Queue**: Celery + Redis (4 queues: high_priority, normal, llm_enrichment, sync)
- **Scheduler**: Celery Beat
- **ORM**: SQLAlchemy (async)
- **Migrations**: Alembic
- **LLM**: Anthropic Claude API (claude-sonnet for enrichment, lighter model for classification)

### Scraping
- **Playwright**: JavaScript-rendered pages (Wowhead)
- **BeautifulSoup**: HTML parsing on top of Playwright output
- **Scrapy**: Bulk non-JS sources (Icy Veins, Reddit API, YouTube API)

### Data Storage
- **Primary DB**: PostgreSQL + pgvector extension
- **Cache + Queue Broker**: Redis
- **Raw Scraped Content**: Local filesystem on VPS (`/raw_storage/{source}/{achievement_id}/{timestamp}.html`)

### Frontend
- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS + shadcn/ui
- **State**: React Query
- **Charts**: Recharts
- **Auth**: JWT in httpOnly cookies, Battle.net OAuth2

### Infrastructure
- **Hosting**: Self-hosted VPS via Docker Compose
- **Reverse Proxy**: Nginx (routes /api/* → FastAPI, everything else → Next.js)
- **SSL**: Certbot
- **Monitoring**: Flower (Celery dashboard), Sentry (errors), structlog (JSON logging)

---

## Repository Structure
```
/
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI route handlers
│   │   ├── core/          # Config, auth, middleware
│   │   ├── models/        # SQLAlchemy ORM models
│   │   ├── scraper/       # Playwright, Scrapy, source clients
│   │   ├── pipeline/      # Orchestration, comment processing, LLM enrichment
│   │   ├── router_engine/ # Constraint filter, dependency resolver, clusterer, assembler
│   │   └── services/      # Business logic layer
│   ├── tests/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── app/               # Next.js App Router pages
│   ├── components/        # Shared UI components
│   ├── lib/               # API client, utilities
│   ├── public/
│   ├── Dockerfile
│   └── .env.example
├── nginx/
│   ├── nginx.conf
│   └── ssl/
├── docs/
│   ├── progress.md        # Task completion tracking — update after every task
│   ├── phase-0-tasks.md
│   ├── phase-1-tasks.md
│   ├── phase-2-tasks.md
│   ├── phase-3-tasks.md
│   ├── phase-4-tasks.md
│   ├── phase-5-tasks.md
│   ├── phase-6-tasks.md
│   └── phase-7-tasks.md
├── docker-compose.yml
├── docker-compose.dev.yml
├── CLAUDE.md              # This file — always read at session start
└── README.md
```

---

## Database — Key Tables
| Table | Purpose |
|---|---|
| `achievements` | Master achievement list from Blizzard API + Wowhead |
| `achievement_criteria` | Sub-tasks within each achievement |
| `achievement_dependencies` | Directed graph of prerequisites |
| `zones` | WoW zones with travel/flying metadata |
| `guides` | Structured guide content per achievement (multiple sources) |
| `comments` | Processed Wowhead comments with scores |
| `users` | Accounts with Battle.net OAuth tokens |
| `characters` | WoW characters linked to users |
| `user_achievement_state` | Per-character completion state (large table) |
| `routes` | Generated route objects |
| `route_stops` | Individual achievement stops within a route |
| `route_steps` | Ordered steps within each stop |
| `pipeline_runs` | Scraper pipeline execution logs |
| `patch_events` | Detected patch changes affecting achievements |

---

## Scraping Source Hierarchy (Confidence Tiers)
1. **Blizzard API** — ground truth for structure, no routing info
2. **Wowhead guide** — primary routing content
3. **Wowhead comments** — practical tips, filtered by score + recency
4. **Icy Veins** — base confidence 0.75, good for dungeons/raids
5. **Reddit** — base confidence 0.50, r/wow + r/wowachievements
6. **YouTube** — base confidence 0.35, title + description only

Every scraped record carries: `source`, `scraped_at`, `confidence_score`, `patch_version_detected`.

---

## Routing Engine — Pipeline Order
1. **Constraint Filter** — hard eliminations (flying gates, level gates, faction, group)
2. **Dependency Resolver** — topological sort, cycle detection, meta-achievement grouping
3. **Geographic Clusterer** — zone grouping, nearest-neighbor + 2-opt sequencing
4. **Session Structurer** — breaks route into play sessions by time budget
5. **Seasonal Override** — runs in parallel, injects time-gated achievements at top
6. **Route Assembler** — combines all outputs into final Route object, persists to DB

The routing engine is a **library inside FastAPI**, not a microservice.
LLM enrichment extracts structured data — it does NOT make routing decisions.

---

## Priority Modes
| Mode | Objective |
|---|---|
| Completionist | Total coverage, most efficient ordering of everything |
| Points Per Hour | Maximize achievement points per hour played |
| Goal-Driven | Work backwards from a specific meta-achievement |
| Seasonal First | Prioritize time-gated achievements above all else |

---

## Key Principles — Never Violate These
- Raw scraped HTML is always stored to filesystem before any processing
- LLM outputs null fields rather than inventing data not present in source
- Hard constraint violations remove achievements from pool entirely (not deprioritized)
- Dependency ordering always overrides geographic optimization when they conflict
- Every data point has a confidence tier visible to the user — no false precision
- Free tier rate limits enforced at service layer, not just API layer

---

## Current Phase
**Update this line every time you start a new session.**
Phase: 7 — Hardening & Deployment (COMPLETE)
Current Task: All phases complete — product is production-ready
Last completed: Phase 6 (6.1–6.3 background jobs) + Phase 7 (7.1–7.5 hardening) on 2026-04-21
See docs/progress.md for full status.

---

## Local Dev Uses Production Database (IMPORTANT — read every session)

**`backend/.env` is pointed at the Coolify production Postgres & Redis** so local
dev runs against real user data. This is the owner's explicit choice — do not
change it back to a local DB unless asked. Concrete connection details live in
`backend/.env` (gitignored) and in the Coolify app env (project `achiv-planner`);
never commit them to this repo.

### Guardrails — apply these EVERY session without asking

1. **Never run destructive SQL/Alembic operations without explicit confirmation.**
   That includes `alembic downgrade`, `alembic revision --autogenerate` followed by
   `upgrade` when the revision drops columns, `TRUNCATE`, `DROP`, mass `DELETE`,
   or anything that can't be rolled back. Show the user the statement and wait.
2. **`alembic upgrade head` is only safe if the pending revisions are additive.**
   Inspect `backend/alembic/versions/*.py` for any new revisions before running it;
   if any touch live tables destructively, stop and confirm.
3. **Treat Celery/Redis as shared with production.** Don't publish test tasks that
   could land in the real worker queue; use `CELERY_TASK_ALWAYS_EAGER=1` or a
   dedicated queue name if you need to exercise tasks.
4. **Do not commit `backend/.env`** — it holds live secrets. It's already in
   `.gitignore`; keep it that way.
5. **If a migration or write looks risky, back up first** via
   `./backup.sh` (project root) before proceeding.

### How to start backend locally
```bash
# from project root
docker compose -f docker-compose.yml -f docker-compose.dev.yml up backend
# OR, if you want to avoid spinning up the unused local postgres/redis containers:
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### How to run migrations against production DB
```bash
# inspect pending revisions first
cd backend && alembic current && alembic heads
# then (only if safe — see guardrails above):
alembic upgrade head
```
