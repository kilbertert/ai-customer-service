# M11+ P2 — Dify Data Volume 备份策略

> **目的**: Dify 1.14.2 (M10+ chain 引入) 的 `dify-data` volume 备份策略,与 `postgres-data` 同级。
> **基线**: M10+5 commit `5c34af2` 引入 `dify` opt-in docker-compose profile,volume 挂载 `/app/api/storage` (Dify 默认 storage 路径,含上传文件、workflow dump、API key metadata)。
> **状态**: ⏸️ 策略文档已写,具体 backup script 待 M11+ ops Sprint 实施 (估 1 人日)。

---

## 0. 背景

`docker-compose.yml` 中 `dify` service 启用时:

```yaml
dify:
  image: langgenius/dify-api:1.14.2
  volumes:
    - dify-data:/app/api/storage
```

`dify-data` volume 包含 (Dify 默认 storage 目录):

- `upload_files/` — 用户上传的附件、image、document
- `tools/` — 自定义 tool code (M10+ per-agent workflow 用的 custom tool 可能落地此处)
- `workflow_logs/` — workflow 执行日志 (Dify 内部 analytics 用,非业务 critical 但调试有用)
- `privkeys/` — Dify 自签 API key 私钥 (若 Dify 1.14.2 用 RSA sign 则有)
- `key_files/` — 已加密的 secret key 文件 (Dify 系统级,不归 basjoo 管)

**关键**: Dify API key (`dify_api_key`) **不在此 volume** — 存在 Dify 的 postgres DB (metadata),由 basjoo Fernet 二次加密后存 basjoo DB 的 agent 表。所以 `dify-data` 备份 + Dify DB 备份 + basjoo DB 备份 = 三重缺一不可。

---

## 1. 三层备份矩阵

| 层级 | 内容 | volume / 位置 | 备份频率 | 保留期 | RTO |
|------|------|--------------|---------|--------|-----|
| **basjoo DB** | workspace / agent / chat / quota / **Fernet 加密的 dify_api_key** | `backend-data/basjoo.db` | 每日 (现成 deploy-pzalo.sh) | 30 天 | < 5 min |
| **Dify DB** | workflow / app / dataset / API key 明文 / tenants | Dify postgres (共用 basjoo postgres) | 每日 | 30 天 | < 10 min |
| **Dify 文件 storage** | upload_files / tools / workflow_logs / privkeys | `dify-data` volume | 每周 (变更频率低) | 90 天 | < 15 min |

**ALL 三层必须同时恢复**,否则 basjoo 启动后无法代理 Dify (Dify API key 在 basjoo DB 但 metadata 在 Dify DB,file storage 在 dify-data)。

---

## 2. 备份脚本模板

### 2.1 Dify 文件 storage 备份

```bash
#!/usr/bin/env bash
# /opt/basjoo/scripts/backup-dify-data.sh
# M11+ P2 — dify-data volume 备份 (weekly)
set -euo pipefail

BACKUP_DIR=/opt/basjoo/backups/dify-data
DATE=$(date +%F)
BACKUP_FILE="${BACKUP_DIR}/dify-data-${DATE}.tgz"
LOG=/var/log/basjoo-dify-backup.log

mkdir -p "${BACKUP_DIR}"

echo "[$(date)] start dify-data backup" | tee -a "${LOG}"
docker run --rm \
  -v basjoo-dify-data:/data:ro \
  -v "${BACKUP_DIR}":/backup \
  alpine tar czf "/backup/dify-data-${DATE}.tgz" /data
echo "[$(date)] backup done: ${BACKUP_FILE}" | tee -a "${LOG}"

# 90 天前清理
find "${BACKUP_DIR}" -name "dify-data-*.tgz" -mtime +90 -delete
echo "[$(date)] old backups (>90d) cleaned" | tee -a "${LOG}"
```

### 2.2 Dify DB 备份 (从 basjoo postgres dump 单 schema)

```bash
#!/usr/bin/env bash
# /opt/basjoo/scripts/backup-dify-db.sh
# 每日 — Dify 用 basjoo postgres 共享实例,Dify schema = `dify`
set -euo pipefail

BACKUP_DIR=/opt/basjoo/backups/dify-db
DATE=$(date +%F)
BACKUP_FILE="${BACKUP_DIR}/dify-db-${DATE}.sql.gz"
LOG=/var/log/basjoo-dify-backup.log

mkdir -p "${BACKUP_DIR}"

echo "[$(date)] start dify-db backup" | tee -a "${LOG}"
docker exec basjoo-postgres pg_dump -U postgres -d dify \
  | gzip > "${BACKUP_FILE}"
echo "[$(date)] dify-db backup done: ${BACKUP_FILE}" | tee -a "${LOG}"

# 30 天前清理
find "${BACKUP_DIR}" -name "dify-db-*.sql.gz" -mtime +30 -delete
echo "[$(date)] old dify-db backups (>30d) cleaned" | tee -a "${LOG}"
```

---

## 3. Crontab 配置 (跟 basjoo 同级)

```bash
# /etc/cron.d/basjoo-backups
# 现有 basjoo 备份 (deploy-pzalo.sh 第 469 行示例)
0 3 * * * /opt/basjoo/scripts/backup.sh >> /var/log/basjoo-backup.log 2>&1

# M11+ P2 新增
0 4 * * * /opt/basjoo/scripts/backup-dify-db.sh >> /var/log/basjoo-dify-backup.log 2>&1
0 5 * * 0 /opt/basjoo/scripts/backup-dify-data.sh >> /var/log/basjoo-dify-backup.log 2>&1
```

**调度错峰**:
- 03:00 basjoo DB
- 04:00 Dify DB
- 05:00 周日 Dify 文件

避免同一时间 3 个 backup 并行跑 (PG dump 锁竞争)。

---

## 4. 恢复流程

### 4.1 仅 basjoo DB 损坏

```bash
# 1. 停 basjoo
docker compose --profile dify stop backend

# 2. 恢复 basjoo DB
LATEST=$(ls -t /opt/basjoo/backups/basjoo_*.sql.gz | head -1)
gunzip -c "${LATEST}" | sqlite3 backend-data/basjoo.db

# 3. 重启
docker compose --profile dify start backend
```

### 4.2 仅 Dify DB 损坏

```bash
# 1. 停 Dify
docker compose --profile dify stop dify

# 2. 恢复 Dify DB (PG 同库,只 drop+restore `dify` schema)
LATEST=$(ls -t /opt/basjoo/backups/dify-db-*.sql.gz | head -1)
gunzip -c "${LATEST}" | docker exec -i basjoo-postgres psql -U postgres -d dify

# 3. 重启 Dify
docker compose --profile dify start dify
```

### 4.3 仅 dify-data 损坏

```bash
# 1. 停 Dify
docker compose --profile dify stop dify

# 2. 恢复 dify-data volume
LATEST=$(ls -t /opt/basjoo/backups/dify-data/dify-data-*.tgz | head -1)
docker run --rm \
  -v basjoo-dify-data:/data \
  -v "$(dirname ${LATEST})":/backup \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/$(basename ${LATEST}) -C /"

# 3. 重启 Dify
docker compose --profile dify start dify
```

### 4.4 ALL 三层同时损坏 (灾难恢复)

```bash
# 1. 停所有服务
docker compose --profile dify down

# 2. 顺序恢复 basjoo DB → Dify DB → dify-data
#    (顺序很关键:basjoo Fernet 加密的 dify_api_key 解密依赖 ENCRYPTION_KEY 文件,该文件在 basjoo DB 之前的 `backend-data` volume)
LATEST_BASJOO=$(ls -t /opt/basjoo/backups/basjoo_*.sql.gz | head -1)
LATEST_DIFY_DB=$(ls -t /opt/basjoo/backups/dify-db-*.sql.gz | head -1)
LATEST_DIFY_DATA=$(ls -t /opt/basjoo/backups/dify-data/dify-data-*.tgz | head -1)

# 2a. 启动 postgres + redis (Dify 依赖)
docker compose --profile dify up -d postgres redis

# 2b. 恢复 basjoo DB
gunzip -c "${LATEST_BASJOO}" | sqlite3 backend-data/basjoo.db

# 2c. 恢复 Dify DB
gunzip -c "${LATEST_DIFY_DB}" | docker exec -i basjoo-postgres psql -U postgres -d dify

# 2d. 启动 Dify + 恢复 dify-data
docker compose --profile dify up -d dify
docker run --rm \
  -v basjoo-dify-data:/data \
  -v "$(dirname ${LATEST_DIFY_DATA})":/backup \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/$(basename ${LATEST_DIFY_DATA}) -C /"
docker compose --profile dify restart dify

# 2e. 启动 backend + frontend
docker compose --profile dify up -d backend frontend
```

---

## 5. 验证流程

每次备份后**必跑**的 smoke test:

```bash
# /opt/basjoo/scripts/verify-backups.sh
set -euo pipefail

echo "=== basjoo DB backup verify ==="
LATEST_BASJOO=$(ls -t /opt/basjoo/backups/basjoo_*.sql.gz | head -1)
gunzip -c "${LATEST_BASJOO}" | sqlite3 :memory: ".tables" | grep -q "agents" && echo "OK: agents table present"

echo "=== Dify DB backup verify ==="
LATEST_DIFY_DB=$(ls -t /opt/basjoo/backups/dify-db-*.sql.gz | head -1)
gunzip -c "${LATEST_DIFY_DB}" | head -50 | grep -q "CREATE TABLE" && echo "OK: Dify schema present"

echo "=== dify-data backup verify ==="
LATEST_DIFY_DATA=$(ls -t /opt/basjoo/backups/dify-data/dify-data-*.tgz | head -1)
tar tzf "${LATEST_DIFY_DATA}" | grep -q "upload_files" && echo "OK: upload_files dir present"
```

**建议**: 加进 crontab 备份跑完后 30 分钟,失败发 alert (email / Slack)。

---

## 6. 监控指标

| 指标 | 阈值 | 告警 |
|------|------|------|
| 最新 backup 时间 | < 25h (每日) / < 8d (每周) | 触发时告警 |
| 备份大小突增 / 突减 | ±50% / 7d 平均 | 触发时告警 (Dify 数据可能异常) |
| 备份文件数 (30 天内) | 30 ± 2 (每日) / 4 ± 1 (每周) | 触发时告警 (脚本可能挂) |
| 磁盘占用 | < 80% `/opt/basjoo/backups/` | 触发时告警 |

---

## 7. 实施 backlog

| 项 | 工作量 | 优先级 |
|----|-------|--------|
| 写 `backup-dify-db.sh` + 测试 | 0.5 人日 | P2 (本文档同步) |
| 写 `backup-dify-data.sh` + 测试 | 0.5 人日 | P2 |
| 写 `verify-backups.sh` + cron | 0.5 人日 | P2 |
| `docs/operations.md` v1.4 加 Dify backup section | 0.2 人日 | P2 |
| M11+ ops Sprint 实施 | **1.2 人日** | — |

---

## 附录 A: 与 M10+ chain 关系

- M10+5 commit `5c34af2` 引入 `dify` opt-in profile + `dify-data` volume
- M10+4 commit `8dc84e9` 6 补丁 (D9a-D9f) 写入数据到 Dify DB + file storage
- M10+ chain 闭环后,任何 Dify 数据丢失 = 重建 per-agent workflow (高成本)
- 本 backup 策略是 M10+ 投资保护层

## 附录 B: 已知缺口

| 缺口 | 触发 |
|------|------|
| Dify 文件 storage 是否含 custom tool code? | M11+ 验证 (Dify 1.14.2 source code 读) |
| `privkeys/` 是否 Dify 用? RSA sign? | 同上 |
| basjoo postgres 跟 Dify postgres 是同实例 (M10+5 docker-compose 默认) — 物理隔离? | 灾难恢复时 PG 整机挂 = ALL 3 层同时挂 (极端情况) |

---

**END OF M11-P2-DIFY-DATA-BACKUP**