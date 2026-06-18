# M11PLUS-CLOSURE — M11+ P0-A/B/C 系列收口

> **版本**:v0.1 草稿(M11+ 闭环同步件,与 M11-CLOSURE.md v1.1 配套)
> **收口日期**:2026-06-18
> **基线 HEAD**:`404f191`(本仓库 `feat/m11-frontend-routing` 分支)
> **状态**:M11+ P0-A/B/C 全部闭环
> **阅读对象**:接手 M12+ backlog / 复盘 M11+ 工作流的人(用户本人或新 Claude)

---

## 0. 一句话总结

**M11+ = M11 系列收口(2026-06-17)后 24 小时内,M11-CLOSURE.md §4.1 列的 3 个 P0 必做项的闭环工作**。P0-A(Plan A 切回)+ P0-B(Dify 1.15+ 升级 prep)+ P0-C(Dify workflow 工具包集成层重写)3 个 stream 全部 ✅,留 5 项 P1-E 真机 E2E 验证 + 2 项 P2 视情况启动给 M12+。

**与 M11-CLOSURE 关系**:M11-CLOSURE 是 M11 主线收口(本文件是它的 §4.1 backlog 闭环注记),M11PLUS-CLOSURE 是 M11+ 主线收口(M11-CLOSURE 的 §4.1 是它的输入)。两份文件互相引用。

---

## 1. 系列交付清单(P0-A/B/C 三 stream)

| Stream | 范围 | 关键 commit | spec / doc |
|--------|------|------------|-----------|
| **P0-A** Plan A 切回 | `services/tenant_service.py::register_tenant` 阶段 3 写 `dify_enabled=True` + 4 字段;**历史 ws backfill 脚本** `scripts/backfill_dify_enabled.py` + runbook;**真机 E2E 待补** | PR1-PR3 已合(`e0f0b6b` ~ `5e00c2f`);PR3 backfill + PR4 doc = 本会话 | (本文件 §3.1 + runbook) |
| **P0-B** Dify 1.15+ 升级 prep | 5+3=8 checklist 全部条目化;升级日执行脚本待写 | `docs/handoffs/M11-DIFY-1.15-UPGRADE.md` 已存在(M11+ 早期 commit) + `scripts/check_dify_1.15_breaking.sh`(升级日 grep 脚本) | `docs/handoffs/M11-DIFY-1.15-UPGRADE.md` |
| **P0-C** Dify workflow 工具包集成 | 干掉 SSH / docker exec / paramiko;走 HTTP API + DB 直连;`services/dify_toolkit/` 5 新模块 + 9 测试 PASSED | P0-C PR 1-3 = 本会话(`deployer.py` / `verifier.py` / `cli.py` / `db.py` / `constants.py` / `exceptions.py` + 2 测试文件) | (本文件 §3.3) |

### 1.1 本会话(M11+ P0 闭环)新增/修改文件清单

**新增**:
- `backend/services/dify_toolkit/constants.py` — DIFY_WORKFLOWS_REQUIRED_COLUMNS 等常量
- `backend/services/dify_toolkit/exceptions.py` — DifySchemaError / DifyPublishError
- `backend/services/dify_toolkit/db.py` — psycopg2 ThreadedConnectionPool + probe / check / update
- `backend/services/dify_toolkit/deployer.py` — Deployer / DeployResult (重写)
- `backend/services/dify_toolkit/verifier.py` — Verifier / TestCase / CaseResult / VerificationReport (重写)
- `backend/services/dify_toolkit/cli.py` — Click CLI(validate / deploy / verify 子命令)
- `backend/scripts/backfill_dify_enabled.py` — 历史 ws backfill 脚本
- `backend/tests/test_dify_toolkit_p0c.py` — 6 单元测试(Deployer)
- `backend/tests/test_api_workflow_deploy.py` — 3 端点集成测试
- `backend/docs/runbooks/m11plus-p0a-backfill-dify-enabled.md` — backfill runbook
- `docs/m11plus/M11PLUS-CLOSURE.md` — **本文件**

**修改**:
- `backend/services/dify_toolkit/__init__.py` — 加 5 模块 export,`__version__ = "0.3.0-p0c-pr2"`
- `backend/config.py` — 加 `dify_db_url` 配置
- `backend/api/v1/endpoints.py` — 加 `POST /workflows/{agent_id}/deploy` 端点 + 2 Pydantic model
- `docs/m11/M11-CLOSURE.md` — v1.0 → v1.1(§2 + D5-D9 / §3 + 3 P0 gate / §4.1 P0 mark ✅ / §9 + revision log)

---

## 2. 决策基线(LOCKED — 不再翻案)

| 决策 ID | 内容 | 影响范围 | 来源 |
|---------|------|----------|------|
| **D5** | Dify 1.14.2 fork **冻结期不 rebase**,升级时刻按 5+3=8 checklist 验 | 升级必跑 `docs/handoffs/M11-DIFY-1.15-UPGRADE.md` + `scripts/check_dify_1.15_breaking.sh`;冻结期内所有 Dify 改动走 fork patch | M11+ 战略 |
| **D6** | **Plan B 维持** + 准备 per-tenant API key(Plan A 是部署拓扑,不是必须) | basjoo 核心 = workspace-level 隔离;Plan A 是 Plan B 之上的可选升级 | `basjoo-dify-isolation-strategy.md` 2026-06-13 |
| **D7** | **Dify workflow toolkit 集成层走 HTTP API + DB 直连**,干掉 SSH / docker exec / paramiko | `services/dify_toolkit/` 5 个新模块;CLI 走 `--workspace-id` 而非 `--ssh-host` | P0-C PR 2 D8/C1/C2/C3 |
| **D8** | schema probe 守门:`probe_workflows_schema()` + `check_required_columns()` 缺列即 fail-fast | `services/dify_toolkit/db.py::_PROBE_SQL` + `constants.py::DIFY_WORKFLOWS_REQUIRED_COLUMNS` | P0-C PR 2 D10 |
| **D9** | DB 写 OK + Dify publish 5xx → raise `DifyPublishError` 而非静默 200(防御性 — admin 需重 deploy) | `deployer.py::_audit` 5xx 分支 + endpoint 502 mapping | P0-C PR 2 D9c |
| **D10** | **backfill 不回填凭据字段**(`dify_admin_email` / `dify_admin_password_ref`)— 这些只能来自真实 Dify 注册流 | `scripts/backfill_dify_enabled.py` 只翻 `dify_enabled=1` + COALESCE 填 `dify_api_base`;`audit_logs` 写 `actor_user_id=0`(system) | 本会话 P0-A PR 3 |

---

## 3. 各 Stream 实施细节

### 3.1 P0-A Plan A 切回

**代码路径**(`backend/services/tenant_service.py`):

```python
# 阶段 3: 写 Dify 成功结果回 basjoo DB
ws = await self.db.get(Workspace, workspace_id)
ws.dify_tenant_id = dify_result["workspace_id"]
ws.dify_account_id = dify_result["owner_account_id"]
ws.dify_provisioning_status = "ready"
ws.dify_provisioning_last_error = None
# M11+ P0-A (D5): persist Dify admin creds so create_agent can flip to Plan A.
ws.dify_api_base = settings.dify_api_base
ws.dify_admin_email = owner_email
ws.dify_admin_password_ref = encrypt_api_key(dify_result["initial_password"])
ws.dify_enabled = True  # ← 总开关,Plan A 4-step create_agent 路径的 gate
```

**历史 ws backfill**(`scripts/backfill_dify_enabled.py` + runbook):

- **目的**:M11 PR1 之前已注册成功的 ws,`dify_provisioning_status='ready'` 但 `dify_enabled=0` —— backfill 翻为 1
- **SQL**:单个 UPDATE 同时做 `dify_enabled=1` + `dify_api_base=COALESCE(dify_api_base, ?)`(只在 NULL 时回填,不覆盖)
- **不做的**:不回填 `dify_admin_email` / `dify_admin_password_ref`(无凭据不能伪造)
- **audit**:每 ws 写一条 `audit_logs` row,`actor_user_id=0`(system),`correlation_id` 由调用方传
- **dry-run + idempotent**:可重复执行,第二次 0 行匹配
- **DB backup**:执行前 `shutil.copy2` 一份 `*.before_backfill_dify_enabled`

**验收**:
- [x] 脚本在真实 pytest DB 上跑通(0 行场景 + 1 行场景)
- [ ] **真 basjoo chat_stream** E2E — 留本机 / CI(参见 P1-E)

### 3.2 P0-B Dify 1.15+ 升级 prep

**交付物**:`docs/handoffs/M11-DIFY-1.15-UPGRADE.md` —— 5+3=8 checklist 全部条目化 + `scripts/check_dify_1.15_breaking.sh` 升级日 grep 脚本

**5 条核心**:
1. `TenantService.create_tenant(name, is_setup=...)` 签名兼容
2. `TenantService.create_tenant_member(...)` 签名兼容
3. `AccountService.create_account(...)` 对外暴露
4. `@admin_required` 装饰器仍位于 `controllers/console/admin.py`
5. 无 `TenantPluginAutoUpgradeStrategy` 之外的强制初始化逻辑

**3 条增强**:(略,见 spec 文档)

**执行时刻**:Dify 升级日(冻结期不要求);必跑 + 失败即阻断升级

### 3.3 P0-C Dify workflow 工具包集成

**架构变化**:

```
BEFORE (SSH 直连, 1,757 LOC):
  tools/dify_workflow_toolkit/
    ├── builder.py
    ├── yml_validator.py
    ├── deployer.py    ← paramiko + docker exec
    ├── verifier.py    ← paramiko
    └── cli.py         ← --ssh-host --ssh-user --ssh-password

AFTER (HTTP API + DB 直连):
  backend/services/dify_toolkit/
    ├── __init__.py
    ├── builder.py          ← cp 自 tools/, 改包名
    ├── yml_validator.py    ← cp 自 tools/, 改包名
    ├── constants.py        ← 新增, DIFY_WORKFLOWS_REQUIRED_COLUMNS
    ├── exceptions.py       ← 新增, DifySchemaError / DifyPublishError
    ├── db.py               ← 新增, psycopg2 ThreadedConnectionPool + probe/check/update
    ├── deployer.py         ← 重写, Deployer.from_workspace(workspace)
    ├── verifier.py         ← 重写, Verifier.from_workspace(workspace, api_key=)
    └── cli.py              ← 重写, --workspace-id (非 --ssh-host)
```

**PR 1 范围**(cp toolkit + 改包名):
- `backend/services/dify_toolkit/builder.py` ← `tools/dify_workflow_toolkit/builder.py`
- `backend/services/dify_toolkit/yml_validator.py` ← `tools/dify_workflow_toolkit/yml_validator.py`
- `backend/services/dify_toolkit/__init__.py` 改 import 路径

**PR 2 范围**(重写 + 5 新模块):
- `constants.py` — DIFY_WORKFLOWS_REQUIRED_COLUMNS 字典(`id` / `app_id` / `version` / `graph` / `updated_at` / `tenant_id`)
- `exceptions.py` — `DifySchemaError(missing, actual)` / `DifyPublishError(message)`
- `db.py` — `get_conn()` ctx mgr / `probe_workflows_schema(conn)` / `check_required_columns(actual)` / `update_workflow_graph(conn, *, app_id, graph, tenant_id=None)`
- `deployer.py` — `Deployer.from_workspace(workspace)` 工厂 + `deploy()` 编排(probe → DB write → publish + audit at each step)
- `verifier.py` — `Verifier.from_workspace(workspace, api_key=...)` + `run(cases)` 跑 `/v1/chat-messages` 校验
- `cli.py` — Click group `validate / deploy / verify`,`deploy --workspace-id`(从 DB 拿凭据)

**PR 3 测试**(9 个,全部 PASSED):

`tests/test_dify_toolkit_p0c.py`(6 单元):
- `test_from_workspace_sets_all_4_fields` — DifyAdminClient 4 字段 wiring
- `test_from_workspace_without_tenant_id` — Plan A 早期 tenant_id=None 不报错
- `test_probe_schema_ok_runs_full_deploy` — schema OK 走 DB write + publish 全路径
- `test_probe_schema_missing_raises` — 缺列 raise DifySchemaError,DB write + publish 不调
- `test_db_fallback_on_5xx_raises` — publish 5xx raise DifyPublishError
- `test_publish_api_success_no_db_fallback` — 200 写 deploy_success audit,不写 deploy_publish_5xx

`tests/test_api_workflow_deploy.py`(3 端点集成):
- `test_200_deploy` — Plan A 完整路径 → 200,audit 写 deploy_success
- `test_502_schema_mismatch` — probe 缺列 → 502,错误信息含 missing
- `test_403_not_owner` — 非 workspace_owner → 403

**关键工程教训**(PR 2/3 调试记录,留底):
- **Test sessionmaker 陷阱**:`from database import AsyncSessionLocal` 在 module import 时绑定到 `settings.database_url`,后续 conftest `configure_database()` 重新指向测试 DB 也无效 → 必须用 `database.AsyncSessionLocal()` 直接访问属性
- **Deployer 测试隔离**:`DifyAdminClient.publish_workflow` 触发 login chain(`/console/api/login`),respx mock 不覆盖 → 直接 `deployer.dify_admin = MagicMock()` + `AsyncMock(side_effect=...)` 替换整个 admin client
- **Endpoint 测试用 `_stub_dify_admin(publish_ok=True)`**:patch `services.dify_toolkit.deployer.DifyAdminClient.from_workspace` 返回 MagicMock,绕过 login chain

---

## 4. 验收门状态(M11+ 盖棺时刻)

| Gate | 状态 | 证据 |
|------|------|------|
| P0-A 4 字段代码路径就绪 | ✅ PASS | `services/tenant_service.py` 阶段 3 |
| P0-A backfill 脚本 | ✅ PASS | `scripts/backfill_dify_enabled.py` 在 pytest DB 上跑通(0 行 / 1 行场景) |
| P0-A runbook | ✅ PASS | `docs/runbooks/m11plus-p0a-backfill-dify-enabled.md` |
| P0-B 5+3=8 checklist | ✅ PASS | `docs/handoffs/M11-DIFY-1.15-UPGRADE.md` + `scripts/check_dify_1.15_breaking.sh` |
| P0-C deployer / verifier / cli 重写 | ✅ PASS | `services/dify_toolkit/{deployer,verifier,cli}.py` |
| P0-C 5 新模块(constants / exceptions / db / deployer / verifier) | ✅ PASS | (同上) |
| P0-C 6 单元测试 PASSED | ✅ PASS | `tests/test_dify_toolkit_p0c.py` |
| P0-C 3 端点测试 PASSED | ✅ PASS | `tests/test_api_workflow_deploy.py` |
| **P0-A 真机 E2E** | ⚠️ **DEFERRED** | 留 P1-E / 本机 / CI |
| **P0-C CI 自动化测试** | ⚠️ **DEFERRED** | 沙箱内 pytest PASSED;CI 未跑(诚实标注) |
| **P0-B 升级时刻执行** | ⚠️ **DEFERRED** | Dify 升级日执行;冻结期不要求 |

---

## 5. 跨会话方法论(M11+ 复用)

### 5.1 三个新学到的工程教训

1. **Test sessionmaker 陷阱**:从 `database` 模块 import sessionmaker 会**冻结**该 sessionmaker 绑定的 DB URL 在 import 时刻;conftest 重指测试 DB 不生效。**修复模式**:用 `database.AsyncSessionLocal()` 函数式访问,每次调用读最新属性。

2. **第三方 HTTP client 测试隔离**:依赖第三方 HTTP API 的代码,`respx` mock 必须覆盖所有链路(包括 login);**简化模式**:在模块边界直接用 `MagicMock()` 替换整个 client 实例,只 mock 你关心的方法(`AsyncMock(return_value=..., side_effect=...)`),不 mock 不相关的认证流。

3. **backfill 脚本的"不做什么"清单**:比"做什么"更重要。P0-A backfill 显式列出**不回填凭据字段**(admin email/password)—— 这些只能来自真实注册流;backfill 的本分是"把已有状态修正成一致",不是"伪造数据"。这条原则要在 docstring / runbook / PR 描述里**重复三遍**才不会被运营误用。

### 5.2 M11+ 工作流节奏

```
M11 闭环 (2026-06-17, 24h 前)
   ↓
M11+ 启动 (2026-06-18 早) — M11-CLOSURE §4.1 列 P0
   ↓
决策日 (本会话前半) — D5-D10 LOCKED
   ↓
实施日 (本会话中) — 3 stream × 多 PR
   ↓
测试日 (本会话后) — 9 测试 PASSED + backfill dry-run PASSED
   ↓
收口日 (本会话末) — M11PLUS-CLOSURE.md + M11-CLOSURE v1.1
   ↓
git commit + push (下一步)
```

每个阶段 < 2 小时,跨决策/实施/测试/收口。

### 5.3 给 M12+ 接手者的指令

> **接手 M12+ backlog 时**:
> 1. 读 `M11-CLOSURE.md` v1.1 顶层收口 + 方法论
> 2. 读 `M11PLUS-CLOSURE.md`(本文件)看 M11+ 怎么从 P0 backlog 走到闭环的
> 3. 看 P1 backlog(M11-CLOSURE §4.2 + 本文件 §4)挑一个 PR 启动
> 4. **别从零开始** —— M11+ 的代码路径 / runbook / 决策日志都在 git history + docs 里

---

## 6. 相关链接

- 顶层收口: `docs/m11/M11-CLOSURE.md` (v1.1)
- P0-A runbook: `backend/docs/runbooks/m11plus-p0a-backfill-dify-enabled.md`
- P0-A 脚本: `backend/scripts/backfill_dify_enabled.py`
- P0-B 升级 spec: `docs/handoffs/M11-DIFY-1.15-UPGRADE.md` + `scripts/check_dify_1.15_breaking.sh`
- P0-C deployer: `backend/services/dify_toolkit/deployer.py`
- P0-C 测试 1: `backend/tests/test_dify_toolkit_p0c.py`
- P0-C 测试 2: `backend/tests/test_api_workflow_deploy.py`
- 决策记录:
  - `~/.claude/memory/m11-dify-1.15-upgrade-spec.md` — D5
  - `~/.claude/memory/basjoo-dify-isolation-strategy.md` — D6
  - `~/.claude/memory/m11plus-p2-strategy-and-debt-2026-06-16.md` — Plan A/B LOCKED
  - `~/.claude/memory/m11plus-chain-closure-2026-06-16.md` — M11+ 系列决策脉络

---

## 7. 修订记录

| 版本 | 日期 | 改动 | commit |
|------|------|------|--------|
| v0.1 | 2026-06-18 | 草稿,M11+ P0-A/B/C 闭环注记 + 3 stream 实施细节 + 5 验收门 + 跨会话方法论 | (本会话 commit) |