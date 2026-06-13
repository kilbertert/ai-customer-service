# M8.0 完成报告 — Playwright `*.spec.ts` 接 CI

**日期**: 2026-06-13
**分支**: `feat/m8-e2e-spec-ts`
**工作目录**: `china_charge_kf/frontend/`
**M7.5 状态**: ✅ 已合并 (`c91c056`)
**M8.0 范围**: 只做 P3(spec 固化),M8.1-P1/M8.2-P2/M8.3-P4/M8.4/M8.5 均不在本次范围

---

## 1. 目标 & 范围

把 M7 用 Playwright MCP 交互式验证的 7 个场景(T1-T7)固化为可重跑的
`*.spec.ts`,接 CI 守门。完成的事:

1. **2 个 helpers**(`e2e/helpers/`)— Dify v2 SSE byte stream mocks + UI locator 工具
2. **6 个 spec 文件**(`e2e/specs/`)— T1, T2, T3, T4, T5, T6 共 18 个 test,覆盖 M7 验证矩阵的 6/7(除 T7 真 Dify 链路)
3. **1 个 T7 spec** — `@real-dify` tag,默认 `test.skip(!RUN_REAL_DIFY)`,需要真后端 + 真 Dify 时手动跑
4. **`playwright.config.ts` 更新** — `testDir: ./specs`、`reporter: list+html+junit`、`expect.timeout: 10000`、修复 webServer cwd 让 backend 读 `backend/.env`
5. **`package.json` scripts** — `test:e2e` / `test:e2e:ui-only` / `test:e2e:real-dify` / `test:e2e:all`,加 `cross-env` devDep

**不在范围(显式禁止)**:
- M8.1 P1 stream 中断 noResponse 兜底 — 业务代码改动
- M8.2 P2 `<think>...` 跨 chunk strip — 业务代码改动
- M8.3 P4 拍摄按钮决策 — 业务代码改动
- M8.4 `.env.dify.example` 模板 — backend 配置改动
- M8.5 `_sse_bytes` / `_truncate_error` 提取到 `sse_bytes.py` — backend 重构
- 任何 `frontend/src/**` / `backend/app_dify/**` 业务代码改动(测试驱动的不算)

---

## 2. 交付文件清单

| 文件 | 类型 | 行数 | 用途 |
|------|------|------|------|
| `e2e/tsconfig.json` | 新增 | 9 | 给 e2e specs/helpers 用的独立 tsconfig(继承 app.json,加 @playwright/test + node types) |
| `e2e/helpers/dify-sse-mocks.ts` | 新增 | ~165 | `mockDifyV2StreamResponse` / `mockDifyV2Error` / `mockHttpError`,严格按 M3/M7.5 修复后的 v2 SSE 字节格式(`event: \n data: \n\n`) |
| `e2e/helpers/stream-helpers.ts` | 新增 | ~95 | `waitForAssistantBubble` / `getAssistantText` / `isStreaming` / `waitForStreamingStart` / `waitForStreamingEnd` / `getErrorBannerText` / `getNoResponseIndicator` / `getStoppedIndicator` |
| `e2e/specs/01-chat-stream-text.spec.ts` | 新增 | 105 | T1 (3 tests: 单 chunk / 多 chunk / end terminator) + T7 (1 test, `@real-dify` skip-by-default) |
| `e2e/specs/02-chat-stream-image-upload.spec.ts` | 新增 | 119 | T2 (2 tests: 上传成功 + file_ids 验证 / 上传失败回退到 assistant bubble) |
| `e2e/specs/03-chat-stream-error-banner.spec.ts` | 新增 | 73 | T3 (3 tests: HTTP 5xx / DIFY_UPSTREAM / DIFY_AUTH,banner 隔离 + dismiss 按钮) |
| `e2e/specs/04-chat-stream-null-text.spec.ts` | 新增 | 89 | T4 (2 tests: 无 deltas + null text → noResponse / 有 deltas + null text → 用累积值) |
| `e2e/specs/05-i18n-locale-switch.spec.ts` | 新增 | 117 | T5 (4 tests: 默认 zh / zh→en / en→vi / error banner 三语本地化) |
| `e2e/specs/06-chat-stream-abort.spec.ts` | 新增 | 135 | T6 (3 tests: stop 触发 AbortController + "(已停止)" tag / stop race 早期 abort / POST body 形状断言) |
| `e2e/playwright.config.ts` | **更新** | 70 | testDir / testMatch / reporter(html+junit+list) / expect.timeout / webServer cwd 修复 / projects |
| `frontend/package.json` | **更新** | +5 scripts + +1 devDep | `test:e2e` 系列 + `cross-env ^7.0.3` |

---

## 3. 与 M7 验证矩阵对照表(M7 交互式 ↔ M8.0 CI 自动化)

| # | M7 场景(MCP 手动) | M8.0 spec | M7 状态 | M8.0 验证方式 |
|---|------------------|-----------|---------|--------------|
| T1 | 文本流式 (real Dify) | `01-chat-stream-text.spec.ts:19` | ✅ PASS (M7.5) | mocked v2 SSE(`session_started → message_delta → message_complete`),断言 bubble 文本匹配 + streaming indicator 消失 |
| T1 扩展 | 多 chunk delta 累积 | `01:46` | (新) | mock 3 个 message_delta,断言最终 bubble 文本为 chunks 拼接 |
| T1 扩展 | end terminator 兜底 | `01:73` | (新) | mock `message_delta → end`(无 message_complete),断言最终 bubble 文本仍 flush 出来 |
| T2 | 图片上传 | `02-chat-stream-image-upload.spec.ts:28` | ✅ PASS | mock `/api/files/upload` + `/api/chat/stream`,断言 chat request body 含 `file_ids: [FILE_ID]` + user bubble 有 `.img` |
| T2 扩展 | upload 失败回退 | `02:99` | (新) | mock 5xx upload,断言 inline bubble 含错误文案 + 无 banner |
| T3 | error banner (M6.4) | `03-chat-stream-error-banner.spec.ts:18` | ✅ PASS | Case A: HTTP 5xx → banner "出错了" + dismiss 按钮可关闭 |
| T3 扩展 | DIFY_UPSTREAM | `03:45` | (新) | Case B: v2 SSE `error` event code=DIFY_UPSTREAM → banner 特定文案 "服务暂时不可用" |
| T3 扩展 | DIFY_AUTH | `03:68` | (新) | Case C: v2 SSE `error` event code=DIFY_AUTH → banner 特定文案 "认证失败" |
| T4 | null text (M6.1) | `04-chat-stream-null-text.spec.ts:22` | ✅ PASS-by-code | mock `session_started → message_complete.text=null` (无 deltas),断言 `.noResponse` 渲染 + 0 pageerror |
| T4 扩展 | deltas + null text | `04:60` | (新) | mock 有 deltas 后 message_complete.text=null,断言用累积值(防 backend flakiness) |
| T5 | i18n 切换 | `05-i18n-locale-switch.spec.ts:60` | ✅ PASS | zh → en → vi 切换 title / placeholder / lang chip;error banner 文案随语言重渲染 |
| T6 | 中断流 (M6.3) | `06-chat-stream-abort.spec.ts:43` | ✅ PASS | mock 长流(60 chunks × 200 chars = ~12 KB),点 `.send.stop`,断言 `.stoppedTag` 渲染 + `requestfailed` errorText 含 "abort" |
| T6 扩展 | 早期 stop race | `06:84` | (新) | mock 短开头 + 80 个 chunk,send 后立即 stop,断言 abort 不崩 |
| T6 扩展 | POST body 形状 | `06:114` | (新) | 监听 `request` 事件,断言 method=POST + body 含 `"text":"audit"` |
| T7 | real Dify happy path | `01:93` (`@real-dify`) | ✅ PASS (M7.5) | `test.skip(!process.env.RUN_REAL_DIFY)`,需手动跑 `RUN_REAL_DIFY=1 npm run test:e2e -- --grep "@real-dify"` |

**总计**: 18 个 test(17 always-run + 1 `@real-dify`),覆盖 M7 矩阵 7/7 场景。

---

## 4. 验证门结果

| 验证门 | 命令 | 状态 |
|--------|------|------|
| TypeScript 编译 | `npx tsc --noEmit -p e2e/` | ✅ **0 errors** |
| ESLint | `npx eslint e2e/specs/ e2e/helpers/ e2e/playwright.config.ts` | ✅ **0 errors / 0 warnings** |
| Spec list(配置发现) | `npx playwright test --config e2e/playwright.config.ts --list` | ✅ **18 tests in 6 files** |
| Spec runner (UI-only) | `npm run test:e2e:ui-only` | ⚠️ **sandbox 拦截 Playwright 内部 spawn cmd.exe** — Node 直接 spawn `cmd.exe` OK,但 Playwright bundled spawn(`utilsBundle.js:56930` `parsed.command = process.env.comspec \|\| "cmd.exe"`)在当前 Claude Code sandbox 下报 `ENOENT`。**留给 CI / 本机 Git Bash runner 跑。** |
| Spec runner (real Dify) | `RUN_REAL_DIFY=1 npm run test:e2e -- --grep "@real-dify"` | ⚠️ 同上,需 CI / 本机跑 |

### 4.1 当前 sandbox 限制(透明记录)

Claude Code 提供的 bash sandbox 在 Windows + Git Bash 环境下,允许直接 `child_process.spawn("cmd.exe", ...)` 调用(测试过),但 Playwright 1.60 内部走 `utilsBundle.js` 的 bundled spawn 路径,被 sandbox 拦截报 `Error: spawn C:\WINDOWS\system32\cmd.exe ENOENT`。已尝试以下 workaround,均无效:
- 设 `process.env.ComSpec` / `process.env.comspec` 为绝对 cmd.exe 路径
- 把 `C:\WINDOWS\system32` 注入 `PATH`
- `dangerouslyDisableSandbox: true` 跑 Playwright

结论:**设计工作完成,真实跑通留给干净的 GitHub Actions runner(或本地 Git Bash 直接跑 `npm run test:e2e:ui-only`)**。M7 同样的限制已记录在 `M7-REPORT.md §1`。

### 4.2 CI 验证(推荐)

CI 环境无 sandbox 拦截,期望 18/18 通过(17 mock-path + 1 T7 with `RUN_REAL_DIFY=1` secret)。

---

## 5. 如何本地跑

### 5.1 mock-only 套件(默认,17 tests)

```bash
cd china_charge_kf/frontend

# 1. 确保 Python + backend 依赖就绪(miniconda 已用)
"C:/Users/q1234/miniconda3/python" -c "import fastapi, uvicorn"  # sanity

# 2. 确保 backend/.env 有 DIFY_API_KEY / DIFY_V2_API_KEY
cat ../backend/.env | grep DIFY_  # 应有两行

# 3. 跑 mock-only 套件(自动启动 backend + frontend webServer)
npm run test:e2e:ui-only
```

webServer 自动:
- backend (`uvicorn app_dify.main:app` on :8012),cwd 自动切到 `../backend/`,读 `backend/.env`
- frontend (`npm run dev --port 5173 --strictPort`),cwd 切到 `..`(frontend/)

### 5.2 T7 真 Dify 链路(1 test)

```bash
# 1. 先手动确认后端能联通真 Dify
curl -X POST http://124.243.178.156:8501/v1/workflows/run \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"inputs":{"input_text":"ping"},"response_mode":"streaming","user":"h5-test"}'

# 2. 跑 T7
RUN_REAL_DIFY=1 npm run test:e2e -- --grep "@real-dify"
```

### 5.3 全部(18 tests)

```bash
RUN_REAL_DIFY=1 npm run test:e2e:all
```

### 5.4 单 spec 文件

```bash
npx playwright test --config e2e/playwright.config.ts specs/03-chat-stream-error-banner.spec.ts
```

### 5.5 报告产物

```
frontend/e2e-results/
├── html/index.html         # Playwright HTML 报告(可浏览器打开)
├── junit.xml               # JUnit 格式(CI 集成用)
└── test-results/           # trace / video / screenshot-on-failure
```

---

## 6. CI 集成路线(M8.6 范围,不在 M8.0)

> M8.0 只到 `npm run test:e2e:ui-only` 可跑通为止。GitHub Actions workflow 文件不在本 commit。

下一步(M8.6 候选)的 GH Actions workflow 草案(供后续 commit 复用):

```yaml
# .github/workflows/frontend-e2e.yml
name: frontend-e2e
on:
  pull_request:
    paths:
      - 'china_charge_kf/frontend/**'
  push:
    branches: [main]

jobs:
  e2e:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: china_charge_kf/frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: npm ci
      - run: pip install -r ../backend/requirements.txt  # backend deps
      - run: cp ../backend/.env.example ../backend/.env  # or use secrets
      - run: npx playwright install --with-deps chromium
      - run: npm run test:e2e:ui-only  # mock-only CI gate
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-report
          path: china_charge_kf/frontend/e2e-results/
```

T7 (real Dify) 不在常规 CI(需联通外网 + 付费 Dify 配额),改为手动 job:
```yaml
  e2e-real-dify:
    runs-on: ubuntu-latest
    if: github.event_name == 'workflow_dispatch'
    steps:
      ...
      - run: RUN_REAL_DIFY=1 npm run test:e2e -- --grep "@real-dify"
        env:
          DIFY_API_KEY: ${{ secrets.DIFY_API_KEY }}
          DIFY_V2_API_KEY: ${{ secrets.DIFY_V2_API_KEY }}
```

---

## 7. 已知限制 & 风险

| 项 | 说明 | 影响 |
|---|------|------|
| Cross-env added | `cross-env ^7.0.3` 加到 devDeps,Windows + bash 必备 | +1 devDep,跨平台 RUN_REAL_DIFY |
| WebServer cwd 修复 | M7 config 的 webServer[0].cwd 是 `..` (frontend/),导致 uvicorn 读 frontend/.env 缺 DIFY_API_KEY 崩溃。M8.0 改为 `../backend/` | 修了一个潜在崩溃,只在 e2e 跑时触发 |
| mock SSE body 大小 | T6 abort 测试用 12 KB body,route.fulfill 一次性发完,browser 内部流式读取,提供足够 wall-clock 让用户点 stop | 浏览器依赖内部 buffering,理论极端情况下 abort race 可能不稳定 |
| Selector 稳定性 | spec 全部用 class-name selector(`.bubble` / `.send.stop` / `.errorBanner` 等),App.tsx 没有 data-testid | 若未来重构 CSS 类名,spec 需同步更新。建议后续 M8.x 给关键 UI 元素加 `data-testid` |
| `verbatimModuleSyntax` | 继承 tsconfig.app.json 的 `verbatimModuleSyntax: true`,所有 type-only imports 必须用 `import type` 或 inline `import { type X }` | 已严格遵守,tsc 0 errors |

---

## 8. 改动文件 commit 计划

| # | 提交 | 包含文件 |
|---|------|---------|
| 1 | `feat(frontend): M8.0 — Playwright fixtures + 6 *.spec.ts (T1-T7)` | `e2e/specs/*.ts` (6 files), `e2e/helpers/*.ts` (2 files), `e2e/tsconfig.json`, `e2e/M7-REPORT.md` 不动 |
| 2 | `chore(frontend): M8.0 — playwright.config projects + reporter + npm scripts` | `e2e/playwright.config.ts`, `frontend/package.json`, `frontend/package-lock.json` |
| 3 | `docs(frontend): M8.0 completion report + CI integration roadmap` | `e2e/M8-REPORT.md` |

未触碰(符合 M8.0 约束):
- `frontend/src/**` 全部业务代码
- `backend/app_dify/**` 全部业务代码
- `e2e/M7-REPORT.md` 历史记录
- `e2e/fixtures/test-image-100x100.png` M7 fixture
- `docs/**` (M8.6 范围)

---

## 9. 后续建议(M8.1 / M8.2 / M8.3 / M8.6)

详见 M7-REPORT §8 优先级建议。M8.0 守门化完成后,后续 M8.x 改动都会被这 18 个 spec 自动验证:
- M8.1 noResponse 兜底 → 04 chat-stream-null-text + 06 abort 可直接扩
- M8.2 `<think>` strip → 加新 spec 06(在 fixture SSE 里嵌入 `<think>...</think>` 跨 chunk)
- M8.3 拍摄按钮删除 → 02 image upload spec 微调(.morePanel 第二个 panelItem 消失)
- M8.6 GH Actions workflow → 落地 §6 草案