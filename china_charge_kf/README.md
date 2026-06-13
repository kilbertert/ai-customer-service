# H5 智能客服（前端 + FastAPI 后端）

> **2026-06-13 备注**：本目录原为独立 git 仓库，已于 commit `5981f65` 并入主仓 `ai-customer-service/` 作为子目录。代码与历史内容保持不变，后续工作统一在主仓进行。

多模态净水器问答助手前端 + 后端。后端并列两套实现，**互不依赖、按需启停**：

- **`backend/app/`**（Coze 版，端口 8011）—— 原实现
- **`backend/app_dify/`**（Dify 版，端口 8012）—— 当前主推

前端通过 Vite dev server 代理到任一后端，**代码零改动**。

---

## 目录结构

```
china_charge_kf/
├── frontend/                     # Vite + React + TS
│   ├── .env                      # VITE_BACKEND_PORT=8012 等（本地配置）
│   ├── .env.example
│   └── vite.config.ts            # /api 代理目标由 VITE_BACKEND_PORT 决定
│
├── backend/
│   ├── app/                      # Coze 后端，端口 8011
│   ├── app_dify/                 # Dify 后端，端口 8012
│   │   ├── main.py               # FastAPI 入口
│   │   ├── dify_client.py        # Dify HTTP 客户端
│   │   ├── response_parser.py    # 剥 <think>...</think> 等模型思考块
│   │   ├── config.py             # Pydantic Settings
│   │   └── README.md             # Dify 后端单独说明
│   ├── .env                      # Coze 后端配置（本地，不入仓）
│   ├── .env.dify                 # Dify 后端配置模板
│   └── .env.example
│
└── Workflow-China_charge_seriver-draft-9380/
    └── workflow/
        ├── China_charge_seriver-draft.yaml   # Coze 原始导出
        └── workflow.yml                       # Dify 工作流 DSL（导入 Dify Studio 用）
```

---

## 双后端选择

| 维度 | Coze（`app/`） | Dify（`app_dify/`） |
|---|---|---|
| 端口 | 8011 | 8012 |
| 工作流 | Coze 平台托管 | 自托管 / Dify Cloud，Dify Studio 编辑 |
| DSL | Coze 私有格式 | Dify 标准 YAML（`workflow.yml`） |
| 文件输入格式 | `{"file_id": "..."}` | `[{type, transfer_method, upload_file_id}]` 数组 |
| Workflow 响应路径 | 递归搜索 | `data.outputs.<var>` |
| 失败判定 | HTTP 4xx | HTTP 200 + `data.status="failed"` |
| 思考块泄漏 | 否 | 是（已由 `response_parser.py` 兜底剥除） |

**Dify 是当前主推**。Coze 后端保留作为对比/回退，部署时**二选一**即可。

---

## Dify 后端（推荐）

### 1. 导入工作流

1. 用 Dify Studio 创建一个空白 Workflow App
2. 通过 "DSL 导入" 上传 `Workflow-China_charge_seriver-draft-9380/workflow/workflow.yml`
3. 在 Dify Studio 里手动替换以下占位符：
   - 节点 1008 的 ASR URL → 你的语音识别服务
   - 节点 1006/1009/1012 的 `REPLACE_WITH_YOUR_DIFY_DATASET_ID` → 你创建的知识库 ID
4. 配置模型供应商（`volcengine_maas` / `doubao-seed-2-0-lite-260428`）
5. **点"发布"**

> 详细节点拓扑见 `Workflow-China_charge_seriver-draft-9380/README.md`（如未生成可参照 `workflow.yml` 注释）。

### 2. 配置环境变量

```bash
cd backend
cp .env.dify .env.dify.local   # 或直接用 .env
```

编辑 `backend/.env.dify`（或 `.env`）：

```env
# 必填
DIFY_API_KEY=app-xxxxxxxxxxxxxxxxxxxxxxxx

# 可选（默认值已可工作）
DIFY_API_BASE=https://api.dify.ai/v1
DIFY_END_USER=h5-frontend-user
DIFY_INPUT_TEXT=input_text
DIFY_INPUT_IMAGE=input_img_id
DIFY_INPUT_AUDIO=input_audio_id
DIFY_INPUT_LANGUAGE=language
DIFY_OUTPUT_TEXT=output
APP_CORS_ORIGINS=http://localhost:5173,http://localhost:8082
PORT=8012
```

### 3. 启动

**本地（开发）：**

```bash
cd backend
uvicorn app_dify.main:app --host 0.0.0.0 --port 8012 --reload
```

健康检查：
```bash
curl http://localhost:8012/api/health
# {"ok":true,"backend":"dify","api_base":"...","end_user":"h5-frontend-user"}
```

**Docker Compose：**

```bash
docker compose up --build backend-dify
```

端口 8012 暴露到宿主。

---

## Coze 后端（兼容）

```bash
cd backend
# 编辑 .env：填好 COZE_API_TOKEN 和 COZE_WORKFLOW_ID

uvicorn app.main:app --host 0.0.0.0 --port 8011 --reload
# 或
docker compose up --build backend
```

健康检查：`curl http://localhost:8011/api/health`

---

## 前端开发

### 切换后端：用 `VITE_BACKEND_PORT`，不要用 `VITE_API_BASE`

`VITE_API_BASE=http://localhost:8012` 这种写法在**局域网访问时会断**（浏览器会连到对方机器的 localhost），所以统一改用 **Vite 代理方案**：

- `frontend/.env` 里设置 `VITE_API_BASE=`（留空）→ 浏览器发同源请求 `/api/chat`
- `VITE_BACKEND_PORT=8012` → Vite 代理把 `/api/*` 转到 `http://127.0.0.1:8012`

### 开发模式（推荐）

```bash
cd frontend
# 默认 VITE_BACKEND_PORT=8011 走 Coze；用 Dify 就改 .env
npm run dev
```

终端会显示：
```
[vite] /api proxy → http://127.0.0.1:8012  (VITE_BACKEND_PORT=8012)
  VITE v7.x ready in XXXX ms
  ➜  Network: http://100.115.126.49:5173/
```

局域网设备访问 `http://<server-ip>:5173/` 即可。如果连不上，**Windows 防火墙**要放行 5173（控制面板 → 防火墙 → 入站规则 → 放行 TCP 5173）。

### 切换后端

只改 `frontend/.env` 一行，重启 `npm run dev`：

```env
VITE_BACKEND_PORT=8012   # 切 Dify
VITE_BACKEND_PORT=8011   # 切 Coze
```

> ⚠️ 改 `.env` 必须重启 Vite，env 变量在启动时读，HMR 不会重新加载。

### 生产构建

```bash
cd frontend
npm run build           # 产物在 frontend/dist/
npm run preview         # 本地预览，默认端口 4173
```

部署时由 nginx 托管 `dist/`，并把 `/api/*` 反代到 8011 或 8012。

---

## 完整本地双后端调试拓扑

3 个终端，互不干扰：

```bash
# T1 — Dify 后端（主）
cd backend && uvicorn app_dify.main:app --port 8012 --reload

# T2 — Coze 后端（可选）
cd backend && uvicorn app.main:app --port 8011 --reload

# T3 — 前端
cd frontend && npm run dev     # 走 .env 里 VITE_BACKEND_PORT 决定的后端
```

切后端：T1/T2 不动，只改 T3 的 `.env` 然后 Ctrl+C 重启。

---

## 常见踩坑

| 症状 | 原因 | 解决 |
|---|---|---|
| 改了 `.env` 前端没生效 | env 在启动时读，HMR 不重载 | Ctrl+C 重启 `npm run dev` |
| 局域网访问 `http://<ip>:5173/` 报 `Failed to fetch` | Windows 防火墙拦截 5173 | 放行入站 TCP 5173 |
| 终端 proxy 目标端口不对 | `VITE_BACKEND_PORT` 未读到 | 检查 `.env` 没被注释、没多余空格 |
| 响应里出现 `<think>...</think>` 块 | doubao-seed-2.0-lite 启用了 reasoning | 已由 `response_parser.py` 兜底；也可在 Dify 模型参数里关 |
| 响应里是整段 JSON | Dify 结束节点输出变量名不匹配 | 改 `.env` 里 `DIFY_OUTPUT_TEXT` |
| `[DifyError:workflow]` 前缀 | 上游工作流跑失败 | 看响应 `raw.data.error` |

---

## 排障命令速查

```bash
# 直连后端
curl http://127.0.0.1:8012/api/health

# 走 Vite 代理（确认代理通）
curl http://127.0.0.1:5173/api/health

# 浏览器里看实际请求 URL：F12 → Network → 选 XHR/fetch → 点 chat
```
