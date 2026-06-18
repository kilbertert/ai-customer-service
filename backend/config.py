import logging
import secrets
import stat
import uuid
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

INSECURE_SECRET_VALUES = {
    "",
    "change-me-in-production",
    "your-secret-key-change-in-production",
    "dev-secret-key",
}

DEFAULT_AGENT_ID_FILE = "/app/data/.agent_id"
DEFAULT_AGENT_MAX_TOKENS = 1024
DEFAULT_AGENT_SIMILARITY_THRESHOLD = 0.01  # KB hybrid search scores; default 10% (0.01)


def _is_missing_or_insecure_secret(value: str | None) -> bool:
    normalized = (value or "").strip()
    return not normalized or normalized in INSECURE_SECRET_VALUES


def _load_secret_key_from_file(secret_key_file: str) -> str | None:
    try:
        path = Path(secret_key_file)
        if not path.exists():
            return None

        secret_key = path.read_text(encoding="utf-8").strip()
        return secret_key or None
    except Exception as exc:
        logger.warning("Failed to load secret key from %s: %s", secret_key_file, exc)
        return None


def _generate_and_save_secret_key(secret_key_file: str) -> str:
    secret_key = secrets.token_urlsafe(32)
    path = Path(secret_key_file)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secret_key, encoding="utf-8")
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        logger.info("Generated SECRET_KEY file at %s", secret_key_file)
    except Exception as exc:
        logger.warning(
            "Failed to persist generated SECRET_KEY to %s: %s. Using an in-memory fallback.",
            secret_key_file,
            exc,
        )

    return secret_key


def _is_valid_agent_id(value: str | None) -> bool:
    normalized = (value or "").strip()
    if not normalized.startswith("agt_"):
        return False
    suffix = normalized[4:]
    return len(suffix) == 12 and all(char in "0123456789abcdef" for char in suffix)


def _load_agent_id_from_file(agent_id_file: str) -> str | None:
    try:
        path = Path(agent_id_file)
        if not path.exists():
            return None

        agent_id = path.read_text(encoding="utf-8").strip()
        return agent_id if _is_valid_agent_id(agent_id) else None
    except Exception as exc:
        logger.warning("Failed to load agent id from %s: %s", agent_id_file, exc)
        return None


def _save_agent_id(agent_id_file: str, agent_id: str) -> None:
    path = Path(agent_id_file)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(agent_id, encoding="utf-8")
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception as exc:
        logger.warning(
            "Failed to persist agent id to %s: %s.",
            agent_id_file,
            exc,
        )


def _generate_and_save_agent_id(agent_id_file: str) -> str:
    agent_id = f"agt_{uuid.uuid4().hex[:12]}"
    _save_agent_id(agent_id_file, agent_id)
    logger.info("Generated default agent id file at %s", agent_id_file)
    return agent_id


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="allow",
    )

    # DeepSeek API (optional - can be set per-agent in dashboard)
    deepseek_api_key: str = ""

    # Jina Embedding API
    jina_embedding_api_base: str = "https://api.jina.ai/v1/embeddings"

    # Scrapling 微服务
    scrapling_service_url: str = "http://scrapling-service:8001"
    scraping_provider: str = "local_scrapling"
    cloud_scraping_api_url: str = ""
    cloud_scraping_api_key: str = ""
    scraping_timeout_seconds: int = 60
    scraping_agent_concurrency: int = 2
    scraping_workspace_concurrency: int = 6
    scraping_fallback_to_cloud: bool = False

    # 数据库 - SQLite (轻量级MVP方案)
    database_url: str = "sqlite:///./data/basjoo.db"

    # Redis 配置
    redis_url: str = "redis://redis:6379/0"
    redis_cache_ttl: int = 3600  # 缓存过期时间（秒）
    redis_rate_limit_ttl: int = 60  # 限流窗口（秒）

    # Qdrant 向量数据库配置
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_timeout: float = 30.0

    # JWT 认证
    secret_key: str = ""
    secret_key_file: str = "/app/data/.secret_key"
    default_agent_id: str = ""
    agent_id_file: str = DEFAULT_AGENT_ID_FILE
    create_default_agent_on_bootstrap: bool = False
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # LLM / Embedding reliability
    llm_test_timeout_seconds: int = 10
    llm_retry_attempts: int = 3
    llm_retry_base_delay_seconds: float = 1.0
    llm_retry_max_delay_seconds: float = 8.0
    embedding_cache_max_entries: int = 1000
    embedding_cache_trim_count: int = 200

    # M10 G3 — Dify 集成层 Plan B 全局默认 (1 basjoo workspace = 1 Dify workspace 共享)
    # 工作空间级别覆盖: workspace.dify_api_base / workspace.dify_api_key (Fernet 加密)
    # 空字符串 = 未配置,DifyProvider 在 runtime 校验失败时立刻 raise
    dify_api_base: str = ""
    dify_api_key: str = ""

    # M11 PR3 — 系统级 Dify super-admin 凭据,用于租户 provisioning 阶段。
    # 设计原因: provisioning 发生在 workspace 还没有 Dify 凭据之前 (chicken-and-egg),
    # 因此必须有一个系统全局的 Dify 超级管理员用于创建新 workspace。
    # 与 workspace 级别的 dify_admin_email/dify_admin_password_ref (M10+2) 是两个层:
    # - 系统级 = basjoo 平台管理员 (启动期配置, 用来"建 workspace")
    # - workspace 级 = workspace 自己的 owner (workspace 创建后, 用来"管 workspace")
    # 留空 → DifyTenantProvisioner 在构造时 fail-fast 抛 DifyConfigError,
    # /api/v1/tenants/register 返回 503 而不是 500
    dify_admin_email: str = ""
    dify_admin_password: str = ""
    # M11 PR1 fork — Bearer ADMIN_API_KEY (Dify .env 配的 ADMIN_API_KEY)
    # 用于 /console/api/admin/workspaces/* 的 @admin_required 装饰器校验
    # 与 dify_admin_email/dify_admin_password 二选一(优先 Bearer)
    dify_admin_api_key: str = ""
    # M11 PR1 fork — Dify admin base URL (与 dify_api_base /v1 后缀不兼容, 单独配)
    # 例: http://162.211.183.169  (无 /v1)
    # 留空 → fallback 到 dify_api_base (legacy)
    dify_admin_api_base: str = ""

    # M11+ P0-C PR 2 (D8 决策) — Dify PostgreSQL 直连 DSN, 供 services/dify_toolkit/db.py
    # 走 psycopg2 直连(干掉原 SSH + docker inspect 拿凭据的链路)。
    # 默认指向 docker-compose 共用 postgres service, ops 切凭据走 Vault 不动代码。
    # 多 DB 场景(Dify Cloud 模式 / per-tenant DB)→ 留 P1+,D9 决策已为 per-tenant 留位
    dify_db_url: str = "postgresql://postgres:postgres@postgres:5432/dify"

    # Multimodal chat (PR13) — image captioning + voice transcription
    media_storage_dir: str = "/app/data/attachments"
    vision_api_key: str = ""
    vision_base_url: str = "https://api.openai.com/v1"
    vision_model: str = "gpt-4o"
    whisper_api_key: str = ""
    whisper_base_url: str = "https://api.openai.com/v1"
    whisper_model: str = "whisper-1"

    # CORS 配置
    # 生产环境建议配置具体域名，例如 "https://example.com,https://app.example.com"
    # 使用 * 允许所有来源，适用于公开的无凭证接口
    allowed_origins: str = "*"
    allowed_methods: str = "GET,POST,PUT,DELETE,OPTIONS"
    allowed_headers: str = "Content-Type,Authorization,X-Requested-With,Accept"

    # Whether to allow wildcard CORS for Origin: null (e.g., file:// widget preview).
    # Off by default; enable explicitly in dev environments.
    cors_allow_null_origin: bool = False

    # 应用
    app_name: str = "Basjoo"
    app_port: int = 8000

    # 限流
    default_rate_limit: int = 100
    rate_limit_per_minute: int = 1000
    rate_limit_burst_size: int = 200

    # Login rate limit
    login_rate_limit_max_attempts: int = 5
    login_rate_limit_window_seconds: int = 300

    # M11 PR3 — B 端租户自助注册
    dify_tenant_provision_enabled: bool = True
    tenant_signup_ip_rate_limit: int = 5
    tenant_signup_email_rate_limit: int = 3
    tenant_signup_rate_limit_window_seconds: int = 3600
    tenant_provisioning_max_attempts: int = 3
    tenant_provisioning_retry_interval_seconds: int = 300

    # 日志
    log_level: str = "info"

    def model_post_init(self, __context) -> None:
        secret_key_file = self.secret_key_file.strip() or "/app/data/.secret_key"
        object.__setattr__(self, "secret_key_file", secret_key_file)

        agent_id_file = self.agent_id_file.strip() or DEFAULT_AGENT_ID_FILE
        object.__setattr__(self, "agent_id_file", agent_id_file)

        if not self.allowed_origins.strip():
            # No wildcard by default — deployments must explicitly set ALLOWED_ORIGINS.
            object.__setattr__(self, "allowed_origins", "")

        if not self.allowed_methods.strip():
            object.__setattr__(self, "allowed_methods", "GET,POST,PUT,DELETE,OPTIONS")

        if not self.allowed_headers.strip():
            object.__setattr__(
                self,
                "allowed_headers",
                "Content-Type,Authorization,X-Requested-With,Accept",
            )

        if _is_missing_or_insecure_secret(self.secret_key):
            resolved_secret = _load_secret_key_from_file(secret_key_file)
            if not resolved_secret:
                resolved_secret = _generate_and_save_secret_key(secret_key_file)
            object.__setattr__(self, "secret_key", resolved_secret)

        resolved_agent_id = self.default_agent_id.strip()
        if resolved_agent_id and not _is_valid_agent_id(resolved_agent_id):
            logger.warning(
                "Ignoring invalid DEFAULT_AGENT_ID %r. Expected format agt_<12 lowercase hex chars>.",
                resolved_agent_id,
            )
            resolved_agent_id = ""

        if resolved_agent_id:
            _save_agent_id(agent_id_file, resolved_agent_id)
        else:
            file_agent_id = _load_agent_id_from_file(agent_id_file)
            if file_agent_id:
                resolved_agent_id = file_agent_id
            else:
                resolved_agent_id = _generate_and_save_agent_id(agent_id_file)

        object.__setattr__(self, "default_agent_id", resolved_agent_id)

    @property
    def cors_origins_list(self) -> list[str]:
        """将逗号分隔的字符串转换为列表"""
        return [
            origin.strip()
            for origin in self.allowed_origins.split(",")
            if origin.strip()
        ]

    @property
    def cors_methods_list(self) -> list[str]:
        """将逗号分隔的HTTP方法转换为列表"""
        methods = [
            method.strip()
            for method in self.allowed_methods.split(",")
            if method.strip()
        ]
        return methods or ["GET", "POST", "PUT", "DELETE", "OPTIONS"]

    @property
    def cors_headers_list(self) -> list[str]:
        """将逗号分隔的请求头转换为列表"""
        headers = [
            header.strip()
            for header in self.allowed_headers.split(",")
            if header.strip()
        ]
        return headers or [
            "Content-Type",
            "Authorization",
            "X-Requested-With",
            "Accept",
        ]


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()


# ── Multimodal chat (PR13) ─────────────────────────────────────────────────
MAX_IMAGE_BYTES: int = 5 * 1024 * 1024            # 5 MB / image
MAX_AUDIO_BYTES: int = 3 * 1024 * 1024            # 3 MB / audio (60s Opus ≪ 3 MB)
MAX_ATTACHMENTS_PER_MESSAGE: int = 3              # D4 cap
MAX_AUDIO_DURATION_MS: int = 60_000              # 60 s

ALLOWED_IMAGE_MIME: frozenset[str] = frozenset({
    "image/jpeg", "image/png", "image/webp",
})
ALLOWED_AUDIO_MIME: frozenset[str] = frozenset({
    "audio/webm", "audio/ogg", "audio/wav", "audio/mpeg", "audio/mp4",
})

# Public id regex for MessageAttachment rows (matches models.py default).
ATTACHMENT_ID_PATTERN: str = r"^att_[0-9a-f]{12}$"
