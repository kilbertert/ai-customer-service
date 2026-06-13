# Dify API 集成契约

> 状态：v1（M0 产出）
> 关联：[`docs/dify-integration-plan.md` §6, §7](./dify-integration-plan.md) ｜ [`docs/sse-event-mapping.md`](./sse-event-mapping.md) ｜ [ADR 0001](./adr/0001-dify-llm-engine.md) ｜ [ADR 0002](./adr/0002-tenant-isolation.md) ｜ [ADR 0003](./adr/0003-workflow-simplification.md)
> 适用范围：M2 起的所有 Dify 集成代码

---

## 0. 目的与读者

本文档给出 **Dify 作为 LLM 引擎** 时，Backend 对 Dify Workflow API 与 Backend 对外公共 API 的**接口契约**。它是 M2（`DifyClient` 服务层）的实现依据，也是 M5（`/chat/stream-v2`）端点设计的前置约束。

读者：
- M2-M9 的实现工程师：按本文实现 `DifyClient`、`LLMProvider` 适配器、协议代理
- 前端 / Widget 工程师：可参考 §3 确认 `/chat/stream-v2` 端点的输入形态
- 测试工程师：§6 给出的合同测试用例即为测试矩阵

---

## 1. 术语对齐

| 术语 | 本文定义 | 与其他文档的关系 |
|------|---------|----------------|
| **Dify App** | 一个 Dify 工作流应用，类型 = `workflow`（非 `chatbot`/`agent`），对应一个 `app_id` | 一个 Dify App 对应一份 workflow.yml |
| **Dify Workspace** | Dify 多租户容器；本文方案下**全平台共用 1 个** | 见 ADR 0002 |
| **Dify workflow inputs** | Start 节点声明的入参（`input_text`/`language`/`input_image`/`input_audio`） | v2 workflow 保留这 4 个变量名 |
| **Dify workflow outputs** | End 节点声明的出参（v2 仅 `output: string`） | 经 End 节点返回，由代理层解析 |
| **Backend `DifyClient`** | `backend/services/dify_client.py` 中的 Python 客户端 | 唯一与 Dify HTTP 通信的入口 |
| **`/chat/stream-v2`** | M5 新建端点，老 `/chat/stream` 保留 | 仅在 sticky rollout 命中 `v2` 时由 Backend 路由至此 |
| **`MessagesToDifyInputConverter`** | `ChatRequest` → Dify workflow `inputs` 的纯函数 | M2 内部组件 |

---

## 2. Dify Workflow API 契约（Backend → Dify）

### 2.1 文件上传（multipart/form-data）

**端点**：`POST {DIFY_API_BASE}/v1/files/upload`

**请求**：
```http
POST /v1/files/upload HTTP/1.1
Host: api.dify.example.com
Authorization: Bearer {DIFY_API_KEY}
Content-Type: multipart/form-data; boundary=...

--boundary
Content-Disposition: form-data; name="file"; filename="photo.jpg"
Content-Type: image/jpeg

<binary>
--boundary
Content-Disposition: form-data; name="user"

wsid_agt_a1b2c3d4e5f6
--boundary--
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `file` | ✅ | 二进制文件（image/* 或 audio/*，受 `ALLOWED_*_MIME` 约束） |
| `user` | ✅ | Backend 注入的 `tenant_id:agent_id` 组合（Dify 用作审计标识） |

**响应 200**：
```json
{
  "id": "72fa9618-8f89-4f37-b1f4-0b3e3b5e7a51",
  "name": "photo.jpg",
  "size": 184320,
  "extension": "jpg",
  "mime_type": "image/jpeg",
  "created_by": "wsid_agt_a1b2c3d4e5f6",
  "created_at": 1717000000
}
```

**错误码**：

| HTTP | 含义 | Backend 行为 |
|------|------|------------|
| 400 | 格式 / mime 非法 | 转 `DifyClientError(code="UPLOAD_BAD_REQUEST")` |
| 413 | 文件超限 | 转 `DifyClientError(code="UPLOAD_TOO_LARGE")` |
| 415 | 不支持的 mime | 同 400 |
| 500/502/503/504 | Dify 上游 | 触发重试（最多 2 次，指数退避 1s/2s）后转 `DifyClientError(code="UPLOAD_UPSTREAM")` |
| 401/403 | 鉴权 | 转 `DifyClientError(code="AUTH")` —— **不重试**，触发 Circuit Breaker |

**Backend 内部类型**（`backend/services/dify_client.py`）：
```python
@dataclass(frozen=True)
class DifyUploadedFile:
    file_id: str            # 透传到 workflow inputs
    name: str
    mime_type: str
    size: int
```

### 2.2 阻塞运行（blocking mode）

**端点**：`POST {DIFY_API_BASE}/v1/workflows/run`

**用途**：M0.5 联调用例 / 灰度回退 / 健康检查。生产 `/chat/stream-v2` **不**使用本端点。

**请求体**：
```json
{
  "inputs": {
    "input_text": "充电桩无法启动怎么办？",
    "language": "zh-CN",
    "input_image": {
      "type": "image",
      "transfer_method": "local_file",
      "upload_file_id": "72fa9618-8f89-4f37-b1f4-0b3e3b5e7a51"
    },
    "input_audio": {
      "type": "audio",
      "transfer_method": "local_file",
      "upload_file_id": null
    }
  },
  "response_mode": "blocking",
  "user": "wsid_agt_a1b2c3d4e5f6"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `inputs.input_text` | ✅ | 用户文本（空字符串亦允许，纯语音场景） |
| `inputs.language` | ✅ | BCP-47 标签；v2 workflow 透传至 LLM prompt |
| `inputs.input_image` | 条件 | 仅在用户附带图片时存在；对象含 `upload_file_id`（来自 §2.1） |
| `inputs.input_audio` | 条件 | 仅在用户附带语音时存在 |
| `response_mode` | ✅ | 仅 `blocking` |
| `user` | ✅ | Dify 审计标识 |

**响应 200**（Dify `workflow_finished` payload 的最终聚合结果）：
```json
{
  "workflow_run_id": "xxx",
  "task_id": "yyy",
  "data": {
    "id": "yyy",
    "workflow_id": "app-uuid",
    "status": "succeeded",
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

**Backend 内部类型**：
```python
@dataclass(frozen=True)
class DifyBlockingResult:
    workflow_run_id: str
    status: Literal["succeeded", "failed", "stopped"]
    output_text: str          # data.outputs["output"]
    elapsed_ms: int
    total_tokens: int | None
    error: str | None
```

**超时与重试**：
- 超时：`llm_test_timeout_seconds = 10` 用于探活，**真实调用 60s 上限**（Dify Cloud 业务默认 100s，60s 给前端 + 网络 40s 余量）
- 重试：仅在 `5xx` / `429` / `TimeoutError` 时重试，最多 2 次，指数退避

### 2.3 流式运行（streaming mode）— **生产路径**

**端点**：`POST {DIFY_API_BASE}/v1/workflows/run`（同 URL，靠 `response_mode` 切换）

**请求体**：
```json
{
  "inputs": { /* 同 §2.2 */ },
  "response_mode": "streaming",
  "user": "wsid_agt_a1b2c3d4e5f6"
}
```

**响应**：`Content-Type: text/event-stream`，事件序列详见 `docs/sse-event-mapping.md`。

**关键约束**：
- Dify Cloud 单次 workflow 总时长 **≤ 100s**；超过会切断
- 单个 LLM 节点 `max_tokens` v2 workflow 锁定 `4096`（与原 yml 对齐）
- 若 v2 workflow 包含多个 LLM 节点（**不推荐**），必须确认 v2 是否仍走 `stream` —— 当前 v2 锁定为单 LLM 节点，不存在该歧义

### 2.4 请求级 Header（Backend 注入）

| Header | 取值 | 用途 |
|--------|------|------|
| `Authorization` | `Bearer {DIFY_API_KEY}` | Dify API 鉴权；key 通过 Fernet 解密（见 `ENCRYPTION_KEY`） |
| `X-Dify-Tenant` | `wsid_{wsid}` | 平台审计透传（**Dify 自身不读**，仅用于内部 trace） |
| `X-Request-Id` | UUID4 | 关联 Backend 日志与 Dify 调用链 |
| `Content-Type` | `application/json` 或 `multipart/form-data` | 协议区分 |

---

## 3. Backend 对外公共 API 契约

> 老 `/api/v1/chat/stream` **不动**。`/api/v1/chat/stream-v2` 是 M5 新建端点。

### 3.1 `POST /api/v1/chat/stream-v2`

**请求**（Content-Type: `application/json`）：
```json
{
  "agent_id": "agt_a1b2c3d4e5f6",
  "message": "充电桩无法启动怎么办？",
  "locale": "zh-CN",
  "widget_locale": "zh-CN",
  "session_id": "sess_xxx_yyy",
  "visitor_id": "visitor_xxx",
  "timezone": "Asia/Shanghai",
  "attachment_ids": ["att_abcd1234abcd"]
}
```

字段语义与 `ChatRequest` 一致（见 `backend/api/v1/endpoints.py` 已存在定义）；v2 端点**不**新增字段。`attachment_ids` 中的 `att_xxx` 已通过 `/api/v1/chat/attachments` 上传，Backend 在 Phase 1 解析为 Dify 文件引用。

**响应**：`text/event-stream`，事件顺序与 v1 兼容：

```
event: sources
data: {"sources":[{"type":"url","title":"...","url":"...","snippet":"..."}]}

event: content
data: {"content":"请先"}

event: content
data: {"content":"检查供电"}

event: done
data: {"message_id":1234,"session_id":"sess_xxx_yyy","usage":{"prompt_tokens":120,"completion_tokens":56,"total_tokens":176},"taken_over":false,"attachments":[...]}
```

事件完整定义见 `docs/sse-event-mapping.md`。错误形态见 §3.3。

**Header 透传**（由 `apply_cors_headers` 注入）：
- `Cache-Control: no-cache`
- `Connection: keep-alive`
- `X-Accel-Buffering: no`（关键：禁用 nginx 缓冲以保真 SSE）
- `Content-Type: text/event-stream`

### 3.2 路由分发（sticky rollout）

请求处理入口 `chat_stream_v2_router`（M5 新建）：

```python
def should_route_to_v2(agent_id: str, session_id: str) -> bool:
    """Sticky rollout: 同 session 永远走同一实现，直到切换 rollout 比例。"""
    rollout_pct = get_rollout_percentage(agent_id)  # 0-100, 来自 settings.dify_rollout_pct
    if rollout_pct <= 0:
        return False
    if rollout_pct >= 100:
        return True
    h = int(md5(f"{agent_id}:{session_id}".encode()).hexdigest(), 16) % 100
    return h < rollout_pct
```

`/chat/stream`（老）与 `/chat/stream-v2`（新）共用 Phase 1（`prepare_chat_request`），仅在 Phase 2 选择 LLM provider 时分支。

### 3.3 错误码（v2 端点专用）

| 错误码 | 触发条件 | SSE `event: error` payload | 客户端行为 |
|--------|---------|---------------------------|----------|
| `DIFY_UPSTREAM` | Dify 5xx/网络错误且 Circuit 已开 | `{"error":"AI 服务暂时不可用", "code":"DIFY_UPSTREAM"}` | 显示降级提示，可点重试 |
| `DIFY_TIMEOUT` | Dify 100s 内未完成 | 同上 `code` 改为 `DIFY_TIMEOUT` | 同上 |
| `DIFY_BAD_REQUEST` | Dify 400（workflow inputs 不合法） | `{"error":"请求格式错误", "code":"DIFY_BAD_REQUEST"}` | 不可重试，记录后端日志 |
| `DIFY_AUTH` | Dify 401/403（key 失效） | `{"error":"AI 服务鉴权失败", "code":"DIFY_AUTH"}` | 触发告警，自动全量回滚到 v1 |
| `QUOTA_EXCEEDED` | 租户配额超限 | `{"error":"今日对话次数已用完", "code":"QUOTA_EXCEEDED"}` | 显示配额提示 |
| `PERSISTENCE_ERROR` | DB 写入失败但内容已输出 | `{"error":"回复已发送但保存失败", "code":"PERSISTENCE_ERROR"}` | UI 已展示，不重试 |

所有错误码在 v1 已存在定义（`get_stream_error_code`），v2 **不**新增 `StreamErrorPayload` 字段。

### 3.4 附件上传（`POST /api/v1/chat/attachments`）

**保持现状**。v2 workflow 通过 Dify `inputs.input_image`/`input_audio` 引用：
- Backend 在 Phase 1 把 `attachment_id` 解析为 `MessageAttachment` 行
- 读取本地 `media_storage_dir/{att.id}` 文件 → `DifyClient.upload_file()` → 拿到 `upload_file_id`
- 把 `upload_file_id` 注入到 `MessagesToDifyInputConverter` 输出的 `inputs` 字典
- v1 的 `att_xxx` ID 在 v2 中**仅作 Backend 内部标识**，Dify 端用的是 Dify 的 `file_id`

> **断点恢复考虑**：M5 实现 `DifyClient.upload_file()` 时必须支持 idempotency —— 同 `attachment_id` 第二次调用复用首次的 `upload_file_id`（缓存 5 分钟），避免每次请求都重传。

---

## 4. Backend 内部契约（Python）

### 4.1 `DifyClient` 抽象接口

```python
# backend/services/dify_client.py

class DifyClient(Protocol):
    """Dify HTTP 客户端抽象。M2 实现为 DifyHttpClient；M3 测试可注入 FakeDifyClient。"""

    async def upload_file(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        tenant_id: str,
        agent_id: str,
    ) -> DifyUploadedFile: ...

    async def run_workflow_blocking(
        self,
        *,
        app_id: str,
        inputs: dict[str, Any],
        tenant_id: str,
        agent_id: str,
        timeout_s: float = 60.0,
    ) -> DifyBlockingResult: ...

    def run_workflow_stream(
        self,
        *,
        app_id: str,
        inputs: dict[str, Any],
        tenant_id: str,
        agent_id: str,
    ) -> AsyncIterator[DifyStreamEvent]:
        """产生 DifyStreamEvent 流，由 ProtocolAdapter 转换为 Backend SSE。"""
        ...

    async def health_check(self) -> bool: ...
```

### 4.2 `DifyStreamEvent` 联合类型

> **输入契约（M2 v2 yml 锁定，PR10）**：v2 workflow yml（`china_charge_kf/Workflow-China_charge_seriver-draft-9380/workflow/workflow_v2.yml`）声明如下：
>
> | 变量 | yml type | Dify Studio 显示 | 值类型（Backend 必须传） |
> |------|---------|----------------|-----------------------|
> | `input_text` | `text-input` | Text | `string` |
> | `language` | `text-input` | Text | `string` |
> | `input_img_id` | `file-list` | Array[File] | **file-ref array**（非单 object） |
> | `input_audio_id` | `file-list` | Array[File] | **file-ref array**（非单 object） |
>
> **值形态约束**（M1.5 v5 S2 实测，Dify 平台层严格校验）：
>
> ```json
> // ✅ 正确（array 形态）
> "input_img_id": [
>   {"type": "image", "transfer_method": "local_file", "upload_file_id": "<uuid>"}
> ]
> // ❌ 错误（单 object，400 "must be a file"）
> // "input_img_id": {"type": "image", ...}
> // ❌ 错误（string，400 "must be a string"）
> // "input_img_id": "<uuid>"
> ```
>
> **Backend 序列化约定（spec §6 约束）**：
> - 实现位置：`china_charge_kf/backend/app_dify/dify_client.py:file_ref()`
> - 调用位置：`china_charge_kf/backend/app_dify/main.py:chat()` 第 134/136 行
> - 输出形态：**始终 array**（即使只有一个文件：`inputs[input_img_id] = [client.file_ref(file_id, "image")]`）
> - **禁止**改 Backend 现有序列化代码（PR10 锁定）
>
> **变更历史**：
> - v1 yml：`type: file`（单值，v1 平台宽松接受 array 是向后兼容，**不**依赖）
> - v2 yml v3 (Fix C)：`type: file` + Backend 改 object（已废）
> - **v2 yml v5（最终态）**：`type: file-list` + Backend 维持 array（M1.5 §1.2）
>
> 完整 yml 字段定义见 `china_charge_kf/Workflow-.../workflow_v2.yml` 的 `user_input_form` 节点。

```python
DifyStreamEvent = Union[
    WorkflowStartedEvent,   # event=workflow_started
    NodeStartedEvent,       # event=node_started
    TextChunkEvent,         # event=text_chunk
    NodeFinishedEvent,      # event=node_finished
    WorkflowFinishedEvent,  # event=workflow_finished
    TtsMessageEvent,        # event=tts_message  -- v2 不使用 TTS
    PingEvent,              # event=ping
    HumanInputRequired,     # event=human_input_required -- v2 不使用
]
```

完整字段定义见 `docs/sse-event-mapping.md` §2。

#### 4.2.1 `DifyClient.run_workflow` 输出判定规则（基于 M0.5 实测 D5/D6/V10b）

> **supersede v1 §2.2 响应 200 处理路径**：`data.status` ≠ 输出可用性判定标准。

```python
def extract_output_text(data: dict, output_key: str = "output") -> str | None:
    """从 workflow_finished.data 中提取 LLM 文本。

    判定规则（按优先级）：
    1. data.outputs[output_key] 非空 → 返回（主路径）
    2. data.outputs[output_key] 为空但 outputs 字典其他键命中
       (deep search 顺序: output > answer > result > text > message > content)
       → 返回首个非空字符串
    3. 都为空 / None → 返回 None
       调用方应发 SSE error{code="DIFY_BAD_OUTPUT"}

    ⚠️ 不依赖 data.status:
    - data.status="succeeded" 不保证 outputs 非空
      (实测 V10b: fake file_id 触发 v1 if-else 走 text 分支,workflow 整体 succeeded)
    - data.status="failed" 不一定 outputs 为空(部分节点 error 但其他节点 outputs 完整)

    实测来源: M0.5 findings V10b
    """
    outputs = (data or {}).get("outputs") or {}
    primary = outputs.get(output_key)
    if isinstance(primary, str) and primary.strip():
        return _strip_thinking(primary)
    for k in ("output", "answer", "result", "text", "message", "content"):
        v = outputs.get(k)
        if isinstance(v, str) and v.strip():
            return _strip_thinking(v)
    return None
```

**新增错误码**(给 sse-mapping §3.3 / api-contract §3.3 共享):

| code | 触发条件 | SSE payload |
|------|---------|-----------|
| `DIFY_BAD_OUTPUT` | `data.status=succeeded` 但 `outputs[output_key]` 为空且无 fallback 命中 | `{"error":"AI 回复内容为空", "code":"DIFY_BAD_OUTPUT"}` |

**单元测试用例**（M2 必覆盖，pytest `tests/test_dify_client.py::test_extract_output_text`）：

| # | 输入 `data` 形态 | `output_key` | 期望返回 | 覆盖场景来源 |
|---|----------------|-------------|---------|------------|
| U1 | `{"status":"succeeded","outputs":{"output":"请先检查供电..."}}` | `"output"` | `"请先检查供电..."` | 正常路径（M1.5 S1） |
| U2 | `{"status":"succeeded","outputs":{}}` | `"output"` | `None` | outputs 字典存在但所有 key 缺失 → 触发 `DIFY_BAD_OUTPUT` |
| U3 | `{"status":"succeeded","outputs":{"text":"fallback answer..."}}` | `"output"` | `"fallback answer..."` | outputs 键非 output → fallback 搜索命中（M0.5 V10b） |
| U4 | `{"status":"succeeded","outputs":{"output":"<think>CoT</think>您好"}}` | `"output"` | `"您好"` | thinking 块剥离（§6.10） |
| U5 | `{"status":"failed","error":"PluginInvokeError: ArkBadRequestError: image too small","outputs":{}}` | `"output"` | `"PluginInvokeError: ArkBadRequestError: image too small"` | **v2 S6b 新增**：status=failed 时从 `data.error` 提取（**不**返回 None） |
| U6 | `{"status":"failed","error":"req_id: xxx PluginInvokeError: ...","outputs":{"output":"partial answer"}}` | `"output"` | `"partial answer"`（忽略 error，outputs 优先） | status=failed 但 outputs 非空 → outputs 优先（M0.5 D6） |
| U7 | `{"status":"stopped","outputs":null}` | `"output"` | `None` | outputs=None 时退化（避免 AttributeError） |
| U8 | `{"status":"succeeded","outputs":{"output":""}}` | `"output"` | `None` | outputs[output_key] 是空字符串（**不**返回空串） |
| U9 | `{"status":"succeeded","outputs":{"output":"   "}}` | `"output"` | `None` | outputs[output_key] 仅空白字符（**不**返回空白） |
| U10 | `{}` | `"output"` | `None` | 完全空 data（防御性，不抛异常） |

**关键不变量**（测试断言）：
- U5/U6：status=failed 时**不**返回 None；若 `outputs[output_key]` 有值则优先 outputs（U6），否则返回 `data.error`（U5）
- U4：`_strip_thinking` 必须在所有返回路径上调用（幂等）
- U8/U9：空字符串/纯空白**视为无输出**，返回 None（让上层抛 `DIFY_BAD_OUTPUT`，不静默吞掉）
- U2/U7/U10：缺失字段、null 字段、空 data 都**不抛异常**，仅返回 None

### 4.3 `MessagesToDifyInputConverter`

```python
# backend/services/dify_input_converter.py

@dataclass(frozen=True)
class ConvertedDifyInputs:
    inputs: dict[str, Any]
    """可直接 POST 到 Dify /v1/workflows/run 的 inputs 字典。"""
    file_ids_resolved: list[str]
    """本次调用通过 DifyClient.upload_file() 实际产生的 file_id（用于日志/账单）。"""

def convert_chat_to_dify_inputs(
    *,
    message: str,
    locale: str,
    attachments: list[ResolvedAttachment],
    uploaded_files: dict[str, DifyUploadedFile],  # att_id -> uploaded
) -> ConvertedDifyInputs:
    """将 ChatRequest + 已上传文件转换为 Dify workflow inputs。

    转换规则：
    - input_text = message（已 trim，长度 ≤ 2000 字符）
    - language = locale（BCP-47 标签）
    - input_image = {type, transfer_method, upload_file_id} 仅在用户附带图片时
    - input_audio = {type, transfer_method, upload_file_id} 仅在用户附带语音时
    """
```

`ResolvedAttachment` 来自 `MessageAttachment` 模型的 DB 行（`mime_type`/`filename`/`storage_path` 等字段）；`uploaded_files` 由 `DifyClient.upload_file()` 提前填充并缓存。

### 4.4 `CircuitBreaker` 行为契约

> 防止 Dify 全平台不可用时把 v2 流量打挂。

| 状态 | 进入条件 | 通过条件 | 失败条件 | 行为 |
|------|---------|---------|---------|------|
| **CLOSED** | 初始 | 连续 10 次成功 | 5xx/超时 ≥ 5 次（滑动窗口 60s） | 正常调用 Dify |
| **OPEN** | 失败阈值 | 静默 30s | — | 直接返回 `DIFY_UPSTREAM`，**不再调用 Dify** |
| **HALF_OPEN** | 30s 静默后 | 探测 1 次成功 | 探测失败 | 放 1 个请求试 Dify；成功 → CLOSED，失败 → OPEN |

**Backend 集成点**：
- `DifyClient` 构造时注入 `CircuitBreaker` 单例（按 `app_id` 维度）
- `chat_stream_v2` 在 Phase 2 调用前 `await breaker.allow()`；不通过则降级到 v1
- 状态变更触发 `logger.warning` + Prometheus counter `dify_circuit_state{state}`

---

## 5. 配置项（M0 写入 config.py 的扩展点）

```python
# backend/config.py 追加（M2 实现时落地）

# Dify LLM 引擎
dify_api_base: str = ""                          # 例: https://api.dify.ai/v1
dify_api_key_encrypted: str = ""                 # Fernet 加密存储
dify_app_id: str = ""                            # v2 workflow 的 app_id
dify_workspace_id: str = ""                      # 平台统一 workspace（ADR 0002）
dify_streaming_timeout_s: float = 90.0           # workflow 流式调用上限
dify_blocking_timeout_s: float = 60.0            # 探活 / 灰度回退
dify_rollout_pct: int = 0                        # sticky rollout 比例 0-100

# Circuit Breaker
dify_cb_failure_threshold: int = 5               # 触发 OPEN 的失败数
dify_cb_window_s: int = 60                       # 滑动窗口
dify_cb_open_duration_s: int = 30                # OPEN 静默时长
dify_cb_half_open_probe_count: int = 1           # HALF_OPEN 探测数
```

**取值校验**（`model_post_init`）：
- `dify_rollout_pct` ∈ `[0, 100]`，否则拒绝启动
- `dify_api_base` 非空时 `dify_app_id` 必须非空
- `ENCRYPTION_KEY` 必须存在才能解密 `dify_api_key_encrypted`

---

## 6. 合同测试矩阵（M2 必须覆盖）

> 测试位于 `backend/tests/contract/test_dify_client_contract.py`

| # | 场景 | 输入 | 期望 |
|---|------|------|------|
| C1 | 上传合法 image | 1KB JPEG | 返回 `DifyUploadedFile{mime_type="image/jpeg", file_id=...}` |
| C2 | 上传超大 image | 6MB JPEG | 抛 `DifyClientError(code="UPLOAD_TOO_LARGE")` |
| C3 | 上传非法 mime | text/plain | 抛 `DifyClientError(code="UPLOAD_BAD_REQUEST")` |
| C4 | 上传时 Dify 401 | 模拟 401 | 抛 `DifyClientError(code="AUTH")`，**不重试** |
| C5 | 上传时 Dify 5xx | 模拟 503 | 重试 2 次后抛 `DifyClientError(code="UPLOAD_UPSTREAM")` |
| C6 | blocking 成功 | 简单 text inputs | 返回 `DifyBlockingResult{status="succeeded", output_text=...}` |
| C7 | blocking 超时 | 模拟 65s 阻塞 | 抛 `DifyClientError(code="TIMEOUT")` |
| C8 | streaming 完整链路 | text inputs | 产生 `workflow_started`→`text_chunk*N`→`workflow_finished` 序列 |
| C9 | streaming 中途断开 | 模拟半路断流 | 抛 `DifyClientError(code="STREAM_BROKEN")` |
| C10 | Converter 无附件 | 仅 message | inputs 只有 `input_text` + `language` |
| C11 | Converter 1 张图片 | 1 attachment | inputs 含 `input_image.upload_file_id` |
| C12 | Converter 1 段语音 | 1 audio attachment | inputs 含 `input_audio.upload_file_id` |
| C13 | Converter 混合 | text + image + audio | 三个 attachment 字段全填 |
| C14 | Converter 空 message + 仅语音 | message="", 1 audio | input_text=""，audio 字段填 |
| C15 | Circuit Breaker CLOSED→OPEN | 连续 5 次失败 | 第 6 次直接 `DIFY_UPSTREAM` 不调用 Dify |
| C16 | Circuit Breaker HALF_OPEN 恢复 | OPEN 后 30s 静默 | 放 1 个请求，成功后回 CLOSED |
| C17 | Sticky rollout 同 session | `agent_id=X, session_id=Y` 连续调用 | 100% 同路由到 v1 或 v2 |
| C18 | 健康检查 | 调用 `health_check()` | 返回 True/False，5s 内必须返回 |

---

## 7. 变更控制

| 版本 | 日期 | 作者 | 变更 |
|------|------|------|------|
| v1 | 2026-06-12 | Claude (M0) | 初版 |

后续变更必须同步更新：
- `docs/dify-integration-plan.md` 的相关 §6/§7
- 关联 ADR
- 对应 M2-M5 任务的 acceptance criteria
