# M11+ P1 Kickoff — M10+ chain 本机尾巴

> **目的**: 关掉 M10+4 沙箱 E2E 留下的 3 个本机尾巴:6 个 Dify 测试 app 残留 / `docker compose --profile dify` 真起容器 / Playwright chat_stream E2E。
>
> **基线**: HEAD `5c34af2` (M10+5) + P0 卫生债 2 commits (`3db9039` `4b27d37`),已 push origin `caf5ab8..3db9039`。
>
> **本 PR 不动** backend / frontend / docs 业务代码 — 纯本机 ops + 验证。

---

## 上下文 & 必读

| 文档 | 用途 |
|------|------|
| `docs/handoffs/M10PLUS4-REPORT.md` | 沙箱 E2E 7 步原始报告 (§6 publish 容错, §8 cleanup DEFER) |
| `docs/handoffs/M10PLUS5-REPORT.md` | M10+5 终态报告 (§3 docker-compose dify profile 详设) |
| `docs/handoffs/M10PLUS5-REPORT.md` §3.1 | `dify` service docker-compose YAML(可直 copy 验) |
| `docs/dify-integration-plan.md` §17 | M10+ 完整规范 (§17.5 D9a-D9f 6 补丁) |
| `memory/m10plus-chain-closure-2026-06-16.md` | M10+ chain 闭环 + 7 项 M11+ backlog |

**已知**: M10+4 沙箱预检**推翻**了 3 个旧假设:
- Docker build ✅ 通(不是"沙箱挂")
- 真 Dify HTTP ✅ 通(124.243.178.156:8501)
- Playwright 真 spec ❌ 仍拦(cmd.exe spawn)

所以 P1-1 (HTTP 清理) + P1-2 (docker compose) **本机**可做;P1-3 (Playwright E2E) **沙箱不通,只能本机**。

---

## 任务范围

### P1-1: 清 6 个 Dify 测试 app 残留

**来源**: M10+4 §8 cleanup DEFER — 沙箱跑 7 步 E2E 时创建了 6 个 Dify app(`M10+4 Test Agent` 类似命名),留在 124.243.178.156:8501 那边。

**目标**: 删除全部 6 个(或列出后人工确认删除),Dify admin 账号登录操作。

**本机命令模板**:

```bash
# 1. 准备 env vars
export DIFY_API_BASE="http://124.243.178.156:8501"
export DIFY_ADMIN_EMAIL="<dify-admin-email>"        # 跟 M10+4 §3 实际值一致
export DIFY_ADMIN_PASSWORD="<dify-admin-password>"

# 2. 登录拿 session cookie
curl -s -c /tmp/dify-cookies.txt -X POST \
  "${DIFY_API_BASE}/console/api/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${DIFY_ADMIN_EMAIL}\",\"password\":\"$(printf %s "${DIFY_ADMIN_PASSWORD}" | base64)\"}"
# 注: D9b 修复后 password 字段是 base64 编码,不是 RSA 加密

# 3. 列 app
curl -s -b /tmp/dify-cookies.txt \
  "${DIFY_API_BASE}/console/api/apps?page=1&limit=50" \
  | python -c "
import sys, json
d = json.load(sys.stdin)
apps = d.get('data', d) if isinstance(d, dict) else d
for a in apps:
    print(f\"{a.get('id','?')} | {a.get('name','?')} | {a.get('mode','?')} | {a.get('created_at','?')}\")"

# 4. 删除 (按 ID 批量, 名字含 'M10+' / 'Test Agent' / 'test_' 等 sandbox 标记)
for app_id in <list-of-6-ids>; do
  curl -s -b /tmp/dify-cookies.txt -X DELETE \
    "${DIFY_API_BASE}/console/api/apps/${app_id}"
  echo "Deleted ${app_id}"
done
```

**判定 PASS**:
- 删除前列表包含 ≥ 6 个 `M10+` / `test_` 模式 app
- 删除后 `GET /console/api/apps?page=1&limit=50` 列表里这些 app 消失
- 不误删: 业务 app(命名清晰的)保留

**风险 / 撤销**:
- 风险: 误删业务 app — **必须**先 `--dry-run`(只列, 不删),人工核对后再删
- 撤销: Dify Console 端可手动重建 app(丢 workflow 草稿, 不可逆)

**Hard gate**:
| Gate | 命令 | 通过条件 |
|------|------|---------|
| G1.1 列表包含目标 | step 3 输出 | ≥ 6 个匹配 app |
| G1.2 删除完成 | step 4 + 再次 list | 0 个残留 |
| G1.3 不误删 | list 比对删除前/后 | 业务 app 数 - 残留数 = 删除数 |

---

### P1-2: `docker compose --profile dify up -d` 真起容器

**来源**: M10+5 §3.4 DEFER — 镜像 ~3GB,沙箱拉不起;但沙箱 docker daemon 实际有权限(只是镜像大)。

**目标**: 本机拉 `langgenius/dify-api:1.14.2` 镜像 + 起 `basjoo-dify` 容器 + healthcheck 通过 + 验 6 步 E2E 完整可跑(同 M10+4 §6 流程)。

**本机命令模板**:

```bash
# 1. 拉镜像(3GB, 留 4-6 GB 磁盘, 估计 5-15 分钟)
docker pull langgenius/dify-api:1.14.2

# 2. 起容器(opt-in profile)
docker compose --profile dify up -d dify

# 3. 看 logs
docker logs -f basjoo-dify 2>&1 | head -100
# 预期: postgres migration 跑通 / redis 连接 OK / qdrant 连接 OK / API listens on 0.0.0.0:5001

# 4. Healthcheck (Dify 1.14.2 setup endpoint 未登录返 401, 这是 healthy 标志)
sleep 30  # 等 migration
curl -s -o /dev/null -w "health: %{http_code}\n" \
  "http://localhost:8501/console/api/setup"
# 预期: 401 (NOT 500 / NOT 502)

# 5. 跟真 Dify 同样跑 M10+4 §6 7 步 E2E, 但用 localhost:8501 替代 124.243.178.156:8501
# 注意: 端口是 8501:5001, 跟沙箱一致
```

**判定 PASS**:
- 镜像拉取无 404 / hash mismatch
- 容器起来后 30s 内 healthcheck 401
- 完整 6 步 E2E 跑通(`M10+4 Test Agent` 创建 + graph 配 + publish + chat_stream)
- `dify_publish_status='published'`(不是 `publish_failed`,因为 1.14.2 允许空 graph 走完整链路)

**风险 / 撤销**:
- 风险: 跟 `124.243.178.156:8501` 真 Dify 同时跑 → 数据串扰
  - **必检**: `docker ps` 看 `basjoo-dify` 容器在跑, **不是**连接 124.243.178.156
- 风险: postgres `dify` DB 已存在 / Redis `REDIS_DB=1` 已有数据 → migration 跳步可能失败
  - 解决: `docker volume rm basjoo_dify-data` 干净重启
- 撤销: `docker compose --profile dify down -v`(删容器 + volume)

**Hard gate**:
| Gate | 命令 | 通过条件 |
|------|------|---------|
| G2.1 镜像存在 | `docker images langgenius/dify-api:1.14.2` | 列表里有 |
| G2.2 容器起 | `docker ps --filter name=basjoo-dify` | 状态 `Up` |
| G2.3 healthcheck | step 4 curl | 401 |
| G2.4 6 步 E2E | 复用 M10+4 §6 7 步流程 | 7/7 PASS, `dify_publish_status='published'` |

---

### P1-3: Playwright chat_stream E2E

**来源**: M10+4 §7 sandbox Playwright DEFER (cmd.exe spawn 拦) + M10+5 §1.3 sandbox skip 项 #3。

**目标**: 本机 Git Bash 跑 Playwright 真 spec 走通 `chat_stream` 端到端(Dify 走通 + think strip + SSE 解析 + DB 持久化)。

**本机命令模板**:

```bash
# 1. 确保本机起 basjoo dev 栈 (跟 P1-2 dify profile 同时)
docker compose --profile dev up -d
docker compose --profile dify up -d dify

# 2. 装 Playwright (如未装)
cd frontend-nextjs
npm install
npx playwright install chromium

# 3. 跑 chat_stream E2E spec (M9.4 已写的 specs/07-think-streaming 之类)
npm run test:e2e -- specs/07-think-streaming.spec.ts

# 4. 跑 widget E2E (M7 时代的 MCP 交互式, 现在改 CI 守门)
npm run test:e2e:widget

# 5. 全跑一遍
npm run test:e2e:all
```

**判定 PASS**:
- chat_stream 端到端 SSE 解析成功
- thinking tag 被 strip(走 M9.1 stream-level + M9.3 final-state 双保险)
- 最终回复写入 `chat_messages.content` DB 字段
- Dify API 失败时降级路径触发(如果 P2 已合)或 SSE 返 error event(P2 未合时)

**风险 / 撤销**:
- 风险: 跟 sandbox 同端口冲突(5433 / 3001) — 本机 `lsof -i :3001` 查占用
- 撤销: 删测试数据 / 删 basjoo dev 容器重启

**Hard gate**:
| Gate | 命令 | 通过条件 |
|------|------|---------|
| G3.1 spec 跑通 | `npm run test:e2e` | 0 fail |
| G3.2 think strip 验 | spec 断言 `<think>` 不在最终回复 | ✅ |
| G3.3 DB 持久化 | spec 查 `chat_messages` 表新行 | 1+ 新行 |
| G3.4 widget 嵌入 | `npm run test:e2e:widget` | 0 fail |

---

## 执行流程

1. **P1-1 先做**(最低风险, 不依赖 Docker):
   - 列 app → 人工核对 → 删 → 验
2. **P1-2 其次**(依赖磁盘 + Docker daemon):
   - 拉镜像 → 起容器 → healthcheck → 跑 6 步 E2E
3. **P1-3 最后**(依赖 P1-2 + dev 栈):
   - Playwright 跑通 → 验证 think strip + DB 持久化
4. **写 M11-P1-REPORT.md** 10 节结构(跟 M10+4/M10+5 对齐)
5. **commit**:`chore(ops): M11+ P1 — Dify app 清理 + docker compose dify 真起 + Playwright E2E`
6. **push** to origin (按用户指示)

---

## 沙箱 vs 本机 边界

| 任务 | 沙箱 | 本机 |
|------|------|------|
| P1-1 HTTP 清理 | ✅ 通(M10+4 验过) | ✅ |
| P1-2 镜像拉取 | ❌ 3GB 太大 | ✅ |
| P1-2 容器起 | ⚠️ 试过 ok 但镜像拉不起 | ✅ |
| P1-2 6 步 E2E | ✅ 通(用 124.243.178.156:8501 跑过) | ✅ |
| P1-3 Playwright | ❌ cmd.exe spawn 拦 | ✅ |
| P1-3 widget E2E | ❌ 同上 | ✅ |

**沙箱内能 partial 做的**: P1-1 (用真 Dify 124.243.178.156:8501) + P1-2 的 6 步 E2E 部分(用真 Dify 替代本机 dify 容器)。

**沙箱内不做**: P1-2 拉镜像 + 起本机容器 / P1-3 任何 Playwright。

---

## 完成定义

回复格式(贴给用户):

```
✅ M11+ P1 commit 完成 (<SHA>) <type>: <subject>. N files changed, +X/-Y.

[P1-1 验收表 — 6 个 app 删前/删后]
[P1-2 验收表 — 镜像 + 容器 + healthcheck + 6 步 E2E]
[P1-3 验收表 — Playwright spec + think strip + DB 持久化]
[沙箱 vs 本机: 哪些本机做了, 哪些沙箱替代]
[沙箱 skip 项 / 留给 M11+ P2 的]
[结论: PASS / CONDITIONAL PASS / FAIL]
```

不要 UNCONDITIONAL PASS — M10+4 教训在那里。本机能跑通的写 ✅,跑不通的写 ⚠️ DEFER + 留给 P2。

---

## 跨任务依赖

- P1-2 假设 P1-1 已完成(否则 6 个测试 app 还在,跑 6 步 E2E 会再增 1 个)
- P1-3 假设 P1-2 已完成(否则 dify workflow 端点 5001 没人接)
- 三个都不改 backend / frontend / docs 业务代码(纯 ops + 验证)
- 不动 china_charge_kf/(FROZEN)
- 不动 dify-integration-plan.md(M10+5 §17 已锁定)
