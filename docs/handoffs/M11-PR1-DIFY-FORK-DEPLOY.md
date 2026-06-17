# M11 PR1 Dify Fork Deploy + Verify

> **Scope**: M11 PR1 = Dify 1.14.2 fork patch (4 admin endpoints) + 端到端部署到 162.211.183.169 + E2E 验证。
> **Branch**: `feat/m11-admin-provision`
> **Commits**: `9285ecc` (initial) → `b0a1176` (amend: schemas move) → `e1f66dc` (amend: Dockerfile.fork 修正) → **`576f4e9` (amend: 4 server bugfix 同步回本地)**
> **Date**: 2026-06-17
> **Status**: ✅ **PASS** — 4 endpoints 端到端 6/6 测试通过(直连 api + nginx 外部 162.211.183.169:80)

---

## 1. 背景

M10+ 战略回答(2026-06-13)确定 basjoo 走 **Plan B** — basjoo 后端通过 HTTP 调 Dify 1.14.2 的 4 个 admin endpoint 来一次性创建 tenant + owner account(避免 basjoo 直接改 Dify DB)。

PR1 的目标:在 Dify 1.14.2 fork 上把这 4 个 endpoint 暴露出来,带 `ADMIN_API_KEY` Bearer auth,过 24h 幂等 + 单事务回滚。

---

## 2. 4 个 Admin Endpoint

| # | Method | Path | 用途 |
|---|--------|------|------|
| 1 | GET    | `/console/api/admin/workspaces/health` | 健康检查,返回 `fork_version: m11-v1.0` |
| 2 | POST   | `/console/api/admin/workspaces` | 创建 tenant + owner account,要求 32-36 字符 idempotency_key |
| 3 | GET    | `/console/api/admin/workspaces/{tenant_id}/owner-credentials` | 24h 内返回 owner 明文 password(24h 后 404) |
| 4 | DELETE | `/console/api/admin/workspaces/{tenant_id}` | 软回滚(供测试) |

**Auth**: `Authorization: Bearer ${ADMIN_API_KEY}` (.env 配,basjoo 持有)

**幂等保证**: 24h 内同 `idempotency_key` → 返回原 `workspace_id` + **原 password**(不重新生成)+ `idempotent_replay: true`。

---

## 3. 部署到 162.211.183.169 步骤

### 3.1 上传 dify-1.14.2/ 到服务器
```bash
# 在本机:
scp -r dify-1.14.2/ root@162.211.183.169:/home/ranlei/
# 或 rsync(增量)
```

### 3.2 构 fork 镜像
```bash
ssh root@162.211.183.169
cd /home/ranlei/dify-1.14.2
docker build -f Dockerfile.fork -t langgenius/dify-api:1.14.2-fork-m11-v1.0 .
```

### 3.3 配 .env
```bash
cd docker
cp .env.example .env
# 追加:
echo 'DIFY_API_IMAGE=langgenius/dify-api:1.14.2-fork-m11-v1.0' >> .env
echo "ADMIN_API_KEY=$(openssl rand -base64 36 | tr -d '\n=' | cut -c1-48)" >> .env
```

### 3.4 让 compose 用 fork 镜像(关键)
Dify stock `docker-compose.yaml` 把 image 写死成 `langgenius/dify-api:1.14.2`,**`DIFY_API_IMAGE` env 不会自动注入**。需要先把 4 处 image 行改成变量形式:
```bash
sed -i 's|image: langgenius/dify-api:1.14.2|image: ${DIFY_API_IMAGE:-langgenius/dify-api:1.14.2}|' docker/docker-compose.yaml
# 验证 4 处都改了:
grep -n 'dify-api' docker/docker-compose.yaml
```

### 3.5 启动 + 初始化 Dify + 应用迁移
```bash
cd docker
docker compose up -d                       # 起中间件 + 所有服务(初次)
docker compose up -d api worker worker_beat api_websocket  # 重启用 fork

# 初始化 Dify 管理员(只首次)
curl -s -X POST http://localhost:5001/console/api/setup \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@basjoo.test","name":"basjoo admin","password":"BasjooAdmin2026!"}'

# 应用 alembic 迁移(PR1 一次性 + 上游如有更新)
docker compose exec -T api flask db upgrade
```

### 3.6 注意事项
- **多 head 报错** `Multiple head revisions`: PR1 migration 改 `down_revision = ('fecff1c3da27', 'a4f2d8c9b731')` 自合 head(已在 `576f4e9` 落地)。第一次部署如果没改,fork image 启动会进 restart loop。
- **nginx 缓存旧 api IP**: api 重启后 nginx 仍连旧 IP 502。`docker compose restart nginx` 解决。
- **.env `ADMIN_API_KEY`** 改了之后必须 `docker compose restart api` 才生效。
- **API 端口**: `:5001` 是 docker 内部,外部访问走 nginx `:80`(`/console/api/*` 反代)。

---

## 4. E2E 测试结果(2026-06-17)

经 `http://162.211.183.169/console/api/admin/...` 外部访问 6/6 通过:

| # | Test | HTTP | 关键响应字段 |
|---|------|------|------|
| 1 | GET  /health | 200 | `{"status":"ok","fork_version":"m11-v1.0"}` |
| 2 | POST /workspaces (idempotency_key=`e2e12...`) | 200 | `workspace_id` + `owner_account_id` + `initial_password` + `idempotent_replay:false` |
| 3 | POST 同 key 重放 | 200 | **同** `workspace_id` + **同** `initial_password` + `idempotent_replay:true` |
| 4 | GET  /workspaces/{id}/owner-credentials | 200 | 返回明文 password |
| 5 | DELETE /workspaces/{id} | 204 | 空 body |
| 6 | GET credentials after DELETE | 404 | `{"error":"not_found","message":"Tenant not found"}` |

测试用幂等 key: `e2e12345-6789-abcd-ef01-23456789abcd` / `550e8400-e29b-41d4-a716-446655440000` / `aaaa1111-bbbb2222-cccc3333-dddd44445555`(36 字符上限校验)。

---

## 5. 期间发现并修复的 4 个问题

| # | 问题 | 根因 | 修复 |
|---|------|------|------|
| 1 | `ImportError: cannot import name 'AdminProvisionForbiddenError'` | Dockerfile.fork 没 COPY `errors/account.py`(里面加了 2 个新异常类) | Dockerfile.fork 加 `COPY api/services/errors/account.py` |
| 2 | `NameError: name 'TenantProvisionPayload' is not defined` | `workspace.py` 缺 `from controllers.console.workspace.models import ...` | 加 import |
| 3 | `Multiple head revisions` 循环重启 | PR1 migration 只接 `fecff1c3da27`,与上游 `a4f2d8c9b731` 头分叉 | PR1 migration 改 `down_revision = ('fecff1c3da27', 'a4f2d8c9b731')` 自合 head |
| 4 | **idempotent replay 返回新生成 password** | `account_service.py:1230` 在 replay 路径调 `_generate_initial_password()` | 改 `existing.initial_password_plain or _generate_initial_password()` |
| 5 | nginx 反代 502 | nginx 缓存了旧 api 容器 IP | `docker compose restart nginx` |

---

## 6. 文件清单(已入库 9 个,gitignore 强制跟踪)

| 类别 | 文件 |
|------|------|
| Dockerfile | `dify-1.14.2/Dockerfile.fork` |
| 新增 schema | `dify-1.14.2/api/services/admin_provision_schemas.py` |
| 新增 error 类 | `dify-1.14.2/api/services/errors/account.py`(2 个异常类) |
| Controller | `dify-1.14.2/api/controllers/console/workspace/{workspace,models,error}.py` |
| Service | `dify-1.14.2/api/services/account_service.py`(+`provision_tenant_by_admin` + `create_account_with_password`) |
| Model | `dify-1.14.2/api/models/account.py`(+3 列) |
| Migration | `dify-1.14.2/api/migrations/versions/2026_06_17_basjoo_admin_provision.py`(自合 head) |
| 单测 | `dify-1.14.2/api/tests/test_tenant_provision_by_admin.py`(13 case) |

`.gitignore` 已加注释说明 force-track 模式,详见 commit 576f4e9 后的 `.gitignore` 192-211 行。

---

## 7. 服务器 Dify 当前状态

| 维度 | 值 |
|------|---|
| Server IP | 162.211.183.169(Ubuntu 22.04) |
| Dify console 入口 | `http://162.211.183.169/install`(已 init) |
| Dify 管理员 | `admin@basjoo.test` / `BasjooAdmin2026!` |
| fork image | `langgenius/dify-api:1.14.2-fork-m11-v1.0` |
| DB revision | `2026_06_17_basjoo`(3 列已加) |
| ADMIN_API_KEY | `uZ/sKPiywz/u+wZtzbzRR7drXw/x8l6PTKU8OgpTm6ItF7P2`(仅 Dify 端,.env) |
| API 端口 | 内部 5001 / 外部走 nginx 80 |
| Tenant 表新列 | `custom_idempotency_key` / `created_via_admin_at` / `initial_password_plain` |

basjoo 后端(`DifyProvider` / `services/dify/`)调这 4 个 endpoint 的客户端封装待 PR3。

---

## 8. 后续 PR 衔接

- **M11 PR2 (Dify 升级 1.15)**: 已写 spec `docs/handoffs/M11-DIFY-1.15-UPGRADE.md`,6 个补丁逐一回测。在 PR1 fork 上做,本 handoff 的部署链可复用。
- **M11 PR3 (basjoo backend DifyProvider 接入)**: 写 `services/dify/dify_admin_client.py` 调这 4 个 endpoint + pytest 集成测试(真 Dify 走 162.211.183.169)。
- **M11+ P2 (运维)**: 已完成 Dify data 三层备份 + 9 URL indexing 测试修完,见 `M11-P2-DIFY-DATA-BACKUP.md`。
