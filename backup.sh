#!/usr/bin/env bash
# Back up the PostgreSQL database to a gzipped SQL dump.
#
# Usage: ./backup.sh
#
# Recommended crontab entry:
#   0 2 * * * /path/to/backup.sh >> /var/log/wow-backup.log 2>&1

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="wow_optimizer_${TIMESTAMP}.sql.gz"
RETENTION="${BACKUP_RETENTION:-30}"

if [ -z "${POSTGRES_USER:-}" ] || [ -z "${POSTGRES_DB:-}" ]; then
    # Source env from backend/.env if running interactively
    if [ -f "$(dirname "$0")/backend/.env" ]; then
        # shellcheck disable=SC1091
        set -a; . "$(dirname "$0")/backend/.env"; set +a
    fi
fi

mkdir -p "${BACKUP_DIR}"

echo "[backup] Starting database backup: ${FILENAME}"

docker-compose exec -T postgres pg_dump \
    -U "${POSTGRES_USER}" \
    "${POSTGRES_DB}" \
    | gzip > "${BACKUP_DIR}/${FILENAME}"

echo "[backup] Backup complete: ${BACKUP_DIR}/${FILENAME}"
echo "[backup] Size: $(du -sh "${BACKUP_DIR}/${FILENAME}" | cut -f1)"

# Keep only the last RETENTION backups
COUNT=$(ls -1 "${BACKUP_DIR}"/*.sql.gz 2>/dev/null | wc -l | tr -d ' ')
if [ "${COUNT}" -gt "${RETENTION}" ]; then
    PRUNE_COUNT=$((COUNT - RETENTION))
    echo "[backup] Pruning ${PRUNE_COUNT} old backup(s)"
    ls -1t "${BACKUP_DIR}"/*.sql.gz | tail -n "+$((RETENTION + 1))" | xargs -r rm
fi

echo "[backup] Total backups retained: $(ls -1 "${BACKUP_DIR}"/*.sql.gz 2>/dev/null | wc -l | tr -d ' ')"
