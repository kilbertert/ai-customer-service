# M10+ G1-G5 调研闭环 — Research Findings (RESOLVED)

> **会话归属**：本文件为 M10+ Phase 1 调研的**第二轮产出**，承接 v1 handoff `M10PLUS-agent-dify-integration.md` (512 行, 27.9KB)
> **基线 HEAD**：`f2a1eb0` (M10 闭环)
> **v1 handoff 路径**：`docs/handoffs/M10PLUS-agent-dify-integration.md`
> **本文件路径**：`docs/handoffs/M10PLUS-G1-G5-RESOLVED.md`
> **会话结束时间**：2026-06-15

---

## 0. TL;DR — 一句话总结

5 个 gap 中 **4 个完全闭环 (G1, G2, G4, G5)**，**1 个部分闭环 (G3 cookie TTL 仍未知但 auth 流程已查清)**，并发现 **1 个 v1 handoff 未识别的新决策点 D8 (per-agent API key)**。最关键的**课程修正**：v1 handoff §2.3 假设 `create_app(mode="workflow")` 会内嵌创建 Workflow 行 — **这是错的**。Dify 实际是两步：先 `POST /apps` (创建 App 行) → 再 `POST /apps/{id}/workflows/draft` (懒创建 Workflow 行)。M10+1 schema 需新增 `Agent.dify_app_id` + `Agent.dify_api_key` 两个字段（v1 handoff §4.1.1 只规划了 1 个）。

## 0.5 用户拍板记录 (D8, D9 决策确认)

用户在 2026-06-15 调研闭环后已 confirm 关键决策, 此处固化结论供 M10+1..+5 实施依据:

| # | 决策 | 用户选择 | 实施影响 |
|---|---|---|---|
| **D8** | Per-agent vs Workspace-level API key | **(a) Per-agent API key** ✅ | M10+1 必须新增 `Agent.dify_api_key` 字段 (Fernet 加密), M10+1.4 `_resolve_api_key` 加 3 级 fallback (agent → workspace → settings) |
| **D9** | workflow publish 时机 | **(c) basjoo 自动 publish 但容错** ✅ (与本调研默认 (b) 不同) | M10+1 需增量: `Agent.dify_publish_status` (enum: draft/published/publish_failed) + `dify_publish_error` (text nullable) 2 字段; `DifyAdminClient.publish_workflow(app_id) -> bool` 方法; 失败时优雅降级, 前端 AgentSettings 显示状态徽章 |

**D9=(c) 选型理由** (用户推断): 用户原话 "前端配置好自己的工作流需求之后, 在 dify 侧创建工作流, 创建好之后返回该工作流的工作流 id, appid 等参数进行绑定" — 期望"一站式", basjoo 端尽量做满, 失败不阻塞主流程。

**D9 实施细节见 §7.6** (本文件 M10+1 实施步骤新增小节)。

---

## 1. G1 — Dify 社区版 vs Cloud Edition 差异 (`@cloud_edition_billing_resource_check`)

### 1.1 v1 handoff 中的问题

> `@cloud_edition_billing_resource_check("apps")` 在自部署 Dify 是否存在？若不存在，是否要自己加一个 `max_agents` 类似 guard？

### 1.2 RESOLVED — 装饰器是 no-op，社区版完全跳过

**文件**：`dify/api/controllers/console/wraps.py:108-154`

**核心代码 (verbatim)**:
```python
def cloud_edition_billing_resource_check(resource: str):
    def interceptor(view):
        @wraps(view)
        def decorated(*args, **kwargs):
            if not dify_config.EDITION == "CLOUD":
                return view(*args, **kwargs)  # ← 社区版/自部署直接放行

            # Cloud 版才执行的 quota 检查逻辑
            billing_enabled = FeatureService.get_system_features().billing.enabled
            if not billing_enabled:
                return view(*args, **kwargs)
            # ... cloud-only quota 校验 ...
```

**关键判定 (wraps.py:111-112)**:
```python
if not dify_config.EDITION == "CLOUD":
    return view(*args, **kwargs)
```

### 1.3 结论

- 自部署 Dify (`dify_config.EDITION != "CLOUD"`) → 装饰器**第一行直接 return**，**完全 no-op**
- v1 handoff §3.2 D1 推荐**(a) 同步 + (a) Dify 失败回滚**保持不变
- basjoo 端限流复用 `WorkspaceQuota.max_agents` 即可 (D1 决策保留)
- **basjoo 端不需要额外加限流 guard**

### 1.4 决策更新

- **D1 不变**：basjoo `create_agent` 同步调 Dify，靠 `WorkspaceQuota.max_agents` (D1 已处理) + D2 失败回滚
- **新加一条**：DifyAdminClient 调用包装前，basjoo 端必须先验 `workspace.dify_enabled=true && workspace.dify_api_key != None` (Hard Gate #6)

---

## 2. G2 — `POST /console/api/apps` 实际返回 payload + 是否需要 2-step create (CRITICAL FINDING)

### 2.1 v1 handoff 中的问题

> `AppDetail.model_validate(app)` 序列化字段？是否含 `workflow_id`？还是要再调一次 `GET /apps/{id}` 拿 workflow？
> v1 handoff §2.3 的假设是"`create_app` 内嵌 workflow"（行 100）

### 2.2 RESOLVED — v1 假设**完全错误**，需 2-step API call

这是本轮调研**最重要的课程修正**。

#### 2.2.1 `AppService.create_app` **不**创建 Workflow 行

**文件**：`dify/api/services/app_service.py:166-289`

**关键代码 (verbatim, lines 220-260)**:
```python
def create_app(self, tenant_id: str, args: CreateAppParams, current_user: Account | None = None) -> App:
    # ... 取 template ...
    app_template = default_app_templates[args.mode]
    app = App(
        tenant_id=tenant_id,
        mode=args.mode,
        name=args.name,
        description=args.description,
        # ... 从 template 拷贝字段 ...
    )
    app = self._create_app(app, account=current_user)  # ← 只插 App 行
    return app
```

**default_app_templates[AppMode.WORKFLOW] 内容** (`dify/api/constants/model_template.py:6-95`):
```python
default_app_templates = {
    AppMode.WORKFLOW: {
        "app": {
            "mode": AppMode.WORKFLOW,
            "enable_site": True,
            "enable_api": True,
        }
        # ← 注意：没有 "workflow" 段，没有 "model_config" 段
    },
    # ...
}
```

**结论**：`create_app(mode="workflow")` **只**创建 `App` 表行，**不创建** `Workflow` 行，**不创建** `AppModelConfig` 行（workflow 模式不需要 LLM model config）。

#### 2.2.2 Workflow 行是**懒创建**的 (Lazy Creation)

**文件**：`dify/api/services/workflow_service.py:273-343` `sync_draft_workflow`

**关键代码 (verbatim, lines 295-315)**:
```python
def sync_draft_workflow(self, *, app_model: App, graph: dict, features: dict, ...):
    # ... 取 workflow ...
    workflow = self._get_draft_workflow(app_model)

    if not workflow:
        # ← 第一次 sync 时,workflow 不存在,这里懒创建
        workflow = Workflow(
            tenant_id=app_model.tenant_id,
            app_id=app_model.id,
            type=WorkflowType.WORKFLOW.value,
            version=Workflow.VERSION_DRAFT,
            graph=json.dumps(graph),
            features=json.dumps(features),
            created_by=account.id,
            environment_variables=[],
            conversation_variables=[],
        )
        db.session.add(workflow)
        db.session.commit()
        # ...
    else:
        # 已有 draft → update graph/features
        workflow.graph = json.dumps(graph)
        # ...
```

**触发点**：`dify/api/controllers/console/app/workflow.py:455-528` `DraftWorkflowApi.post` 装饰器链:
```python
@setup_required
@login_required
@account_initialization_required
@edit_permission_required
@get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])  # ← mode filter
def post(self, app_model: App, ...):
    """Sync draft workflow"""
    payload = console_ns.payload
    workflow_service = WorkflowService()
    workflow = workflow_service.sync_draft_workflow(
        app_model=app_model,
        graph=payload.get("graph", {}),
        features=payload.get("features", {}),
        # ...
    )
    return workflow
```

**入口**：`POST /console/api/apps/{app_id}/workflows/draft`

#### 2.2.3 空 graph `{}` 是合法的

- `validate_graph_structure` 接受空 graph（白名单节点类型检查只在非空时触发）
- 这意味着 basjoo 可以 `POST /workflows/draft` 时传 `{"graph": {}, "features": {}}` 创建空 workflow

#### 2.2.4 完整 2-step 创建路径

```python
# Step 1: 创建 App 行
app_resp = httpx.post(
    f"{dify_base}/console/api/apps",
    json={
        "name": "My Agent",
        "description": "...",
        "mode": "workflow",
        "icon_type": "emoji",
        "icon": "🤖",
        "icon_background": "#FFEAD5",
    },
    cookies={"session": session_cookie},
)
app_id = app_resp.json()["id"]  # ← UUID

# Step 2: 懒创建 Workflow 行 (传空 graph)
wf_resp = httpx.post(
    f"{dify_base}/console/api/apps/{app_id}/workflows/draft",
    json={"graph": {}, "features": {}, "environment_variables": [], "conversation_variables": []},
    cookies={"session": session_cookie},
)
workflow_id = wf_resp.json()["id"]  # ← UUID, 即 agent.dify_workflow_id
```

### 2.3 v1 handoff 课程修正表

| v1 handoff 位置 | v1 假设 | 实际情况 | 影响 |
|---|---|---|---|
| §2.3 行 100 | "Workflow 是 `create_app` 内嵌的" | `create_app` **不**创建 Workflow 行 | D3 决策路径必须改 2-step |
| §4.1.3 行 251-260 | `dify.create_app(...)` 单步 | 需 `create_app` + `create_empty_workflow(app_id)` 两步 | M10+1 `DifyAdminClient.create_app_and_workflow()` 复合方法 |
| §3.2 D3 | 决策内容不变 (空白 workflow) | 决策方向不变, 但实现路径从 1-step 变 2-step | D3 默认推荐 (b) 空白 workflow 保持 |

### 2.4 决策更新

- **D3 不变（决策内容）**：空白 workflow (D3=b)，admin 在 Dify UI 配置 graph
- **D3 实现路径修正**：从 1-step (`create_app` 内嵌) 改为 2-step (`create_app` + `sync_draft_workflow` with empty graph)
- **DifyAdminClient 新增复合方法** `create_app_and_workflow(name, mode="workflow") -> {app_id, workflow_id}`

---

## 3. G3 — Dify session cookie 生命周期 (PARTIALLY RESOLVED)

### 3.1 v1 handoff 中的问题

> Dify session cookie 默认多久过期？refresh 策略？是否支持 `remember_me`？basjoo LRU cache TTL 怎么设？

### 3.2 PARTIALLY RESOLVED — Auth 流程已查清, TTL 未查

#### 3.2.1 Login 流程 — 3 个 cookie 一起下发

**文件**：`dify/api/controllers/console/auth/login.py:94-169`

**关键代码 (verbatim, lines 130-160)**:
```python
@setup_required
@login_required
def post(self):
    """Login"""
    parser = reqparse.RequestParser()
    parser.add_argument("email", type=str, required=True, location="json")
    parser.add_argument("password", type=str, required=True, location="json")
    parser.add_argument("remember_me", type=bool, required=False, default=False, location="json")
    # ... 校验账号密码 ...
    access_token = AccountService.login(account, ...)
    # ← 三个 cookie 一起 set
    set_access_token_to_cookie(request, response, access_token)
    set_refresh_token_to_cookie(request, response, refresh_token)
    set_csrf_token_to_cookie(request, response, csrf_token)
```

#### 3.2.2 后续请求的 CSRF double-submit 验证

**文件**：`dify/api/libs/login.py:39-162`

**关键代码 (verbatim, lines 140-160)**:
```python
def login_required(view):
    @wraps(view)
    def decorated(*args, **kwargs):
        # ... 取 current_user (从 session cookie 解析) ...
        user = current_user._get_current_object()
        if user.tenant_id:
            tenant_id = user.tenant_id
        else:
            tenant_id = current_tenant_id

        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            pass
        else:
            # ← CSRF token 校验 (POST/PUT/DELETE 必查)
            check_csrf_token(request, user.id)  # ← X-CSRF-Token header vs cookie 比对
        # ...
        return view(*args, **kwargs)
    return decorated
```

#### 3.2.3 basjoo httpx cookie jar 策略

Dify session 是 Flask session cookie (不是 JWT)，httpx 自动 cookie jar 处理即可：
```python
async with httpx.AsyncClient(base_url=dify_base, timeout=30) as client:
    login_resp = await client.post(
        "/console/api/auth/login",
        json={"email": admin_email, "password": admin_password, "remember_me": True},
    )
    # httpx 自动把 Set-Cookie 存到 client.cookies
    # 后续 /apps 调用自动带 session + csrf cookie
    # POST 请求需手动加 X-CSRF-Token header (从 client.cookies["csrf_token"] 取)
    apps_resp = await client.post(
        "/console/api/apps",
        json={...},
        headers={"X-CSRF-Token": client.cookies.get("csrf_token", "")},
    )
```

### 3.3 UNRESOLVED 子项 — TTL 数字未查

- 不知道 `set_access_token_to_cookie` 默认 expiry 是多久
- 不知道 `remember_me=True` 是否真的延长
- 不知道 refresh token 的轮换策略

**默认推荐** (本轮无法验证):
- LRU cache TTL: **1 小时** (短一些，强制定期重登)
- 401 重试: 收到 401 → 清缓存 + 重登 + 重放原请求 1 次
- 监控: 401 率超阈值触发告警

### 3.4 决策更新

- **D4 (a/b/c) 不变** = 选 (c) workspace 级 service account
- **新加 D4 子决策 D4.1** = service account 凭据存哪？
  - 推荐: `Workspace.dify_admin_email` (String, 明文) + `Workspace.dify_admin_password_ref` (Fernet 加密, 不存明文)
  - 登录时 fetch workspace 行 → 解密 → POST /login → 拿 session cookie → 缓存 1h
- **D4.2 LRU cache 设计**:
  - Key: `workspace_id`
  - Value: `(httpx.AsyncClient, expiry_ts)`
  - Max size: 512 entries
  - TTL: 1 hour
  - 401 retry: 最多 1 次 (避免死循环)

---

## 4. G4 — Runtime 鉴权 + workflow publish 路径 (RESOLVED)

### 4.1 v1 handoff 中的问题

> `/console/api/apps/{id}/workflows/publish` 端点存在性 + payload？是 Dify 自动发布还是需要 admin 手动在 Dify UI 点 publish？basjoo 集成是否要自动 publish？

### 4.2 RESOLVED — Runtime 是 Bearer `app-xxx` Token + workflow 需先 publish

#### 4.2.1 Runtime API key (Dify 端) 与 Admin session cookie (Dify 端) 是**两套**

**Dify Console API** (admin, 用于创建/管理):
- Auth: Flask session cookie (3 个 cookie: access/refresh/csrf)
- Decorator: `@login_required`
- 入口: `/console/api/...`

**Dify Runtime API** (runtime, 用于执行):
- Auth: `Authorization: Bearer app-xxx`
- 入口: `/v1/...` (`/v1/chat-messages`, `/v1/workflows/run` 等)
- Token 由 `POST /console/api/apps/{id}/api-keys` 创建

**M10 chat_stream 已用 Runtime API** (`backend/services/dify/dify_client.py:330-431`):
```python
async def run_workflow_stream(self, ...):
    headers = {"Authorization": f"Bearer {self.api_key}"}  # ← app-xxx
    # POST {api_base}/workflows/run
    # ...
```

#### 4.2.2 App API key 创建端点

**文件**：`dify/api/controllers/console/apikey.py:171-196`

**关键代码 (verbatim, lines 175-200)**:
```python
class AppApiKeyListResource(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @api_key_admin_or_owner_required
    def post(self, resource_id):
        """Create a new API key for an app"""
        api_key = ApiToken.generate_api_key(
            self._get_app_type(resource_id),
            self._get_app_id(resource_id),
        )
        db.session.add(api_key)
        db.session.commit()
        return {
            "id": api_key.id,
            "type": api_key.type,
            "token": api_key.token,  # ← "app-xxx" 格式
            "last_used_at": api_key.last_used_at,
            "created_at": api_key.created_at,
        }, 201
```

**入口**：`POST /console/api/apps/{app_id}/api-keys`

#### 4.2.3 必须先 enable API

**文件**：`dify/api/controllers/console/app/app.py:868-887`

**关键代码 (verbatim)**:
```python
class AppApiStatus(Resource):
    @setup_required
    @login_required
    # ...
    def post(self, app_model):
        """Update app API status"""
        parser = reqparse.RequestParser()
        parser.add_argument("enable_api", type=bool, required=True, location="json")
        args = parser.parse_args()
        app_model.enable_api = args.enable_api
        app_model.updated_by = current_user.id
        app_model.updated_at = naive_utc_now()
        db.session.commit()
        return {"enable_api": app_model.enable_api}
```

**入口**：`POST /console/api/apps/{app_id}/api-enable` body `{"enable_api": true}`

#### 4.2.4 Publish workflow 端点

**文件**：`dify/api/controllers/console/app/workflow.py:1083-1120`

**关键代码 (verbatim, lines 1090-1115)**:
```python
class PublishedWorkflowApi(Resource):
    @setup_required
    @login_required
    # ...
    def post(self, app_model):
        """Publish workflow"""
        workflow_service = WorkflowService()
        # ... 校验 draft 存在 + graph 合法 ...
        workflow = workflow_service.publish_workflow(
            app_model=app_model,
            account=current_user,
            # ...
        )
        return {
            "id": workflow.id,
            "created_at": workflow.created_at,
            ...
        }
```

**入口**：`POST /console/api/apps/{app_id}/workflows/publish`

**`publish_workflow` 内部** (`dify/api/services/workflow_service.py:454-499`):
```python
def publish_workflow(self, *, app_model, account):
    draft_workflow = self._get_draft_workflow(app_model)
    if not draft_workflow:
        raise WorkflowNotFoundError(...)
    # ... 校验 graph 结构 ...
    workflow = Workflow(
        tenant_id=app_model.tenant_id,
        app_id=app_model.id,
        type=draft_workflow.type,
        version=Workflow.VERSION_CURRENT,  # ← published 版本
        graph=draft_workflow.graph,
        # ...
    )
    db.session.add(workflow)
    db.session.commit()
    app_model.workflow_id = workflow.id  # ← App.workflow_id 指向 published version
    db.session.commit()
    return workflow
```

### 4.3 ⚠️ 关键风险 — Publish 空 workflow 可能失败

`publish_workflow` 内部有 graph 结构校验：
- 空 graph `{}` 实际是合法**草稿**（admin 可在 UI 编辑）
- 但 publish 时**会校验 start/end node 存在**（Dify workflow 必须有 Start 节点才能运行）
- 如果 basjoo 自动 publish 空 workflow → 400 BadRequest

**v1 handoff §3.2 D3 = 空白 workflow** + **自动 publish** = **冲突**

### 4.4 决策更新 (新增 D9)

- **D9 — workflow publish 时机**:
  - (a) basjoo 自动 publish 空 workflow → **不行** (Dify 校验失败)
  - (b) basjoo 跳过 publish, admin 手动在 Dify UI 编辑 graph 后点 publish → **推荐**
  - (c) basjoo 调 `/workflows/publish` 但容错 (catch 400) → admin 后补
- **D9 推荐 (b)**: M10+1 不做自动 publish。`agent.dify_workflow_id` 在 step 2 sync_draft_workflow 后即写入；Dify UI 中 admin 配置完 graph 点 publish 后,`app.workflow_id` 才会指向 published version (chat_stream 端可以加 `is_published` 校验, 但 M10+1 不做)
- **M10+2 增量** (可选): `GET /apps/{id}` 检查 `app.workflow_id` 是否非空, 若空则在 AgentConfig response 加 `dify_publish_status: "draft"|"published"` 字段

---

## 5. G5 — Dify Tenant 创建 API (RESOLVED, LOW 优先级)

### 5.1 v1 handoff 中的问题

> 如果走 Plan B 共享 Dify workspace，是否需要 basjoo 端预创建 Dify tenant？还是 admin 一次性在 Dify UI 创建，后续 basjoo 只用？

### 5.2 RESOLVED — 走 Plan B 不需要 tenant API

- **D5 决策保留** = Plan B 共享 1 个 Dify workspace
- 所有 basjoo workspace 共享同一 Dify 租户, 靠 `dify_user_prefix` (Dify `user` 字段加前缀) 隔离 (M10 G1 已实现)
- basjoo 端不需要调 Dify tenant 创建 API
- 运营侧: 一次性在 Dify UI 配好 service account, 把邮箱密码填到 basjoo `Workspace.dify_admin_*` 字段

### 5.3 决策更新

- D5 不变
- 不需要 tenant API
- 唯一 ops 步骤: Dify 侧人工创建 1 个 service account + 1 个 workspace, 把凭据存到 basjoo

---

## 6. NEW D8 — Per-agent API Key 必要性 (v1 handoff 未识别)

### 6.1 问题

v1 handoff §3.2 决策 D1-D7 都假设 **workspace-level** Dify API key (即所有 agent 共享一个 `app-xxx` token)。**但** `POST /console/api/apps/{id}/api-keys` 是**每个 App 一个 key** — Dify 端不支持 "workspace-level runtime key"。

### 6.2 当前 M10 实现的错误

**文件**：`backend/services/dify/provider.py:193-207` `_resolve_api_key`

```python
def _resolve_api_key(self) -> str:
    # 优先级: workspace.dify_api_key → settings.dify_api_key
    if self.workspace and self.workspace.dify_api_key:
        return decrypt_api_key(self.workspace.dify_api_key)
    if settings.dify_api_key:
        return settings.dify_api_key
    raise DifyConfigError(...)
```

**问题**: `workspace.dify_api_key` 在 basjoo schema 里 (`models.py:46-62`) 是**workspace-level Dify Console admin session 凭据**(D4 决策中 service account 用的)，**不是** runtime `app-xxx` token。

M10 §3.2 D1 决策定义 `workspace.dify_api_key` 字段时**没有区分** "Dify Console admin 凭据" 和 "Dify Runtime API key" — 现在回看 schema 命名是有歧义的。

### 6.3 课程修正 — 必须新增 per-agent API key

每个 basjoo agent 必须**有自己**的 Dify `app-xxx` token (因为每个 agent 对应一个 Dify App)：

**Schema 改动 (`backend/models.py:83-254` Agent 表)**:
```python
# 现有 (v1 决策 D7):
dify_app_id = Column(String(64), nullable=True)         # ← M10+1 新增
dify_workflow_id = Column(String(64), nullable=True)    # ← M10 已有

# 新增 (D8):
dify_api_key = Column(Text, nullable=True)               # ← M10+1 新增, Fernet 加密
```

**`DifyProvider._resolve_api_key` 优先级调整**:
```python
def _resolve_api_key(self) -> str:
    # 优先级: agent.dify_api_key → workspace.dify_api_key (legacy/M10 路径) → settings.dify_api_key
    if self.agent and self.agent.dify_api_key:
        return decrypt_api_key(self.agent.dify_api_key)
    # M10 legacy fallback
    if self.workspace and self.workspace.dify_api_key:
        return decrypt_api_key(self.workspace.dify_api_key)
    if settings.dify_api_key:
        return settings.dify_api_key
    raise DifyConfigError(...)
```

### 6.4 决策更新 — 新加 D8

| # | 决策 | 选项 | 默认推荐 |
|---|---|---|---|
| **D8** | **Per-agent vs Workspace-level API key** | (a) Per-agent: 每 agent 自己的 `app-xxx` token (来自 Dify `POST /apps/{id}/api-keys`)/ (b) Workspace-level: 1 个 `app-xxx` 共享给所有 agent (Dify 不原生支持, 需 admin 手动在 Dify UI 创建 1 个 key 给所有 agent 用) | **(a) Per-agent** — M10+1 必须支持, 否则 M10+1 只能让 admin 手动在 Dify UI 创建 1 个 key 塞到 workspace.dify_api_key, 失去 per-agent 隔离意义 |

---

## 7. M10+1 实施步骤 (根据本轮调研更新)

### 7.1 M10+1.1 Schema migration (2 个新字段)

**文件**：`backend/sqlite_migrations/0XX_add_agent_dify_app_id_and_api_key.sql` (新)

```sql
-- v1 决策 D7
ALTER TABLE agents ADD COLUMN dify_app_id VARCHAR(64) NULL;

-- 新 D8 决策
ALTER TABLE agents ADD COLUMN dify_api_key TEXT NULL;  -- Fernet 加密存储
```

**Model 改动** (`backend/models.py:230 附近`):
```python
# 现有 (M10):
dify_workflow_id = Column(String(64), nullable=True)
dify_user_prefix = Column(String(64), nullable=True)
dify_inputs_schema = Column(JSON, nullable=True)
dify_end_user_strategy = Column(String(32), nullable=True)

# 新增 (M10+1):
dify_app_id = Column(String(64), nullable=True)    # D7
dify_api_key = Column(Text, nullable=True)          # D8 (Fernet 加密的 app-xxx token)
```

### 7.2 M10+1.2 新增 `DifyAdminClient` 类

**文件**：`backend/services/dify/admin_client.py` (新, ~280 行)

**核心方法 (基于本轮调研)**:
```python
@dataclass(frozen=True)
class DifyAdminClient:
    api_base: str                              # fail-fast
    admin_email: str
    admin_password: str                        # Plaintext at runtime, Fernet 加密存储
    timeout: float = 30.0
    cache_ttl: int = 3600                      # 1 hour

    def __post_init__(self):
        if not self.api_base: raise DifyConfigError(...)
        if not self.admin_email: raise DifyConfigError(...)
        if not self.admin_password: raise DifyConfigError(...)

    @classmethod
    def from_workspace(cls, workspace: Workspace) -> "DifyAdminClient":
        return cls(
            api_base=workspace.dify_api_base or settings.dify_api_base,
            admin_email=workspace.dify_admin_email,
            admin_password=decrypt_api_key(workspace.dify_admin_password_ref),
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """LRU cached session client (keyed by api_base + admin_email)"""
        # 查 cache → 命中且未过期 → 返回
        # 未命中 → login → 缓存
        # 401 → 清缓存 → 重登 → 重放
        ...

    async def create_app_and_workflow(
        self,
        name: str,
        description: str,
        mode: str = "workflow",
        icon_type: str = "emoji",
        icon: str = "🤖",
        icon_background: str = "#FFEAD5",
    ) -> dict:
        """2-step: create_app → sync_draft_workflow (D3 课程修正)"""
        client = await self._get_client()
        csrf = client.cookies.get("csrf_token", "")

        # Step 1: create app
        app_resp = await client.post(
            "/console/api/apps",
            json={"name": name, "description": description, "mode": mode,
                  "icon_type": icon_type, "icon": icon, "icon_background": icon_background},
            headers={"X-CSRF-Token": csrf},
        )
        app_resp.raise_for_status()
        app_id = app_resp.json()["id"]

        # Step 2: lazy create workflow (empty graph)
        wf_resp = await client.post(
            f"/console/api/apps/{app_id}/workflows/draft",
            json={"graph": {}, "features": {}, "environment_variables": [], "conversation_variables": []},
            headers={"X-CSRF-Token": csrf},
        )
        wf_resp.raise_for_status()
        workflow_id = wf_resp.json()["id"]

        return {"app_id": app_id, "workflow_id": workflow_id}

    async def enable_api_and_create_key(self, app_id: str) -> str:
        """Step 3: enable_api → POST /api-keys → return app-xxx token"""
        client = await self._get_client()
        csrf = client.cookies.get("csrf_token", "")

        # Enable API
        await client.post(
            f"/console/api/apps/{app_id}/api-enable",
            json={"enable_api": True},
            headers={"X-CSRF-Token": csrf},
        )

        # Create API key
        key_resp = await client.post(
            f"/console/api/apps/{app_id}/api-keys",
            headers={"X-CSRF-Token": csrf},
        )
        key_resp.raise_for_status()
        return key_resp.json()["token"]  # ← "app-xxx..."
```

### 7.3 M10+1.3 扩展 `create_agent` endpoint

**文件**：`backend/api/v1/endpoints.py:2007-2085`

**改动** (D1 同步 + D2 回滚 + D8 per-agent key):
```python
@router.post("/agents", response_model=AgentConfig, status_code=201)
async def create_agent(
    request: AgentCreateRequest,
    current_user: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    # 既有 workspace quota 校验
    workspace = await db.get(Workspace, current_user.workspace_id)
    quota = await db.get(WorkspaceQuota, current_user.workspace_id)
    agent_count = await db.scalar(select(func.count(Agent.id)).where(Agent.workspace_id == workspace.id))
    if agent_count >= quota.max_agents:
        raise HTTPException(402, "Agent quota exceeded")

    # 既有 basjoo Agent 创建 (default DeepSeek LLM)
    agent = Agent(
        workspace_id=workspace.id,
        name=request.name,
        # ... 其余 default ...
    )
    db.add(agent)
    await db.flush()  # 取 agent.id

    # M10+ 改造点: Dify 集成
    if workspace.dify_enabled and workspace.dify_admin_email and workspace.dify_admin_password_ref:
        try:
            dify = DifyAdminClient.from_workspace(workspace)
            # 2-step create (D3 课程修正)
            result = await dify.create_app_and_workflow(
                name=request.name,
                description=request.description or "",
                mode="workflow",
            )
            agent.dify_app_id = result["app_id"]
            agent.dify_workflow_id = result["workflow_id"]

            # D8: 立即创建 per-agent API key (runtime 用)
            api_key = await dify.enable_api_and_create_key(result["app_id"])
            agent.dify_api_key = encrypt_api_key(api_key)
        except DifyError as e:
            await db.rollback()  # D2: 不留脏数据
            raise HTTPException(502, f"Dify workflow creation failed: {e}")
        except httpx.HTTPError as e:
            await db.rollback()
            raise HTTPException(502, f"Dify HTTP error: {e}")

    await db.commit()
    await db.refresh(agent)
    return await build_agent_config_with_stats(agent, db)
```

### 7.4 M10+1.4 更新 `DifyProvider._resolve_api_key` (D8)

**文件**：`backend/services/dify/provider.py:193-207`

```python
def _resolve_api_key(self) -> str:
    # D8: per-agent 优先
    if self.agent and getattr(self.agent, "dify_api_key", None):
        return decrypt_api_key(self.agent.dify_api_key)
    # M10 legacy fallback (workspace-level)
    if self.workspace and self.workspace.dify_api_key:
        return decrypt_api_key(self.workspace.dify_api_key)
    if settings.dify_api_key:
        return settings.dify_api_key
    raise DifyConfigError("No Dify API key resolved")
```

### 7.5 M10+1.5 Unit tests (新文件)

**文件**：`backend/tests/test_dify_admin_client.py` (新, ~300 行)

**测试用例 (10+ cases)**:
1. `test_create_app_and_workflow_happy_path` — mock 2 个 httpx 响应
2. `test_create_app_failure_raises` — mock 4xx
3. `test_sync_workflow_failure_raises` — mock step 1 OK step 2 fail
4. `test_enable_api_and_create_key_happy_path` — mock 2 步
5. `test_login_failure_raises_difyautherror`
6. `test_401_triggers_relogin` — mock 第 1 次 401, 第 2 次 200
7. `test_from_workspace_decrypts_password`
8. `test_post_init_fail_fast_empty_api_base`
9. `test_post_init_fail_fast_empty_email`
10. `test_post_init_fail_fast_empty_password`
11. `test_session_cache_ttl_expiry`
12. `test_create_agent_with_dify_disabled_fallback` (集成 create_agent endpoint)

### 7.6 M10+1.6 D9 (c) 增量 — publish 容错 + 状态字段 (用户拍板 2026-06-15)

**文件**：`backend/sqlite_migrations/0XX_add_agent_dify_publish_status.sql` (新)

```sql
ALTER TABLE agents ADD COLUMN dify_publish_status VARCHAR(32) NOT NULL DEFAULT 'draft';
-- 枚举: 'draft' | 'published' | 'publish_failed'
ALTER TABLE agents ADD COLUMN dify_publish_error TEXT NULL;
```

**Model 改动** (`backend/models.py:230 附近`):
```python
# D9 (c) 状态字段
dify_publish_status = Column(String(32), nullable=False, default="draft")
dify_publish_error = Column(Text, nullable=True)
```

**`DifyAdminClient` 新增方法** (`backend/services/dify/admin_client.py`):
```python
async def publish_workflow(self, app_id: str) -> bool:
    """D9 (c) 自动 publish, 失败返回 False 不抛异常。
    Returns: True on 200, False on 400/422 (空 graph 等校验失败)。其他 5xx 抛 DifyUpstreamError。
    """
    client = await self._get_client()
    csrf = client.cookies.get("csrf_token", "")
    try:
        resp = await client.post(
            f"/console/api/apps/{app_id}/workflows/publish",
            headers={"X-CSRF-Token": csrf},
        )
        if resp.status_code in (200, 201):
            return True
        if resp.status_code in (400, 422):
            # 校验失败 (空 graph 无 Start 节点等), 不抛
            return False
        # 5xx 等真错误才上抛
        resp.raise_for_status()
        return True
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (400, 422):
            return False
        raise DifyUpstreamError(f"publish_workflow failed: {e}")
```

**`create_agent` endpoint 改造** (`backend/api/v1/endpoints.py:2007-2085`):
```python
# 在 D9 (c) 自动 publish 步骤:
publish_ok = await dify.publish_workflow(result["app_id"])
if publish_ok:
    agent.dify_publish_status = "published"
else:
    # 不抛 502, 主流程继续
    agent.dify_publish_status = "publish_failed"
    agent.dify_publish_error = "Dify workflow publish failed (likely empty graph validation). Admin can retry in Dify UI after configuring graph."
    # 记录告警 metric (可选)
```

**新增测试用例** (`backend/tests/test_dify_admin_client.py`):
13. `test_publish_workflow_success` — mock 200
14. `test_publish_workflow_validation_failure_returns_false` — mock 400
15. `test_publish_workflow_validation_422_returns_false` — mock 422
16. `test_publish_workflow_5xx_raises` — mock 500
17. `test_create_agent_publish_failed_status_persists` (集成测试)

**前端提示** (`M10+3` 处理, 此处仅 spec):
- `AgentSettings` 页面加 `dify_publish_status` 徽章
  - `published` = 绿色 "✓ Published"
  - `publish_failed` = 黄色 "⚠ Publish failed, click to retry / go to Dify UI"
  - `draft` = 灰色 "Draft (auto-created)"

---

## 8. 关键文件路径速查 (本轮调研涉及)

### Dify 仓 (新增已读)

```
dify/api/controllers/console/wraps.py:108-154          # G1: cloud_edition_billing_resource_check (no-op)
dify/api/services/app_service.py:166-300               # G2: create_app 不创建 Workflow
dify/api/constants/model_template.py:6-95             # G2: default_app_templates[AppMode.WORKFLOW]
dify/api/services/workflow_service.py:273-343          # G2: sync_draft_workflow 懒创建
dify/api/services/workflow_service.py:454-499          # G4: publish_workflow
dify/api/controllers/console/app/workflow.py:455-528   # G2: DraftWorkflowApi.post
dify/api/controllers/console/app/workflow.py:1083-1120 # G4: PublishedWorkflowApi.post
dify/api/controllers/console/apikey.py:171-196         # G4: AppApiKeyListResource.post
dify/api/controllers/console/app/app.py:868-887        # G4: AppApiStatus.post (enable_api)
dify/api/controllers/console/auth/login.py:94-169      # G3: login 3 cookie
dify/api/libs/login.py:39-162                          # G3: CSRF check
```

### basjoo 仓 (M10+1 涉及)

```
backend/models.py:83-234                              # M10+1.1: 加 dify_app_id + dify_api_key 字段
backend/services/dify/admin_client.py                 # M10+1.2: 新建 ~280 行
backend/services/dify/exceptions.py                   # M10+1.2: 新建 DifyError 类族
backend/api/v1/endpoints.py:2007-2085                 # M10+1.3: create_agent 集成 Dify
backend/services/dify/provider.py:193-207             # M10+1.4: _resolve_api_key D8 优先级
backend/sqlite_migrations/0XX_add_agent_dify_app_id_and_api_key.sql  # M10+1.1: 新 migration
backend/tests/test_dify_admin_client.py               # M10+1.5: 新建 ~300 行
```

---

## 9. 决策修订表 (v1 → v2)

| # | 决策 | v1 假设 | v2 修正 | 原因 |
|---|---|---|---|---|
| D1 | 创建时机 | (a) 同步 | 不变 | M9/M10 已稳, 同步是最佳体验 |
| D2 | 失败回滚 | (a) 不留脏数据 | 不变 | 防止半成品 agent |
| D3 | workflow 内容 | (b) 空白 workflow | 内容不变,**实现路径** 1-step → **2-step** | `create_app` 不创建 Workflow 行 (G2) |
| D4 | Dify 鉴权 | (c) workspace service account | 不变, **新增 D4.1/D4.2 子决策** (cache TTL, 凭据存储) | G3 部分闭环 |
| D5 | Multi-tenant | (b) Plan B 共享 | 不变 | G5 闭环 |
| D6 | 前端改造 | (a) 最小化 | 不变 | M10+3 处理 |
| D7 | dify_app_id 字段 | 必加 | 不变 | workflow_id 是 App 下属, 多 1 个外键便于回查 |
| **D8 (NEW)** | **Per-agent API key** | (v1 未识别) | **(a) Per-agent** | Dify 端不支持 workspace-level runtime key, 每 App 一个 `app-xxx` token |
| **D9 (NEW)** | **workflow publish 时机** | (v1 未识别) | **(c) basjoo 自动 publish 但容错** (用户拍板 2026-06-15, 原默认 (b) admin 手动被否) | 符合用户"一站式"愿景, 失败不阻塞, 加 2 个状态字段 |

---

## 10. 硬门更新 (相对 v1 handoff §7)

### 10.1 新增硬门 (M10+ 特有)

- [ ] **D8 兼容性**: `DifyProvider._resolve_api_key` 必须支持 3 级 fallback: agent → workspace → settings (旧 M10 path 不破坏)
- [ ] **D9 (c) publish 容错**: M10+1 `DifyAdminClient.publish_workflow(app_id)` 必须 try/except HTTP 400/422, 失败时设 `agent.dify_publish_status='publish_failed'` + `agent.dify_publish_error=<error message>`, **不抛 502**, 允许主流程继续 (admin 后续可重试或去 Dify UI 补 publish)
- [ ] **D3 2-step 一致性**: `create_app_and_workflow` 复合方法必须原子性, step 1 失败不能调 step 2, step 2 失败必须 rollback step 1 (调 `DELETE /apps/{id}`)
- [ ] **D8 字段加密**: `agent.dify_api_key` 必须 Fernet 加密存储, DB 校验明文不出现
- [ ] **LRU cache 401 重试**: 收到 401 必须清缓存 + 重登 1 次, 死循环上限 1

### 10.2 v1 handoff §7 硬门 (全部保留)

- [ ] `pytest backend/tests/` 全绿
- [ ] `cd frontend-nextjs && npm run typecheck && npm run lint` 全绿
- [ ] `cd frontend-nextjs && npm run test` 全绿
- [ ] 不引入新 `console.log`
- [ ] 不引入 hardcoded secret
- [ ] 既有 `chat_stream` 真 Dify 流式路径不破坏
- [ ] Schema 一致性
- [ ] 回滚对称性
- [ ] Plan B 兼容
- [ ] session cookie 不外泄
- [ ] 超时兜底
- [ ] fail-fast 校验

---

## 11. 自我评估 (This Session)

### 11.1 已完成

- [x] **G1** 完全闭环 — `cloud_edition_billing_resource_check` 在自部署 Dify 是 no-op
- [x] **G2** 完全闭环 + **v1 课程修正** — `create_app` 不创建 Workflow 行, 必须 2-step
- [x] **G3** 部分闭环 — auth 流程 + CSRF 模式已查清, TTL 数字未查 (默认推荐 1h + 401 重试 1 次)
- [x] **G4** 完全闭环 — Runtime Bearer `app-xxx` + publish 失败风险识别
- [x] **G5** 完全闭环 (LOW) — Plan B 不需要 tenant API
- [x] **D8 新决策** — per-agent API key 必要性已论证 + 优先级调整方案
- [x] **D9 新决策** — workflow publish 时机定为 (b) admin 手动
- [x] **M10+1 实施步骤** — 7.1-7.5 全部产出代码骨架
- [x] **决策修订表** — v1 → v2 9 项决策对比
- [x] **硬门更新** — 5 条新硬门 (D8 兼容 / D9 不自动 publish / D3 2-step 原子性 / D8 Fernet 加密 / LRU 401 重试)

### 11.2 未完成 (留给后续会话)

- [ ] **M10+1 实际代码实现** (本轮不写代码, 只出 spec)
- [ ] **G3 cookie TTL 数字** (本轮未深查 lib/auth, 留给 M10+1 实施时按需补充)
- [ ] **M10+2 endpoint 集成** (依赖 M10+1 落地)
- [ ] **M10+3 前端 form 扩展**
- [ ] **M10+4 真 Dify E2E** (本机/CI, 沙箱不可跑)
- [ ] **M10+5 文档 + docker-compose**

### 11.3 关键 takeaway 给后续会话

1. **D3 课程修正最关键** — 任何"create_app 内嵌 workflow"假设都是错的, 必须 2-step
2. **D8 per-agent API key 必须做** — 不做的话 M10+1 就只能让 admin 手动在 Dify UI 创 1 个 key 塞到 workspace.dify_api_key, 失去 per-agent 隔离意义
3. **D9 publish 不自动做** — M10+1 `DifyAdminClient` 必须不暴露 `publish_workflow` 方法, admin 手动在 Dify UI 配置 + publish
4. **PR 拆分节奏** — v1 §6 M10+1..+5 拆分合理, M10+1 范围确认是 schema + admin_client + 单测 (无 endpoint 改动, 无前端改动), M10+2 才是 endpoint 集成
5. **G3 cookie TTL 默认 1h** — 短一些, 强制定期重登, 401 重试上限 1

---

**文档结束**。新会话请带着本文件 §9 决策修订表 + §7 M10+1 实施步骤进入 M10+1 实际编码。
