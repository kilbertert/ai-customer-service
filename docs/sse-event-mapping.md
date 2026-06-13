# SSE 事件映射：Dify → Backend → Frontend

> 状态：v1（M0 产出）
> 关联：[`docs/api-contract-dify.md`](./api-contract-dify.md) ｜ [`docs/dify-integration-plan.md` §6.3](./dify-integration-plan.md) ｜ [ADR 0001](./adr/0001-dify-llm-engine.md) ｜ [ADR 0003](./adr/0003-workflow-simplification.md)
> 适用范围：M4（`DifySseAdapter`）和 M5（`/chat/stream-v2`）

---

## 0. 目的

Dify Workflow streaming API 与现有 Backend → Frontend SSE 协议**字段名 / 事件粒度均不同**。本文档规定：

1. Dify 原始 SSE 事件的字段定义（来源：Dify 官方文档 + 工作流 `workflow.yml` 行为）
2. Backend `DifySseAdapter`（M4 实现）将 Dify 事件转换为 Backend 内部 `DifyStreamEvent` 的规则
3. Backend `SseProxyLayer`（M4 实现）将 `DifyStreamEvent` 进一步转换为现有 `/chat/stream` 协议 SSE 的规则
4. 边界场景（多分支、variable-aggregator、TTS、超时、断流）的处理

读者：M4-M5 实现工程师；前端/Widget 工程师可参考 §3 确认 `/chat/stream-v2` 输出形态与 v1 兼容。

---

## 1. 概念分层

```
┌─────────────────────────────────────────────────────┐
│  Dify Cloud                                         │  ← 上游，外部依赖
│  (text/event-stream, event=workflow_started/...)   │
└─────────────────┬───────────────────────────────────┘
                  │ raw bytes
                  ▼
┌─────────────────────────────────────────────────────┐
│  DifySseDecoder  (M4)                               │  ← 解析 + 分类
│  bytes → DifyStreamEvent (Union)                    │
└─────────────────┬───────────────────────────────────┘
                  │ 强类型事件
                  ▼
┌─────────────────────────────────────────────────────┐
│  SseProxyLayer  (M4)                                │  ← 业务翻译
│  DifyStreamEvent → backend sse_event() 字符串      │
│  (event: sources / content / done / error)         │
└─────────────────┬───────────────────────────────────┘
                  │ 字符串
                  ▼
┌─────────────────────────────────────────────────────┐
│  Frontend / Widget (已有 consumeStream 解析器)      │  ← 既有协议，零修改
└─────────────────────────────────────────────────────┘
```

**不变量**：Frontend / Widget **不感知** Dify 存在。M4 的 `SseProxyLayer` 必须保证 v1 的全部事件类型与字段（`sources`/`content`/`done`/`error`/`thinking`/`thinking_done`）字面兼容。

---

## 2. Dify 原始事件（Dify 侧）

### 2.1 事件清单（Dify 官方支持，v1.x workflow 模式）

| 事件名 | 触发时机 | 关键字段 | v2 是否使用 |
|--------|---------|---------|----------|
| `workflow_started` | workflow 启动 | `task_id`, `workflow_run_id`, `data.id` | ✅ 用作 SseProxyLayer 启动信号 |
| `node_started` | 单个节点开始 | `node_id`, `node_type`, `data.title` | ❌ 忽略（debug only） |
| `text_chunk` | LLM 节点产出 token | `text`, `from_variable_selector` | ✅ **核心**：映射到 `content` |
| `node_finished` | 单个节点结束 | `node_id`, `status`, `outputs`, `elapsed_time` | △ 仅监控耗时（debug log） |
| `workflow_finished` | workflow 整体结束 | `status`, `outputs`, `elapsed_time`, `total_tokens` | ✅ 映射到 `done` |
| `ping` | 5-10s 间隔 | `(空 data)` | ✅ 透传为 SSE 注释行保活 |
| `tts_message` | TTS 节点 | `audio`, `meta` | ❌ v2 workflow 不含 TTS 节点 |
| `human_input_required` | 人类输入节点 | `form_id`, `form_fields` | ❌ v2 workflow 不含此节点 |

### 2.1.1 事件类型双源解析（M0.5 协议发现 D5 修正）

> **supersede §2.1**：M0.5 探针（`V9_streaming_event_count=16`，见 `docs/m0.5-protocol-findings.md` §5.1）发现 Dify SSE 实际有两种事件类型编码格式，**不能**只看 `event:` 行：

| 编码 | 形态 | 例子 |
|------|------|------|
| **格式 A**（心跳保活） | `event:` 行写事件名，`data:` 为空 | `event: ping\ndata: \n\n` |
| **格式 B**（业务事件） | `event:` 行**省略或为空**，事件类型在 `data:` JSON 的 `event` 字段 | `data: {"event":"text_chunk","data":{...}}\n\n` |

`DifySseDecoder` **必须**双源取事件类型：

```python
def parse_event_type(sse_line_event: str | None, data_json: dict) -> str:
    # 优先 event: 行
    if sse_line_event and sse_line_event.strip():
        return sse_line_event.strip()
    # fallback 到 data.event JSON 字段
    return data_json.get("event", "unknown")
```

**不接受**只读 `event:` 行的实现——M0.5 实测业务事件（`text_chunk` / `workflow_started` / `node_started` 等 16 个事件中 15 个）**全部走格式 B**。仅 `ping` 走格式 A。

### 2.2 关键事件 payload 详解

#### 2.2.1 `text_chunk`（流式核心）

```json
{
  "event": "text_chunk",
  "task_id": "task-uuid",
  "workflow_run_id": "run-uuid",
  "data": {
    "node_id": "2007",
    "node_type": "llm",
    "index": 3,
    "text": "请",
    "from_variable_selector": ["2007", "text"]
  }
}
```

| 字段 | 含义 | Backend 处理 |
|------|------|------------|
| `data.text` | 本次增量文本 | **必读**：拼接为 Assistant 回复 |
| `data.from_variable_selector` | 来源变量路径 | **必读**：形态由 workflow 结构决定（见下表） |
| `data.node_id` | 节点 ID | 冗余校验 |
| `data.index` | 块序号 | 监控用，不参与业务逻辑 |

**`from_variable_selector` 形态（**M0.5 协议发现 D6 修正**）**：

> **supersede §6.6**：「`from_variable_selector` 永远 = `["2007", "text"]`」是错的。M0.5 v1 实测 selector 形态随 workflow 拓扑变化：

| workflow 拓扑 | 形态 | 第 [0] 项 | 第 [1] 项 | 例子 |
|--------------|------|---------|---------|------|
| **v1**（10 节点 / 含 variable-aggregator 1014） | `[aggregator_id, output_var_name]` | 聚合器节点 ID | end 节点配置的 output 变量名 | `["1014", "output"]`（M0.5 实测，16 个事件中的 1 个 text_chunk） |
| **v2**（3 节点 / 单 LLM 链） | `[llm_node_id, "text"]` | LLM 节点 ID | 字面量 `"text"` | `["2007", "text"]`（M1.5 待实测） |

**Backend 节点过滤规则**（覆盖 v1/v2 兼容）：
- **白名单 + 形态校验**：`SseProxyLayer` 不依赖 selector 第 [1] 项的字面值；改为校验 `[0]` 是否在白名单 `{ "2007" }`（v2 单 LLM）/ `{ "1007", "1010", "1013", "1014" }`（v1 多 LLM）。
- **未知节点**：`SseProxyLayer` log warning + 丢弃（见 §6.6）。
- **白名单由 `DIFY_WORKFLOW_VERSION` 配置项控制**（M2 引入）：`v1` / `v2` 切换时无需改代码。

**关键事实**：Dify 的 LLM 节点会**逐 token 产出 `text_chunk`**，无需等整个 LLM 完成。Variable Aggregator（仅 v1）在 LLM 节点 `node_finished` 之后才发 `text_chunk`（M0.5 实测事件 12 出现在事件 10 `node_finished(1013)` 之后）。v2 单 LLM 节点无 aggregator，`text_chunk` 序列可**直接**映射为流式输出，**不需要等待**。

#### 2.2.2 `workflow_finished`

```json
{
  "event": "workflow_finished",
  "task_id": "task-uuid",
  "workflow_run_id": "run-uuid",
  "data": {
    "id": "run-uuid",
    "workflow_id": "app-uuid",
    "status": "succeeded",     // succeeded | failed | stopped
    "outputs": { "output": "请先检查供电是否正常..." },
    "error": null,
    "elapsed_time": 2.34,
    "total_tokens": 312,
    "total_steps": 1,
    "created_at": 1717000000,
    "finished_at": 1717000002
  }
}
```

`outputs.output` 是 v2 workflow 唯一对外输出（`end` 节点的 `value_selector: ["1014", "output"]` —— 注意：v2 简化为单 LLM 节点后 `1014` → `2015` 即 end 节点；详见 ADR 0003）。

**SseProxyLayer 处理**：
- 状态 `succeeded` → 触发 `done` SSE
- 状态 `failed` 且 `error` 非空 → 触发 `error` SSE（code=`DIFY_BAD_REQUEST` 或 `DIFY_UPSTREAM`）
- 状态 `stopped` → 触发 `done` SSE 但 `usage=null`（视作用户取消）
- 校验 `outputs.output` 与流式累计文本一致性：v2 阶段 M0.5 联调验证（详见 §6）

#### 2.2.3 `ping`

```http
event: ping
data:
```

Dify 默认每 ~10s 发送一次。`SseProxyLayer` 转换为 SSE 注释行（`: ping\n\n`）以保活，且**不**推给前端。Widget 已有自己的 90s 读超时（见 `BasjooWidget.tsx:2407`），不需要保活事件。

#### 2.2.4 `workflow_started` / `node_started` / `node_finished`

均不直接产生 Backend SSE 事件。`DifySseDecoder` 内部记录：
- `workflow_started` → 触发 SseProxyLayer 内部状态从 `IDLE` → `STREAMING`
- `node_started`/`node_finished` → 仅 log，不影响外发事件

---

## 3. Backend SSE 事件（Frontend 侧，v1 已存在）

> 这些是 `widget/src/BasjooWidget.tsx` 中 `consumeStream` 已识别的 6 种事件。v2 端点必须**严格**沿用。

| 事件 | 触发 | payload | 来源（v1） |
|------|------|---------|----------|
| `sources` | Phase 1 KB 检索完成后 | `{"sources": [{type, title, url, snippet, ...}]}` | `chat_stream` L1490 行 |
| `thinking` | 流式 chunk 超 15s 等待 | `{"elapsed": int}` | `chat_stream` L1581 |
| `thinking_done` | 首个 content 到达 | `{}` | `chat_stream` L1599 |
| `content` | LLM 每段 token | `{"content": "..."}` | `chat_stream` L1600 |
| `done` | 流结束且成功持久化 | `{message_id, session_id, usage, taken_over, attachments}` | `chat_stream` L1672 |
| `error` | 流结束但失败 | `{error, code}` | `chat_stream` L1518, L1648, L1686 |

**Frontend 解析器关键分支**（节选自 `consumeStream`）：
- `event === 'sources'` → 缓存到 `currentStreamSources`
- `event === 'thinking'` → 启动转圈动画
- `event === 'thinking_done'` → 关闭转圈
- `event === 'content'` → 追加到流式消息 DOM
- `event === 'done'` → finalize 流（替换 reference 链接、推入 `this.messages`）
- `event === 'error'` → throw → 走错误 UI

---

## 4. 映射表（Dify → Backend SSE）

| Dify 事件 | Backend SSE 事件 | 转换规则 |
|----------|----------------|---------|
| `workflow_started` | （不发） | 仅触发内部 `STREAMING` 状态 |
| `node_started` | （不发） | log only |
| `text_chunk` (text 非空) | `content` | `data: {"content": <data.text>}` |
| `text_chunk` (text 为空) | （不发） | Dify 偶发空 chunk，丢弃 |
| `node_finished` (llm 节点) | `thinking_done` | **首次** LLM 节点完成时发 `{}` |
| `node_finished` (其他) | （不发） | log only |
| `workflow_finished` (succeeded) | `done` | 见 §5 拼装 |
| `workflow_finished` (failed) | `error` | `code=DIFY_UPSTREAM`，`error=data.error or "Dify workflow failed"` |
| `workflow_finished` (stopped) | `done` | `usage=null`，标记 `stopped=true`（Backend 内部用，不外发） |
| `ping` | SSE 注释 | `": ping\n\n"`，不参与事件流 |
| `tts_message` | （不发） | v2 不含 TTS，丢弃 |
| `human_input_required` | `error` | `code=DIFY_BAD_REQUEST`，`error="unsupported node triggered"`（告警：v2 workflow 不应包含此节点） |
| **（协议级断流）** | `error` | `code=DIFY_TIMEOUT` 或 `DIFY_UPSTREAM` |

**第一个 `content` 之前的 `thinking` 事件**：v2 中**不发** `thinking` 事件。理由：Dify 流式首字延迟通常 < 2s，前端转圈动画无必要。若 M8 e2e 测试发现首字延迟偏高，可在 v2.1 中按 Phase 1 完成时刻延迟 3s 再补发 `thinking`（参见 M5 验收点 §6.2）。

---

## 5. `done` 事件 payload 拼装

Dify `workflow_finished` 不含 `message_id`/`session_id`/`attachments` —— 这些是 Backend 自己的领域对象。因此 `SseProxyLayer` 在收到 `workflow_finished` 后**不能**立即发 `done`，而是要等：

```
1. SseProxyLayer 收集 Dify workflow_finished（拿到 output_text + tokens + elapsed）
2. SseProxyLayer 触发 DifySseAdapter 的 on_workflow_finished 回调
3. 回调方（chat_stream_v2 端点）：
   a. Phase 3: 持久化（写入 ChatMessage + ChatSession + 扣 quota）
   b. 取到 assistant_message.id
   c. 组装 done payload
   d. yield sse_event("done", payload)
```

**done payload 字段**（与 v1 完全一致）：
```json
{
  "message_id": 1234,
  "session_id": "sess_xxx_yyy",
  "usage": {
    "prompt_tokens": 120,
    "completion_tokens": 56,
    "total_tokens": 176
  },
  "taken_over": false,
  "attachments": [
    {"id": "att_xxx", "kind": "image", "mime_type": "image/jpeg",
     "filename": "photo.jpg", "size_bytes": 184320, "url": "/api/v1/chat/attachments/att_xxx/file",
     "status": "uploaded", "preview_url": "", "duration_ms": null}
  ]
}
```

字段来源：

| 字段 | 来源 |
|------|------|
| `message_id` | Phase 3 持久化返回的 `ChatMessage.id` |
| `session_id` | `ChatSession.session_id`（来自 Phase 1） |
| `usage.prompt_tokens` | `data.total_tokens` 减去估读的 `completion_tokens`（Dify 只给 total） |
| `usage.completion_tokens` | 同上反向计算；若不可得则取 `None` |
| `usage.total_tokens` | `data.total_tokens` |
| `taken_over` | 始终 `false`（v2 阶段未接入人工接管接管 v2 路径） |
| `attachments` | Phase 1 收集的 `attachments_payload`（与 v1 同源） |

**注**：Dify 不区分 prompt/completion tokens，仅给 `total_tokens`。Backend 在 `usage` 中**用估算拆分**（如 `completion = min(total, len(output)/2)`），同时通过 `total_tokens` 保留准确值给账单模块。若需精确拆分，M9 可选接入 Dify usage API（v2 阶段不实施）。

---

## 6. 边界场景处理

### 6.1 Dify 返回空 workflow

- **触发**：`workflow_finished.status=succeeded` 但 `outputs.output` 为空字符串
- **现象**：前端收到 `done` 时 `content` 全空
- **处理**：`SseProxyLayer` 检测到 `outputs.output` 为空且累计 `text_chunk` 文本也为空时，主动发 `content` 事件 payload `{"content": "抱歉，我暂时无法回答这个问题，请换个方式提问。"}`（取 `agent.restricted_reply` 或默认），再发 `done`
- **复现条件**：v2 workflow LLM 节点 `max_tokens=4096` 但 LLM 端返回 0 token（理论场景）

### 6.2 长耗时首字延迟

- **触发**：`workflow_started` 后超过 15s 无任何 `text_chunk`
- **现象**：前端无任何反馈，用户误以为卡死
- **处理**：`chat_stream_v2` 端点内部启动 3s 计时器；超过则发 `thinking` 事件 `{"elapsed": 3}`，每 3s 递增一次；收到第一个 `text_chunk` 时发 `thinking_done`
- **可关闭**：`agent.disable_streaming_thinking = true`（M5 引入；默认 false）

### 6.3 客户端断连

- **触发**：Widget 关闭 / 页面跳转触发 `streamAbortController.abort()`
- **现象**：Backend 端 `StreamingResponse` 抛出 `ClientDisconnect`
- **处理**：FastAPI 自动关闭生成器。`DifySseAdapter` 通过 `try/finally` 关闭 Dify HTTP 连接（Dify 100s 限制不会被白白消耗）
- **持久化**：**仍执行** Phase 3，因为内容已产生，DB 写入可让用户在 `/chat/messages` 中看到历史

### 6.4 Dify 100s 切断

- **触发**：Dify Cloud 工作流总时长 ≥ 100s
- **现象**：Dify 返回 `event: workflow_finished` 携带 `status=succeeded` 但 `outputs.output` 可能截断
- **处理**：
  1. `SseProxyLayer` 正常发出 `done`（含部分内容）
  2. 持久化记录的 `reply` 字段是已收到的累计文本
  3. 日志中 warn：`workflow_finished but elapsed > 100s, output may be truncated`
- **预防**：v2 LLM 节点 `max_tokens=4096` + temperature=0.5，正常 < 5s

### 6.5 Dify 工作流异常（节点失败 + 平台层错误，M1.5 v2 修订）

> 触发场景分两类：(a) **HTTP 层错误**（workflow 启动前被 Dify 平台拦截，4xx），(b) **workflow 内部节点失败**（HTTP 200 但 `data.status=failed`）。v1 平台宽松，假 file_id 走 graceful 降级；v2 平台严格（S4/S6 实测），**`SseProxyLayer` 必须在 platform-4xx 层就拦截，不要等 `workflow_finished`**。

#### 6.5.1 HTTP 层错误（v2 平台严格校验新增，M1.5 S4/S6 实测）

| HTTP | `code` 字段 | `message` 关键字 | 映射 SSE `error.code` | 触发场景（M1.5 实测） |
|------|------------|----------------|---------------------|---------------------|
| 401  | `unauthorized` | `Access token is invalid` | `DIFY_AUTH` | API key 失效/错误（S4） |
| 400  | `invalid_param` | `must be a string` / `must be a file` | `DIFY_BAD_REQUEST` | yml 声明与值类型不匹配（schema mismatch） |
| 400  | `invalid_param` | `Invalid upload file` | `DIFY_BAD_REQUEST` | `upload_file_id` 在 Dify 平台不存在（平台层 file 校验，S6） |

**响应 body 形态**（S4/S6 实测）：

```json
{"code": "unauthorized", "message": "Access token is invalid", "status": 401}
{"code": "invalid_param", "message": "Invalid upload file", "status": 400}
```

**处理要点**：
- 401 不重试（v1 既有逻辑），触发 Circuit Breaker
- 400 是契约不匹配（M2 PR10 锁定 yml `type=file-list` + array），**通常意味着 Backend 序列化错误**，需立即排查（不降级、不重试）
- SSE `error` 事件 payload 形态：`{"error": "<data.message or friendly>", "code": "<mapped>"}`

#### 6.5.2 workflow 内部节点失败

- **触发**：`workflow_finished.status=failed` 且 `data.error` 非空
- **现象**：Dify 端 workflow 已启动但运行中失败
- **处理**：发 `error` SSE 事件，code 由 `data.error` 模式匹配：
  - 含 `PluginInvokeError` → `DIFY_UPSTREAM`（**v2 S6b 新增**：LLM 插件失败，如 volcengine Ark 拒收 1×1 PNG）
  - 含 `dataset` / `dataset_id` → `DIFY_BAD_REQUEST`（dataset 配置错误）
  - 含 `model` / `quota` / `rate_limit` → `DIFY_UPSTREAM`
  - 含 `auth` / `token` → `DIFY_AUTH`
  - 其它 → `DIFY_UPSTREAM`
- **告警**：所有 `failed` 触发 Prometheus counter `dify_workflow_failures_total{error_class}`

### 6.6 Variable Aggregator 多分支残留风险（ADR 0003 已规避）

- v2 workflow 锁定为单 LLM 节点，**不存在**多分支
- **v1 → v2 selector 形态变化**（M0.5 协议发现 D6 修正）：
  - v1 有 variable-aggregator 1014，selector = `["1014", "output"]`（实测）
  - v2 无 aggregator，selector 预测 = `["2007", "text"]`（M1.5 待实测确认）
- **防御性编程（v1/v2 通用）**：`SseProxyLayer` 不假设 selector 第 [1] 项字面值；改用节点 ID 白名单（见 §2.2.1 形态表）：
  - v2 白名单：`{"2007"}`（仅 LLM 节点）
  - v1 白名单：`{"1007", "1010", "1013", "1014"}`（含 aggregator）
  - 白名单由 `DIFY_WORKFLOW_VERSION` 环境变量控制（M2 引入）
- 收到非白名单节点的 `text_chunk` 时 log warning 并丢弃（绝不让 KB 节点 / HTTP 节点 / Code 节点的输出污染 Assistant 回复）

### 6.7 Dify `tts_message` 事件意外出现

- v2 workflow 不含 TTS 节点，理论上不会出现
- 若 M8 e2e 测试发现 Dify 升级引入此事件 → `SseProxyLayer` 直接丢弃（不映射到任何 Backend 事件）
- 日志 warn：`unsupported dify event tts_message; v2 workflow should not include TTS nodes`

### 6.8 网络层断流（reader 收到 EOF 但无 `workflow_finished`）

- **触发**：Dify 进程崩溃 / TCP 断开 / nginx 5xx
- **现象**：流中途无新事件
- **处理**：
  1. `DifySseDecoder` 检测到 reader 关闭但内部状态 ≠ `FINISHED`
  2. 抛 `DifyClientError(code="STREAM_BROKEN")`
  3. `SseProxyLayer` 捕获后发 `error` SSE，code=`DIFY_UPSTREAM`
  4. Circuit Breaker 记录一次失败（向 OPEN 方向推）

### 6.9 workflow `status=succeeded` 但 `outputs[output]` 为空（M0.5 D5 修正）

> **supersede §6.1**：§6.1 处理 `outputs.output=""` 字符串空的场景。本节处理更隐蔽的失败模式——Dify if-else / 缺失输入时的**优雅降级**：workflow 整体 `status=succeeded`，`outputs` dict 存在但**不包含** `output` 键，或 `output` 值为 `None` / 嵌套 dict / 非字符串。

**触发条件**（M0.5 V10b 实测）：
- Dify workflow 含 if-else 路由 + 缺失关键输入（如 image=null 时跳过 image 分支）
- workflow 走通 fallback 分支但 fallback 节点未定义 `output` 变量
- 响应形态：`{"status": "succeeded", "outputs": {<其他键>}, "total_tokens": <数字>, "elapsed_time": <数字>}`，**无** `output` 键

**v1 实测样本**（V10b 假 file_id）：
```json
{
  "event": "workflow_finished",
  "data": {
    "status": "succeeded",
    "outputs": {"text": "fallback answer..."},  // 注意：键是 "text" 不是 "output"
    "total_tokens": 1274,
    "elapsed_time": 4.2
  }
}
```

**处理**（参考 `docs/api-contract-dify.md` §4.2.1 `extract_output_text`）：
1. `DifyClient.run_workflow` 收到 `workflow_finished` 后**不**只看 `data.status`（v1 V10b 反例证明 status=succeeded ≠ 有可用输出）
2. 调用 `extract_output_text(data, output_key="output")`：
   - 主键 `outputs[output]` 命中 → 返回
   - 主键未命中 → 退化搜索 `["output", "answer", "result", "text", "message", "content"]`
   - 全未命中 → 返回 `None`
3. 返回 `None` 时：
   - `DifyClient` 抛 `DifyError(code="DIFY_BAD_OUTPUT")`（见 `api-contract-dify.md` §4.2.2）
   - `SseProxyLayer` 捕获后发 `error` SSE：`{"error": "Dify workflow succeeded but output is empty", "code": "DIFY_BAD_OUTPUT"}`
   - **不**走 §6.1 兜底文案（避免给用户"AI 拒答"假象；这是平台错误，不是模型拒答）

**SseProxyLayer 必须**：
- 校验 `outputs[output]` 字段的存在性，不止非空校验
- 对 status=succeeded + outputs 无 output 键的响应，**视为失败**而非成功

### 6.10 `<think>...</think>` 块在 `text_chunk` 阶段就需 strip（M0.5 D7 修正）

> **supersede §3 / §5 隐含假设**：「`<think>` 块只在 `workflow_finished.outputs.output` 出现，strip 逻辑可以放 done 阶段兜底」是错的。M0.5 实测 v1 流式增量推送时 `text_chunk.data.text` **也含** `<think>` 块。

**v1 实测样本**（V9 事件 12 text_chunk）：
```json
{
  "event": "text_chunk",
  "data": {
    "text": "<think>...</think><think>...</think><think>\n\n</think>您好呀~ ...",
    "from_variable_selector": ["1014", "output"]
  }
}
```

**问题**：
- v1 LLM 模型 `doubao-seed-2-0-lite` 是 thinking-enabled，CoT 泄露在**流式** `text_chunk` 中
- 若在 `done` 阶段才 strip，前端已经把 `<think>...</think>` 渲染到 DOM（视觉污染 + 干扰 streaming 动画）
- 累计文本 vs 最终文本不一致：流式拼出的字符串含 `<think>` 块，done payload 的 `usage` 估算会偏高

**处理**（`SseProxyLayer` 在 `text_chunk` 路径）：
1. 每个 `text_chunk` 的 `data.text` **先 strip 再 yield**：
   ```python
   import re
   _THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
   def _strip_thinking(s: str) -> str:
       return _THINK_RE.sub("", s)
   ```
2. `text_chunk` 处理流程：
   ```python
   if event_type == "text_chunk":
       raw = payload["data"]["text"]
       clean = _strip_thinking(raw)
       if clean:  # 全是 think 块时 clean 为空字符串
           yield sse_event("content", {"content": clean})
   ```
3. `done` 阶段的 `outputs.output` 同样 strip（与 v1 `response_parser.py:9` 一致）
4. **空 chunk 不发 `content` 事件**：避免前端收到 `{"content": ""}` 触发无意义 DOM 更新

**关键不变量**：
- 前端流式看到的 content 与最终 done 时的完整文本**必须一致**（除空白）
- `<think>` 块**不能**漏到 SSE 事件 payload 中
- `_strip_thinking` 是**幂等**的（多次调用结果相同），可在 text_chunk 阶段和 done 阶段都调用

---

## 7. 状态机

`SseProxyLayer` 内部状态（与 Dify 事件解耦）：

```
        ┌──────┐
        │ IDLE │
        └──┬───┘
   workflow_started
           │
           ▼
      ┌─────────┐
      │ STREAMING│ ◀──┐
      └────┬─────┘    │ workflow_finished? no
           │          │ 收到 text_chunk / node_finished (llm)
           │ 首个 text_chunk ───┐
           │                    │
           ▼                    ▼
      ┌──────────┐         ┌─────────┐
      │ FIRST_TOK│ ───────▶│ STREAMING│
      └─────┬────┘         └────┬────┘
            │                  │
            │ workflow_finished│
            ▼                  ▼
        ┌──────────┐
        │ FINISHED │   (正常出口)
        └──────────┘
            │ error / stream_broken / timeout
            ▼
        ┌──────────┐
        │ FAILED   │   (异常出口)
        └──────────┘
```

**FIRST_TOK 状态意义**：用于在收到首个 `text_chunk` 时同步发 `thinking_done`（关闭前端转圈）。

---

## 8. 协议一致性验收（M0.5 协议发现 + M1.5 v2 一致性）

> **重要**：v2 workflow（M1 产物）尚未生成前，无法"验收"它——这是 verification-before-deliverable 循环依赖。本节按里程碑分两阶段：
>
> - **M0.5 协议发现（Protocol Discovery）**：用**已部署的 v1 workflow** 跑 S1-S10，验证 Backend 端 `DifyClient` / `SseProxyLayer` 的协议假设。v1 多 LLM 节点会触发 §6.6 的"非 2007 节点 `text_chunk` 防御性丢弃"路径——M0.5 阶段必须覆盖。**M0.5 全部 ✅ 才能进 M1**。
> - **M1.5 v2 一致性**：M1 产出 v2 yml 并导入 Dify 平台后，把 S1-S10 **重跑**一遍，验证 v2 单 LLM 链路（`from_variable_selector` 永远 = `["2007", "text"]`、单次 LLM 调用 1 次、首字延迟 < 2s）。**M1.5 全部 ✅ 才能进 M2/M3 之后的集成**。
>
> 任一阶段不通过，对应里程碑不验收、不进入下游。

| # | 场景 | 操作 | 预期 Backend SSE 序列 | M0.5 (v1) | M1.5 (v2) |
|---|------|------|------------------|-----------|-----------|
| S1 | 纯文本问答 | POST `/chat/stream-v2` with `message="你好"`, no attachment | `sources` → N × `content` → `done{usage.total_tokens>0}` | ✅ | ✅ + 唯一来源节点 = 2007 |
| S2 | 文本+图片 | 加 1 个 image attachment | 同 S1，但 `done.attachments` 含 1 项 | ✅（v1 走 1007 视觉） | ✅（v2 走 2007 视觉） |
| S3 | 纯语音 | message="", 1 audio attachment | 同 S1，`input_text=""` 仍能产生 `content` 流 | ✅（Backend ASR 先转写） | ✅（同 v1） |
| S4 | Dify 401 | DIFY_API_KEY 错误 | `error{code=DIFY_AUTH}`，**Circuit Breaker 记录 1 次失败** | ✅ | ✅ |
| S5 | Dify 5xx | Dify 端 mock 503 | `error{code=DIFY_UPSTREAM}`，触发 Circuit OPEN 阈值 | ✅ | ✅ |
| S6 | Dify workflow failed | workflow 节点报配置错 | `error{code=DIFY_BAD_REQUEST}` | ✅ | ✅ |
| S7 | 长耗时首字 | Dify mock 20s 延迟 | `thinking{elapsed:3}` → 重复 → 首个 `content` → `thinking_done` | ✅（断言 **首字 ≥ 3s**，v1 aggregator 拖慢） | ✅（断言 **首字 < 2s**，v2 单链） |
| S8 | 客户端断连 | widget.abort() | Dify 连接关闭，Phase 3 仍执行，DB 中有完整记录 | ✅ | ✅ |
| S9 | 流中 Dify 断开 | 模拟 TCP RST | `error{code=DIFY_UPSTREAM}` | ✅ | ✅ |
| S10 | 100s 切断 | 强制 workflow 超时 | `done`（含截断内容），log warn | ✅ | ✅ |
| **S11** | **v2 单 LLM 链断言（v2-only）** | v2 触发任意 chat | Backend 收到的 `text_chunk` 全部 `from_variable_selector=["2007","text"]`，**非 2007 节点 0 个** | ⏸ 不适用 | ✅（v2 强约束） |
| **S12** | **§6.6 防御性丢弃（v1-only）** | v1 触发纯文本 | Backend 收到 1 个非 2007 节点的 `text_chunk`（来自 1013 文本链），`SseProxyLayer` 丢弃 | ✅（v1 才会触发；v2 不应出现） | ⏸ 不适用 |

**前端零修改验收**：
- 用 v1 widget 直接打 `/chat/stream-v2` 端点（修改 widget 的 fetch URL 一行）
- 6 类事件全部命中既有 `consumeStream` 分支
- 视觉与 v1 端点**无差异**（除 thinking 行为按 §6.2 启用时）

---

## 9. 协议字段对照速查

| Backend SSE event | Dify 源 | 关键字段 | 备注 |
|------------------|--------|---------|------|
| `sources` | （非 Dify，Phase 1 KB 检索产物） | `sources[]` | 不变 |
| `thinking` | （v2 端点内部计时器） | `elapsed` | 仅在 M5.2 启用 |
| `thinking_done` | 首个 `text_chunk` | `{}` | 不变 |
| `content` | `text_chunk.data.text` | `content` | 增量 |
| `done` | `workflow_finished` + Phase 3 持久化 | `message_id, session_id, usage, taken_over, attachments` | 见 §5 |
| `error` | `workflow_finished.status=failed` / 协议级错误 | `error, code` | 见 §3.3 / §6.8 |

---

## 10. 变更控制

| 版本 | 日期 | 作者 | 变更 |
|------|------|------|------|
| v1 | 2026-06-12 | Claude (M0) | 初版 |

后续变更（特别是新增 Dify 事件类型或调整 SseProxyLayer 行为）必须同步更新：
- `docs/api-contract-dify.md` §4.2 DifyStreamEvent 联合类型
- v2 方案相关章节
- 关联 M5 acceptance criteria
