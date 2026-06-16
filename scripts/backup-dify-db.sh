#!/usr/bin/env bash
# /opt/basjoo/scripts/backup-dify-db.sh (deployed from scripts/ in repo)
# M11+ P2 — Dify DB 备份 (每日,Dify schema = `dify` 跟 basjoo postgres 共享实例)
set -euo pipefail

BACKUP_DIR="/opt/basjoo/backups/dify-db"
DATE=$(date +%F)
BACKUP_FILE="${BACKUP_DIR}/dify-db-${DATE}.sql.gz"
LOG="/var/log/basjoo-dify-backup.log"
RETENTION_DAYS=30

mkdir -p "${BACKUP_DIR}"

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }

log "start dify-db backup"

# 探测 postgres 容器名 (basjoo 部署约定: basjoo-postgres)
PG_CONTAINER="${BASJOO_PG_CONTAINER:-basjoo-postgres}"

if ! docker ps --format '{{.Names}}' | grep -q "^${PG_CONTAINER}\$"; then
    log "ERROR: postgres container '${PG_CONTAINER}' not running"
    exit 1
fi

# pg_dump 整库 `dify` 压缩输出
if ! docker exec "${PG_CONTAINER}" pg_dump -U postgres -d dify | gzip > "${BACKUP_FILE}"; then
    log "ERROR: pg_dump failed, partial file: ${BACKUP_FILE}"
    rm -f "${BACKUP_FILE}"
    exit 1
fi

BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
log "dify-db backup done: ${BACKUP_FILE} (${BACKUP_SIZE})"

# 清理 > 30 天旧备份
DELETED=$(find "${BACKUP_DIR}" -name "dify-db-*.sql.gz" -mtime +${RETENTION_DAYS} -delete -print | wc -l)
log "cleaned ${DELETED} old backups (older than ${RETENTION_DAYS}d)"

log "done"
exit 0
