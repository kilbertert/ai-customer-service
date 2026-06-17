# M11+ P2 — Plan A vs Plan B 战略评估 (M10+ 闭环后再评)

> **目的**: 在 M10+ chain (`c9f5a8a` → `5c34af2` → `660b8c1`) 闭环后,把 M9.5 addendum (§1.2.1) 的 Plan A/B 评估推进一步:
> 加入 M10+ 落地实际成本 (per-agent API key、Dify 1.15 升级、Fernet 加密层),产出**清晰的"是否切换"决策框架**。
> **基线**: 维持 Plan B (双层 defense-in-depth)。本文只更新触发条件矩阵 + 加 M10+ 影响维度。
> **状态**: ⏸️ STRATEGY LOCKED — Plan B 维持,触发 Plan A 切换条件未达。

---

## 0. 背景

M9.5 addendum (2026-06-13) 写 Plan A/B 评估时,**还没有** M10+ chain。M10+ 落地后,**Plan A 的"代码量 -30%-50%"估算已显著缩水**:

- per-agent Dify API key (D8 决策 (a)) — Plan A 1 key 1 tenant 也得做,**复杂度没省**
- Fernet 加密层 — Plan A 也得加密存储 per-tenant API key,**复用现有**
- 6 D9 补丁 (Dify 1.14.2 实测偏差) — Plan A 也得维护,**零节省**
- DifyStatusBadge + frontend Dify 字段 — Plan A 也得做 (UI 跟引擎无关)

**重新算账**: Plan A 实际节省 < 20% (主要剩 M6 KB 层),不是 -30%-50%。

---

## 1. M10+ 影响维度更新

| 维度 | M9.5 addendum 估算 | M10+ 后实测 | 修正 |
|------|-------------------|-------------|------|
| M3 代码减量 | -30%~-50% | **< 20%** | per-agent API key 取代 workspace-level,DifyProvider 复杂度不减反增 |
| Fernet 加密 | 0 改动 | **per-agent Dify API key 也需 Fernet** | M10+ PR2 已实现,Plan A 复用 |
| D9 6 补丁 | 0 改动 | **Plan A 也得维护** | Dify 升级是平台决策,跟 Plan A/B 无关 |
| Dify 1.15+ 升级成本 | N/A | **6 补丁逐一回归** (spec: `M11-DIFY-1.15-UPGRADE.md`) | Plan A 切换**不省**升级成本 |
| Frontend DifyStatusBadge | N/A | **已落地** (`frontend-nextjs/src/components/DifyStatusBadge.tsx`) | Plan A 也得展示状态,UI 工作量相等 |
| 后切 Plan A 触发工作量 | N/A | **< 20% 代码减 + 重写 M3 + 重测 + 灰度** | 实际收益更低,触发门槛更高 |

---

## 2. 决策框架 (再精简)

### 2.1 维持 Plan B 的硬条件 (ANY 一条)

1. **Dify Cloud 仍是潜在部署选项** — Plan A N × $59/月 不可接受 (M9.5 §1.2.1.4 #1 维持)
2. **Backend 审计仍是 SaaS 计费/合规的核心** — Plan A 把审计权让给 Dify API 反查,商业风险
3. **M10+ 投入未摊销** — per-agent API key + 6 补丁 + frontend UI,**重写收益 < 10%**

### 2.2 触发 Plan A 切换的硬条件 (ALL 必须)

| # | 条件 | 当前状态 | 何时触发 |
|---|------|---------|---------|
| 1 | 部署拓扑**确定**为自托管 (Cloud 排除) | ⏸️ 未定 | 商务签单 / 部署决策落地 |
| 2 | Basjoo tenant 数 ≥ 50 (规模效应可消化重写成本) | ❌ 当前 1 (平台自有) | B 客户签约 ≥ 50 |
| 3 | Dify Dataset API 支持 per-request dataset_id (绕开 yml 硬编码) | ⏸️ 跟踪 roadmap | Dify release notes 出现 |
| 4 | Plan A 实际代码减量 ≥ 30% (重测) | ❌ M10+ 后估算 < 20% | 重写收益阈值上调 |
| 5 | Backend 审计替代方案 (ClickHouse / 计费数据 warehouse) 上线 | ❌ 无 | 商业化计费系统落地 |

**ALL 5 必须达**才考虑 Plan A 切换。**当前 0/5 达**,Plan B 锁死。

---

## 3. Plan B 现状 (M10+ 后)

### 3.1 代码拓扑

```
basjoo backend (workspace-level)
├── workspace_id 直接 FK (M10 G2 决定)
├── Qdrant 物理 collection per workspace
├── Agent 字段 dify_api_key (Fernet 加密)
└── DifyProvider._resolve_api_key()
    → agent.dify_api_key
    → workspace.dify_api_key
    → settings.dify_api_key

Dify (1 workspace, basjoo 平台自有)
└── 共享 1 个 workspace,所有 per-agent workflow 在内部 by-name 区分
```

### 3.2 关键不变量

| 不变量 | 维护方 | 验证 |
|--------|-------|------|
| Backend Qdrant collection 与 workspace_id 一一对应 | Backend | `test_kb_collection_isolation` |
| Fernet 加密存储 per-agent Dify API key | Backend | `test_dify_api_key_fernet_roundtrip` |
| Dify 1.14.2 6 补丁维持 | Backend (Dify 集成层) | 118 Dify tests |
| Cross-tenant 拒绝 (Backend 隔离) | Backend | `test_cross_tenant_*` |
| Dify workspace 数量 = 1 | Dify (docker-compose opt-in) | manual + `docker inspect` |

### 3.3 切换 Plan A 工作量 (再估)

如果 §2.2 5 条件 ALL 达,Plan A 切换**最少工作量**:

| 模块 | Plan B 现状 | Plan A 切换 | 工作量估算 |
|------|------------|------------|----------|
| DifyProvider | 3 级 fallback + Fernet | per-tenant DifyClient 工厂 | -200 行 |
| KB 隔离层 | Qdrant collection per workspace | Dify Dataset API per workspace | -400 行 |
| 配额 / 计费 | Backend SQL 直查 | Dify API 反查 + Backend 镜像表 | -100 / +200 行 (净 +100) |
| Frontend | DifyStatusBadge 已实现 | 不变 | 0 |
| D9 6 补丁 | 维护中 | 不变 | 0 |
| Fernet 加密层 | 复用 | 不变 | 0 |
| 测试重写 | 118 Dify tests | 重写 ~60% | 3 人日 |
| 灰度发布 | 无 (同构切换) | 必备 | 2 人日 |
| **合计** | — | — | **~7 人日** (从 M9.5 估的 5 人日上调) |

---

## 4. 长期监控 (每季度审)

| 监控指标 | 阈值 | 数据来源 |
|---------|------|---------|
| Basjoo tenant 数 | < 10: Plan A 不划算;10-50: 灰度;> 50: 考虑切换 | DB `SELECT COUNT(*) FROM workspaces` |
| Dify Cloud 定价 | workspace 单价 ≤ $20/月 才考虑 Plan A + Cloud | Dify 官网 release notes |
| Dify Dataset API 改进 | per-request dataset_id 支持 | Dify GitHub releases |
| Backend 审计需求 | 商业化计费系统落地 = Plan A 切换窗口 | 商业化里程碑 |
| Dify 升级频次 | > 2 次/年 显著增加 6 补丁维护成本 | `docs/handoffs/` 计数 |

**审视频率**: 每季度一次 (M11+ 战略评审)。下次评审: **2026-09-16**。

---

## 5. 触发 Plan A 切换的"早行动"信号 (任意 1 条触发立即讨论)

1. **大客户签约** (≥ 10 tenants 一次性到位) — 重写收益阈值可能触发
2. **Dify 商业化策略变更** (降价 / 免费 workspace) — Plan A 经济性反转
3. **Backend 审计层独立化** (ClickHouse 等) — Plan A 不再让渡审计权
4. **Dify Dataset API 突破** — Plan A 切换核心阻力消除

---

## 6. 与 M10+ chain 的关系

| M10+ 决策 | 对 Plan A/B 影响 |
|----------|-----------------|
| D3 2-step create (app + workflow 分离) | 0 — Plan A 也得 2-step |
| D8 (a) per-agent API key | **降低** Plan A 收益 (API key 维度不变) |
| D9 (c) publish 容错 | 0 — Dify 平台行为,跟方案无关 |
| Fernet 加密层 | **降低** Plan A 收益 (复用现有) |
| 6 D9 补丁 | **0** — Dify 升级维护成本跟方案无关 |

**结论**: M10+ chain 闭环后,Plan A 切换收益**进一步缩水** (< 20% 估算降至 < 15%)。维持 Plan B 的决策**更坚定**。

---

## 7. 决策 (LOCKED)

**维持 Plan B,推迟 Plan A 评估至 2026-09-16**。

**理由**:
- M10+ 闭环后,Plan A 实际收益 < 15%
- §2.2 5 触发条件当前 0/5 达
- §3.3 切换工作量从 5 人日上调至 7 人日 (M9.5 低估)
- M11+ 优先 P1 缺口 (Dify 1.15 升级 / 6 补丁维护 / dify-data 备份) 比战略切换 ROI 更高

**撤销决策条件** (未来):
- §2.2 任一触发条件达成 → 启动 4 周 Plan A 切换 Sprint
- §5 早行动信号触发 → 立即开战略评审会

---

## 附录 A: 参考文档

- `docs/dify-integration-plan.md §1.2.1` — M9.5 addendum 原始 Plan A/B 评估
- `docs/dify-integration-plan.md §17` — M10+ 完整规范
- `docs/handoffs/M10PLUS5-REPORT.md` — M10+5 docs+ops consolidation
- `docs/handoffs/M11-DIFY-1.15-UPGRADE.md` — Dify 升级前 6 补丁回归 spec
- `memory/basjoo-dify-isolation-strategy.md` — basjoo-Dify 隔离战略 (v1 决策)
- `memory/fact-dify-multi-tenant-architecture.md` — Dify Tenant=Workspace 实体发现

---

**END OF M11-P2-STRATEGY-PLAN-AB**