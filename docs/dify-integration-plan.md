# Dify 集成 + 多租户 KB 改造方案（v2 返工版）

> 本文档为后续 10 个里程碑 (M0-M10) 的实施蓝图。v2 相对 v1 的变更：修复 27 个具体问题，新增 5 个章节（§10-14），增加术语表、决策日志、依赖图、应急/数据迁移/安全/计费/文档交付物专章。
>
> **本文件是 single source of truth**，所有跨会话 AI 工作都以此为基线。如有变更，必须先改本文件再写代码。

---

## 目录

- §0 背景与现状
- §1 架构总览与决策日志
- §2 术语表
- §3 里程碑依赖图与总览表
- §4 数据模型
- §5 详细里程碑 (M0-M10)
- §6 跨切关注 (可观测性 / 安全 / 性能 / 兼容)
- §7 全局风险与回滚矩阵
- §8 全局验收标准
- §9 跨会话交接清单
- §10 应急与运维
- §11 数据迁移
- §12 安全与合规
- §13 成本与计费
- §14 文档交付物清单
- §15 关键参考
- §16 变更日志

---

## §0 背景与现状

### 0.1 业务场景
- **B2B**：B 端客户（如充电桩品牌方）订阅平台后获得独立 workspace，前端 widget 嵌入到 B 客户的官网/小程序。
- **B2C**：终端用户（C 端消费者）通过 H5/Widget 与 AI 客服对话，由平台自营品牌方提供知识库与客服能力。
- **多租户隔离**：B 客户私有数据（对话、私有 KB、API Key、配额）物理/逻辑隔离；C 端共享平台默认 KB。

### 0.2 现状（截至 2026-06-12）
- `backend/` 是 FastAPI + SQLite 主后端，核心链路在 `backend/api/v1/endpoints.py`：
  - `chat_stream` 三阶段：Phase 1 准备（Quota/Rate/Session/KB/PR13）/ Phase 2 LLM streaming / Phase 3 持久化。
  - KB 检索由 `backend/services/kb_retrieval_service.py` 走 Qdrant，每 Agent 单一 `kb_id`。
  - 多模态（图片/语音）通过 `vision_service.py` + `asr_service.py` 在 Backend 预处理。
  - 当前已有 `thinking` SSE 事件（endpoints.py ~1577 行），前端 widget 已实现解析。
  - 当前 `BaseLLMService.chat_completion` 真实签名见 §5 M3 前置验证。
- `china_charge_kf/` 是面向海外充电桩场景的**子目录**（2026-06-13 从独立 git 仓库并入主仓，commit `5981f65`；含 FastAPI `app_dify/` 与 Dify workflow yml）。后续 M-milestone 工作统一在主仓进行。
- Dify workflow yml 位于：`china_charge_kf/Workflow-China_charge_seriver-draft-9380/workflow/workflow.yml`（含 if-else 三分支 + 变量聚合 + 3 个 KB retrieval 节点）。
- Dify client（参考实现 + M2 扩展）：`china_charge_kf/backend/app_dify/dify_client.py` — M2 已加 `run_workflow_blocking` / `run_workflow_stream` / 三类错误子类 / `extract_output_text`（PR8/9/10 契约），62 测试覆盖率 97%。

### 0.3 目标
- 用 Dify 替换当前 backend 的 LLM 生成层（OpenAI/DeepSeek/Google 等 provider），但**保留** backend 的 Quota/Rate limit/Session/PR13/持久化 能力。
- 实现真正的 SaaS 多租户：B 客户按 workspace 隔离 KB、会话、配额、API Key。
- 支持 KB 双层结构：平台默认 KB（共享）+ B 客户私有 KB（独占）。
- 端到端流式体验：first token < 2s，Dify workflow 平均 < 10s。
- 平滑灰度：可按 session 粘性路由到 Dify 或原 LLM，故障时 < 30s 回滚。

---

## §1 架构总览

### 1.1 系统架构图

```
┌──────────────────────────────────────────────────────────────┐
│ Frontend Layer                                                │
│  - Next.js Admin (frontend-nextjs/) - B 客户/平台管理后台    │
│  - Widget (widget/) - 嵌入 B 客户网站的聊天组件              │
│  - H5 (frontend/) - C 端用户入口                              │
└────────────────────────┬─────────────────────────────────────┘
                         │ HTTPS
┌────────────────────────▼─────────────────────────────────────┐
│ Nginx (nginx/) - 反向代理 + CORS + Rate Limit                │
└────────────────────────┬─────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────────┐
│ Backend (FastAPI) - 租户层 + 业务逻辑层                       │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ Phase 1: 请求预处理（短 DB session）                      │ │
│ │  - Auth / Origin 白名单 / Quota / Rate Limit             │ │
│ │  - Session 管理（按 workspace_id 隔离）                  │ │
│ │  - MultiLayerKbService（platform + tenant）             │ │
│ │  - PR13: Vision/ASR 处理（仅 audio 走 ASR）            │ │
│ │  - DifyClient.upload_file()（图片/语音）                 │ │
│ │  - 拼接 Dify inputs（kb_context + user_msg + files）   │ │
│ │  - 灰度路由：DIFY_ROLLOUT_HASH 粘性分流                  │ │
│ └──────────────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ Phase 2: SSE 代理层（无 DB 连接）                         │ │
│ │  - 原 LLM 路径：llm.chat_completion(stream=True)        │ │
│ │  - Dify 路径：DifyStreamingProxy.stream_to_frontend()  │ │
│ │  - Circuit Breaker：Dify 故障 → 自动降级原 LLM         │ │
│ │  - thinking 事件：保留现有超时心跳机制                   │ │
│ └──────────────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ Phase 3: 持久化（新 DB session）                          │ │
│ │  - ChatMessage 写入（按 workspace_id 隔离）             │ │
│ │  - Quota 累加（含 token 用量）                          │ │
│ │  - WorkflowExecutionLog 审计日志                        │ │
│ │  - WebSocket 实时推送                                    │ │
│ └──────────────────────────────────────────────────────────┘ │
└────────────────────────┬─────────────────────────────────────┘
                         │ POST /v1/workflows/run (streaming)
┌────────────────────────▼─────────────────────────────────────┐
│ Dify (LLM 引擎层) - 平台自有 1 个 workspace + 1 个 workflow  │
│  Workspace: qushiyun's (Dify Cloud 或自托管，社区版)        │
│  App: customer_service_v1 (Dify 内部命名，原 China_charge) │
│    workflow_v2.yml 结构：                                    │
│    Start (input_text, language, input_image)                │
│      └─→ LLM (vision enabled if image, doubao-seed-2.0)    │
│            └─→ End (output)                                  │
│    system prompt 写在 workflow yml 中（中文客服角色）         │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ 支撑服务                                                       │
│  - Redis: Rate limit / Cache fallback / 灰度计数             │
│  - Qdrant: 向量库（platform_default_kb + tenant_kb_{hash}） │
│  - PostgreSQL: Admin / Workspace / Quota 主库                │
│  - Dify Internal DB: Dify 应用/数据集/执行日志               │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 关键决策（决策日志 v1）

| 决策点 | 选择 | 备选方案 | 为何选 | 决策日期 | 影响 |
|---|---|---|---|---|---|
| Dify workspace 数量 | **1 个**（平台自有） | 每个 B 客户一个 workspace | N 个 workspace 带来运维/计费灾难，且 Dify workspace 是组织单元不是租户单元 | 2026-06-12 | DIFY_WORKSPACE 单一环境变量 |
| Dify workflow 数量 | **1 个** v2 | 多个 workflow 按业务线 | 业务差异通过 inputs 动态注入，1 个 workflow 更易维护 | 2026-06-12 | DIFY_WORKFLOW_ID 单一环境变量 |
| 多租户隔离层 | **Backend 数据库层** | Dify 内置隔离 | 真正的 SaaS 多租户 + Dify 原生不支持细粒度租户 | 2026-06-12 | 所有表加 workspace_id 列 |
| KB 物理隔离 | **Qdrant 多 collection** | Qdrant payload 过滤 | 物理隔离防止逻辑漏洞 + 删除 workspace 时直接 drop collection | 2026-06-12 | tenant_kb_wsid_{hash16} 命名 |
| KB 检索位置 | **Backend** | Dify workflow 内部 KB | Dify `dataset_ids` 硬编码在 yml，无法 API 动态切换 | 2026-06-12 | Dify workflow 简化（去 KB 节点） |
| 图片多模态处理 | **Dify vision** | Backend Vision 描述成文本 | Dify vision 端到端理解更准确 + Backend 减少 LLM 调用 | 2026-06-12 | PR13 vision_service.py 在 chat_stream 不再被调用 |
| 语音多模态处理 | **Backend ASR → 文本** | 整体传音频 | Dify 无内置 ASR，必须 Backend 端 Whisper 转写 | 2026-06-12 | asr_service.py 仍保留 |
| workflow 结构 | **单 LLM 节点** | 保留 if-else 三分支 | 简化后 Dify 维护成本低 + 单 LLM 节点 + vision 开关足够 | 2026-06-12 | v2 删除 if-else / 变量聚合 / 3 个 KB 节点 |
| B/C 区分 | **Backend workspace_id** | Dify 内置 | Dify 不感知业务形态，差异化在 Backend 路由 | 2026-06-12 | Backend 路由层 |
| 灰度路由算法 | **session_id MD5 hash % 100** | 随机 / per-request | 粘性：同一 session 全程一致，UX 一致 | 2026-06-12 | DIFY_ROLLOUT_PERCENTAGE + per-agent 强制开关 |
| 故障降级 | **Dify 失败 → 原 LLM** | 完全失败 | 用户体验优先 + 降级路径可观测 | 2026-06-12 | Circuit Breaker + 健康检查 |
| 核心入口改造方式 | **新建 /chat/stream-v2** | 改造原 /chat/stream | 旧端点保留 6 个月可回滚 + A/B 对比 | 2026-06-12 | 旧端点不删除 |

---

## §2 术语表

| 术语 | 含义 | 范围 |
|---|---|---|
| **Workspace** | 本项目租户单元，对应一个 B 客户或平台自营 | Backend 数据库层 |
| **Agent** | 一个 AI 客服配置单元（含 LLM/KB/系统提示等） | Backend |
| **Dify Workspace** | Dify 内部的组织单元（类似 team） | Dify 平台层 |
| **Dify App** | Dify 内部的一个具体应用（workflow/chatflow/agent） | Dify 平台层 |
| **Dify workflow** | App 内的图编排 | Dify 平台层 |
| **Dify end_user** | 调用方标识字符串 | Dify API 层 |
| **session_id** | Backend 的会话 ID（公开 UUID） | Backend |
| **session_db_id** | Backend 的会话主键（int） | Backend |
| **workflow_run_id** | Dify 单次工作流执行 ID | Dify API 层 |
| **task_id** | Dify 任务跟踪 ID，可用于 stop 端点 | Dify API 层 |
| **KB** | Knowledge Base，文档知识库 | Qdrant collection |
| **platform KB** | 平台默认 KB，所有 workspace 共享 | Qdrant collection `platform_default_kb` |
| **tenant KB** | 租户私有 KB，1 workspace 1 collection | Qdrant collection `tenant_kb_wsid_{hash16}` |
| **DIFY_ROLLOUT_PERCENTAGE** | 灰度百分比 (0-100) | 环境变量 |
| **DIFY_ROLLOUT_FORCE_AGENT_IDS** | 强制走 Dify 的 agent ID 列表（逗号分隔） | 环境变量 |
| **correlation_id** | 跨服务追踪 ID | Backend 日志层 |
| **circuit breaker** | 故障熔断器 | Backend resilience 层 |
| **v1 workflow** | 当前 Dify workflow（含 KB 节点） | Dify 平台层 |
| **v2 workflow** | 改造后的 Dify workflow（单 LLM 节点） | Dify 平台层 |
| **Dify protocol version** | Dify SSE 事件协议版本号 | Dify API 层 |

---

## §3 里程碑依赖图与总览表

### 3.1 依赖图

```
       M0 (设计基线)
        |
       M0.5 (协议发现,against v1)
        |
       M1 (workflow 改造)
       /  |  \
      /   |   \
   M1.5   M2   M6
     |    /|   /  \
     |   / |  /    \
     M3  | M4    M7
        \|/     /
         M5    /
          \   /
           M8 (E2E)
           /   \
          /     \
         M9    M10
        (UI)  (Deploy)
```

**并行可能性**：
- M0.5（协议发现，用 v1）独立，可与 M1、M2、M6 完全并行——v1 已部署，协议层与 v2 一致
- M1（workflow 改造）独立，可与 M2、M6 并行
- M2（DifyClient）独立，可与 M1、M6 并行
- M6（MultiLayerKb）独立
- M1.5（v2 协议一致性验收）必须排在 M1 之后、M2 之前（M2 完成后才接 M3 集成）
- M3 依赖 M1 + M1.5 + M2
- M4 依赖 M2
- M5 依赖 M3 + M4
- M7 依赖 M6
- M8 依赖 M5 + M7
- M9 依赖 M5 + M7
- M10 依赖 M8 + M9

**串行总时长**：~11 人天（单人）
**并行总时长**（3 人）：~6 人天

### 3.2 里程碑总览

| ID | 名称 | 工作量 | 状态 | 关键产出 | 依赖 |
|---|---|---|---|---|---|
| **M0** | 设计基线与契约 | 0.5d | pending | 本文档 + api-contract + sse-mapping + adr | - |
| **M0.5** | 协议发现（against v1） | 0.25d | **completed** | `docs/m0.5-protocol-findings.md` v2（V1-V10 全 ✅,E1-E3 环境问题暴露）| M0 |
| **M1** | Dify workflow 改造 | 0.5d | pending | workflow_v2.yml（Dify 控制台导入） | M0 |
| **M1.5** | v2 协议一致性验收 | 0.25d | pending | sse-event-mapping §8 M1.5 列全 ✅（含 S11 单链断言） | M1 |
| **M2** | Backend DifyClient 服务层 | 1d | pending | services/dify_client.py + 单测 | M0 |
| **M3** | LLMProvider 抽象层 | 1d | pending | DifyProvider + Agent 字段 + 输入转换器 | M1, M1.5, M2 |
| **M4** | Dify SSE 协议代理 | 1d | pending | services/dify_streaming_proxy.py + 单测 | M2 |
| **M5** | chat_stream 接入 Dify | 1.5d | pending | 新端点 /chat/stream-v2 + 灰度 + 降级 | M3, M4 |
| **M6** | 多层 KB 检索服务 | 1.5d | pending | MultiLayerKbService + Qdrant 多 collection | - |
| **M7** | 租户 KB 文档管理 | 1.5d | pending | tenant_kb_endpoints + TenantKbQuota | M6 |
| **M8** | 端到端集成测试 | 1d | pending | 4 大场景 E2E 测试 | M5, M7 |
| **M9** | 管理 UI 集成 | 1.5d | pending | Agent 配置页 + KB 管理页 | M5, M7 |
| **M10** | 部署与灰度 | 1d | pending | docker-compose + 监控 + runbook | M8, M9 |

---

## §4 数据模型

### 4.1 Agent 模型扩展（M3 触发）

```python
# backend/models.py 增量

class Agent(Base):
    # ... 现有字段 ...
    # LLM Provider
    llm_provider: str = "openai"  # "openai" | "deepseek" | "google" | "dify"
    dify_api_base_encrypted: Optional[bytes] = None  # Fernet 加密 bytes
    dify_api_key_encrypted: Optional[bytes] = None   # Fernet 加密 bytes
    dify_workflow_id: Optional[str] = None  # Dify workflow ID (UUID) 或 None 使用全局
    dify_user_prefix: str = "agent-{id}-"   # end_user 标识前缀
    # KB 配置
    default_kb_enabled: bool = True
    tenant_kb_enabled: bool = False
    # 灰度
    dify_rollout_force: bool = False  # True 时该 agent 强制走 Dify（无视百分比）
```

### 4.2 TenantKnowledgeBase 模型（M7 触发）

```python
class TenantKnowledgeBase(Base):
    __tablename__ = "tenant_knowledge_bases"
    id: str  # UUID
    workspace_id: str  # 关联 Workspace
    name: str
    description: str
    qdrant_collection: str  # 物理 Qdrant collection 名，命名见 §6.3
    embedding_model: str
    document_count: int = 0
    storage_bytes: int = 0
    created_at: datetime
    updated_at: datetime
    created_by: str  # admin user id
```

### 4.3 TenantKbQuota 模型（M7 触发）

```python
class TenantKbQuota(Base):
    __tablename__ = "tenant_kb_quotas"
    workspace_id: str  # PK
    max_documents: int = 100
    max_storage_bytes: int = 100 * 1024 * 1024  # 100MB
    max_document_size_bytes: int = 10 * 1024 * 1024  # 10MB
    max_uploads_per_hour: int = 50
    updated_at: datetime
```

### 4.4 KbDocument 模型扩展（M7 触发）

```python
class KbDocument(Base):
    # ... 现有字段 ...
    workspace_id: Optional[str] = None      # 租户隔离关键字段
    tenant_kb_id: Optional[str] = None      # NULL = 平台默认 KB
    storage_bytes: int = 0                  # 配额统计
```

### 4.5 WorkflowExecutionLog 模型（M5 触发）

```python
class WorkflowExecutionLog(Base):
    __tablename__ = "workflow_execution_logs"
    id: str  # UUID
    workspace_id: str
    session_id: str
    agent_id: str
    workflow_run_id: str     # Dify 返回
    task_id: str             # Dify 返回
    inputs: dict             # JSON
    outputs: Optional[dict]  # JSON
    status: str              # running / succeeded / failed / stopped
    total_tokens: int
    elapsed_time: float
    dify_protocol_version: str  # 协议版本
    error: Optional[str]
    correlation_id: str      # 跨服务追踪
    created_at: datetime
    finished_at: Optional[datetime]
```

### 4.6 QuotaUsage 模型扩展（M10 触发）

```python
class QuotaUsage(Base):
    # ... 现有字段 ...
    monthly_token_used: int = 0           # 新增：token 计量
    last_token_reset_at: Optional[datetime] = None
```

---

## §5 详细里程碑

### M0: 设计基线与契约

**目标**：固化设计基线，定义 API 契约，让后续每个 M 都能独立作业。

**前置**：无

**上下文**：
- 本里程碑的产出是后续所有 M 的"宪法"，必须在开始 M1 之前完成评审。
- 评审内容包括：Dify workflow 输入契约、SSE 事件协议转换、KB 检索合并策略、回退路径、降级策略、命名规范、加密规范。

**涉及文件**：
- `docs/dify-integration-plan.md` (本文档)
- `docs/api-contract-dify.md` (新增 - DifyClient 公开 API 契约)
- `docs/sse-event-mapping.md` (新增 - SSE 事件映射表)
- `docs/adr/0001-dify-llm-engine.md` (新增 - ADR：为何选 Dify)
- `docs/adr/0002-tenant-isolation.md` (新增 - ADR：多租户隔离策略)
- `docs/adr/0003-workflow-simplification.md` (新增 - ADR：workflow 简化)

**实施步骤**：
1. 评审本文档（特别是 §1.2 决策表）
2. 编写 `docs/api-contract-dify.md`：
   - `DifyClient` 类公开方法签名、参数、返回类型、异常
   - 错误码体系（DifyNetworkError / DifyAPIError / DifyWorkflowError）
   - 重试与超时策略
3. 编写 `docs/sse-event-mapping.md`：
   - Dify 原始事件 → 前端 SSE 事件的映射表
   - 所有 Dify 事件的处理策略（`workflow_started` / `node_started` / `text_chunk` / `node_finished` / `workflow_finished` / `tts_message*` / `human_input_required` / `ping` / `iteration_*`）
   - `text_chunk` → `content` 转换
   - `workflow_finished` 触发持久化钩子
4. 编写 3 个 ADR：
   - 0001: 为何选 Dify（对比 Coze / LangChain / 直接 OpenAI）
   - 0002: 多租户隔离策略（Dify workspace 数 / KB 物理隔离 / Session 隔离）
   - 0003: workflow 简化（为何去 KB / 为何单 LLM / 为何 Backend ASR）
5. **子任务：技术验证前置**（M1 的硬前置）：
   - [ ] 验证 `doubao-seed-2.0-lite` 是否支持 vision
   - [ ] 验证 Dify 的 LLM 节点 `vision.enabled` 配置
   - [ ] 验证 Dify 端音频支持范围（确认 Backend 必须 ASR）
   - [ ] 验证 Dify Cloud 100s 超时对长 workflow 的影响
6. 在 `docs/CHANGELOG.md` 顶部记录本次重构

**验收**：
- [ ] 本文档 §1 架构图与目标 codebase 一致
- [ ] `api-contract-dify.md` 中所有方法签名与 `china_charge_kf/backend/app_dify/dify_client.py` 兼容
- [ ] `sse-event-mapping.md` 列出所有 Dify 事件（含 `iteration_*`）的处理策略
- [ ] 3 个 ADR 评审通过
- [ ] 技术验证子任务 4 项全部确认

**测试**：无（文档里程碑）

**风险**：低。如有分歧，应在 M0 解决。

---

### M1: Dify workflow 改造（v2 workflow）

**目标**：让 Dify workflow 只做 LLM 生成（v2: 单 LLM 节点 + 简化结构）。

**前置**：M0（必须完成技术验证子任务）

**上下文**：
- 当前 `china_charge_kf/Workflow-China_charge_seriver-draft-9380/workflow/workflow.yml` 包含 if-else 三分支 + 3 个 knowledge-retrieval 节点 + 3 个 LLM 节点 + 1 个变量聚合节点。
- 改造原因：
  - Dify workflow 的 `dataset_ids` 硬编码在 yml 中（`REPLACE_WITH_YOUR_DIFY_DATASET_ID`），无法 API 动态切换。
  - 三分支 + 变量聚合增加了 Dify 端复杂度，且对 Backend 透明性差。
  - 图片走 Dify vision 端到端；语音由 Backend ASR 后只传文本。

**v2 workflow 结构（目标）**：
```
Start (input_text, language, input_image)
  └─→ LLM 节点（vision 根据 input_image 自动启用，prompt 用 {{#1001.input_text#}}）
        └─→ End (output)
```

**v2 节点 ID 锁**（与 M4 配合）：
- Start 节点 ID：`2001`（与 v1 区分）
- LLM 节点 ID：`2007`（v1 是 1007）
- End 节点 ID：`2015`（v1 是 1015）

**涉及文件**：
- `china_charge_kf/Workflow-China_charge_seriver-draft-9380/workflow/workflow_v2.yml` (新增)

**实施步骤**：
1. **创建 v2 workflow yml**：
   ```yaml
   app:
     name: customer_service_v1  # Dify 内部应用名
     mode: workflow
   workflow:
     graph:
       nodes:
         - id: '2001'
           data:
             type: start
             variables:
               - variable: input_text
                 type: paragraph
                 required: false
               - variable: language
                 type: text-input
                 default: "zh-CN"
               - variable: input_image
                 type: file
                 required: false
                 allowed_file_types: [image]
         - id: '2007'
           data:
             type: llm
             model:
               provider: volcengine_maas
               name: doubao-seed-2-0-lite
             prompt_template:
               - role: system
                 text: |
                   # 角色定义
                   你是充电桩售后诊断助手...
                   # 输出语言为{{#2001.language#}}
               - role: user
                 text: |
                   {{#2001.input_text#}}
             vision:
               enabled: true  # 自动按 input_image 决定
         - id: '2015'
           data:
             type: end
             outputs:
               - variable: output
                 value_selector: [2007, text]
   ```
2. 删除 3 个 knowledge-retrieval 节点（id 1006/1009/1012）
3. 删除 if-else 节点（id 1002）
4. 删除 ASR HTTP 节点（id 1008）
5. 删除 Code 节点（id 1011）
6. 删除变量聚合节点（id 1014）
7. 改 LLM 节点 user prompt 模板从 `{{#context#}}` 改为 `{{#2001.input_text#}}`
8. 删除 3 个 voice/text/image 三个 LLM 节点（保留一个 2007 即可）
9. **命名调整**：Dify App 改名为 `customer_service_v1`（原 `China_charge_seriver`）
10. 在 Dify 控制台导入 yml，发布为 production 版本
11. 录制 Dify streaming SSE 流到文件，确认 `text_chunk` 事件是 token 级

**验收**：
- [ ] `workflow_v2.yml` 不含 knowledge-retrieval / if-else / 变量聚合 / ASR 节点
- [ ] 单 LLM 节点 ID 为 `2007`，End 节点 ID 为 `2015`
- [ ] Dify 控制台运行测试：传 `{"input_text": "Hello", "language": "en"}` 收到完整回复
- [ ] Dify 控制台运行测试：传 `{"input_text": "Describe", "language": "en", "input_image": [...]}` 收到图片描述
- [ ] streaming 模式下，UI 可见逐 token 输出（`text_chunk` 间隔 < 1s）
- [ ] **L0 verification passed**: `doubao-seed-2.0-lite` 支持 vision 已确认

**测试**：
- Dify 控制台手动测试 3 个 case
- 录制 SSE 流到文件，确认 `text_chunk` 间隔

**风险**：
- 中：`doubao-seed-2.0-lite` vision 支持需 M0 验证确认
- 中：Dify App 改名 `customer_service_v1` 需要通知所有引用方
- 低：v1 workflow 仍可访问，不需删除（Dify 保留所有版本）

**后续衔接**：M4 `_selector_to_branch` 映射表硬编码 `2007 → "llm"`（简化版，无分支）。

---

### M2: Backend DifyClient 服务层

**目标**：在 Backend 实现可复用的 Dify HTTP 客户端，支持 blocking + streaming + 文件上传 + 错误处理。

**前置**：M0

**上下文**：
- `china_charge_kf/backend/app_dify/dify_client.py` 是**参考实现**（blocking + 文件上传）。
- M2 升级为 blocking + streaming 双模式 + 单元测试 + 重试 + 错误码。
- 这是 LLMProvider（M3）、SSE 代理（M4）的底层依赖。

**涉及文件**：
- `backend/services/dify_client.py` (新增)
- `backend/exceptions/dify_exceptions.py` (新增 - 异常类)
- `backend/tests/test_dify_client.py` (新增)
- `backend/config.py` (Dify 配置项)
- `backend/requirements.txt` (新增 `respx>=0.20.0` 用于 mock httpx)

**实施步骤**：
1. `config.py` 新增：
   ```python
   dify_api_base: str = "https://api.dify.ai/v1"
   dify_api_key: Optional[str] = None
   dify_workflow_id: Optional[str] = None
   dify_request_timeout: int = 300
   dify_max_retries: int = 3
   dify_retry_backoff_factor: float = 0.5
   dify_circuit_breaker_threshold: int = 10
   dify_circuit_breaker_timeout: int = 60
   ```
2. 异常类 `backend/exceptions/dify_exceptions.py`：
   ```python
   class DifyError(Exception): pass
   class DifyNetworkError(DifyError): pass
   class DifyAPIError(DifyError):
       def __init__(self, message, status_code, body): ...
   class DifyWorkflowError(DifyError):
       def __init__(self, message, status, outputs, error): ...
   class DifyTimeoutError(DifyError): pass
   class DifyFileUploadError(DifyError): pass
   ```
3. 实现 `DifyClient` 类：
   ```python
   class DifyClient:
       def __init__(self, api_base: str, api_key: str,
                    workflow_id: Optional[str] = None,
                    timeout: int = 300,
                    max_retries: int = 3,
                    backoff_factor: float = 0.5):
           # 不允许明文 API key 出现在 __repr__ / __str__
           self._api_base = api_base.rstrip("/")
           self._api_key = api_key
           self._workflow_id = workflow_id
           self._timeout = timeout
           self._max_retries = max_retries
           self._backoff = backoff_factor

       def __repr__(self):
           return f"DifyClient(api_base={self._api_base}, workflow_id={self._workflow_id})"

       async def upload_file(
           self,
           content: bytes,
           filename: str,
           content_type: str,
           user: str,
       ) -> str:
           """上传文件到 Dify，返回 upload_file_id.
           Raises: DifyFileUploadError, DifyAPIError, DifyNetworkError"""

       async def run_workflow_blocking(
           self,
           inputs: dict,
           user: str,
           files: Optional[List[Dict]] = None,
       ) -> Dict[str, Any]:
           """blocking 模式调用 workflow.
           Returns: data.outputs dict
           Raises: DifyWorkflowError (status=failed), DifyTimeoutError"""

       async def stream_workflow(
           self,
           inputs: dict,
           user: str,
           files: Optional[List[Dict]] = None,
       ) -> AsyncGenerator[Dict[str, Any], None]:
           """streaming 模式调用 workflow.
           Yields: 解析后的 Dify SSE 事件 dict, e.g. {"event": "text_chunk", "data": {"text": "...", "from_variable_selector": [...]}}
           Raises: DifyNetworkError, DifyAPIError"""
   ```
4. **streaming 解析器**：
   ```python
   async def _parse_sse_stream(self, response: httpx.Response) -> AsyncGenerator[Dict, None]:
       buffer = ""
       async for chunk in response.aiter_bytes():
           buffer += chunk.decode("utf-8", errors="replace")
           while "\n\n" in buffer:
               event_str, buffer = buffer.split("\n\n", 1)
               # 处理 "data: {...}" 格式
               for line in event_str.split("\n"):
                   if line.startswith("data: "):
                       try:
                           yield json.loads(line[6:])
                       except json.JSONDecodeError:
                           # 跳过非 JSON 行（如 ping 注释）
                           continue
   ```
5. **重试机制**（仅对网络错误和 5xx 错误）：
   ```python
   async def _request_with_retry(self, method, url, **kwargs):
       for attempt in range(self._max_retries):
           try:
               return await method(url, **kwargs)
           except (httpx.NetworkError, httpx.TimeoutException) as e:
               if attempt == self._max_retries - 1:
                   raise DifyNetworkError(...)
               await asyncio.sleep(self._backoff * (2 ** attempt))
   ```
6. 日志：每次调用记录 `correlation_id` / `workflow_run_id` / `elapsed_time` / `status`
7. 单元测试覆盖率 ≥ 80%（统一标准）：
   - 用 `respx` mock httpx
   - 覆盖：blocking 成功/失败/超时/重试、streaming 多个事件/中断/格式错误、文件上传成功/失败/类型错误、网络错误

**验收**：
- [ ] `DifyClient` 类实现完整，3 个方法都有类型注解和 docstring
- [ ] API key 不出现在 `__repr__` / `__str__` / 日志中（grep 验证）
- [ ] 单测覆盖 ≥ 80%
- [ ] `pytest backend/tests/test_dify_client.py` 全绿
- [ ] 不依赖 Dify 真实服务（用 respx mock）

**测试关键 case**：
```python
async def test_stream_parses_text_chunks(respx_mock):
    respx_mock.post(...).respond(
        text='data: {"event":"text_chunk","data":{"text":"你好","from_variable_selector":["2007","text"]}}\n\n',
        headers={"content-type": "text/event-stream"},
    )
    events = [e async for e in client.stream_workflow({"input_text": "hi"}, "user")]
    assert events[0]["data"]["text"] == "你好"

async def test_blocking_handles_failed_status(respx_mock):
    respx_mock.post(...).respond(json={"data": {"status": "failed", "error": "..."}})
    with pytest.raises(DifyWorkflowError):
        await client.run_workflow_blocking({}, "user")

async def test_api_key_not_in_repr():
    client = DifyClient(api_base="x", api_key="secret-key")
    assert "secret-key" not in repr(client)
    assert "secret-key" not in str(client)

async def test_network_error_retries_then_raises(respx_mock):
    respx_mock.post(...).mock(side_effect=httpx.NetworkError)
    with pytest.raises(DifyNetworkError):
        await client.run_workflow_blocking({}, "user")
    # 断言调用了 max_retries 次
```

**风险**：
- 低。httpx + respx 成熟。
- 中：Dify Cloud 100s 超时需在 M10 解决；M2 不处理。

**后续衔接**：M3 复用 `DifyClient` 实现 `DifyProvider`，M4 复用 `stream_workflow()`。

---

### M3: LLMProvider 抽象层 + Agent 模型扩展

**目标**：让 Agent 可以选择"传统 LLM"或"Dify workflow"作为 LLM 后端，统一接口调用。

**前置**：M1, M2

**上下文**：
- 现有 `backend/services/llm_service.py` 有 `BaseLLMService` 抽象和 `get_llm_service()` 工厂。
- M3 在工厂里加 `DifyProvider`，与 `OpenAIService` 等并列。
- 给 `Agent` 模型增加配置字段（§4.1）。
- **关键不变量**：`chat_stream` 的 Phase 2 调用方式必须兼容。
- **API key 加密规范**：见 §6.2。

**实施前必读**：
- `backend/services/llm_service.py` 的 `BaseLLMService` 真实签名
- `backend/services/agent_key_service.py` 的现有 key 加密机制

**涉及文件**：
- `backend/services/llm_service.py` (新增 `DifyProvider`、`MessagesToDifyInputConverter`)
- `backend/services/dify_client.py` (M2 产物)
- `backend/services/agent_key_service.py` (扩展 `get_agent_dify_key`)
- `backend/models.py` (Agent 增量字段)
- `backend/database.py` (Alembic 迁移)
- `backend/api/v1/schemas.py` (Agent schema 扩展)
- `backend/tests/test_dify_provider.py` (新增)
- `backend/tests/test_messages_to_dify_input.py` (新增)

**实施步骤**：
1. **Alembic 迁移**：
   ```bash
   alembic revision --autogenerate -m "add_dify_config_to_agents"
   alembic upgrade head
   ```
2. **Agent 字段**（见 §4.1）
3. **API key 加密**（在 `agent_key_service.py`）：
   ```python
   def get_agent_dify_key(agent: Agent) -> Optional[str]:
       if not agent.dify_api_key_encrypted:
           return None
       return fernet_decrypt(settings.ENCRYPTION_KEY, agent.dify_api_key_encrypted)
   # 严禁在 __repr__ / 日志中打印明文 key
   ```
4. **`MessagesToDifyInputConverter`**（关键新组件）：
   ```python
   class MessagesToDifyInputConverter:
       """把 OpenAI 风格 messages 转换为 Dify input_text.

       转换规则:
       - system_prompt 拼接在头部, 标记为 [系统指令]
       - 历史对话拼接为 [历史对话] 段
       - 最后一条 user message 作为 [当前问题]
       - 多模态 content (list 类型) 转换为文本描述
       """

       def __init__(self, kb_context: str = "", agent_system_prompt: str = ""):
           self.kb_context = kb_context
           self.agent_system_prompt = agent_system_prompt

       def convert(self, messages: List[Dict[str, str]]) -> str:
           sections = []

           if self.agent_system_prompt:
               sections.append(f"[系统指令]\n{self.agent_system_prompt}")

           if self.kb_context:
               sections.append(f"[参考资料]\n{self.kb_context}")

           # 历史对话
           history = self._extract_history(messages)
           if history:
               history_text = "\n".join(
                   f"{'用户' if m['role'] == 'user' else '助手'}: {self._flatten_content(m['content'])}"
                   for m in history
               )
               sections.append(f"[历史对话]\n{history_text}")

           # 当前问题
           current = self._extract_current_question(messages)
           sections.append(f"[当前问题]\n{current}")

           return "\n\n".join(sections)

       def _extract_history(self, messages):
           """取最后 N 条非当前 user 消息"""
           # 最后一条是当前用户消息, 之前的是历史
           if len(messages) <= 1:
               return []
           return messages[:-1]

       def _extract_current_question(self, messages):
           """取最后一条 user 消息的 content, 处理多模态"""
           for m in reversed(messages):
               if m["role"] == "user":
                   return self._flatten_content(m["content"])
           return ""

       def _flatten_content(self, content) -> str:
           """把 list 类型 content 转为文本描述"""
           if isinstance(content, str):
               return content
           if isinstance(content, list):
               parts = []
               for item in content:
                   if item.get("type") == "text":
                       parts.append(item["text"])
                   elif item.get("type") == "image_url":
                       parts.append("[图片]")
                   elif item.get("type") == "audio_url":
                       parts.append("[音频]")
               return " ".join(parts)
           return str(content)
   ```
5. **`DifyProvider`**：
   ```python
   class DifyProvider(BaseLLMService):
       def __init__(self, agent: Agent, kb_context: str = ""):
           self.agent = agent
           self.kb_context = kb_context
           api_key = get_agent_dify_key(agent)
           if not api_key:
               raise ValueError(f"Agent {agent.id} has no Dify API key configured")
           self.client = DifyClient(
               api_base=agent.dify_api_base or settings.dify_api_base,
               api_key=api_key,
               workflow_id=agent.dify_workflow_id or settings.dify_workflow_id,
           )
           self._last_usage = None

       async def chat_completion(
           self,
           messages: List[Dict[str, str]],
           system_prompt: Optional[str] = None,
           stream: bool = True,
           temperature: float = 0.7,
           max_tokens: int = 2000,
       ) -> AsyncIterator[str]:
           converter = MessagesToDifyInputConverter(
               kb_context=self.kb_context,
               agent_system_prompt=system_prompt or "",
           )
           input_text = converter.convert(messages)
           inputs = {
               "input_text": input_text,
               "language": getattr(self.agent, "default_language", "zh-CN"),
           }
           async for event in self.client.stream_workflow(
               inputs=inputs,
               user=f"{self.agent.dify_user_prefix}{self.agent.id}",
           ):
               if event.get("event") == "text_chunk":
                   yield event["data"]["text"]
               elif event.get("event") == "workflow_finished":
                   data = event.get("data", {})
                   self._last_usage = {
                       "total_tokens": data.get("total_tokens", 0),
                       "elapsed_time": data.get("elapsed_time", 0.0),
                       "workflow_run_id": event.get("workflow_run_id"),
                       "task_id": event.get("task_id"),
                   }

       def get_last_usage(self) -> Optional[Dict]:
           return self._last_usage
   ```
6. **`get_llm_service(agent)` 工厂**：
   ```python
   def get_llm_service(agent: Agent, kb_context: str = "") -> BaseLLMService:
       if agent.llm_provider == "dify":
           return DifyProvider(agent, kb_context=kb_context)
       # ... 原有逻辑
   ```
7. **API key 字段加到 `AgentCreate` / `AgentUpdate` schema**

**验收**：
- [ ] Agent 字段加好，迁移无报错
- [ ] `DifyProvider.chat_completion()` 能 yield 字符串（单测 mock）
- [ ] `get_llm_service(agent)` 根据 `llm_provider` 返回正确实例
- [ ] 原有 `OpenAIService` 等 provider 行为不变（回归测试）
- [ ] API key 加密存储 + 解密
- [ ] 单测覆盖 ≥ 80%

**测试关键 case**：
```python
async def test_messages_converter_merges_kb_context():
    converter = MessagesToDifyInputConverter(
        kb_context="[来源1] 充电桩指南",
        agent_system_prompt="你是客服",
    )
    messages = [
        {"role": "user", "content": "我的充电桩坏了"},
        {"role": "assistant", "content": "请提供型号"},
        {"role": "user", "content": "A100"},
    ]
    result = converter.convert(messages)
    assert "[系统指令]\n你是客服" in result
    assert "[参考资料]\n[来源1] 充电桩指南" in result
    assert "[历史对话]" in result
    assert "[当前问题]\nA100" in result

async def test_messages_converter_handles_multimodal_content():
    converter = MessagesToDifyInputConverter()
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "看这个"},
            {"type": "image_url", "image_url": "..."},
        ]}
    ]
    result = converter.convert(messages)
    assert "[图片]" in result
    assert "看这个" in result

async def test_dify_provider_yields_text_chunks():
    # mock DifyClient.stream_workflow 返回 [text_chunk, text_chunk, workflow_finished]
    provider = DifyProvider(agent, kb_context="")
    tokens = [t async for t in provider.chat_completion(
        messages=[{"role": "user", "content": "hi"}], stream=True
    )]
    assert tokens == ["token1", "token2"]
    usage = provider.get_last_usage()
    assert usage["total_tokens"] > 0
```

**风险**：
- 中：messages → input_text 转换的细节可能影响 Dify 端 prompt 效果，需要多轮调优
- 中：API key 加密在 M3 引入，需要先读 `agent_key_service.py` 现有机制

**后续衔接**：M4 直接消费 `DifyProvider.chat_completion()` 的事件；M5 chat_stream 接入。

---

### M4: Dify SSE 协议代理层

**目标**：把 Dify streaming 响应转换为结构化事件流，让 M5 chat_stream 可以监听完整事件信息。

**前置**：M2

**上下文**：
- M3 的 `DifyProvider.chat_completion` 只暴露 token 字符串。
- M4 提供更"全量"的 Dify 事件流接口（`AsyncGenerator[Dict]`），让 chat_stream 可以：
  - 监听 `text_chunk` 实时 yield
  - 在 `workflow_finished` 后拿到 usage / outputs 用于持久化
- v2 workflow 节点 ID 锁为 `2007`（M1 决策），无 if-else 三分支。

**涉及文件**：
- `backend/services/dify_streaming_proxy.py` (新增)
- `backend/tests/test_dify_streaming_proxy.py` (新增)
- `docs/sse-event-mapping.md` (M0 产物，作为本 M 实施参考)

**实施步骤**：
1. **DifyStreamingProxy 类**：
   ```python
   class DifyStreamingProxy:
       """Dify SSE → 结构化事件流转换器.

       v2 workflow 节点 ID:
         - 2007: LLM 节点
         - 2015: End 节点

       yield dict 结构:
         {"type": "content", "content": "token", "from_node": "2007"}
         {"type": "workflow_started", "workflow_run_id": "...", "task_id": "..."}
         {"type": "workflow_finished", "outputs": {...}, "usage": {...}, "status": "..."}
         {"type": "node_started", "node_id": "2001", "node_type": "start"}
         {"type": "node_finished", "node_id": "2007", "status": "succeeded"}
         {"type": "error", "error": "...", "code": "..."}
       """

       # v2 节点 ID 映射
       NODE_NAME_MAP = {
           "2001": "start",
           "2007": "llm",
           "2015": "end",
       }

       def __init__(self, client: DifyClient, logger=None):
           self.client = client
           self.logger = logger or logging.getLogger(__name__)

       async def stream_to_frontend(
           self,
           inputs: dict,
           user: str,
           files: Optional[List[Dict]] = None,
       ) -> AsyncGenerator[Dict[str, Any], None]:
           try:
               async for event in self.client.stream_workflow(inputs, user, files):
                   yield self._transform_event(event)
           except DifyNetworkError as e:
               self.logger.exception("Dify network error")
               yield {"type": "error", "error": str(e), "code": "DIFY_NETWORK_ERROR"}
           except DifyWorkflowError as e:
               self.logger.exception("Dify workflow error")
               yield {"type": "error", "error": str(e), "code": "DIFY_WORKFLOW_ERROR"}
           except Exception as e:
               self.logger.exception("Dify unexpected error")
               yield {"type": "error", "error": str(e), "code": "DIFY_UNKNOWN_ERROR"}

       def _transform_event(self, event: Dict) -> Dict:
           event_type = event.get("event")
           data = event.get("data", {})

           if event_type == "text_chunk":
               selector = data.get("from_variable_selector", [])
               from_node = selector[0] if selector else "unknown"
               return {
                   "type": "content",
                   "content": data.get("text", ""),
                   "from_node": from_node,
               }
           elif event_type == "workflow_started":
               return {
                   "type": "workflow_started",
                   "workflow_run_id": event.get("workflow_run_id"),
                   "task_id": event.get("task_id"),
               }
           elif event_type == "workflow_finished":
               return {
                   "type": "workflow_finished",
                   "outputs": data.get("outputs", {}),
                   "status": data.get("status"),
                   "usage": {
                       "total_tokens": data.get("total_tokens", 0),
                       "elapsed_time": data.get("elapsed_time", 0.0),
                   },
                   "error": data.get("error"),
               }
           elif event_type == "node_started":
               return {
                   "type": "node_started",
                   "node_id": data.get("node_id"),
                   "node_type": data.get("node_type"),
                   "title": data.get("title"),
               }
           elif event_type == "node_finished":
               return {
                   "type": "node_finished",
                   "node_id": data.get("node_id"),
                   "status": data.get("status"),
               }
           elif event_type == "ping":
               return {"type": "ping"}
           elif event_type == "tts_message":
               # v2 不启用 TTS
               self.logger.warning("Unexpected tts_message in v2 workflow")
               return {"type": "skipped", "reason": "tts_not_supported"}
           elif event_type == "human_input_required":
               # v2 不启用 HITL
               self.logger.error("Unexpected human_input_required in v2 workflow")
               return {
                   "type": "error",
                   "error": "Human-in-the-loop not supported",
                   "code": "HUMAN_INPUT_UNSUPPORTED",
               }
           elif event_type in ("iteration_started", "iteration_finished"):
               # v2 无 loop 节点, 记录但不转发
               self.logger.debug(f"Dify {event_type}: {data}")
               return {"type": "skipped", "reason": event_type}
           else:
               # 未知事件类型: 记录 + 跳过
               self.logger.warning(f"Unknown Dify event type: {event_type}")
               return {"type": "skipped", "reason": f"unknown:{event_type}"}
   ```
2. **单元测试覆盖**（≥ 80%）：
   - 各种事件类型的 transform
   - 错误路径 yield error dict 而非 raise
   - 未知事件类型不抛异常

**验收**：
- [ ] `stream_to_frontend` 异步生成器能正确解析 Dify 所有 v2 事件类型
- [ ] `text_chunk` 实时 yield
- [ ] 错误路径 yield error dict 而非 raise
- [ ] 未知事件类型安全跳过
- [ ] 单测覆盖 ≥ 80%

**测试**：
```python
async def test_v2_text_chunks_transformed():
    proxy = DifyStreamingProxy(client)
    # mock DifyClient 返回 v2 事件
    events = [
        {"event": "workflow_started", "workflow_run_id": "w1", "task_id": "t1"},
        {"event": "text_chunk", "data": {"text": "你好", "from_variable_selector": ["2007", "text"]}},
        {"event": "text_chunk", "data": {"text": "世界", "from_variable_selector": ["2007", "text"]}},
        {"event": "workflow_finished", "data": {"status": "succeeded", "outputs": {}, "total_tokens": 100}},
    ]
    # 用 mock async generator
    ...

async def test_network_error_yields_error_event():
    # mock DifyClient 抛 DifyNetworkError
    # 断言 yield {"type": "error", "code": "DIFY_NETWORK_ERROR"}
```

**风险**：
- 中：`_transform_event` 中的节点 ID 映射依赖 M1 决策。M1 完成后才能最终确定。
- 低：Dify 协议稳定性 - 引入协议版本检查（M10 监控）

**后续衔接**：M5 chat_stream 接入时直接调用 `DifyStreamingProxy.stream_to_frontend()`。

---

### M5: chat_stream 接入 Dify（新端点 + 灰度 + 降级）

**目标**：**新建** `/api/v1/chat/stream-v2` 端点走 Dify 路径，**保留** 原 `/chat/stream` 端点 6 个月。灰度按 session 粘性分流。故障自动降级。

**前置**：M3, M4

**上下文**：
- 现有 chat_stream 是生产核心入口，**直接修改风险极高**。
- M5 改造方式：**新建** `/chat/stream-v2` 端点，**原端点不删除**。
- 灰度通过 `DIFY_ROLLOUT_PERCENTAGE` 粘性路由：基于 `session_id` 哈希分流。
- 故障降级：Dify 调用失败 → 自动回退到原 LLM provider（如果是 OpenAI agent）。
- PR13 多模态在 M1 决策后简化为：图片走 Dify vision，语音由 Backend ASR 转写后只传文本。

**涉及文件**：
- `backend/api/v1/endpoints.py` (新增 `chat_stream_v2`，保留 `chat_stream`)
- `backend/api/v1/routers.py` (注册新端点)
- `backend/services/dify_streaming_proxy.py` (M4 产物)
- `backend/services/llm_service.py` (`DifyProvider` from M3)
- `backend/services/circuit_breaker.py` (新增 - 故障熔断)
- `backend/services/rollout_router.py` (新增 - 灰度路由)
- `backend/config.py` (新增灰度配置)
- `backend/models.py` (WorkflowExecutionLog)
- `backend/tests/test_chat_stream_v2.py` (新增)
- `backend/tests/test_rollout_router.py` (新增)

**实施步骤**：
1. **config.py**：
   ```python
   dify_rollout_percentage: int = 0  # 0-100
   dify_rollout_force_agent_ids: str = ""  # 逗号分隔
   dify_circuit_breaker_threshold: int = 10
   dify_circuit_breaker_timeout: int = 60
   dify_circuit_breaker_window: int = 60
   ```
2. **`rollout_router.py`**（粘性路由）：
   ```python
   import hashlib

   def should_route_to_dify(
       session_id: str,
       agent: Agent,
       rollout_percentage: int,
       force_agent_ids: List[str],
   ) -> bool:
       """基于 session_id MD5 hash 的粘性灰度"""
       if agent.llm_provider != "dify":
           return False
       if agent.dify_rollout_force or str(agent.id) in force_agent_ids:
           return True
       if rollout_percentage <= 0:
           return False
       if rollout_percentage >= 100:
           return True
       h = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
       return (h % 100) < rollout_percentage
   ```
3. **`circuit_breaker.py`**（故障熔断）：
   ```python
   class CircuitBreaker:
       """Dify 故障熔断器.

       状态机: CLOSED → OPEN → HALF_OPEN → CLOSED
       - CLOSED: 正常调用, 记录失败次数
       - OPEN: 熔断, 直接抛 DifyCircuitOpenError
       - HALF_OPEN: 半开, 允许 1 个请求试探
       """

       def __init__(self, name: str, failure_threshold: int,
                    recovery_timeout: int, window: int = 60):
           self.name = name
           self.failure_threshold = failure_threshold
           self.recovery_timeout = recovery_timeout
           self.window = window
           self.state = "CLOSED"
           self.failures = []
           self.last_failure_at = None

       async def call(self, func, *args, **kwargs):
           if self.state == "OPEN":
               if self._should_half_open():
                   self.state = "HALF_OPEN"
               else:
                   raise DifyCircuitOpenError(f"Circuit {self.name} is OPEN")
           try:
               result = await func(*args, **kwargs)
               self._on_success()
               return result
           except (DifyNetworkError, DifyWorkflowError) as e:
               self._on_failure()
               raise
   ```
4. **新建 `/chat/stream-v2` 端点**（基于 `chat_stream` 复制 + 改造）：
   ```python
   @router.post("/chat/stream-v2")
   async def chat_stream_v2(
       request: ChatRequest,
       http_request: Request,
   ):
       """chat_stream 的 Dify 版本, 保留原 chat_stream 不变."""

       async def event_generator():
           # Phase 1: 准备（与原 chat_stream 相同, 但 KB 检索改为 M6 实现, PR13 仅 ASR）
           async with database.AsyncSessionLocal() as prep_db:
               chat_context = await prepare_chat_request_v2(
                   request, http_request, prep_db
               )
               if chat_context["mode"] in ("rate_limited", "taken_over"):
                   # 走原逻辑
                   ...

               session_public_id = chat_context["session_public_id"]
               agent = chat_context["agent"]

               # 决定走哪条路径
               if should_route_to_dify(
                   session_public_id, agent,
                   settings.dify_rollout_percentage,
                   settings.dify_rollout_force_agent_ids_list,
               ):
                   path = "dify"
               else:
                   path = "legacy"

           # Phase 2: 流式
           yield sse_event("sources", {"sources": chat_context.get("sources", [])})

           if path == "dify":
               async for sse in stream_dify_path(chat_context):
                   yield sse
           else:
               async for sse in stream_legacy_path(chat_context):
                   yield sse

           # Phase 3: 持久化
           ...
   ```
5. **`stream_dify_path()`**：
   ```python
   async def stream_dify_path(chat_context):
       try:
           # 准备 dify inputs
           dify_inputs = {
               "input_text": chat_context["combined_user_text_with_kb"],
               "language": chat_context["language"],
           }
           # 上传图片
           dify_files = []
           for att in chat_context.get("attachments", []):
               if att["kind"] == "image":
                   file_id = await chat_context["dify_client"].upload_file(
                       content=att["content"],
                       filename=att["filename"],
                       content_type=att["mime_type"],
                       user=chat_context["end_user_id"],
                   )
                   dify_files.append({
                       "type": "image",
                       "transfer_method": "local_file",
                       "upload_file_id": file_id,
                   })

           # 调 Dify（带 Circuit Breaker）
           proxy = DifyStreamingProxy(chat_context["dify_client"])
           circuit = chat_context["dify_circuit"]

           async def _call_dify():
               async for event in proxy.stream_to_frontend(
                   inputs=dify_inputs,
                   user=chat_context["end_user_id"],
                   files=dify_files,
               ):
                   yield event

           async for event in circuit.call(_call_dify):
               if event["type"] == "content":
                   yield sse_event("content", {"content": event["content"]})
               elif event["type"] == "workflow_finished":
                   chat_context["workflow_run_id"] = event.get("workflow_run_id")
                   chat_context["dify_usage"] = event.get("usage")
               elif event["type"] == "error":
                   # 降级路径
                   logger.warning(f"Dify error, fallback: {event}")
                   async for sse in stream_legacy_path(chat_context):
                       yield sse
                   return

       except DifyCircuitOpenError:
           logger.warning("Dify circuit open, fallback to legacy LLM")
           async for sse in stream_legacy_path(chat_context):
               yield sse
   ```
6. **`stream_legacy_path()`**：封装原 chat_stream 的 Phase 2 逻辑（LLM provider 调用）
7. **thinking 事件保留**：原 chat_stream 已有超时心跳触发 `thinking` 事件，新端点沿用
8. **WorkflowExecutionLog 持久化**（Phase 3）：
   ```python
   # Phase 3 持久化后追加
   if chat_context.get("workflow_run_id"):
       await persist_workflow_execution_log(chat_context, db)
   ```
9. **A/B 对比（可选）**：在 rollout_percentage=10 阶段，同时把请求发到新旧端点，对比结果
   ```python
   # 仅在 dify_rollout_ab_test_enabled=True 时启用
   if settings.dify_rollout_ab_test_enabled:
       asyncio.create_task(_ab_compare(chat_context))
   ```

**验收**：
- [ ] 新端点 `/chat/stream-v2` 实现完整
- [ ] 原端点 `/chat/stream` 不受影响（回归测试）
- [ ] 灰度按 session 粘性分流（同一 session 全程走同一路径）
- [ ] 灰度开关可用：`DIFY_ROLLOUT_PERCENTAGE=0/10/50/100`
- [ ] Dify 故障自动降级到 legacy LLM
- [ ] `WorkflowExecutionLog` 记录完整
- [ ] `thinking` SSE 事件保留
- [ ] 单测覆盖 ≥ 80%

**测试**：
- E2E Playwright：创建 Dify agent，发消息，断言看到流式 token
- 灰度测试：mock 100 个不同 session_id，断言比例正确
- 降级测试：mock Dify 失败，断言走 legacy 路径
- 回归测试：原 OpenAI agent 不受影响

**风险**：
- **高**：核心入口改造，必须充分测试
- 中：A/B 对比可能增加 Dify 配额消耗
- 中：Circuit Breaker 状态需持久化（避免重启后状态丢失）

**后续衔接**：M6 把 KB 检索实现替换为 MultiLayerKbService（PR13 改造的 Phase 1）。

---

### M6: 多层 KB 检索服务

**目标**：实现 `MultiLayerKbService`，支持"平台默认 KB + 租户私有 KB"双层检索，结果合并去重。

**前置**：M0（设计）

**上下文**：
- 当前 `kb_retrieval_service.py` 是单一 KB 检索。
- 改造后：
  - 平台默认 KB：所有租户共享（`platform_default_kb` collection）
  - 租户私有 KB：每个 workspace 独立 collection（`tenant_kb_wsid_{hash16}`，命名见 §6.3）
- 合并策略：各自 top_k=5 检索 → 去重 → 按 score 排序 → 取 top_k=5
- 1 workspace 对应 1 个 KB collection（**简化设计**，多 KB 用 metadata 区分，**取消** v1 中的多 KB 概念）

**涉及文件**：
- `backend/services/kb_retrieval_service.py` (重写)
- `backend/services/qdrant_service.py` (扩展多 collection)
- `backend/services/embedding_service.py` (确保 embedding 模型一致)
- `backend/tests/test_multi_layer_kb.py` (新增)
- `backend/models.py` (新增 `TenantKnowledgeBase`, `TenantKbQuota`)

**实施步骤**：
1. **Qdrant 集合命名规范**（与 §6.3 一致）：
   ```python
   import hashlib

   def tenant_collection_name(workspace_id: str) -> str:
       """生成 tenant KB 的 Qdrant collection 名.
       格式: tenant_kb_wsid_{md5前16位}
       限制: 总长 < 60 字符, 仅含 [a-z0-9_]
       """
       h = hashlib.md5(workspace_id.encode()).hexdigest()[:16]
       return f"tenant_kb_wsid_{h}"
   ```
2. **`MultiLayerKbService`**：
   ```python
   class MultiLayerKbService:
       DEFAULT_KB_COLLECTION = "platform_default_kb"
       DEFAULT_TENANT_COLLECTION_PREFIX = "tenant_kb_wsid_"
       DEFAULT_TOP_K = 5
       DEFAULT_THRESHOLD = 0.01

       def __init__(self, qdrant_service, embedding_service):
           self.qdrant = qdrant_service
           self.embed = embedding_service

       async def retrieve(
           self,
           workspace_id: str,
           agent: Agent,
           query: str,
           top_k: int = DEFAULT_TOP_K,
           threshold: float = DEFAULT_THRESHOLD,
       ) -> List[Dict[str, Any]]:
           """双层 KB 检索."""
           results = []

           # 1. 平台默认 KB
           if agent.default_kb_enabled:
               default_results = await self._retrieve_collection(
                   collection_name=self.DEFAULT_KB_COLLECTION,
                   query=query, top_k=top_k, threshold=threshold,
                   filter_conditions=None,  # 平台 KB 无 workspace 过滤
               )
               for r in default_results:
                   r["source_scope"] = "platform"
               results.extend(default_results)

           # 2. 租户私有 KB
           if agent.tenant_kb_enabled:
               tenant_collection = tenant_collection_name(workspace_id)
               tenant_results = await self._retrieve_collection(
                   collection_name=tenant_collection,
                   query=query, top_k=top_k, threshold=threshold,
                   filter_conditions={"workspace_id": workspace_id},  # 二次校验
               )
               for r in tenant_results:
                   r["source_scope"] = "tenant"
               results.extend(tenant_results)

           # 3. 去重 + 排序
           deduped = self._dedupe_by_text_hash(results)
           sorted_results = sorted(deduped, key=lambda x: x["score"], reverse=True)
           return sorted_results[:top_k]

       async def _retrieve_collection(
           self, collection_name, query, top_k, threshold, filter_conditions
       ) -> List[Dict[str, Any]]:
           """检索单个 collection."""
           try:
               query_vector = await self.embed.embed_query(query)
               results = await self.qdrant.search(
                   collection_name=collection_name,
                   query_vector=query_vector,
                   top_k=top_k,
                   score_threshold=threshold,
                   filter_conditions=filter_conditions,
               )
               return results
           except Exception as e:
               logger.warning(f"KB collection {collection_name} search failed: {e}")
               return []  # 降级: 不阻塞 chat

       def _dedupe_by_text_hash(self, results):
           seen = set()
           deduped = []
           for r in results:
               text_hash = hashlib.md5(r["text"].encode()).hexdigest()
               if text_hash not in seen:
                   seen.add(text_hash)
                   deduped.append(r)
           return deduped
   ```
3. **Qdrant collection 自动创建**：
   ```python
   async def ensure_tenant_collection(workspace_id: str, embedding_dim: int):
       """确保租户 KB collection 存在."""
       collection_name = tenant_collection_name(workspace_id)
       if not await qdrant.collection_exists(collection_name):
           await qdrant.create_collection(
               collection_name=collection_name,
               vectors_config=VectorParams(size=embedding_dim, distance=Distance.COSINE),
           )
   ```
4. **workspace 删除时清理**：
   ```python
   async def cleanup_workspace_kb(workspace_id: str):
       """workspace 删除时清理 Qdrant collection."""
       collection_name = tenant_collection_name(workspace_id)
       if await qdrant.collection_exists(collection_name):
           await qdrant.delete_collection(collection_name)
   ```
5. **单元测试**（≥ 80% 覆盖）：
   - mock Qdrant 返回 platform 和 tenant 结果
   - 断言合并 + 去重 + 排序
   - 断言只检索启用的层
   - 断言 scope_filter 防止跨租户越权
   - 断言 Qdrant 失败时降级（不阻塞 chat）

**验收**：
- [ ] `MultiLayerKbService.retrieve()` 返回正确合并结果
- [ ] platform 和 tenant 之间物理隔离（不同 collection）
- [ ] `scope_filter` 二次校验
- [ ] Qdrant 失败时优雅降级
- [ ] 集合命名规范严格（长度、字符集）
- [ ] 单测覆盖 ≥ 80%

**测试关键 case**：
```python
async def test_tenant_a_cannot_retrieve_tenant_b_docs():
    # mock Qdrant 返回 tenant A 文档
    # 断言结果中不含 tenant B 的文档
    pass

async def test_results_deduped_by_text_hash():
    # platform 和 tenant 都有相同 text
    # 断言去重后只保留一条（保留 score 高的）
    pass

async def test_qdrant_failure_does_not_block_chat():
    # mock Qdrant 抛异常
    # 断言 retrieve 返回空列表（不抛）
    pass

async def test_workspace_id_special_chars_handled():
    # workspace_id 含特殊字符
    # 断言 collection name 哈希后安全
    pass
```

**风险**：
- 中：合并策略可能需要多轮调优
- 低：Qdrant collection 数量爆炸问题（每 workspace 一个）— 见 §13 容量规划

**后续衔接**：M7 依赖此服务做租户 KB 文档管理。

---

### M7: 租户 KB 文档管理

**目标**：B 客户管理员可上传/查看/删除自己 workspace 下的私有 KB 文档，配额限制。

**前置**：M6

**涉及文件**：
- `backend/api/v1/tenant_kb_endpoints.py` (新增)
- `backend/api/v1/kb_document_endpoints.py` (扩展支持 tenant_kb_id)
- `backend/services/kb_document_processor.py` (扩展)
- `backend/services/tenant_kb_service.py` (新增 - 配额检查)
- `backend/models.py` (新增 `TenantKnowledgeBase`, `TenantKbQuota`, KbDocument 扩展)
- `backend/tests/test_tenant_kb_endpoints.py` (新增)

**实施步骤**：
1. **数据模型**（见 §4.2, §4.3, §4.4）
2. **API 端点**：
   ```
   POST   /api/v1/tenant-kb/{workspace_id}/documents        # 上传
   GET    /api/v1/tenant-kb/{workspace_id}/documents        # 列表
   GET    /api/v1/tenant-kb/{workspace_id}/documents/{id}   # 详情
   DELETE /api/v1/tenant-kb/{workspace_id}/documents/{id}   # 删除
   POST   /api/v1/tenant-kb/{workspace_id}/reindex          # 强制重新索引
   GET    /api/v1/tenant-kb/{workspace_id}/quota            # 配额
   PUT    /api/v1/tenant-kb/{workspace_id}/quota            # 配额更新（admin only）
   ```
3. **上传流程**：
   ```python
   @router.post("/tenant-kb/{workspace_id}/documents")
   async def upload_document(
       workspace_id: str,
       file: UploadFile = File(...),
       current_admin: Admin = Depends(get_current_admin),
       db: AsyncSession = Depends(get_db),
   ):
       # 1. 权限检查
       if not is_workspace_admin(current_admin, workspace_id, db):
           raise HTTPException(403, "Not workspace admin")

       # 2. 配额检查
       quota_service = TenantKbService(db)
       await quota_service.check_can_upload(workspace_id, file.size)

       # 3. 存储文件
       storage_key = await MediaStorage().put(file.filename, await file.read())

       # 4. 创建 KbDocument 记录
       doc = KbDocument(
           workspace_id=workspace_id,
           tenant_kb_id=workspace_id,  # 简化: 1 workspace 1 KB
           filename=file.filename,
           storage_key=storage_key,
           status="pending",
           storage_bytes=file.size,
       )
       db.add(doc)
       await db.commit()

       # 5. 异步索引
       background_tasks.add_task(
           index_document_task,
           doc.id,
           tenant_collection_name(workspace_id),
       )
       return {"id": doc.id, "status": "pending"}
   ```
4. **配额检查服务**：
   ```python
   class TenantKbService:
       async def check_can_upload(self, workspace_id: str, file_size: int):
           quota = await self.get_or_create_quota(workspace_id)
           usage = await self.get_usage(workspace_id)

           if usage["document_count"] >= quota.max_documents:
               raise HTTPException(400, f"Document count limit reached ({quota.max_documents})")
           if usage["storage_bytes"] + file_size > quota.max_storage_bytes:
               raise HTTPException(400, f"Storage quota exceeded")
           if file_size > quota.max_document_size_bytes:
               raise HTTPException(400, f"Document too large (max {quota.max_document_size_bytes} bytes)")

           # 频率限流
           recent_uploads = await self.count_recent_uploads(workspace_id, minutes=60)
           if recent_uploads >= quota.max_uploads_per_hour:
               raise HTTPException(429, f"Upload rate limit exceeded")
   ```
5. **索引流程**：
   - `index_document_task(doc_id, collection_name)` 后台任务
   - 调用 `kb_document_processor.py` 但传入 `tenant_kb_id`
   - 写入 Qdrant 时 metadata 带 `workspace_id`（二次校验）
6. **权限模型**：
   - 只有 workspace 的 admin 可以上传/删除
   - 平台 admin (super_admin) 可以管理所有 workspace
7. **删除流程**：
   - DB 软删除（status="deleted"）
   - Qdrant 同步删除对应 points
   - 配额计数减少

**验收**：
- [ ] 上传文档后能在 Qdrant 中查到
- [ ] 上传后能立即参与 KB 检索（M6 链路）
- [ ] 跨租户上传/删除被拒绝
- [ ] 删除文档时同步从 Qdrant 删除
- [ ] 配额检查生效
- [ ] 单元测试覆盖 ≥ 80%

**风险**：
- 中：上传/索引 pipeline 失败时的回滚
- 低：Qdrant 删除是异步的，可能有短暂不一致
- 中：限流需要 Redis 计数（确保分布式环境正确）

**后续衔接**：M8 E2E 测试此 API；M9 UI 集成此 API。

---

### M8: 端到端集成测试

**目标**：覆盖 B2B / B2C / 隔离 / 流式 4 大场景的自动化 E2E 测试。

**前置**：M5, M7

**涉及文件**：
- `e2e/tests/test_dify_b2b.py` (新增)
- `e2e/tests/test_dify_b2c.py` (新增)
- `e2e/tests/test_tenant_isolation.py` (新增)
- `e2e/tests/test_dify_streaming.py` (新增)
- `e2e/tests/test_dify_fallback.py` (新增 - 降级路径)
- `e2e/fixtures/dify_test_data.py` (新增 - 测试数据初始化)

**实施步骤**：
1. **测试环境**：
   - docker compose 起 Dify + Redis + Qdrant + Backend + Frontend
   - Dify 使用 mock 服务（避免真实 token 消耗）
   - Qdrant 使用临时 collection（避免污染）
2. **测试数据准备**：
   ```python
   # e2e/fixtures/dify_test_data.py
   async def setup_b2b_workspaces(db):
       workspace_a = await create_workspace("test-A", db)
       workspace_b = await create_workspace("test-B", db)
       await upload_kb_doc(workspace_a, "A-私有-充电桩型号1使用指南")
       await upload_kb_doc(workspace_b, "B-私有-充电桩型号2使用指南")
       return workspace_a, workspace_b
   ```
3. **B2B 隔离测试**：
   ```python
   async def test_workspace_a_cannot_see_workspace_b_kb():
       workspace_a, workspace_b = await setup_b2b_workspaces(db)
       # workspace A 问 "型号2 怎么用"
       response_a = await chat(workspace_a, "型号2 怎么用")
       assert "B-私有" not in response_a
       # workspace B 问 "型号1 怎么用"
       response_b = await chat(workspace_b, "型号1 怎么用")
       assert "A-私有" not in response_b
   ```
4. **B2C 测试**：
   ```python
   async def test_c2_user_uses_platform_kb():
       await setup_platform_kb("默认-充电桩通用指南")
       response = await chat(platform_workspace, "通用指南", is_c2=True)
       assert "默认-充电桩通用指南" in response
   ```
5. **流式测试**：
   ```python
   async def test_first_token_latency_under_2s():
       start = time.monotonic()
       first_token_at = None
       async for chunk in stream_chat(...):
           if chunk["type"] == "content" and not first_token_at:
               first_token_at = time.monotonic()
               break
       latency = first_token_at - start
       assert latency < 2.0  # 端到端 first token < 2s
   ```
6. **降级测试**：
   ```python
   async def test_dify_failure_falls_back_to_legacy():
       # 注入 Dify 故障
       with mock_dify_failure():
           response = await stream_chat(agent_with_dify_enabled, "hello")
       # 断言响应非空, 走 legacy 路径
       assert response.status == "success"
       assert response.path == "legacy"
   ```
7. **Tenant 隔离深度测试**：
   ```python
   async def test_cross_tenant_session_access_denied():
       # workspace A 用户查询 workspace B 的 session
       with pytest.raises(HTTPException) as exc:
           await get_session(workspace_a_user, workspace_b_session_id)
       assert exc.value.status_code in (403, 404)
   ```

**验收**：
- [ ] 5 类测试全部通过
- [ ] CI 中自动跑
- [ ] 测试报告附在 PR
- [ ] 测试数据自动清理（不污染 Qdrant）

**风险**：
- 中：CI 中启动 docker compose 时间长
- 中：Dify mock 服务需要模拟 SSE 流
- 低：测试依赖网络，CI 网络波动需处理

---

### M9: 管理 UI 集成

**目标**：在 Next.js admin 中增加 Dify 配置页面和租户 KB 管理页面。

**前置**：M5, M7

**涉及文件**：
- `frontend-nextjs/src/views/agents/AgentDifyConfig.tsx` (新增)
- `frontend-nextjs/src/views/knowledge-bases/TenantKbManagement.tsx` (新增)
- `frontend-nextjs/src/services/api.ts` (新增 Dify/KB API 客户端)
- `frontend-nextjs/src/i18n/locales/zh-CN.json` (增量)

**实施步骤**：
1. **Agent 配置页** (`AgentDifyConfig.tsx`)：
   - LLM Provider 下拉 (OpenAI / DeepSeek / Google / Dify)
   - 选 Dify 时显示：
     - Dify API Base 输入（默认填全局默认）
     - Dify API Key 输入（带"测试连接"按钮）
     - Dify Workflow ID 输入
   - 平台默认 KB 开关
   - 租户私有 KB 开关
2. **租户 KB 管理页** (`TenantKbManagement.tsx`)：
   - 文档上传组件（拖拽 / 选择，进度条）
   - 文档列表（文件名/大小/状态/上传时间）
   - 删除 / 重新索引按钮
   - 配额显示
3. **Dify 凭据测试连接 API**：
   ```python
   @router.post("/agents/{agent_id}/test-dify-connection")
   async def test_dify_connection(agent_id: str, ...):
       # 用 agent 的 Dify 凭据调用 Dify 一个无副作用的接口
       client = DifyClient(...)
       result = await client.run_workflow_blocking(
           inputs={"input_text": "ping"}, user="test-connection"
       )
       return {"success": True, "elapsed_time": result.get("elapsed_time")}
   ```
4. **i18n**：中英文双语
5. **权限**：复用现有 admin 角色 + workspace ownership 检查

**验收**：
- [ ] Agent 配置页可保存 Dify 凭据
- [ ] 凭据错误时显示明确错误信息
- [ ] 租户 KB 文档可上传/查看/删除
- [ ] 上传后 dashboard 立即可见
- [ ] UI 兼容中英文

**风险**：低。主要是前端工作量。

---

### M10: 部署与灰度

**目标**：生产部署支持 Dify 集成，灰度切换可控，监控完善。

**前置**：M8, M9

**涉及文件**：
- `docker-compose.yml` (新增 `dify-api` 和 `dify-worker`，或文档说明 Dify Cloud）
- `backend/.env.example` (Dify 配置项)
- `docs/runbook-dify.md` (新增 - 运维手册)
- `docs/deploy-dify.md` (新增 - 部署指南)

**实施步骤**：
1. **Dify 部署选择**：
   - **选项 A**：Dify Cloud（快速，但有配额和成本风险）
   - **选项 B**：Dify Community 自托管（控制力强，但需要 GPU 资源）
   - **决策**：默认推荐 Cloud，按需提供自托管 docker-compose
2. **环境变量**（`backend/.env.example`）：
   ```bash
   # Dify 配置
   DIFY_API_BASE=https://api.dify.ai/v1
   DIFY_API_KEY=app-xxxxxxxxxxxx
   DIFY_WORKFLOW_ID=
   DIFY_REQUEST_TIMEOUT=300

   # 灰度配置
   DIFY_ROLLOUT_PERCENTAGE=0
   DIFY_ROLLOUT_FORCE_AGENT_IDS=
   DIFY_ROLLOUT_AB_TEST_ENABLED=false

   # Circuit Breaker
   DIFY_CIRCUIT_BREAKER_THRESHOLD=10
   DIFY_CIRCUIT_BREAKER_TIMEOUT=60
   DIFY_CIRCUIT_BREAKER_WINDOW=60
   ```
3. **docker-compose 集成**（自托管模式）：
   ```yaml
   # docker-compose.yml 增量
   services:
     dify-api:
       image: langgenius/dify-api:1.0.0
       environment:
         - MODE=api
         - DB_DATABASE=dify
         # ...
       depends_on:
         - postgres-dify
         - redis
     dify-worker:
       image: langgenius/dify-api:1.0.0
       environment:
         - MODE=worker
       depends_on:
         - dify-api
     postgres-dify:
       image: postgres:15
       # ...
   ```
4. **灰度发布步骤**：
   - 第 1 周：`DIFY_ROLLOUT_PERCENTAGE=0`，内部测试
   - 第 2 周：`DIFY_ROLLOUT_PERCENTAGE=10`，B 客户 opt-in
   - 第 3 周：`DIFY_ROLLOUT_PERCENTAGE=50`
   - 第 4 周：`DIFY_ROLLOUT_PERCENTAGE=100`
5. **监控**（§6.1 可观测性）：
   - Prometheus 指标：`dify_request_total`, `dify_error_total`, `dify_first_token_latency_ms`
   - 告警规则：first_token_latency > 3s, error_rate > 5%
6. **Runbook**（`docs/runbook-dify.md`）：
   - 启动检查清单
   - 常见故障处理（流式中断 / KB 检索失败 / Dify 服务不可用）
   - 紧急回滚步骤
   - 联系 Dify 客服流程
7. **协议版本检查**：
   - Backend 启动时调用 `DifyClient.get_info()` 获取 Dify 版本
   - 不匹配时报警（warn，不阻塞）

**验收**：
- [ ] docker compose up 后所有服务健康
- [ ] 灰度开关能即时生效（无需重启）
- [ ] 监控指标可观测
- [ ] runbook 完整
- [ ] 回滚 < 30s

**风险**：
- 高：灰度必须有完善的回滚路径
- 中：Dify 自托管需要资源，Dify Cloud 需要配额评估

---

## §6 跨切关注

### 6.1 可观测性

**Logging 规范**：
- 每次 chat_stream 请求生成 `correlation_id`（UUID v4）
- 关键日志点：进入 Phase 1 / Phase 1 完成 / 进入 Phase 2 / 第一个 token / Phase 2 完成 / Phase 3 完成
- Dify 调用日志包含 `workflow_run_id` / `task_id` / `elapsed_time` / `status`
- API key **永不**出现在日志中（grep 验证）

**Metrics**（Prometheus 格式）：
```python
# backend/metrics/dify_metrics.py
dify_request_total = Counter(
    "dify_request_total",
    "Total Dify workflow requests",
    ["agent_id", "status"],  # status: success / failed / circuit_open
)
dify_first_token_latency_ms = Histogram(
    "dify_first_token_latency_ms",
    "Time to first token from Dify",
    ["agent_id"],
    buckets=[100, 250, 500, 1000, 2000, 5000],
)
dify_total_tokens = Counter(
    "dify_total_tokens",
    "Total Dify tokens used",
    ["agent_id", "workspace_id"],
)
```

**Tracing**：
- Dify 的 `trace_id` 透传到 Backend 日志
- 优先用 OpenTelemetry（如果项目已集成）

**告警**：
- first_token_latency p95 > 3s
- error_rate > 5%
- circuit_breaker 状态切换（OPEN/HALF_OPEN/CLOSED）

### 6.2 安全

**API key 加密**：
- 使用现有 `ENCRYPTION_KEY`（Fernet 加密）
- DB 字段类型：`LargeBinary`（存 bytes）
- 解密在 service 层（不在 API 层）
- 严禁在 `__repr__` / `__str__` / 日志 / 异常信息中打印明文

**网络隔离**：
- Backend → Dify 走 HTTPS
- 如果 Dify 自托管，部署在同一 VPC / 内网
- 不允许 Dify 公网 IP 直接访问

**SSRF 防护**：
- `DIFY_API_BASE` 必须是 allowlist 内的 URL
- 不接受用户输入作为 `DIFY_API_BASE`

**审计日志**：
- 所有 Dify 调用记录到 `WorkflowExecutionLog`
- 包含 `workspace_id` / `agent_id` / `user` / `inputs` / `outputs` / `status`
- 保留期：1 年

**租户权限**：
- 所有 `/tenant-kb/*` API 检查 workspace 权限
- 所有 `/agents/*` 修改 API 检查 ownership
- super_admin 可以跨 workspace 操作（但需审计）

### 6.3 Qdrant 命名规范

**Platform KB**：
- Collection 名：`platform_default_kb`（固定，不变）

**Tenant KB**：
- Collection 名：`tenant_kb_wsid_{md5(workspace_id)[:16]}`
- 长度限制：< 60 字符
- 字符集：`[a-z0-9_]`（hash 输出天然满足）
- 删除 workspace 时必须同步删除 collection

**Embedding 模型一致性**：
- 所有 collection 使用**同一个** embedding 模型
- 不允许不同 workspace 使用不同模型（避免 vector space 不兼容）
- 平台默认 embedding 模型在 `config.py` 配置

### 6.4 性能预算

| 指标 | 预算 | 测量方法 |
|---|---|---|
| 端到端 first token | < 2s | Histogram p95 |
| Dify workflow 平均 | < 10s | 实时监控 |
| 并发 QPS | 100 (单 Backend 实例) | 压测 |
| Qdrant 检索 | < 100ms | 监控 |
| Dify 配额 | 1M tokens/月（Cloud 起步） | 配额监控 |

### 6.5 向后兼容

**已部署 widget**：
- 现有 widget 不修改
- 后端 `/chat/stream` 端点保留 6 个月
- 新端点 `/chat/stream-v2` 与 `/chat/stream` 并存

**已有 Agent（OpenAI）**：
- 保持 `llm_provider="openai"`，行为不变
- 灰度期间这些 agent 不走 Dify

**ChatMessage 历史**：
- 不迁移历史 provider 字段
- 新增 `provider` 字段（用于分析）

**Quota 历史**：
- `monthly_token_used` 字段从 0 开始累加
- 历史 `messages_count` 仍保留

### 6.6 配置管理

**环境变量分层**：
- 平台级（环境变量）：`DIFY_API_BASE`, `DIFY_API_KEY`
- Agent 级（DB 字段）：`dify_api_base_encrypted`, `dify_api_key_encrypted`
- 灰度级（环境变量）：`DIFY_ROLLOUT_PERCENTAGE`

**热更新**：
- 灰度百分比支持热更新（不需重启 Backend）
- 实现：`Settings` 类的属性读取最新值（不使用启动时快照）

---

## §7 全局风险与回滚矩阵

| 风险 | 触发条件 | 缓解措施 | 回滚动作 | RTO |
|---|---|---|---|---|
| Dify 服务不可用 | streaming 错误率 > 5% | Circuit Breaker 自动降级 | `DIFY_ROLLOUT_PERCENTAGE=0` | < 30s |
| SSE 事件格式不兼容 | 前端报错 | E2E 测试覆盖 | git revert M5 | < 1h |
| KB 隔离失效 | tenant A 看到 tenant B 数据 | Qdrant scope_filter + 物理 collection | 立即停服修复 | < 1h |
| 灰度期间体验下降 | first_token_latency > 3s | 监控告警 | 降回低百分比 | < 1min |
| Dify workflow 改动未同步 | Dify 端改了 yml 但 Backend 不知道 | workflow 版本号 + 启动时校验 | 锁定 workflow 版本 | < 1h |
| API key 泄露 | git 扫描发现 | 立即重置 + 加密存储 | 强制重置所有 key | < 1h |
| Qdrant collection 数量爆炸 | workspace 数 > 10000 | shared collection + namespace 模式 | 切换 namespace 模式 | N/A |
| Dify Cloud 配额耗尽 | 配额监控报警 | 告警 + 切换到自托管 | 切换 Dify 部署模式 | < 4h |
| 旧端点完全弃用 | 6 个月后 | 双端点监控 | 保留旧端点 | N/A |

---

## §8 全局验收标准

- [ ] M0-M10 所有里程碑按 §5 步骤完成
- [ ] 单元测试覆盖率 ≥ 80%（统一标准）
- [ ] 集成测试全绿
- [ ] B2B / B2C / 隔离 / 流式 4 大 E2E 场景全通过（M8）
- [ ] 灰度开关可用，能在 30s 内回滚
- [ ] 监控指标可观测（Prometheus）
- [ ] 文档完整（本文档 + api-contract-dify.md + sse-event-mapping.md + 3 个 ADR + runbook-dify.md + deploy-dify.md）
- [ ] 旧 `/chat/stream` 端点保留
- [ ] 旧 OpenAI agent 行为不变（回归测试通过）
- [ ] API key 加密存储，无明文泄露
- [ ] 多语言 i18n 正常

---

## §9 跨会话交接清单

### 9.1 会话开始时 AI 必读

1. 本文档（`docs/dify-integration-plan.md`）
2. 已完成里程碑的代码：`git log --oneline -n 20` 找 `M{ID}:` 前缀的 commit
3. 当前里程碑对应的 §5 小节
4. 涉及文件清单（见 §5 中每个 M 的"涉及文件"）
5. 关键代码文件：
   - `backend/api/v1/endpoints.py` (chat_stream 在 ~1436 行, chat 在 ~1300 行)
   - `backend/services/llm_service.py` (LLMProvider 抽象)
   - `backend/services/kb_retrieval_service.py` (KB 检索)
   - `backend/models.py` (Agent / ChatSession / ChatMessage)
   - `backend/config.py` (Settings)

### 9.2 会话结束时 AI 必做

1. **更新本文件** §3.2 状态列（如有进展）
2. **更新本文件** §4 数据模型（如有字段改动）
3. **git commit** 标注 M{ID} 前缀：`git commit -m "M3: 实现 DifyProvider"`
4. **更新本文件** §8 验收 checklist
5. **更新本文件** §16 变更日志

### 9.3 状态跟踪

**M1 已完成情况**（截至 2026-06-12）：
- `M1: Agent 加 Dify 配置字段`（task #2）已 completed
- 这对应 §5 M3 的部分内容，**不算 M1 完成**
- 真实 M1（workflow 改造）尚未开始

---

## §10 应急与运维

### 10.1 故障分类

| 级别 | 描述 | 响应 SLA | 负责人 |
|---|---|---|---|
| P0 | Dify 完全不可用 + Circuit Breaker 全开 | 15min | 平台 SRE |
| P1 | Dify 错误率 > 20% | 30min | 平台 SRE |
| P2 | first_token latency > 5s | 2h | 平台 SRE |
| P3 | 单租户上传失败 | 1 day | 平台 SRE |

### 10.2 应急操作清单

**Dify 完全不可用**：
1. 立即 `DIFY_ROLLOUT_PERCENTAGE=0`
2. 验证所有流量走 legacy LLM
3. 联系 Dify 客服（如果是 Cloud）
4. 检查 Circuit Breaker 状态
5. 等待恢复后逐步恢复灰度

**降级路径失败**：
1. 检查 legacy LLM provider 是否可用（API key / 配额）
2. 临时回滚到上一个 commit
3. 评估影响范围

**租户数据泄露**：
1. 立即停服
2. 通知受影响租户
3. 修复后从备份恢复
4. 复盘 + 加固

### 10.3 健康检查

```python
# backend/api/v1/health.py 增量
@router.get("/health/dify")
async def dify_health() -> dict:
    """Dify 服务健康检查."""
    try:
        client = DifyClient(...)
        info = await client.get_app_info()
        return {
            "status": "healthy",
            "dify_version": info.get("version"),
            "workflow_id": info.get("workflow_id"),
            "circuit_state": circuit.state,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

### 10.4 Runbook 索引

完整 runbook 见 `docs/runbook-dify.md`（M10 产出），包含：
- 启动检查清单
- 监控告警响应
- 常见故障 FAQ
- 紧急回滚操作步骤
- 联系 Dify 客服流程

---

## §11 数据迁移

### 11.1 现有数据影响范围

| 表 | 影响 | 迁移 |
|---|---|---|
| `agents` | 需补 `llm_provider` 字段 | Alembic 自动加列，默认 `openai` |
| `chat_messages` | 无结构变化 | 不迁移 |
| `quotas` | 无结构变化 | 不迁移 |
| `kb_documents` | 需补 `workspace_id`, `tenant_kb_id` | Alembic 自动加列，NULL 默认 |

### 11.2 迁移脚本

```python
# alembic/versions/xxxx_add_dify_and_tenant_kb.py
def upgrade():
    op.add_column("agents", sa.Column("llm_provider", sa.String(20), default="openai"))
    op.add_column("agents", sa.Column("dify_api_base_encrypted", sa.LargeBinary, nullable=True))
    # ... 其他字段

    op.add_column("kb_documents", sa.Column("workspace_id", sa.String(36), nullable=True))
    op.add_column("kb_documents", sa.Column("tenant_kb_id", sa.String(36), nullable=True))
    op.create_index("ix_kb_documents_workspace_id", "kb_documents", ["workspace_id"])

    op.create_table("tenant_knowledge_bases", ...)
    op.create_table("tenant_kb_quotas", ...)
    op.create_table("workflow_execution_logs", ...)
```

### 11.3 数据兼容性

- 现有 OpenAI agent：行为完全不变
- 现有 KB 文档：`workspace_id=NULL` 表示"平台默认 KB"
- 现有 chat_messages：不变

### 11.4 双写期

迁移期间（建议 1 周）：
- 旧 LLM 路径继续工作
- 新 Dify 路径灰度
- `ChatMessage` 不写 `provider` 字段（保持兼容）
- 1 周后稳定后补 `provider` 字段

---

## §12 安全与合规

### 12.1 API Key 管理

**存储**：
- DB 字段：`dify_api_key_encrypted: LargeBinary`
- 加密算法：Fernet（`ENCRYPTION_KEY` 环境变量）
- 备份：DB 备份包含加密 key，恢复后需重新配置 `ENCRYPTION_KEY`

**访问控制**：
- 只有 `agent_key_service.py` 能解密
- 不在 API 响应中返回 key
- 不在日志中打印 key
- `__repr__` / `__str__` 屏蔽 key

**轮换**：
- 平台支持手动轮换 key
- 旧 key 保留 24h 过渡期（如果实现）

### 12.2 网络安全

- Backend → Dify：HTTPS 强制
- Dify API Base 必须 allowlist（防止 SSRF）
- 自托管 Dify：必须部署在 VPC 内
- WAF：限流 + 防滥用

### 12.3 审计日志

- 所有 Dify 调用记录到 `WorkflowExecutionLog`
- 字段：user / agent / workspace / inputs / outputs / status / timestamp
- 保留期：1 年
- 查询 API：仅 super_admin 可访问

### 12.4 数据合规

- 用户数据存储在 Backend DB（本地）
- Dify 端不存储用户对话历史（Dify Cloud 默认 0 留存）
- 数据出境：取决于 Dify Cloud region 选择
- GDPR：用户数据删除时同时删除 Qdrant 对应 points

### 12.5 配额防滥用

- Per-tenant 上传配额（M7）
- Per-tenant 消息配额（已有）
- Per-IP rate limit（已有）
- Dify 调用频率监控

---

## §13 成本与计费

### 13.1 Dify Cloud 成本（参考）

- Dify Cloud Sandbox：$0/月（限制功能）
- Dify Cloud Professional：$59/月 + token 费用
- Dify Cloud Team：$159/月 + token 费用
- Token 费用：~¥0.0008/1K tokens（`doubao-seed-2.0-lite`）

**预估**：
- 1000 月活用户，每人 100 消息/月，每消息 1K tokens
- 月 token：100M tokens
- Token 成本：~¥80/月
- 平台版固定费：$59/月
- 总成本：~$150/月

### 13.2 Dify 自托管成本

- 服务器：4 vCPU + 16GB RAM（最低配置）
- 月固定成本：~$100/月（云主机）
- Token 费用：直接付给 LLM provider（如火山引擎）
- 总成本：~$150-300/月（取决于流量）

### 13.3 B 客户计费公式

**计费维度**：
- 月活用户数（MAU）
- 月消息数
- 月 token 用量

**计费模式**（建议）：
- 基础订阅：¥X/月（含 N 消息 + M tokens）
- 超量：每消息 ¥0.01 或每 1K token ¥0.001
- 大客户：定制

**实现**：
- M5 Phase 3 累加 `agent.monthly_token_used`
- M10 增加 `BillingService.aggregate(workspace_id, period)` 报表
- 月底生成账单

### 13.4 成本监控

- 平台成本：每日聚合
- B 客户用量：每日聚合
- 告警：单日成本 > 阈值

---

## §14 文档交付物清单

### 14.1 内部文档

| 文档 | 路径 | 何时产出 | 受众 |
|---|---|---|---|
| 本方案 | `docs/dify-integration-plan.md` | M0 | 开发团队 |
| API 契约 | `docs/api-contract-dify.md` | M0 | 开发团队 |
| SSE 事件映射 | `docs/sse-event-mapping.md` | M0 | 开发团队 |
| ADR-0001 | `docs/adr/0001-dify-llm-engine.md` | M0 | 架构师 |
| ADR-0002 | `docs/adr/0002-tenant-isolation.md` | M0 | 架构师 |
| ADR-0003 | `docs/adr/0003-workflow-simplification.md` | M0 | 架构师 |
| 部署指南 | `docs/deploy-dify.md` | M10 | SRE |
| 运维手册 | `docs/runbook-dify.md` | M10 | SRE |
| 监控告警配置 | `docs/monitoring-dify.md` | M10 | SRE |

### 14.2 B 客户管理员手册

| 文档 | 路径 | 何时产出 | 受众 |
|---|---|---|---|
| Dify 配置指南 | `docs/customer/dify-config.md` | M9 | B 客户 admin |
| 租户 KB 管理 | `docs/customer/tenant-kb.md` | M9 | B 客户 admin |
| 配额说明 | `docs/customer/quota.md` | M7 | B 客户 admin |

### 14.3 C 端 FAQ

- `docs/customer/faq-c2.md`（M9）
- 内容：常见问题、Widget 集成方法、隐私说明

### 14.4 README 更新

- 根 `README.md` 增量：Dify 集成说明
- `backend/README.md` 增量：DifyClient / DifyProvider 使用说明
- `frontend-nextjs/README.md` 增量：Dify 配置 UI 说明

---

## §15 关键参考

### 15.1 内部代码

| 文件 | 作用 | 行数参考 |
|---|---|---|
| `backend/api/v1/endpoints.py` | chat_stream 主端点 | ~1700 行 |
| `backend/services/llm_service.py` | LLMProvider 抽象 | ~500 行 |
| `backend/services/kb_retrieval_service.py` | KB 检索 | ~200 行 |
| `backend/services/vision_service.py` | PR13 图片描述 | ~150 行 |
| `backend/services/asr_service.py` | PR13 语音转写 | ~150 行 |
| `backend/models.py` | Agent / ChatSession / ChatMessage | ~800 行 |
| `backend/config.py` | Settings | ~150 行 |
| `backend/main.py` | FastAPI app 入口 | ~100 行 |
| `china_charge_kf/backend/app_dify/dify_client.py` | Dify 客户端参考 | ~150 行 |
| `china_charge_kf/Workflow-China_charge_seriver-draft-9380/workflow/workflow.yml` | Dify v1 workflow | ~800 行 |

### 15.2 外部参考

- Dify 官方文档：https://docs.dify.ai/
- Dify 源码：https://github.com/langgenius/dify
- Dify Workflow API 说明：见项目内 `china_charge_kf/dify_workflow_api说明文档.md`
- CLAUDE.md：本仓库根目录，约束规则

### 15.3 Memory 中的相关记录

- `basjoo-second-pass-decisions.md` - 二开决策
- `basjoo-pr1-to-pr10-abandoned.md` - 早期 PR 放弃
- `basjoo-venv-path.md` - venv 路径

---

## §16 变更日志

| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-06-12 | v1.0 | 初版设计基线，定义 M0-M10 里程碑 | AI |
| 2026-06-12 | v2.0 | 返工版：修复 27 个问题，新增 5 个章节（§10-14），增加术语表、决策日志、依赖图、统一单测覆盖率至 80%、统一节点 ID 锁、M5 改为新建端点 + 灰度粘性 + 降级、PR13 简化为单 LLM、增加 §6 跨切关注、扩展 §4 数据模型 | AI |
| 2026-06-12 | v2.0 | 新增 ADR 章节引用、§9 跨会话交接清单细化、§11 数据迁移、§12 安全合规、§13 成本计费、§14 文档交付物 | AI |

---

## §17 评审签字

| 角色 | 姓名 | 签字 | 日期 |
|---|---|---|---|
| 架构师 |  |  |  |
| 后端 Lead |  |  |  |
| 前端 Lead |  |  |  |
| SRE |  |  |  |
| 产品 |  |  |  |

> 本文档必须经评审签字后方可作为后续 M1-M10 实施的基线。
