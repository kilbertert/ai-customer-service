#!/usr/bin/env bash
# /opt/basjoo/scripts/backup-dify-data.sh (deployed from scripts/ in repo)
# M11+ P2 — dify-data volume 备份 (每周,变更频率低)
set -euo pipefail

BACKUP_DIR="/opt/basjoo/backups/dify-data"
DATE=$(date +%F)
BACKUP_FILE="${BACKUP_DIR}/dify-data-${DATE}.tgz"
LOG="/var/log/basjoo-dify-backup.log"
RETENTION_DAYS=90

mkdir -p "${BACKUP_DIR}"

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }

log "start dify-data backup"

# 探测 volume 名 (basjoo 部署约定: basjoo-dify-data)
DIFY_VOLUME="${BASJOO_DIFY_VOLUME:-basjoo-dify-data}"

if ! docker volume inspect "${DIFY_VOLUME}" >/dev/null 2>&1; then
    log "ERROR: docker volume '${DIFY_VOLUME}' not found (Dify profile not enabled?)"
    exit 1
fi

# 用临时 alpine 容器挂载只读 volume + 备份目录,tar 打包
if ! docker run --rm \
    -v "${DIFY_VOLUME}:/data:ro" \
    -v "${BACKUP_DIR}:/backup" \
    alpine tar czf "/backup/dify-data-${DATE}.tgz" -C / data; then
    log "ERROR: tar failed, partial file: ${BACKUP_FILE}"
    rm -f "${BACKUP_FILE}"
    exit 1
fi

BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
log "dify-data backup done: ${BACKUP_FILE} (${BACKUP_SIZE})"

# 清理 > 90 天旧备份
DELETED=$(find "${BACKUP_DIR}" -name "dify-data-*.tgz" -mtime +${RETENTION_DAYS} -delete -print | wc -l)
log "cleaned ${DELETED} old backups (older than ${RETENTION_DAYS}d)"

log "done"
exit 0
