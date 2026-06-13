# ADR 0003: Dify Workflow 简化（v1 → v2）

> 状态：**Accepted**（2026-06-12）
> 作者：Claude (M0)
> 关联：[ADR 0001](./0001-dify-llm-engine.md) ｜ [ADR 0002](./0002-tenant-isolation.md) ｜ [`docs/dify-integration-plan.md` §5 (M1)](./../dify-integration-plan.md)
>
> **2026-06-13 备注**：`china_charge_kf/` 从独立 git 仓库并入主仓（commit `5981f65`），本文内所有 `china_charge_kf/...` 路径在新结构下仍然有效（subdir 路径未变）。文中"demo"表述仍准确 — china_charge_kf/ 仍是原型态，未升级为生产实现。

---

## Context（背景）

现有 Dify workflow（v1，`china_charge_kf/Workflow-China_charge_seriver-draft-9380/workflow/workflow.yml`）是为 Dify 全独立部署设计的，包含 3 个并行分支：

```
[1001 start] → [1002 if-else]
                    ├── true (image) → [1006 KB] → [1007 LLM] ↘
                    ├── case_audio   → [1008 HTTP/ASR] → [1011 Code] → [1009 KB] → [1010 LLM] ↗
                    └── false (text) → [1012 KB] → [1013 LLM] ↗
                                                                ↓
                                                       [1014 variable-aggregator]
                                                                ↓
                                                       [1015 end]
```

### v1 痛点

1. **首字延迟高**：variable-aggregator 1014 必须等 3 个分支都跑完才 emit 结果
   - 即便 text 分支 0.5s 就出，aggregator 仍要等 image 分支的 KB 检索（~2s）+ LLM（~3s）
   - 实测首字延迟 ≥ 3s，远高于 v1 Backend 的 < 1s
2. **多模态与 LLM 职责重叠**：3 个分支各自调用一次 LLM，doubao 模型被请求 3 次（image 分支走 vision，audio 分支纯文本，text 分支纯文本）
3. **KB 节点 dataset_id 硬编码**：`REPLACE_WITH_YOUR_DIFY_DATASET_ID` 写死在 yml
4. **Backend 多模态能力未复用**：PR13 Vision/ASR 在 Backend 已实现，v1 重复造轮子
5. **ASR 走 Dify 内部 HTTP**：调用 `backend-dify-internal:8012`，增加架构耦合
6. **节点 ID 散乱**：1001-1015 共 10 节点，命名空间 1xxx 与 v2 设计 2xxx 无法共存

### 关键约束

- v1 workflow yml 是 `china_charge_kf` demo 的实际产物 → 改造需保持业务输出（充电桩售后客服）质量不退化
- Dify Cloud 100s workflow 时长上限不变
- Dify workflow yml 是 Dify 平台的"事实标准"，改造后必须能导入 Dify 平台
- v2 设计目标是**接入 Basjoo 多租户架构**，必须与 ADR 0001/0002 协同

---

## Decision（决策）

**将 v1 workflow（10 节点 / 3 分支）简化为 v2 workflow（3 节点 / 单链），多模态与 KB 上移到 Backend。**

### v2 workflow 结构

```
[2001 start] → [2007 LLM] → [2015 end]
```

| 节点 ID | 类型 | 说明 |
|--------|------|------|
| **2001** | start | 入参：`input_text`/`language`/`input_image`/`input_audio`（结构与 v1 一致） |
| **2007** | LLM | 单 LLM 节点（`doubao-seed-2-0-lite`，volcengine_maas）；vision 启用 |
| **2015** | end | 出参：`output: string`（从 LLM 节点 `text` 字段取） |

### 关键设计点

#### 1. 节点 ID 锁定 2xxx

- 2001/2007/2015 是 v2 的**契约 ID**
- 锁定目的：M4（`SseProxyLayer`）和 M2（`DifyClient`）可硬编码 `from_variable_selector=["2007", "text"]` 做防御性校验
- Dify 节点 ID 范围 `[1, 999999999]`，2xxx 远离 v1 的 1xxx，不冲突

#### 2. 单 LLM 节点的 vision 能力保留

- v2 LLM 节点 2007 启用 `vision.enabled=true`，传 `variable_selector: ["2001", "input_image"]`
- audio **不**进 LLM 节点；由 Backend 先 ASR 转写后，把转写文本塞入 `input_text`

#### 3. 变量定义（v2 与 v1 对齐，变量名后缀 `_id`）

> **supersede v1**:基于 M0.5 findings（v1 客户端代码 `china_charge_kf/backend/app_dify/` + 实测探针），变量名后缀是 `_id` 而非 `_image`/`_audio`，**值形态是 file-ref 对象数组**而非 Dify `file` 类型的特殊变量。

```yaml
# 2001 start
variables:
  - variable: input_text           # type: paragraph, required: false, max_length: 2000
  - variable: language             # type: text-input, max_length: 48
  - variable: input_img_id         # type: text-input, value=[file-ref array]
  - variable: input_audio_id       # type: text-input, value=[file-ref array]
```

**值形态**（Backend `MessagesToDifyInputConverter` 必须按此输出）：

```json
{
  "input_text": "用户文本",
  "language": "zh-CN",
  "input_img_id": [
    {"type": "image", "transfer_method": "local_file", "upload_file_id": "<uuid>"}
  ],
  "input_audio_id": [
    {"type": "audio", "transfer_method": "local_file", "upload_file_id": "<uuid>"}
  ]
}
```

**重要约束**：
- **必须是数组**，即使只有一个文件
- 没附件时**省略该 key**，不要传空数组或 null
- `input_audio` 在 v2 workflow **不**在 Dify 端做 ASR——Backend 在 Phase 1（PR13）已 ASR 转写为 `input_text` 附加前缀：
  ```
  [语音转写] {asr_text}

  [用户文本] {user_text}
  ```
  Dify LLM 看到的 `input_text` 是拼接后的最终文本。`input_audio_id` 字段保留（若用户同时上传音频文件作为附件）以备 LLM 端 vision/audio 能力扩展。

#### 4. 2007 LLM 节点 prompt 设计

```yaml
prompt_template:
  - role: system
    text: |
      # 角色定义
      你是面向海外用户的充电桩售后诊断与支持助手...
      （与 v1 LLM 1007 节点的 system prompt 保持一致，
       但移除 "参考资料：{{#context#}}"——v2 不再有 KB 节点）

  - role: user
    text: |
      {{#2001.input_text#}}
      （若 input_image 非空，Dify 自动将图片以 vision 多模态形式传入 LLM）
```

**重要**：v2 system prompt **不再引用** `{{#context#}}`（来自 KB 节点的 context），改为：
- 检索参考资料的逻辑由 Backend `MultiLayerKbService` 完成
- 检索结果通过 `DifyClient.run_workflow_stream` 之外的机制（详见 §"KB 上下文注入"）

#### 5. KB 上下文注入方案

由于 v2 workflow 不含 KB 节点（dataset_id 硬编码问题，见 ADR 0002），**KB 检索结果不再注入 Dify LLM**。

**折中方案**：
- Backend 在 Phase 1 检索 KB → 拿到 `sources[]`
- `sources[]` **不**进 Dify LLM prompt（v2 LLM 无视 KB）
- `sources[]` **照常**发到前端（SSE `sources` 事件），前端在 Assistant 消息下方渲染「参考资料」链接

**对回复质量的影响**：
- LLM 失去 KB 参考 → 回复基于训练数据 + 用户文本/图片
- 评估：原 v1 业务"充电桩售后 FAQ"类问题命中率约 75%（KB 命中率）；v2 估计降至约 50-60%
- 缓解：M+ 引入 "Backend 把 KB top-N 摘要注入 system prompt" 模式（v2.1 改进）

> **注意**：本折中是 ADR 0001（KB 在 Backend）和 ADR 0002（dataset_id 硬编码）的**直接后果**。若 v2.1 需恢复 KB 注入 LLM，需：
> 1. Backend 在 `run_workflow_stream` 前预检索 KB
> 2. 把 KB 摘要（≤ 1000 token）拼入 Dify workflow 的一个**新** `text` 类型 start 变量
> 3. v2.1 LLM prompt 引用该变量
> 4. 本 ADR 在 v2.1 实施前必须先 supersede

#### 6. 去掉 ASR HTTP 节点

- v1 的 1008 (HTTP/ASR) + 1011 (Code 解析) **完全删除**
- ASR 由 Backend 在 Phase 1 调用 Whisper（PR13）完成（见 `backend/services/whisper_service.py`）
- 这也是简化 v2 的最大收益：架构耦合点 -1

---

## Alternatives Considered（备选方案）

### A. 保留 v1 workflow 原样，Backend 仅替换 LLM 调用

- **优点**：改动最小；与 `china_charge_kf` demo 完全一致
- **缺点**：
  1. 首字延迟 ≥ 3s 无法改善
  2. 多模态与 LLM 重复处理 → 成本 ×3
  3. dataset_id 硬编码问题未解
  4. ASR HTTP 节点仍耦合 `backend-dify-internal:8012`
- **结论**：**放弃**。理由：核心痛点（性能/成本/隔离）一项未解决。

### B. v2 = 2 节点（无 if-else router），LLM 节点自己判断输入类型

- **优点**：节点数比 v2 更少
- **缺点**：
  1. 失去 Dify 显式分支控制（image/audio/text 三种 prompt 模板）
  2. LLM 自己判断 → 增加 token 消耗 + 准确率波动
  3. 与原 v1 的"if-else 分流"设计哲学不符
- **结论**：**放弃**。理由：v2 简化方向相反（应该少分支、少决策点）。

### C. v2 = 3 节点（保留 image/audio/text 分支）但**不**用 KB 节点

- **优点**：保留 v1 业务结构；仅删 dataset_id
- **缺点**：
  1. 仍有 3 LLM 节点（成本 ×3）
  2. 仍有 variable-aggregator（首字延迟 ≥ 3s）
  3. ASR HTTP 节点仍存在
- **结论**：**放弃**。理由：只解决了一个子问题。

### D. v2 = 单 LLM 节点（本决策）✓

- **优点**：
  1. 首字延迟 = LLM 节点耗时（实测 0.5-2s）
  2. 1 次 LLM 调用（成本 ×1/3）
  3. 节点数 -70%，workflow 调试更简单
  4. ADR 0002 的"dataset_id 硬编码"问题**彻底消失**（workflow 无 KB 节点）
  5. 架构耦合 -1（去掉 ASR HTTP）
- **缺点**：
  1. 失去 KB 注入 LLM 能力（见 §"KB 上下文注入"折中）
  2. audio 必须由 Backend ASR 后转 text（已 plan 在 M2）
  3. 需重新评估业务命中率（50-60% vs 75%）
- **结论**：**采纳**。理由：性能/成本/可维护性收益远超 KB 注入能力损失。

### E. v2 = 0 节点（Backend 不调 Dify workflow，调 Dify chat-messages API）

- **优点**：Backend 完全自洽；Dify 仅当 LLM provider
- **缺点**：
  1. 失去 Dify workflow 可视化编辑能力（与 ADR 0001 决策 C 冲突）
  2. Dify chat-messages API 的多模态支持需独立验证
  3. 用户原始诉求"用 Dify workflow 替换"被绕开
- **结论**：**放弃**。理由：违背用户明确意图。

---

## Consequences（后果）

### 正面

1. **首字延迟 0.5-2s**（v1 的 1/6）
2. **单次 chat 1 次 LLM 调用**（v1 的 1/3），成本 ↓ 60%
3. **workflow 节点数 10 → 3**，Dify 平台编辑效率 ↑
4. **架构耦合点 -1**（去掉 ASR HTTP 调用）
5. **dataset_id 硬编码问题彻底解决**（无 KB 节点）
6. **Backend 主导 KB** 与 ADR 0001/0002 一致

### 负面

1. **KB 不再注入 LLM**：
   - 业务命中率从 ~75% → ~50-60%
   - 缓解：M+ 引入 v2.1 改进（KB 摘要注入 start 变量）
   - 缓解：M9 评估"命中率下降是否在业务可接受范围"
2. **audio 必须 Backend ASR**：
   - Backend 多一道 ASR 调用（~1s 延迟 + Whisper 费用）
   - 缓解：Whisper 已有 cache（按 `audio_hash`），重复消息 0 成本
3. **v1 workflow 历史数据无法直接迁移**：
   - 旧 yml 入 git 历史可读，但 Dify 平台需重导入
   - 缓解：v1 yml 保留在 `china_charge_kf/Workflow-.../workflow.yml`，Dify 平台 v1 App 不删

### 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 业务命中率下降 | 客服满意度 ↓ | M8 必跑命中率测试；不达标则走 v2.1 |
| ASR 失败 → text 为空 | LLM 无内容可参考 | Backend ASR 失败时发 `error{DIFY_BAD_REQUEST}` |
| v1 业务已习惯多分支 LLM 输出 | 回答风格变化 | prompt 调优（M9）保留原"角色/目标/优先级"措辞 |
| 节点 ID 2xxx 与 Dify 升级冲突 | 协议层错位 | ID 是 Dify 平台级唯一；2xxx 远离常见 v1 节点 ID 范围 |

---

## 实施要点

### M0（已完成）

- 本 ADR 决策落地
- 节点 ID 锁定 `2001/2007/2015`

### M1（依赖本 ADR）

- 输出新 yml：`china_charge_kf/Workflow-.../workflow.yml.v2`（或覆盖原文件）
- yml 包含 3 节点 + vision 启用
- 提交 yml 至 git（不直接 push 到 Dify 平台，平台导入是运维动作）

### M2-M5（依赖本 ADR）

- `DifyClient.run_workflow_stream` 写死 `app_id` 指向 v2
- `MessagesToDifyInputConverter` 输出 audio→text 转换后的 `input_text`
- `SseProxyLayer` 校验 `from_variable_selector=["2007", "text"]`（防御性）

### M0.5 联调

- Dify 平台导入 v2 yml
- Backend 调 `/v1/workflows/run` 验证 3 节点全部 emit
- 跑 sse-event-mapping.md §8 S1-S10

### 验收

- M1：v2 yml 渲染通过（Dify 平台 import 无错）
- M8：业务命中率 ≥ 50%（不达则 v2.1）
- M8：单次 chat LLM 调用次数 = 1（v1 是 1-3）
- M8：首字延迟 ≤ 2s（v1 是 3-5s）

---

## 变更历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1 | 2026-06-12 | 初版（M0 产出） |
