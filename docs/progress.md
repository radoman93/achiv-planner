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
- [ ] TASK 6.1 — Achievement Sync Job
- [ ] TASK 6.2 — Scheduled Scrape Coordinator
- [ ] TASK 6.3 — Seasonal Window Monitor

## Phase 7 — Hardening & Deployment
- [ ] TASK 7.1 — Error Handling & Logging
- [ ] TASK 7.2 — Rate Limiting & Security
- [ ] TASK 7.3 — Database Performance
- [ ] TASK 7.4 — Deployment Scripts
- [ ] TASK 7.5 — Environment & Secrets Management

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
