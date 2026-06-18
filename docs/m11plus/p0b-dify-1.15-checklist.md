# P0-B — Dify 1.15+ 升级 5+3=8 步 checklist

> **状态**: ⏸️ SPEC DRAFT (待 PR 实施)
> **基线**: M11 PR1-PR4 闭环 (`404f191`) + 5e00c2f + P0-A 切回后
> **优先级**: P0(必做) — M11+ backlog 第 2 项
> **关联**: `M11-CLOSURE.md §4.1 P0-B` + `M11-DIFY-1.15-UPGRADE.md §2 5 步预检`

---

## 0. 一句话总结

把 M11-DIFY-1.15-UPGRADE.md §2 已有的 5 步预检扩成 5+3=8 步,新增 3 步聚焦:
- **Step 6** P0-A 集成层回归(create_agent + activate-dify 端点全过)
- **Step 7** Release notes 5 类 breaking change 静态扫描
- **Step 8** Staging 24h 灰度 + 回滚 playbook

升级 1.15+ 前必跑,8/8 pass 才允许生产推进。

---

## 1. 现状盘清楚(阶段 0)

### 1.1 M11-DIFY-1.15-UPGRADE.md §2 已有 5 步

`docs/handoffs/M11-DIFY-1.15-UPGRADE.md` §2 的 5 步:

1. **备份** Dify data 三层 (PostgreSQL + docker volumes + `/app/upload_files`)
2. **拉镜像** `langgenius/dify-web:1.15.0` + `langgenius/dify-api:1.15.0` 到 staging
3. **6 D9 补丁 probe**: `admin_client.py:162/166/312/327-346/431` + `provider.py:251` 在 1.15.0 仍生效
4. **pytest 全过**: `tests/test_tenant_service_p0a.py` 4/4 + `tests/test_agents_activate_dify.py` 3/3 + `tests/test_api.py` 0 回归
5. **6 步 E2E**: register → create_agent (Plan A) → chat_stream → activate-dify (旧 agent) → Dify Studio 可视化 → reset-password

### 1.2 缺 3 步的根因

- **Step 6 缺**: P0-A 是 2026-06-17 切回的(本 spec),`create_agent` 走 Plan A 路径调 Dify 1.x API;
  1.15 升级时如果 `DifyAdminClient.create_app_and_workflow` 响应 schema 变了,Plan A 静默死
- **Step 7 缺**: 之前只看 M11 PR1 已知的 6 D9 补丁,1.15+ 的 release notes 里有 5 类通用 breaking
  change (login / App schema / API key / multi-tenant / DB migration) 没系统化扫
- **Step 8 缺**: 之前 5 步是 staging 即停(无 24h 灰度),但 1.15+ 是大版本升级,生产推进前必须 24h 灰度 + 量化回滚阈值

### 1.3 不扩 8 步的风险

| 漏步 | 概率 | 影响 |
|------|------|------|
| Step 6 | 中 | P0-A Plan A 集成层隐藏 break(5xx 上升),Dify 后台 App 不见 |
| Step 7 | 中 | 漏 1-2 类 breaking change(API key endpoint 路径变),E2E 5 步前 4 步 OK,第 5 步 5xx |
| Step 8 | 中 | 全量推生产 1 小时后发现 p99 翻倍,回滚窗口 1h → 1min 差距巨大 |

---

## 2. 问题清单 + 严重度(阶段 1)

### 🔴 P0-2 — P0-A 集成层未回归

- **现象**: P0-A 切回后 `create_agent` Plan A 路径新增 4 步 Dify API 调用 (create_app + enable_api + create_key + publish),升级 1.15 任何一个改 schema 都直接 break
- **影响**: 整批新 agent 创建失败,`dify_publish_status` 全 `publish_failed`
- **决策选项**:
  - A. 升级后跑 P0-A 集成层 7 pytest + 1 沙箱 E2E (**选,本 spec Step 6**)
  - B. 升级前看 Dify release notes 逐字段对比 (人工,易漏)
  - C. 不升级,Dify 1.14.2 长期跑 (技术债累积)

### 🟠 P1-2 — 5 类通用 breaking change 漏扫

- **现象**: 1.15 release notes 5 类 (login / App schema / API key / multi-tenant / DB migration) 任一改都影响 basjoo 集成
- **影响**: 4/5 步预检 OK 但生产上线后第 5 类(DB migration) 不兼容,服务起不来
- **决策选项**:
  - A. 写 grep 脚本扫 5 类关键字,人工 review 命中行 (**选,本 spec Step 7**)
  - B. 不扫,出问题再说 (回滚窗口压力大)
  - C. 等 Dify 社区 1.15 patch 出来再升 (依赖外部节奏)

### 🟠 P1-3 — 无 24h 灰度 + 量化回滚阈值

- **现象**: 当前 5 步预检是 staging 即停(无灰度),升级决策是 binary 推/不推
- **影响**: 推生产 1h 后发现 p99 翻倍,回滚成本 1h + 用户感知
- **决策选项**:
  - A. Staging 24h 灰度 + 量化阈值 (5xx < 0.1%, p99 < 2x baseline) (**选,本 spec Step 8**)
  - B. 全量推生产 1h 即停 (回滚窗口小)
  - C. Staging 跑 1h 即推生产 (灰度时间太短)

---

## 3. 决策日志(阶段 2)

### D5 ✅ — Step 6 = P0-A 集成层 7 pytest + 1 沙箱 E2E

**决策**: 升级 1.15+ 后,在 staging 跑 P0-A 集成层 7 步验收:

```
1. test_register_persists_dify_admin_creds  (P0-A 单元测试 #1)
2. test_register_dify_failure_does_not_persist_creds  (P0-A 单元测试 #2)
3. test_retry_provisioning_success_persists_creds  (P0-A 单元测试 #3)
4. test_activate_dify_200  (P0-A 端点测试 #1)
5. test_activate_dify_400_no_creds  (P0-A 端点测试 #2)
6. test_activate_dify_502_dify_5xx  (P0-A 端点测试 #3)
7. test_create_agent_picks_up_dify_creds  (P0-A 端点测试 #4)
+ 1 沙箱 E2E: register → create_agent Plan A → activate-dify (旧 Plan B agent)
```

**对架构的约束**:
- 7 pytest 在 staging 跑 (非本机) — 沙箱环境与生产同 1.15 镜像
- 7/7 + 1/1 = 8/8 pass 才允许推 Step 8
- 任一 fail → 立即 1.15 rollback 到 1.14.2,PostgreSQL 用 Step 1 备份恢复
- 沙箱 E2E 用 Playwright MCP + 162.211.183.169 staging 节点

### D6 ✅ — Step 7 = 5 类 breaking change 静态扫描

**决策**: 升级前,写 `scripts/check_dify_1_15_breaking.sh` 扫 Dify 1.15.0 源码 5 类关键字:

```bash
# 5 类 (按命中优先级排)
1. login:        grep -rn "console/api/auth/login\|console/api/admin/login" dify-1.15.0/api/
2. App schema:   grep -rn "class App\|app_model\|app_schema" dify-1.15.0/api/models/app.py
3. API key:      grep -rn "enable_api\|api_key\|/app/" dify-1.15.0/api/controllers/console/app.py
4. multi-tenant: grep -rn "tenant_id\|current_tenant" dify-1.15.0/api/libs/
5. DB migration: ls dify-1.15.0/api/migrations/versions/ | sort > new.txt
                 diff -u 1.14.2-migrations.txt new.txt
```

**对架构的约束**:
- 5 类任一命中 ≥ 1 行 → 人工 review 是否影响 basjoo 集成
- 5/5 0 命中 → 标 ✅ "0 breaking change detected",推进 Step 8
- 命中但已在本仓库 D9 补丁覆盖 → 标 ✅ "already patched",推进 Step 8
- 命中且无补丁 → 标 ⚠️ "P0-B blocker",回退到 1.14.2 长期跑,写新 D9 补丁跟进

### D7 ✅ — Step 8 = Staging 24h 灰度 + 量化回滚阈值

**决策**: staging 推 1.15 + 灰度 24h,监控 4 个量化阈值:

| 指标 | 阈值 | 监控工具 |
|------|------|----------|
| 5xx 错误率 | < 0.1% | Prometheus `rate(http_requests_total{status=~"5.."}[5m])` |
| p99 latency | < 2x baseline (P0-A 之前) | Grafana `histogram_quantile(0.99, ...)` |
| Dify App 创建成功率 | > 99% | `curl -X POST .../console/api/apps` 探针 |
| Plan A agent 创建数 | > 0 (P0-A 切回后) | basjoo DB `SELECT COUNT(*) FROM agents WHERE dify_app_id IS NOT NULL` |

**回滚 playbook**:
- 阈值 1/4 fail → 立即 rollback: `docker compose -f staging-1.15.yml down && docker compose -f staging-1.14.2.yml up -d`
- 回滚时间 < 5min (Dify 镜像 + DB 备份恢复)
- PostgreSQL 从 Step 1 备份恢复 (`pg_restore -d dify dify-1.14.2-backup.dump`)
- 24h 灰度 4/4 OK → 全量推生产,同 playbook 待命

**对架构的约束**:
- staging 跟生产同 Dify 镜像 tag + 同 basjoo 镜像 tag
- 灰度期间不开新功能(纯升级验证)
- 24h 监控数据存档到 `/var/log/dify-upgrade-1.15/` 留 audit

---

## 4. spec 详细(阶段 3)

### 4.1 改动文件清单 (本 spec PR)

| 文件 | 改动 | 行数估计 |
|------|------|----------|
| `docs/m11plus/p0b-dify-1.15-checklist.md` | 本文件 (8 步 checklist) | +250 (本文件) |
| `scripts/check_dify_1_15_breaking.sh` | 5 类 breaking change grep 脚本 | +60 (新文件) |
| `docs/runbooks/m11plus-p0b-dify-1.15-rollback.md` | 24h 灰度回滚 playbook | +120 (新文件) |
| `docs/handoffs/M11-DIFY-1.15-UPGRADE.md` | §2 末尾追加 Step 6-8 引用本 spec | +10 / 0 |
| `docs/m11/M11-CLOSURE.md` | §4.1 P0-B 标 ✅ | +5 / -3 |
| **总** | | **+445 / -3** |

### 4.2 8 步 checklist 全表 (M11-DIFY-1.15-UPGRADE.md §2 引用本表)

| # | 步骤 | 输出 | 失败动作 |
|---|------|------|----------|
| 1 | 备份 Dify data 三层 (PG + volumes + /app/upload_files) | `dify-1.14.2-backup.dump` + `dify-volumes-1.14.2.tar.gz` | 备份 fail → 不升级 |
| 2 | 拉 1.15.0 镜像 (web + api) 到 staging | `langgenius/dify-{web,api}:1.15.0` 拉成功 | 拉镜像 fail → 等镜像 tag 修正 |
| 3 | 6 D9 补丁 probe: `admin_client.py:162/166/312/327-346/431` + `provider.py:251` | 6/6 仍生效 | 任意失效 → 写新 D9 补丁,延后升级 |
| 4 | pytest 全过 (P0-A 4 + activate-dify 3 + test_api 0 回归) | 7/7 pass | 任意 fail → 不升级 |
| 5 | 6 步 E2E (register → Plan A create_agent → chat_stream → activate-dify → Dify Studio → reset-password) | 6/6 pass | 任意 fail → 查 D9 补丁覆盖 |
| 6 | **P0-A 集成层 7 pytest + 1 沙箱 E2E (本 spec 新增)** | 8/8 pass | 任意 fail → 立即 rollback 1.14.2 |
| 7 | **5 类 breaking change 静态扫描 (本 spec 新增)** | 5/5 0 命中或已 patch | 命中无 patch → 标 P0-B blocker,延后 |
| 8 | **Staging 24h 灰度 + 4 阈值监控 (本 spec 新增)** | 4/4 阈值 OK | 阈值 1/4 fail → 立即 rollback < 5min |

### 4.3 关键代码 diff

**`scripts/check_dify_1_15_breaking.sh`** (60 行,新文件):

```bash
#!/usr/bin/env bash
# 5 类 breaking change 静态扫描,本 spec Step 7
# 用法: ./scripts/check_dify_1_15_breaking.sh <dify-1.15.0-src-dir>
set -euo pipefail
SRC="${1:?usage: $0 <dify-src-dir>}"
EXIT=0

echo "[1/5] login endpoint"
if grep -rn "console/api/auth/login\|console/api/admin/login" "$SRC/api/" 2>/dev/null; then
  echo "  ⚠️ login endpoint 命中,人工 review"
  EXIT=1
fi

echo "[2/5] App schema"
if grep -rn "class App\|app_model\|app_schema" "$SRC/api/models/app.py" 2>/dev/null; then
  echo "  ⚠️ App schema 命中,人工 review"
  EXIT=1
fi

echo "[3/5] API key"
if grep -rn "enable_api\|api_key" "$SRC/api/controllers/console/app.py" 2>/dev/null; then
  echo "  ⚠️ API key 命中,人工 review"
  EXIT=1
fi

echo "[4/5] multi-tenant"
if grep -rn "tenant_id\|current_tenant" "$SRC/api/libs/" 2>/dev/null; then
  echo "  ⚠️ multi-tenant 命中,人工 review"
  EXIT=1
fi

echo "[5/5] DB migration"
NEW=$(ls "$SRC/api/migrations/versions/" 2>/dev/null | sort)
echo "$NEW" > /tmp/dify-1.15-migrations.txt
if [ -f /tmp/dify-1.14.2-migrations.txt ]; then
  if ! diff -q /tmp/dify-1.14.2-migrations.txt /tmp/dify-1.15-migrations.txt >/dev/null; then
    echo "  ⚠️ DB migration 命中,人工 review diff"
    EXIT=1
  fi
fi

[ $EXIT -eq 0 ] && echo "✅ 0 breaking change detected" || echo "❌ 命中,见上"
exit $EXIT
```

### 4.4 数据库迁移

无需 Alembic 迁移 — 本 spec 是 ops/runbook 类,不碰 basjoo 业务代码。

### 4.5 测试矩阵

| 测试 | 入口 | 期望 |
|------|------|------|
| `scripts/check_dify_1_15_breaking.sh` dry run | 对照 Dify 1.14.2 源码 | 5/5 0 命中(基线) |
| Step 6: `pytest tests/test_tenant_service_p0a.py` | 1.15 镜像跑 | 4/4 pass |
| Step 6: `pytest tests/test_agents_activate_dify.py` | 1.15 镜像跑 | 3/3 pass |
| Step 6: 沙箱 E2E (Playwright MCP) | 1.15 staging 节点 | 1/1 pass |
| Step 7: 5 类 grep | 1.15 源码 | 5/5 0 命中或已 patch |
| Step 8: 24h 灰度 | 1.15 staging | 4/4 阈值 OK |

---

## 5. PR 实施计划(阶段 4)

1. **PR 1**: `ops(m11plus): P0-B 8 步 checklist + 5 类 breaking 扫描脚本`
   - 本 spec 文件
   - `scripts/check_dify_1_15_breaking.sh` (60 行)
   - `docs/handoffs/M11-DIFY-1.15-UPGRADE.md` §2 追加 Step 6-8 引用
   - `docs/m11/M11-CLOSURE.md` §4.1 P0-B 标 ✅
   - 不需要单元测试 (脚本级别,人工跑)

2. **PR 2**: `ops(m11plus): P0-B 24h 灰度回滚 playbook`
   - `docs/runbooks/m11plus-p0b-dify-1.15-rollback.md` (120 行)
   - 包含 4 阈值监控配置 + rollback 5min 步骤
   - 不需要单元测试 (runbook,人工跑)

3. **PR 3**: `docs(m11plus): P0-B 收口 — M11-CLOSURE backlog 更新`
   - `docs/m11/M11-CLOSURE.md §4.1` 移除 P0-B (标 ✅)
   - `docs/m11plus/M11PLUS-CLOSURE.md` 草稿 (P0-A + P0-B + P0-C 收口用)

### 5.6 不做 / 留 P1+

- 不做 P0-A 集成层 7 pytest 编写 (那是 P0-A PR 1-2 的事,本 spec 引用即可)
- 不做 Dify 1.15+ 升级触发器 (CI auto-upgrade 是 P1+,人工触发即可)
- 不做 5 类 breaking change 命中后自动修 (人工 review + 写新 D9 补丁,P0-B blocker 路径)
- 不动 P0-A 已有的 D9 补丁 (M11 PR1 + M9 已固化)

---

## 6. 验收门(阶段 5)

| Gate | 状态 | 证据 |
|------|------|------|
| `docs/m11plus/p0b-dify-1.15-checklist.md` 落地 | ⏳ | 本 PR |
| `scripts/check_dify_1_15_breaking.sh` dry run 5/5 0 命中 | ⏳ | 对照 Dify 1.14.2 源码 |
| `docs/handoffs/M11-DIFY-1.15-UPGRADE.md §2` 追加 Step 6-8 | ⏳ | 本 PR |
| `docs/m11/M11-CLOSURE.md §4.1` P0-B 标 ✅ | ⏳ | 本 PR |
| `docs/runbooks/m11plus-p0b-dify-1.15-rollback.md` 落地 | ⏳ | PR 2 |
| Staging 24h 灰度 4/4 阈值 OK (实际跑) | ⏳ | 升级时跑,不在本 spec PR 范围 |

---

## 7. 风险 + 缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Step 6 P0-A pytest 7/7 pass 但沙箱 E2E 1/1 fail | 低 | 误判升级 OK | 8/8 全过才推进,沙箱是最终门槛 |
| Step 7 5 类 grep 漏报 (新 breaking change 不在 5 类) | 中 | Step 7 0 命中但生产 break | 24h 灰度 Step 8 兜底 |
| Step 8 24h 灰度过长 (push 紧急) | 低 | 用户感知延迟 | 灰度决策权 owner 强制 12h 最短 |
| 5 类 grep 命中后人工 review 漏判 | 中 | 错失 blocker | 双人 review + 沙箱 E2E 兜底 |
| PostgreSQL 备份恢复失败 | 低 | rollback 失败 | Step 1 备份后做一次 restore 演练 |

---

## 8. 修订记录

| 版本 | 日期 | 改动 |
|------|------|------|
| v1.0 | 2026-06-18 | 初稿,5+3=8 步 checklist + D5/D6/D7 决策 + 3 PR 实施计划 |
