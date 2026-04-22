#!/usr/bin/env bash
# Restore the PostgreSQL database from a gzipped SQL dump.
#
# Usage: ./restore.sh /path/to/backup.sql.gz
#
# Stops backend + celery, loads the dump, runs migrations forward, then
# restarts services. Prompts for 'yes' confirmation before proceeding.

set -euo pipefail

if [ "${1:-}" = "" ]; then
    echo "Usage: $0 /path/to/backup.sql.gz"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "ERROR: Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

if [ -z "${POSTGRES_USER:-}" ] || [ -z "${POSTGRES_DB:-}" ]; then
    if [ -f "$(dirname "$0")/backend/.env" ]; then
        # shellcheck disable=SC1091
        set -a; . "$(dirname "$0")/backend/.env"; set +a
    fi
fi

echo "[restore] WARNING: This will OVERWRITE the current database."
echo "[restore] Backup source: ${BACKUP_FILE}"
echo "[restore] Target database: ${POSTGRES_DB}"
read -r -p "Type 'yes' to continue: " confirm
if [ "${confirm}" != "yes" ]; then
    echo "[restore] Aborted."
    exit 0
fi

echo "[restore] Stopping backend services..."
docker-compose stop backend celery-worker celery-beat

echo "[restore] Restoring from: ${BACKUP_FILE}"
gunzip -c "${BACKUP_FILE}" | docker-compose exec -T postgres psql \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}"

echo "[restore] Running migrations to current head..."
docker-compose run --rm backend alembic upgrade head

echo "[restore] Restarting services..."
docker-compose start backend celery-worker celery-beat

echo "[restore] Restore complete. Verify application at http://localhost"
