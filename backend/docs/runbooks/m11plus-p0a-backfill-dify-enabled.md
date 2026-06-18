# M11+ P0-A Backfill `workspace.dify_enabled` Runbook

> 适用范围:已经从 M10 G3 迁移之后,且 M11 PR2 (provisioning 字段) 已落地的生产 DB。
> 目的:把 `dify_provisioning_status='ready'` 但 `dify_enabled=0` 的历史 workspace
> 翻成 `dify_enabled=1`,让 Plan A 4-step `create_agent` 路径和
> `services.dify_toolkit.Deployer` 能跑通。

## 0. 何时需要跑

只有以下**全部**满足时,才需要跑本 backfill:

- [x] 已部署 M10+ (workspace 有 `dify_api_base` 等 4 字段)
- [x] 已部署 M11 PR2 (workspace 有 6 个 provisioning 字段 + `audit_logs` 表)
- [x] 存在历史 workspace —— 即在 M11 PR1 落地前已经完成 Dify 注册的 ws

判定 SQL(只看,不写):

```sql
SELECT COUNT(*) FROM workspaces
WHERE dify_provisioning_status = 'ready'
  AND dify_enabled = 0;
```

- 返回 `0` → 不需要跑(已是新注册路径落地的 DB)
- 返回 `>0` → 需要跑,继续下文

## 1. 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| 误改 `dify_enabled` 字段 | LOW | 默认 SQL 只命中 `provisioning_status='ready'` 的 ws,且只翻 0→1;不写凭据 |
| 误覆盖 `dify_api_base` | LOW | `--dify-api-base` 只在 `IS NULL` 时回填(不覆盖已有值) |
| `audit_logs` 表不存在 | LOW | 脚本探测表存在性,缺表时跳过 audit 不报错(但要补跑 m11 迁移) |
| 误填 admin 凭据 | **N/A** | 脚本**不回填** `dify_admin_email` / `dify_admin_password_ref` — 设计原则 |
| 并发写冲突 | LOW | SQLite 单写锁;生产 SQLite 通常停服维护窗口跑 |
| DB 文件损坏 | LOW | 脚本执行前强制 `shutil.copy2` 一份 `*.before_backfill_dify_enabled` |

> ⚠️ **脚本不会做也不该做的事**:
> - 不会发任何 HTTP 到 Dify(纯 DB 操作)
> - 不会改 `dify_admin_email` / `dify_admin_password_ref`(无凭据不能伪造)
> - 不会触发 `TenantService.register_tenant`(那是注册流,不是 backfill)

## 2. 步骤

### 2.1 准备

1. SSH 到生产 host,定位 DB 路径:

   ```bash
   ls -la /app/data/basjoo.db 2>/dev/null
   ls -la /root/basjoo/backend/data/basjoo.db 2>/dev/null
   ls -la ~/basjoo/backend/data/basjoo.db 2>/dev/null
   ```

   真实路径以 `install-deploy.sh` 安装日志里 `--volume` 那一行为准。

2. 确认 SQLite 可读写:

   ```bash
   sqlite3 /app/data/basjoo.db "SELECT 1"
   ```

3. (可选)记下当前 `dify_enabled=0` 的 ws 数,作为回滚指标:

   ```bash
   sqlite3 /app/data/basjoo.db "SELECT id, name FROM workspaces WHERE dify_enabled = 0"
   ```

### 2.2 Dry-run (强推)

```bash
cd /root/basjoo/backend  # 或实际 backend 路径
python3 scripts/backfill_dify_enabled.py --dry-run
```

预期输出 (示意):

```
[db] /app/data/basjoo.db
[correlation_id] <uuid>
[dry_run] True
[scan] 命中 3 行待 backfill workspace:
  - id=  1 name='default'            tenant=<uuid1> api_base=https://dify.example.com admin_email=None
  - id=  2 name='tenant-acme'        tenant=<uuid2> api_base=None               admin_email=None
  - id=  3 name='tenant-beta'        tenant=<uuid3> api_base=https://dify.example.com admin_email=None
[dry-run] 不写 DB,仅展示命中行
```

如果输出 `[scan] 命中 0 行`,说明不需要跑(参见 §0)。

如果输出有 N 行,**逐行 review**:
- `tenant=<uuid>` 必须看起来像合法 Dify UUID (形如 `abc12345-...`)
- `api_base=None` 的 ws 必须在 §2.3 传 `--dify-api-base` 才回填
- `admin_email=None` 的 ws 需要后续手动补,见 §4

### 2.3 实跑

如果 `dify_api_base` 字段有空 (上面 dry-run 输出有 `api_base=None`),需要传:

```bash
python3 scripts/backfill_dify_enabled.py \
    --dify-api-base "$DIFY_API_BASE" \
    --correlation-id "$(uuidgen)" 2>/dev/null || python3 scripts/backfill_dify_enabled.py \
    --dify-api-base "$DIFY_API_BASE"
```

如果 `dify_api_base` 都已经有值(单 Dify 部署),可以省 `--dify-api-base`:

```bash
python3 scripts/backfill_dify_enabled.py --correlation-id "$(uuidgen)"
```

预期输出:

```
[backup] → /app/data/basjoo.db.before_backfill_dify_enabled
[scan] 命中 3 行待 backfill workspace:
  ...
[update] dify_enabled=0→1 + api_base COALESCE fill: 3 行
[update] dify_api_base='https://dify.example.com' (本次回填): 1 行
[audit] 写入 3 条 audit_logs
[commit] ✅ backfill 完成

[result] enabled=3 api_base_filled=1 audit=3
```

### 2.4 验证

```bash
sqlite3 /app/data/basjoo.db "SELECT id, name, dify_enabled, dify_provisioning_status FROM workspaces"
```

应该看到:
- 所有原本 `dify_enabled=0 AND provisioning_status='ready'` 的行 → `dify_enabled=1`
- 原本 `provisioning_status='pending'` 或 `'failed'` 的行 → 不变

audit_logs 验证:

```bash
sqlite3 /app/data/basjoo.db "SELECT tenant_id, action, correlation_id, created_at FROM audit_logs WHERE action='workspace.backfill_dify_enabled'"
```

应该看到与 §2.3 输出行数一致的 audit 行。

## 3. 回滚

如果发现 backfill 误改(虽然设计上不应该):

```bash
# 1. 停 backend 服务
docker compose --profile prod stop backend

# 2. 从备份恢复
cp /app/data/basjoo.db.before_backfill_dify_enabled /app/data/basjoo.db

# 3. 起 backend
docker compose --profile prod start backend
```

**不要**直接 `UPDATE workspaces SET dify_enabled=0` —— audit log 已经写出去,
回滚 DB 之后要**手动删 audit 行**:

```bash
sqlite3 /app/data/basjoo.db "DELETE FROM audit_logs WHERE action='workspace.backfill_dify_enabled' AND correlation_id='<刚才传的 id>'"
```

## 4. 后续(必须)

本 backfill **不回填 `dify_admin_email` / `dify_admin_password_ref`** —— 这两个字段
只能来自真实的 Dify 注册响应。对 `admin_email=None` 的历史 ws,运营必须:

1. 在 Dify 控制台(`http://<dify_api_base>/install` 或 `/admin`)手动创建 workspace owner
2. 把明文密码交给 basjoo admin
3. 调 basjoo 内部管理 endpoint (M11+ P0-A PR 2 已实现):

   ```bash
   curl -X POST "http://<basjoo>/api/v1/admin/workspaces/<workspace_id>/dify-admin-credentials" \
       -H "Authorization: Bearer $ADMIN_TOKEN" \
       -H "Content-Type: application/json" \
       -d '{"email": "...", "password": "..."}'
   ```

   或(临时方案)直接 SQL UPDATE(M11+ 之前):

   ```bash
   sqlite3 /app/data/basjoo.db "UPDATE workspaces SET dify_admin_email=?, dify_admin_password_ref=? WHERE id=?"
   # 注意:dify_admin_password_ref 必须是 Fernet 加密后的密文,不能填明文
   ```

4. 写 audit log(可选,管理 endpoint 自动会写)

## 5. 复跑(幂等性)

重复执行同一份脚本是**安全的**:

- `UPDATE ... WHERE dify_enabled=0` 在第二次运行时命中 0 行
- `audit_logs` INSERT 不会重复,因为新 `correlation_id` 是新 UUID
- `INSERT audit_logs` 多次记录从操作历史角度看反而是好事(每次 backfill 都有迹可循)

## 6. 相关链接

- 脚本: `backend/scripts/backfill_dify_enabled.py`
- 配套迁移: `backend/migrations/m11_dify_provisioning.py` (建字段) / `m10_dify_fields.py` (建 4 字段)
- 应用层: `backend/services/tenant_service.py::register_tenant` (新注册流 — 写 `dify_enabled=True`)
- 工具包: `backend/services/dify_toolkit/deployer.py` (Plan A 4-step deploy,依赖 `dify_enabled=True`)
- 决策记录: docs/m11plus/M11PLUS-CLOSURE.md §P0-A (待补)