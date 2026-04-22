#!/usr/bin/env bash
# Deploy the WoW Achievement Optimizer stack.
#
# Usage: ./deploy.sh
#
# Steps:
#   1. Pull latest code from origin/main
#   2. Rebuild backend + frontend images (no cache)
#   3. Run Alembic migrations
#   4. Bring the stack up with zero-downtime restart
#   5. Wait for backend + frontend health

set -euo pipefail

LOG_PREFIX="[deploy]"
HEALTH_RETRIES=30
HEALTH_SLEEP=2

log() { echo "${LOG_PREFIX} $*"; }

log "Starting deployment $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# --- Pull latest code --------------------------------------------------------
log "git pull origin main"
git pull origin main

# --- Rebuild images ----------------------------------------------------------
log "Building backend + frontend images (no cache)"
docker-compose build --no-cache backend frontend

# --- Run migrations ----------------------------------------------------------
log "Running Alembic migrations"
docker-compose run --rm backend alembic upgrade head

# --- Zero-downtime restart ---------------------------------------------------
log "Starting services"
docker-compose up -d --remove-orphans

# --- Health checks -----------------------------------------------------------
log "Waiting for backend health..."
for i in $(seq 1 ${HEALTH_RETRIES}); do
    if curl -sf http://localhost/api/health > /dev/null 2>&1; then
        log "Backend healthy after ${i} attempt(s)"
        break
    fi
    if [ "${i}" -eq "${HEALTH_RETRIES}" ]; then
        log "ERROR: Backend failed to become healthy"
        exit 1
    fi
    sleep ${HEALTH_SLEEP}
done

log "Verifying frontend..."
if ! curl -sf http://localhost/ > /dev/null 2>&1; then
    log "ERROR: Frontend not responding"
    exit 1
fi

log "Deployment complete $(date -u +%Y-%m-%dT%H:%M:%SZ)"
