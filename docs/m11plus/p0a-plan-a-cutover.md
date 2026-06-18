# P0-A — Plan A 切回(basjoo 调 Dify create_app 拿 dify_app_id)

> **状态**: ⏸️ SPEC DRAFT (待 PR 实施)
> **基线**: M11 PR1-PR4 闭环 (`404f191`) + 5e00c2f
> **优先级**: P0(必做) — M11+ backlog 第 1 项
> **关联**: `M11-CLOSURE.md §4.1 P0-A`

---

## 0. 一句话总结

**M11+ P0-A = 解锁 basjoo `create_agent` 端点中的 Plan A 死代码**。改 1 个文件 + 1 个默认 = 30 行内,让 `workspace.dify_enabled` 真翻为 True + DifyAdminClient 拿得到 admin 凭据,新 agent 创建时**真的**调 Dify `create_app_and_workflow` → 拿 UUID → 存 `agent.dify_app_id`。旧 Plan B agent(`dify_app_id=NULL`)走 `POST /agents/{id}/activate-dify` 端点补一刀,新 agent 在 `create_agent` 自动激活。

---

## 1. 现状盘清楚(阶段 0)

### 1.1 Plan A 代码已就位,只是死代码

`backend/api/v1/endpoints.py:2067-2213` 的 `create_agent` 端点已经写好 Plan A 全流程:

```
flush agent 行 (不 commit) →
  if workspace.dify_enabled:
    DifyAdminClient.from_workspace(workspace) →
      create_app_and_workflow() →  agent.dify_app_id = app_id
                                  agent.dify_workflow_id = workflow_id
      enable_api_and_create_key() → agent.dify_api_key = Fernet(token)
      publish_workflow() → agent.dify_publish_status = "published" | "publish_failed"
  commit
  on Dify 5xx/4xx → rollback → 502
```

**问题**: `if workspace.dify_enabled:` 守卫 + `Workspace.dify_enabled = Column(Boolean, default=False)` + `tenant_service.register_tenant` 从未 set True → 整段是死代码。

### 1.2 M11 PR3 register 缺 4 个字段持久化

`backend/services/tenant_service.py:117-130` 阶段 3 只写 3 个字段:

```python
ws.dify_tenant_id = dify_result["workspace_id"]
ws.dify_account_id = dify_result["owner_account_id"]
ws.dify_provisioning_status = "ready"
```

**缺**:
- `ws.dify_api_base` (settings.dify_api_base) — DifyAdminClient 构造时需要
- `ws.dify_admin_email` (owner_email) — DifyAdminClient 登录用
- `ws.dify_admin_password_ref` (Fernet(initial_password)) — DifyAdminClient 登录用
- `ws.dify_enabled` (True) — 解锁 Plan A 守卫

**根因**: M11 PR3 设计 Dify tenant 注册时只考虑"Dify tenant 创建 + basjoo admin 凭据",没考虑"basjoo agent 后续调 Dify admin API 也要凭据"。M10+2 的 Plan A 设想里默认"凭据已经在那",但 register 路径根本没写。

### 1.3 旧 agent (`dify_app_id=NULL`)怎么办

M11 PR3 register 之后的新 workspace,Plan A 一开就 work。但 E2E 测试的 `agt_0115aa6588d7` + 历史 Plan B agent(`dify_app_id=NULL`)是历史包袱:

| 来源 | 数量级 | 处理方式 |
|------|-------|---------|
| M11 PR3 register 后创建的新 agent | 0 (E2E 阶段 0 业务) | P0-A 一开就 Plan A 自动激活 ✅ |
| M11 之前 Plan B bootstrap workspace 的 agent | N (几百?) | `POST /agents/{id}/activate-dify` 端点,owner 手动触发 |
| 老的 dify_app_id=NULL 但 workspace dify_enabled=False | 同上 | 同上 |
| workspace 没 dify_admin_password_ref (M11 PR3 之前注册的) | 全部 | **Dify 密码已丢**,需 owner 走 Dify reset-password → 重新注册 → 走 Plan A |

---

## 2. 问题清单 + 严重度(阶段 1)

### 🔴 P0-1 — Plan A 死代码

- **现象**: `if workspace.dify_enabled:` 守卫 `default=False`,新 workspace 一律 Plan B
- **影响**: Dify 后台一片空白(本次 E2E 复现,见 M11 PR4 REPORT),widget 不可用
- **决策选项**:
  - A. 在 `register_tenant` 阶段 3 一并 flip dify_enabled=True + 持久化 admin 凭据 (**选,本 spec**)
  - B. 单独写一个 "enable dify" 后台按钮让用户手动开
  - C. 等 P0-C (toolkit) 落地后再开

### 🟠 P1-1 — 旧 NULL dify_app_id agent 历史包袱

- **现象**: M11 之前创建的 agent `dify_app_id=NULL`,P0-A 落地后仍 NULL
- **影响**: 这些 agent 调 Dify 仍会失败
- **决策选项**:
  - A. 加 `POST /agents/{id}/activate-dify` 端点,owner 触发按需补 (**选**)
  - B. bulk migration script 全量补 (但老 workspace 缺 Dify 密码,无法补)
  - C. 标 `dify_publish_status='legacy_no_app'`,UI 标灰,提示用户重新创建

### 🟡 P2-1 — D9c 容错的 UX

- **现象**: 旧 Plan B agent 走 `activate-dify` 时,`create_app_and_workflow` 会创建空 graph,D9c 触发 → `dify_publish_status='publish_failed'`(不抛)
- **影响**: 用户看到一个 "publish failed" 状态的 agent,实际是预期行为(等 P0-C 给它 workflow yml)
- **决策选项**:
  - A. UI 明确显示 "未配置 workflow,需 Dify Studio 或 P0-C 工具包补充" (**选**)
  - B. 自动 mark 'pending_workflow' 状态(新增 enum 值)

---

## 3. 决策日志(阶段 2)

### D5 ✅ — Plan A 切回 = 修 1 个文件 + flip 1 个开关

**决策**: 在 `tenant_service.register_tenant` 阶段 3 一次性持久化 4 个字段 (`dify_api_base` / `dify_admin_email` / `dify_admin_password_ref` / `dify_enabled=True`),`create_agent` 端点的 Plan A 路径无需改 1 行代码就自动激活。

**对架构的约束**:
- 新 tenant register → workspace 自带 Plan A 凭据 → `create_agent` 调 Dify 真创建 App
- 旧 workspace 没凭据 → `create_agent` 走原 `if workspace.dify_enabled:` 守卫 → 仍是 Plan B
- 旧 agent (`dify_app_id=NULL`) → 走 `POST /agents/{id}/activate-dify` 按需补,新端点复用 Plan A 路径
- 1.15+ 升级时只需验证 `DifyAdminClient.from_workspace(workspace)` 拿到的 3 字段仍可用
- Dify 密码 Fernet 加密存 DB,跟 `agent.dify_api_key` 一致机制

**部署上下文**:
- 自部署 Dify:workspace 拿的 `dify_api_base` = system settings (`DIFY_API_BASE`),所有 workspace 共享同一 Dify 实例
- Dify Cloud 模式(未来):`dify_api_base` 改为 per-workspace,需 D6 决策跟进
- 不影响 Plan B bootstrap workspace (dify_enabled=False → 走 Plan B 兜底)

**升级时刻的硬性约束**:
- 1.15+ 升级时,DifyAdminClient 的 login URL / password encoding 任何改动都要回归 (P0-B 5+3=8 checklist 覆盖)
- 升级前先在 staging 跑 `docs/handoffs/M11-DIFY-1.15-UPGRADE.md §2 5+3=8 步`

### D6 ✅ — 旧 Plan B agent 用 activate-dify 端点按需补

**决策**: 加 `POST /api/v1/agents/{id}/activate-dify` 端点 (in `endpoints.py`),复用 `create_agent` 的 Plan A 路径 (提取为 helper `_provision_dify_app(agent, workspace)`),仅给 workspace owner + super_admin 调。

**对架构的约束**:
- 端点权限: `require_workspace_owner(current_user)` (super_admin ∪ tenant_owner),M11 D3 已定
- 旧 agent `dify_app_id` 仍 NULL → 走 Plan A 4 步 → 写回 `dify_app_id` / `dify_workflow_id` / `dify_api_key` / `dify_publish_status`
- workspace 没 admin 凭据 → 端点 400 提示 "workspace 缺 Dify 凭据,需联系 super_admin 重新签约 Dify tenant"
- Dify 5xx → 端点 502,前端按钮可重试
- UI: 旧 agent 列表加 "Activate in Dify" 按钮 (前端 PR,本 spec 不涵盖)

### D7 ✅ — 老 workspace (M11 PR3 前注册) 密码已丢,需手动 reset

**决策**: 不尝试自动找回老 workspace 的 Dify 密码 (技术不可行,Dify 端 bcrypt 单向)。由 owner 走 Dify 端 reset-password 流程 (Dify Web UI / 或调 M11 PR1 fork 砍掉的 reset-password endpoint,本 spec 不恢复)。

**对架构的约束**:
- 老 workspace 必须 super_admin 协助: 调 Dify admin API 重置 owner 密码 → 让 owner 重新登录 Dify → 在 basjoo 后台走 activate-dify
- 文档化: M11-CLOSURE §4 P1-A 补 "Dify password reset" 文档 (1 PR,1 文件)
- 不在本 spec 范围,但留 P1-D backfill 任务

---

## 4. spec 详细(阶段 3)

### 4.1 改动文件清单 (本 spec PR)

| 文件 | 改动 | 行数估计 |
|------|------|----------|
| `backend/services/tenant_service.py` | 阶段 3 加 4 行 set + 引入 import | +12 / -2 |
| `backend/api/v1/endpoints.py` | 提取 `_provision_dify_app(agent, workspace)` helper + 新端点 `activate_dify` | +60 / -30 |
| `backend/api/v1/schemas.py` (如有) | `AgentConfig` 已存在,无需新 schema | 0 |
| `backend/tests/test_tenant_service_p0a.py` | 4 单元测试 (register 持久化 / retry 持久化 / 没初始密码失败 / 已 set 不覆盖) | +120 (新文件) |
| `backend/tests/test_agents_activate_dify.py` | 3 端点测试 (200 / 400 没凭据 / 502 Dify 5xx) | +90 (新文件) |
| `scripts/backfill_dify_enabled.py` | 一次性 CLI: 扫所有 `dify_provisioning_status='ready'` 但 `dify_enabled=False` 的 workspace,补 3 字段 (用 ops 手动 reset 后的 Dify 密码) | +80 (新文件) |
| `docs/m11plus/p0a-plan-a-cutover.md` | 本文件 | +250 (本文件) |
| **总** | | **+612 / -32** |

### 4.2 关键代码 diff

**`tenant_service.py` 阶段 3** (line 117-130):

```diff
 ws = await self.db.get(Workspace, workspace_id)
 ws.dify_tenant_id = dify_result["workspace_id"]
 ws.dify_account_id = dify_result["owner_account_id"]
 ws.dify_provisioning_status = "ready"
 ws.dify_provisioning_last_error = None
+# M11+ P0-A: persist Dify admin creds so create_agent can flip to Plan A
+# (D5 决策: 一并 flip dify_enabled=True + 持久化 admin 凭据)
+from config import settings
+from core.encryption import encrypt_api_key
+ws.dify_api_base = settings.dify_api_base
+ws.dify_admin_email = owner_email
+ws.dify_admin_password_ref = encrypt_api_key(dify_result["initial_password"])
+ws.dify_enabled = True
 self.db.add(AuditLog(...))
```

**`retry_provisioning` 成功路径** (line 174-178) 同样改。

**`endpoints.py` Plan A helper 提取** (line 2159-2213):

```python
async def _provision_dify_app(agent: Agent, workspace: Workspace) -> None:
    """Plan A 4 步: create_app + enable_api + create_key + publish。
    失败抛 HTTPException(502),调用方决定 rollback / 上抛。
    不 commit — 由调用方统一 commit。
    """
    if not workspace.dify_enabled:
        return  # Plan B 模式,保持 dify_app_id=NULL
    if not workspace.dify_admin_email or not workspace.dify_admin_password_ref:
        raise HTTPException(400, "workspace 缺 Dify 凭据,需先签约 Dify tenant")
    try:
        dify = DifyAdminClient.from_workspace(workspace)
        create_result = await dify.create_app_and_workflow(
            name=agent.name, description=agent.description or "", mode="workflow"
        )
        agent.dify_app_id = create_result["app_id"]
        agent.dify_workflow_id = create_result["workflow_id"]
        api_key = await dify.enable_api_and_create_key(create_result["app_id"])
        agent.dify_api_key = encrypt_api_key(api_key)
        publish_ok = await dify.publish_workflow(create_result["app_id"])
        agent.dify_publish_status = "published" if publish_ok else "publish_failed"
    except (DifyConfigError, DifyAuthError, DifyUpstreamError, httpx.HTTPError) as e:
        raise HTTPException(502, f"Dify workflow creation failed: {e}")
```

`create_agent` 端点 (line 2159-2213) 改 1 行调 helper,新端点 `activate_dify` 同样调 helper。

### 4.3 数据库迁移

无需 Alembic 迁移:
- `dify_api_base` / `dify_admin_email` / `dify_admin_password_ref` / `dify_enabled` 字段已在 M10 G3 + M10+2 D4.1 落地 (`backend/models.py:61-72`)
- `dify_enabled` 字段 default=False 不变 (避免对已存 workspace 惊扰);register 流程显式 flip True

### 4.4 测试矩阵

| 测试 | 入口 | 期望 |
|------|------|------|
| `test_register_persists_dify_admin_creds` | `TenantService.register_tenant` mock Dify success | workspace row 4 字段全 set,Fernet 加密可解密回原密码 |
| `test_register_dify_failure_does_not_persist_creds` | mock Dify 5xx | 4 字段全 None (原子性) |
| `test_retry_provisioning_success_persists_creds` | `retry_provisioning` mock success | 同 #1 |
| `test_activate_dify_200` | `POST /agents/{id}/activate-dify` | 200, agent.dify_app_id 写 UUID |
| `test_activate_dify_400_no_creds` | mock workspace 无 dify_admin_* | 400, agent 字段不变 |
| `test_activate_dify_502_dify_5xx` | mock Dify 5xx | 502, agent 字段不变 (rollback) |
| `test_create_agent_picks_up_dify_creds` | `POST /agents` with dify_enabled=True workspace | 走 Plan A 路径,新 agent dify_app_id 写 UUID |
| `test_create_agent_plan_b_unchanged` | `POST /agents` with dify_enabled=False workspace | 仍 Plan B, dify_app_id=NULL |

---

## 5. PR 实施计划(阶段 4)

1. **PR 1**: `fix(m11plus): P0-A Plan A 切回 — tenant_service 持久化 Dify 凭据`
   - 改 `tenant_service.py` (阶段 3 + retry 成功路径)
   - 加 4 单元测试
   - 跑 `pytest tests/test_tenant_service_p0a.py -v` 期望 4/4 pass
   - 不动前端

2. **PR 2**: `feat(m11plus): P0-A activate-dify 端点 + Plan A helper 提取`
   - 改 `endpoints.py` 提取 `_provision_dify_app` helper
   - 加 `POST /agents/{id}/activate-dify` 端点
   - 改 `create_agent` 端点用 helper (diff -30 行)
   - 加 3 端点测试
   - 跑 `pytest tests/test_agents_activate_dify.py -v` 期望 3/3 pass
   - 跑 `pytest tests/test_api.py` 期望 0 回归
   - 不动前端 (前端 PR 单独)

3. **PR 3**: `ops(m11plus): P0-A backfill CLI + Dify password reset runbook`
   - 加 `scripts/backfill_dify_enabled.py` (80 行)
   - 加 `docs/runbooks/m11plus-p0a-dify-password-reset.md` (60 行,runbook 模板)
   - 不需要单元测试 (脚本级别,人工跑)

4. **PR 4**: `docs(m11plus): P0-A 收口 — M11-CLOSURE backlog 更新`
   - `docs/m11/M11-CLOSURE.md §4.1` 移除 P0-A (标 ✅)
   - `docs/m11plus/M11PLUS-CLOSURE.md` 草稿 (P0-A + P0-B + P0-C 收口用)

### 5.6 不做 / 留 P1+

- 不做前端 "Activate in Dify" 按钮 → P1-A (前端 PR,1-2 个组件)
- 不做 D9c UX 优化 (publish_failed 状态显示) → P1-B (前端 PR)
- 不做老 workspace Dify 密码自动重置 → P1-D (ops runbook,见 PR 3 runbook)
- 不动 `dify_enabled` default (保持 False, register 时显式 flip,避免惊扰) → 已决策
- 不动 Plan B bootstrap workspace (单租户视角) → 不动

---

## 6. 验收门(阶段 5)

| Gate | 状态 | 证据 |
|------|------|------|
| `pytest tests/test_tenant_service_p0a.py` 4/4 pass | ⏳ | PR 1 跑 |
| `pytest tests/test_agents_activate_dify.py` 3/3 pass | ⏳ | PR 2 跑 |
| `pytest tests/test_api.py` 0 回归 | ⏳ | PR 2 跑 |
| E2E: 新 register → 自动 Plan A → `agent.dify_app_id` UUID 写入 | ⏳ | 沙箱 E2E (Playwright MCP + 162.211.183.169) |
| E2E: 旧 Plan B agent → activate-dify → `dify_app_id` 写入 | ⏳ | 沙箱 E2E |
| E2E: Dify 端能看见新 App | ⏳ | SSH 162.211.183.169 / SELECT * FROM apps |
| Dify 1.15+ 兼容性 (P0-B) | ⏳ | PR 完后跑 P0-B 5+3=8 checklist |

---

## 7. 风险 + 缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Fernet 加密失败 (key rotation) | 低 | agent 创建 500 | 复用 M10 G3 的 encrypt_api_key,有现成测试 |
| Dify 端 `initial_password` 包含特殊字符被 Dify login 拒 | 低 | register 5xx | Dify 接受任意 base64 字符,M11 PR1 已验证 |
| 老 workspace 没 Dify 密码无法 backfill | 高 | 老 agent 永远 Plan B | 文档化 + runbook (PR 3) |
| `if workspace.dify_enabled:` 旧 Plan B workspace 误触发 Plan A | 低 | 老 workspace 出 Dify 错误 | register 时显式 flip,老 workspace dify_enabled=False → 仍 Plan B |
| 并发 register 同一 email | 中 | 重复 Dify tenant | M11 PR2 `signup_idempotency_key` UNIQUE 约束 + 409 i18n 已 cover |

---

## 8. 修订记录

| 版本 | 日期 | 改动 |
|------|------|------|
| v1.0 | 2026-06-18 | 初稿,D5/D6/D7 决策 + 4 PR 实施计划 |
