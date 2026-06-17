# M11-CLOSURE — B 端多租户(Plan A 切换)系列收口

> **版本**:v1.0 盖棺定论
> **收口日期**:2026-06-17
> **基线 HEAD**:`404f191`(本仓库 `feat/m11-frontend-routing` 分支)
> **状态**:M11 PR1-PR4 全部闭环,系列收口
> **阅读对象**:下一会话接手 M11+ / M12+ backlog 的人(用户本人或新 Claude)

---

## 0. 一句话总结

**M11 = basjoo 从单租户 bootstrap 切到 B 端多租户 Plan A(每个 B 端用户一个 basjoo Workspace + 一个 Dify Tenant + 一个 tenant_owner 角色)**。4 个 PR 全部闭环,基线 5d6b5be0 → `404f191`(5 个 commit,含 PR1 fork Bearer 化 + tenant_owner role gating 修复),Dify 自部署冻结期 fork rebase 工作量为 0,后续 backlog 转入 M11+ / M12+。

---

## 1. 系列交付清单(PR1-PR4)

| PR | 范围 | 关键 commit | spec / handoff |
|----|------|------------|---------------|
| **PR1** Dify fork + Bearer ADMIN_API_KEY provisioning | `POST /console/api/admin/workspaces` endpoint + 5 文件 +205 行 Python;basjoo `DifyTenantProvisioner` Bearer 路径;`dify_admin_api_key` / `dify_admin_api_base` settings | `ed19d87`(merge) / `a963b81`(merge) / `5410756`(Bearer) | `m11-pr1-dify-fork.md` |
| **PR2** Alembic schema + 关联字段 | `workspaces` 表 +6 列(`dify_tenant_id` / `dify_account_id` / `dify_provisioning_status` / `dify_provisioning_attempts` / `dify_provisioning_last_error` / `signup_idempotency_key`);`audit_log` 表;迁移脚本 | (PR2 merge) | `m11-pr2-schema.md` |
| **PR3** `/api/v1/tenants/register` 端点 + `tenant_service` | basjoo DB 写先于 Dify HTTP 调用;5min cron 重试,3 次后 `failed_permanent`;事务回滚路径 | `78a4b2b` | `m11-pr3-register-flow.md` |
| **PR4** B 端注册前端 + 路由层重写 | `/signup` 路由 + `Register.tsx` 改造 + 30s mask 密码展示 modal + M3/M6/M7 路由层 workspace_id 路由;**收口修复**:tenant_owner 角色 routing + 鉴权门 + Login.tsx state batching | `4e9fd11` / `ad3595a` / `58e047a` / `9552f63`(本会话) | `m11-pr4-frontend-routing.md` |

### 1.5 本会话(M11 PR4 E2E 收口)的 4 个 commit

```
5410756  fix(m11): PR1 fork — Bearer ADMIN_API_KEY provisioning path
9552f63  fix(m11): tenant_owner role gating — B端注册后路由 + API 鉴权
404f191  chore(gitignore)+docs(m11): 允许 docs/m11/ 归档 + B端问题梳理入仓
+ (本盖棺定论 commit, 即将)
```

### 1.6 关键决策 — "为什么这 4 个 commit 在 PR4 闭环后才补"

- `5410756` Bearer 化 = PR1 fork 的 `dify-1.14.2-fork-m11` 镜像暴露的 `/console/api/admin/*` endpoint 改用 `ADMIN_API_KEY` header 鉴权(原 Dify 默认无鉴权,1.14.2-m11 fork 加的),basjoo `tenant_provisioner.py` 同步支持
- `9552f63` tenant_owner role gating = PR4 E2E 发现的真 bug:M11 PR3 引入的 `tenant_owner` 角色,前端 `RequireAuth` + 后端 `require_*` 鉴权门**都没接** → B 端用户登录后被弹回 /login + `/agents` 报"Insufficient permissions" → 7 处硬编码 `role == "super_admin"` 替换为 `is_workspace_owner()` helper(语义 super_admin ∪ tenant_owner)

---

## 2. 决策基线(LOCKED — 不再翻案)

| 决策 ID | 内容 | 影响范围 | 来源 |
|---------|------|----------|------|
| **D0** | Dify workspace 创建走 **A 路径**:Fork Dify 源码 + 加 admin endpoint | Dify fork 5 文件 +205 行;basjoo `.env` 加 `DIFY_TENANT_PROVISION_ENABLED` 开关 | B端 doc §5 决策 1 |
| **D1** | B 端 owner **不登 Dify Console**:basjoo 一次性回传随机密码,30s mask | basjoo 注册成功页 UX;Dify fork 砍掉 reset-password endpoint(从 +245 → +205 行) | B端 doc §5 决策 2 |
| **D2** | 成员邀请 v1 **不实现**,无期限延后 | `tenant_admin` / `tenant_member` 枚举值预留,v1 不创建;无邀请 UI | B端 doc §5 决策 3 |
| **D3**(实施期) | `tenant_owner` = workspace 全权(等同 `super_admin` 在自家 workspace 范围);跨 workspace 仍只 `super_admin` | `RequireAuth.tsx` / `auth.py` / `endpoints.py` 7 处 + `is_workspace_owner()` helper | `9552f63` |
| **D4**(实施期) | Plan B 基线保持:basjoo 创建 agent 时**不调 Dify 4 步**(`dify_app_id=NULL`,`dify_publish_status='draft'`) | `agent` 表 8 个 dify_* 字段在 Plan B 模式下均为 NULL;Plan A 切换 = 把这块从"没调"变成"必调" | E2E 验证 2026-06-17 |

---

## 3. 验收门状态(盖棺时刻)

| Gate | 状态 | 证据 |
|------|------|------|
| 端到端 B 端注册 → 登录 → 创建智能体 | ✅ PASS | Playwright MCP 2026-06-17;`agt_0115aa6588d7` 创建成功 |
| Dify tenant + account 自动创建 | ✅ PASS | Dify 162.211.183.169 / `qushiyun` tenant + `15330487961rl@gmail.com` owner account |
| Plan B 隔离基线保持 | ✅ PASS | `apps` 表 0 行(basjoo 没调 Dify 4 步),符合 Plan B 预期 |
| 跨 PR 不破坏现有功能 | ✅ PASS | `tenant_owner` role gating fix 回归 `super_admin` 行为不变 |
| Dify fork 5 项改动实施 | ✅ PASS | `dify-1.14.2-fork-m11` 镜像构建成功(`/admin/workspaces` endpoint 200) |
| Alembic 迁移 | ✅ PASS | `workspaces` 表 +6 列 + 2 索引(PR2 闭环时已跑) |
| `/api/v1/tenants/register` 503 优雅降级 | ✅ PASS | `58e047a` 修复 500→503 + docker-compose 留 DIFY_* 占位 |
| 409 i18n 接线 | ✅ PASS | `ad3595a` 修复 tenant 注册 500 错误并接 409 i18n |

**未通过 / 未执行的 gate**(诚实标注):
- ⚠️ **CI 自动化测试**:M11 PR1-PR4 的 CI 门未在本机跑过,需在远端 CI / 真 basjoo chat_stream 验证后填 `CONDITIONAL PASS → UNCONDITIONAL PASS`
- ⚠️ **Dify 1.15+ 兼容性**:Dify 自部署冻结期不要求;**升级时刻必跑 5 条 checklist**(见 §6)

---

## 4. 未完成 backlog(转入 M11+ / M12+)

### 4.1 P0 — M11+ 必做

- **P0-A** Plan A 切回:basjoo 创建 agent 时调 Dify 4 步(`create_app_and_workflow`),让 `dify_app_id` 从 NULL 变成 UUID;Plan B 模式当前是"基线可跑"但不是"Plan A 切完"
- **P0-B** Dify 1.15+ 升级时的 A 路径兼容测试(5 条 checklist):
  - [ ] `TenantService.create_tenant(name, is_setup=...)` 签名兼容
  - [ ] `TenantService.create_tenant_member(...)` 签名兼容
  - [ ] `AccountService.create_account(...)` 对外暴露
  - [ ] `@admin_required` 装饰器仍位于 `controllers/console/admin.py`
  - [ ] 无 `TenantPluginAutoUpgradeStrategy` 之外的强制初始化逻辑

### 4.2 P1 — M11+ 排队

- **P1-A** DifyStatusBadge deep link(`前端相关问题.md` §3 / §9,route #1,1 PR):badge 旁加 "Configure in Dify Studio" 按钮 → window.open 跳 Dify Studio URL(前提:`dify_app_id` 不为 NULL,见 P0-A)
- **P1-B** M3/M6/M7 路由层压力测试(M11 PR4 实施期内简化,没跑全量压测)
- **P1-C** `audit_log` 表查询后台 admin UI
- **P1-D** `/tenants/register` 限速(IP + email 双维度 + 域名黑名单),防 Dify 撑爆

### 4.3 P2 — M12+ / 视情况启动

- **P2-A** 成员邀请 v2(决策 D2 暂缓项,无期限 → 视业务需求启动)
- **P2-B** 工作流模板预生成(`前端相关问题.md` §3 route #2,3-5 PR):Plan A 切完后,basjoo 创建 agent 时根据用户输入生成 Start→LLM(prompt)→End 基础 DSL
- **P2-C** Dify Studio iframe 内嵌(`前端相关问题.md` §3 route #3,不推荐)

---

## 5. 跨会话处理方法论(给新会话/新 Claude 复用)

> **本节是核心价值** — 新会话接手 `前端相关问题.md`(第一块)时,**按本节方法论处理**。
> 不要重新发明轮子。

### 5.1 方法论 — 7 阶段闭环

M11 系列用的处理方式,提炼成可复用流程:

```
阶段 0 — 盘清楚现状(必做,1-2 小时)
   ↓
阶段 1 — 列问题清单 + 严重度排序(P0/P1/P2)
   ↓
阶段 2 — 用户拍板关键决策点(决策日志,不再翻案)
   ↓
阶段 3 — spec 文档(主 spec + 分项 spec,4-6 份)
   ↓
阶段 4 — PR 实施(每个 PR 1 commit,commit message 标准化)
   ↓
阶段 5 — 收口 E2E 验证(Playwright MCP + Dify 平台实测)
   ↓
阶段 6 — 盖棺定论(本文件就是产物,见 §5.7 模板)
```

### 5.2 阶段 0 — 盘清楚现状(必做)

**做什么**:
1. 读 CLAUDE.md / 项目根的 M*.md 系列文档,知道仓库历史脉络
2. 读最近的 1-2 份 handoff 文档,知道上一个里程碑的交付状态
3. **不要假设**,**源码实证**:
   - 看 `git log` 最近 10 个 commit
   - 看相关表 schema(`sqlite3 ... ".schema"`)
   - 必要时 SSH 到 Dify 服务器查 Dify 端 DB(本次用的方式)
4. 把"用户口述的现状"和"代码实证的现状"做 diff,标出 gap

**本节关键**:别猜,别训练数据外推,**源码 + DB 实证**。

### 5.3 阶段 1 — 列问题清单 + 严重度

**格式**(沿用 B端 doc §3 模式):

```markdown
### 🔴 P0 - 立项前必须拍板
#### P0-X 现象
- 现状
- 影响
- 决策选项 A/B/C(每个选项给工作量 + 风险)

### 🟠 P1 - 设计阶段必须决策
#### P1-X ...
### 🟡 P2 - PR 阶段细化
#### P2-X ...
```

**关键**:每个 P0 必须给"决策选项",不能只描述现象让用户自己想去哪。

### 5.4 阶段 2 — 用户拍板关键决策(决策日志)

**格式**(沿用 B端 doc §5):

```markdown
### 决策 X — ✅ 已拍板 — 标题

**决策**: 一句话结论

**对架构的约束**: 列出下游 P0/P1 必须遵守的约束

**部署上下文**: 自部署 vs Cloud,会影响长期维护模型

**升级时刻的硬性约束**: 升级时必须验的 checklist
```

**关键**:
- 决策一旦拍板就**不再翻案**,下次讨论从"决策 X 已拍板,执行"开始
- 决策要带"对架构的约束"段,**写出来就强制下游遵守**
- 决策前要给工作量精算(参考 B端 doc §6 的表格)

### 5.5 阶段 3 — spec 文档(主 spec + 分项)

**目录结构**(沿用 `docs/m11/` 模式):

```
docs/m11/
  m11-spec.md                ← 顶层 spec,1 PR/1 范围 + 决策基线 + 风险
  m11-pr1-xxx.md             ← 1 个 PR = 1 份 spec
  m11-pr2-xxx.md
  m11-pr3-xxx.md
  m11-pr4-xxx.md
  m11-test-plan.md           ← 测试矩阵
  m11-rollback-strategy.md   ← 回滚预案 + 升级 playbook
  M11-CLOSURE.md             ← 系列收口(本文件,阶段 6 产物)
```

**每个 PR spec 必含**:
- 范围(改动文件 + 行数估计)
- 依赖(其他 PR)
- 工作量精算(人天)
- 接口契约(API 端点 / DB schema / 前端路由)
- 测试用例(关键路径 + 边界)

### 5.6 阶段 4 — PR 实施(commit message 标准化)

**commit message 格式**(沿用本仓库 `git log` 风格):

```bash
<type>(m11): <PR 名> — <一句话范围>

<改动文件 + 行数 + 关键设计点>

<不做的事 / 保持不动>
<基线: 上一个 commit SHA>
<如果跨 PR: 写明这是 PR X / Y / Z 哪个>
```

**每个 PR 一个 commit,不要 squash 也不要分太细**。理由:
- 后续好回溯(每个 commit 对应一个 PR,粒度刚好)
- 出问题能精准 revert(不会带其他 PR 的改动)

### 5.7 阶段 6 — 盖棺定论(本文件就是模板)

**新会话接手新问题时,要生成的收口文件结构**:

```markdown
# {系列名}-CLOSURE — {一句话范围}

## 0. 一句话总结
## 1. 系列交付清单(每个 PR)
## 2. 决策基线(LOCKED,表格)
## 3. 验收门状态(✅ / ⚠️ / ❌)
## 4. 未完成 backlog(P0/P1/P2)
## 5. 跨会话处理方法论(给下一个 {类似问题} 复用)
## 6. 文件索引(所有 docs/{系列}/ 下的文件)
## 7. 决策日志全文(可选,见 B端 doc §5)
```

**核心价值在 §5**:把"这次怎么处理的"提炼成方法论,下次新会话接手类似问题**直接按 §5 走**,不要从零开始。

### 5.8 诚实标注

- ⚠️ 没跑过的 gate → 标 `⚠️` + 写明"需要在 X 环境跑"
- ❌ 失败的 gate → 标 `❌` + 写明根因 + 修复 PR 编号
- 不要"UNCONDITIONAL PASS"虚标(M10 PR4c 教训)
- `committed but not verified` ≠ `working`

---

## 6. 文件索引(完整 `docs/m11/`)

| 文件 | 角色 | 行数 |
|------|------|------|
| `m11-spec.md` | 顶层 spec,4 PR 总览 + 决策基线 | 17.7K |
| `m11-pr1-dify-fork.md` | Dify fork 5 项改动 + 行级 patch | 17.3K |
| `m11-pr2-schema.md` | Alembic 迁移 + DDL | 17.7K |
| `m11-pr2-schema.md.alembic-original` | 原始 alembic 草稿(留底) | 7.3K |
| `m11-pr3-register-flow.md` | `/api/v1/tenants/register` + 事务/重试 | 18.2K |
| `m11-pr4-frontend-routing.md` | 前端 /signup + M3/M6/M7 路由层 | 10.0K |
| `m11-test-plan.md` | 测试矩阵 | 7.0K |
| `m11-rollback-strategy.md` | 回滚 + Dify 升级 playbook | 7.0K |
| `前端相关问题-第二块-B端租户隔离.md` | 立项前问题梳理 + 决策日志 | 24.8K |
| `M11-CLOSURE.md`(**本文件**) | 系列收口 + 跨会话方法论 | ~6K |

**新会话 first reads**(按顺序):
1. 本文件 `M11-CLOSURE.md` — 顶层收口 + 方法论
2. `前端相关问题-第二块-B端租户隔离.md` — 立项前问题梳理(看阶段 0-2 怎么做的)
3. `m11-spec.md` — 主 spec(看阶段 3 怎么写的)
4. 4 个 PR spec — 看阶段 4 怎么落的
5. 阶段 5 验证证据 = `git log` + 必要时复跑 Playwright MCP

---

## 7. 决策日志全文(从 B端 doc §5 摘出,留底)

### 决策 1 (P0-1) ✅ — Dify 端 workspace 创建走 A 路径

**决策**:Fork Dify 源码,新加 `POST /console/api/admin/workspaces` endpoint(basjoo admin service account 调)。

**对架构的约束**:
- Dify fork 是 v1 长期资产,必须建分支维护,**不** cherry-pick 到 Dify upstream
- 冻结期 fork 不需要 rebase,可全力做 basjoo 侧
- 升级时刻按 5 条 checklist 验证新 endpoint 与 Dify 新版本兼容,失败则阻断升级
- basjoo `.env` 加 `DIFY_TENANT_PROVISION_ENABLED=true` 开关,未就绪时 `503`
- Dify fork 改动收敛到 5 项(原 6 项,决策 2 砍掉 reset-password),约 +205 行 Python

### 决策 2 (P1-2) ✅ — A1 方案,owner 不登 Dify Console

**决策**:B 端 owner **不**登 Dify Web Console。basjoo 一次性展示随机密码(30s mask),basjoo DB 不持久化。

**对架构的约束**:
- Dify fork 砍 `POST /admin/accounts/{id}/reset-password` endpoint
- basjoo `/tenants/register` 响应加 `initial_dify_password` 字段(只返一次)
- basjoo 前端注册成功页必须做"30s 强制 mask"modal
- Dify Account 字段 `password_salt` 是 Dify 内部 bcrypt salt,basjoo 拿不到明文 hash 反推 → 设计上就只能一次性回传

### 决策 3 (P2-2) ✅ — 成员邀请 v1 不实现,无期限延后

**决策**:v1 完全不实现,每个 workspace 只有 1 个 owner。

**对架构的约束**:
- `AdminUser.role` 仍预留 `tenant_admin` / `tenant_member`,v1 只创建 `super_admin` / `tenant_owner`
- 无成员管理 UI,settings 页只展示"成员管理即将推出"
- 未来补这块只是 basjoo 前/后端 + UI 工作,不依赖 Dify 侧新功能

### 决策 4 (实施期) — tenant_owner = workspace 全权

**决策**:`tenant_owner` 在自家 workspace 范围等同 `super_admin`;跨 workspace 仍只 `super_admin`。

**对架构的约束**:
- `RequireAuth.tsx` / `auth.py` 3 个 `require_*` 鉴权门 + 7 处硬编码 `role == "super_admin"` 全部接 `is_workspace_owner()` helper
- `require_tenant_access` 仍只 `super_admin`(跨租户 = 平台方)
- `update_admin_user` 的 super_admin demotion 逻辑保持 super_admin-specific

### 决策 5 (实施期) — Plan B 基线保持

**决策**:basjoo 创建 agent 时**不调 Dify 4 步**(`dify_app_id=NULL`,`dify_publish_status='draft'`)。

**对架构的约束**:
- 切换到 Plan A 之前,basjoo core = workspace-level 隔离,Dify app 创建是 M11+ P0-A
- `前端相关问题.md`(第一块)描述的"Dify 后台空 apps"是预期行为,**不**是 bug
- `dify_app_id=NULL` 状态下,任何依赖 Dify 的功能(widget chat / 配置同步)需要先 P0-A 切回

---

## 8. 一句话给新会话的指令

> **接手新问题时**:看阶段 0-2 在 `前端相关问题-第二块-B端租户隔离.md` 怎么做的;看阶段 3-5 在 `m11-spec.md` + 4 个 PR spec 怎么做的;看本文件 §5 知道下一步该出什么产物。**别从零开始**。

---

## 9. 修订记录

| 版本 | 日期 | 改动 | commit |
|------|------|------|--------|
| v1.0 | 2026-06-17 | 初稿,M11 PR1-PR4 收口 + 方法论 | (本文件 commit) |
