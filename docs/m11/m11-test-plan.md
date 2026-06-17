# M11 Test Plan — 测试用例清单

> **覆盖范围**:M11 整体 + 4 个 PR 各自的验收测试

---

## 1. 测试层次

| 层次 | 工具 | 覆盖率目标 |
|------|------|----------|
| 单元测试 | pytest(backend) / Jest(frontend) | ≥ 80% |
| 集成测试 | pytest + docker compose dev | 关键路径 100% |
| E2E | Playwright | 4 个核心用户旅程 |
| 性能 | k6 / locust | 注册 P95 < 3s |

---

## 2. PR1 测试用例(Dify fork)

详见 `m11-pr1-dify-fork.md` §10。10 个测试用例,覆盖率 ≥ 70%。

---

## 3. PR2 测试用例(basjoo schema)

详见 `m11-pr2-schema.md` §6。6 个测试用例,覆盖率 ≥ 80%。

---

## 4. PR3 测试用例(注册流后端)

详见 `m11-pr3-register-flow.md` §4。13 个单元测试 + 3 个集成测试 + 1 个性能测试。

**额外场景**:

| 测试 | 期望 |
|------|------|
| `test_register_concurrent_same_email` | 并发同邮箱 → 1 个成功 1 个 409 |
| `test_register_with_dify_503_response` | Dify 返回 503 → basjoo 标 failed |
| `test_register_idempotency_after_basjoo_restart` | basjoo 进程重启后同 key 不重复注册 |
| `test_retry_after_3_failures_marks_failed_permanent` | 第 3 次失败 → failed_permanent + 通知 admin |
| `test_audit_logs_no_pii_leak` | audit_log 不含密码 / 邮箱明文 |
| `test_email_blacklist_bypass_attempt` | 试图绕过黑名单(改大小写等) |
| `test_rate_limit_per_ip` | 同 IP 第 6 次注册 → 429 |
| `test_rate_limit_per_email` | 同 email 第 4 次注册 → 429 |

---

## 5. PR4 测试用例(前端 + 路由层)

详见 `m11-pr4-frontend-routing.md` §4。3 个前端单测 + 4 个后端集成测试 + 1 个 E2E。

**额外场景**:

| 测试 | 期望 |
|------|------|
| `test_signup_form_xss_prevention` | workspace_name 含 `<script>` 被转义 |
| `test_signup_form_unicode_workspace_name` | 中文 / emoji 名字正常处理 |
| `test_password_modal_close_on_esc` | ESC 键不能关闭(必须确认) |
| `test_password_modal_browser_back_button` | 后退按钮不能跳过 modal |
| `test_widget_streaming_workspace_isolation` | workspace A 的 widget 不能访问 B 数据 |
| `test_kb_documents_cross_workspace_403` | 跨 workspace KB 访问被拒 |

---

## 6. E2E 核心用户旅程(Playwright)

### Journey 1:B 端 owner 完整流程

```typescript
// e2e/specs/m11-b-signup-full.spec.ts
test("B 端 owner 完整流程", async ({ page }) => {
  await page.goto("http://localhost:3001/login");
  await page.click("text=立即注册");
  await page.fill('input[name="workspaceName"]', "Acme 测试公司");
  await page.fill('input[name="name"]', "张三");
  await page.fill('input[name="email"]', `test-${Date.now()}@acme.com`);
  await page.fill('input[name="password"]', "TestPass123!");
  await page.fill('input[name="confirmPassword"]', "TestPass123!");
  await page.check('input[name="terms"]');
  await page.click('button[type="submit"]');
  await expect(page.locator(".modal-content")).toBeVisible();
  const password = await page.locator(".password-display code").textContent();
  expect(password).toHaveLength(32);
  await page.click("text=我已保存");
  await expect(page).toHaveURL("http://localhost:3001/");
  // 后续:创建智能体 + 验证 Dify 侧
});
```

### Journey 2:Dify 故障注入 → basjoo 自动恢复

```typescript
test("Dify 故障注入 → 自动恢复", async ({ page }) => {
  // 1. 注册 workspace(走通)
  // 2. kill Dify 容器
  // 3. 触发 workspace retry(Dashboard 手动按钮)
  // 4. 重启 Dify 容器
  // 5. 等待 basjoo 自动 cron 重试
  // 6. 验证 provisioning 状态从 failed → ready
});
```

### Journey 3:跨 workspace 隔离验证

```typescript
test("跨 workspace 隔离", async ({ page }) => {
  // 注册 A → 在 A 创建 agent/KB
  // 注册 B → 验证 B 看不到 A 数据
  // 用 B widget token 访问 A 资源 → 403
});
```

### Journey 4:Dify 升级 playbook 模拟(冻结期不跑,升级时跑)

```bash
git checkout dify-1.15.x
./scripts/dify-upgrade-playbook.sh
# 1. 跑 5 条 checklist
# 2. 启动 Dify 新版本
# 3. basjoo 测试套件跑通
# 4. 24h 监控
```

---

## 7. 性能测试(k6)

```javascript
// e2e/load/m11-register-stress.js
import http from "k6/http";
import { check } from "k6";

export const options = {
  stages: [
    { duration: "30s", target: 10 },
    { duration: "1m", target: 50 },
    { duration: "30s", target: 0 },
  ],
  thresholds: {
    http_req_duration: ["p(95)<3000"],
    http_req_failed: ["rate<0.01"],
  },
};

export default function () {
  const email = `loadtest-${__VU}-${__ITER}@example.com`;
  const res = http.post(
    "http://localhost:8000/api/v1/tenants/register",
    JSON.stringify({
      workspace_name: `Load Test ${__VU}`, name: `User ${__VU}`,
      email, password: "LoadTest123!", terms_accepted: true,
    }),
    { headers: { "Content-Type": "application/json" } }
  );
  check(res, {
    "status is 200 or 429": (r) => r.status === 200 || r.status === 429,
  });
}
```

---

## 8. 测试环境

| 环境 | 用途 | 数据 |
|------|------|------|
| 单测 | pytest / Jest in-memory mock | 无真实 Dify |
| 集成 | docker compose dev | 临时数据 |
| E2E | docker compose dev + Playwright | 临时数据 |
| 性能 | docker compose dev + k6 | 临时数据 |
| 升级 playbook | 切到 Dify 新版本镜像(冻结期不跑) | 生产数据备份后验证 |

---

## 9. 测试目录(避免污染 M10+5)

```
backend/tests/
├── m11/
│   ├── test_tenants_register.py        # PR3
│   ├── test_tenant_provisioner.py      # PR3
│   ├── test_provisioning_retry.py      # PR3
│   ├── test_workspace_provisioning.py  # PR2
│   └── test_tenant_routing.py          # PR4

dify/api/tests/
├── test_tenant_provision_by_admin.py   # PR1
├── test_rollback_endpoint.py           # PR1
└── test_owner_credentials_ttl.py       # PR1

frontend-nextjs/tests/unit/
└── Signup.test.tsx                     # PR4
```

---

## 10. 验收门(M11 整体)

1. **单测**:M11 新增 + M10+5 已有 ≥ 80% 覆盖率
2. **集成**:M11 集成测试 + M10+5 集成测试全绿
3. **E2E**:4 个核心用户旅程全绿
4. **性能**:注册 P95 < 3s,失败率 < 1%
5. **M10+5 无回归**:M10+5 已有测试 100% 通过
6. **Dify 升级 playbook**:`docs/operations.md` 含完整章节(冻结期不要求跑)

---

## 11. 测试不通过时的处理

| 失败级别 | 处理 |
|----------|------|
| 单元测试失败 | PR 不能合入,必须修 |
| 集成测试失败 | PR 不能合入 |
| E2E 失败 | 阻塞 main 合并,hotfix |
| 性能不达标 | 阻塞 M11 release,优化后重测 |
| M10+5 回归 | 阻塞 main 合并,回滚 PR |

---

## 12. PR 评审与测试要求

| PR | 必跑测试 |
|----|----------|
| PR1 | Dify pytest + basjoo mock 集成 |
| PR2 | alembic upgrade/downgrade SQLite + Postgres |
| PR3 | 单测 + 集成 + docker compose dev |
| PR4 | 前端 Jest + 后端单测 + E2E + 性能 |