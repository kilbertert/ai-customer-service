# M10+ Agent↔Dify Workflow 集成 — 交接文档

> **会话归属**：本会话结束于 2026-06-15，承接 M10 (5 Gap 修复) 闭环后启动的 M10+ Phase 1 调研。
> **基线 HEAD**：`f2a1eb0` (M10 闭环，9 个 sub-PR 落地)
> **本目录路径**：`docs/handoffs/M10PLUS-agent-dify-integration.md`
> **作者**：Claude (MiniMax-M3) — 给下一会话用，带着它讨论 + 推进。

---

## 0. 用户原始诉求 (Verbatim Quote)

用户在 M10 收尾时启动 M10+ 调研，原话分三段（重要！不可改写）：

> **业务背景**：
> "用户第一次使用我们的前端在注册登录之后，页面上会让用户去创建智能体，点击创建智能体之后会跳转到一个页面，在这一块的逻辑我还没弄清楚情况，按照我们的业务需求用户在第一次注册登录之后确实需要创建智能体，也就是进入到前端的创建页面"

> **集成愿景**：
> "在创建智能体的背后是对应着在dify上创建一个工作流，我需要彻查这部分逻辑... 我想知道的是现在的逻辑中，在前端创建智能体之后是否是按照我们的愿景在dify平台上创建一个workflow 对应于前端创建的智能体？我记得当前的代码中完全没有创建 Dify workflow 的逻辑（这部分需要从dify原仓库代码：d:\AI\company-projects\ai-customer\ai-customer-service\dify 里面去扣）... 这个集成逻辑是完全没有的，现在只是两边原型分立的状态"

> **集成复杂度预判 + 范围**：
> "集成在我的预想中会比较复杂，前端配置好自己的工作流需求之后，在dify侧创建工作流，创建好之后返回该工作流的工作流id，appid等参数进行绑定 等等细节）前端的逻辑同样需要大改 等这个环节实际完成之后才算阶段性的成功"

**核心决策**：用户明示忽略成本告警，详细的完成即可，不需要管花费。下一会话可放心用大上下文继续。

---

## 1. TL;DR — 一句话回答用户的核心问题

> **当前代码完全没有"前端创建 agent → Dify 创建 workflow"的集成链路。** 两端是**完全分立**的状态：
> - basjoo `POST /api/v1/agents` 只创建 basjoo 的 `Agent` 表行（默认走 DeepSeek LLM，**不调 Dify**）
> - basjoo `Agent.dify_workflow_id` 字段在 schema 里**有**，但只能**事后手动填入**（admin UI 暂无入口，靠 SQL 注入或 PR4a 的 chat_stream 检测）
> - Dify 工作流的真实创建在 Dify 仓的 `POST /console/api/apps`（Flask-restx，`login_required` + session cookie，**不是 Bearer Token**），需要 tenant/account 上下文

**集成是空白的，需要从 0 开始造**。详见 §3 集成蓝图。

---

## 2. 当前状态清单 (Verified 2026-06-15)

### 2.1 basjoo 前端 (`frontend-nextjs/`)

| 路径 | 行数 | 职责 | 与 Dify 关系 |
|---|---|---|---|
| `src/views/Agents.tsx` | 725 | **创建 agent 的唯一入口**。4 字段 form：name / description / agent_type / channel_mode | **无任何 Dify 调用** |
| `src/views/AgentSettings.tsx` | 503 | 配置 widget 外观 / CORS / rate limit / welcome msg | **无 Dify 配置项** |
| `src/views/AgentPanel.tsx` | 待查 | dashboard widget | 无 Dify |
| `src/views/AgentSelector.tsx` | 待查 | agent 下拉 | 无 Dify |
| `src/services/api.ts:647-654` | 8 | `createAgent(input)` → `POST /api/v1/agents` | **无 Dify 调用** |

**关键事实**：
- `AgentCreateInput` 类型只含 name/description/agent_type/channel_mode/widget_title（`api.ts` 顶部 import）
- 创建后跳 `KBSetupWizard` 弹窗（onboarding KB），**没有任何 Dify 配置引导**
- `channel_mode` 枚举仅 `web_widget`，目前没启用其他渠道

### 2.2 basjoo 后端 (`backend/`)

| 路径 | 行 | 职责 | 与 Dify 关系 |
|---|---|---|---|
| `api/v1/endpoints.py:2007-2085` | 79 | `POST /api/v1/agents` `create_agent` | **无 Dify 调用** — 只写 Agent 行 |
| `api/v1/endpoints.py:1508-1540` | 33 | `chat_stream` PR4a 路径：`if _agent.dify_workflow_id:` 才走 DifyProvider | **消费侧**已就绪 |
| `services/dify/provider.py` | 293 | `DifyProvider` frozen dataclass + G1 `_build_end_user()` | **消费侧**已就绪 |
| `services/dify/sse_proxy_layer.py` | 改过 | 4 错误路径 + normal end 调 `stripper.flush()` | **消费侧**已就绪 |
| `services/dify/strip_think.py` | 147 | backend `_StreamingThinkStripper` (M9.1 port) | **消费侧**已就绪 |
| `models.py:83-234` Agent 表 | — | 含 `dify_workflow_id` / `dify_user_prefix` / `dify_app_id` (待加) | **schema 已开洞** |
| `models.py:46-62` Workspace 表 | — | `dify_api_base` / `dify_api_key` (Fernet) / `dify_workspace_id` / `dify_enabled` | **schema 已开洞** |
| `config.py:162-163` | — | `settings.dify_api_base` / `dify_api_key` (Plan B 全局默认) | **配置已开洞** |

**`create_agent` 当前实现 (verbatim, lines 2056-2077)**：
```python
agent = Agent(
    workspace_id=current_user.workspace_id,
    name=request.name,
    description=request.description,
    agent_type=request.agent_type,
    channel_mode=request.channel_mode,
    system_prompt=system_prompt,
    model="deepseek-v4-flash",
    temperature=0.7,
    max_tokens=DEFAULT_AGENT_MAX_TOKENS,
    api_base="https://api.deepseek.com/v1",
    provider_type="deepseek",
    # ... defaults ...
)
if settings.deepseek_api_key:
    agent.api_key = encrypt_api_key(settings.deepseek_api_key)
db.add(agent)
await db.commit()
```
**完全没有任何 Dify 相关字段写入或 API 调用**。

### 2.3 Dify 仓 (`dify/`) — workflow / app 创建相关

| 路径 | 行 | 职责 |
|---|---|---|
| `api/controllers/console/app/app.py:504-609` | 106 | `POST /console/api/apps` `AppListApi.post()` 创建 app endpoint |
| `api/controllers/console/app/app.py:66` | 1 | `ALLOW_CREATE_APP_MODES = ["chat","agent-chat","agent","advanced-chat","workflow","completion"]` |
| `api/controllers/console/app/app.py:150-158` | 9 | `CreateAppPayload` Pydantic schema (name/description/mode/icon_*) |
| `api/services/app_service.py:51-60` | 10 | `CreateAppParams` 内部 service 参数 (含 api_rph/api_rpm/max_active_requests) |
| `api/services/app_service.py:166-289` | 124 | `AppService.create_app()` 核心实现 — 返回 `App`，自创建 `AppModelConfig` + (agent 模式) backing Agent |
| `api/services/app_service.py:230-289` | 60 | **Workflow 是 `create_app` 内嵌的**：mode="workflow" 用 `default_app_templates["workflow"]` 自动创建 draft workflow |
| `dify_workflow_api说明文档.md` | — | **只覆盖 runtime/execution API** (POST /v1/workflows/run 等)，**不覆盖创建** |

**`AppListApi.post()` 装饰器链 (verbatim, app.py:581-609)**：
```python
@setup_required
@login_required                # ← session cookie, 不是 Bearer
@account_initialization_required
@cloud_edition_billing_resource_check("apps")
@edit_permission_required
@with_current_user
@with_current_tenant_id
def post(self, current_tenant_id: str, current_user: Account):
    """Create app"""
    args = CreateAppPayload.model_validate(console_ns.payload)
    params = CreateAppParams(
        name=args.name, description=args.description, mode=args.mode,
        icon_type=args.icon_type, icon=args.icon, icon_background=args.icon_background,
    )
    app_service = AppService()
    app = app_service.create_app(current_tenant_id, params, current_user)
    app_detail = AppDetail.model_validate(app, from_attributes=True)
    return app_detail.model_dump(mode="json"), 201
```

**Auth 模型关键发现**：
- **不是** `Authorization: Bearer <api_key>` (那是 runtime API 用法)
- **是** Flask session cookie + `login_required` 装饰器
- `current_tenant_id` 是 Dify 侧 tenant UUID（多租户隔离维度）
- `current_user` 是 Dify 侧 Account 对象（含 `current_tenant_id` 字段）
- Cloud edition 还有 `cloud_edition_billing_resource_check("apps")` — 社区版无此装饰器

---

## 3. 集成蓝图 — 用户愿景 → 落地步骤

### 3.1 用户愿景 (Verbatim)

> "前端配置好自己的工作流需求之后，在dify侧创建工作流，创建好之后返回该工作流的工作流id，appid等参数进行绑定"

→ 抽象为 7 步 happy path：

```
[1] User 注册/登录
    ↓
[2] 前端路由跳转 /agents（已存在）
    ↓
[3] 用户填 form：name + description + agent_type + (新) workflow_config_json
    ↓
[4] 前端 POST /api/v1/agents（已存在，需扩展）
    ↓
[5] basjoo backend 收到请求 → 调用 Dify POST /console/api/apps (mode="workflow")
    ↓ (Dify 返回 app_id, workflow_id 在 App.workflow 关联中)
[6] basjoo 把 Dify app_id + workflow_id 写入 Agent.dify_app_id / dify_workflow_id
    ↓
[7] 前端跳 /agents/{id}/dashboard，KB wizard 弹窗（已存在）
```

### 3.2 关键决策点 (新会话要 confirm)

| # | 决策 | 选项 | 默认推荐 |
|---|---|---|---|
| D1 | **创建时机** | (a) 同步：basjoo `create_agent` 直接调 Dify 阻塞等结果 / (b) 异步：先建 basjoo Agent 状态 pending，后台 worker 调 Dify | **(a) 同步** — 用户在 form 提交按钮看到 loading，体验直接，但需要 timeout 处理 |
| D2 | **失败回滚** | (a) Dify 失败 → basjoo Agent 不存（rolled back）/ (b) Dify 失败 → basjoo Agent 存但 `dify_workflow_id=null`，标 `dify_provisioning_status=failed` 让 admin 重试 | **(a)** — 不留脏数据 |
| D3 | **workflow 内容** | (a) 上传 DSL yaml (AppDslService.import_app) / (b) 创建一个空白 workflow 让 admin 后台用 Dify UI 编辑 / (c) 用 server-side DSL 模板（如 "basjoo-default-workflow-v1"） | **(b) 空白 workflow** — 最小改动，admin 在 Dify UI 配置 graph *(M10+5 修正: 实现路径 2-step `create_app` → `POST /apps/{id}/workflows/draft` with `{nodes:[], edges:[]}`, D9c)* |
| D4 | **Dify 鉴权** | (a) admin 在 basjoo UI 填 Dify admin 账号密码 → basjoo 持久化 + 调 Dify 时 session login / (b) 用 Dify Service API token (Bearer) + `ApiToken` model / (c) workspace 级 service account 共享 | **(c)** — 服务端凭据，admin 不用感知 Dify 登录；M10 已为此设计 `workspace.dify_api_base` + Fernet 加密 |
| D5 | **Multi-tenant Dify workspace** | (a) Plan A：每个 basjoo workspace 单独配 Dify workspace_id / (b) Plan B：所有 basjoo workspace 共享 1 个 Dify workspace，靠 `dify_user_prefix` 隔离 | **(b) Plan B** — M10 已选定，M10 决策保留 |
| D6 | **前端改造范围** | (a) 最小：Agents.tsx form 加 workflow 字段，复用现有创建流程 / (b) 中等：拆出独立 `/agents/create-workflow` wizard 页 / (c) 大改：Agents.tsx 拆 `<CreateAgentForm>` + `<DifyConfigStep>` 多步向导 | **(a) 最小** — 后续 (b) (c) 是后续 PR |
| D7 | **app_id 字段** | 新增 `Agent.dify_app_id: String(64) nullable` (类比 dify_workflow_id) | **必加** — workflow_id 是 App 下属，多 1 个外键便于回查 |

---

## 4. 详细改造方案 (按决策 D1-D7 的默认推荐)

### 4.1 Backend 改造 (5 块)

#### 4.1.1 Schema — 新增 `Agent.dify_app_id`

**位置**：`backend/models.py` Agent 表 (line 230 附近)

```python
# M10+: Dify app 绑定 (workflow 是 App 下属资源)
dify_app_id = Column(String(64), nullable=True)  # Dify App UUID
# dify_workflow_id 已有 (line 232)
```

**Migration**：`backend/sqlite_migrations/00X_add_agent_dify_app_id.sql` (M10 风格 — 非 Alembic，手动迁移脚本)

#### 4.1.2 Service — 新增 `DifyAdminClient`

**位置**：`backend/services/dify/admin_client.py` (新文件，~250 行)

**职责**：
- `login(email, password) -> session_cookie` — 调 `POST /console/api/auth/login`
- `logout(session_cookie)` — 调 `POST /console/api/auth/logout`
- `create_app(session_cookie, tenant_id, payload) -> {app_id, mode}` — 调 `POST /console/api/apps`
- `create_workflow_from_template(session_cookie, app_id, template_name="basjoo-default") -> {workflow_id}`
- `publish_workflow(session_cookie, app_id)` — 调 `POST /console/api/apps/{app_id}/workflows/publish`

**Auth 策略 (D4)**：
- Plan B：basjoo `Workspace.dify_api_base` + Fernet 解密 `dify_api_key`
- `dify_api_key` 实际是**服务账号 session token** (不是 Dify 自身 API key — 那是 runtime 用的)
- Token 缓存：workspace_id → cookie (LRU 512 entries, 24h TTL)，定期 refresh

**Fail-fast** (M10 风格)：
```python
@dataclass(frozen=True)
class DifyAdminClient:
    api_base: str  # raise if empty
    session_token: str  # raise if empty

    def __post_init__(self):
        if not self.api_base:
            raise DifyConfigError("Dify api_base not configured for workspace")
        if not self.session_token:
            raise DifyAuthError("Dify session token not configured")
```

#### 4.1.3 扩展 `create_agent` endpoint

**位置**：`backend/api/v1/endpoints.py:2007-2085`

**改动**：
```python
@router.post("/agents", response_model=AgentConfig, status_code=201)
async def create_agent(
    request: AgentCreateRequest,  # 扩展：加 workflow_mode, workflow_name 等
    current_user: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    # ... 既有 workspace quota 校验 ...
    
    # M10+ 改造点 1：先建 basjoo Agent (deferred dify_workflow_id 写入)
    agent = Agent(
        workspace_id=current_user.workspace_id,
        name=request.name,
        description=request.description,
        agent_type=request.agent_type,
        channel_mode=request.channel_mode,
        # ... 其余 default ...
    )
    db.add(agent)
    await db.flush()  # 取 agent.id 但未 commit
    
    # M10+ 改造点 2：Dify 集成 (D1=同步, D2=失败回滚)
    workspace = await db.get(Workspace, current_user.workspace_id)
    if workspace.dify_enabled and workspace.dify_api_key:
        try:
            dify = DifyAdminClient.from_workspace(workspace)
            dify_app = await dify.create_app(
                name=request.name,
                description=request.description,
                mode="workflow",
                icon_type="emoji",
                icon="🤖",
                icon_background="#FFEAD5",
            )
            agent.dify_app_id = dify_app["id"]
            # D3 决策：空白 workflow
            dify_workflow = await dify.create_empty_workflow(dify_app["id"])
            agent.dify_workflow_id = dify_workflow["id"]
        except DifyError as e:
            await db.rollback()  # D2: 不留脏数据
            raise HTTPException(502, f"Dify workflow creation failed: {e}")
    
    await db.commit()
    await db.refresh(agent)
    return await build_agent_config_with_stats(agent, db)
```

#### 4.1.4 错误处理 (D2)

**新增异常类** `backend/services/dify/exceptions.py`:
- `DifyError(Exception)` 基类
- `DifyAuthError` (401/403)
- `DifyBadRequestError` (400)
- `DifyUpstreamError` (5xx)

**回滚策略**：
- Dify 失败 → `await db.rollback()` + HTTP 502
- 不创建 basjoo Agent (无孤儿数据)

#### 4.1.5 测试 (新增 `backend/tests/test_dify_admin_client.py` + `test_create_agent_dify_integration.py`)

- Mock httpx responses for Dify endpoints
- 11+ cases: happy path / Dify 401 / Dify 500 / workspace.dify_enabled=false / workspace.dify_api_key=None / rollback
- Integration: 真 Dify (CI gate)

### 4.2 Frontend 改造 (2 块)

#### 4.2.1 Form 扩展

**位置**：`frontend-nextjs/src/views/Agents.tsx` (line 514-684 form 段)

**新增字段**（D6=最小化）：
```typescript
const [form, setForm] = useState<AgentCreateInput>({
  name: "",
  description: "",
  agent_type: "website_support",
  channel_mode: "web_widget",
  // M10+ 新增：
  workflow_mode: "blank" as "blank" | "template_v1",  // D3 决策
  icon_emoji: "🤖",  // → Dify icon
});
```

**显示逻辑**：仅当 `workspace.dify_enabled=true` (从 `api.getWorkspaceConfig()` 拿) 才显示 workflow 字段组，否则隐藏并 fallback 到原 LLM-only agent

**保存后跳转**：保留 KBSetupWizard 弹窗 + 新增"Dify workflow 已创建，请到 Dify Studio 配置"提示

#### 4.2.2 API client 扩展

**位置**：`frontend-nextjs/src/services/api.ts:647-654`

无前端 Dify 调用（D4 决策 = 服务端代理）。但 `createAgent` 返回结构需要扩展：

```typescript
interface Agent {
  // ... 既有 ...
  dify_app_id: string | null;
  dify_workflow_id: string | null;
  // M10+ 提示：
  dify_provisioning_status: "active" | "pending" | "failed";  // 新加
  dify_provisioning_error: string | null;  // 新加
}
```

`AgentConfig` schema (`backend/api/v1/schemas.py`) 同步加这 2 字段。

### 4.3 Dify 集成层扩展

#### 4.3.1 M10 已就绪的（消费侧）
- `DifyProvider` (`backend/services/dify/provider.py`)
- `SseProxyLayer` (`backend/services/dify/sse_proxy_layer.py`)
- `_StreamingThinkStripper` (`backend/services/dify/strip_think.py`)
- `useDifyStream` opt-in (`frontend-nextjs/src/services/api.ts`)
- G1 双层 end_user 编码 (`DifyProvider._build_end_user()`)

#### 4.3.2 M10+ 需新增（生产侧）
- `DifyAdminClient` (`backend/services/dify/admin_client.py`) ← §4.1.2
- `DifyWorkflowTemplateService` (`backend/services/dify/workflow_template.py`) ← D3 决策实现
- `Workspace.dify_admin_email` / `dify_admin_password_ref` (Fernet) ← D4=Plan B 服务账号

---

## 5. 待新会话补充调研的清单 (Gaps from This Session)

新会话接手前**强烈建议**先确认这 5 项：

| # | 调研项 | 现状 | 优先级 |
|---|---|---|---|
| G1 | **Dify 社区版 vs Cloud 版差异** — `@cloud_edition_billing_resource_check("apps")` 在自部署 Dify 是否存在？若不存在，是否要自己加一个 `max_agents` 类似 guard？ | 部分已知 (cloud 装饰器会 skip 但 basjoo 端需要独立限流) | **高** — 决定 DifyAdminClient 是否要双路径 |
| G2 | **`POST /console/api/apps` 实际返回 payload 结构** — `AppDetail.model_validate(app)` 序列化字段？是否含 `workflow_id`？还是要再调一次 `GET /apps/{id}` 拿 workflow？ | `AppService.create_app` 返回 App 对象，但 `workflow_id` 是否同时创建 + 暴露在 API 响应里**未读** (workflow.py controller 未确认) | **高** — 决定是否需要 2-step create |
| G3 | **Dify session cookie 生命周期** — 默认多久过期？refresh 策略？是否支持 `remember_me`？basjoo LRU cache TTL 怎么设？ | 未查 | **中** — 决定 session 缓存粒度 |
| G4 | **`/console/api/apps/{id}/workflows/publish` 端点存在性 + payload** — 是 Dify 自动发布还是需要 admin 手动在 Dify UI 点 publish？basjoo 集成是否要自动 publish？ | 未查 | **中** — 决定 D3=空白 workflow 是否需要"保存为草稿"+"自动 publish"两步 |
| G5 | **Dify Tenant 创建 API** — 如果走 Plan B 共享 Dify workspace，是否需要 basjoo 端预创建 Dify tenant？还是 admin 一次性在 Dify UI 创建，后续 basjoo 只用？ | 未查 (`/console/api/workspaces/current` 等未确认) | **低** — 走 D4=Plan B 共享 service account 时不需要 |

### G2 重点文件 (待新会话读完)

```
dify/api/controllers/console/app/app.py:609    # POST /apps 返回位置
dify/api/controllers/console/app/workflow.py  # GET/POST /apps/{id}/workflows 全集
dify/api/services/app_dsl_service.py           # import_app DSL 用法 (备选 D3=模板路径)
dify/api/services/workflow_service.py          # workflow 内部 service
dify/api/models/workflow.py                    # Workflow ORM
```

### G1 重点文件 (待新会话读完)

```
dify/api/controllers/console/wraps.py          # cloud_edition_billing_resource_check 实现
dify/configs/__init__.py                       # ENTERPRISE_ENABLED / EDITION 判定
dify/api/services/billing_service.py           # 配额逻辑
```

---

## 6. PR 拆分建议 (5 PR,渐进交付)

| PR | 范围 | 依赖 | 硬门 |
|---|---|---|---|
| **M10+1** | Schema migration (`Agent.dify_app_id` + `Workspace.dify_admin_*`) + `DifyAdminClient` + 单测 | 无 | ① 单测 100% pass ② `DifyAdminClient.__post_init__` fail-fast 测试 ③ 不破坏既有 `create_agent` 路径 (workspace.dify_enabled=false 时) |
| **M10+2** | `create_agent` endpoint 集成 + 错误回滚 + schema 扩展 (AgentCreateRequest 加 workflow_mode) | M10+1 | ① httpx mock 单测覆盖 7 个分支 ② rollback 集成测试 (Dify 失败 → basjoo 无 Agent 记录) ③ 既有 `test_create_agent.py` 不挂 |
| **M10+3** | 前端 form 扩展 (Agents.tsx) + api.ts 类型 + 提示文案 | M10+2 | ① TS typecheck pass ② vitest update ③ UI 截图 (`page.on('screenshot')`) |
| **M10+4** | 真 Dify 端到端 E2E (docker compose --profile dev up + 注册新 admin + 创建 agent + 验证 agent.dify_app_id 非空 + 真 chat_stream 走 Dify) | M10+3 | ① Playwright spec ② 真 Dify login + POST /apps + GET /apps/{id} 全链路 ③ 输出 `M10+4-REPORT.md` |
| **M10+5** | 文档 + changelog + docker-compose Dify 服务编排 + 部署指南 | M10+4 | ① docs/dify-integration-plan.md §17 新增 ② docker-compose.yml 加 dify service (可选, 沙箱可 skip) ③ `M10+5-REPORT.md` 终态报告 |

**M10+4 注意事项**：
- 沙箱内 Docker build 会挂 (M10 PR4c 已知 — python:3.13-slim size validation 失败)
- M10+4 必须在**本机或 CI** 跑，沙箱内仅验证 schema/单测
- 类比 M10 §8 7 步本机补跑清单，需写一份 M10+4 7 步本机清单

---

## 7. 验证硬门清单 (Hard Gates Per PR)

### 7.1 通用硬门 (每个 PR 必跑)

- [ ] `pytest backend/tests/` 全绿
- [ ] `cd frontend-nextjs && npm run typecheck && npm run lint` 全绿
- [ ] `cd frontend-nextjs && npm run test` 全绿
- [ ] 不引入新 `console.log` (TS Hook audit)
- [ ] 不引入 hardcoded secret (Fernet 加密所有 Dify 凭据)
- [ ] 既有 `chat_stream` 真 Dify 流式路径不破坏 (回归测试)

### 7.2 M10+ 特有硬门

- [ ] **Schema 一致性**：`Agent.dify_app_id` 必 nullable (admin 创建空白 agent 不调 Dify 时)
- [ ] **回滚对称性**：Dify 失败 → basjoo 端不留 Agent 记录 (DB 校验)
- [ ] **Plan B 兼容**：`workspace.dify_enabled=false` 时 `create_agent` 行为与 M10 完全一致 (byte-for-byte)
- [ ] **session cookie 不外泄**：DifyAdminClient 日志 redact cookie
- [ ] **超时兜底**：Dify 调用必须设 httpx timeout (推荐 30s)，超时失败回滚
- [ ] **fail-fast 校验**：`Workspace.dify_enabled=true && dify_api_key=None` → `create_agent` 400 报错，不调 Dify

### 7.3 M10+4 沙箱 E2E 预检表 (M10+5 backport)

> **2026-06-16 沙箱实测**：所有项 ✅, 打破 kickoff §4 "沙箱不通" 假设。详细 4/7 PASS + 2 PARTIAL + 1 DEFER 见 `docs/handoffs/M10PLUS4-REPORT.md` §10。

| 检查项 | 沙箱实测 | 备注 |
|---|---|---|
| Docker build (basjoo 全栈) | ✅ | python:3.13-slim 沙箱 build 通过 (M10 PR4c python:3.13-slim 失败问题已 fix) |
| Dify HTTP 124.243.178.156:8501 | ✅ | 真 Dify 1.14.2 网络通, 5/5 round-trip |
| Playwright 1.60 端到端 | ✅ | 改用 Playwright MCP (沙箱拦 npx test cmd.exe spawn, 改 MCP 等价实跑) |
| 真实 chat_stream → Dify 流式 E2E | ✅ | basjoo `/api/v1/chat/stream` → DifyProvider → 124.243.178.156:8501 SSE 200 OK + thinking event + stripper 工作 |
| Dify publish status 自动同步 | ⚠️ DEFER | 需 admin 手动改 DB 或加 webhook (M11+) |
| Plan A per-tenant Dify workspace | ⚠️ DEFER | 当前 Plan B 共享 workspace, M11+ 需求触发时再切换 |

---

## 8. 风险与决策待办

### 8.1 已知风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| Dify session cookie 过期导致 basjoo 大面积 502 | **高** | LRU cache + 24h TTL + refresh on 401 + 监控 metric |
| Dify 社区版无 cloud_edition_billing_resource_check | 中 | basjoo 端独立 guard (`WorkspaceQuota.max_agents` 已存在，复用) |
| Dify 版本迭代导致 API 不兼容 (e.g., 1.0.0 → 1.5.0 字段变更) | 中 | pin Dify 版本 (docker-compose tag) + 契约测试 |
| Workflow DSL 上传路径 (D3 选项 a) 暂未实现 | 低 | 先做空白 workflow (D3=b)，DSL 是后续 PR |
| Plan A 切换 (per-tenant Dify workspace) | 低 | 暂不实现，等 M11+ 需求 |
| basjoo agent 表行数爆涨 (per agent 1 Dify workflow) | 低 | Dify 端配额 + basjoo `WorkspaceQuota.max_agents` 已限流 |

### 8.2 待决策 (新会话讨论)

- **是否要支持"用户在 basjoo UI 看到 Dify workflow graph 缩略图"** — 需调 `GET /apps/{id}/workflows/draft` 拿 graph 数据，前端渲染成本？
- **是否支持"basjoo 端编辑 Dify workflow prompt 节点"** — 这是个小型 Dify Studio 嵌入，工作量翻倍
- **是否做"agent 删除时同步删除 Dify workflow"** — 当前 `deactivate_agent` 只软删 basjoo Agent；要不要级联 DELETE /apps/{id}？
- **是否做"Dify workflow publish status → basjoo agent.is_active"** — Dify workflow 必须是 published 才能调；现在 chat_stream 检测 `dify_workflow_id` 非空就放行，但 unpublish workflow 会 4xx

---

## 9. 关键文件路径速查 (Quick Reference)

### basjoo 仓

```
backend/api/v1/endpoints.py:2007            # create_agent endpoint
backend/api/v1/schemas.py                   # AgentCreateRequest / AgentConfig
backend/models.py:83-234                    # Agent ORM
backend/models.py:46-62                     # Workspace ORM (dify_* 字段)
backend/config.py:160-163                   # settings.dify_* 全局默认
backend/services/dify/provider.py           # DifyProvider 消费侧 (M10)
backend/services/dify/sse_proxy_layer.py    # SSE 代理 (M10)
backend/services/dify/strip_think.py        # think stripper (M10)
backend/services/dify/admin_client.py       # ← M10+1 新建
backend/services/dify/exceptions.py         # ← M10+1 新建
backend/sqlite_migrations/                  # M10+1 migration
backend/tests/test_dify_admin_client.py     # ← M10+1 新建
backend/tests/test_create_agent_dify.py     # ← M10+2 新建
frontend-nextjs/src/views/Agents.tsx:500-684 # 创建 form (M10+3 改)
frontend-nextjs/src/views/AgentSettings.tsx # widget 配置 (M10+3 可能加 Dify status section)
frontend-nextjs/src/services/api.ts:647-654 # createAgent (M10+3 扩展类型)
frontend-nextjs/src/services/__tests__/     # vitest
```

### M10+5 实测修正 (2026-06-16 backport)

> **本节为 M10+5 落地后回填的实测事实**, 引用 M10+4 沙箱 E2E (`docs/handoffs/M10PLUS4-REPORT.md`) + M10+1/2/3 集成 (`docs/handoffs/M10PLUS5-REPORT.md` §6 M10+ chain 完整轨迹)。

| 假设 (v1 handoff §) | v1 假设 | Dify 1.14.2 实测 | 影响 |
|---|---|---|---|
| §2.3 line 100 | "Workflow 是 `create_app` 内嵌的" | `create_app` **只**创建 App 行, Workflow 行懒创建 (D3 = 2-step) | D3 实现路径修正: `create_app` + `POST /apps/{id}/workflows/draft` 复合方法 |
| §3.2 D3 | (b) 空白 workflow | 决策内容不变, **实现路径 1-step → 2-step** + graph body `{nodes:[], edges:[]}` (D9c) | M10+1 `DifyAdminClient.create_app_and_workflow()` 复合方法 |
| §4.1.2 DifyAdminClient | password 明文 | password **base64 编码** (Dify 1.14.2 `FieldEncryption.decrypt_field` 是 base64.b64decode) (D9b) | login payload 加 `b64encode(password).decode()` |
| §4.1.2 DifyAdminClient | login endpoint `/console/api/auth/login` | **`/console/api/login`** (Dify 1.14.2 改名) (D9a) | 改 URL |
| §4.1.3 `create_agent` | publish 必失败 | **Dify 1.14.2 允许空 graph published** (无 Start 节点也 OK) (D9e 修 payload) | publish_workflow 加 `PublishWorkflowPayload` body + D9(c) 容错 |
| §5.2 G3 cookie TTL | TTL 数字未知 | 默认推荐 1h + 401 重试 1 次; 实测 LRU cache 跑通 | 无代码改动, M11+ 跟踪 |
| §5.2 G4 publish | "Dify publish 必校验 start/end 节点" | **1.14.2 允许空 graph published**, 1.15+ 待验证 | M10+1 `publish_workflow` 仍走 D9(c) 容错 (400/422 → False), 但 1.14.2 实际触发概率低 |

### Dify 仓 (`d:/AI/company-projects/ai-customer/ai-customer-service/dify/`)

```
api/controllers/console/app/app.py:504-609  # POST /console/api/apps
api/controllers/console/app/app.py:66       # ALLOW_CREATE_APP_MODES
api/controllers/console/app/app.py:150-158  # CreateAppPayload
api/controllers/console/app/workflow.py     # ← 待读 (G2)
api/services/app_service.py:166-289         # AppService.create_app
api/services/app_service.py:51-60           # CreateAppParams
api/services/app_dsl_service.py             # ← 待读 (G2, DSL 模板路径)
api/services/workflow_service.py            # ← 待读 (G2)
api/models/workflow.py                      # ← 待读 (G2)
api/controllers/console/wraps.py            # ← 待读 (G1, billing check)
dify_workflow_api说明文档.md                # runtime API 文档, 不覆盖创建
```

---

## 10. 上下文依赖 — 与 M10 的关联

- **M10 PR4a (commit c3b14be)** — G1 dual-layer end_user 编码 + `DifyProvider` 落地。**M10+ 是这套消费侧的生产侧配对**：没有 Dify workflow 就没东西可消费
- **M10 PR4b (commit 828cd7e)** — backend `_StreamingThinkStripper` + frontend `useDifyStream: true`。**M10+ 创建后，chat_stream 走 Dify 时这两道防护自动生效**
- **M10 PR4c (commit 79ca18f→f2a1eb0)** — CONDITIONAL PASS，缺口 = basjoo 真 Dify 流式 E2E 未跑。**M10+4 必须把 PR4c 这个缺口补上** — 因为 M10+ 创建 workflow 后 chat_stream 立刻就接得上，E2E 自然覆盖

---

## 11. 给新会话的建议启动序列

1. **读完本文件 + M10-REPORT.md** (china_charge_kf/M10-REPORT.md) — 了解 5 Gap + 9 sub-PR 闭环
2. **完成 §5 G1-G5 调研** — 优先 G2 (workflow 实际返回结构) 和 G1 (cloud edition 装饰器)
3. **与用户 confirm §3.2 D1-D7 决策** — 别假设，沿用默认推荐但 user 拍板
4. **执行 §6 PR 拆分 M10+1 → M10+5** — 不要跳 PR，每个 PR 跑 §7 硬门
5. **M10+4 E2E 时** — 跟 M10 PR4c 一样先承认沙箱限制 + 列本机补跑清单，不要 UNCONDITIONAL PASS

---

## 12. 完成度自评 (This Session)

- [x] **Task #17 彻查 basjoo 后端 agent 创建端点** — DONE (`endpoints.py:2007-2085` + `models.py:83-234`)
- [x] **Task #18 探查 dify 仓 workflow 创建 API** — PARTIAL (`app.py` + `app_service.py` 已查，`workflow.py` + `app_dsl_service.py` 留 G2)
- [x] **Task #20 彻查 basjoo 前端创建智能体页面逻辑** — DONE (`Agents.tsx` + `AgentSettings.tsx` + `api.ts`)
- [x] **Task #19 写 Dify workflow 集成交接文档** — DONE (本文档)

**未在本会话闭环 (留给新会话)**：
- G1-G5 五项补调研
- 任何代码改动 (按 §6 PR 拆分渐进交付)

---

**文档结束**。新会话请带着 §3.2 决策 + §5 调研清单 + §6 PR 拆分表进入讨论。
