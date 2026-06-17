# M11+ — Dify 1.15+ 升级准备 spec

> **目的**: Dify 1.15+ 升级前的回归测试 checklist + 6 补丁逐一验证脚本。
> **基线**: M10+4 commit `8dc84e9` (D9a-D9f 6 补丁) + M10+5 commit `5c34af2` (docs 收口)
> **触发条件**: 升级 Dify 之前**必做** (M10+5 §8 #3 已知缺口)
> **状态**: ⏸️ PRE-UPGRADE PREP — 真升级时按本 spec 跑

---

## 0. 背景

Dify 1.15+ 升级前,6 个 D9 补丁 (针对 1.14.2 实测偏差) 都需要**逐一回归**。1.15+ 可能:
- 改 schema (尤其 D9c graph 格式)
- 改 endpoint 路径 (D9a `auth/login` 历史改名)
- 改 body 格式 (D9e `PublishWorkflowPayload`)
- 改 runtime path 前缀 (D9f `/v1` 后缀)
- 改 login 加密方式 (D9b base64)
- 改 sync_draft 响应格式 (D9d workflow.id 可能回来也可能不回来)

**关键风险**: 6 补丁任何 1 个回归都会让 `create_app_and_workflow` 链断,生产事故。

---

## 1. 6 补丁逐一回归表

| 编号 | 文件:行 | 1.14.2 实测 | 1.15+ 预期 | 验证命令 | 通过条件 |
|------|---------|------------|-----------|----------|---------|
| **D9a** | `admin_client.py:162` | `POST /console/api/login` | 同名 / 改? | `curl -X POST "${DIFY_BASE}/console/api/login"` | 返 200 + Set-Cookie csrf_token |
| **D9b** | `admin_client.py:166` | password base64 编码 | 同上? | 登录返 200 不是 401 | 用错 encoding 应 401 |
| **D9c** | `admin_client.py:312` | `graph: {nodes:[], edges:[]}` 显式空 | schema 变? | mock `sync_draft_workflow` 验 body shape | 1.15+ 可能换 key 名 |
| **D9d** | `admin_client.py:327-346` | sync_draft 返 `{result, hash, updated_at}` 无 id → fallback list | 同上? | 跑 1.15 真 Dify,fallback 仍通 | `workflow_id` 不为空字符串 |
| **D9e** | `admin_client.py:431` | publish 必带 `PublishWorkflowPayload` body | schema 变? | mock `publish_workflow` 验 body shape | 1.15+ 可能加必填字段 |
| **D9f** | `provider.py:251` | runtime 路径必带 `/v1` | 同上? | `curl -X POST "${DIFY_BASE}/v1/workflows/run"` | 200 不 404 |

---

## 2. 升级前 5 步预检

### Step 1: 备份生产 Dify 数据

```bash
# 1a. 备份 dify-data volume
docker run --rm -v basjoo-dify-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/dify-data-$(date +%F).tgz /data

# 1b. 备份 Dify DB schema (Dify 1.14.2 用了 postgres DB=dify)
docker exec basjoo-postgres pg_dump -U postgres -d dify \
  > dify-db-$(date +%F).sql
```

### Step 2: 1.15+ 镜像可拉 + healthcheck 通

```bash
# 2a. 拉 1.15+ 镜像 (具体 tag 由 release notes 决定)
docker pull langgenius/dify-api:1.15.x

# 2b. 改 docker-compose.yml 镜像 tag
#     image: langgenius/dify-api:1.14.2
#     image: langgenius/dify-api:1.15.x

# 2c. 起容器,看 healthcheck
docker compose --profile dify up -d
docker inspect --format='{{.State.Health.Status}}' basjoo-dify
# 期望: healthy (不是 unhealthy / starting)
```

### Step 3: 1.15+ console 端点 6 补丁逐一探针

```bash
export DIFY_BASE="http://localhost:8501"
export DIFY_ADMIN_EMAIL="<dify-admin-email>"
export DIFY_ADMIN_PASSWORD="<dify-admin-password>"

# D9a: login URL 是否改名
curl -s -c /tmp/dify-cookies.txt -X POST "${DIFY_BASE}/console/api/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${DIFY_ADMIN_EMAIL}\",\"password\":\"$(printf %s ${DIFY_ADMIN_PASSWORD} | base64)\"}"
# 期望 200; 若 404 → 1.15+ 改名, 改 admin_client.py:162

# CSRF token 提取 (Dify 1.14.2+ console 端点都走 double-submit)
export CSRF_TOKEN=$(awk '$6 == "csrf_token" { print $7 }' /tmp/dify-cookies.txt)

# D9c: sync_draft body shape
APP_ID=$(curl -s -b /tmp/dify-cookies.txt -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  "${DIFY_BASE}/console/api/apps?page=1&limit=1" | python -c "import json,sys; print(json.load(sys.stdin)['data'][0]['id'])")

curl -s -b /tmp/dify-cookies.txt -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -X POST "${DIFY_BASE}/console/api/apps/${APP_ID}/workflows/draft" \
  -H 'Content-Type: application/json' \
  -d '{"graph": {"nodes": [], "edges": []}}'
# 期望 200; 若 400 → 1.15+ 改 schema, 改 admin_client.py:312

# D9d: sync_draft 是否返 workflow.id
RESP=$(curl -s -b /tmp/dify-cookies.txt -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -X POST "${DIFY_BASE}/console/api/apps/${APP_ID}/workflows/draft" \
  -H 'Content-Type: application/json' -d '{"graph": {"nodes": [], "edges": []}}')
echo "${RESP}" | python -c "import json,sys; d=json.load(sys.stdin); print('id present:', 'id' in d)"
# 期望 id present; 若否 → D9d fallback 仍通 (admin_client.py:327-346)

# D9e: publish body shape
curl -s -b /tmp/dify-cookies.txt -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -X POST "${DIFY_BASE}/console/api/apps/${APP_ID}/workflows/publish" \
  -H 'Content-Type: application/json' \
  -d '{"marked_name": "", "marked_comment": ""}'
# 期望 200/201 (空 graph 也 OK); 若 415 → 1.15+ 改 body 要求, 改 admin_client.py:431

# D9f: runtime path 必带 /v1
curl -s -X POST "${DIFY_BASE}/v1/workflows/run" \
  -H "Authorization: Bearer app-test-token" \
  -H 'Content-Type: application/json' \
  -d '{"inputs": {}, "response_mode": "blocking", "user": "probe"}'
# 期望 401/403 (token 错); 若 404 → 1.15+ 改 path, 改 provider.py:251
```

### Step 4: backend pytest 6 补丁 mock 跑通

```bash
cd backend && /c/Users/q1234/miniconda3/python.exe -m pytest \
  tests/test_dify_admin_client.py \
  tests/test_dify_client.py \
  tests/test_dify_provider.py \
  tests/test_chat_stream_dify.py \
  -v --tb=short
# 期望 118/118 pass; 若 fail → 检查 §1 表对应 D9 编号,按需改实现 + 测试
```

### Step 5: 真 Dify 端到端 6 步 E2E (跑 M10+4 §6 模板)

```bash
# 跑 docs/handoffs/M10PLUS4-REPORT.md §6 的 6 步 E2E
# 1. POST /console/api/login
# 2. POST /console/api/apps (create agent app)
# 3. POST /apps/{id}/workflows/draft (lazy create workflow)
# 4. POST /apps/{id}/api-enable
# 5. POST /apps/{id}/api-keys
# 6. POST /apps/{id}/workflows/publish (D9c/D9e 容错 400/422)
# 期望 6/6 PASS; publish 返 True 或 False 都算 (D9c 容错)
```

---

## 3. 升级失败回滚

如果 §2 任何一步 fail:

```bash
# 3a. 停 1.15+ 容器
docker compose --profile dify down

# 3b. 改回 1.14.2 镜像 tag
#     image: langgenius/dify-api:1.15.x
#     image: langgenius/dify-api:1.14.2

# 3c. 重新起 1.14.2 容器
docker compose --profile dify up -d

# 3d. 验证 1.14.2 6 步 E2E 仍通 (确认回滚成功)

# 3e. 把 1.15+ 失败原因记入 M11-DIFY-1.15-FAILED-REPORT.md
#     包含: 哪个 D9 补丁回归 / 1.15+ 改了什么 / 建议修复方向
```

---

## 4. 升级成功后 4 步收口

```bash
# 4a. 把 §1 表 "1.15+ 预期" 列更新为实测结果
# 4b. 把 §2 探针脚本结果 (status code / body) 归档
# 4c. 更新 docs/dify-integration-plan.md §17.5 + §16 变更日志
# 4d. 写 M11-DIFY-1.15-UPGRADE-DONE.md (跟 M10+5 REPORT 格式对齐, 10 节)
```

---

## 5. 长期 Dify 版本兼容策略

| Dify 版本 | 我们的兼容状态 | 6 补丁要求 |
|-----------|---------------|-----------|
| 1.14.2 (当前) | ✅ 已验证 (M10+4 沙箱 E2E) | 全 6 补丁必须 |
| 1.15.x (待升) | ⏸️ 待回归 | 按 §1 表探针 |
| 1.16.x+ | 🔮 远期 | 升级前重跑本 spec |

**重要**: 任何 Dify 升级都应**先在 staging 跑完 §2 5 步**,确认通过后再切生产。

---

## 附录 A: 探针脚本 (可独立跑)

把 §2 Step 3 的 curl 串打包成 `scripts/probe-dify-1.15.sh` (本机或 CI 跑),失败即 fail-fast。

## 附录 B: 参考

- `docs/dify-integration-plan.md §17.5` — D9a-D9f 6 补丁原始描述
- `docs/handoffs/M10PLUS4-REPORT.md §6` — 6 步 E2E 模板
- `docs/handoffs/M10PLUS5-REPORT.md §4` — 6 补丁落点 (commit + 行号)
- `M11-P1-REPORT.md` — 3 sandbox app cleanup 经验 (CSRF + base64 password 实际跑过)
- 沙箱真 Dify: `http://124.243.178.156:8501` (1.14.2, 2026-06-16 verified)

---

**END OF M11-DIFY-1.15-UPGRADE SPEC**
