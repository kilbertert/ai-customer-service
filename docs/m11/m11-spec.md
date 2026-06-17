# M11 Spec — B 端多租户(Plan A 切换)

> **版本**:v1.0 草稿
> **起草日期**:2026-06-17
> **状态**:草稿,待评审
> **上游决策文档**:`前端相关问题-第二块-B端租户隔离.md`(本仓库根)
> **下游分项 spec**:`m11-pr1-dify-fork.md` / `m11-pr2-schema.md` / `m11-pr3-register-flow.md` / `m11-pr4-frontend-routing.md` / `m11-test-plan.md` / `m11-rollback-strategy.md`

---

## 1. 范围与目标

### 1.1 业务目标

实现 B 端租户自助注册:每个 B 端用户在 basjoo 前端注册后,自动获得:
- 1 个 basjoo `Workspace`(数据隔离边界)
- 1 个对应的 Dify `Tenant`(Dify 侧 workspace)
- 1 个 Dify `Account`(owner 角色,绑进该 Tenant)
- 1 个 basjoo `AdminUser`(角色 `tenant_owner`,绑进该 Workspace)

注册成功后,B 端用户登录 basjoo 创建智能体 → basjoo 路由层按 `workspace_id` 找到对应 Dify tenant 的 API key → 调 Dify 完成 app/workflow/dataset 操作,**B 端之间数据完全隔离**。

### 1.2 战略对齐

- **M9.5 spec §1.2.1 Plan A 路径**:1 basjoo tenant → 1 Dify workspace。本 spec 是 Plan A 的具体实施。
- **决策记录**(2026-06-17 用户拍板):
  - D0 = **A**:Fork Dify 源码,新加 admin endpoint
  - D1 = **A1 否**:owner 不登 Dify Console,basjoo 一次性回传随机密码
  - D2 = **暂缓(无期限)**:成员邀请 v1 不实现
- **部署模型**:Dify **自部署**,非 Cloud。冻结一段时间,未来某时点升级。

### 1.3 不在范围

- B 端成员邀请(v1 单 owner,留作未来 backlog,详见 §6.2)
- B 端 owner 登录 Dify Web Console(v1 不支持,详见 §6.3)
- Dify 升级兼容性的实际执行(留作升级 playbook,M11 立项不跑,详见 §7)

---

## 2. 数据模型

### 2.1 basjoo 侧新增/变更表

**`workspaces` 表加 6 列 + 2 索引**(完整 DDL 见 `m11-pr2-schema.md`):

| 列 | 类型 | 默认 | 用途 |
|----|------|------|------|
| `dify_tenant_id` | VARCHAR(36) NULL | NULL | Dify Tenant UUID,provisioning 成功后回填 |
| `dify_account_id` | VARCHAR(36) NULL | NULL | Dify Account UUID,provisioning 成功后回填 |
| `dify_provisioning_status` | VARCHAR(20) NOT NULL | 'pending' | `pending` / `provisioning` / `ready` / `failed` / `failed_permanent` |
| `dify_provisioning_attempts` | INT NOT NULL | 0 | 后台重试计数 |
| `dify_provisioning_last_error` | TEXT NULL | NULL | 最后一次失败的 Dify 错误信息 |
| `signup_idempotency_key` | VARCHAR(36) UNIQUE NULL | NULL | 每次 `/tenants/register` 调用生成一次,贯穿 basjoo + Dify 幂等性 |

**索引**:
- `idx_workspaces_dify_provisioning_status` — 部分索引 `WHERE status IN ('failed', 'provisioning')`,后台 cron 拉取
- `idx_workspaces_dify_tenant_id`

### 2.2 basjoo 侧新增表

**`audit_logs` 表**(P1-3 双轨审计):

| 列 | 类型 | 用途 |
|----|------|------|
| `id` | BIGSERIAL PK | 自增 |
| `tenant_id` | VARCHAR(36) | basjoo Workspace.id |
| `actor_user_id` | INT | basjoo AdminUser.id |
| `action` | VARCHAR(64) | `tenant.create` / `tenant.retry` / `tenant.provision_failed` |
| `dify_request_id` | VARCHAR(36) NULL | Dify 侧 correlation_id,透传自 Dify 审计 |
| `correlation_id` | VARCHAR(36) | basjoo 生成,贯穿 basjoo ↔ Dify |
| `status` | VARCHAR(20) | `success` / `failed` |
| `error_detail` | TEXT NULL | 失败时填 |
| `created_at` | TIMESTAMP NOT NULL | 默认 `now()` |

### 2.3 basjoo 侧 RBAC 枚举扩展

`AdminUser.role` 扩展:

| 值 | 含义 | v1 是否创建 |
|----|------|------|
| `super_admin` | 平台方 | ✅(bootstrap) |
| `tenant_owner` | B 端 owner | ✅(注册时) |
| `tenant_admin` | B 端管理员 | ❌ 占位,v1 不创建 |
| `tenant_member` | B 端成员 | ❌ 占位,v1 不创建 |

### 2.4 basjoo 状态机

```
pending ──register 触发──> provisioning ──Dify 成功──> ready
                              │
                              └──Dify 失败──> failed ──cron 重试──> provisioning
                                              │
                                              └──重试 3 次仍失败──> failed_permanent
```

---

## 3. 接口契约

### 3.1 basjoo 后端新端点

| 端点 | 方法 | 用途 | 鉴权 |
|------|------|------|------|
| `/api/v1/tenants/register` | POST | B 端租户自助注册 | 无(bootstrap 后开放) |
| `/api/v1/tenants/{id}/provisioning-status` | GET | 轮询 workspace 准备状态 | JWT(workspace owner) |
| `/api/v1/tenants/{id}/retry-provisioning` | POST | 手动触发重试 | JWT(workspace owner,`status in (failed, failed_permanent)`) |

**完整契约见 `m11-pr3-register-flow.md`**。

### 3.2 Dify fork 新端点(PR1)

| 端点 | 方法 | 用途 | 鉴权 |
|------|------|------|------|
| `/console/api/admin/workspaces` | POST | basjoo admin 代建 tenant + owner account | Dify admin session |
| `/console/api/admin/workspaces/{tenant_id}` | DELETE | 回滚时清理(tenant + 关联 account) | Dify admin session |
| `/console/api/admin/workspaces/{tenant_id}/owner-credentials` | GET | 一次性拉 owner 初始密码 | Dify admin session |
| `/console/api/admin/workspaces/health` | GET | basjoo 启动时探测 fork endpoint 是否就绪 | Dify admin session |

**完整 patch 见 `m11-pr1-dify-fork.md`**。

### 3.3 basjoo 后端行为约束

- `/tenants/register` 限速:IP 维度 5 次/小时 + email 维度 3 次/小时(借 `middleware/rate_limit.py` 现有 Redis 限流器)
- 域名黑名单:`@tempmail.com` / `@guerrillamail.com` / `@mailinator.com` 等(黑名单文件 `backend/security/email_blacklist.txt`,可通过环境变量覆盖)
- 注册密码必须 ≥ 8 字符 + 满足 Dify `valid_password` 校验
- workspace_name 长度 [3, 50]

---

## 4. 注册流时序

### 4.1 正常流程

```
B 端用户  →  basjoo 前端 /signup 提交(name, email, password, workspace_name)
           ↓
basjoo 后端 /api/v1/tenants/register
           ↓
[事务 1:basjoo DB]
  - 生成 signup_idempotency_key (UUIDv7)
  - INSERT workspaces(dify_provisioning_status='pending', signup_idempotency_key=...)
  - INSERT workspace_quotas
  - INSERT admin_users(role='tenant_owner', workspace_id=..., password=bcrypt)
  - INSERT audit_logs(action='tenant.create', status='success')
  COMMIT
           ↓
[事务外:Dify HTTP 调用]
  POST Dify /console/api/admin/workspaces
    body: {workspace_name, owner_email, owner_name, owner_password, idempotency_key}
  → 返回 {workspace_id, owner_account_id, initial_password}
           ↓
[事务 2:basjoo DB]
  - UPDATE workspaces SET dify_tenant_id=..., dify_account_id=..., dify_provisioning_status='ready'
  - INSERT audit_logs(action='tenant.provision', status='success', dify_request_id=...)
  COMMIT
           ↓
返回 {access_token, workspace_id, dify_initial_password}
           ↓
basjoo 前端注册成功页:30 秒 modal 展示 initial_password,后强制 mask
```

### 4.2 失败流程

**Case A**:basjoo 写库失败 → 返回 500,B 端无副作用,basjoo 自动 rollback。

**Case B**:basjoo 写库成功 + Dify 调用失败:
- basjoo 调 `DifyAdminClient._request()` 抛异常 → 事务 2 更新 `status='failed'`,记录 `last_error`
- 写入 `audit_logs(action='tenant.provision', status='failed', error_detail=...)`
- 后台 cron(每 5 分钟)扫描 `status IN ('failed', 'failed_permanent') AND attempts < 3` 重试
- 第 3 次失败后 → `status='failed_permanent'`,触发 admin 通知(baskjoo 日志 + 可选邮件)

**Case C**:Dify 部分写入(tenant 已建但 owner account 失败):
- Dify fork 必须在事务内完成 tenant + account + TenantAccountJoin 创建,任一步失败全回滚
- 详请见 `m11-pr1-dify-fork.md` §3 事务边界设计

**Case D**:网络超时:
- basjoo 用 `idempotency_key` 调 Dify,Dify fork **必须** 24h 内同 key 幂等
- 重试时如果 Dify 端已成功,直接返回已有 tenant_id / account_id,basjoo 不会重复创建

---

## 5. PR 拆分(4 个 PR,顺序可部分并行)

| PR | 范围 | 工作量 | 依赖 |
|----|------|--------|------|
| **PR1**:Dify fork | 5 项 endpoint/service 改动 + Dockerfile + docker-compose | 1.0 周 | 无 |
| **PR2**:basjoo 数据模型 | Alembic 迁移 + Workspace 关联字段 + `audit_logs` 表 | 0.2 周 | 无(可与 PR1 并行) |
| **PR3**:basjoo 注册流 | `/api/v1/tenants/register` + `TenantService` + 后台重试 cron + DifyAdminClient wrapper | 0.8 周 | PR1 + PR2 |
| **PR4**:basjoo 前端 + 路由层 | `/signup` 路由 + Register.tsx + 30 秒 mask modal + M3/M6/M7 路由层重写 | 1.0 周 | PR3 |

**总工作量 3 周 1 人**。冻结期内 PR1 无需 rebase,可全力做 basjoo 侧。

**PR 顺序**:PR1 + PR2 并行起步 → PR3 → PR4。

---

## 6. 边界与约束

### 6.1 与 M10+5 已闭环代码的兼容性

M10+5(commit `5c34af2` + CSRF sync `e0f0b6b`)已闭环:
- DifyProvider 位于 `backend/services/dify/` 包
- DifyAdminClient 已在 `backend/services/dify/admin_client.py` 实现
- M11 PR3 必须复用 `DifyAdminClient._request()`,**不新增 HTTP 客户端**

### 6.2 成员邀请(v1 不实现)

每个 workspace 只有 1 个 owner。`tenant_admin` / `tenant_member` 角色枚举预留但不创建。未来要补时:
- basjoo 后端:`/api/v1/tenants/{id}/members` GET/POST/DELETE
- basjoo 前端:`Members` settings 页 + 邀请 modal
- Dify 侧:复用已有 `TenantService.create_tenant_member`,无需 fork

### 6.3 B 端 owner 登录 Dify Console(v1 不支持)

v1 注册成功页一次性展示 Dify 随机密码,30 秒后强制 mask。B 端想看 Dify Console:
- v1 不提供入口
- 未来如要支持:basjoo 引导页 + 调 Dify `forgot_password` 触发邮件,baskjoo 侧 0.5 人天,Dify 侧 0 改动

### 6.4 与 Dify 1.15+ 升级 spec 的关系

M11 PR1 完成后,fork 与 Dify upstream 的 drift 接受,直到升级时刻。升级时按 `m11-rollback-strategy.md` §4 升级 playbook 5 条 checklist 验证。

### 6.5 Dify 自部署的运维约束

- Dify 镜像版本号必须在 basjoo `.env` 显式声明(`DIFY_IMAGE_VERSION=1.14.2-fork-m11-v1.0`),Dify 侧 `.env` 需配套设置 `ADMIN_API_KEY` 给 basjoo 调用
- basjoo 启动时调 `GET /console/api/admin/workspaces/health` 探测 Dify fork 就绪状态,失败则 503
- Dify 容器重启时 basjoo 无需重启,`DifyAdminClient` LRU 缓存自动重建 session

---

## 7. 验收门(M11 整体)

每 PR 单独验收 + 整体 M11 验收:

### 单 PR 验收

- 单测覆盖率 ≥ 80%(PR1 Dify fork ≥ 70%,因 Dify 测试基础设施有限)
- 集成测试覆盖正常流 + 4 个失败 case
- 与 M10+5 已有测试套件无回归
- 类型检查 / lint 通过

### 整体 M11 验收

- E2E:docker compose up dev → 走完 B 端注册 → 创建智能体 → widget chat 流式响应
- 失败注入:Dify 容器 kill → basjoo 自动 retry → Dify 重启后 provisioning 成功
- 文档:`docs/operations.md` 含 Dify 升级 playbook(5 条 checklist + rebase 模板 + 回滚 SOP)
- 性能:注册 P95 < 3s(Dify 调用 < 2s)

---

## 8. 风险与缓解

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| Dify fork 升级时 rebase 冲突 | 中 | 升级 playbook + 6 个月冻结期经验值 1-2 天修复 |
| Dify 1.15+ 重构 TenantService | 中 | 升级 playbook 5 条 checklist 阻断不兼容升级 |
| 30 秒 mask UX:B 端没看清 | 低 | 注册成功页"重新发送到注册邮箱"兜底(走 basjoo 自有 SMTP) |
| 多 B 端共享 Dify 进程的隔离可靠性 | 低 | Dify 自带 tenant_id 隔离 + basjoo 路由层 + audit 双轨 |
| fork 与 Dify upstream drift 累积 | 低 | 接受,升级时刻一次性 rebase |

---

## 9. 时间线(冻结期内)

```
Week 1:
  Mon-Tue  PR1 Dify fork endpoint/service 改动
  Wed      PR1 Dockerfile + docker-compose 联调
  Thu-Fri  PR2 Alembic 迁移脚本 + audit_logs 表
  同时 PR1/PR2 review

Week 2:
  Mon-Tue  PR3 /tenants/register 端点 + TenantService
  Wed      PR3 后台重试 cron + audit_logs 写入
  Thu-Fri  PR3 DifyAdminClient wrapper + 单测

Week 3:
  Mon-Tue  PR4 /signup 前端 + Register.tsx + 30 秒 mask modal
  Wed      PR4 i18n + 测试
  Thu      PR4 M3/M6/M7 路由层重写
  Fri      M11 整体 E2E + 验收门

收尾:
  - Dify 升级 playbook 写进 docs/operations.md
  - M11 spec 标记 v1.0 released
  - 后续:M12 引入成员邀请(决策待定)
```

---

## 10. 参考资料

- `前端相关问题-第二块-B端租户隔离.md` — 决策源头
- `memory/basjoo-dify-isolation-strategy.md` — Plan A 战略回答
- `memory/m11-dify-1.15-upgrade-spec.md` — Dify 1.15+ 升级 6 补丁(升级时刻执行)
- `memory/m10plus5-closure-2026-06-16.md` — M10+5 闭环基线
- `docs/m9.5-spec-addendum.md` — M9.5 §1.2.1 Plan A 路径详细对比
- `backend/services/dify/admin_client.py` — basjoo ↔ Dify 复用基础设施
- `dify/api/services/account_service.py:1153-1242` — Dify TenantService 现有实现
- `dify/api/controllers/console/workspace/workspace.py` — Dify workspace 控制器

---

## 附录 A:变更清单(本 spec 涉及的文件)

**Dify fork 侧(PR1)**:
- `dify/api/services/account_service.py` — +60 行
- `dify/api/controllers/console/workspace/workspace.py` — +120 行
- `dify/api/controllers/console/workspace/error.py` — +15 行
- `dify/api/controllers/console/workspace/models.py` — +30 行
- `dify/Dockerfile.fork` — 新增

**basjoo 后端(PR2 + PR3)**:
- `backend/alembic/versions/xxxx_add_dify_provisioning.py` — 新增
- `backend/models.py` — Workspace +6 列,新增 AuditLog 模型
- `backend/api/v1/tenants.py` — 新增文件,~150 行
- `backend/services/tenant_service.py` — 新增文件,~120 行
- `backend/services/dify/tenant_provisioner.py` — 新增文件,~80 行
- `backend/scheduler/tenant_provisioning_retry.py` — 新增文件,~50 行
- `backend/security/email_blacklist.txt` — 新增
- `backend/config.py` — 新增 3 个配置项

**basjoo 前端(PR4)**:
- `frontend-nextjs/app/(auth)/signup/page.tsx` — 新增
- `frontend-nextjs/src/views/Signup.tsx` — 新增,~250 行
- `frontend-nextjs/src/views/Register.tsx` — 改造(拆 bootstrap / tenant signup 分支)
- `frontend-nextjs/src/context/AuthContext.tsx` — 新增 `signupAsTenant()` 方法
- `frontend-nextjs/src/components/PasswordRevealModal.tsx` — 新增 30 秒 mask modal
- `frontend-nextjs/src/locales/{zh-CN,en-US}/auth.json` — 新增 `tenantSignup.*` 文案
- `frontend-nextjs/src/views/Login.tsx` — 改造(显示"立即注册"链接)
- `backend/api/v1/endpoints.py` — M3/M6/M7 路由层重写(~200 行)

**文档**:
- `docs/operations.md` — 新增"Dify 升级 playbook"专章

**总行数估算**:basjoo 后端 ~+700 行 / basjoo 前端 ~+500 行 / Dify fork ~+225 行 / 文档 ~+200 行