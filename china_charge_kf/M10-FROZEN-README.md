# china_charge_kf/ — FROZEN-DEPRECATED 2026-06-15

> **本目录的 Dify 协议层代码已物理合并到 basjoo 仓**,作为 reference 镜像保留
> 只读。新功能、bug 修复、refactor 请在 basjoo 仓提交,不要再往本目录加代码。
> 整体废弃等 M14 决定。

## 合并历史

| Commit | PR | 内容 |
|--------|-----|------|
| `475246c` | M10 PR3a | backend 9 源文件 + 3 test 文件 → basjoo `backend/services/dify/` + `backend/tests/` |
| `fc7bc4a` | M10 PR3b | frontend 2 文件 → basjoo `frontend-nextjs/src/services/difyStream.ts` + `__tests__/difyStream.test.ts` |
| (本 README) | M10 PR3 frozen | FROZEN-DEPRECATED 标记 + 转移说明 |

## 路径对照表 (新改动请到 basjoo 仓)

### Backend (9 源 + 3 test)

| china_charge_kf (frozen) | basjoo (active) |
|--------------------------|------------------|
| `backend/app_dify/__init__.py` | `backend/services/dify/__init__.py` |
| `backend/app_dify/config.py` | `backend/services/dify/config.py` |
| `backend/app_dify/dify_client.py` | `backend/services/dify/dify_client.py` |
| `backend/app_dify/main.py` | `backend/services/dify/main.py` |
| `backend/app_dify/response_parser.py` | `backend/services/dify/response_parser.py` |
| `backend/app_dify/schemas.py` | `backend/schemas/dify.py` (待 PR4 决定) |
| `backend/app_dify/sse_bytes.py` | `backend/services/dify/sse_bytes.py` |
| `backend/app_dify/sse_proxy_layer.py` | `backend/services/dify/sse_proxy_layer.py` |
| `backend/tests/test_dify_client.py` | `backend/tests/test_dify_client.py` |
| `backend/tests/test_sse_bytes.py` | `backend/tests/test_sse_bytes.py` |
| `backend/tests/test_sse_proxy_layer.py` | `backend/tests/test_sse_proxy_layer.py` |

### Frontend (2 文件)

| china_charge_kf (frozen) | basjoo (active) |
|--------------------------|------------------|
| `frontend/src/services/difyStream.ts` | `frontend-nextjs/src/services/difyStream.ts` |
| `frontend/src/services/__tests__/difyStream.test.ts` | `frontend-nextjs/src/services/__tests__/difyStream.test.ts` |

## 不搬 / 留 china_charge_kf

- `frontend/src/App.tsx` (basjoo 架构不同,只搬 services)
- `frontend/src/assets/` (basjoo 已有自己的 assets)
- `frontend/src/services/fileUpload.ts` + `__tests__/fileUpload.test.ts` (basjoo widget/ 已有等价实现)
- `frontend/src/main.tsx` / `App.css` / `index.css` (basjoo Next.js 架构)
- `backend/app/` (Coze prototype,完全独立于 Dify,保留作 reference)
- `backend/scripts/` (m0_5_probe.py / m1_5_probe.py 探针脚本,保留作历史记录)
- `Workflow-China_charge_seriver-draft-9380/` (Dify workflow 草稿 yml 库,非代码)

## 本目录仍可用的 reference 资产

- `M10-PROMPT.md` — M10 5 Gap 修复任务书 SSoT
- `M9-PROMPT.md` / `M9-REPORT.md` — M9 think-stripper 报告
- `M8-CLEANUP-REPORT.md` — M8 清理报告
- `CLAUDE.md` — china_charge_kf 子项目说明
- `docker-compose.yml` — Dify prototype 独立部署参考
- `dify_workflow_api说明文档.md` — Dify API 中文参考

## 何时删除本目录

按 M10-PROMPT §8 #4: "china_charge_kf 整体废弃 → 仅冻结标记,真正废弃等 M14"
M14 触发条件待 M11+ 决策 (届时 basjoo 仓 Dify 集成层稳定后再决定)。

## 紧急回滚

如需回滚 PR3 合并:
```bash
git revert 475246c fc7bc4a
```
会撤销 basjoo 仓 12 个新文件 + .gitignore 调整 + 1 个 M10-PROMPT 不存在的 __init__.py 标记。
china_charge_kf 侧 FROZEN 标记需手动从本目录 3 个文件移除。
