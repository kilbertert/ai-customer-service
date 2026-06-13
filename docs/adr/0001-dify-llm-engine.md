# ADR 0001: Dify 作为 LLM 引擎

> 状态：**Accepted**（2026-06-12）
> 作者：Claude (M0)
> 关联：[`docs/dify-integration-plan.md` §1.2 (决策日志)](./../dify-integration-plan.md) ｜ [ADR 0002](./0002-tenant-isolation.md) ｜ [ADR 0003](./0003-workflow-simplification.md)

---

## Context（背景）

Basjoo AI 客服后端当前采用「自研 LLM 抽象层 + 多种 provider 适配（OpenAI/DeepSeek/Google）」模式，聊天响应生成完全在 Backend 内部完成。`china_charge_kf/` 子目录（前身为独立 git 仓库，2026-06-13 commit `5981f65` 合并入主仓）提供了基于 Dify Workflow 的替代实现，目前是单点 demo，与 Basjoo 多租户/多模态/SSE 流式/KB 检索等要求不兼容。

我们需要在「保留 Backend 全部已有能力（KB/多模态/SSE/限流/会话管理）」的前提下，用 Dify 替换**LLM 响应生成**这一环节。

### 关键约束

| # | 约束 | 详细 |
|---|------|------|
| C1 | KB 检索已自研（Qdrant + 多种 embedding provider） | 见 `backend/services/kb_retrieval_service.py` |
| C2 | PR13 多模态已支持（Vision + ASR） | 见 `backend/services/llm_service.py` 中的 `multimodal_fold_*` |
| C3 | SSE 流式协议已被前端/Widget 深度集成 | 见 `widget/src/BasjooWidget.tsx` 的 `consumeStream` |
| C4 | 现有 Dify workflow 包含 3 分支（image/audio/text） | 见 `china_charge_kf/Workflow-.../workflow.yml` |
| C5 | Dify 知识库 dataset_id 在 workflow 中硬编码 | 无法 per-tenant 切换 |
| C6 | 平台多租户（B 端 / C 端）需要 KB 隔离 | 详见 ADR 0002 |

---

## Decision（决策）

**采用 Dify 作为 LLM 引擎，KB 检索与多模态预处理保留在 Backend。**

具体方案：

1. **Backend 负责**：会话管理、租户隔离、KB 检索（Qdrant 多 collection）、多模态预处理（图片 captioning / 语音转写）、限流、配额、SSE 协议到前端的转换、错误降级。
2. **Dify 负责**：仅 LLM 响应生成（v2 workflow 简化为单 LLM 节点，详见 ADR 0003）。
3. **协作方式**：Backend 把 `ChatRequest` 通过 `MessagesToDifyInputConverter` 转换为 Dify workflow `inputs`；Dify 输出的 SSE 流经 `SseProxyLayer`（M4）转换为现有 `/chat/stream` 协议，前端**零修改**。
4. **部署形态**：Dify 全平台共用 1 个 Workspace + 1 个 v2 workflow App（详见 ADR 0002）。

---

## Alternatives Considered（备选方案）

### A. 完全替换（Backend 仅做代理，所有逻辑放 Dify）

- **优点**：Backend 代码大幅简化；Dify 可视化编辑流程便于业务方调优
- **缺点**：
  1. Dify dataset 硬编码 → 无法 per-tenant 切 KB
  2. 多模态分散到 3 个分支 → SSE 流式事件顺序依赖 variable-aggregator，**首字延迟 = 整 workflow 时长**（实测 ≥ 3s）
  3. Backend 失去 SSE 端到端控制（限流/降级/审计都得走 Dify）
  4. 现有 PR13 多模态管线无法复用
- **结论**：**放弃**。理由：性能与租户隔离两个硬性需求无法满足。

### B. 完全保留 Backend 自研，引入 Dify 仅作为 prompt 调试工具

- **优点**：风险最低；不动核心 chat 链路
- **缺点**：
  1. 浪费 `china_charge_kf` 已有的 workflow 沉淀（视觉化调试优势）
  2. 业务方期望"低代码调 prompt"的诉求落空
  3. 后期业务扩展（如加 TTS/多轮状态机）仍需自研
- **结论**：**放弃**。理由：与用户立项意图不符，未充分利用 Dify 价值。

### C. **混合（Backend + Dify，本决策）** ✓

- **优点**：
  1. Backend 守住关键边界（KB/多模态/租户/SSE/限流）
  2. Dify 接管 LLM prompt 工程（业务方可低代码调）
  3. SSE 协议严格兼容 → 渐进式灰度 → 风险可控
  4. 故障隔离（v1 路径保留 + Circuit Breaker）
- **缺点**：
  1. 需维护两套 `workflow` × `Backend` 逻辑（通过 v2 workflow 单 LLM 节点简化）
  2. 多模态需 Backend 先做 caption/ASR 一次，Dify 再做一次（成本 ↑ 但可控）
  3. 引入 Dify 外部依赖（运维/Dify Cloud 限流）
- **结论**：**采纳**。理由：在满足所有硬约束前提下，最大化 Dify 价值。

### D. 引入 LiteLLM / LangChain 统一 LLM 层（不引入 Dify）

- **优点**：纯 Backend 内聚；Dify 运维负担为零
- **缺点**：
  1. 与用户"用 Dify 替代"的明确诉求冲突
  2. prompt 调试可视化能力 < Dify
  3. 工作流编排能力 < Dify（多分支/工具调用等需要手写）
- **结论**：**用户已明确拒绝**。背景：用户原始诉求就是用 Dify 替换。

---

## Consequences（后果）

### 正面

1. **可视化 prompt 工程**：业务方/客服产品经理可在 Dify UI 直接调整 LLM prompt，无需 Backend 改代码
2. **流程可视化**：v2 workflow（单 LLM 节点）虽简单，但留有扩展空间（M+ 可加 RAG 节点/工具调用节点/分支）
3. **可灰度回滚**：保留 v1 端点 + sticky rollout，回滚成本 < 5 分钟
4. **故障隔离**：Dify 全平台不可用时，10s 内 Circuit OPEN，全部 v2 流量降级 v1

### 负面

1. **额外 HTTP 调用**：每次 chat 1 次 Dify workflow 调用（30-100ms 网络开销）；通过流式首字掩盖
2. **外部依赖**：
   - Dify Cloud API SLA < 99.9%（自托管可控但增加运维）
   - Dify 100s 单次 workflow 时长上限 → 大 prompt/大上下文场景受限
3. **观测面增加**：
   - Dify 工作流耗时/费用/LLM token 消耗需在 Dify 平台 + Backend 双向观测
   - M9 需要新建 `DifyWorkflowMetrics` 采集器
4. **Dify 升级风险**：Dify v1 → v2 重大变更时（如 `text_chunk` 字段调整），`SseProxyLayer` 需同步更新
5. **开发模式复杂度**：本地 dev 需启动 Dify（或用 Dify 公共测试工作流）；M2 需提供 mock Dify 服务

### 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| Dify Cloud 限流/不可用 | v2 全量 502 | Circuit Breaker + 自动降级 v1 |
| Dify workflow 误改 | 全平台回复异常 | workflow yml 进 git；Dify Web UI 改完必须同步 yml |
| Dify 升级破坏协议 | 流式失效 | §8 协议一致性验收 + 每次升级跑 M0.5 S1-S10 |
| 多模态被 Dify 重复处理 | 成本翻倍 | Backend 在 Phase 1 已 caption/ASR；v2 workflow prompt 明确"不重新识别图片" |

---

## 实施要点

### M0（已完成）

- 本 ADR + ADR 0002/0003 落地
- 配套契约文档：`api-contract-dify.md` + `sse-event-mapping.md`

### M1（依赖本 ADR）

- Dify workflow yml 简化为 v2（ADR 0003）
- 锁定节点 ID：`2001/2007/2015`

### M2（依赖本 ADR）

- 实现 `DifyClient` 抽象（blocking + streaming + upload）
- 实现 `MessagesToDifyInputConverter`
- 实现 `CircuitBreaker`

### M3-M5（依赖本 ADR）

- `LLMProvider` 抽象层扩展
- `DifySseAdapter` + `SseProxyLayer`（M4）
- `/chat/stream-v2` 端点（M5）

### 验收

- M0.5 必跑 S1-S10（见 `sse-event-mapping.md` §8）
- M8 必跑端到端 e2e
- M9 必接 DifyWorkflowMetrics

---

## 变更历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1 | 2026-06-12 | 初版（M0 产出） |
