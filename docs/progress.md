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
- [ ] TASK 3.1 — Constraint Filter
- [ ] TASK 3.2 — Dependency Resolver
- [ ] TASK 3.3 — Zone Connectivity Graph
- [ ] TASK 3.4 — Geographic Clusterer
- [ ] TASK 3.5 — Session Structurer
- [ ] TASK 3.6 — Seasonal Override Layer
- [ ] TASK 3.7 — Route Assembler
- [ ] TASK 3.8 — Reoptimization Handler

## Phase 4 — API Layer
- [ ] TASK 4.1 — Achievement API Endpoints
- [ ] TASK 4.2 — Character API Endpoints
- [ ] TASK 4.3 — Route API Endpoints
- [ ] TASK 4.4 — User API Endpoints

## Phase 5 — Frontend
- [ ] TASK 5.1 — Next.js Project Setup
- [ ] TASK 5.2 — Auth Pages
- [ ] TASK 5.3 — Onboarding Flow
- [ ] TASK 5.4 — Dashboard Page
- [ ] TASK 5.5 — Route View — List Mode
- [ ] TASK 5.6 — Route View — Map Mode
- [ ] TASK 5.7 — Seasonal Calendar Page
- [ ] TASK 5.8 — Achievement Browser Page
- [ ] TASK 5.9 — Mobile Responsiveness Pass

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
