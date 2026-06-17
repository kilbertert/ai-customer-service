# 前端相关问题 - 第二块:B 端租户隔离(Plan A 切换) 详细问题梳理

> **作者**:基于 2026-06-17 与 Claude Code 沟通整理
> **范围**:`前端相关问题.md` 已记录的第一块问题(单租户视角)之外,**第二块**:面向 B 端多租户的注册 → workplace 创建 → 智能体创建全链路
> **决策前提**(2026-06-17 用户拍板):
> 1. 现在就要切 Plan A(每个 B 端独立 Dify workspace)
> 2. 因为看到 B 端租户隔离的**硬需求**(非提前布局)
> 3. basjoo 用 **Dify service account(admin)** 调 Dify console API

---

## 1. 业务远景(用户的设想)

B 端用户在 basjoo 前端打开注册页面 → 填账号密码 → basjoo 后端做两件事:

1. 在 basjoo DB 建 `Workspace + AdminUser`,owner_email = 该 B 端用户邮箱
2. **同步**调用 Dify console API,以 Dify admin(service account)身份,在 Dify 侧为该 B 端用户:
   - 建一个 `Tenant`(Dify 的 workspace)
   - 建一个 `Account`(邮箱同名)
   - 建 `TenantAccountJoin(role="owner")`,让该用户成为这个 Dify workspace 的 owner

注册成功后,B 端用户登录 basjoo 前端 → 进 dashboard → 创建智能体 → 此时:
- basjoo 的 `Workspace.id` 已经存在,`Agent` 创建时归属到该 workspace
- Dify 的 `Tenant.id` 已经存在,`DifyProvider` 调 Dify 时携带该 tenant 的 API key
- **两边的 workspace 概念一一对应,数据天然隔离**

---

## 2. 当前代码实际能力(基于源码实证)

### 2.1 basjoo 前端注册入口(`frontend-nextjs/src/views/Register.tsx` + `frontend-nextjs/app/(auth)/register/page.tsx`)

| 现状 | 问题 |
|------|------|
| 路由 `/register` **存在** | ✅ 不是缺失路由 |
| `Login.tsx:23-34` 启动时 `fetch("/api/admin/registration-settings")` | 仅在 `bootstrap_required=true` 时 `navigate("/register")` |
| `bootstrap_required` = `AdminUser.id == 0` | **系统一旦有任意 admin,永远跳不出 `/register`** |
| `Register.tsx:23-37` 同样检查 `bootstrap_required` | 如果被直接访问但 admin 已存在,`navigate("/login", { replace: true })` 弹回 |

**结论**:注册入口**是只给系统首次启动用的一次性 bootstrap**,不是给 B 端租户用的注册。用户在登录页看到的"只有登录没有注册"是**设计如此**,但这个设计**与多租户 SaaS 远景根本不兼容**。

### 2.2 basjoo 后端注册端点(`backend/api/endpoints/auth.py:228-293`)

```python
@router.post("/register", response_model=LoginResponse)
async def register(request, req: RegisterRequest, db):
    async with _bootstrap_lock:
        admin_count = (select(func.count(AdminUser.id))).scalar() or 0
        if admin_count > 0:
            raise HTTPException(403, "System already has an administrator")  # ← 硬阻断
        # 建 Workspace("Default Workspace")
        # 建 WorkspaceQuota
        # 建 AdminUser(role="super_admin", workspace_id=workspace.id)
        # 返回 access_token
```

**问题清单**:
- ❌ **一次性 bootstrap**,注册一次后 `/register` 永久 403
- ❌ **不调任何 Dify API**,Dify 侧完全没有 workplace 创建
- ❌ Workspace 写死 `name="Default Workspace"`,无租户命名
- ❌ 无 `dify_tenant_id` / `dify_account_id` 关联字段(`Workspace` 表当前不含)
- ❌ AdminUser 创建后**直接 super_admin**,没有 `tenant_owner` 角色区分
- ❌ 无邀请/审批流(自助注册 = 直接激活)

### 2.3 basjoo Workspace 模型(`backend/models.py` + `database.py:140-177`)

| 字段/能力 | 现状 | 多租户 Plan A 需求 |
|----------|------|------|
| `Workspace` 表 | 存在 | ✅ 但缺 `dify_tenant_id` 列 |
| `Workspace.owner_email` | 存在 | ✅ |
| `WorkspaceQuota` | 存在 | ✅ |
| 启动时自动建默认 workspace | `database.py:140-177` 在 `init_db` 时创建 | ⚠️ 单租户 bootstrap 行为要降级为"无 workspace 才建" |
| `Agent.workspace_id` 外键 | 存在 | ✅ basjoo core 已经 workspace-level 隔离 |
| 知识源/会话/文件按 workspace_id 隔离 | 存在 | ✅ |

**结论**:basjoo core 数据模型**已经支持多 workspace**,Plan A 切换不需要改 schema 主体,只需**新增 `dify_tenant_id` 列 + 启动逻辑降级**。

### 2.4 basjoo ↔ Dify 集成现状(`backend/services/dify/admin_client.py`)

| 现状 | 问题 |
|------|------|
| `DifyAdminClient` 已有,用 Dify admin email/password 登录拿 Flask session cookie,LRU 缓存 512 sessions | ✅ **基础设施已就绪** |
| 已实现 `POST /console/api/apps` + 5 步 workflow 创建流程 | ✅ Plan A 路由层可以**复用这套会话** |
| Dify admin 凭证在 `.env`(`DIFY_ADMIN_EMAIL` / `DIFY_ADMIN_PASSWORD`) | ✅ |
| **无 workspace 创建方法** | ❌ Dify 侧无 `POST /console/api/workspaces` 端点 |
| **无 Dify account 创建方法** | ❌ Dify 侧 email 注册需走 `email_register` 流(需要 SMTP + 验证码) |
| **无 TenantAccountJoin 创建方法** | ❌ 即使有 tenant 和 account,绑定关系也必须走 Dify 内部 service |

### 2.5 Dify 侧 workspace 创建能力(基于 `dify/` 源码实证)

| Dify 端点 | 用途 | 适用吗? |
|----------|------|--------|
| `POST /console/api/setup` | 系统首次 bootstrap,**只允许一次**(`dify_setup` 表标志) | ❌ 不能复用 |
| `POST /console/api/email-register/send-email` + `/validity` + `/email-register` | Dify 自带邮箱注册,**依赖 SMTP 验证码** | ⚠️ 可以借用,但 basjoo 后端要等邮件验证码中转,UX 差 |
| `POST /console/api/workspaces` | **不存在这个端点**(`dify/api/controllers/console/workspace/workspace.py:228-275` 只有 GET `/workspaces` 列举当前用户加入的 workspace) | ❌ |
| `POST /console/api/workspaces/switch` | 切换当前 workspace,不能创建 | ❌ |
| `RegisterService.setup(...)` / `TenantService.create_tenant(...)` | **Dify 内部 Python 方法,无 HTTP 暴露**(`dify/api/services/account_service.py:1153-1236`) | ⚠️ 只能在 Dify 进程内调用 |
| `TenantService.create_tenant_member(...)` | 同上 | ⚠️ 同上 |

**P0 风险(必须在立项前与用户对齐)**:
**Dify self-host 默认不开 HTTP 创建 workspace 的口子**。要在 basjoo 里通过 HTTP 触发 workspace 创建,**只有三条路**:
1. **路由 A**:**在 Dify 源码里新加一个 `POST /console/api/workspaces` endpoint**(fork Dify,改 3-5 个文件,可控但要维护 fork)
2. **路由 B**:**basjoo 跟 Dify 共用 Postgres**,basjoo 后端直接 ORM 写 Dify `tenants / accounts / tenant_account_join` 表(零 Dify 改动,但绕过 Dify 业务校验,迁移/升级 Dify 时有耦合风险)
3. **路由 C**:**走 Dify email_register 流**,basjoo 在 `/register` 时同步给 B 端用户邮箱发 Dify 注册邮件,B 端点链接完成 Dify 侧验证(无需改 Dify,但 UX 割裂,basjoo 不能保证 Dify 账号先于 basjoo 账号就绪)

> 用户说的"Dify API 能力去查 dify 源码"——已查,**Dify 公开 console API 覆盖的是 app/工作流/api-key 维度,不覆盖 workspace 创建**。这是事实,不是疏漏。

### 2.6 Dify Admin session 复用性

`DifyAdminClient` 已经能:
- 用 admin 邮箱密码登录 Dify 拿 Flask session
- 自动加 `X-CSRF-Token`
- 401 自动重登 1 次

**新场景下能否复用**:
- ✅ 复用 `DifyAdminClient._request()` 调 Dify 公开端点
- ❌ 但调 `POST /console/api/workspaces`(如果走路由 A fork 出新端点),需要在 Dify 侧加 `@login_required` + `@setup_required`,并加上"admin 可代任意账号建 workspace"的授权
- ⚠️ 走路由 A 时,admin 创建的 workspace 的 owner 是谁?需要 Dify 侧授权模型确认(`TenantService.create_tenant` 不带 owner,owner 是后续 `create_tenant_member` 决定的)

---

## 3. 当前实际面临的问题清单(按严重度排序)

### 🔴 P0 - 必须立项时拍板

#### P0-1 Dify workspace 创建走 A 路径(fork 新 endpoint)— ✅ 决策已拍板

- **决策**:Fork Dify 源码,新加 `POST /console/api/admin/workspaces` endpoint(basjoo admin service account 调)
- **部署上下文**(2026-06-17 用户确认):**Dify 是自部署**(非 Dify Cloud),当前冻结一段时间,未来某时点升级——这是大多数自部署的现实
  - **A 路径长期含义**:basjoo ↔ Dify 版本强绑定,升级时刻需要 rebase Dify fork + 跑 §6 升级 playbook
  - **不要求**立项前预检 Dify 1.15+ 兼容性,但**必须**把升级预案写进 ops 文档(详见 §6 升级策略专章)
- **新增能力**(详见 §5 决策 1 改动清单):
  - Dify 侧:`POST /console/api/admin/workspaces` body `{workspace_name, owner_email, owner_name, owner_password}` → `{workspace_id, owner_account_id, status}`
  - Dify 侧:`GET /console/api/admin/workspaces/{workspace_id}/owner-credentials` → `{email, initial_password}`(仅 provision 阶段可用一次)
- **影响**:
  - 必须维护 Dify fork 分支(详见 §5 决策 1 安全约束)
  - 升级时刻(fork rebase)的兼容性测试**必须**作为升级验收门(checklist 见 §6)
  - basjoo `.env` 必须新增 `DIFY_TENANT_PROVISION_ENABLED=true` 开关,未就绪时 `503`
- **实施细节**:见 §5 决策 1 的 Dify fork 改动清单 5 项(D1=否 后),约 +205 行 Python

#### P0-2 basjoo `/register` 是一次性 bootstrap,不是租户注册

- **现象**:`auth.py:228-293` 的 `register` 在 `admin_count > 0` 时硬阻断
- **影响**:即使 Dify 侧有 workspace 创建 API,basjoo 这层也根本不允许"非首次注册"
- **必须**:
  - 拆 `/register`(bootstrap)和 `/api/v1/tenants/register`(租户注册)为两条独立路由
  - `AdminUser.role` 区分 `super_admin`(平台方) / `tenant_owner`(B 端 owner) / `tenant_admin`(B 端管理员) / `tenant_member`(B 端成员)
  - 前端路由 `/register` 仅在 `bootstrap_required` 时显示,新增 `/signup` 给 B 端用
  - AuthContext 改造:`register()` 保留给 bootstrap,新增 `signupAsTenant()` 走新路由
- **RBAC 矩阵**:

| 角色 | workspace_id 取值 | 可创建 workspace? | 可邀请成员? | 可创建 Agent? |
|------|------|------|------|------|
| `super_admin` | NULL(平台方) | ✅ | 跨 workspace | ✅ |
| `tenant_owner` | 自家 workspace | ❌ | ✅ | ✅ |
| `tenant_admin` | 自家 workspace | ❌ | ✅(非 owner) | ✅ |
| `tenant_member` | 自家 workspace | ❌ | ❌ | ✅ |

#### P0-3 事务边界与回滚(基于 A 路径推演)

- **现象**:当前 basjoo `/register` 整个在 `_bootstrap_lock` 里串行,DB 原子
- **A 路径下的事务拓扑**:
  - basjoo DB 事务:Workspace + WorkspaceQuota + AdminUser + TenantSignup 记录
  - Dify HTTP 调用:`POST /admin/workspaces`(创建 tenant + account + 绑定,**Dify 侧单次 commit**)
- **执行顺序**(已确定):**先 basjoo DB 写 → 再 Dify HTTP → 标记 ready**,理由:
  1. basjoo 写失败 → 直接 500 返回,B 端无副作用
  2. basjoo 写成功 + Dify 调用失败 → `Workspace.dify_provisioning_status="failed"`,前端展示"准备中,请稍后",后台定时重试
  3. basjoo 写成功 + Dify 调用成功 → `status="ready"`,`dify_tenant_id` / `dify_account_id` 写入 Workspace
- **回滚策略**:
  - **Step A→B 失败**:basjoo DB 已写但 Dify 没建 → **不回滚 basjoo**,保留 `failed` 状态,后台 cron 每 5 min 重试,最多 3 次后标 `failed_permanent` 通知 admin
  - **Step B 失败但 Dify 部分写入**(Dify tenant 已建但 owner account 失败):basjoo 调 `DELETE /console/api/admin/workspaces/{tenant_id}`(Dify fork 也要新增这个 endpoint)清理
  - **Step B 超时**:basjoo 用 idempotency key(`basjoo_signup_id` UUIDv7)调 Dify,Dify fork 必须支持同一 key 24h 内幂等(否则重试会建出 2 个 workspace)
- **关键字段**(新增到 basjoo Workspace 表):
  - `signup_idempotency_key VARCHAR(36) UNIQUE` — 每次 `/tenants/register` 调用生成一次,贯穿 basjoo + Dify
  - `dify_provisioning_status VARCHAR(20)` — enum: `pending` / `provisioning` / `ready` / `failed` / `failed_permanent`
  - `dify_provisioning_attempts INT DEFAULT 0` — 后台重试计数
  - `dify_provisioning_last_error TEXT` — 最后一次失败的 Dify 错误信息,排障用

### 🟠 P1 - 设计阶段必须决策

#### P1-1 basjoo Workspace ↔ Dify Tenant 关联字段(A 路径精确清单)

- **现象**:`Workspace` 表当前无 `dify_tenant_id` / `dify_account_id` / `dify_provisioning_status` 列
- **Alembic 迁移脚本**(完整 DDL,基于 SQLite 开发库 + Postgres 生产库双兼容):

```sql
-- alembic/versions/xxxx_add_dify_provisioning_fields.py
ALTER TABLE workspaces ADD COLUMN dify_tenant_id VARCHAR(36);          -- Dify Tenant UUID
ALTER TABLE workspaces ADD COLUMN dify_account_id VARCHAR(36);         -- Dify Account UUID
ALTER TABLE workspaces ADD COLUMN dify_provisioning_status VARCHAR(20) NOT NULL DEFAULT 'pending';
ALTER TABLE workspaces ADD COLUMN dify_provisioning_attempts INT NOT NULL DEFAULT 0;
ALTER TABLE workspaces ADD COLUMN dify_provisioning_last_error TEXT;
ALTER TABLE workspaces ADD COLUMN signup_idempotency_key VARCHAR(36) UNIQUE;

-- 反向索引:方便后台 cron 拉 failed 重试
CREATE INDEX idx_workspaces_dify_provisioning_status ON workspaces(dify_provisioning_status)
    WHERE dify_provisioning_status IN ('failed', 'provisioning');
CREATE INDEX idx_workspaces_dify_tenant_id ON workspaces(dify_tenant_id);
```

- **状态机**(`dify_provisioning_status`):

```
pending ──register 触发──> provisioning ──Dify 成功──> ready
                              │
                              └──Dify 失败──> failed ──cron 重试──> provisioning
                                              │
                                              └──重试 3 次仍失败──> failed_permanent
                                                                          │
                                                                          └──admin 手工处理
```

- **basjoo 登录逻辑**:workspace `status != ready` 时:
  - 允许登录(`super_admin` / `tenant_owner` / `tenant_admin`)
  - dashboard 顶部红色 banner:"Dify workspace 准备中,请稍候..."
  - **禁止**创建 Agent / 上传 KB / 创建 Widget
  - `tenant_member` 角色直接 403(等待期不让用,降低 UX 复杂度)

#### P1-2 B 端 owner 的 Dify 账号密码(A1 方案) — ✅ D1=否 已拍板

- **决策**:**A1**(basjoo 代建 + 随机密码,basjoo 不持久化 Dify 密码,B 端 owner 不登 Dify Console)
- **实施细节**:
  - basjoo 调 Dify `POST /console/api/admin/workspaces`(同 P0-1 endpoint),Dify fork 在创建 Dify Account 时**生成 32 字节随机密码**(Dify 内部存 bcrypt hash + salt)
  - Dify fork endpoint 响应**返回明文密码一次性**(basjoo 调用方在 `POST /workspaces` 时传 `return_initial_password=true`)
  - basjoo 在 `/tenants/register` 响应中**一次性回传密码给前端**,注册成功页用大字号 modal 提示"这是您的 Dify workspace 初始密码,**仅展示一次**,请妥善保存",30 秒后必须 mask 掉(防止肩窥)
  - basjoo DB **不持久化**明文密码,只存 `signup_idempotency_key` 追溯
  - B 端后续所有 basjoo→Dify 调用都走 basjoo service account + `dify_account_id`,**B 端不需要 Dify 密码**
- **Dify fork 改动收敛**:原计划 §5 决策 1 改动 5 中的 `POST /admin/accounts/{id}/reset-password` endpoint **不再需要**,Dify 侧 fork 改动减为 5 项(endpoint 4 + service 1 + error 1 + model 1),约 +205 行(原 +245 行)
- **B 端想看 Dify Console 的应对**:v1 不提供。如未来要支持,走 Dify 原生 `forgot_password` 流,basjoo 仅做引导链接,不存任何 Dify 凭据
- **审计含义**:Dify Account 创建是 admin 操作,Dify 侧审计日志会记 "admin basjoo@... 在 2026-06-17 创建 account foo@bar.com",可追溯

#### P1-3 服务账号权限粒度(A 路径方案)

- **现象**:`DIFY_ADMIN_EMAIL` 是 Dify super admin,权限等同 Dify 平台 owner
- **A 路径审计方案**(基于 Dify 现有日志 + basjoo 审计流水表双轨):
  - Dify 侧:所有经由 `POST /console/api/admin/*` 的请求,Dify 默认记录 admin 操作人,**审计能区分"是 admin 调的还是普通用户调的"**
  - basjoo 侧:新增 `audit_log` 表,记录 `{tenant_id, actor_user_id, action, dify_request_id, timestamp, status}`
  - 关联方式:basjoo 每次调 Dify admin endpoint 时,生成 `x-basjoo-correlation-id` header 透传,Dify fork 在 audit log 写入 correlation_id
  - 这样 Dify 审计能定位"admin 调了啥",basjoo 审计能定位"B 端 X 发起了啥",关联 correlation_id 还原全链路
- **必须 fork 改动**:Dify 侧 `services/feature_service.py` 的 audit log 写入处加 `correlation_id` 透传(1 处,约 +10 行)
- **可选**:如果 Dify audit log 不够详细,baskjoo 自己做一份 Dify action mirror table,通过 Dify `/admin/workspaces/{id}/audit-log` 拉(此 endpoint 也要 fork 新增,约 +50 行)

#### P1-4 basjoo service 路由层 Plan A 重写(M3/M6/M7)

- **现象**:M9.5 spec §1.2.1 已明确:切 Plan A 必重写 M3(LLMProvider)/M6(KB)/M7(Widget streaming)三处的"basjoo→Dify 路由"
- **影响**:
  - M3:`LLMProvider` 当前是全局,需要按 `workspace_id` 路由到该 B 端的 Dify API key
  - M6:`kb_document_endpoints` 当前默认走默认 workspace,需要 tenant scoping
  - M7:Widget chat_stream 当前调全局 Dify endpoint,需要按 widget 所属 agent → workspace → Dify tenant 路由
- **必须**:
  - 改前先 freeze M10+5(已闭环的现状)
  - 三处路由重写 = **中等 PR × 3**,不是小改

### 🟡 P2 - 可在 PR 阶段细化

#### P2-1 注册表单字段

- **现状**:`Register.tsx` 只有 name/email/password/confirmPassword
- **多租户需要**:
  - `workspace_name`(B 端公司/团队名)
  - `industry`(可选,用于后续 B 端画像)
  - `phone`(可选,合规需要)
  - `terms_accepted`(法律要求)
  - i18n 文案:`auth.json` 当前用 `initialSetup.*` 命名,需要新增 `tenantSignup.*`

#### P2-2 邀请 B 端成员加入已存在的 workspace — ❌ D2=暂缓(无期限)

- **决策**:**v1 完全不实现,无期限延后**(详见 §5 决策 3)
- **现状**:basjoo `AdminUser` 只有 1 个 workspace_id 字段
- **v1 行为**:
  - 每个 workspace 只有 **1 个 owner**(就是注册时填的邮箱)
  - `AdminUser.role` 仍预留 `tenant_admin` / `tenant_member` 枚举值(给后续 PR 用),**当前只有 `super_admin` / `tenant_owner` 会被实际创建**
  - Workspace 成员管理页面**不开发**,settings 页只展示"成员管理即将推出"
  - 没有"邀请"、"加入"按钮 UI
- **未来要补时的工作量**(留底):
  - basjoo 后端:`/api/v1/tenants/{id}/members` GET/POST/DELETE
  - basjoo 前端:`Members` settings 页 + 邀请 modal + 接受邀请落地页
  - Dify fork 增量:无需新增 endpoint,复用已有 `TenantService.create_tenant_member`
  - SMTP 集成:basjoo 发邀请邮件(借 Dify SMTP 或自建)
  - RBAC 边界:owner 可邀请 admin/member,admin 可邀请 member,member 不能邀请
- **为什么可以无限期延后**:
  - B 端 owner 单人先把业务跑通,验证业务模型
  - 成员协作需求出现时,再开 M12+ 里程碑
  - Dify 侧 `create_tenant_member` 已存在,**未来补这块只是 basjoo 前/后端 + UI 工作,不依赖 Dify 侧新功能**
- **Dify 侧不需预留**:Dify `TenantAccountJoin` 表 / `create_tenant_member` service 已存在,无需在 Dify fork 里提前埋点

#### P2-3 注册频率限制与防滥用

- **现状**:`auth.py` 无 rate limit
- **多租户需要**:
  - `/tenants/register` 必须限速(IP + email 双维度),否则可被批量建 workspace 把 Dify 撑爆
  - 邮箱验证(发邮件验证码,basjoo 自建或借 Dify SMTP)
  - 域名黑名单(`@tempmail.com` 等)
  - 与 `middleware/rate_limit.py` 现有 Redis 限流器集成

#### P2-4 basjoo 前端 `/signup` 路由的 UI

- **现状**:`app/(auth)/register/page.tsx` 路由已有
- **多租户需要**:
  - 新增 `/signup` 路由(`/register` 保留给 bootstrap)
  - `Login.tsx` 在 `bootstrap_required=false` 时显示"还没有账号?立即注册"链接
  - `Register.tsx` 内部分支:`bootstrap_required=true` 走 bootstrap 注册;否则显示"该链接仅供系统初始化"
  - i18n key 重构

#### P2-5 失败 UX

- **现状**:无相关处理
- **多租户需要**:
  - Dify 创建失败时,前端展示"Dify workspace 准备失败,后台重试中,请稍后查看 dashboard"
  - 注册成功但 provisioning 异步进行时,登录后 dashboard 顶部 banner:workspace 就绪状态
  - 重试按钮(限定 owner 角色)

---

## 4. 依赖关系图(P0 / P1 解锁关系) — 基于决策 1=A 重排

```
P0-1(A:fork Dify 新增 admin endpoint)✅ 决策
    ├─ Dify fork 改动清单 6 项(§5 决策 1)
    │   ├─ service 层:provision_tenant_by_admin / create_account_with_password
    │   ├─ controller 层:POST /console/api/admin/workspaces
    │   ├─ controller 层:DELETE /console/api/admin/workspaces/{id}(回滚用)
    │   ├─ controller 层:GET /console/api/admin/workspaces/{id}/owner-credentials(一次性拉密码)
    │   ├─ controller 层:POST /console/api/admin/accounts/{id}/reset-password(决策=否 时跳过)
    │   └─ models 层:Pydantic schema + error 注册
    └─ basjoo `.env` 加 `DIFY_TENANT_PROVISION_ENABLED` 开关

P0-2(basjoo /register 拆为 bootstrap + tenant_register)
    ├─ 依赖:P0-1 决策(因为 tenant_register 要不要同步调 Dify)
    └─ 解锁:AuthContext / Register.tsx / Login.tsx 改造 + RBAC 矩阵实施

P0-3(事务边界 + 回滚)
    ├─ 依赖:P0-1 决策(必须 Dify fork 提供 DELETE endpoint)
    ├─ 依赖:P1-1 字段(signup_idempotency_key)
    └─ 解锁:可靠的多租户注册,否则数据不一致

P1-1(Workspace 关联字段 + Alembic 迁移)
    ├─ 依赖:无(纯 schema 改动)
    ├─ 解锁:P0-3 落地 + P1-4 路由层
    └─ 解锁后:可立即为单租户 dev 环境跑迁移,不依赖 Dify fork

P1-2(B 端 owner Dify 密码策略)
    ├─ 依赖:决策 2(决策 1=A 已 OK)
    └─ 解锁:注册成功页 UX 设计

P1-3(服务账号审计)
    ├─ 依赖:P0-1 fork(需要在 Dify audit log 加 correlation_id 透传)
    └─ 解锁:合规审计能力,非阻塞但应与 P0-1 同期完成

P1-4(M3/M6/M7 路由层重写)
    ├─ 依赖:P1-1 完成 + Dify API key 列就绪
    └─ 解锁:多租户业务真正跑起来
```

---

## 5. 用户决策记录与待决项

### 决策 1 (P0-1) ✅ 已拍板 — Dify 端 workspace 创建走 A 路径

**决策**:**Fork Dify 源码,新加 `POST /console/api/admin/workspaces` endpoint**(命名约定:加 `admin` 前缀以区分 Dify 原生 `/workspaces`,后续 §3 / §5 一律沿用此命名),basjoo 后端用 Dify admin service account 调这个新 endpoint。

**部署上下文**(2026-06-17 用户确认):**Dify 是自部署,非 Dify Cloud**;当前冻结一段时间,未来某时点升级。这是大多数自部署的现实,直接影响 A 路径的长期维护模型。

**对架构的约束**(下游 P0/P1 必须遵守):
- Dify 侧要新增 endpoint → **Dify fork 是 v1 长期资产**,必须建分支维护,不能 cherry-pick 到 Dify upstream(M9.5 spec §1.2.1 Plan A 路径已包含此假设)
- **冻结期策略**:Dify 自部署版本冻结期间,fork 不需要 rebase,可全力做 basjoo 侧实施;fork 与 Dify upstream 的 drift 接受,直到升级时刻
- **升级时刻必跑**:升级时按 §6 升级 playbook 5 条 checklist 验证新 endpoint 与 Dify 新版本兼容,失败则阻断升级(回滚 Dify 镜像)
- Dify fork 改动量可控:3-5 个 Python 文件,集中在 `controllers/console/workspace/workspace.py` + 新增 service 方法 + 1 个权限装饰器
- basjoo 调 Dify 仍走 `DifyAdminClient._request()`,**复用现有基础设施**,无需新增 HTTP 客户端
- 维护 fork 的代价要写进 ops 文档(`docs/operations.md`),包含:升级时怎么 rebase、新 endpoint 在 Dify 主线 merge 后的去 fork 计划

**冻结期带来的额外好处**:
- ✅ Dify 主线 API 变更不会突然破坏 basjoo,**给 basjoo 团队可控节奏**
- ✅ M11 实施期间不需要担心 Dify 上游 PR 合入与 fork 冲突
- ✅ fork 的 Python 代码可以做完整单测 + 集成测试,测试基线冻结
- ⚠️ 代价:fork 与 Dify upstream 的 drift 会随时间累积,升级时一次性 rebase 工作量大(经验值:6 个月冻结 ≈ 1-2 天 rebase + 修复)

**升级时刻的硬性约束**:
- 不允许"先升 Dify 再补 basjoo" —— **必须** basjoo 测试套件在 Dify 新版本镜像上全绿才允许升级
- 升级失败回滚 = 切回旧 Dify 镜像,baskjoo 不动(baskjoo → Dify admin endpoint 是向后兼容设计)
- 升级后 24h 监控 `dify_provisioning_status='failed'` 比例,>5% 立即回滚

**Dify 侧 fork 改动的精确清单**(基于源码实证 `dify/api/services/account_service.py:1153-1242` + `dify/api/controllers/console/workspace/workspace.py`):

| # | 文件 | 改动 | 行数估计 |
|---|------|------|----------|
| 1 | `dify/api/services/account_service.py` | 新增 `TenantService.provision_tenant_by_admin(name, owner_email, owner_name, owner_password)` — 内部依次调 `create_tenant` + `AccountService.create_account(email, name, password)` + `create_tenant_member(role="owner")`,**bypass `is_allow_create_workspace` 校验**(传 `is_setup=True` 或新增 `is_admin_provision=True` 分支) | +60 行 |
| 2 | `dify/api/controllers/console/workspace/workspace.py` | 新增 `TenantProvisionByAdminApi` Resource,挂 `@console_ns.route("/admin/workspaces")`,装饰器链 `@setup_required` + `@admin_required`(已有 admin 装饰器),不做 `@account_initialization_required`(admin 不需要 init) | +80 行 |
| 3 | `dify/api/controllers/console/workspace/workspace.py` | 在 `console_ns.route("/admin/workspaces/<uuid:tenant_id>/owner-credentials")` 新增查询 owner 凭证的 GET,允许 basjoo 拉随机密码一次性回传 | +40 行 |
| 4 | `dify/api/services/account_service.py` | `AccountService.create_account` 暴露外部调用(目前是私有方法),新增 `create_account_with_password(email, name, password)` 重载 | +20 行 |
| 5 | `dify/api/controllers/console/workspace/error.py` | 新增 `TenantProvisionConflictError` / `AdminProvisionForbiddenError`,复用现有 `console_ns.expect(model)` 注册 | +15 行 |
| 6 | `dify/api/controllers/console/workspace/models.py` | 新增 `TenantProvisionPayload` / `TenantProvisionResponse` Pydantic 模型 | +30 行 |

**总改动**:约 +245 行 Python,集中在 3 个文件;**不影响 Dify 主线任何端点**,admin 路径完全独立。

**关键安全性约束**(A 路径特有的设计点):
- 新 endpoint 必须强制 `@admin_required` — 只有 Dify super admin 能调
- 新 endpoint **不能被 Dify 普通账号通过浏览器触发**(必须有 CSRF token + admin 角色双校验,与现有 `/console/api/apps` 一致)
- `create_account` 接受的密码必须满足 Dify `valid_password` 校验(已存在于 `libs/password.py`)
- basjoo 后端**必须**把新 endpoint 的响应里的随机密码**只回传一次**给 B 端用户注册成功页面,basjoo DB 不持久化(只存 hash,这里"hash"实际上是 basjoo 自己的 bcrypt,与 Dify 无关)
- basjoo 在 `.env` 里加 `DIFY_TENANT_PROVISION_ENABLED=true` 开关,Dify 侧 fork 没就绪时 basjoo 仍可启动,只是 `/tenants/register` 报 503

### 决策 2 (P1-2) ✅ 已拍板 — A1 方案,owner 不登 Dify Console

**决策**:**B 端 owner 不需要登录 Dify Web Console**。basjoo 在注册成功后**一次性展示 Dify 随机密码**,basjoo DB 不持久化,B 端后续所有 basjoo→Dify 调用走 basjoo service account。

**对架构的约束**:
- Dify fork 改动清单 5 中的 `POST /admin/accounts/{id}/reset-password` endpoint **取消**,Dify fork 改动减为 5 项(endpoint 4 个 + service 1 个 + error 1 个 + model 1 个),约 **+205 行 Python**
- basjoo 后端在 `/tenants/register` 响应里增加 `initial_dify_password` 字段(只返回一次,不进 DB 持久层)
- basjoo 前端注册成功页必须做"30 秒后强制 mask"的密码展示 modal(防止肩窥)
- Dify Account 字段:`Account.password_salt` 是 Dify 内部 bcrypt salt,basjoo **永远拿不到明文 hash 反推**,所以即使 basjoo 想要持久化也无法做到——设计上就只能一次性回传
- 后续若要支持"B 端 owner 登 Dify Console",工作量 = basjoo 引导页 + 调 Dify `forgot_password` 触发邮件,basjoo 侧 0.5 人天,Dify 侧 0 改动

### 决策 3 (P2-2) ✅ 已拍板 — 成员邀请 v1 不实现,无期限延后

**决策**:**v1 完全不实现成员邀请,无期限延后**。每个 workspace 只有 1 个 owner(注册时填的邮箱)。

**对架构的约束**:
- P2-2 降级为 **未来 backlog**,不进入 M11 / M11+ 任何 PR
- `AdminUser.role` 枚举仍预留 `tenant_admin` / `tenant_member`(留位),但 **v1 只创建 `super_admin` / `tenant_owner`**
- 不开发成员管理页面,settings 页只展示"成员管理即将推出"
- RBAC 矩阵中 `tenant_admin` / `tenant_member` 行保留为 v1 占位,**禁止**代码里出现创建这两种角色的逻辑(防止误用)
- Dify 侧不需预留:`TenantAccountJoin` 表 + `TenantService.create_tenant_member` 已存在,**未来补这块只是 basjoo 前/后端 + UI 工作,不依赖 Dify 侧新功能**
- Dify fork 改动清单 **不会因此减少**(成员管理本就不在 fork 计划里),仅是 basjoo 侧少一个 P1-4 子模块

---

## 6. 我的建议(2026-06-17)— D1/D2 已拍板后的收敛

### 三项决策全部确认 ✅

| 决策点 | 拍板 | 含义 |
|--------|------|------|
| D0 (workspace 创建路径) | **A** ✅ | Fork Dify,新加 admin endpoint 5 项改动,约 +205 行 Python(原 +245 行,D1=否砍了 reset-password endpoint) |
| D1 (owner 是否登 Dify Console) | **A1 否** ✅ | basjoo 一次性回传随机密码,30 秒后强制 mask |
| D2 (成员邀请 v1) | **暂缓(无期限)** ✅ | 不进 M11,留作未来 backlog |

### A 路径 + D1=否 + D2=暂缓 下的工作量精算

| 模块 | 改动 | 工作量 |
|------|------|--------|
| **Dify fork** | 5 项改动,约 +205 行 Python,3 个文件(详见 §5 决策 1) | 1.0 周 |
| **Dify fork 镜像构建** | Dockerfile + docker-compose 增量配置 + 与 M11+5 镜像协调 | 0.2 周 |
| **Dify 1.15+ 兼容性预检** | 5 条 checklist(详见下方"必须先验证的 1 件事") | 0.2 周 |
| **basjoo 数据模型** | Alembic 1 个迁移脚本,+6 列,2 个索引(详见 P1-1) | 0.2 周 |
| **basjoo 后端** | `/api/v1/tenants/register` 端点 + `TenantService` + 后台重试 cron + `audit_log` 表 + DifyAdminClient 调用 wrapper | 0.8 周 |
| **basjoo 前端** | `/signup` 路由 + Register.tsx 改造 + 30 秒 mask 密码展示 modal + i18n | 0.4 周 |
| **路由层 M3/M6/M7 重写** | workspace_id → Dify API key 路由 | **0.6 周**(从原 1 周压缩,因 D2=暂缓不必为多成员场景设计) |
| **测试 + 集成** | 单测 + 集成测试 + Dify fork 镜像端到端 | 0.4 周 |
| **文档 + ops** | operations.md 更新 Dify fork rebase 流程 + M11 spec 草稿 | 0.2 周 |
| **总工作量** | | **3.0 周 / 1 人** |

D2=暂缓省下约 0.5-0.8 周(成员邀请的 basjoo 后端 + 前端 + SMTP 集成本来就在工作量池里)。

### 风险收敛(决策 1=A + D1=否 + D2=暂缓 后)

- ✅ **B 端 owner 拿不到 Dify 密码风险** —— 已通过 30 秒 mask + 一次性展示 + Dify forgot_password 兜底化解
- ✅ **成员协作需求** —— v1 单 owner 跑通,验证业务模型后再开 M12+
- ⚠️ **Dify 1.15+ 升级破坏 A 路径**:仍是最大风险,详见下方 checklist
- ⚠️ **Dify fork rebase 成本**:Dify 主线月均 100+ commits,fork rebase 每月 2-4 小时,**必须写进 ops 文档**
- ⚠️ **运维复杂度**:docker-compose 要新增 `dify-fork-build` 步骤,或发布 Dify 时同步构建 fork 镜像
- 🆕 **30 秒 mask UX 风险**:B 端 owner 可能没看清就 mask 掉,需要提供"重新发送到注册邮箱"功能(走 basjoo 自有 SMTP,不需要 Dify 介入)

### 必须先验证的 1 件事(优先级最高,1-2 小时可完成)

**Dify 1.15+ 升级会不会破坏 A 路径的关键 service 方法**。**该项不要求 M11 立项前完成,降级为 Dify 升级 playbook,在升级时刻由 ops 团队执行**:
- [ ] `TenantService.create_tenant(name, is_setup=...)` 在 Dify 新版本是否仍存在且签名兼容
- [ ] `TenantService.create_tenant_member(tenant, account, role=...)` 在 Dify 新版本是否仍存在
- [ ] `AccountService.create_account(...)` 在 Dify 新版本是否对外暴露或可新增重载
- [ ] Dify 新版本是否引入了 `TenantPluginAutoUpgradeStrategy` 之外的强制初始化逻辑
- [ ] Dify 新版本的 `@admin_required` 装饰器是否还在 `controllers/console/wraps.py`

**5 条 checklist 完整版**收纳进 `docs/operations.md` 的 **"Dify 升级 playbook"** 专章,M11 立项时不要求跑,但 ops 文档必须包含:
- 升级前停服窗口建议(冻结期间无需,升级时必做)
- rebase 命令模板(基于 Dify fork 分支)
- 5 条 checklist 自动化脚本骨架(grep + pytest + dify integration test)
- 回滚 SOP(切回旧 Dify 镜像 + basjoo `.env` 不动)
- 升级后 24h 监控指标(参见 §5 决策 1 升级时刻硬性约束)

---

## 7. 下一步 — M11 spec 立项路径

### 自部署 Dify 上下文对 PR 顺序的影响

由于 Dify **自部署 + 冻结期**,M11 实施期 fork rebase 工作量为 0,可以全力推进 basjoo 侧。**PR 顺序保持 PR1 + PR2 并行起步**,不需要等 Dify 升级。

### PR 拆分(从原 5 个 PR 收紧为 **4 个 PR**,D2=暂缓砍掉原 PR-成员邀请)

| PR | 范围 | 工作量 | 依赖 |
|----|------|--------|------|
| **PR1**:Dify fork | 5 项 endpoint/service 改动 + Dockerfile + docker-compose | 1.0 周 | 无(冻结期无需 rebase) |
| **PR2**:basjoo 数据模型 | Alembic 迁移 + Workspace 关联字段 + `audit_log` 表 | 0.2 周 | 无(可与 PR1 并行) |
| **PR3**:basjoo 注册流 | `/api/v1/tenants/register` + `TenantService` + 后台重试 cron + DifyAdminClient wrapper | 0.8 周 | PR1 + PR2 |
| **PR4**:basjoo 前端 + 路由层 | `/signup` 路由 + Register.tsx + 30 秒 mask modal + M3/M6/M7 路由层重写 | 1.0 周 | PR3 |

**总工作量 3 周**(测试 + 文档折算在各 PR 内)。

**PR 顺序**:PR1 + PR2 并行 → PR3 → PR4。

### Dify 升级 playbook(M11 立项后由 ops 维护,M11 spec 必须预留接口)

升级 playbook 不是 PR,但要进 `docs/operations.md`,由 ops 团队在 Dify 升级时刻执行:
- **5 条 checklist 自动化脚本**:grep 关键 service 方法存在 + pytest + dify integration test
- **rebase 命令模板**:基于 Dify fork 分支(冻结期不跑,升级时刻跑)
- **回滚 SOP**:切回旧 Dify 镜像 + basjoo `.env` 不动 + basjoo 服务无需重启
- **24h 监控指标**:`dify_provisioning_status='failed'` 比例 < 5%

**M11 PR1 完成后,playbook 由 ops 接手维护**;M11 spec 阶段就要给 ops 留好钩子(Dify 镜像版本号变量化、basjoo 调用 Dify 的版本探测 endpoint)。

### M11 spec 草稿生成清单

**等你拍板进入 spec 阶段**后,我会生成以下文档(参考 M9.5 spec §1.2.1 结构):
- `docs/m11-spec.md` —— 主 spec,含 4 个 PR 的详细规格
- `docs/m11-pr1-dify-fork.md` —— Dify fork 改动逐行级 patch
- `docs/m11-pr2-schema.md` —— Alembic 迁移 + 表结构 DDL
- `docs/m11-pr3-register-flow.md` —— `/api/v1/tenants/register` 接口契约 + 重试策略
- `docs/m11-pr4-frontend-routing.md` —— 前端 + M3/M6/M7 路由层重写
- `docs/m11-test-plan.md` —— 测试用例清单
- `docs/m11-rollback-strategy.md` —— 回滚预案(含 Dify 升级 playbook 占位章节)

### 触发条件:你给出"go"指令

3 项决策都已拍板,**决策阶段已结束**。下一步是你的选择:
- **A. 立刻开 Dify fork 仓库**(PR1 准备工作,冻结期可从容做)
- **B. 立刻生成 M11 spec 草稿**(进入文档阶段,基于现有决策)
- **C. 暂停,先消化这份问题梳理**(给自己留时间评审)
- ~~D. 立刻跑 Dify 1.15+ 兼容性预检~~(已移除:自部署冻结期不要求,降级为升级 playbook)

**建议顺序**:C(评审) → B(spec 草稿) → A(fork 仓库) → 进 PR 实施。但你说了算。