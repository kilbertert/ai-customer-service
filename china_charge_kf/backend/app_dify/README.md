# Dify Backend (app_dify/)

基于 **Dify Workflow** 的 FastAPI 后端,与原 `app/`(Coze 版)**并列**部署,共享前端协议 `/api/chat`。

## 为什么是 Workflow 不是 Chatflow

通过 `GET /v1/info` 验过,目标 App `China_charge_seriver` 的 `mode = "workflow"`,因此使用 `POST /v1/workflows/run` 接口(不是 `/v1/chat-messages`)。

## 与 Coze 后端的关键差异

| 维度 | Coze (`app/`) | Dify (`app_dify/`) |
|---|---|---|
| 文件上传 | `POST /v1/files/upload` 返回 `data.id` (file_id) | `POST /v1/files/upload` 返回 `id` (upload_file_id,UUID) |
| 文件上传要求 | 仅需 token | **需 multipart + `user` 字段** |
| Workflow 入参 | `parameters: {...}` | `inputs: {...}` + 顶层 `user` |
| 文件型 input 格式 | `{"file_id": "..."}` 字符串 | `[{type, transfer_method: "local_file", upload_file_id}]` 数组 |
| 响应文本路径 | 任意 key,需递归搜索 | `data.outputs.<var_name>` 清晰路径 |
| 失败判定 | HTTP 4xx | HTTP 200 但 `data.status = "failed"` |

## 启动

### 1. 准备配置

```bash
cd backend
cp .env.dify .env.dify.local
# 填入 DIFY_API_KEY (app-xxx)
```

### 2. 本地启动(开发)

```bash
cd backend
uvicorn app_dify.main:app --host 0.0.0.0 --port 8012 --reload
```

健康检查:
```bash
curl http://localhost:8012/api/health
# {"ok":true,"backend":"dify","api_base":"https://api.dify.ai/v1","end_user":"h5-frontend-user"}
```

### 3. Docker 启动

```bash
docker compose up --build backend-dify
```

端口 `8012` 暴露到宿主。

## 前端切换

前端代码 **零改动**。只需在 build 时指定 `VITE_API_BASE`:

```bash
cd frontend
VITE_API_BASE=http://localhost:8012 npm run build
```

(开发模式同样: `VITE_API_BASE=http://localhost:8012 npm run dev`)

## 调试 / 排障

| 现象 | 原因 |
|---|---|
| `app_unavailable` | Dify App 配置未发布或工作流为空。回 Dify Studio 点"发布"。 |
| `not_workflow_app` | 你调了 `/chat-messages` 但 App 是 workflow 类型(本项目不会遇到)。 |
| `provider_not_initialize` | Dify 后台没配模型 provider 凭据。 |
| `400 invalid_param` | 多半是 workflow input 变量名对不上,改 `.env` 里 `DIFY_INPUT_*`。 |
| 响应里有 `[DifyError:workflow]` 前缀 | 上游工作流跑失败,看 `raw` 字段的 `data.error`。 |
| 文本全是 JSON | `outputs` 里没拿到字符串,检查 Dify 端"结束节点"的输出变量名,改 `DIFY_OUTPUT_TEXT`。 |

## 项目结构

```
app_dify/
    __init__.py
    config.py           # Settings: api_base / api_key / end_user / 变量名映射
    dify_client.py      # DifyClient: upload_file + run_workflow + file_ref helper
    schemas.py          # ChatResponse (与 app/schemas.py 同形)
    response_parser.py  # extract_assistant_text (Dify 路径优先 + 深度回退)
    main.py             # FastAPI 入口,端点 /api/chat
```

## 切换回 Coze

只需把 `VITE_API_BASE` 改回 `http://localhost:8011`,无需停 Dify 服务,两套可并存。
