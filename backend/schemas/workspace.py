"""Workspace Pydantic schemas (M10 G3 — Dify 4 字段)。

设计要点:
    1. ``WorkspaceUpdate.dify_api_key`` setter 走 Fernet 加密
       (复用 ``core.encryption.encrypt_api_key`` 懒加载 ENCRYPTION_KEY)
    2. ``WorkspaceRead.dify_api_key`` 反序列化时**不**自动解密
       —— DB 存密文,API 也回密文(``enc:`` 标记),避免日志泄露
    3. plaintext → ciphertext 单向:经 Pydantic ``model_dump()`` 后
       写到 DB 的 ``dify_api_key`` 列永远是密文形态
    4. Plan A/B 拓扑由 ``dify_api_key`` 是否为 NULL 判定
       (NULL = Plan B 共享;非空 = Plan A 独占)

加密策略:
    - 加密入口:``encrypt_api_key(plaintext) -> Optional[str]``
    - 解密入口:``decrypt_api_key(ciphertext) -> Optional[str]``
    - 已有 ``enc:`` 前缀的串视为已加密,二次 encrypt 是 noop(幂等)
    - 加密失败 fallback 到 plaintext(保留 ``core.encryption`` 原行为)
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from core.encryption import encrypt_api_key


class WorkspaceUpdate(BaseModel):
    """PATCH /api/v1/workspaces/{id} body — partial update。

    所有字段都 optional;不传 = 不改。``dify_api_key`` 字段接收
    明文,Pydantic 序列化时自动 Fernet 加密(``enc:`` 前缀)。
    """

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
    )

    name: Optional[str] = Field(
        default=None, max_length=100, description="工作空间名"
    )
    owner_email: Optional[str] = Field(
        default=None, max_length=255, description="工作空间 owner email"
    )
    dify_api_base: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Dify API endpoint (NULL = 用平台默认)",
    )
    dify_api_key: Optional[str] = Field(
        default=None,
        description=(
            "Dify API key (明文 → Pydantic 序列化时自动 Fernet 加密). "
            "NULL = 走 Plan B 共享;非空 = Plan A 独占"
        ),
    )
    dify_workspace_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Dify 端 workspace UUID (Plan A 必填)",
    )
    dify_enabled: Optional[bool] = Field(
        default=None,
        description="Dify 集成总开关 (False = 走 OpenAI 直连)",
    )

    @field_serializer("dify_api_key")
    def _encrypt_dify_api_key(self, v: Optional[str]) -> Optional[str]:
        """序列化时把 plaintext 加密成 ``enc:...`` 形态。

        - 已经是 ``enc:`` 前缀的串视为已加密,二次加密是 noop
        - 空串/None 原样返回(由 model 层判定 NULL vs 空)
        - 加密失败 fallback 到 plaintext(``core.encryption`` 已 log)
        """
        if v is None or v == "":
            return v
        return encrypt_api_key(v)


class WorkspaceRead(BaseModel):
    """GET /api/v1/workspaces/{id} response shape。

    注意 ``dify_api_key`` 字段**不**暴露给 API 消费者
    (避免响应体泄露密文 + 标志);
    API 层只透出 ``dify_api_key_set: bool`` 表示"是否配置了 key"。
    真实 key 仅在 PATCH 请求体里接收。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    owner_email: str
    dify_api_base: Optional[str] = None
    dify_api_key_set: bool = Field(
        default=False,
        description="是否已配置 dify_api_key (boolean,不暴露密文)",
    )
    dify_workspace_id: Optional[str] = None
    dify_enabled: bool = False
