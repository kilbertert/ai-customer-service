# Backend (FastAPI)

## 1) 准备环境变量

复制并修改：

- `.env.example` → `.env`

至少需要：

- `COZE_API_TOKEN`
- `COZE_WORKFLOW_ID`

并确保你的工作流入参名与：

- `COZE_PARAM_TEXT`（默认 `text`）
- `COZE_PARAM_IMAGE_ID`（默认 `image_id`）

一致。

## 2) 安装依赖

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 3) 启动

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8011 --reload
```

健康检查：

- `GET http://localhost:8011/api/health`

