# basjoo 本地启动与日常运维手册

> 范围:`fork/main` 之后的 **dev profile**(8 container,`docker compose --profile dev up -d`)。
> 读者:本机 dev / 改代码自测的工程师。
> 配套:`docs/requirements-second-pass.md` 写**改什么**,`CLAUDE.md` 写**架构**。
> 生产部署走 `install-deploy.sh`,**不**用这份。

---

## 0. TL;DR

```bash
# 0. 国内网络(可选,见 §3.1)
docker pull docker.m.daocloud.io/library/python:3.11-slim
docker pull docker.m.daocloud.io/library/node:20-alpine
docker tag docker.m.daocloud.io/library/python:3.11-slim python:3.11-slim
docker tag docker.m.daocloud.io/library/node:20-alpine node:20-alpine

# 1. 起
docker compose --profile dev up -d

# 2. 等 + 验
curl localhost:8000/health   # → {"status":"healthy"}
# admin:           http://localhost:3001
# backend:         http://localhost:8000
# widget demo:     http://localhost:8000/widget-demo  ← 模拟"客户网站"
```

---

## 1. 端口与服务

dev profile 8 container,**对外只暴露 3000 / 8000**:

| 端口 | 服务 | 角色 |
|------|------|------|
| **3001** | `basjoo-frontend-dev` (Next.js) | **管理后台**:管理 agent / KB / 配置 |
| **8000** | `basjoo-backend-dev` (FastAPI) | **后端 API + widget 静态资源** |
| 8000/widget-demo | HTML demo 页(已嵌 sdk.js) | 模拟客户网站,自测 widget |
| 8000/sdk.js | widget 嵌入脚本 (~45KB) | 给真实客户网站 `<script>` 引 |
| 8000/api/v1/chat | 公开 chat JSON | widget SDK 调用 |
| 8000/health | 健康检查 | 探针 / CI |
| 6333 / 6379 / 5433 / 8001 | Qdrant / Redis / Postgres / Scrapling | **内部**,不走公网;PG 宿主端口 5432 → 5433 避本机冲突(2026-06-14) |

> 访客**不直接访问 basjoo**。访客在客户网站上,客户网站 `<script>` 加载 sdk.js,SDK 调 `/api/v1/chat`。basjoo **不托管访客页面**。

---

## 2. 前置依赖

| 依赖 | 验证 |
|------|------|
| Docker Desktop ≥ 4.x(自带 Compose v2) | `docker --version` |
| WSL2(Windows 强依赖) | `wsl --status` |
| 8GB+ 可用内存 | `docker info` |
| 浏览器 | — |

> Python venv:`backend/venv_pr1/`(不是默认 `venv/`,见 §6.2)。

---

## 3. 首次启动

### 3.1 镜像(国内网络)

dev Dockerfile 是 `FROM python:3.11-slim` / `FROM node:20-alpine`,Docker Hub 拉不动则需手动 tag:

```bash
docker pull docker.m.daocloud.io/library/python:3.11-slim
docker pull docker.m.daocloud.io/library/node:20-alpine
docker tag docker.m.daocloud.io/library/python:3.11-slim python:3.11-slim
docker tag docker.m.daocloud.io/library/node:20-alpine node:20-alpine
```

能直连 `docker.io/library/*` 的环境跳过。

**永久方案**:Docker Desktop → Settings → Docker Engine → 加 `"registry-mirrors": ["https://docker.m.daocloud.io"]` → Apply & Restart。

### 3.2 `.env` 与 LLM key

`.env` 已 gitignore。dev profile 的 `backend-dev` 在 `docker-compose.yml:195-208` **显式列 env 变量**,**不**走 `env_file:`,改 `.env` 不会自动进容器。

加全局 LLM key 两条路:
1. **per-agent**(推荐):admin UI → agent 配置填,存 SQLite
2. **env 注入**:改 `docker-compose.yml:195-208` 加 `${XXX_API_KEY:-}`,再 `up -d --build backend-dev`

> **不要**把 key 贴在 AI 聊天 / Slack / GitHub issue 里(见 §6.4)。

### 3.3 启动

```bash
docker compose --profile dev up -d
docker compose --profile dev ps    # STATUS 绿后 OK
```

首次 `up -d` 触发 backend-dev / frontend-dev build(无本地镜像),3-6 分钟。`--watch` flag 开 watch 模式。

### 3.4 默认 admin

`init_db()` 首次跑会建 `me@example.com` / `platform_admin`(无密码)。

**当前 dev 实例**(本机 smoke test 已重置):
- `me@example.com` / `smokepass123` / `super_admin`

新机器或 reset 后:用 §5.2 走 SQLite 重置,或进 admin UI 注册新账号。

---

## 4. 日常操作

### 4.1 起停

| 操作 | 命令 |
|------|------|
| 起 | `docker compose --profile dev up -d` |
| 停(保 volumes) | `docker compose --profile dev down` |
| 停 + 删 volumes(数据全清) | `docker compose --profile dev down -v` |
| 重启单 service | `docker compose --profile dev restart backend-dev` |
| 改依赖 / Dockerfile 后 | `docker compose --profile dev up -d --build backend-dev frontend-dev` |

### 4.2 日志

```bash
docker compose --profile dev logs -f                       # 全部
docker logs -f basjoo-backend-dev                          # 单个
docker logs --tail 100 basjoo-backend-dev | grep -iE "error|exception"
```

### 4.3 进 container 调试

```bash
docker exec -it basjoo-backend-dev bash
docker exec basjoo-backend-dev python3 -c "
import sqlite3
con = sqlite3.connect('/app/data/basjoo.db')
for r in con.execute('SELECT id,email,role FROM admin_users'): print(r)
"
docker exec basjoo-backend-dev curl -s localhost:8000/health   # 内部调,躲宿主侧限流
```

### 4.4 改代码循环

| 改了 | rebuild? | 重启 |
|------|---------|------|
| `backend/**/*.py` 业务代码 | 否 | watch mode 自动,或 `restart backend-dev` |
| `backend/requirements.txt` / `Dockerfile.dev` | **是** | `up -d --build backend-dev` |
| `services/__init__.py` / 新顶层 module | 否(但 reload 不重 import) | **`restart backend-dev`** |
| `frontend-nextjs/**` 业务代码 | 否 | Next.js HMR 自动 |
| `frontend-nextjs/package.json` | **是** | 重建 frontend-dev |
| `nginx/**` | 否(挂卷) | `restart nginx` |
| `docker-compose.yml` | 否 | `up -d`(重 plan) |
| `widget/src/**` | 否(产物 `backend/static/sdk.js` bind-mount) | `restart backend-dev` 让缓存失效 |

### 4.5 smoke test

5 步全 200 即健康:

```bash
curl -s -o /dev/null -w "health:     %{http_code}\n" localhost:8000/health         # 200
curl -s -o /dev/null -w "frontend:   %{http_code}\n" localhost:3001/              # 200(首 20s 编译)
docker exec basjoo-backend-dev curl -s -X POST localhost:8000/api/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"smokepass123"}' \
  | python3 -c 'import sys,json; print("login: token_len=",len(json.load(sys.stdin)["access_token"]))'
# login: token_len= ~120
docker exec basjoo-backend-dev curl -s -H "Authorization: Bearer $(docker exec basjoo-backend-dev curl -s -X POST localhost:8000/api/admin/login -H 'Content-Type: application/json' -d '{"email":"me@example.com","password":"smokepass123"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')" \
  localhost:8000/api/v1/agents | head -c 100
# {"agents":[],"total":0}
curl -s -o /dev/null -w "widget-demo: %{http_code}\n" localhost:8000/widget-demo # 200
```

### 4.6 多模态 widget 自测（PR11–14）

需要 vision/ASR API key 才完整通过；不依赖 key 的部分（上传 / schema / DB）直接测。

```bash
# 0. 确认 stack 健康
curl -s http://localhost:8000/health   # → {"status":"healthy"}

# 1. Python 端到端 smoke（完整覆盖，见 scripts/verify_pr15.py）
# 需要先安装 httpx: pip install httpx
python scripts/verify_pr15.py
# 期望 10/10 全绿（vision/ASR 未配时 done.attachments=[] 但流程继续）

# 2. 手动 curl 上传测试（无 Python）
# 2a. 上传 1×1 PNG image
curl -s -X POST http://localhost:8000/api/v1/chat/attachments \
  -H "Origin: http://localhost:8000" \
  -F "file=@/tmp/test.png;type=image/png" \
  -F "agent_id=$(docker exec basjoo-backend-dev python3 -c \"import sqlite3 as s; c=s.connect('/app/data/basjoo.db'); print(c.execute('SELECT id FROM agents WHERE is_active=1 LIMIT 1').fetchone()[0])\")" \
  -F "session_id=test-sess" \
  -F "visitor_id=test-vis" | python3 -m json.tool
# → {"attachment": {"id": "att_...", "kind": "image", "status": "pending"}}

# 2b. 上传 fake WebM audio（30s, multipart/form-data）
# MediaRecorder 在 CLI 不可用，用 raw bytes 模拟上传路径
curl -s -X POST http://localhost:8000/api/v1/chat/attachments \
  -H "Origin: http://localhost:8000" \
  -F "file=@/tmp/test.webm;type=audio/webm" \
  -F "agent_id=..." \
  -F "session_id=test-sess" \
  -F "visitor_id=test-vis" \
  -F "duration_ms=30000" | python3 -m json.tool
# → {"attachment": {"id": "att_...", "kind": "audio", "status": "pending"}}

# 2c. 负面测试：超 5MB → 413
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/chat/attachments \
  -H "Origin: http://localhost:8000" \
  -F "file=@/tmp/oversized.png;type=image/png" \
  -F "agent_id=..." -F "session_id=sess" -F "visitor_id=vis"
# → 413

# 2d. 负面测试：text/plain → 415
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/chat/attachments \
  -H "Origin: http://localhost:8000" \
  -F "file=@/tmp/test.txt;type=text/plain" \
  -F "agent_id=..." -F "session_id=sess" -F "visitor_id=vis"
# → 415

# 3. DB sanity: 查 message_attachments 表
docker cp basjoo-backend-dev:/app/data/basjoo.db /tmp/basjoo.db
sqlite3 /tmp/basjoo.db "SELECT id, kind, status, length(transcript), length(ocr_text) FROM message_attachments LIMIT 5;"
# 注意：DB schema 列名是 ocr_text（image description），不是 description
# status=pending → 上传成功但未处理；status=processed → vision/ASR 已跑过

# 4. SSE stream 手动测试（带 attachment_ids）
AGENT_ID=$(docker exec basjoo-backend-dev python3 -c "import sqlite3 as s; c=s.connect('/app/data/basjoo.db'); print(c.execute('SELECT id FROM agents WHERE is_active=1 LIMIT 1').fetchone()[0])")
curl -N -s -X POST http://localhost:8000/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -H "Origin: http://localhost:8000" \
  -d "{\"agent_id\":\"$AGENT_ID\",\"message\":\"Hello\",\"session_id\":\"test\",\"visitor_id\":\"vis\",\"attachment_ids\":[]}" \
  | python3 -c "import sys,json; lines=[l for l in sys.stdin if l.strip()]; print(lines[-1] if lines else '')"
# 期待 event: done → reply 非空

# 5. vi-VN locale 测试
curl -N -s -X POST http://localhost:8000/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -H "Origin: http://localhost:8000" \
  -d "{\"agent_id\":\"$AGENT_ID\",\"message\":\"Xin chào\",\"session_id\":\"vi-test\",\"visitor_id\":\"vi-vis\",\"widget_locale\":\"vi-VN\"}" \
  | grep -o '"content":"[^"]*"' | tail -1
```

> **注意**：`message_attachments` 表的实际 schema 列名是 `ocr_text`（image 描述）而非 `description`；
> `session_id` 列不存在于当前 schema（migration 6144374 移除）；
> `storage_backend` 列为 `local`。
> 详情见 `docs/multimodal-quickref.md`。

---

## 5. 数据与状态

### 5.1 看健康

```bash
docker compose --profile dev ps
```

### 5.2 重置 admin 密码 / role

```bash
docker exec basjoo-backend-dev python3 -c "
import sqlite3, bcrypt
con = sqlite3.connect('/app/data/basjoo.db')
hashed = bcrypt.hashpw(b'new_password_min_8', bcrypt.gensalt()).decode()
con.execute('UPDATE admin_users SET hashed_password=?, role=? WHERE email=?',
            (hashed, 'super_admin', 'me@example.com'))
con.commit()
"
```

### 5.3 看 / 清 KB

```bash
docker exec basjoo-qdrant sh -c "ls /qdrant/storage/collections/"               # collections
docker exec basjoo-qdrant curl -s -X DELETE http://localhost:6333/collections/<name>  # 删(慎)
docker exec basjoo-postgres psql -U basjoo -d basjoo -c \
  "SELECT id, kb_id, filename, status FROM kb_documents ORDER BY created_at DESC LIMIT 10;"
```

### 5.4 全部 reset(到首次启动)

```bash
docker compose --profile dev down -v   # 删:backend-data, redis-data, postgres-data, qdrant-data
docker compose --profile dev up -d
```

`/app/data/.secret_key` / `.encryption_key` 跟着删。`.env` 里 `SECRET_KEY` 优先(无则用 `dev-secret-key`)。

### 5.5 部分 reset(保留 KB 向量)

```bash
docker compose --profile dev stop backend-dev frontend-dev
docker volume rm basjoo_backend-data basjoo_postgres-data
docker compose --profile dev up -d
```

### 5.6 Dify 数据备份 (M11+ P2)

> 三层备份矩阵: basjoo DB (每日) / Dify DB (每日) / dify-data volume (每周)。三层缺一不可 — basjoo 启动后 Dify API key 才能解密 → Dify metadata 查得到 → dify-data 文件可访问。详 `docs/handoffs/M11-P2-DIFY-DATA-BACKUP.md`。

**生产部署** (Ubuntu/Debian, basjoo 部署机器):

```bash
# 1. 一键安装 (复制 3 个脚本到 /opt/basjoo/scripts + 写 /etc/cron.d/basjoo-backups)
cd /opt/basjoo/src   # 假设仓库已 clone 到 /opt/basjoo/src
bash scripts/install-dify-backups.sh

# 2. 验证
tail -f /var/log/basjoo-dify-backup.log
crontab -l   # 应见 3 条 dify 相关 cron (04:00 / 05:00 周日 / 05:30)
```

**手动触发** (调试或恢复演练):

```bash
/opt/basjoo/scripts/backup-dify-db.sh        # 立刻跑 dify-db 备份
/opt/basjoo/scripts/backup-dify-data.sh      # 立刻跑 dify-data 备份
/opt/basjoo/scripts/verify-backups.sh        # smoke test 三层备份
```

**恢复流程** (灾难场景):
- 仅 basjoo DB 损坏 → 用 deploy-pzalo 既有 `basjoo_*.sql.gz` 恢复
- 仅 Dify DB 损坏 → 详见 `M11-P2-DIFY-DATA-BACKUP.md §4.2`
- 仅 dify-data 损坏 → 详见 `M11-P2-DIFY-DATA-BACKUP.md §4.3`
- 三层同时挂 (PG 整机挂) → `§4.4` 顺序: basjoo DB → Dify DB → dify-data → 重启

**3 个脚本来源** (在 repo, 跟代码同版本管理):
- `scripts/backup-dify-db.sh` — 每日 pg_dump of `dify` schema
- `scripts/backup-dify-data.sh` — 每周 tar czf of `dify-data` volume
- `scripts/verify-backups.sh` — daily smoke test + 告警 (返回非零 exit 触发 cron 告警)
- `scripts/install-dify-backups.sh` — 一键安装器 (idempotent, 重复跑安全)

---

## 6. 排错

### 6.1 build 卡在 `failed to fetch oauth token`

国内网络拉 `auth.docker.io:443` 不通。**修**:§3.1 用 DaoCloud 镜像手动 tag,或在 Docker Desktop registry-mirrors 永久加。

### 6.2 `python` / `pip` 报 `command not found`

`python` 指向 WindowsApps 占位。venv 在 `backend/venv_pr1/`,不是默认 `venv/`。**修**:

```bash
cd backend
source venv_pr1/Scripts/activate   # Git Bash / WSL
# 或 .\venv_pr1\Scripts\Activate.ps1 (PowerShell)
python -m pip install -r requirements.txt
python -m pytest tests/test_xxx.py
```

### 6.3 SQLite `unable to open database file`

Windows 路径反斜杠没转 forward slash。**修**:

```python
url = "sqlite:///" + str(path).replace("\\", "/")
```

(`backend/tests/test_mcp_http_e2e.py:55` 有现成例子。)

### 6.4 API key 泄漏

**⚠️ 别把 key 贴 AI 聊天 / Slack / 公共 issue**。AI 服务端会留 history,key 一旦发出等于公开。

**安全做法**:admin UI 填 / `.env` 设(已 gitignore) / SSH 传。

**已泄漏**:① provider 后台 rotate;② `docker exec basjoo-backend-dev python3 -c "import sqlite3; con=sqlite3.connect('/app/data/basjoo.db'); con.execute('UPDATE agents SET api_key=NULL WHERE id=?', ('XXX',)); con.commit()"`;③ 重填新 key。

### 6.5 改代码 backend 不生效

- reload 抽风 → `docker compose restart backend-dev` + `docker logs --tail 30 basjoo-backend-dev`
- 改的不是 dev 挂的卷 → `docker exec basjoo-backend-dev cat /app/api/v1/endpoints.py | head -5` 验证
- 改 `services/__init__.py` 之类 → **必须 `restart`**,reload 不重 import module

### 6.6 端口被占

```bash
netstat -ano | grep ":3001\|:8000"   # Windows,找到 PID
taskkill /F /PID <pid>
```

### 6.7 SQLite `database is locked` / greenlet 警告刷屏

SQLite 单写,测试并发没关连接会锁。**修**:

```bash
rm -rf backend/.pytest_dbs/*.db
cd backend && source venv_pr1/Scripts/activate && pytest tests/test_xxx.py
```

greenlet finalize warning 通常无害(测试结果对),看着糟心可分文件跑,避免一次跑全。

### 6.8 MCP `RuntimeError: Task group is not initialized`

PR9 + PR10 已修(`backend/main.py` 用 `Starlette(Mount(...), lifespan=...)` + 后台 task 跑 `_session_manager.run()`)。**新分支**看到这错,先 `git log -p backend/main.py | grep -A20 "Mount.*mcp"` 确认 fix 是否继承。

---

## 7. 给真实客户网站嵌 widget(部署期)

> 本地 dev 跳过这一节;生产部署 + 嵌入用。

1. **部署 basjoo**:走 `install-deploy.sh`(Ubuntu/Debian 一键,起 prod profile + nginx + HTTPS)。
2. **HTTPS 必须开**:访客的浏览器只允许 HTTPS 页面跑 SDK,HTTP SDK 加载会失败。
3. **widget origin 白名单**:**`super_admin` 在 admin UI 上把客户网站域名加进 agent 的 `allowed_widget_origins`**(JSON 数组)。不加的话 `/api/v1/chat` 会 403(同源策略)。
4. **嵌代码**(放客户网站 `</body>` 前):

   ```html
   <script>
   (function() {
     var s = document.createElement('script');
     s.src = 'https://<basjoo-domain>/sdk.js';
     s.async = true;
     s.defer = true;
     s.setAttribute('data-agent-id', '<AGENT_ID>');
     s.setAttribute('data-api-base', 'https://<basjoo-domain>');
     document.head.appendChild(s);
   })();
   </script>
   ```

   `<AGENT_ID>` 在 admin → agents 列表里复制。

5. **验证**:用客户的域名打开网站,看右下角气泡;F12 console 应该看到 SDK 日志(若开了 verbose)。

---

## 8. 完全拆除

```bash
docker compose --profile dev down -v
docker rmi basjoo-backend-dev basjoo-frontend-dev basjoo-scrapling-service
rm -rf backend/.pytest_dbs/
# 浏览器 localStorage 清:F12 → Application → Local Storage → Clear
```

---

## 9. 引用

- `docker-compose.yml` — service / 端口 / 依赖
- `install-deploy.sh` — 生产部署
- `CLAUDE.md` — 架构 / API / 安全
- `docs/requirements-second-pass.md` — 二开需求
- `docs/operations.md`(本文件)— 怎么跑

---

## 变更记录

- 2026-06-11 v1.0 — 初稿(基于 PR1-PR10 + dev 实际操作)
- 2026-06-12 v1.1 — 收 PR11(vi_VN locale + widget_locale)、PR12(widget language selector);删冗余;默认 admin 改记实际值(`smokepass123`);修 §5.5 自指 bug;§6 排错去重;加 §7 widget 嵌入指引
- 2026-06-14 v1.2 — PG 宿主端口 5432 → 5433(避本机 PG 服务冲突,backend 容器内仍 5432 走 docker network),`docker-compose.yml:40` 同步
- 2026-06-14 v1.3 — Frontend 宿主端口 3000 → 3001(避本机网易云 API 冲突,容器内仍 3000),`docker-compose.yml:256` 同步;同步 §0 / §1 / §4.5 / §6.6 端口引用
- 2026-06-16 v1.4 — M11+ P2 ops Sprint 落地: 加 §5.6 Dify 数据备份 (3 脚本 + 一键安装器),三层备份矩阵 (basjoo DB / Dify DB / dify-data) 跨 04:00 / 05:00 周日 cron 错峰;详 `docs/handoffs/M11-P2-DIFY-DATA-BACKUP.md`
