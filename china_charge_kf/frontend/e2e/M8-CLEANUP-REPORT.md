# M8.1-M8.5 Cleanup Suite 完成报告

**日期**: 2026-06-13
**分支**: `feat/m8-cleanup-suite`
**基线**: M8.0 (`9dec4d4`) — Playwright `*.spec.ts` 固化已合并
**交付**: 5 个 cleanup task + 1 docs commit,单分支 6 commits

---

## 1. 目标 & 范围

M8.0 完成了 e2e spec 固化(P3 守门),把 M7 验证矩阵的 18 个 test 接到 CI。
M8.0 报告显式禁止了 P1/P2/P4 业务改动 + M8.4/M8.5 backend 改动 —— 留给本次
cleanup suite 一次性收尾。

本分支按 **风险递减** 顺序交付:

| Task | 编号 | 优先级 | 改动域 | 风险 | 简述 |
|------|------|--------|--------|------|------|
| E | M8.5 | refactor | backend | 高 | `_sse_bytes` / `_truncate_error` 提取到公共模块 |
| D | M8.4 | docs | backend | 低 | `.env.example` 加 DIFY section,含 `DIFY_V2_API_KEY` |
| C | M8.3 | chore | frontend | 低 | 删 dead 拍摄(相机)按钮 |
| B | M8.2 | P2 MEDIUM | frontend | 中 | message_complete `<think>...` 兜底剥离 |
| A | M8.1 | P1 MEDIUM | frontend | 中 | 中断时 `noResponse` 兜底判定 |

**M8.0 frozen 18-spec 全程未触碰**(P3 守门保持绿)。

---

## 2. 5 个 Task 详情

### Task E — M8.5 提取 `sse_bytes` 公共模块 (commit `14d0c6d`)

**问题**: `backend/app_dify/main.py` 和 `backend/app_dify/sse_proxy_layer.py` 各自
实现了 `_sse_bytes(event_type, data) → bytes` 和 `_truncate_error_message(msg, limit)`,
是 M3+M4 时代的 copy-paste DRY violation。

**解法**: 抽到 `backend/app_dify/sse_bytes.py` 公共模块:

```python
_MAX_ERROR_MESSAGE = 200

def sse_bytes(event_type: str, data: dict | str) -> bytes:
    """W3C SSE: event: <type>\\ndata: <json>\\n\\n, UTF-8 encoded."""

def truncate_error(msg: str, limit: int = _MAX_ERROR_MESSAGE) -> str:
    """H3 强化:错误消息截断 200 字符,不泄露上游堆栈。"""
```

- `main.py` 和 `sse_proxy_layer.py` 改为 `from .sse_bytes import sse_bytes, truncate_error`
- 移除两处私有 `_sse_bytes` / `_sse_event` / `_truncate_error_message` 定义(各 -20 行)
- 旧 helper 的 28 个测试中 18 个迁移到 `tests/test_sse_bytes.py`(5 个 class)

**覆盖**:
- `test_sse_bytes.py` 18 个新 test(dict/str payload, UTF-8 safe, truncate 边界,常量值)
- `test_sse_proxy_layer.py` 保留 28 个 test(剥离 helper 测试后聚焦 4-event mapping)
- 全部 46 个 pytest 通过

**风险控制**: 改 backend 入口模块,但纯重构 —— SSE wire format 字节完全相同。

---

### Task D — M8.4 `.env.example` 加 DIFY section (commit `b4b4740`)

**问题**: `backend/.env.example` 是 Coze 时代模板,只有 `COZE_*` 变量。
`app_dify/` 启动需要 `DIFY_API_BASE` / `DIFY_API_KEY` / `DIFY_V2_API_KEY` 等,
新人 clone 后没有任何提示去查 `docs/api-contract-dify.md` 找变量清单。

**解法**: 追加完整 DIFY section,保留 Coze section 向后兼容(原 app/ 仍在运行):

```env
# === Dify Workflow (app_dify/, port 8012) ===
DIFY_API_BASE=https://your-dify-host/v1
DIFY_API_KEY=app-your-v1-key-here
DIFY_V2_API_KEY=app-your-v2-key-here
DIFY_INPUT_TEXT=input_text
DIFY_INPUT_IMAGE=input_img_id
DIFY_INPUT_AUDIO=input_audio_id
DIFY_INPUT_LANGUAGE=language
DIFY_END_USER=h5-widget
DIFY_OUTPUT_TEXT=output
```

**所有 value 都是占位符**,不含真实 key(已 grep 验证)。

---

### Task C — M8.3 删 dead 拍摄按钮 (commit `d9c7bbc`)

**问题**: `App.tsx` 有个 9 行 JSX 拍摄(camera)按钮,但 `onClick={() => {}}` 是空函数,
也没绑 `MediaCapture` API。是 M0 早期占位,后来语音/上传走另两条路径,
拍摄从未实装就遗留下来。

**解法**:
- 删 `App.tsx` 拍摄按钮 JSX(9 行)
- 同步删 `china_charge_kf/CLAUDE.md` 里那行 "支持拍摄输入"(stale doc)

**回归测试**: 无,纯删除,UI 上少一个不响应的按钮反而是 UX 改进。

---

### Task B — M8.2 兜底剥 `<think>` (commit `eb73800`)

**问题**: M3 `extract_output_text` 已在 backend workflow_finished 路径剥 `<think>...</think>`,
但**两条**前端路径漏网:

1. **跨 chunk `<think>`**: Dify 的 text_chunk 是字符级 emit,`<think>` 起止 tag 可能
   被 TCP 分片切成 `<th` / `ink>...` —— backend 的 chunk-level strip 看不全标签,
   前端在 `message_delta` 累积时也不剥,最终 message_complete 时已成既成事实。
2. **非 `output` fallback 键**: `extract_output_text` 走 U2/U7/U10 fallback 时
   有些键(`text` / `answer` / etc.)的剥离路径尚未覆盖。

**解法**: 前端 `difyStream.ts` 加 `stripThinkTags(text)` 公共函数:

```ts
const THINK_TAG_RE = /<think>[\s\S]*?<\/think>/gi
export function stripThinkTags(text: string): string {
  if (!text) return text
  return text.replace(THINK_TAG_RE, '')
}
```

- `[\s\S]*?` lazy 多行 + `gi` flag(case-insensitive + global)
- App.tsx `message_complete` 处理时:
  `const completeText = ev.text === null ? null : stripThinkTags(ev.text)`
- **null vs '' 区分保留**: M6.1 "no reply" 语义不受影响

**覆盖**: 7 个 vitest 新 test
- 单行单块、多行 spanning、多块 g flag、lazy 非贪婪(`KEEP_ME` regression)、
  passthrough、空串、大小写混合

**Defense-in-depth**: backend 仍剥(主防线),frontend 兜底(防线 2)。

---

### Task A — M8.1 中断 noResponse 兜底 (commit `3ff9124`)

**问题**: M6.3 实现 AbortController 中断时,**无条件**给 message 设 `stopped: true`,
不管气泡里是否真有文字。结合 M6.1 增加的 `noResponse` 字段和 "(no response)"
i18n 渲染,以下三种状态没区分清楚:

- **A**: 用户点停 + 已收到 partial text → 应显示 `(stopped)` 后缀(M6.3)
- **B**: 用户点停 + 还没收到任何 text_chunk → 应显示 `(no response)` 占位
- **C**: backend 主动返回 None → M6.1 已正确显示 `(no response)`

M6.3 把 B 错误归到 A 行为,空气泡显示 `(stopped)` 但没内容,UX 退化。

**解法**: `difyStream.ts` 加纯函数 `abortStatePatch(currentText)`:

```ts
export interface AbortStatePatch {
  stopped: boolean
  noResponse: boolean
}

export function abortStatePatch(currentText: string | null | undefined): AbortStatePatch {
  if (!currentText) return { stopped: false, noResponse: true }
  return { stopped: true, noResponse: false }
}
```

App.tsx catch 块:

```ts
if (e instanceof DOMException && e.name === 'AbortError') {
  setMessages((prev) =>
    prev.map((m) => (m.id === assistantId ? { ...m, ...abortStatePatch(m.text) } : m)),
  )
  return
}
```

**两字段都显式赋值**(不是 undefined),所以上一次 abort 的 `stopped: true`
不会通过 spread 漏到下一次 abort 的 noResponse 路径。

**覆盖**: 5 个 vitest 新 test
- 空串 → noResponse、null → noResponse、undefined → noResponse、partial → stopped、
  always-set-both-fields regression

---

## 3. 测试矩阵 & 覆盖率

| Layer | 文件 | Before | After | Delta |
|-------|------|--------|-------|-------|
| backend pytest | `test_sse_bytes.py` | — (new) | 18 | +18 |
| backend pytest | `test_sse_proxy_layer.py` | 46 | 28 | -18(迁移) |
| backend pytest | **合计 sse_*** | **46** | **46** | **0**(纯迁移) |
| frontend vitest | `difyStream.test.ts` | 46 | 58 | +12(7 strip + 5 abort) |

**测试总计**: backend sse_* 46 pass,frontend 58 pass。

**M8.0 frozen 18-spec**(`e2e/specs/T1-T7`)未触碰,守门保持绿。

---

## 4. Commit 链(6 commits)

```
3ff9124 feat(frontend): M8.1 — abort path noResponse fallback
eb73800 feat(frontend): M8.2 — strip <think> tags from message_complete text
d9c7bbc chore(frontend): M8.3 — remove dead 拍摄 (camera) button
b4b4740 docs(backend): M8.4 — add DIFY section to .env.example incl. DIFY_V2_API_KEY
14d0c6d refactor(backend): M8.5 — extract sse_bytes helpers to public module
9dec4d4 ← M8.0 baseline
```

**顺序逻辑**: E (refactor 入口) → D (env 模板) → C (删 dead) → B (兜底 strip)
→ A (中断兜底)。docs commit 排在最后(本文件)。

---

## 5. 风险评估 & 回滚路径

| Task | 风险面 | 回滚 |
|------|--------|------|
| E | 改了 main.py / sse_proxy_layer.py 入口 | `git revert 14d0c6d`,helper 函数旧定义回到两处 |
| D | 只加文档 | `git revert b4b4740` |
| C | 删 UI 按钮 | `git revert d9c7bbc`,按钮恢复但仍无 onClick handler |
| B | 改 message_complete 渲染 | `git revert eb73800`,backend 主防线仍生效 |
| A | 改 abort catch 块 | `git revert 3ff9124`,所有 abort 退化到 `stopped: true` |

**所有 commit 独立 revertable**,M8.0 行为可逐个回退。

---

## 6. 已验证 & 已校对

- [x] backend pytest 46/46 (`test_sse_bytes.py` + `test_sse_proxy_layer.py`)
- [x] frontend vitest 58/58 (`difyStream.test.ts`)
- [x] frontend `npx tsc --noEmit` clean
- [x] `git log 9dec4d4..HEAD` = 5 个 task commit + 1 docs(待加)
- [x] M8.0 frozen 18-spec 未触碰(`e2e/specs/` 0 changes)
- [x] `.env.example` 不含真实 secret(grep 验证)
- [x] `<think>` strip 保留 M6.1 null-vs-empty 语义
- [x] `abortStatePatch` 显式赋值两字段,无 spread leak

---

## 7. M9 进展回填 (2026-06-13)

- ✅ **M9 候选 #1 (真 Dify e2e)**:M9 阶段通过 Playwright MCP 跑了 T7 `@real-dify` 探针(基线 短查 27 fires / 长查 104 fires,见 `M9-PROMPT.md` §1.5),并新增 `specs/07-think-streaming.spec.ts` 永久守门
- ⏭️ **M9 候选 #2 (`_dig_first_text` 整合)**:M9 范围之外,**未做**,留作 M9.x / M10+ 候选
- ✅ **M9 候选 #3 (i18n 完整性)**:M8.1 阶段已 audit 通过(`(no response)` 和 `(stopped)` 在 zh/en/vi 齐全)
- 详见 `frontend/e2e/M9-REPORT.md`

---

**报告完毕**。本分支可 merge 到 main。
