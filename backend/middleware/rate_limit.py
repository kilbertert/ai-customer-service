"""
API级速率限制中间件

支持两种模式：
1. Redis 分布式限流（生产环境）
2. 内存限流（开发/测试环境）
"""

from collections import defaultdict, deque
from functools import wraps
import logging
import time
from typing import Deque, Dict, Optional, Tuple

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from config import settings

logger = logging.getLogger(__name__)

PUBLIC_RATE_LIMIT_PATH_PREFIXES = (
    "/api/v1/chat",
    "/api/v1/contexts",
    "/api/v1/config:public",
)


def _append_vary_header(response: Response, value: str) -> None:
    """Append a value to the Vary header without duplicating it."""
    existing = response.headers.get("Vary")
    if not existing:
        response.headers["Vary"] = value
        return

    values = [item.strip() for item in existing.split(",") if item.strip()]
    if value not in values:
        response.headers["Vary"] = ", ".join([*values, value])


def apply_cors_headers(request: Request, response: Response) -> Response:
    """Apply CORS headers for early middleware responses that bypass CORSMiddleware."""
    origin = request.headers.get("origin")

    # No Origin header -> no CORS needed (non-browser/server-to-server requests)
    if origin is None or origin == "":
        return response

    # Handle Origin: null (e.g., file:// protocol) only if explicitly allowed
    if origin == "null":
        if settings.cors_allow_null_origin:
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = settings.allowed_methods
            response.headers["Access-Control-Allow-Headers"] = settings.allowed_headers
        return response

    allowed_origins = settings.cors_origins_list
    if "*" in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = settings.allowed_methods
        response.headers["Access-Control-Allow-Headers"] = settings.allowed_headers
        return response

    if origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = settings.allowed_methods
        response.headers["Access-Control-Allow-Headers"] = settings.allowed_headers
        _append_vary_header(response, "Origin")

    return response


def get_request_client_ip(request: Request) -> str:
    """Get the originating client IP, preferring the first forwarded IP."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        for candidate in forwarded.split(","):
            candidate = candidate.strip()
            if candidate:
                return candidate

    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        return real_ip.strip()

    if request.client and request.client.host:
        return request.client.host

    return "unknown"


def should_apply_rate_limit(request: Request) -> bool:
    """Apply rate limiting only to public client-facing endpoints."""
    if request.method == "OPTIONS":
        return False

    path = request.url.path
    return path.startswith(PUBLIC_RATE_LIMIT_PATH_PREFIXES)


def check_memory_sliding_window(
    history_map: Dict[str, Deque[float]],
    key: str,
    *,
    max_requests: int,
    window_seconds: int,
) -> Tuple[bool, int]:
    """Shared in-memory sliding-window limiter.

    Keeps only timestamps inside the window and returns remaining capacity.
    """
    now = time.time()
    history = history_map.get(key)
    if history is None:
        history = deque()
        history_map[key] = history

    while history and now - history[0] >= window_seconds:
        history.popleft()

    if not history:
        history_map.pop(key, None)
        history = deque()
        history_map[key] = history

    if len(history) >= max_requests:
        return False, 0

    history.append(now)
    remaining = max(0, max_requests - len(history))
    return True, remaining


# ── M11 PR3 — 端点级 IP+email 限速装饰器 ───────────────────────────────
# 复用上面的滑动窗口逻辑, 加一层 Redis 优先 + 内存兜底。专门用于注册/重置密码等
# 高敏感端点, 防止单一 IP 或邮箱暴力枚举。
_REGISTER_IP_HISTORY: Dict[str, Deque[float]] = defaultdict(deque)
_REGISTER_EMAIL_HISTORY: Dict[str, Deque[float]] = defaultdict(deque)


async def _check_endpoint_rate_limit(
    key: str,
    max_requests: int,
    window_seconds: int,
    history_map: Dict[str, Deque[float]],
) -> bool:
    """端点级限速。优先 Redis, 失败/不健康兜底内存滑动窗口。"""
    redis_healthy = False
    try:
        from services.redis_service import get_redis
        redis = await get_redis()
        if redis is not None and await redis.health_check():
            allowed, _ = await redis.check_rate_limit(
                key, max_requests=max_requests, window_seconds=window_seconds
            )
            redis_healthy = True
            return allowed
    except Exception as e:
        logger.debug("Redis endpoint rate-limit fallback to memory: %s", e)

    if redis_healthy:
        return True  # Redis 通了且没超限(刚拿到 allowed=True)

    allowed, _ = check_memory_sliding_window(
        history_map, key,
        max_requests=max_requests, window_seconds=window_seconds,
    )
    return allowed


def rate_limit_by_ip_and_email(
    ip_limit: int,
    email_limit: int,
    window_seconds: int,
):
    """端点装饰器: 同时限速 IP 和 email。

    Usage::

        @router.post("/register")
        @rate_limit_by_ip_and_email(ip_limit=5, email_limit=3, window_seconds=3600)
        async def register_tenant(req: TenantRegisterRequest, request: Request, ...): ...

    IP 来自 ``Request.client.host``(走 ``get_request_client_ip`` 兼容反向代理);
    email 优先从 kwargs 中的 Pydantic body 取 ``req.email``, 退一步从
    ``X-Tenant-Email`` header 取。
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request")
            if request is None:
                for a in args:
                    if isinstance(a, Request):
                        request = a
                        break
            if request is None:
                # 装饰器拿不到 Request: 降级放行, 不阻断业务
                return await func(*args, **kwargs)

            client_ip = get_request_client_ip(request)
            ip_key = f"ratelimit:register_ip:{client_ip}"
            if not await _check_endpoint_rate_limit(
                ip_key, ip_limit, window_seconds, _REGISTER_IP_HISTORY
            ):
                raise HTTPException(429, "Too many requests from this IP")

            email = ""
            for candidate_name in ("req", "payload", "data", "body"):
                body = kwargs.get(candidate_name)
                if body is not None and hasattr(body, "email"):
                    email = str(getattr(body, "email", "") or "")
                    if email:
                        break
            if not email:
                email = request.headers.get("X-Tenant-Email", "")
            if email:
                email_key = f"ratelimit:register_email:{email.lower()}"
                if not await _check_endpoint_rate_limit(
                    email_key, email_limit, window_seconds, _REGISTER_EMAIL_HISTORY
                ):
                    raise HTTPException(429, "Too many requests for this email")

            return await func(*args, **kwargs)
        return wrapper
    return decorator


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    速率限制中间件

    支持 Redis 分布式限流和内存限流两种模式
    """

    def __init__(
        self,
        app,
        requests_per_minute: int = 60,
        burst_size: int = 10,
        use_redis: bool = True,
    ):
        """
        初始化速率限制中间件

        Args:
            app: FastAPI应用实例
            requests_per_minute: 每分钟允许的最大请求数
            burst_size: 短时间内允许的突发请求数
            use_redis: 是否使用 Redis（生产环境推荐）
        """
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self.use_redis = use_redis

        # 内存限流的备用存储
        self.request_history: Dict[str, Deque[float]] = defaultdict(deque)
        self.burst_counters: Dict[str, int] = defaultdict(int)
        self.last_burst_reset: float = time.time()

        # Redis 服务（延迟初始化，按事件循环隔离）
        self._redis_service = None
        self._redis_loop_id: Optional[int] = None

    async def _get_redis(self):
        """获取 Redis 服务（延迟初始化）"""
        if not self.use_redis:
            return None

        try:
            import asyncio
            from services.redis_service import get_redis

            loop_id = id(asyncio.get_running_loop())
            if self._redis_service is None or self._redis_loop_id != loop_id:
                self._redis_service = await get_redis()
                self._redis_loop_id = loop_id
        except Exception as e:
            logger.warning(f"Redis not available, falling back to memory: {e}")
            self.use_redis = False
            self._redis_service = None
            self._redis_loop_id = None

        return self._redis_service

    async def dispatch(self, request: Request, call_next):
        """处理每个请求"""
        if not should_apply_rate_limit(request):
            return await call_next(request)

        client_ip = self._get_client_ip(request)

        # 检查速率限制
        allowed, remaining = await self._check_rate_limit(client_ip)

        if not allowed:
            logger.warning(f"Rate limit exceeded for IP: {client_ip}")
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": "请求过于频繁，请稍后再试",
                    "error": "rate_limit_exceeded",
                },
            )
            response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
            response.headers["X-RateLimit-Remaining"] = "0"
            return apply_cors_headers(request, response)

        # 处理请求
        response = await call_next(request)

        # 添加速率限制头
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端IP地址"""
        return get_request_client_ip(request)

    async def _check_rate_limit(self, ip: str) -> Tuple[bool, int]:
        """
        检查是否超过速率限制

        Args:
            ip: 客户端IP地址

        Returns:
            (是否允许, 剩余请求数)
        """
        # 尝试使用 Redis
        redis = await self._get_redis()
        if redis:
            try:
                key = f"rate:ip:{ip}"
                allowed, remaining = await redis.check_rate_limit(
                    key,
                    max_requests=self.requests_per_minute,
                    window_seconds=60,
                )
                return allowed, remaining
            except Exception as e:
                logger.warning(f"Redis rate limit error, falling back to memory: {e}")

        # 使用内存限流
        return self._check_memory_rate_limit(ip)

    def _check_memory_rate_limit(self, ip: str) -> Tuple[bool, int]:
        """
        内存限流（备用方案）

        Args:
            ip: 客户端IP地址

        Returns:
            (是否允许, 剩余请求数)
        """
        current_time = time.time()

        # 检查突发限制
        if current_time - self.last_burst_reset > 1:  # 每秒重置突发计数
            self.burst_counters.clear()
            self.last_burst_reset = current_time

        if self.burst_counters[ip] >= self.burst_size:
            logger.debug(f"Burst rate limit exceeded for IP: {ip}")
            return False, 0

        allowed, remaining = check_memory_sliding_window(
            self.request_history,
            ip,
            max_requests=self.requests_per_minute,
            window_seconds=60,
        )
        if not allowed:
            logger.debug(f"Minute rate limit exceeded for IP: {ip}")
            return False, 0

        self.burst_counters[ip] += 1
        return True, remaining
