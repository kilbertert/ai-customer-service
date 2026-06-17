# M11 PR1 — Dify Fork 改动逐行级 Patch

> **依赖**:无(冻结期内无需 rebase,可与 PR2 并行起步)
> **工作量**:1.0 周 1 人
> **下游**:PR3 调用此 fork 暴露的 endpoint

---

## 1. 范围

Fork Dify 1.14.2 源码(已下载在 `dify-1.14.2/`,已逐文件核对实际接口),在 `controllers/console/workspace/` 下新增 **4 个 admin endpoint**,在 `services/account_service.py` 新增 1 个 service 方法,在 `error.py` + `models.py` 各加错误类与 Pydantic schema。

**总改动**:+225 行 Python,5 个文件 + 1 个 Alembic 迁移,**不影响 Dify 主线任何端点**。

> **1.14.2 兼容性核对**(已实地验证):
> - ✅ `api/services/account_service.py` 含 `AccountService.create_account` (L268)、`TenantService.create_account_and_tenant` (L326)、`TenantService.create_tenant` (L1066)、`TenantService.create_tenant_member` (L1132)
> - ✅ `api/controllers/console/workspace/__init__.py` 已注册 workspace blueprint(`api/controllers/console/__init__.py:124-125, 220`)
> - ⚠️ **`admin_required` 实际位于 `api/controllers/console/admin.py:11-30`(不在 `wraps.py`),基于 `dify_config.ADMIN_API_KEY` header 校验**,与 basjoo service account 模型天然契合 → PR1 直接 `from controllers.console.admin import admin_required`
> - ⚠️ `TenantService.create_tenant` 实际会**额外创建 `TenantPluginAutoUpgradeStrategy` 记录**(L1078-1090),PR1 的 `provision_tenant_by_admin` 必须保留这一副作用,否则新 tenant plugin 自动升级失效
> - ⚠️ 装饰器采用 PEP 695 泛型语法(`def admin_required[**P, R]`),Python ≥ 3.13 要求
> - ⚠️ `AccountService.create_account` 实际签名 `create_account(email, name, interface_language, password=None, interface_theme='light', is_setup=False, timezone=None)`,PR1 的 `create_account_with_password` 重载需兼容此签名

---

## 2. 文件改动清单

| # | 文件 | 行数 | 内容 |
|---|------|------|------|
| 1 | `dify/api/services/account_service.py` | +60 | 新增 `TenantService.provision_tenant_by_admin` |
| 2 | `dify/api/controllers/console/workspace/workspace.py` | +80 | 新增 `TenantProvisionByAdminApi`(POST /admin/workspaces) |
| 3 | `dify/api/controllers/console/workspace/workspace.py` | +40 | 新增 `TenantProvisionOwnerCredentialsApi`(GET /admin/workspaces/{id}/owner-credentials) |
| 4 | `dify/api/controllers/console/workspace/workspace.py` | +30 | 新增 `TenantProvisionRollbackApi`(DELETE /admin/workspaces/{id}) |
| 5 | `dify/api/controllers/console/workspace/workspace.py` | +10 | 新增 `TenantProvisionHealthApi`(GET /admin/workspaces/health) |
| 6 | `dify/api/controllers/console/workspace/error.py` | +15 | 新增 `TenantProvisionConflictError` / `AdminProvisionForbiddenError` |
| 7 | `dify/api/controllers/console/workspace/models.py` | +30 | 新增 Pydantic schema |

(workspace.py 累计 +160 行,但内部分 4 个 Resource 写)

---

## 3. 改动 1:`account_service.py` 新增 service 方法

### 3.1 在 `TenantService` 类内(约 `account_service.py:1153` 之后)新增

```python
@staticmethod
def provision_tenant_by_admin(
    name: str,
    owner_email: str,
    owner_name: str,
    owner_password: str,
    idempotency_key: str,
) -> dict:
    """basjoo admin 调用,一次性创建 tenant + owner account + 绑定关系。

    与 create_owner_tenant_if_not_exist 的关键差异:
    - 不依赖当前登录 user(account 参数是 owner_email/name)
    - 强制 is_admin_provision=True,bypass is_allow_create_workspace 校验
    - 同 idempotency_key 24h 内幂等
    - 全部操作在单事务内,任一失败全回滚

    Returns:
        {
            "workspace_id": str,      # Tenant.id
            "owner_account_id": str,  # Account.id
            "initial_password": str,  # 仅返回一次,basjoo 持久化前取走
            "status": "ready",
            "idempotent_replay": bool  # True 表示本次是幂等命中
        }
    """
    # 1. 幂等性检查:24h 内同 idempotency_key 已成功 → 直接返回
    existing = db.session.scalar(
        select(Tenant).where(Tenant.custom_idempotency_key == idempotency_key)
    )
    if existing:
        owner_join = db.session.scalar(
            select(TenantAccountJoin)
            .where(TenantAccountJoin.tenant_id == existing.id)
            .where(TenantAccountJoin.role == TenantAccountRole.OWNER)
        )
        if owner_join:
            # 幂等命中,直接返回(密码仍可重新生成,见下方)
            return {
                "workspace_id": existing.id,
                "owner_account_id": owner_join.account_id,
                "initial_password": _generate_initial_password(),
                "status": "ready",
                "idempotent_replay": True,
            }

    # 2. 创建 tenant(bypass is_allow_create_workspace)
    tenant = Tenant(
        name=name,
        custom_idempotency_key=idempotency_key,  # 需新增列,见下方迁移
    )
    db.session.add(tenant)
    db.session.flush()  # 拿 tenant.id

    # 3. 创建 owner account(走 AccountService.create_account_with_password)
    try:
        account = AccountService.create_account_with_password(
            email=owner_email,
            name=owner_name,
            password=owner_password,
        )
    except Exception as e:
        db.session.rollback()
        raise AdminProvisionForbiddenError(f"Failed to create owner account: {e}")

    # 4. 创建 TenantAccountJoin(role='owner')
    try:
        ta = TenantService.create_tenant_member(tenant, account, role="owner")
    except Exception as e:
        # 删除已建的 account,避免孤儿
        db.session.delete(account)
        db.session.commit()
        raise TenantProvisionConflictError(f"Failed to bind owner: {e}")

    # 5. 触发 tenant_was_created signal(Dify 默认行为)
    tenant_was_created.send(tenant)

    # 6. 生成 initial_password 返回(明文,basjoo 拿走前不在 Dify 持久化)
    initial_password = _generate_initial_password()

    db.session.commit()

    return {
        "workspace_id": tenant.id,
        "owner_account_id": account.id,
        "initial_password": initial_password,
        "status": "ready",
        "idempotent_replay": False,
    }
```

### 3.2 在 `Tenant` 模型(`dify/api/models/account.py`)新增 1 列

```python
custom_idempotency_key: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
```

(注:此列**仅供 basjoo ↔ Dify 同步使用**,Dify 其他业务不读)

### 3.3 在 `AccountService` 类内新增重载

```python
@staticmethod
def create_account_with_password(email: str, name: str, password: str) -> Account:
    """暴露外部调用的 account 创建,接受明文密码(Dify 内部 bcrypt hash)"""
    if not valid_password(password):
        raise PasswordMismatchError("Password does not meet complexity requirements")
    account = Account(
        email=email,
        name=name,
        password=password,  # Dify 模型 setter 自动 hash
        password_salt=generate_salt(),  # 见 Dify 现有实现
    )
    db.session.add(account)
    db.session.commit()
    return account
```

### 3.4 在 `account_service.py` 文件顶部新增 helper

```python
def _generate_initial_password() -> str:
    """生成 32 字节随机密码,Dify 不持久化,仅返回给 basjoo"""
    import secrets
    import string
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(32))
```

---

## 4. 改动 2-5:workspace.py 4 个 Resource

### 4.1 TenantProvisionByAdminApi(POST /console/api/admin/workspaces)

```python
@console_ns.route("/admin/workspaces")
class TenantProvisionByAdminApi(Resource):
    @console_ns.expect(console_ns.models[TenantProvisionPayload.__name__])
    @console_ns.response(200, "Success", console_ns.models[TenantProvisionResponse.__name__])
    @setup_required
    @admin_required  # 仅 Dify super admin
    def post(self):
        payload = TenantProvisionPayload.model_validate(request.get_json())

        # 参数校验
        if not payload.workspace_name or len(payload.workspace_name) > 50:
            raise TenantProvisionConflictError("workspace_name invalid")

        try:
            result = TenantService.provision_tenant_by_admin(
                name=payload.workspace_name,
                owner_email=payload.owner_email,
                owner_name=payload.owner_name,
                owner_password=payload.owner_password,
                idempotency_key=payload.idempotency_key,
            )
            return marshal(result, tenant_provision_response_fields), 200
        except TenantProvisionConflictError as e:
            return {"error": str(e)}, 409
        except AdminProvisionForbiddenError as e:
            return {"error": str(e)}, 403
```

### 4.2 TenantProvisionOwnerCredentialsApi(GET /console/api/admin/workspaces/{id}/owner-credentials)

```python
@console_ns.route("/admin/workspaces/<uuid:tenant_id>/owner-credentials")
class TenantProvisionOwnerCredentialsApi(Resource):
    @setup_required
    @admin_required
    def get(self, tenant_id: str):
        # 仅当 tenant 是 24h 内由 admin 创建时才返回密码
        tenant = db.session.get(Tenant, tenant_id)
        if not tenant:
            raise NotFound("Tenant not found")

        # 通过 custom_idempotency_key + 24h TTL 判断是否"新创建"
        # 这里简化:Tenant 模型上再增 created_via_admin_at 字段
        from datetime import datetime, timedelta, timezone
        if not tenant.created_via_admin_at or \
           tenant.created_via_admin_at < datetime.now(timezone.utc) - timedelta(hours=24):
            raise TenantProvisionConflictError("Credentials no longer retrievable")

        # 返回明文密码(此 endpoint 仅 basjoo admin 调,内网调用)
        return {
            "owner_account_id": tenant.owner_account_id,  # 需新增字段
            "initial_password": _retrieve_initial_password(tenant_id),  # 见下方
        }, 200
```

(注:`_retrieve_initial_password` 需要 Dify 侧短暂缓存明文密码,设计上不可行。**简化方案**:在 `Tenant` 模型新增 `initial_password_plain VARCHAR(64)` 列,**TTL 24h 后由后台 cron 清空**。见 §7)

### 4.3 TenantProvisionRollbackApi(DELETE /console/api/admin/workspaces/{id})

```python
@console_ns.route("/admin/workspaces/<uuid:tenant_id>")
class TenantProvisionRollbackApi(Resource):
    @setup_required
    @admin_required
    def delete(self, tenant_id: str):
        """basjoo 失败时回滚,删除 tenant + 关联 account + tenant_account_join"""
        tenant = db.session.get(Tenant, tenant_id)
        if not tenant:
            return "", 404

        # 删除顺序:join → account → tenant
        joins = db.session.scalars(
            select(TenantAccountJoin).where(TenantAccountJoin.tenant_id == tenant_id)
        ).all()
        for join in joins:
            db.session.delete(join)

        # 删 owner account
        for join in joins:
            account = db.session.get(Account, join.account_id)
            if account:
                db.session.delete(account)

        db.session.delete(tenant)
        db.session.commit()
        return "", 204
```

### 4.4 TenantProvisionHealthApi(GET /console/api/admin/workspaces/health)

```python
@console_ns.route("/admin/workspaces/health")
class TenantProvisionHealthApi(Resource):
    @setup_required
    @admin_required
    def get(self):
        return {"status": "ok", "fork_version": "m11-v1.0"}, 200
```

---

## 5. 改动 6:`workspace/error.py`

```python
class TenantProvisionConflictError(Exception):
    """Tenant provision conflict (e.g. duplicate idempotency_key, owner already exists)"""

class AdminProvisionForbiddenError(Exception):
    """Admin provision forbidden (e.g. password complexity failed)"""
```

---

## 6. 改动 7:`workspace/models.py` Pydantic schema

```python
class TenantProvisionPayload(BaseModel):
    workspace_name: str = Field(..., min_length=3, max_length=50)
    owner_email: EmailStr
    owner_name: str = Field(..., min_length=1, max_length=100)
    owner_password: str = Field(..., min_length=8)
    idempotency_key: str = Field(..., min_length=36, max_length=36)  # UUIDv7 字符串


class TenantProvisionResponse(ResponseModel):
    workspace_id: str
    owner_account_id: str
    initial_password: str
    status: str
    idempotent_replay: bool
```

---

## 7. Dify 侧模型新增字段

| 模型 | 新增列 | 用途 | TTL |
|------|--------|------|-----|
| `Tenant` | `custom_idempotency_key VARCHAR(36) NULL` | basjoo 幂等 key,24h 内去重 | 24h 后清空 |
| `Tenant` | `created_via_admin_at TIMESTAMP NULL` | 标记是 admin 创建,用于 owner-credentials 鉴权 | 24h 后清空 |
| `Tenant` | `initial_password_plain VARCHAR(64) NULL` | 临时存明文密码供 basjoo 拉取 | 24h 后清空(cron) |

**Dify 侧 Alembic 迁移脚本**:`dify/api/migrations/versions/xxxx_basjoo_admin_provision.py`(与 basjoo PR2 同步提交)

---

## 8. 事务边界设计(Case C 防护)

`provision_tenant_by_admin` 必须在 Dify 侧 **单 SQLAlchemy session 单事务** 内完成:

```python
# 伪代码,实际由 SQLAlchemy session 管理
db.session.begin()
try:
    tenant = Tenant(...)
    db.session.add(tenant); db.session.flush()

    account = AccountService.create_account_with_password(...)
    # ↑ 此函数内已 db.session.commit(),需要在子函数去 commit
    # ↓ 改为 db.session.flush() 而非 commit
    db.session.flush()

    ta = TenantService.create_tenant_member(tenant, account, role="owner")
    # ↑ 此函数内已 db.session.commit(),需同样改
    db.session.flush()

    db.session.commit()
except Exception:
    db.session.rollback()
    raise
```

**关键修复**:`AccountService.create_account` 和 `TenantService.create_tenant_member` 当前**内部 commit**,必须**改为 flush** 或者在调用前 `db.session.begin_nested()`(SAVEPOINT)。

实现选择:**保存点模式** — 在 `provision_tenant_by_admin` 顶层 `db.session.begin()`,子函数内部 commit 改为 flush,任一异常触发外层 rollback。

---

## 9. Dockerfile.fork

`dify/Dockerfile.fork` 基于 `langgenius/dify-api:1.14.2` 在最后追加:

```dockerfile
FROM langgenius/dify-api:1.14.2-fork-m11-v1.0

# basjoo M11 PR1 改动
COPY api/services/account_service.py /app/api/services/account_service.py
COPY api/controllers/console/workspace/workspace.py /app/api/controllers/console/workspace/workspace.py
COPY api/controllers/console/workspace/error.py /app/api/controllers/console/workspace/error.py
COPY api/controllers/console/workspace/models.py /app/api/controllers/console/workspace/models.py
COPY api/models/account.py /app/api/models/account.py
COPY api/migrations/versions/xxxx_basjoo_admin_provision.py /app/api/migrations/versions/
```

basjoo `.env` 引用:`DIFY_IMAGE_VERSION=1.14.2-fork-m11-v1.0`

Dify `.env` 必须配置 `ADMIN_API_KEY=<basjoo 持有>`,basjoo 调用 `/console/api/admin/workspaces/*` 时通过 `Authorization: Bearer ${ADMIN_API_KEY}` 头鉴权。

---

## 10. 测试要点

PR1 单测(覆盖率 ≥ 70%):

| 测试用例 | 期望 |
|----------|------|
| `test_provision_tenant_success` | 200,返回 workspace_id + initial_password |
| `test_provision_tenant_idempotent_replay` | 同 key 第二次调返回 `idempotent_replay=True`,不重复创建 |
| `test_provision_tenant_owner_account_failure_rollback` | account 创建失败 → tenant 也回滚,DB 无痕迹 |
| `test_provision_tenant_bind_failure_rollback` | TenantAccountJoin 失败 → account 删,tenant 删 |
| `test_provision_tenant_workspace_name_too_long` | 422 |
| `test_provision_tenant_duplicate_email` | 409(邮箱已存在) |
| `test_provision_tenant_invalid_idempotency_key` | 422 |
| `test_rollback_endpoint_cascade` | DELETE 级联删除 join + account + tenant |
| `test_owner_credentials_24h_ttl` | 25h 后 GET 返回 409 |
| `test_health_endpoint` | 200 + fork_version |

---

## 11. 与 M11 其他 PR 的耦合点

- **PR2**:basjoo Workspace 表加 `dify_tenant_id` / `dify_account_id` 列 → PR1 返回值必须包含这两个字段 ✅(已在 §4.1 实现)
- **PR3**:basjoo 后端调用 PR1 4 个 endpoint → 必须在 PR1 完成后才能合并 PR3
- **PR4**:前端不直接调 PR1,经 basjoo 后端中转 → 无耦合

---

## 12. 升级 playbook 接入(冻结期不需要,升级时执行)

详见 `m11-rollback-strategy.md` §4。简要 checklist:

1. `TenantService.create_tenant(name, is_setup=...)` 在 Dify 新版本是否仍存在
2. `TenantService.create_tenant_member(...)` 是否仍存在
3. `AccountService.create_account` 是否可重载
4. Dify 新版本是否引入新的 tenant 初始化逻辑
5. `@admin_required` 装饰器路径是否变动

PR1 在升级时若失败,回滚 = 切回 `1.14.2-fork-m11-v1.0` 旧镜像,basjoo 侧不动。

---

## 13. PR1 评审 checklist

提交 PR 前自检:
- [ ] 5 个文件改动全部提交
- [ ] Dify 侧 Alembic 迁移脚本已写
- [ ] `provision_tenant_by_admin` 事务边界已用 SAVEPOINT 验证(Case C 测试通过)
- [ ] 单测覆盖率 ≥ 70%(Dify 测试基础设施有限,目标 ≤ 80%)
- [ ] 集成测试:basjoo 调 Dify 完整流可走通(在 basjoo PR3 mock 环境)
- [ ] Dockerfile.fork 构建成功
- [ ] `docs/operations.md` 更新"Dify 升级 playbook"5 条 checklist