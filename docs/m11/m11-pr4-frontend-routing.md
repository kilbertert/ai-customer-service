# M11 PR4 — basjoo 前端 + M3/M6/M7 路由层重写

> **依赖**:PR3
> **工作量**:1.0 周 1 人

---

## 1. 范围

**前端**(0.4 周):
- `/signup` 路由
- `Signup.tsx` 视图
- `Register.tsx` 拆分 bootstrap / tenant signup 分支
- `Login.tsx` 添加"立即注册"链接
- `PasswordRevealModal.tsx` 30 秒 mask 组件
- i18n 文案
- `AuthContext.signupAsTenant()` 方法

**后端路由层重写**(0.6 周):
- M3 `LLMProvider`:按 workspace_id 路由 Dify API key
- M6 `kb_document_endpoints`:tenant scoping 校验
- M7 `Widget chat_stream`:按 widget → agent → workspace → Dify tenant 路由

---

## 2. 前端改动

### 2.1 新增 `frontend-nextjs/app/(auth)/signup/page.tsx`

```typescript
"use client";

import { Signup } from "../../../src/views/Signup";

export default function SignupPage() {
  return <Signup />;
}
```

### 2.2 新增 `frontend-nextjs/src/views/Signup.tsx`

```typescript
"use client";

import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useTranslation } from "react-i18next";
import { PasswordRevealModal } from "../components/PasswordRevealModal";

export const Signup = () => {
  const { t } = useTranslation("auth");
  const { signupAsTenant } = useAuth();
  const navigate = useNavigate();

  const [workspaceName, setWorkspaceName] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [initialPassword, setInitialPassword] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password !== confirmPassword) {
      setError(t("errors.passwordMismatch"));
      return;
    }
    if (!termsAccepted) {
      setError(t("errors.termsRequired"));
      return;
    }
    setLoading(true);
    try {
      const result = await signupAsTenant({
        workspaceName, name, email, password, termsAccepted,
      });
      if (result.provisioning_status === "ready") {
        setInitialPassword(result.dify_initial_password);
      } else {
        navigate("/", { replace: true });
      }
    } catch (err: any) {
      setError(err?.message ?? t("errors.signupFailed"));
    } finally {
      setLoading(false);
    }
  };

  // 表单 JSX:workspaceName / name / email / password / confirmPassword / terms checkbox
  // 样式与 Register.tsx 保持一致,使用 liquid-glass-card

  return (
    <>
      {/* form UI */}
      {initialPassword && (
        <PasswordRevealModal
          password={initialPassword}
          onAcknowledge={() => { setInitialPassword(null); navigate("/", { replace: true }); }}
        />
      )}
    </>
  );
};
```

### 2.3 新增 `frontend-nextjs/src/components/PasswordRevealModal.tsx`

```typescript
"use client";

import { useEffect, useState } from "react";

interface Props {
  password: string;
  onAcknowledge: () => void;
}

export const PasswordRevealModal = ({ password, onAcknowledge }: Props) => {
  const [masked, setMasked] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(30);

  useEffect(() => {
    const interval = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1) { setMasked(true); clearInterval(interval); return 0; }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal-content">
        <h2>Dify workspace 创建成功</h2>
        <p>这是您 Dify workspace 的初始密码,30 秒后自动隐藏。</p>
        <p>请妥善保存,丢失需通过 Dify forgot_password 流找回。</p>
        <div className="password-display">
          {masked ? <code>{"•".repeat(32)}</code> : (
            <>
              <code>{password}</code>
              <span className="countdown">{secondsLeft}s 后隐藏</span>
            </>
          )}
        </div>
        <button onClick={onAcknowledge}>我已保存,进入 dashboard</button>
      </div>
    </div>
  );
};
```

### 2.4 `AuthContext` 新增 `signupAsTenant`

```typescript
// frontend-nextjs/src/context/AuthContext.tsx
const signupAsTenant = async (data: {
  workspaceName: string; name: string; email: string;
  password: string; termsAccepted: boolean;
}) => {
  const response = await fetch(`${API_BASE_URL}/api/v1/tenants/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      workspace_name: data.workspaceName, name: data.name,
      email: data.email, password: data.password,
      terms_accepted: data.termsAccepted,
    }),
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail ?? "Signup failed");
  }
  const result = await response.json();
  localStorage.setItem("basjoo_token", result.access_token);
  localStorage.setItem("basjoo_workspace_id", String(result.workspace_id));
  return result;
};
```

### 2.5 `Register.tsx` 拆分

保留 bootstrap 注册逻辑,但 `bootstrap_required=false` 时显示"该链接仅供系统初始化使用"。

### 2.6 `Login.tsx` 加"立即注册"链接

```typescript
{!bootstrapRequired && (
  <p>
    还没有账号?{" "}
    <Link to="/signup" style={{...}}>立即注册</Link>
  </p>
)}
```

### 2.7 i18n 文案

`frontend-nextjs/src/locales/zh-CN/auth.json` 新增 `tenantSignup.*`:

```json
{
  "tenantSignup": {
    "title": "注册 B 端账号",
    "subtitle": "创建您的智能体工作空间",
    "workspaceName": "工作空间名称",
    "workspaceNamePlaceholder": "例如:Acme 公司客服",
    "name": "您的姓名", "namePlaceholder": "您的姓名",
    "email": "邮箱", "emailPlaceholder": "you@company.com",
    "password": "密码", "passwordPlaceholder": "至少 8 个字符",
    "confirmPassword": "确认密码", "confirmPasswordPlaceholder": "再次输入密码",
    "terms": "我已阅读并同意《服务条款》和《隐私政策》",
    "submitButton": "注册", "submitInProgress": "注册中...",
    "haveAccount": "已有账号?", "loginLink": "前往登录"
  },
  "errors": {
    "passwordMismatch": "两次输入的密码不一致",
    "termsRequired": "请同意服务条款",
    "signupFailed": "注册失败,请重试"
  }
}
```

(en-US/auth.json 同步)

---

## 3. M3/M6/M7 路由层重写(后端)

### 3.1 M3 LLMProvider:workspace-scoped

```python
# backend/services/llm_service.py 新增
class TenantScopedLLMProvider:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dify_client(self, workspace_id: int) -> DifyAdminClient:
        ws = await self.db.get(Workspace, workspace_id)
        if not ws:
            raise ValueError("Workspace not found")
        if ws.dify_provisioning_status != "ready":
            raise WorkspaceNotReadyError(
                f"Dify workspace not ready: {ws.dify_provisioning_status}")
        return DifyAdminClient.for_tenant(
            tenant_id=ws.dify_tenant_id,
            admin_email=settings.DIFY_ADMIN_EMAIL,
            admin_password=settings.DIFY_ADMIN_PASSWORD,
        )
```

### 3.2 M6 kb_document_endpoints:tenant scoping 校验

```python
# backend/api/v1/kb_document_endpoints.py
# 已有 workspace_id scoping,只需验证不依赖默认 workspace
# 在每个 endpoint 入口加:assert document.workspace_id == current_user.workspace_id
```

### 3.3 M7 Widget chat_stream:workspace 路由

```python
# backend/api/v1/endpoints.py:chat_stream 路由
async def chat_stream(
    widget_token: str = Depends(verify_widget_token),
    db: AsyncSession = Depends(get_db),
):
    widget = await get_widget_by_token(widget_token, db)
    agent = await db.get(Agent, widget.agent_id)
    workspace = await db.get(Workspace, agent.workspace_id)
    if workspace.dify_provisioning_status != "ready":
        raise HTTPException(503, "Workspace not ready")
    dify_client = await get_tenant_scoped_dify_client(workspace, db)
    return await dify_client.stream_chat(...)
```

### 3.4 路由层重写清单

| 模块 | 工作量 |
|------|--------|
| M3 LLMProvider workspace-scoped | 0.2 周 |
| M6 KB documents tenant 校验 | 0.1 周 |
| M7 Widget streaming workspace 路由 | 0.3 周 |

**总 0.6 周**(已压缩,D2=暂缓简化了多成员场景设计)

---

## 4. 测试要点

### 4.1 前端单测

| 测试 | 期望 |
|------|------|
| `test_signup_form_validation` | 密码不匹配、terms 未勾等场景 |
| `test_signup_password_modal_30s_mask` | 30 秒后强制 mask |
| `test_login_page_shows_signup_link_when_not_bootstrap` | Login.tsx 条件渲染 |

### 4.2 后端路由层集成测试

| 测试 | 期望 |
|------|------|
| `test_llm_provider_routes_to_correct_dify_workspace` | workspace A 调 Dify tenant A |
| `test_widget_streaming_uses_workspace_tenant` | widget 走对 Dify tenant |
| `test_kb_documents_scoped_to_workspace` | 跨 workspace KB 访问被拒 |
| `test_workspace_not_ready_returns_503` | provisioning 失败时 chat_stream 返回 503 |

### 4.3 E2E

| 测试 | 期望 |
|------|------|
| `test_e2e_b_signup_to_chat` | 完整:注册 → 创建智能体 → 配置 widget → 访客 chat |

---

## 5. 与 M10+5 兼容性

- M10+5 已闭环的 `DifyProvider`(`backend/services/dify/`)复用,**不重写**
- 不影响 M10+5 任何已通过的测试

---

## 6. PR4 评审 checklist

- [ ] 前端 7 个新/改文件全部提交
- [ ] 后端 M3/M6/M7 路由层重写单元测试通过
- [ ] 30 秒 mask modal 在浏览器实测
- [ ] i18n 中英文案完整
- [ ] E2E 流程在 docker compose dev 环境跑通
- [ ] M10+5 测试套件无回归
- [ ] 前端单测覆盖率 ≥ 80%
- [ ] 后端路由层单测覆盖率 ≥ 80%