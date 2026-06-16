#!/usr/bin/env bash
# /opt/basjoo/scripts/verify-backups.sh (deployed from scripts/ in repo)
# M11+ P2 — 验证三层备份可恢复 (basjoo DB / Dify DB / dify-data)
set -euo pipefail

LOG="/var/log/basjoo-dify-backup.log"
EXIT_CODE=0

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }

check() {
    local desc="$1"
    local cmd="$2"

    if eval "${cmd}" >/dev/null 2>&1; then
        log "OK: ${desc}"
    else
        log "FAIL: ${desc}"
        EXIT_CODE=1
    fi
}

log "=== backup verification start ==="

# 1. basjoo DB 备份 (deploy-pzalo 既有,这里也验下存在)
BASJOO_DB_BACKUP=$(ls -t /opt/basjoo/backups/basjoo_*.sql.gz 2>/dev/null | head -1 || true)
if [ -n "${BASJOO_DB_BACKUP}" ]; then
    BASJOO_AGE_DAYS=$(( ($(date +%s) - $(stat -c %Y "${BASJOO_DB_BACKUP}")) / 86400 ))
    if [ "${BASJOO_AGE_DAYS}" -le 1 ]; then
        log "OK: basjoo DB backup fresh (${BASJOO_AGE_DAYS}d old, ${BASJOO_DB_BACKUP})"
    else
        log "WARN: basjoo DB backup stale (${BASJOO_AGE_DAYS}d old, ${BASJOO_DB_BACKUP})"
        EXIT_CODE=1
    fi
    # smoke test: gzip + sql 头
    check "basjoo DB backup gzip integrity" \
        "gunzip -c '${BASJOO_DB_BACKUP}' | head -1 | grep -q 'SQLite format'"
else
    log "WARN: no basjoo DB backup found in /opt/basjoo/backups/"
    EXIT_CODE=1
fi

# 2. Dify DB 备份
DIFY_DB_BACKUP=$(ls -t /opt/basjoo/backups/dify-db/dify-db-*.sql.gz 2>/dev/null | head -1 || true)
if [ -n "${DIFY_DB_BACKUP}" ]; then
    DIFY_DB_AGE_DAYS=$(( ($(date +%s) - $(stat -c %Y "${DIFY_DB_BACKUP}")) / 86400 ))
    if [ "${DIFY_DB_AGE_DAYS}" -le 1 ]; then
        log "OK: dify DB backup fresh (${DIFY_DB_AGE_DAYS}d old, ${DIFY_DB_BACKUP})"
    else
        log "WARN: dify DB backup stale (${DIFY_DB_AGE_DAYS}d old, ${DIFY_DB_BACKUP})"
        EXIT_CODE=1
    fi
    check "dify DB backup contains CREATE TABLE" \
        "gunzip -c '${DIFY_DB_BACKUP}' | head -100 | grep -q 'CREATE TABLE'"
else
    log "INFO: no dify DB backup found (Dify profile not enabled?)"
fi

# 3. dify-data volume 备份
DIFY_DATA_BACKUP=$(ls -t /opt/basjoo/backups/dify-data/dify-data-*.tgz 2>/dev/null | head -1 || true)
if [ -n "${DIFY_DATA_BACKUP}" ]; then
    DIFY_DATA_AGE_DAYS=$(( ($(date +%s) - $(stat -c %Y "${DIFY_DATA_BACKUP}")) / 86400 ))
    if [ "${DIFY_DATA_AGE_DAYS}" -le 8 ]; then
        log "OK: dify-data backup fresh (${DIFY_DATA_AGE_DAYS}d old, ${DIFY_DATA_BACKUP})"
    else
        log "WARN: dify-data backup stale (${DIFY_DATA_AGE_DAYS}d old, ${DIFY_DATA_BACKUP})"
        EXIT_CODE=1
    fi
    check "dify-data backup contains upload_files dir" \
        "tar tzf '${DIFY_DATA_BACKUP}' | grep -q 'data/upload_files'"
else
    log "INFO: no dify-data backup found (Dify profile not enabled?)"
fi

# 4. 磁盘占用 (触发告警)
BACKUP_DISK_USAGE=$(df -P /opt/basjoo/backups/ | tail -1 | awk '{print $5}' | tr -d '%')
if [ "${BACKUP_DISK_USAGE}" -lt 80 ]; then
    log "OK: backup disk usage ${BACKUP_DISK_USAGE}% (< 80%)"
else
    log "WARN: backup disk usage ${BACKUP_DISK_USAGE}% (>= 80%)"
    EXIT_CODE=1
fi

log "=== backup verification done (exit=${EXIT_CODE}) ==="
exit "${EXIT_CODE}"
