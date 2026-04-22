# Project Progress

Update this file after every completed task. Reference it at the start of every Claude Code session.

---

## Phase 0 — Repository & Infrastructure Bootstrap
- [x] TASK 0.1 — Monorepo Structure
- [x] TASK 0.2 — Docker Compose Full Stack Definition
- [x] TASK 0.3 — PostgreSQL Schema Migration System
- [x] TASK 0.4 — Nginx Configuration

## Phase 1 — Backend Foundation
- [x] TASK 1.1 — FastAPI Application Core
- [x] TASK 1.2 — SQLAlchemy Models
- [x] TASK 1.3 — Authentication System
- [x] TASK 1.4 — Battle.net OAuth Integration
- [x] TASK 1.5 — Celery Configuration

## Phase 2 — Scraping Pipeline
- [x] TASK 2.1 — Blizzard API Client
- [x] TASK 2.2 — Raw Storage Client
- [x] TASK 2.3 — Playwright Wowhead Scraper
- [x] TASK 2.4 — Scrapy Spider for Fallback Sources
- [x] TASK 2.5 — Comment Processing Pipeline
- [x] TASK 2.6 — LLM Enrichment Task
- [x] TASK 2.7 — Pipeline Orchestrator
- [x] TASK 2.8 — Patch Monitoring Task

## Phase 3 — Routing Engine
- [x] TASK 3.1 — Constraint Filter
- [x] TASK 3.2 — Dependency Resolver
- [x] TASK 3.3 — Zone Connectivity Graph
- [x] TASK 3.4 — Geographic Clusterer
- [x] TASK 3.5 — Session Structurer
- [x] TASK 3.6 — Seasonal Override Layer
- [x] TASK 3.7 — Route Assembler
- [x] TASK 3.8 — Reoptimization Handler

## Phase 4 — API Layer
- [x] TASK 4.1 — Achievement API Endpoints
- [x] TASK 4.2 — Character API Endpoints
- [x] TASK 4.3 — Route API Endpoints
- [x] TASK 4.4 — User API Endpoints

## Phase 5 — Frontend
- [x] TASK 5.1 — Next.js Project Setup
- [x] TASK 5.2 — Auth Pages
- [x] TASK 5.3 — Onboarding Flow
- [x] TASK 5.4 — Dashboard Page
- [x] TASK 5.5 — Route View — List Mode
- [x] TASK 5.6 — Route View — Map Mode
- [x] TASK 5.7 — Seasonal Calendar Page
- [x] TASK 5.8 — Achievement Browser Page
- [x] TASK 5.9 — Mobile Responsiveness Pass

## Phase 6 — Background Jobs & Sync
- [x] TASK 6.1 — Achievement Sync Job
- [x] TASK 6.2 — Scheduled Scrape Coordinator
- [x] TASK 6.3 — Seasonal Window Monitor

## Phase 7 — Hardening & Deployment
- [x] TASK 7.1 — Error Handling & Logging
- [x] TASK 7.2 — Rate Limiting & Security
- [x] TASK 7.3 — Database Performance
- [x] TASK 7.4 — Deployment Scripts
- [x] TASK 7.5 — Environment & Secrets Management

---

## Blocked Items
_List anything that is blocked and why._

## Notes & Decisions Made During Build
_Log any architectural decisions or deviations from the original plan here so future sessions have context._

- Phase 2: Celery task chain implemented via `celery_app.send_task` links inside each task body rather than Celery `link=` kwargs, so each step owns its own downstream dispatch and can branch on DB state (e.g. comment_processor → fallback vs. enrichment based on confidence).
- Phase 2: Blizzard token-bucket rate limiter uses a Redis sorted set keyed per region so multiple Celery workers share the 100 req/s ceiling.
- Phase 2: Raw storage writes are atomic (tempfile + os.replace) and every HTML file has a sidecar `.meta.json` with source/url/confidence_base for downstream pipelines.
- Phase 2: Orchestrator aliases (`blizzard_skeleton_pass`, `scrape_coordinator`, `patch_monitor`, `seasonal_window_monitor`) match the pre-existing celery_beat_schedule.py task names so the beat scheduler starts cleanly.
- Phase 2: Added `feedparser` to requirements.txt for RSS parsing in patch_monitor.
- Phase 2 acceptance: live-network/Playwright/Claude calls were not executed in this environment; modules are syntax-clean and covered by docstring-level acceptance mapping. Integration testing deferred until VPS/Docker env.
- Phase 3: All 8 routing engine modules live in `backend/app/router_engine/` as a library (not a microservice), called from FastAPI handlers and Celery tasks.
- Phase 3: Zone connectivity data stored in editable JSON (`router_engine/data/zone_connections.json`) covering all WoW expansions through The War Within.
- Phase 3: Migration 0002 adds `blocked_pool`, `deferred_pool` (JSONB) to routes and `community_tips` (JSONB) to route_stops.
- Phase 3: Geographic clusterer uses nearest-neighbor + 2-opt (200 iterations, deterministic seed) with cluster-level dependency ordering constraints.
- Phase 3: Reoptimizer rate-limits full reoptimize to once per hour per character via Redis TTL key.
- Phase 3: Seasonal override handles year-wrap events (e.g., Dec→Jan) and classifies urgency as critical/high/normal based on days remaining.
- Phase 4: All endpoints use consistent envelope `{"data": ..., "error": null}`. Auth via httpOnly cookie JWT.
- Phase 4: Route generation runs the full Phase 3 pipeline synchronously (ConstraintFilter → DependencyResolver → ZoneGraph → GeographicClusterer → SessionStructurer → SeasonalOverride → RouteAssembler).
- Phase 4: Free tier rate limit (5 routes/day) enforced via Redis daily counter. Reoptimize rate limit (1/hour) via Reoptimizer's existing Redis TTL.
- Phase 4: Account deletion (GDPR) cascades in FK-safe order: RouteSteps → RouteStops → Routes → UserAchievementState → Characters → User. Logs deletion event without PII.
- Phase 4: Achievement search uses PostgreSQL full-text search (plainto_tsquery + ts_rank) on name+description.
- Phase 4: Sync endpoint dispatches Celery task to `sync` queue, stores progress in Redis key `sync:progress:{job_id}`, client polls via status endpoint.
- Phase 5: Next.js 14 App Router + TypeScript + Tailwind with WoW-themed dark design system (CSS custom properties).
- Phase 5: API client uses axios with httpOnly cookie credentials, global 401→redirect and 429→RateLimitError interceptors.
- Phase 5: React Query v5 for data fetching with 5-min stale time, no retry on 401/404.
- Phase 5: Middleware guards protected routes via access_token cookie check.
- Phase 5: NavShell provides desktop sidebar + mobile bottom tab bar (5 items, fixed).
- Phase 5: Route list view has optimistic UI for complete/skip, collapsible sessions, community tips per stop.
- Phase 5: Map view uses SVG with zone positions by continent, color-coded by completion status.
- Phase 5: Achievement browser has debounced search, filter panel (desktop sidebar / mobile bottom sheet), detail drawer (side on desktop, full-screen on mobile).
- Phase 5: All interactive elements have minimum 44px touch targets, safe-area-bottom padding on mobile nav.
- Phase 6.1: Sync is a service (`app/services/sync_service.py`) wrapped by a Celery task (`app/pipeline/sync_tasks.py::sync_character_achievements`). Lock key `sync:lock:{character_id}` uses Redis SET NX with 3600s TTL, acquired atomically by the API handler before dispatch. Progress key `sync:progress:{job_id}` updates every 50 entries. Blizzard 404 maps to `SyncError(reason="character_not_found")` which writes `status=failed` to the progress key. Newly-completed achievements on an active route dispatch `pipeline.sync.mark_route_complete` (async reoptimize) per achievement.
- Phase 6.2: Scrape coordinator lives in `app/pipeline/scrape_coordinator.py` (task name `pipeline.scrape.coordinate`, queue `high_priority`, scheduled every 6h). In-flight tracking uses per-id Redis keys `scrape:queued:{blizzard_id}` with 24h TTL rather than a plain Redis set (gets per-member TTL for free). Beat schedule updated to point at the new task name. Wowhead scrape task now clears the queued marker and resets staleness_score=0 on success. Staleness scorer lives alongside the coordinator as `compute_staleness_score` for use elsewhere in the pipeline.
- Phase 6.3: Seasonal monitor in `app/pipeline/seasonal_monitor.py` (task `pipeline.seasonal.monitor`, queue `high_priority`, daily at 06:00 UTC). Dates are injectable via kwargs to keep unit testing trivial. Year-wrap handling mirrors the logic in `router_engine/seasonal_override.py::_adjust_seasonal_dates`. Daily report stored at Redis key `seasonal:daily_report` with 25h TTL and structure `{generated_at, active_events[], opening_soon[], upcoming_30_days[]}`. Opening events force staleness=1.0 and dispatch `pipeline.scrape.wowhead` on the high_priority queue.
- Phase 7.1: Logging switches between structlog JSONRenderer (production) and ConsoleRenderer (development) based on ENVIRONMENT. Each log line carries `service` + `environment` via a custom processor. Sentry init lives in `app/core/sentry.py` and wires up FastAPI/Starlette/Celery/SQLAlchemy integrations only when SENTRY_DSN is set. `before_send` drops 401/404, masks emails, and redacts known token/password keys (tokens, secrets, cookies, authorization). `scrub_secrets()` utility redacts Anthropic keys + Bearer tokens from arbitrary strings. Docker Compose uses YAML anchor `x-log-rotate` for 100MB×5 rotation on every service. Frontend `components/error-boundary.tsx` wraps the app in `lib/providers.tsx`.
- Phase 7.2: Rate limiter in `app/core/rate_limiter.py` wraps slowapi with a Redis storage backend and three key functions (`ip_key`, `tier_key`, `character_key`). `rate_limit_exceeded_handler` returns the canonical `{data, error:{code:"rate_limited", retry_after_seconds}}` envelope + a `Retry-After` header. Per-endpoint limits applied: `/auth/register` 5/min, `/auth/login` 10/min, `/achievements` 100/min, `/achievements/search` 60/min (also max_length=200 on `q`), `/characters/{id}/sync` 10/day per character. Route-generation limit stays in `api/routes.py` as a Redis daily counter (5/day free, 50/day pro). Security headers + 1MB payload limit via `app/core/security_headers.py`. CORS restricted to FRONTEND_URL in production; localhost:3000/3001 only added in development.
- Phase 7.3: Migration `0003_performance_indexes.py` adds 7 composite/partial indexes and the `character_completion_stats` materialized view with a `refresh_character_stats()` wrapper that uses REFRESH CONCURRENTLY. Sync job calls the refresh at commit time (best-effort — rolls back on view-not-present or concurrent refresh errors). SQLAlchemy pool upgraded to pool_size=10, max_overflow=20, pool_recycle=1800, pool_pre_ping=True. Full query access-pattern audit documented in `docs/query-performance.md` (includes a flagged future improvement: generated tsvector column + GIN index for search above 50k rows).
- Phase 7.4: Deployment scripts at repo root — `deploy.sh`, `backup.sh`, `restore.sh`, `health_check.sh`. All use `set -euo pipefail`. Backup defaults to /backups with 30-dump retention (overridable via BACKUP_DIR, BACKUP_RETENTION). Restore requires an explicit `yes` confirmation. README updated with prerequisites, first-deploy + subsequent-deploy steps, crontab line, and Certbot SSL instructions.
- Phase 7.5: Startup validator at `app/core/startup_validator.py` — required fields (DATABASE_URL, REDIS_URL, SECRET_KEY, Battle.net client id/secret, ANTHROPIC_API_KEY, FRONTEND_URL), plus format checks (SECRET_KEY ≥32 chars, ANTHROPIC_API_KEY sk-ant- prefix, FRONTEND_URL valid URL, ENVIRONMENT enum). Called from FastAPI startup before Sentry init; raises SystemExit(1) on failure with a readable stderr summary. Optional fields (YOUTUBE_API_KEY, SENTRY_DSN) produce warnings but don't block startup. `.pre-commit-config.yaml` runs gitleaks + standard hooks (large-files, merge-conflict, detect-private-key). `.gitignore` hardened with `*.env` allowlist + `/backups/` + `*.sql.gz`.
