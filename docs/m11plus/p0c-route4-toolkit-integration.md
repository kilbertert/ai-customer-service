# P0-C — Route #4 工具包集成(toolkit → basjoo service)

> **状态**: ⏸️ SPEC DRAFT (待 PR 实施)
> **基线**: P0-A 切回 + P0-B 8 步 checklist
> **优先级**: P0(必做) — M11+ backlog 第 3 项,Route #4 完整闭环必经
> **关联**: `M11-CLOSURE.md §4.1 P0-C` + `tools/dify_workflow_toolkit/` (1,757 LOC)

---

## 0. 一句话总结

把 `tools/dify_workflow_toolkit/`(1,757 行,SSH + docker exec + psycopg2 直写 `workflows.graph`)整包**复制 + 重构**到 `backend/services/dify_toolkit/`,改 4 件事:

- **C1 安全收敛**: 干掉 `SSHClient` / `docker exec` / `paramiko.AutoAddPolicy` / `docker inspect` 读 DB 凭据,改走 basjoo-side HTTP API + 直连 PostgreSQL(用 basjoo `settings.dify_db_url`)
- **C3 租户路由**: 从单 Dify 主机 `124.243.178.156` 硬编码改为 `DifyAdminClient.from_workspace(workspace)`,per-tenant
- **C2 升级适配**: 钉死 `workflows` 表 schema(`graph jsonb` / `version != 'draft'`),加 `SELECT information_schema.columns` 探针,P0-B 8 步 §6 跑回归
- **C4 工具包集成**: `cp -r tools/dify_workflow_toolkit/dify_workflow_toolkit/ backend/services/dify_toolkit/` + 改包名 + 加 `pyproject.toml` 复用 basjoo 依赖 + `__init__.py` 重新导出 4 公共类(Workflow / yml_validator / Deployer / Verifier)

实施 4 PR(总 +1,070/-413),builder/verifier 改 0 行,只改 deployer 的"如何到达 Dify"。

---

## 1. 现状盘清楚(阶段 0)

### 1.1 toolkit 模块清单(1,757 LOC)

| 模块 | LOC | 职责 | C1/C3 改造 |
|------|-----|------|-----------|
| `builder.py` | 518 | `Workflow` / `StartNode` / `LLMNode` / `CodeNode` / `EndNode` / `Variable` 构造器,`to_yaml()` | 改 0 行(Pure Python DSL)|
| `yml_validator.py` | 147 | `validate_yaml(text)` 静态校验 | 改 0 行 |
| `verifier.py` | 267 | `Verifier(ssh, endpoint)` curl POST `/api/.../chat` | **C1 改**: 改用 basjoo `httpx` + 调 Dify `/v1/chat-messages` (走 tenant 凭据,不调 SSH) |
| `deployer.py` | 369 | `Deployer(ssh)` SSH + docker cp + psycopg2 `UPDATE workflows SET graph` | **C1 改**: 改用 basjoo-side 直连 PG(用 `settings.dify_db_url`),干掉 SSH/docker exec |
| `cli.py` | 210 | Click CLI: `validate / deploy / verify / test-code` | **C1 改**: `deploy` / `verify` 子命令改调 basjoo HTTP API 而不是 SSH 直连 |
| `ssh_client.py` | 116 | `paramiko` 包装 + `docker exec` + `docker cp` + `AutoAddPolicy` | **C1 整文件删除** |

### 1.2 D9 直写是设计核心,不是 bug

toolkit README 明确说 "Dify web UI 不暴露发布新 workflow 版本的稳定 API" → **唯一可靠路径是 SSH → UPDATE workflows.graph**。这绕开 D9(c/d/e) 三个补丁(client library 不全 / API 不稳定 / DSL 解析无错)。但 SSH 这条路在 basjoo 多租户场景下有 4 个问题:

| 问题 | 严重度 | 后果 |
|------|--------|------|
| (a) `paramiko.AutoAddPolicy()` 静默接受未知 host key | 🔴 P0-1 | MITM 攻击,SSH 凭据泄露 |
| (b) DB 凭据靠 `docker inspect` 读,Dify 1.15+ `docker inspect` 字段可能变(D9e) | 🟠 P1-4 | 升级 1.15 后 deploy 静默失败 |
| (c) 单 Dify 主机 `124.243.178.156` 硬编码,多 tenant 隔离诉求下每个 workspace 应该是独立 Dify tenant | 🔴 P0-2 | basjoo 多租户 1 个 Dify 复用 = 串租户 |
| (d) `UPDATE workflows SET graph = %s::jsonb` 绕过 Dify auth,谁拿到 SSH 凭据都能改任何 App | 🟠 P1-5 | 内部威胁 + audit 缺口 |

### 1.3 basjoo-side 已有的同构能力(M11 PR1 + PR3 + P0-A 落地)

| 能力 | basjoo 实现 | 复用方式 |
|------|------------|----------|
| 登录 Dify + Bearer token | `DifyAdminClient` (M11 PR1 fork) | C1 干掉 `paramiko`,改用 `DifyAdminClient` |
| 多租户凭据 | `Workspace.dify_api_base + dify_admin_email + dify_admin_password_ref` (P0-A 落 4 字段) | C3 替换硬编码 IP |
| 直连 PostgreSQL(已有 docker-compose) | `services.dify.db` 模块(待建,本 spec §4.5) | C1 替换 `docker inspect` 拿凭据 |

### 1.4 不集成会怎样

新 basjoo 客户 onboard → 走 P0-A Plan A → Dify 后台有 App 框架但 workflow 是空的(只有 Start + End)→ 用户必须**手动**在 Dify Studio 拖节点(几百行)→ 或者用 toolkit SSH 直连(凭据需 ops 提供且要暴露 SSH)→ 任一路径都不可规模化。

---

## 2. 问题清单 + 严重度(阶段 1)

### 🔴 P0-3 — `paramiko.AutoAddPolicy()` + SSH 凭据明文传递

- **现象**: `tools/dify_workflow_toolkit/ssh_client.py:41` `self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())` + `__init__` 直接接 `password=...`
- **影响**: (1) MITM 攻击无防护,(2) `DIFY_SSH_PASSWORD` env 散落 ops 终端
- **决策选项**:
  - A. 删 SSHClient,改用 basjoo-side 直连 Dify API (DifyAdminClient) + 直连 PG (psycopg2 over Dify DB) (**选,本 spec C1**)
  - B. 保留 SSHClient,改成 `RejectPolicy` + 强制 `~/.ssh/known_hosts` 预置 (只解决 (1),不解决 (2))
  - C. 加 `bastion` 跳板 + audit log (运维成本翻倍)

### 🔴 P0-4 — 硬编码单 Dify 主机,不支持 per-workspace

- **现象**: `tools/dify_workflow_toolkit/cli.py:154` 强制 `--ssh-host 124.243.178.156`;`deployer.py:18` 注释 "DB connection details are auto-read from `docker inspect` of the api container"
- **影响**: basjoo 多租户(M11 PR3 register 已经按 workspace 切分)下,所有 workspace 共享一个 Dify tenant,违反隔离战略(`basjoo-dify-isolation-strategy.md`)
- **决策选项**:
  - A. `Deployer.from_workspace(workspace)` 从 `Workspace.dify_api_base` 拿目标 Dify,`DifyAdminClient.from_workspace(workspace)` 拿 admin token (**选,本 spec C3**)
  - B. 改用 env var `--dify-host` 但仍单实例(只解决 50%,需 ops 切来切去)
  - C. 写一个 Dify router 端点 `POST /dify-router/{workspace_id}/deploy` (架构最干净,但 P0-C 不必做这步,先用 A)

### 🟠 P1-6 — Dify 1.15+ 升级后 `workflows` 表 schema 漂移

- **现象**: `deployer.py:76-79` `UPDATE workflows SET graph = %s::jsonb, updated_at = NOW() WHERE app_id = %s AND version != 'draft'` — 钉死列名 `graph` / `version` / `updated_at` / `app_id`
- **影响**: Dify 1.15+ 若给 `workflows` 表加 `published_at` 列 / 改 `version` 类型 / 加 `tenant_id` 列(多租户化),本 SQL 仍能跑(只 set 4 列),但 `WHERE version != 'draft'` 可能在 v2 = UUID 时变 false
- **决策选项**:
  - A. 加 `constants.DIFY_WORKFLOWS_TABLE_SCHEMA = {"graph": "jsonb", "version": "text", "app_id": "uuid", "updated_at": "timestamp"}` + `probe_workflows_schema()` 在 deploy 开头跑 `SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'workflows'`,不匹配则 5xx 报错 (**选,本 spec C2**)
  - B. 不动,等升级时出问题再修 (回滚成本)
  - C. 用 Alembic 维护一套 Dify 端 schema mirror (维护成本爆炸,不做)

### 🟠 P1-7 — DB 写绕过 Dify auth 层,无 audit

- **现象**: `UPDATE workflows SET graph = ...` 直接走 DB 写,绕开 Dify 端 RBAC;toolkit 无 audit log
- **影响**: 谁拿到 SSH 凭据都能改任何 App,出事故无法追溯
- **决策选项**:
  - A. 改用 DifyAdminClient `POST /console/api/apps/{app_id}/workflows/publish` API(D9c 已 cover),失败再 fallback DB 直写 + audit 写 `basjoo.AuditLog` (**选,本 spec C1**)
  - B. 保留 DB 直写,加 basjoo `AuditLog(action="workflow.deploy_db_direct")` (折中,audit 仍写,但 bypass Dify auth 风险在)
  - C. 改 Dify 端,加 audit trigger (碰 Dify 端,不做)

### 🟡 P2-2 — 工具包不在 basjoo 仓库 import 路径上

- **现象**: `tools/dify_workflow_toolkit/` 是 sub-package,需 `pip install -e .` 才能在 basjoo `import dify_workflow_toolkit`
- **影响**: 脚本化操作不在 basjoo runtime 可见,前端 / ops dashboard 无法触发
- **决策选项**:
  - A. `cp -r` 进 `backend/services/dify_toolkit/` + basjoo `pyproject.toml` 配 `dify_toolkit = { path = "./backend/services/dify_toolkit" }` (uv/pip 自动 link) (**选,本 spec C4**)
  - B. 保留 `tools/dify_workflow_toolkit/`,加 `pip install -e` 进 Dockerfile (Docker 镜像分层 OK,但 IDE 跳转 / type check 不友好)
  - C. 发布到内部 pypi (过度工程,2-3 个 PR 搞不定)

---

## 3. 决策日志(阶段 2)

### D8 ✅ — C1 安全收敛 = 干掉 SSH/docker,改 basjoo-side 直连

**决策**: 删 `tools/dify_workflow_toolkit/ssh_client.py` 整文件 + `deployer.py` 的 SSH 路径 + `verifier.py` 的 SSH 路径,改用:

| 旧 toolkit 路径 | 新 basjoo 路径 |
|----------------|---------------|
| `SSHClient(host, password)` | `settings.dify_db_url` (psycopg2 直连) + `DifyAdminClient.from_workspace(workspace)` (HTTP) |
| `docker exec docker-api-1 python3 deploy.py` | 删 (`deploy.py` 整段内联到 `Deployer.deploy()`,在 basjoo process 跑) |
| `docker inspect ... DB_HOST/DB_PORT/...` | 删 (`settings.dify_db_url` 直接给 `postgresql://user:pass@host:port/db`) |
| `paramiko.AutoAddPolicy()` | 删 (无 SSH = 无 host key 问题) |
| `UPDATE workflows SET graph = ...` (Dify auth bypass) | 优先 `DifyAdminClient.publish_workflow(app_id, graph)` (走 Dify auth);失败 fallback DB 直写 + 写 `basjoo.AuditLog(action="workflow.deploy_db_fallback")` |

**对架构的约束**:
- `DifyAdminClient.publish_workflow` 已在 M11 PR1 fork 落地 (D9c),本 spec 不重写,只复用
- DB 直连走 `services.dify.db` 新模块 (`settings.dify_db_url` + `psycopg2.pool.ThreadedConnectionPool`),fallback 路径
- basjoo 跟 Dify 在同一 Docker network(默认),所以 DB 直连无网络层问题;跨 host 走 TLS
- 不再需要 `DIFY_SSH_PASSWORD` env,ops 切换 SSH 凭据 → 切 `settings.dify_db_url` (Vault 友好)

### D9 ✅ — C3 租户路由 = Deployer.from_workspace(workspace)

**决策**: 新 `Deployer.from_workspace(workspace, db)` 替代 `Deployer(ssh)`,从 `workspace` 拿:

```python
@classmethod
def from_workspace(cls, workspace: "Workspace", db: AsyncSession) -> "Deployer":
    return cls(
        dify_api_base=workspace.dify_api_base,
        dify_admin=DifyAdminClient.from_workspace(workspace),  # P0-A 落地
        dify_db_url=settings.dify_db_url,                       # 共享 Dify DB (Plan A 共用)
        workspace_id=workspace.id,
    )
```

**对架构的约束**:
- **Plan A 共用 Dify 实例,per-workspace 切 `tenant_id`**: basjoo 自部署单 Dify,所有 workspace 共享,workflow deploy 用 `workspace.dify_tenant_id` 过滤 row
- **未来 Dify Cloud 模式**: `workspace.dify_api_base` 已是 per-workspace,D9 决策已为 per-tenant API key 留位(`basjoo-dify-isolation-strategy.md`)
- `cli.py deploy` 子命令加 `--workspace-id` 参数(从 `basjoo.AuditLog` 拿 workspace),不再 `--ssh-host`
- 单 Dify 主机 (124.243.178.156) 硬编码从 cli / 文档全删,改用 `basjoo settings.dify_api_base`

### D10 ✅ — C2 升级适配 = 钉死 schema + 探针 + 引用 P0-B §6

**决策**: 新 `services.dify_toolkit.constants` 模块 + `probe_workflows_schema()` 探针:

```python
# constants.py
DIFY_WORKFLOWS_REQUIRED_COLUMNS = {
    "id": "uuid",
    "app_id": "uuid",
    "version": "text",
    "graph": "jsonb",
    "updated_at": "timestamp",
}

# db.py
def probe_workflows_schema(conn) -> list[str]:
    """Return list of missing required columns. Empty = OK."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = 'workflows'
        """)
        actual = {row[0]: row[1] for row in cur.fetchall()}
    return [
        c for c, t in DIFY_WORKFLOWS_REQUIRED_COLUMNS.items()
        if c not in actual or actual[c] != t
    ]
```

**对架构的约束**:
- `Deployer.deploy()` 开头调 `probe_workflows_schema()`,missing → raise `DifySchemaError`(basjoo 端 5xx + audit `workflow.deploy_schema_mismatch`)
- Dify 1.15+ 升级时 P0-B §6 跑回归 (7 P0-A pytest + 1 沙箱 E2E),其中 sandbox E2E 包含 `tools/check_dify_1_15_breaking.sh` 第 5 类 "DB migration" 命中 `workflows` 表时,本探针会拒绝写并标 P0-B blocker
- 钉死 schema 不写 Alembic(避免碰 Dify 端),探针 + P0-B §6 双保险

### D11 ✅ — C4 集成 = cp 到 `backend/services/dify_toolkit/` + 改包名

**决策**: 文件级集成 + 重命名:

```bash
# 1. 复制
cp -r tools/dify_workflow_toolkit/dify_workflow_toolkit/ backend/services/dify_toolkit/

# 2. 全局重命名 package (避免与 services/dify/ 冲突)
#   dify_workflow_toolkit → dify_toolkit
#   builder/verifier/deployer/yml_validator/__init__ 内 import 路径全改

# 3. 删 ssh_client.py (C1 决策)

# 4. 改 deployer.py/verifier.py 用 basjoo deps (config.settings, models.Workspace, services.dify.db)

# 5. 加 backend/services/dify_toolkit/__init__.py 重新导出 4 公共类
#   from .builder import Workflow, StartNode, LLMNode, CodeNode, EndNode, Variable
#   from .yml_validator import validate_yaml
#   from .deployer import Deployer
#   from .verifier import Verifier, TestCase
```

**对架构的约束**:
- `tools/dify_workflow_toolkit/` 保留(只读 archive),`backend/services/dify_toolkit/` 是活跃 fork
- `pyproject.toml` (basjoo 根) 已有 `paramiko` / `pyyaml` 间接依赖(走 Dify 集成层),无需新加;只加 `dify_toolkit = { path = "./backend/services/dify_toolkit" }` (uv workspace)
- `examples/health_consult_v2.py` 移到 `backend/services/dify_toolkit/examples/`(跟随 fork)
- `tests/test_builder.py` / `tests/test_example.py` 移到 `backend/tests/test_dify_toolkit_*.py`,跑 `pytest backend/tests/`
- 老 `tools/dify_workflow_toolkit/` 加 `DEPRECATED.md` 指向新地址,3 个月后删

---

## 4. spec 详细(阶段 3)

### 4.1 改动文件清单 (本 spec 4 PR)

| PR | 文件 | 改动 | 行数 |
|----|------|------|------|
| 1 | `backend/services/dify_toolkit/__init__.py` | 新建,re-export 4 公共类 | +25 (新) |
| 1 | `backend/services/dify_toolkit/builder.py` | 复制 + 改 import `dify_workflow_toolkit.X` → `dify_toolkit.X` | +0 / -3 |
| 1 | `backend/services/dify_toolkit/yml_validator.py` | 同上 | +0 / -1 |
| 1 | `backend/services/dify_toolkit/ssh_client.py` | **删除** | -116 |
| 1 | `tools/dify_workflow_toolkit/DEPRECATED.md` | 新建,指向新地址 | +20 (新) |
| 2 | `backend/services/dify_toolkit/deployer.py` | 改写:删 SSH,加 `from_workspace`,加 `probe_workflows_schema`,DB fallback + audit | +150 / -200 |
| 2 | `backend/services/dify_toolkit/db.py` | 新建,psycopg2 pool + `probe_workflows_schema` | +80 (新) |
| 2 | `backend/services/dify_toolkit/constants.py` | 新建,`DIFY_WORKFLOWS_REQUIRED_COLUMNS` | +30 (新) |
| 2 | `backend/services/dify_toolkit/verifier.py` | 改写:删 SSH,改用 `DifyAdminClient` + `httpx` | +30 / -50 |
| 2 | `backend/services/dify_toolkit/cli.py` | 改:子命令 `deploy/verify` 改调 basjoo HTTP API | +20 / -40 |
| 2 | `backend/api/v1/endpoints.py` | 加 `POST /api/v1/workflows/{agent_id}/deploy` + `POST /api/v1/workflows/{agent_id}/verify` | +80 (新) |
| 2 | `backend/services/dify_toolkit/exceptions.py` | 新建,`DifySchemaError` / `DifyPublishError` | +30 (新) |
| 3 | `backend/tests/test_dify_toolkit_builder.py` | 复制 `test_builder.py` + 改 import | +0 / -3 |
| 3 | `backend/tests/test_dify_toolkit_p0c.py` | 新建,4 单元测试: `from_workspace` / `probe_schema` / `publish_api` / `db_fallback` | +120 (新) |
| 3 | `backend/tests/test_api_workflow_deploy.py` | 新建,2 端点测试: `200 deploy` / `502 schema_mismatch` | +80 (新) |
| 4 | `docs/m11plus/p0c-route4-toolkit-integration.md` | 本文件 | +250 (本文件) |
| 4 | `docs/m11/M11-CLOSURE.md §4.1` | P0-C 标 ✅ | +5 / -3 |
| 4 | `docs/m11plus/M11PLUS-CLOSURE.md` | 草稿 (P0-A + P0-B + P0-C 收口) | +150 (新) |
| **总** | | | **+1,070 / -413** |

### 4.2 关键代码 diff (PR 2 `deployer.py` 重写)

```diff
-# tools/dify_workflow_toolkit/dify_workflow_toolkit/deployer.py (369 行)
-"""Deploy a Dify workflow DSL to a running Dify instance over SSH."""
-from dify_workflow_toolkit.ssh_client import SSHClient
+# backend/services/dify_toolkit/deployer.py (重写后 200 行)
+"""Deploy a Dify workflow DSL to the workspace's Dify tenant.
+
+Plan A 路径 (D8 决策): 优先 DifyAdminClient.publish_workflow (走 Dify auth);
+失败 fallback DB 直写 (用 settings.dify_db_url) + basjoo.AuditLog 留痕。
+升级 1.15+ 时 (D10 决策): probe_workflows_schema() 在 deploy 开头探针,
+缺列即 raise DifySchemaError(5xx),不静默死。
+"""
+from sqlalchemy.ext.asyncio import AsyncSession
+from config import settings
+from models import AuditLog, Workspace
+from services.dify.admin_client import DifyAdminClient
+from services.dify_toolkit import constants, db, exceptions

-class Deployer:
-    def __init__(self, ssh: SSHClient) -> None: ...
-    def deploy(self, yml, app_id, restart=True, must_have_nodes=None): ...
+class Deployer:
+    def __init__(
+        self,
+        dify_api_base: str,
+        dify_admin: DifyAdminClient,
+        dify_db_url: str,
+        workspace_id: int,
+    ) -> None: ...
+
+    @classmethod
+    def from_workspace(cls, ws: Workspace) -> "Deployer":
+        """D9 决策: 从 workspace 拿 4 字段构造,per-tenant 隔离。"""
+        return cls(
+            dify_api_base=ws.dify_api_base,
+            dify_admin=DifyAdminClient.from_workspace(ws),
+            dify_db_url=settings.dify_db_url,
+            workspace_id=ws.id,
+        )
+
+    async def deploy(
+        self, yml: str, app_id: str, db: AsyncSession,
+    ) -> "DeployResult":
+        # C2 探针 (D10)
+        missing = db.probe_workflows_schema()
+        if missing:
+            raise exceptions.DifySchemaError(f"workflows 缺列: {missing}")
+        # C1 Plan A 优先 (D8)
+        try:
+            graph = yaml.safe_load(yml)
+            await self.dify_admin.publish_workflow(app_id, graph)
+        except (DifyAuthError, DifyUpstreamError) as e:
+            # Fallback DB 直写 + audit
+            logger.warning("publish_workflow 失败,fallback DB 直写: %s", e)
+            db.write_workflow_graph(app_id, graph)
+            await self._audit_deploy_fallback(db, app_id, e)
+        return DeployResult(app_id=app_id, ...)
```

### 4.3 关键代码 diff (PR 2 `endpoints.py` 新增 2 端点)

```python
# backend/api/v1/endpoints.py 新增
@router.post("/workflows/{agent_id}/deploy")
async def deploy_agent_workflow(
    agent_id: int,
    payload: WorkflowDeployRequest,
    current_user: User = Depends(require_admin_or_super_admin),
    db: AsyncSession = Depends(get_db),
) -> WorkflowDeployResponse:
    """Route #4 主端点: 把 yml 部署到 agent 对应 workspace 的 Dify tenant。
    仅 workspace owner / super_admin 调 (D9 决策 + M11 D3 WORKSPACE_OWNER_ROLES)。
    """
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "agent not found")
    if not is_workspace_owner(current_user, agent.workspace_id):
        raise HTTPException(403, "需要 workspace owner 权限")
    workspace = await db.get(Workspace, agent.workspace_id)
    if not workspace.dify_enabled:
        raise HTTPException(400, "workspace 缺 Dify 凭据 (P0-A 未落地)")
    deployer = Deployer.from_workspace(workspace)
    try:
        result = await deployer.deploy(payload.yml, agent.dify_app_id, db)
    except DifySchemaError as e:
        raise HTTPException(502, f"Dify schema 不兼容: {e}")
    except DifyPublishError as e:
        raise HTTPException(502, f"Dify publish 失败: {e}")
    return WorkflowDeployResponse(
        app_id=result.app_id, deployed=True, ...
    )
```

### 4.4 测试矩阵

| 测试 | 入口 | 期望 |
|------|------|------|
| `test_dify_toolkit_builder.py` | 10 builder 单测 | 10/10 pass (复制 + 改 import) |
| `test_dify_toolkit_p0c::test_from_workspace` | `Deployer.from_workspace(mock_ws)` | 4 字段全 set, 引用 DifyAdminClient |
| `test_dify_toolkit_p0c::test_probe_schema_ok` | mock `probe_workflows_schema` return [] | deploy 走 Plan A 路径 |
| `test_dify_toolkit_p0c::test_probe_schema_missing` | mock return `["graph"]` | raise DifySchemaError, 5xx |
| `test_dify_toolkit_p0c::test_publish_api_success` | mock DifyAdminClient.publish_workflow | 不走 DB fallback, audit 写 success |
| `test_dify_toolkit_p0c::test_db_fallback_on_5xx` | mock DifyAdminClient 5xx | 走 DB fallback, audit 写 `db_fallback` |
| `test_api_workflow_deploy::test_200` | `POST /workflows/{id}/deploy` | 200, agent.dify_app_id 不变, deploy result 写 audit |
| `test_api_workflow_deploy::test_502_schema_mismatch` | mock probe 缺列 | 502, 错误信息含 missing columns |
| `test_api_workflow_deploy::test_403_not_owner` | mock 普通 user | 403, audit 写 forbidden |
| Dify 1.15+ 升级回归 (P0-B §6) | staging 跑 | 7 P0-A pytest + 1 sandbox E2E + 2 新 deploy 端点测试 = 10/10 pass |

### 4.5 数据库迁移

无需 Alembic 迁移:
- `DifyAdminClient.publish_workflow` 已在 M11 PR1 fork 落地 (D9c)
- `Workspace.dify_api_base` + `dify_admin_email` + `dify_admin_password_ref` + `dify_enabled` 4 字段 P0-A 已落 (`backend/models.py:61-72`)
- `AuditLog.action` 字段已支持 `workflow.deploy_db_fallback` / `workflow.deploy_schema_mismatch` 字符串 (varchar)

### 4.6 新增配置 (`backend/config.py`)

```python
# settings 新增 (D8 决策: 用 env 拿 Dify DB URL, ops 切凭据走 Vault)
dify_db_url: str = "postgresql://postgres:postgres@postgres:5432/dify"
# 说明: basjoo 跟 Dify 默认共用 postgres docker-compose service (单 DB 实例)
# 多 DB 场景 (Dify Cloud 模式) 改用 per-workspace URL, 留 P1+ 跟进
```

---

## 5. PR 实施计划(阶段 4)

1. **PR 1**: `refactor(m11plus): P0-C 工具包集成 — cp + 改包名 + 删 ssh_client`
   - `cp -r tools/dify_workflow_toolkit/dify_workflow_toolkit/ backend/services/dify_toolkit/`
   - 全局改 `dify_workflow_toolkit` → `dify_toolkit` (sed / 手工)
   - 删 `ssh_client.py` (暂时保留 deployer 的 SSH 路径不删,留给 PR 2)
   - `tools/dify_workflow_toolkit/DEPRECATED.md` 写迁移说明
   - 跑 `pytest backend/tests/test_dify_toolkit_builder.py -v` 期望 10/10 pass (复制即过,只改 import)
   - 不动 deployer/verifier (PR 2)

2. **PR 2**: `feat(m11plus): P0-C deployer 重写 — C1 安全收敛 + C3 租户路由 + C2 升级探针`
   - 改 `deployer.py` 删 SSH,加 `from_workspace` + `probe_workflows_schema` + DB fallback + audit
   - 改 `verifier.py` 删 SSH,改用 `DifyAdminClient` + `httpx`
   - 改 `cli.py` 子命令 `deploy/verify` 调 basjoo HTTP API
   - 新建 `db.py` / `constants.py` / `exceptions.py`
   - 加 `POST /api/v1/workflows/{agent_id}/deploy` 端点
   - 加 4 单元测试 + 2 端点测试
   - 跑 `pytest backend/tests/test_dify_toolkit_p0c.py -v` 期望 4/4 pass
   - 跑 `pytest backend/tests/test_api_workflow_deploy.py -v` 期望 2/2 pass
   - 跑 `pytest backend/tests/test_api.py` 期望 0 回归

3. **PR 3**: `chore(m11plus): P0-C 老 toolkit 归档 + Dockerfile 适配`
   - `tools/dify_workflow_toolkit/README.md` 顶部加 "DEPRECATED, moved to backend/services/dify_toolkit/"
   - `Dockerfile.backend` 移除 `tools/dify_workflow_toolkit` COPY(改成 COPY `backend/services/dify_toolkit/`)
   - `pyproject.toml` (basjoo 根) 加 `dify_toolkit = { path = "./backend/services/dify_toolkit" }`
   - `examples/health_consult_v2.py` 移到新地址并改 import
   - 不需要单元测试 (chore 类)

4. **PR 4**: `docs(m11plus): P0-C 收口 — M11-CLOSURE backlog 更新 + M11PLUS-CLOSURE 草稿`
   - `docs/m11/M11-CLOSURE.md §4.1` 移除 P0-C (标 ✅)
   - `docs/m11plus/M11PLUS-CLOSURE.md` 草稿 (P0-A + P0-B + P0-C 收口用)
   - `tools/dify_workflow_toolkit/DEPRECATED.md` 加 3 个月后删除时间表

### 5.6 不做 / 留 P1+

- 不做 "前端 UI 触发 deploy" → P1+ (前端 PR,本 spec 后端闭环即可)
- 不做 "Alembic 维护 Dify 端 schema mirror" → 不做,探针 + P0-B §6 双保险已够
- 不做 "Dify Cloud 模式 per-workspace DB URL" → P1+ (D9 决策留位)
- 不做 "toolkit publish API 优先 + DB fallback" 的开关 → 默认行为即最优,不做开关
- 不删 `tools/dify_workflow_toolkit/`(留 3 个月 archive,3 个月后整目录删)

---

## 6. 验收门(阶段 5)

| Gate | 状态 | 证据 |
|------|------|------|
| PR 1: `pytest backend/tests/test_dify_toolkit_builder.py` 10/10 pass | ⏳ | PR 1 跑 |
| PR 2: `pytest backend/tests/test_dify_toolkit_p0c.py` 4/4 pass | ⏳ | PR 2 跑 |
| PR 2: `pytest backend/tests/test_api_workflow_deploy.py` 2/2 pass | ⏳ | PR 2 跑 |
| PR 2: `pytest backend/tests/test_api.py` 0 回归 | ⏳ | PR 2 跑 |
| PR 2: `grep -r "AutoAddPolicy\|paramiko" backend/services/dify_toolkit/` 0 命中 | ⏳ | PR 2 跑 (C1 验证) |
| E2E: 旧 Plan B agent → `POST /workflows/{id}/deploy` → Dify 后台 graph 写新 | ⏳ | 沙箱 E2E (Playwright MCP + 162.211.183.169) |
| E2E: 多 workspace → 各 deploy 到自己 Dify tenant (per-tenant 隔离) | ⏳ | 沙箱 E2E (C3 验证) |
| Dify 1.15+ 兼容性 (P0-B §6 回归) | ⏳ | 升级时跑,本 spec PR 不直接验 |

---

## 7. 风险 + 缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| DifyAdminClient.publish_workflow 1.15+ 改 API | 中 | deploy 失败 | DB fallback 路径保留;P0-B §6 探针 |
| `workflows` 表 schema 漂移 | 中 | DB fallback 失败 | `probe_workflows_schema()` 探针 + 5xx 报错 |
| `DifyAdminClient.publish_workflow` 走的不是 published version 而是 draft | 中 | worker 读不到新 graph | `D9c` patch 已修 (M11 PR1);`publish_workflow` 默认走 published path |
| basjoo 跟 Dify 不在同一 Docker network(自部署 vs 托管) | 低 | DB fallback 网络断 | `settings.dify_db_url` 走 TLS + 凭据从 Vault |
| 老 toolkit 跟新 toolkit 行为不一致 | 低 | ops 切换工具时困惑 | PR 3 归档 + DEPRECATED.md 顶部红色 banner |
| `cp -r` 复制时漏掉 `__pycache__` / `.pyc` | 低 | 测出诡异 import 错 | 复制前 `find . -name __pycache__ -exec rm -rf {} +` |
| basjoo `pyproject.toml` 加 `dify_toolkit = { path = ... }` 跟 uv workspace 冲突 | 低 | 装包失败 | 用 editable install 验证 `pip install -e ./backend/services/dify_toolkit` |

---

## 8. 修订记录

| 版本 | 日期 | 改动 |
|------|------|------|
| v1.0 | 2026-06-18 | 初稿,D8/D9/D10/D11 决策 + 4 PR 实施计划 (C1/C2/C3/C4 拆分) |
