#!/usr/bin/env bash
# scripts/install-dify-backups.sh (在 basjoo 部署机器上跑一次)
# M11+ P2 — 安装 dify backup 三件套到 /opt/basjoo/scripts/ + /etc/cron.d/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/basjoo/scripts"
CRON_FILE="/etc/cron.d/basjoo-backups"
LOG_DIR="/var/log"

echo "=== install dify backup scripts ==="

# 1. 创建安装目录
mkdir -p "${INSTALL_DIR}"
mkdir -p "${LOG_DIR}"

# 2. 复制 3 个脚本
for script in backup-dify-db.sh backup-dify-data.sh verify-backups.sh; do
    if [ ! -f "${SCRIPT_DIR}/${script}" ]; then
        echo "ERROR: ${SCRIPT_DIR}/${script} not found"
        exit 1
    fi
    cp "${SCRIPT_DIR}/${script}" "${INSTALL_DIR}/${script}"
    chmod +x "${INSTALL_DIR}/${script}"
    echo "installed: ${INSTALL_DIR}/${script}"
done

# 3. 追加 cron 条目 (idempotent: 先检测再追加)
CRON_DIFY_DB="0 4 * * * root /opt/basjoo/scripts/backup-dify-db.sh >> /var/log/basjoo-dify-backup.log 2>&1"
CRON_DIFY_DATA="0 5 * * 0 root /opt/basjoo/scripts/backup-dify-data.sh >> /var/log/basjoo-dify-backup.log 2>&1"
CRON_VERIFY="30 5 * * * root /opt/basjoo/scripts/verify-backups.sh >> /var/log/basjoo-dify-backup.log 2>&1"

if [ ! -f "${CRON_FILE}" ]; then
    cat > "${CRON_FILE}" <<EOF
# basjoo backups (installed $(date -I))
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${CRON_DIFY_DB}
${CRON_DIFY_DATA}
${CRON_VERIFY}
EOF
    chmod 0644 "${CRON_FILE}"
    echo "created: ${CRON_FILE}"
else
    # append-if-not-present
    for entry in "${CRON_DIFY_DB}" "${CRON_DIFY_DATA}" "${CRON_VERIFY}"; do
        KEY=$(echo "${entry}" | awk '{print $5, $6, $7, $8, $9}')
        if ! grep -qF "${KEY}" "${CRON_FILE}"; then
            echo "${entry}" >> "${CRON_FILE}"
            echo "appended cron entry: ${entry}"
        else
            echo "skip (already present): ${entry}"
        fi
    done
fi

# 4. 初次 dry-run 验证
echo ""
echo "=== dry-run check ==="
"${INSTALL_DIR}/backup-dify-db.sh" 2>&1 | tail -5 || echo "  (backup-dify-db dry-run skipped — Dify not running yet)"
"${INSTALL_DIR}/backup-dify-data.sh" 2>&1 | tail -5 || echo "  (backup-dify-data dry-run skipped — Dify volume not present yet)"
"${INSTALL_DIR}/verify-backups.sh" 2>&1 | tail -10

echo ""
echo "=== install done ==="
echo "Next steps:"
echo "  1. If Dify profile enabled: docker compose --profile dify up -d"
echo "  2. Wait for cron to fire (04:00 daily for dify-db, 05:00 weekly for dify-data)"
echo "  3. Tail logs: tail -f /var/log/basjoo-dify-backup.log"
