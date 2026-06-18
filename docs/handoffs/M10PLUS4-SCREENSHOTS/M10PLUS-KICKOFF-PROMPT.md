# M10+ Phase 2 Kickoff Prompt — Agent↔Dify Workflow 集成实施

> **使用方式**: 新会话开启后, 把本文件**完整内容**复制粘贴到第一条 prompt。
> **作用**: 让新会话的 Claude 直接进入 M10+1 编码, 不必重新调研。
> **生成日期**: 2026-06-15 (M10+ Phase 1 调研闭环日)
> **基线 HEAD**: `f2a1eb0` (M10 闭环, 9 sub-PR)

---

## 任务一句话

承接 M10+ Phase 1 调研（G1-G5 闭环 + D8/D9 用户拍板），启动 **M10+1 PR 实际代码实现**。本提示词是 2026-06-15 调研会话的完整状态快照 — 你（新会话的 Claude）应**从读文档开始**，不要重新调研 Dify API、basjoo 现状或决策。直接落地 5+1 子任务（§M10+1 PR 任务）。

---

## 1. 项目背景

| 项 | 值 |
|---|---|
| 工作目录 | `D:\AI\company-projects\ai-customer\ai-customer-service` |
| 当前分支 | `feat/m9-stream-think-stripper` |
| basjoo 主仓 | `backend/` (FastAPI) + `frontend-nextjs/` (Next.js) + `widget/` (embed SDK) |
| Dify 原仓参考 | `dify/` (只读，用于查 workflow / app API 端点) |
| 基线 HEAD | `f2a1eb0` (M10 闭环，9 sub-PR) |
| 关键产物状态 | M10 消费侧（chat_stream 走 Dify）✅；生产侧（create_agent 创建 Dify）❌ 空白 |

---

## 2. 用户原始诉求（Verbatim，**不可改写**）

**业务背景**：
> "用户第一次使用我们的前端在注册登录之后，页面上会让用户去创建智能体，点击创建智能体之后会跳转到一个页面，在这一块的逻辑我还没弄清楚情况，按照我们的业务需求用户在第一次注册登录之后确实需要创建智能体，也就是进入到前端的创建页面"

**集成愿景**：
> "在创建智能体的背后是对应着在dify上创建一个工作流，我需要彻查这部分逻辑... 我想知道的是现在的逻辑中，在前端创建智能体之后是否是按照我们的愿景在dify平台上创建一个workflow 对应于前端创建的智能体？我记得当前的代码中完全没有创建 Dify workflow 的逻辑（这部分需要从dify原仓库代码：d:\AI\company-projects\ai-customer\ai-customer-service\dify 里面去扣）... 这个集成逻辑是完全没有的，现在只是两边原型分立的状态"

**集成复杂度预判 + 范围**：
> "集成在我的预想中会比较复杂，前端配置好自己的工作流需求之后，在dify侧创建工作流，创建好之后返回该工作流的工作流id，appid等参数进行绑定 等等细节）前端的逻辑同样需要大改 等这个环节实际完成之后才算阶段性的成功"

**成本说明**：用户明示忽略成本告警，详细的完成即可，不需要管花费。

---

## 3. 必读文档（按顺序，**不要跳读**）

1. `~/.claude/projects/D--AI-company-projects-ai-customer-ai-customer-service/memory/MEMORY.md`（auto-loaded）— 重点看 `project-m10plus-handoff.md` 链接的 7 条 How-to-apply
2. `docs/handoffs/M10PLUS-agent-dify-integration.md`（v1 handoff，512 行 27.9KB）— 蓝图 + 决策表 + PR 拆分
3. `docs/handoffs/M10PLUS-G1-G5-RESOLVED.md`（调研闭环，~700 行）— 4 个 gap 完整闭环 + 3 个关键发现
4. `CLAUDE.md`（仓库根，**已有**，含架构说明 / 部署 / 测试 notes）
5. `china_charge_kf/CLAUDE.md`（M10 原型，**仅参考**，不集成）

**完整读完后，回答我一个 sanity check 再开干**：「v1 假设 `create_app` 内嵌 workflow 是对的吗？」答 1 句就够。

---

## 4. 关键决策（D1-D9，**已固化，不要重新论证**）

| # | 决策 | 选项 | **默认值** | 备注 |
|---|---|---|---|---|
| D1 | 创建时机 | (a) 同步 / (b) 异步 | **(a) 同步** | 体验直接，timeout 30s 兜底 |
| D2 | 失败回滚 | (a) 不留脏数据 / (b) 标 failed | **(a) 不留脏数据** | 配合 D9 (c) 例外（publish 失败不阻塞） |
| D3 | workflow 内容 | (a) DSL / (b) 空白 / (c) 模板 | **(b) 空白 workflow** | admin 在 Dify UI 配置 graph |
| D4 | Dify 鉴权 | (a/b/c) | **(c) workspace service account** | + D4.1 凭据存 Workspace 加密字段 + D4.2 LRU 1h |
| D5 | Multi-tenant | (a) Plan A / (b) Plan B | **(b) Plan B 共享 Dify workspace** | 靠 `dify_user_prefix` 隔离（M10 G1） |
| D6 | 前端改造 | (a/b/c) | **(a) 最小化** | M10+3 处理 |
| D7 | dify_app_id 字段 | 必加 | **必加** | workflow_id 是 App 下属 |
| **D8 (NEW)** | Per-agent API key | (a) per-agent / (b) workspace-level | **(a) per-agent** ✅ 用户拍板 | 新增 `Agent.dify_api_key` Fernet 字段 |
| **D9 (NEW)** | publish 时机 | (a/b/c) | **(c) basjoo 自动 publish 但容错** ✅ 用户拍板 | 替代原推荐 (b) admin 手动；新增 `Agent.dify_publish_status` + `dify_publish_error` 字段 |

---

## 5. 3 个关键发现（**实施时不要忘**）

### 5.1 D3 课程修正 — 2-step create（v1 假设错误）

**错误假设**：`create_app(mode="workflow")` 内嵌创建 Workflow 行
**实际路径**：
```python
# Step 1: POST /console/api/apps body={name, description, mode:"workflow", ...}
#         → 返回 {"id": app_id}
# Step 2: POST /console/api/apps/{app_id}/workflows/draft body={graph:{}, features:{}, ...}
#         → 返回 {"id": workflow_id}  ← 懒创建
```

`DifyAdminClient.create_app_and_workflow()` 复合方法封装这 2 步。`graph: {}` 是合法草稿，**但 publish 会校验** Start 节点。

### 5.2 D8 (a) — Per-agent API key 必须做

Dify 端不支持 workspace-level runtime key。每 App 独立 `app-xxx` token：
```python
# Step 3: POST /console/api/apps/{app_id}/api-enable body={enable_api:true}
# Step 4: POST /console/api/apps/{app_id}/api-keys
#         → 返回 {"token": "app-xxx..."}  ← Fernet 加密存 Agent.dify_api_key
```

`DifyProvider._resolve_api_key` 3 级 fallback：
```python
agent.dify_api_key → workspace.dify_api_key (M10 legacy) → settings.dify_api_key
```

### 5.3 D9 (c) — basjoo 自动 publish 但容错

`POST /console/api/apps/{app_id}/workflows/publish` 对空 graph 校验失败（Dify workflow 必须有 Start 节点）。M10+1 必须 try/except 400/422：
- 成功 → `agent.dify_publish_status = "published"`
- 400/422 → `agent.dify_publish_status = "publish_failed"` + `agent.dify_publish_error = <error>`, **不抛 502**
- 5xx → 抛 `DifyUpstreamError` 走 D2 失败回滚

**D9 (c) 与 D2 的边界**：
- D9 publish 失败（400/422）= 业务可恢复，**不**回滚
- D8 API key 创建失败（5xx）= 系统故障，**回滚**
- D3 create_app 或 sync_draft_workflow 失败 = 必回滚

---

## 6. M10+1 PR 任务（5+1 子任务，**从 7.1 开始**）

### 7.1 Schema migration（3 个新字段）

**新文件**：`backend/sqlite_migrations/0XX_add_agent_dify_integration_fields.sql`

```sql
-- D7
ALTER TABLE agents ADD COLUMN dify_app_id VARCHAR(64) NULL;
-- D8
ALTER TABLE agents ADD COLUMN dify_api_key TEXT NULL;  -- Fernet 加密
-- D9 (c)
ALTER TABLE agents ADD COLUMN dify_publish_status VARCHAR(32) NOT NULL DEFAULT 'draft';
ALTER TABLE agents ADD COLUMN dify_publish_error TEXT NULL;
```

**Model 改动** (`backend/models.py:230 附近`)：对应 3 个新 `Column` 声明。

### 7.2 DifyAdminClient 类（新文件 `backend/services/dify/admin_client.py`，~320 行）

**核心方法**：
- `from_workspace(workspace) -> DifyAdminClient` — 解密 `dify_admin_password_ref` Fernet
- `_get_client() -> httpx.AsyncClient` — LRU cache（key=api_base+email, TTL=1h, max 512 entries, 401 重登 1 次）
- `create_app_and_workflow(name, description, mode="workflow", ...) -> {app_id, workflow_id}` — **2-step** (D3 课程修正)
- `enable_api_and_create_key(app_id) -> str` — 2-step（enable + api-keys），返回 `app-xxx` token
- `publish_workflow(app_id) -> bool` — **D9 (c) try/except 400/422**，返回 bool

**Fail-fast** `__post_init__`：空 `api_base` / `admin_email` / `admin_password` → `DifyConfigError`

**新文件** `backend/services/dify/exceptions.py`：`DifyError` / `DifyConfigError` / `DifyAuthError` / `DifyUpstreamError`

### 7.3 create_agent endpoint 集成

**文件**：`backend/api/v1/endpoints.py:2007-2085`

**改造流程**：
```python
# 1. 既有 workspace quota 校验 (D1)
# 2. db.add(agent); await db.flush()  ← 取 agent.id 不 commit
# 3. if workspace.dify_enabled and workspace.dify_admin_email:
#      try:
#        dify = DifyAdminClient.from_workspace(workspace)
#        result = await dify.create_app_and_workflow(name=..., description=..., mode="workflow")
#        agent.dify_app_id = result["app_id"]
#        agent.dify_workflow_id = result["workflow_id"]
#        api_key = await dify.enable_api_and_create_key(result["app_id"])
#        agent.dify_api_key = encrypt_api_key(api_key)
#        publish_ok = await dify.publish_workflow(result["app_id"])  # D9 (c)
#        if publish_ok:
#          agent.dify_publish_status = "published"
#        else:
#          agent.dify_publish_status = "publish_failed"
#          agent.dify_publish_error = "Dify workflow publish failed (likely empty graph validation). ..."
#      except (DifyConfigError, DifyAuthError, DifyUpstreamError, httpx.HTTPError) as e:
#        await db.rollback()  # D2
#        raise HTTPException(502, f"Dify workflow creation failed: {e}")
# 4. await db.commit()
```

### 7.4 DifyProvider._resolve_api_key 3 级 fallback

**文件**：`backend/services/dify/provider.py:193-207`

```python
def _resolve_api_key(self) -> str:
    # D8: per-agent 优先
    if self.agent and getattr(self.agent, "dify_api_key", None):
        return decrypt_api_key(self.agent.dify_api_key)
    # M10 legacy fallback
    if self.workspace and self.workspace.dify_api_key:
        return decrypt_api_key(self.workspace.dify_api_key)
    if settings.dify_api_key:
        return settings.dify_api_key
    raise DifyConfigError(...)
```

### 7.5 单元测试（新文件 `backend/tests/test_dify_admin_client.py`，~350 行）

**17+ cases**（按 G1-G5-RESOLVED.md §7.5 + §7.6 列表）：
1. test_create_app_and_workflow_happy_path
2. test_create_app_failure_raises
3. test_sync_workflow_failure_raises
4. test_enable_api_and_create_key_happy_path
5. test_login_failure_raises_difyautherror
6. test_401_triggers_relogin
7. test_from_workspace_decrypts_password
8. test_post_init_fail_fast_empty_api_base
9. test_post_init_fail_fast_empty_email
10. test_post_init_fail_fast_empty_password
11. test_session_cache_ttl_expiry
12. test_create_agent_with_dify_disabled_fallback
13. test_publish_workflow_success
14. test_publish_workflow_validation_failure_returns_false
15. test_publish_workflow_validation_422_returns_false
16. test_publish_workflow_5xx_raises
17. test_create_agent_publish_failed_status_persists

---

## 7. 硬门（**每个 PR 必跑**）

### 7.1 通用硬门
- [ ] `pytest backend/tests/` 全绿
- [ ] `cd frontend-nextjs && npm run typecheck && npm run lint` 全绿（M10+1 不改前端，但仍跑）
- [ ] 不引入新 `console.log`
- [ ] 不引入 hardcoded secret
- [ ] 既有 `chat_stream` 真 Dify 流式路径不破坏（回归测试）

### 7.2 M10+1 特有硬门
- [ ] **D8 兼容**：`DifyProvider._resolve_api_key` 3 级 fallback 覆盖 agent / workspace / settings
- [ ] **D9 (c) 容错**：`publish_workflow` 必须 try/except 400/422，失败时 `dify_publish_status='publish_failed'`，**不抛 502**
- [ ] **D3 2-step 原子性**：`create_app_and_workflow` 复合方法必须原子，step 1 失败不调 step 2，step 2 失败必须 rollback step 1（调 `DELETE /apps/{id}`）
- [ ] **D8 字段 Fernet 加密**：`Agent.dify_api_key` DB 校验明文不出现
- [ ] **LRU 401 重试上限 1**：避免死循环
- [ ] **fail-fast 校验**：`workspace.dify_enabled=true && dify_admin_email=None` → 400 报错，不调 Dify
- [ ] **session cookie 不外泄**：DifyAdminClient 日志 redact cookie
- [ ] **超时兜底**：httpx timeout=30s，超时失败走 D2 回滚

---

## 8. M10+1 PR 范围（**不要扩大**）

- ✅ **做**：7.1 schema migration / 7.2 DifyAdminClient + exceptions / 7.5 单元测试
- ❌ **不做**：7.3 endpoint 集成（**留给 M10+2**）/ 7.4 Provider 调整（**留给 M10+2**） / 前端任何改动（**留给 M10+3**）

**M10+1 PR 的可验证标准**：
- `pytest backend/tests/test_dify_admin_client.py` 17 cases 全绿
- `python3 -c "from backend.services.dify.admin_client import DifyAdminClient"` 导入成功
- DB migration 跑成功（新建 sqlite 测试库 + 跑 migration + 验证 4 字段存在）
- 不破坏既有 `backend/tests/test_create_agent.py`（即 `workspace.dify_enabled=false` 路径）

---

## 9. 上下文连续性（**你必须知道**）

- **任务 #7（pending）**：backport D3/D8/D9 课程修正到 v1 handoff `M10PLUS-agent-dify-integration.md` — 你可以在 M10+1 PR 完成后顺手做
- **任务 #8（pending）**：本提示词涵盖的 M10+1 PR 实际代码实现
- **M10+2..+5**：在 M10+1 合并后启动，spec 在 `G1-G5-RESOLVED.md` §6-§7
- **M10+4 E2E**：类比 M10 PR4c，**沙箱内跑不起来**（Docker build 挂），**必须本机/CI**。M10+1 PR 完成后产出"7 步本机补跑清单"类比 M10 §8
- **G3 cookie TTL 数字**：未查，**默认 LRU TTL=1h + 401 重试 1 次**。M10+1 实施时如需精确 TTL，可深挖 `dify/api/libs/login.py` 找 `set_access_token_to_cookie` 的 `expire` 参数
- **Dify 真实地址**：参考 `memory/dify-v1-real-url.md`（沙箱内走 `124.243.178.156:8501` 直连 HTTP，**不是** ai.trendpower.cc/v1）
- **成本告警**：用户明示忽略，放心用大上下文做完整的 deep-dive / 测试 / 实施

---

## 10. 沙箱限制（**提前知道**）

- ❌ 沙箱内 Docker build 会挂（M10 PR4c 已知）
- ❌ 沙箱内 Playwright 1.60 跑不起来（Windows sandbox 拦 `cmd.exe` spawn，参考 `feedback-playwright-sandbox-spawn.md`）
- ❌ 沙箱内真 Dify E2E 跑不起来
- ✅ 沙箱内可做：schema migration / 单测 / type check / lint / `pytest --list` / 静态分析
- ✅ 真集成测试（httpx mock + pytest-httpx）**沙箱内可跑**
- ❌ 真 Dify HTTP 调用（M10+2 端点集成测）**本机/CI 跑**

---

## 11. 第一步行动

读完 §1-§10 后, **第一步**：

```bash
git status  # 确认 working tree 干净
git log --oneline -5  # 确认 HEAD = f2a1eb0 附近
ls docs/handoffs/  # 确认 v1 + G1-G5-RESOLVED 文件存在
```

然后开始 M10+1.1 schema migration。

**任何**遇到 spec 模糊的，先回 `G1-G5-RESOLVED.md` §7-§10 找答案；找不到再问我。

---

**文档结束**。新会话带本提示词进入 M10+1 编码，按 §6 顺序实施，按 §7 硬门验证。
