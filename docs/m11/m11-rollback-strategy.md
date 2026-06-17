# M11 Rollback Strategy — 回滚预案 + Dify 升级 Playbook 占位

> **范围**:M11 整体回滚策略 + 各 PR 单 PR 回滚 + Dify 升级 playbook 占位章节

---

## 1. 单 PR 回滚策略

### PR1(Dify fork)

**回滚方式**:切回旧 Dify 镜像
```bash
sed -i 's/DIFY_IMAGE_VERSION=.*/DIFY_IMAGE_VERSION=1.14.2-baseline/' .env
docker compose down dify
docker compose up -d dify
```

basjoo 侧无需改动,`DifyAdminClient` 自动重建 session。无数据影响。

### PR2(schema 迁移)

**回滚方式**:`alembic downgrade -1`

**数据丢失风险**:若 PR2 已上线一段时间,workspaces 表里 `dify_*` 字段填充,**downgrade 会丢失这些数据**。建议:
- 回滚前先备份:`sqlite3 backend/.pytest_dbs/prod.db ".backup backup.db"` 或 `pg_dump`
- 评估:若没有 B 端注册过可安全 downgrade;若有,需保留 Dify 端数据重建 basjoo 记录

### PR3(注册流后端)

**回滚方式**:git revert PR3 + 重启 basjoo

**注意**:`/tenants/register` 撤回后:
- 已注册的 B 端 workspace 仍存在(Dify tenant 不会消失)
- basjoo 端无法再注册新租户,直到 PR3 重新部署
- 已 failed 的 workspace 无法自动重试,需手动调 Dify DELETE 后重建

### PR4(前端 + 路由层)

**回滚方式**:git revert PR4 + 重启前端 + 重启后端

**注意**:前端 `/signup` 撤回后新用户无法自助注册。后端 M3/M6/M7 路由层重写撤回后,所有 workspace-scoped 调用回退到全局路由(可能短暂数据错乱)。

---

## 2. M11 整体回滚策略

### 场景:M11 已上线一段时间后出现严重问题

**优先级**:数据完整性 > 用户体验 > 业务流程

#### Step 1:冻结 basjoo 写入(5 分钟)

```bash
# 在 backend/config.py 加 BASJOO_TENANT_REGISTER_DISABLED=true
# 或在 nginx 层 block /api/v1/tenants/*
```

#### Step 2:备份 basjoo + Dify 数据库(15 分钟)

```bash
# basjoo
sqlite3 backend/.pytest_dbs/prod.db ".backup backup_$(date +%s).db"
# 或
pg_dump basjoo > backup_$(date +%s).sql

# Dify
pg_dump dify > dify_backup_$(date +%s).sql
```

#### Step 3:评估回滚范围(30 分钟)

| 问题 | 回滚范围 |
|------|----------|
| 仅前端 bug | 回滚 PR4 前端 |
| 注册流 bug | 回滚 PR3 + PR4 |
| Schema 问题 | 回滚 PR2 + PR3 + PR4 + alembic downgrade |
| Dify fork 端点 bug | 切回旧 Dify 镜像 + 回滚 PR3 PR4 |

#### Step 4:按顺序回滚 PR

按 PR4 → PR3 → PR2 → PR1 逆序回滚。

#### Step 5:通知 B 端用户(已注册的)

- 邮件通知:`dify_provisioning_status='ready'` 不受影响,可正常使用
- `status='failed'` 的 workspace:**必须**逐个手工恢复(basjoo admin 调 Dify DELETE 后重建)

---

## 3. Dify 升级 Playbook(冻结期不要求跑,升级时刻执行)

> **本章节由 ops 团队在 Dify 自部署版本升级时刻执行。M11 立项时预留,实际执行延后到升级决策日。**

### 3.1 升级前准备(冻结期随时可做)

- [ ] 备份当前 Dify 数据库:`pg_dump dify > dify_pre_upgrade_$(date +%s).sql`
- [ ] 备份 Dify 上传文件:`tar czf dify_storage_$(date +%s).tgz /app/api/storage`
- [ ] 确认 Dify 当前版本 + basjoo PR1 Dockerfile.fork 基线版本
- [ ] 评估升级范围:minor 升级(1.14.x → 1.15.x)?major 升级(1.14 → 2.0)?
- [ ] 检查 Dify release notes:`https://github.com/langgenius/dify/releases`

### 3.2 升级时 5 条 checklist(必跑,任一失败阻断升级)

```bash
# 在 Dify 新版本源码下跑(冻结期不跑,升级时跑)
cd dify-new-version

# 1. TenantService.create_tenant 存在?
grep -n "def create_tenant" api/services/account_service.py
# 期望:匹配,签名类似 (name: str, is_setup: bool = False, ...)

# 2. TenantService.create_tenant_member 存在?
grep -n "def create_tenant_member" api/services/account_service.py
# 期望:匹配

# 3. AccountService.create_account 可重载?
grep -n "def create_account" api/services/account_service.py
# 期望:匹配,且非 underscore 前缀

# 4. 是否有新的 tenant 强制初始化逻辑?
grep -A 20 "def create_tenant" api/services/account_service.py | grep -i "plugin\|credit\|encrypt"
# 期望:与 PR1 实现的初始化步骤一致

# 5. @admin_required 装饰器位置?
grep -n "def admin_required" api/controllers/console/wraps.py
# 期望:仍存在
```

### 3.3 升级步骤

```bash
# 1. 拉取 Dify 新版本源码
git fetch origin
git checkout v1.15.x

# 2. rebase Dify fork 改动
git checkout m11-fork
git rebase v1.15.x

# 3. 跑 Dify 侧单测
pytest api/tests/

# 4. 构建 fork 镜像
docker build -f Dockerfile.fork -t langgenius/dify-api:1.15.x-fork-m11-v1.0 .

# 5. 切 basjoo .env
sed -i 's/DIFY_IMAGE_VERSION=.*/DIFY_IMAGE_VERSION=1.15.x-fork-m11-v1.0/' .env

# 6. 重启 Dify
docker compose down dify
docker compose up -d dify

# 7. 验证 fork endpoint
curl -b /tmp/dify_admin_cookie http://dify:5001/console/api/admin/workspaces/health
# 期望:200 OK + fork_version: m11-v1.0

# 8. 跑 basjoo 测试套件
cd ../
pytest backend/tests/m11/
```

### 3.4 升级后 24h 监控

```sql
SELECT
  dify_provisioning_status,
  COUNT(*) AS count,
  100.0 * COUNT(*) / SUM(COUNT(*)) OVER () AS percentage
FROM workspaces
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY dify_provisioning_status;

-- 期望:status='ready' > 95%
-- 若 'failed' > 5%,触发回滚
```

### 3.5 升级失败回滚 SOP

```bash
# 1. 切回旧 Dify 镜像
sed -i 's/DIFY_IMAGE_VERSION=1.15.x-fork-m11-v1.0/DIFY_IMAGE_VERSION=1.14.x-fork-m11-v1.0/' .env

# 2. 重启 Dify
docker compose down dify
docker compose up -d dify

# 3. 验证旧镜像可用
curl http://dify:5001/console/api/admin/workspaces/health

# 4. 通知开发团队升级失败,记录原因
```

### 3.6 basjoo 侧无需改动

回滚 Dify 镜像后,baskjoo 无需重启(`DifyAdminClient` LRU 缓存自动重建)。

---

## 4. 升级 playbook 维护责任

- **M11 PR1 合入后**:ops 团队接管本 playbook
- **playbook 更新频率**:每次 Dify 升级后,无论成功失败,更新 checklist 实际表现
- **playbook 存放**:`docs/operations.md` 的"Dify 升级 playbook"专章
- **触发条件**:用户决定升级 Dify 自部署版本

---

## 5. 风险缓解回顾

| 风险 | 回滚手段 | RTO(恢复时间目标) |
|------|----------|---------------------|
| Dify fork bug | 切旧镜像 | 5 分钟 |
| PR2 schema 升级失败 | alembic downgrade | 5 分钟 |
| PR3 注册流 bug | git revert PR3 | 10 分钟 |
| PR4 前端 bug | git revert PR4 前端 | 5 分钟 |
| Dify 升级失败 | 切旧镜像 + basjoo 不动 | 10 分钟 |
| 已注册的 B 端数据错乱 | 手工 Dify DELETE + basjoo 重建 | 1 小时/workspace |

---

## 6. 演练计划

| 演练 | 频率 | 负责人 |
|------|------|--------|
| alembic upgrade/downgrade | 每次 PR2 部署 | dev |
| basjoo 单 PR 回滚演练 | 每季度 | dev |
| Dify 升级 dry-run(冻结期不跑) | 升级前 1 周 | ops + dev |

---

## 7. 应急预案联系人(占位,实际填写)

```
平台故障:baskjoo-ops@example.com
Dify 侧故障:baskjoo-dev@example.com
数据恢复:baskjoo-data@example.com
```