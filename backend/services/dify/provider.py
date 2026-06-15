"""M10 PR4a — DifyProvider.

Per-agent Dify workflow invocation layer for the basjoo main backend.

职责:
- 接受 ``(workspace, agent, visitor_id)`` 并在调用 ``stream_chat`` 时透传
  ``session_public_id``
- 内部构造 ``DifyClient`` (frozen dataclass, 复用 services.dify.dify_client 现有契约)
- 实施 G1 双层 ``end_user`` 编码:
  ``agent-{aid}-v-{visitor_id}-s-{session_public_id}``
- 透传 ``SseProxyLayer.proxy()`` 的 SSE 字节产出,不做协议层改动
  (协议层 thinking strip / 事件映射属于 PR4b 范围, 本文件不做)

不做的事 (M10 §5.1 边界):
- 不改 ``Tenant.plan`` 字段 (M11+)
- 不实现 Plan A / Plan B 运行时切换 (M13+)
- 不触碰 ``llm_service.py`` 路由表 (DifyProvider 是平行代码路径, 不是路由分支)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from config import settings
from core.encryption import decrypt_api_key
from models import Agent, Workspace
from services.dify.dify_client import DifyClient
from services.dify.sse_proxy_layer import SseProxyLayer

logger = logging.getLogger(__name__)


# M10 §2.2 字符预算: 100 chars 上限 (Dify end_user 字段 256 chars, 留余量)
_END_USER_MAX_LEN = 100

# 单段最大字符数 (visitor_id / session_public_id), 避免 format overhead 撑爆
_END_USER_SEGMENT_MAX_LEN = 36

# Agent.dify_user_prefix 默认值 (M10 §4.2 锁定 'agent-')
_DEFAULT_USER_PREFIX = "agent-"

# Dify workflow '开始' 节点 inputs / '结束' 节点 output 的默认变量名。
# 这些是 M2 阶段锁定的 Dify workflow 通用契约, 不做运行时可配 (留 M13+ UI 改造)。
_DIFY_INPUT_TEXT = "input_text"
_DIFY_INPUT_LANGUAGE = "language"
_DIFY_OUTPUT_TEXT = "output"

# Visitor 兜底: 当 ChatSession.visitor_id 为 None 时使用此值 (M10 PR4a 硬门 1)
_ANON_VISITOR = "anon"

# SSE event type name used by SseProxyLayer to carry the final reply text
_MESSAGE_COMPLETE_EVENT = "message_complete"


@dataclass(frozen=True)
class DifyProvider:
    """Per-call Dify 集成层。

    构造期完成 ``DifyClient`` 装配, ``stream_chat`` 调用期再注入 per-call 参数
    (text / language / file_ids / session_public_id), 内部走 ``SseProxyLayer``
    产出与 basjoo widget ``difyStream.ts`` 兼容的 SSE 字节流。

    校验失败 (无 api_base / 无 api_key) 在 ``__post_init__`` 阶段 fail-fast,
    不延迟到流开始再报错 — 避免 HTTP 200 但流挂死 / 静默失败。
    """

    workspace: Workspace
    agent: Agent
    visitor_id: Optional[str]

    def __post_init__(self) -> None:
        api_base = self.workspace.dify_api_base or settings.dify_api_base
        if not api_base:
            raise ValueError(
                "DifyProvider: neither workspace.dify_api_base nor "
                "settings.dify_api_base is configured (Plan B global default missing). "
                "Set DIFY_API_BASE in .env or workspace admin UI."
            )

        api_key = self._resolve_api_key()
        if not api_key:
            raise ValueError(
                "DifyProvider: no Dify API key resolved from workspace.dify_api_key "
                "(decrypted) or settings.dify_api_key. Configure at least one."
            )

        if not self.agent.dify_workflow_id:
            raise ValueError(
                "DifyProvider: agent.dify_workflow_id is empty. "
                "Bind an agent to a Dify workflow before invoking stream_chat()."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        *,
        text: str,
        language: Optional[str],
        file_ids: list[str] | None = None,
        session_public_id: str,
    ) -> AsyncIterator[bytes]:
        """主入口: 调用 Dify workflow, 产出 H5 SSE 字节流。

        Args:
            text: 用户消息文本 (PR13 multimodal 折叠后)
            language: locale 字符串 (e.g. "zh-CN"), 透传到 Dify workflow
            file_ids: 已上传的 MessageAttachment.id 列表 (Dify upload_file_id 数组)
            session_public_id: ChatSession.session_id (C 端公开 ID, 非 DB 主键)

        Yields:
            SSE 字节块, 与 basjoo widget ``difyStream.ts`` 契约一致:
            ``session_started`` / ``message_delta`` / ``message_complete`` /
            ``error`` / ``end``。
        """
        inputs = self._build_inputs(text=text, language=language, file_ids=file_ids)
        end_user = self._build_end_user(
            agent=self.agent,
            visitor_id=self.visitor_id,
            session_public_id=session_public_id,
        )

        client = self._build_dify_client(end_user=end_user)
        proxy = SseProxyLayer(client)

        logger.info(
            "DifyProvider.stream_chat agent_id=%s workflow_id=%s end_user_len=%d",
            self.agent.id,
            self.agent.dify_workflow_id,
            len(end_user),
        )

        async for chunk in proxy.proxy(inputs=inputs, end_user=end_user):
            yield chunk

    # ------------------------------------------------------------------
    # G1 end_user 编码 (M10 §2.2 锁定)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_end_user(
        *,
        agent: Agent,
        visitor_id: Optional[str],
        session_public_id: str,
    ) -> str:
        """实施 G1 双层编码: ``agent-{aid}-v-{visitor_id}-s-{session_public_id}``.

        行为:
        - ``dify_end_user_strategy == 'dual_layer'`` (默认): 完整三段, visitor_id 为
          None 时兜底为 'anon' (M10 PR4a 硬门 1 case 2)
        - ``dify_end_user_strategy == 'agent'``: 仅 ``agent-{aid}`` (M3 旧版兼容, deprecated)
        - ``dify_end_user_strategy == 'visitor'``: ``agent-{aid}-v-{visitor_id}``
          (无 session 粒度, 适用于无状态场景)
        - 未知 strategy: 退化为 dual_layer (防御性)

        字符预算:
        - 总长 > ``_END_USER_MAX_LEN`` (100) 时, 截断 visitor_id / session_public_id
          至 ``_END_USER_SEGMENT_MAX_LEN`` (36) 字符, 保留格式有效
        """
        strategy = (agent.dify_end_user_strategy or "dual_layer").strip().lower()
        prefix = (agent.dify_user_prefix or _DEFAULT_USER_PREFIX).strip()
        aid = agent.id

        if strategy == "agent":
            return f"{prefix}{aid}"

        if strategy == "visitor":
            vid = _segment_or_anon(visitor_id)
            return f"{prefix}{aid}-v-{vid}"

        # dual_layer (默认) + 未知 strategy 退化
        vid = _segment_or_anon(visitor_id)
        sid = _segment_or_truncate(session_public_id)
        candidate = f"{prefix}{aid}-v-{vid}-s-{sid}"

        if len(candidate) <= _END_USER_MAX_LEN:
            return candidate

        # 超长截断: visitor_id 和 session_public_id 各 cap 到 _END_USER_SEGMENT_MAX_LEN
        vid_capped = _segment_or_truncate(visitor_id, fallback=_ANON_VISITOR)
        sid_capped = _segment_or_truncate(session_public_id)
        return f"{prefix}{aid}-v-{vid_capped}-s-{sid_capped}"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_api_key(self) -> str:
        """按 workspace → settings 优先级解析 Dify API key。

        workspace.dify_api_key 是 Fernet 加密存储 (PR2-3 引入), 需要解密;
        settings.dify_api_key 是明文环境变量 (Plan B 全局默认)。
        """
        if self.workspace.dify_api_key:
            decrypted = decrypt_api_key(self.workspace.dify_api_key)
            if decrypted:
                return decrypted
            logger.warning(
                "DifyProvider: workspace.dify_api_key present but failed to decrypt; "
                "falling back to settings.dify_api_key"
            )
        return settings.dify_api_key or ""

    def _build_dify_client(self, *, end_user: str) -> DifyClient:
        """构造 ``DifyClient`` (frozen dataclass)。

        ``end_user`` 字段填入 G1 编码结果, 但 ``run_workflow_stream`` 在调用时
        会用 per-call ``end_user`` 参数覆盖 (DifyClient frozen dataclass 仅作
        兜底默认值)。
        """
        api_base = self.workspace.dify_api_base or settings.dify_api_base
        api_key = self._resolve_api_key()
        return DifyClient(api_base=api_base, api_key=api_key, end_user=end_user)

    def _build_inputs(
        self,
        *,
        text: str,
        language: Optional[str],
        file_ids: list[str] | None,
    ) -> dict[str, Any]:
        """构造 Dify workflow '开始' 节点 inputs 字典。

        字段命名按 M2 锁定: input_text / language. file_ids 暂未透传
        (Dify file-list inputs 的 protocol 在 PR3 落地的 response_parser.py
        里, M10 PR4a 范围不含 file 上传链路)。
        """
        inputs: dict[str, Any] = {_DIFY_INPUT_TEXT: text}
        if language:
            inputs[_DIFY_INPUT_LANGUAGE] = language
        # file_ids 留作 M10+ 扩展 (PR3 response_parser 落地后再接)
        _ = file_ids  # suppress unused-arg linter, 接口保留
        return inputs


# ============== Helpers ==============


def _segment_or_anon(visitor_id: Optional[str]) -> str:
    """visitor_id 兜底: None / 空字符串 → 'anon'."""
    if not visitor_id:
        return _ANON_VISITOR
    return visitor_id


def _segment_or_truncate(value: Optional[str], *, fallback: str = "") -> str:
    """value 兜底 + 截断到 _END_USER_SEGMENT_MAX_LEN."""
    if not value:
        return fallback
    if len(value) <= _END_USER_SEGMENT_MAX_LEN:
        return value
    return value[:_END_USER_SEGMENT_MAX_LEN]


# ============== SSE byte helpers ==============


def extract_message_complete_text(chunk: bytes) -> Optional[str]:
    """从 SseProxyLayer 产出的单块 SSE 字节中提取 ``message_complete.text``.

    SseProxyLayer 一次 yield 一个事件对应一块字节 (e.g.
    ``b'event: message_complete\\ndata: {"text":"...","total_tokens":N}\\n\\n'``),
    所以按"单 chunk = 单事件"的最小假设即可。

    Returns:
        解出的 text 字符串;若 chunk 不是 message_complete 事件或解析失败 → None。

    Used by:
        ``backend.api.v1.endpoints.chat_stream`` Phase 3 持久化前,需要把
        Dify 流式产出的最终回复作为 ``reply`` 写入 ChatMessage.content。
    """
    needle = f"event: {_MESSAGE_COMPLETE_EVENT}".encode("utf-8")
    if needle not in chunk:
        return None
    try:
        text = chunk.decode("utf-8")
    except UnicodeDecodeError:
        return None
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            payload = json.loads(line[len("data: "):])
        except json.JSONDecodeError:
            return None
        value = payload.get("text")
        return value if isinstance(value, str) else None
    return None
