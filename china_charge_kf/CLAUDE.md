# CLAUDE.md

> **2026-06-13 备注**：本目录原为独立 git 仓库，已于 commit `5981f65` 并入主仓 `ai-customer-service/` 作为子目录。本文件同时也是子目录的项目说明，两份 CLAUDE.md 各自维护自身内容（根 CLAUDE.md 描述 basjoo fork 全局，本文件描述 china_charge_kf/ 子项目）。

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

H5 智能客服 — a browser-based customer service chat application with text, image, and voice input. The backend has two parallel implementations, **independent and selectively runnable**:

- `backend/app/` — Coze prototype (port 8011, original)
- `backend/app_dify/` — Dify Workflow prototype (port 8012, current focus, M2-extended)

**Stack**: React + TypeScript + Vite (frontend) | FastAPI (backend, two impls) | Nginx (proxy) | Docker + docker-compose (deployment)

### M2 状态 (2026-06-13)

- `backend/app_dify/dify_client.py` 已扩展：`run_workflow_blocking` / `run_workflow_stream` / `DifyAuthError` / `DifyBadRequestError` / `DifyUpstreamError` / `extract_output_text`
- 62 tests, 97% line coverage at `backend/tests/test_dify_client.py`
- 契约文档：`docs/api-contract-dify.md` §4.2.1 (PR9 U1–U10) + §4.2 (PR10 file-list)
- 错误映射：`docs/sse-event-mapping.md` §6.5.1/§6.5.2 (PR8)

### M9 状态 (2026-06-13) — stream-level `<think>` 剥离器

- `frontend/src/services/difyStream.ts` 新增 `createThinkStripper()`:跨 chunk 缓冲 + drain() state machine,把流式 `<think>` 推理挡在 `message_delta` 之外
- 11 个新 vitest(`difyStream.test.ts` 53 总数,全套 69) + M9.4 e2e spec `specs/07-think-streaming.spec.ts` 永久守门(`page.on('console')` 抓 `[M9-HARD-GATE]` fires)
- 退役:`App.tsx` 原 dev-only `[M9-HARD-GATE]` useEffect(M9-PROMPT §11 选项 b,e2e spec 接管)
- 验收:CONDITIONAL PASS(5 轮 T7 `@real-dify` 硬门 regression 待用户本机实跑,Σ fires 必须 = 0 升级无条件 PASS)
- 报告:`frontend/e2e/M9-REPORT.md`
- 后续:`M8-CLEANUP-REPORT.md` §7 候选 #2(`_dig_first_text` 整合)未做,留 M9.x / M10+

### M10 状态 (2026-06-15) — 5 Gap 修复 + basjoo 仓物理合并

- 任务书:`china_charge_kf/M10-PROMPT.md`(M10 全部 SSoT,untracked — 待 M14 决定是否移到 basjoo)
- 9 个 sub-PR 落地(8 commit + 1 amend,基线 `19cfda2` → HEAD `f2a1eb0`):
  - PR1 G2 Tenant↔Workspace 1:1(`0aa8792`)+ PR2-1/2-2/2-3 G3 schema/Fernet(`6431b97`/`f33cc2d`)+ PR2-4 G5 #5/#6(`e178035`)
  - PR3a G4 backend 物理搬运(`475246c`)+ PR3b G4 frontend 物理搬运(`fc7bc4a`)+ PR3 frozen 标记(`8065f62`)
  - PR4a G1 dual-layer end_user 编码(`c3b14be`)+ PR4b streaming think strip(`828cd7e`)+ PR4c E2E + report amend(`f2a1eb0`)
- 本目录已 **FROZEN-DEPRECATED**(详见 `china_charge_kf/M10-FROZEN-README.md`),Dify 协议层代码全在 basjoo 仓
- 验收: **CONDITIONAL PASS**(165/165 backend pytest + 180/180 frontend vitest + 1/1 basjoo DifyClient 真 Dify round-trip;5/5 china_charge_kf H5 widget M9 baseline 维持;缺口 = basjoo `/api/v1/chat/stream` 真 Dify 流式 E2E 待本机/CI 补跑,清单见 `china_charge_kf/M10-REPORT.md` §8)
- 报告:`china_charge_kf/M10-REPORT.md`(168 行,含基线阻断分析 + 7 步本机补跑清单)
- M10+ follow-up: ① basjoo H5 widget → chat_stream → DifyProvider → 真 Dify 3 轮 E2E ② admin UI 配 workflow_id(production DB 0 rows) ③ frontend `useDifyStream:true` 触发 ④ `china_charge_kf/M10-PROMPT.md` 移到 basjoo 仓决策

## Dev Commands

### Frontend
```bash
cd frontend
npm run dev          # Vite dev server with HMR
npm run build         # TypeScript build + Vite production bundle
npm run lint          # ESLint check
```

### Backend
```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8011 --reload   # local dev server
```

### Docker (production-like)
```bash
docker compose up --build   # starts frontend + backend + nginx proxy
```
Access at http://localhost:8082

## Architecture

```
Browser (H5)
  └── Nginx (port 8082) ──── proxied ──── FastAPI backend (port 8011)
                                                └── Coze API (api.coze.cn)
```

- **Frontend** (`frontend/src/App.tsx`): single-page chat UI; handles text/voice/image input; POSTs multipart/form-data to `/api/chat`; supports zh/en/vi i18n via a `translations` dict
- **Backend** (`backend/app/main.py`): FastAPI app; `POST /api/chat` receives `text`, optional `image`, optional `audio`; uploads files to Coze then runs a Coze workflow; returns `ChatResponse` with `assistant_text`, `image_id`, `audio_id`
- **Coze client** (`backend/app/coze_client.py`): wraps Coze REST API — `upload_file()` → file_id, `run_workflow()` → raw JSON response
- **Config** (`backend/app/config.py`): Pydantic `Settings` from `.env`; all Coze param names are configurable via env vars (`COZE_PARAM_TEXT`, `COZE_PARAM_IMAGE_ID`, etc.)
- **Response parsing** (`backend/app/main.py`, `_extract_assistant_text`): Coze workflow responses have variable structure; `_dig_first_text` recursively searches for the first meaningful text string across many possible key names

## Environment Variables

### Backend (`backend/.env`)
| Variable | Description | Default |
|---|---|---|
| `COZE_API_TOKEN` | Coze API token | **required** |
| `COZE_WORKFLOW_ID` | Target workflow ID | **required** |
| `COZE_API_BASE` | Coze API endpoint | `https://api.coze.cn` |
| `COZE_PARAM_TEXT` | Workflow text input param name | `input_text` |
| `COZE_PARAM_IMAGE_ID` | Workflow image param name | `input_img_id` |
| `COZE_PARAM_AUDIO_ID` | Workflow audio param name | `input_audio_id` |
| `COZE_PARAM_LANGUAGE` | Workflow language param name | `language` |
| `APP_CORS_ORIGINS` | CORS allowed origins | `http://localhost:5173` |

### Frontend (`frontend/.env`)
| Variable | Description | Default |
|---|---|---|
| `VITE_API_BASE` | Backend API base URL | `https://zcf.h5.qumall.qushiyun.com` |

## Key Implementation Notes

- Audio is recorded as WebM/MP4 via `MediaRecorder`, converted to WAV before upload because Coze prefers WAV format
- The backend's `_dig_first_text` function handles Coze's non-uniform response format by recursively searching keys like `output`, `answer`, `result`, `text`, `message`, `content`
- The frontend defaults `apiBase` to a production URL (`https://zcf.h5.qumall.qushiyun.com`); override with `VITE_API_BASE` for local development