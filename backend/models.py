import hashlib
import uuid
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    Text,
    TIMESTAMP,
    String,
    Boolean,
    ForeignKey,
    JSON,
    Enum as SQLEnum,
    Index,
    Float,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, relationship
from sqlalchemy.sql import func

from database import Base
from config import DEFAULT_AGENT_MAX_TOKENS, DEFAULT_AGENT_SIMILARITY_THRESHOLD


def normalize_url(url: str) -> str:
    """规范化URL（去重用）"""
    url = url.strip().lower()
    # 移除末尾斜杠
    if url.endswith("/"):
        url = url[:-1]
    # 移除www前缀
    if url.startswith("https://www."):
        url = url.replace("https://www.", "https://", 1)
    elif url.startswith("http://www."):
        url = url.replace("http://www.", "http://", 1)
    return url


def compute_content_hash(content: str) -> str:
    """计算内容哈希（用于去重）"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class Workspace(Base):
    """工作空间模型"""

    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, default="Default Workspace")
    owner_email = Column(String(255), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # M10 G3: Dify 集成层字段(同时支持 Plan A / Plan B 拓扑)
    # NULL dify_api_key = Plan B (共享 Dify workspace + 共享 API key)
    # 非空 dify_api_key = Plan A (本 workspace 独占 Dify workspace)
    dify_api_base = Column(String(255), nullable=True)
    dify_api_key = Column(Text, nullable=True)  # Fernet 加密,见 core/encryption.py
    dify_workspace_id = Column(String(64), nullable=True)  # Dify 端 workspace UUID
    dify_enabled = Column(Boolean, nullable=False, default=False)  # 总开关

    # M10+2 D4.1: Dify admin 凭据 (workspace service account)
    # dify_enabled=True 时必须 2 个都非空,否则 endpoint fail-fast 400
    # dify_admin_email: 明文 (Dify admin 用 email 登录, 非密钥无需加密)
    # dify_admin_password_ref: Fernet 加密 (解密切 core.encryption.decrypt_api_key)
    # DifyAdminClient.from_workspace 用这 2 个字段构造生产侧管理 API 客户端
    dify_admin_email = Column(String(255), nullable=True)
    dify_admin_password_ref = Column(Text, nullable=True)  # Fernet 加密

    # M11 PR2: Dify tenant provisioning 状态机 (新 workspace 自助签约 Dify tenant)
    # dify_tenant_id: Dify tenant UUID (NULL = 还没签 / bootstrap workspace)
    # dify_account_id: Dify account UUID (NULL = 还没签)
    # dify_provisioning_status: 'pending' / 'provisioning' / 'ready' / 'failed'
    #   - pending: 待发起 provisioning
    #   - provisioning: 正在调用 Dify API (D5 job 中)
    #   - ready: Dify tenant 创建成功 (tenant_id + account_id 都非空)
    #   - failed: 连续 retry 仍失败,等 ops 介入
    # dify_provisioning_attempts: 累计失败次数,达 5 次后转 failed
    # dify_provisioning_last_error: 最近一次失败原因(给 ops debug)
    # signup_idempotency_key: 注册时一次性幂等键,UUID v4,
    #   同 key 多次请求不会创建多个 workspace (DB 层 UNIQUE 约束)
    dify_tenant_id = Column(String(36), nullable=True)
    dify_account_id = Column(String(36), nullable=True)
    dify_provisioning_status = Column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    dify_provisioning_attempts = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    dify_provisioning_last_error = Column(Text, nullable=True)
    signup_idempotency_key = Column(String(36), unique=True, nullable=True)

    # M11 PR2 索引:由 SQLAlchemy ``create_all`` 在 fresh DB 自动建,
    # existing DB 由 ``sqlite_migrations._migrate_workspaces_dify_provisioning``
    # 用 ``CREATE INDEX IF NOT EXISTS`` 补。注:``signup_idempotency_key`` 的
    # UNIQUE 约束由上面 ``unique=True`` 触发,SQLite 把它实现为
    # ``sqlite_autoindex_workspaces_*``(对 NULL 用 distinct 语义,符合预期)。
    __table_args__ = (
        Index("idx_workspaces_dify_tenant_id", "dify_tenant_id"),
        Index("idx_workspaces_dify_provisioning_status", "dify_provisioning_status"),
    )

    # 关系
    agents = relationship(
        "Agent", back_populates="workspace", cascade="all, delete-orphan"
    )
    quotas = relationship("WorkspaceQuota", back_populates="workspace", uselist=False)
    admin_users = relationship("AdminUser", back_populates="workspace")
    # M10 G2: Tenant ↔ Workspace 1:1 (Tenant.plan 字段保留为 M11+ 占位,本 M10 不实现)
    tenant = relationship(
        "Tenant",
        back_populates="workspace",
        uselist=False,
        cascade="all, delete-orphan",
    )
    # M10 G2: 直接 FK 到 workspace 的 KB(避免 JOIN tenants)
    knowledge_bases = relationship(
        "KnowledgeBase", back_populates="workspace", cascade="all, delete-orphan"
    )


class Agent(Base):
    """Agent模型"""

    __tablename__ = "agents"

    id = Column(
        String(50), primary_key=True, default=lambda: f"agt_{uuid.uuid4().hex[:12]}"
    )
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id"), nullable=False, index=True
    )

    # 基本信息
    name = Column(String(100), nullable=False, default="AI Agent")
    description = Column(Text, nullable=True)
    agent_type = Column(String(50), nullable=False, default="website_support")
    channel_mode = Column(String(50), nullable=False, default="web_widget")
    avatar = Column(String(500), nullable=True)

    # LLM配置
    system_prompt = Column(
        Text, nullable=False, default="You are a helpful customer service assistant."
    )
    model = Column(String(100), nullable=False, default="gpt-4o-mini")
    temperature = Column(Float, nullable=False, default=0.7)
    max_tokens = Column(Integer, nullable=False, default=DEFAULT_AGENT_MAX_TOKENS)

    # API配置
    api_key = Column(String(500), nullable=True)
    api_base = Column(String(500), nullable=True, default="https://api.openai.com/v1")

    # Jina Embedding API Key
    jina_api_key = Column(String(500), nullable=True)

    # SiliconFlow Embedding API Key
    siliconflow_api_key = Column(String(500), nullable=True)

    # Multimodal chat (PR13) — image captioning + voice transcription
    vision_api_key = Column(String(500), nullable=True)
    vision_base_url = Column(
        String(500), nullable=True, default="https://api.openai.com/v1"
    )
    vision_provider_type = Column(String(20), nullable=True, default="openai")
    vision_model = Column(String(100), nullable=True, default="gpt-4o")
    whisper_api_key = Column(String(500), nullable=True)
    whisper_base_url = Column(
        String(500), nullable=True, default="https://api.openai.com/v1"
    )
    whisper_model = Column(String(100), nullable=True, default="whisper-1")

    # AI服务商配置
    provider_type = Column(
        SQLEnum(
            "openai",
            "openai_native",
            "google",
            "anthropic",
            "xai",
            "openrouter",
            "zai",
            "deepseek",
            "minimax",            # PR: MiniMax (OpenAI 兼容) https://api.minimaxi.com/v1
            "volcengine",
            "moonshot",
            "aliyun_bailian",
            "siliconflow",
            name="llm_provider",
        ),
        nullable=True,
        default="openai",
    )

    # Azure OpenAI特定配置
    azure_endpoint = Column(String(500), nullable=True)
    azure_deployment_name = Column(String(100), nullable=True)
    azure_api_version = Column(String(20), nullable=True)

    # Anthropic特定配置
    anthropic_version = Column(String(20), nullable=True, default="2023-06-01")

    # Google特定配置
    google_project_id = Column(String(100), nullable=True)
    google_region = Column(String(50), nullable=True)

    # 通用提供商配置
    provider_config = Column(JSON, nullable=True)

    # 嵌入配置
    embedding_provider = Column(String(20), nullable=False, default="jina")
    embedding_api_base = Column(String(500), nullable=True)
    embedding_model = Column(String(100), nullable=False, default="jina-embeddings-v3")
    embedding_batch_size = Column(Integer, nullable=False, default=4)
    # 知识库初始化状态
    kb_setup_completed = Column(Boolean, nullable=False, default=False)
    # URL抓取配置
    crawl_max_depth = Column(Integer, nullable=False, default=2)  # 全站爬取深度
    crawl_max_pages = Column(Integer, nullable=False, default=20)  # 全站爬取最大页面数
    url_fetch_interval_days = Column(
        Integer, nullable=False, default=7
    )  # URL自动抓取间隔（天）
    enable_auto_fetch = Column(
        Boolean, nullable=False, default=False
    )  # 是否启用自动抓取

    # 检索配置
    top_k = Column(Integer, nullable=False, default=8)
    similarity_threshold = Column(
        Float, nullable=False, default=DEFAULT_AGENT_SIMILARITY_THRESHOLD
    )
    enable_context = Column(Boolean, nullable=False, default=False)

    # AI对话限制配置
    rate_limit_per_minute = Column(
        Integer, nullable=False, default=20
    )  # 每分钟对话限制（0表示不限制）
    restricted_reply = Column(
        Text, nullable=True, default="抱歉，当前服务受限，请稍后再试。"
    )  # 自动回复（速率限制、AI 服务异常等场景）
    last_error_code = Column(String(50), nullable=True)
    last_error_message = Column(Text, nullable=True)
    last_error_at = Column(DateTime(timezone=True), nullable=True)
    allowed_widget_origins = Column(JSON, nullable=True, default=None)

    # 人设类型
    persona_type = Column(
        String(20), nullable=False, default="general"
    )  # general, customer-service, sales, custom

    # Widget 配置
    widget_title = Column(String(100), nullable=True, default="AI 客服")
    widget_color = Column(String(20), nullable=True, default="#06B6D4")
    welcome_message = Column(
        Text, nullable=True, default="您好！我是Basjoo助手，有什么可以帮您的吗？"
    )
    history_days = Column(Integer, nullable=False, default=30)

    # 状态
    is_active = Column(Boolean, default=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    purge_after = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 知识库关联（新增）
    kb_id = Column(
        String(36), ForeignKey("knowledge_bases.id"), nullable=True, index=True
    )

    # M10 G3: Dify 集成层 per-agent 字段
    dify_workflow_id = Column(String(64), nullable=True)  # 1 agent = 1 workflow
    # M10 G1: end_user 编码策略 (双层 agent-{aid}-v-{vid}-s-{sid})
    dify_user_prefix = Column(String(20), nullable=False, default="agent-")
    dify_inputs_schema = Column(JSON, nullable=True)  # G1 schema 描述(可选)
    dify_end_user_strategy = Column(
        String(20), nullable=False, default="dual_layer"
    )  # dual_layer | legacy
    # M10+1 D7: Dify App UUID (workflow 是 App 下属资源, 多 1 个外键便于回查)
    dify_app_id = Column(String(64), nullable=True)
    # M10+1 D8: per-agent runtime API key (Fernet 加密存储, 解密见 core.encryption)
    # 来源: Dify POST /console/api/apps/{id}/api-keys 返回的 "app-xxx..." token
    dify_api_key = Column(Text, nullable=True)
    # M10+1 D9(c): workflow publish 状态字段
    # 枚举: 'draft' (未 publish) | 'published' (publish 成功) | 'publish_failed' (Dify 校验失败/空 graph 等)
    dify_publish_status = Column(
        String(32), nullable=False, default="draft", server_default="draft"
    )
    dify_publish_error = Column(Text, nullable=True)  # publish 失败时的错误信息

    # 关系
    workspace = relationship("Workspace", back_populates="agents")
    url_sources = relationship(
        "URLSource", back_populates="agent", cascade="all, delete-orphan"
    )
    knowledge_files = relationship(
        "KnowledgeFile", back_populates="agent", cascade="all, delete-orphan"
    )
    chat_sessions = relationship(
        "ChatSession", back_populates="agent", cascade="all, delete-orphan"
    )
    members = relationship(
        "AgentMember", back_populates="agent", cascade="all, delete-orphan"
    )
    knowledge_base = relationship("KnowledgeBase", back_populates="agents")


class URLSource(Base):
    """URL知识源模型"""

    __tablename__ = "url_sources"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(50), ForeignKey("agents.id"), nullable=False, index=True)

    # URL信息
    url = Column(String(1000), nullable=False, index=True)
    normalized_url = Column(String(1000), nullable=False, index=True)  # 规范化后的URL

    # 抓取状态
    status = Column(
        SQLEnum("pending", "fetching", "success", "failed", name="url_status"),
        default="pending",
        index=True,
    )
    last_fetch_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)

    # 抓取内容
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=True)  # 清洗后的正文
    content_hash = Column(String(64), nullable=True)  # 用于去重

    # 元数据
    fetch_metadata = Column(
        JSON, nullable=True
    )  # etag, last_modified, content_length等
    is_indexed = Column(Boolean, nullable=False, default=False)  # 是否已训练
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关系
    agent = relationship("Agent", back_populates="url_sources")

    # 索引和约束
    __table_args__ = (
        Index("ix_url_sources_agent_status", "agent_id", "status"),
        UniqueConstraint("agent_id", "normalized_url", name="uq_agent_normalized_url"),
    )


class KnowledgeFile(Base):
    """知识文件模型"""

    __tablename__ = "knowledge_files"

    id = Column(
        String(50), primary_key=True, default=lambda: f"kf_{uuid.uuid4().hex[:12]}"
    )
    agent_id = Column(String(50), ForeignKey("agents.id"), nullable=False, index=True)

    # 文件信息
    filename = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=True)  # bytes
    file_type = Column(String(50), nullable=True)  # pdf, txt, csv, etc.

    # 状态
    status = Column(
        SQLEnum(
            "uploading", "processing", "ready", "failed", "pending", name="file_status"
        ),
        default="uploading",
        index=True,
    )
    error_message = Column(Text, nullable=True)

    # 元数据
    metadata_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关系
    agent = relationship("Agent", back_populates="knowledge_files")

    # 索引
    __table_args__ = (Index("ix_knowledge_files_agent", "agent_id"),)


class ChatSession(Base):
    """聊天会话模型"""

    __tablename__ = "chat_sessions"

    id = Column(
        String(50), primary_key=True, default=lambda: f"sess_{uuid.uuid4().hex[:12]}"
    )
    agent_id = Column(String(50), ForeignKey("agents.id"), nullable=False, index=True)

    # 会话标识
    session_id = Column(
        String(100), nullable=False, index=True
    )  # 客户端提供的session_id
    locale = Column(String(10), nullable=True, default="zh-CN")

    # 访客信息
    visitor_id = Column(String(100), nullable=True, index=True)  # 访客标识
    visitor_ip = Column(String(50), nullable=True)  # 访客 IP
    visitor_user_agent = Column(String(500), nullable=True)  # 访客浏览器信息
    visitor_country = Column(String(50), nullable=True)  # 访客国家
    visitor_region = Column(String(50), nullable=True)  # 访客省份/地区
    visitor_city = Column(String(50), nullable=True)  # 访客城市

    # 会话状态: active-活跃, taken_over-已接管, closed-已关闭
    status = Column(String(20), nullable=False, default="active", index=True)

    # 统计
    message_count = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)

    # 时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关系
    agent = relationship("Agent", back_populates="chat_sessions")
    messages = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan"
    )

    # 索引
    __table_args__ = (
        Index(
            "uq_chat_sessions_active_session",
            "agent_id",
            "session_id",
            unique=True,
            sqlite_where=text("status != 'closed'"),
        ),
        Index("ix_chat_sessions_agent_session", "agent_id", "session_id"),
        Index("ix_chat_sessions_updated", "updated_at"),
    )


class ChatMessage(Base):
    """聊天消息模型"""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        String(50), ForeignKey("chat_sessions.id"), nullable=False, index=True
    )

    # 消息内容
    role = Column(
        SQLEnum("user", "assistant", "system", name="message_role"), nullable=False
    )
    content = Column(Text, nullable=False)

    # 发送者信息（用于区分人工和 Agent）
    sender_type = Column(String(20), nullable=True)  # 'agent', 'human'
    sender_id = Column(String(50), nullable=True)  # 管理员ID（人工发送时）

    # 引用来源
    sources = Column(
        JSON, nullable=True
    )  # [{"type": "url", "title": "...", "url": "...", "snippet": "..."}]

    # Token使用
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)

    # 时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    session = relationship("ChatSession", back_populates="messages")
    # PR13: viewonly back-ref; the chat pipeline does the FK back-fill
    # explicitly in persist_chat_response (see api/v1/endpoints.py).
    attachments = relationship(
        "MessageAttachment",
        primaryjoin="ChatMessage.id==foreign(MessageAttachment.message_id)",
        viewonly=True,
    )

    # 索引
    __table_args__ = (
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
    )


class WorkspaceQuota(Base):
    """工作空间配额模型"""

    __tablename__ = "workspace_quotas"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id"), nullable=False, unique=True, index=True
    )

    # 配额限制
    max_agents = Column(Integer, default=10)
    max_urls = Column(Integer, default=500)
    max_qa_items = Column(Integer, default=100)
    max_messages_per_day = Column(Integer, default=1500)
    max_total_text_mb = Column(Integer, default=20)  # 最大文本量MB

    # 当前使用量
    used_urls = Column(Integer, default=0)
    used_qa_items = Column(Integer, default=0)
    used_messages_today = Column(Integer, default=0)
    used_total_text_mb = Column(Float, default=0.0)

    # Multimodal chat (PR13) — column reserved; daily MB cap NOT enforced in PR13.
    max_attachment_mb_per_day = Column(Integer, default=50)
    used_attachment_mb_today = Column(Float, default=0.0)

    # 重置时间
    last_message_reset = Column(DateTime(timezone=True), nullable=True)

    # 时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关系
    workspace = relationship("Workspace", back_populates="quotas")


class AgentMember(Base):
    """Per-agent admin membership."""

    __tablename__ = "agent_members"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(50), ForeignKey("agents.id"), nullable=False, index=True)
    admin_user_id = Column(
        Integer, ForeignKey("admin_users.id"), nullable=False, index=True
    )
    role = Column(String(50), default="admin", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    agent = relationship("Agent", back_populates="members")
    admin_user = relationship("AdminUser", back_populates="agent_members")

    __table_args__ = (
        UniqueConstraint("agent_id", "admin_user_id", name="uq_agent_member_admin"),
    )


class IndexJob(Base):
    """索引构建任务模型"""

    __tablename__ = "index_jobs"

    id = Column(
        String(50), primary_key=True, default=lambda: f"job_{uuid.uuid4().hex[:12]}"
    )
    agent_id = Column(String(50), ForeignKey("agents.id"), nullable=False, index=True)

    # 任务信息
    job_type = Column(
        SQLEnum("full", "incremental", "url_refetch", name="job_type"), nullable=False
    )
    status = Column(
        SQLEnum("queued", "running", "completed", "failed", name="job_status"),
        default="queued",
        index=True,
    )

    # 任务参数
    params = Column(JSON, nullable=True)  # {"url_ids": [...], "force": true}

    # 执行结果
    result = Column(JSON, nullable=True)  # {"chunks_indexed": 100, "errors": []}
    error_message = Column(Text, nullable=True)

    # 时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # 索引
    __table_args__ = (
        Index("ix_jobs_agent_status", "agent_id", "status"),
        Index("ix_jobs_created", "created_at"),
    )


class AdminUser(Base):
    """管理员用户模型（用于管理后台登录）"""

    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)
    role = Column(String(50), default="admin", nullable=False)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id"), nullable=True, index=True
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    workspace = relationship("Workspace", back_populates="admin_users")
    agent_members = relationship(
        "AgentMember", back_populates="admin_user", cascade="all, delete-orphan"
    )


class Tenant(Base):
    """Workspace 的计费/订阅 profile 壳 (M10 G2 起)。

    1:1 绑定到一个 Workspace (Tenant.workspace_id UNIQUE)。`plan` /
    `billing_email` 字段保留为 M11+ 计费功能占位,本 M10 不实现,代码库内 0 引用。
    """

    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # M10 G2: 1:1 Workspace (per M10-PROMPT.md §3.2 option B)
    workspace_id = Column(
        Integer,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    name = Column(String(100), nullable=False)  # 冗余 workspace.name 便于查询
    slug = Column(String(50), unique=True, nullable=False, index=True)
    plan = Column(String(20), nullable=False, default="free")  # M11+ 占位
    billing_email = Column(String(255), nullable=True)  # M11+ 占位
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    workspace = relationship("Workspace", back_populates="tenant")
    knowledge_bases = relationship(
        "KnowledgeBase", back_populates="tenant", cascade="all, delete-orphan"
    )


class KnowledgeBase(Base):
    """Workspace 级知识库 (M10 G2 后,不再 per-agent)。

    tenant_id 字段保留(向后兼容旧数据),但语义改为"workspace 的计费壳";
    新增 workspace_id 直接 FK 避免穿透 tenant。
    """

    __tablename__ = "knowledge_bases"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    # M10 G2: 直接 FK 到 workspace,避免总是要 JOIN tenants 表
    workspace_id = Column(
        Integer,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(100), nullable=False)
    embedding_model = Column(String(100), nullable=False, default="BAAI/bge-m3")
    embedding_base_url = Column(String(500), nullable=True)
    vector_backend = Column(String(20), nullable=False, default="qdrant")
    qdrant_collection = Column(String(50), unique=True, nullable=False, index=True)
    is_locked = Column(
        Boolean, nullable=False, default=False
    )  # 有 chunk 后锁定 embedding 配置
    chunk_size = Column(Integer, nullable=False, default=512)
    chunk_overlap = Column(Integer, nullable=False, default=64)
    status = Column(
        SQLEnum(
            "active",
            "resetting",
            "processing",
            "error",
            name="kb_status",
        ),
        default="active",
        nullable=False,
        index=True,
    )
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tenant = relationship("Tenant", back_populates="knowledge_bases")
    workspace = relationship("Workspace", back_populates="knowledge_bases")
    documents = relationship(
        "KbDocument", back_populates="knowledge_base", cascade="all, delete-orphan"
    )
    agents = relationship("Agent", back_populates="knowledge_base")


class KbDocument(Base):
    """文档表"""

    __tablename__ = "kb_documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    kb_id = Column(
        String(36), ForeignKey("knowledge_bases.id"), nullable=False, index=True
    )
    tenant_id = Column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )  # 冗余，方便过滤
    filename = Column(String(500), nullable=False)
    file_type = Column(String(20), nullable=True)
    status = Column(
        SQLEnum("pending", "processing", "ready", "error", name="kb_doc_status"),
        default="pending",
        index=True,
    )
    chunk_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    file_size = Column(Integer, nullable=True)
    storage_path = Column(String(1000), nullable=True)
    # Metadata for document source info (e.g., URL for crawled pages)
    metadata_json = Column(JSON, nullable=True, default=None)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    chunks = relationship(
        "KbChunk", back_populates="document", cascade="all, delete-orphan"
    )


class KbChunk(Base):
    """Chunk 元数据表"""

    __tablename__ = "kb_chunks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    kb_id = Column(
        String(36), ForeignKey("knowledge_bases.id"), nullable=False, index=True
    )
    doc_id = Column(
        String(36), ForeignKey("kb_documents.id"), nullable=False, index=True
    )
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    vector_id = Column(String(100), nullable=True, index=True)  # Qdrant point id
    chunk_index = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("KbDocument", back_populates="chunks")


class MessageAttachment(Base):
    """Multimodal attachment row (image / audio) attached to a chat turn (PR13).

    Two-phase lifecycle: rows are inserted on `POST /api/v1/chat/attachments` with
    `status="pending"`. The chat pipeline runs vision/Whisper service synchronously
    in `prepare_chat_request`, fills `description` (ocr_text) / `transcript`, and
    flips status to `processed` (or `failed` with `error_message`).
    FK `message_id` is back-filled in `persist_chat_response`.
    Bytes live on disk under ``{MEDIA_STORAGE_DIR}/{sha256[:2]}/{sha256}``.
    """

    __tablename__ = "message_attachments"

    id = Column(
        String(50), primary_key=True,
        default=lambda: f"att_{uuid.uuid4().hex[:12]}",
    )
    message_id = Column(
        Integer, ForeignKey("chat_messages.id"), nullable=True, index=True,
    )
    # session_id: Python-only attribute, NOT mapped to a DB column.
    # The column was removed from the DB in migration 6144374.
    # Code that needs session ownership should use message.session_id instead.
    # We use a simple instance attribute without any Column or Mapped[] annotation,
    # so SQLAlchemy never includes it in SQL.
    agent_id = Column(
        String(50), ForeignKey("agents.id"), nullable=False, index=True,
    )
    kind = Column(
        SQLEnum("image", "audio", name="attachment_kind"),
        nullable=False,
    )
    mime_type = Column(String(100), nullable=False)
    filename = Column(String(500), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    storage_backend = Column(String(20), nullable=False, default="local")
    storage_key = Column(String(200), nullable=False, unique=True)
    sha256 = Column(String(64), nullable=False, index=True)

    # Modality-specific outputs (filled in by vision/ASR services).
    # DB column is ocr_text (not description); mapped via column.
    transcript = Column(Text, nullable=True)        # audio
    description = Column("ocr_text", Text, nullable=True)  # image
    # duration_ms: Python-only (not a DB column — client-supplied, not stored)
    duration_ms = None

    # Lifecycle
    status = Column(
        SQLEnum(
            "pending", "processing", "processed", "failed",
            name="attachment_status",
        ),
        nullable=False, default="pending", index=True,
    )
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # session relationship removed: no session_id FK column exists
    # (session link is via message.chat_session, not a direct FK)
    agent = relationship("Agent")
    message = relationship("ChatMessage", foreign_keys=[message_id])

    __table_args__ = (
        Index("ix_msg_attach_sha256", "sha256"),
    )


class AuditLog(Base):
    """M11 PR2 — Dify provisioning 审计日志。

    用途: 记录 workspace 在 Dify 注册流程的关键操作(创建 tenant / 创建 account /
    重试 / 失败),便于事后回溯 + 安全审计。

    设计取舍:
      - BigInteger autoincrement pk: 单调递增,审计表只追加、不更新;
        避免 UUID 写入开销,便于范围扫描(latest N events per tenant)。
      - tenant_id 必填: 没有 tenant 上下文的 audit 行无意义。
      - actor_user_id 必填: 操作者,可追溯。值 = admins.id (Integer)。
      - dify_request_id 可空: 不是所有 audit 行都对应 Dify 一次 API 调用
        (例如本地校验失败),允许 NULL。
      - correlation_id 必填: 一次业务流程共享同一 correlation_id,
        便于把多条 audit 行串成一条 timeline。
      - status: 'success' / 'failed' (后续可扩 'pending' 但当前 PR 不需要)。
      - created_at: 应用层写时由 DB 默认 CURRENT_TIMESTAMP 填入,
        避免应用时间漂移。
    """

    __tablename__ = "audit_logs"

    # SQLite 仅 INTEGER PRIMARY KEY 是 rowid 别名(自动填充);BIGINT 在 SQLite
    # 是普通列,需要显式传值。用 with_variant 让 SQLite 走 INTEGER,Postgres
    # 保留 BIGSERIAL(autoincrement=True → SERIAL/BIGSERIAL)。
    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    tenant_id = Column(String(36), nullable=False)
    actor_user_id = Column(Integer, nullable=False)
    action = Column(String(64), nullable=False)
    dify_request_id = Column(String(36), nullable=True)
    correlation_id = Column(String(36), nullable=False)
    status = Column(String(20), nullable=False)  # 'success' / 'failed'
    error_detail = Column(Text, nullable=True)
    created_at = Column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "idx_audit_logs_tenant_id_created_at", "tenant_id", "created_at"
        ),
        Index("idx_audit_logs_correlation_id", "correlation_id"),
    )
