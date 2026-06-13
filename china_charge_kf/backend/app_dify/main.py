from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app_dify.config import settings
from app_dify.dify_client import DifyClient, DifyError, DifyUpstreamError
from app_dify.response_parser import extract_assistant_text
from app_dify.schemas import ChatResponse
from app_dify.sse_proxy_layer import SseProxyLayer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("app_dify")

app = FastAPI(
    title="China Charge - Dify H5 Chat Backend",
    version="0.2.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== 共享 helpers (M4 streaming 端点) ==============

_MAX_ERROR_MESSAGE = 200  # 与 SseProxyLayer._MAX_ERROR_MESSAGE 对齐 (PR8 §6.5 H3)


def _sse_bytes(event: str, data: dict[str, Any]) -> bytes:
    """生成单个 SSE 事件字节（`event: <name>\\ndata: <json>\\n\\n`）。

    与 `SseProxyLayer._sse_event` 同形（ensure_ascii=False + UTF-8）。
    独立实现避免 import M3 私有符号；语义对齐靠 `test_sse_proxy_layer` 锁定。
    """
    return (
        f"event: {event}\n"
        f"data: {json.dumps(data, ensure_ascii=False)}\n"
        "\n"
    ).encode("utf-8")


def _truncate_error(message: str, max_len: int = _MAX_ERROR_MESSAGE) -> str:
    """截断错误消息到 ≤ max_len 字符（H3 — 与 SseProxyLayer._truncate_error_message 对齐）。"""
    if len(message) <= max_len:
        return message
    return message[:max_len] + "..."


# ============== M4 Schemas ==============

class ChatStreamRequest(BaseModel):
    """M4 streaming chat 入参契约。

    - text 必填,长度 1-2000 (匹配 v2 workflow input_text.max_length=2000)
    - end_user 缺省走 settings.dify_end_user
    - language 缺省不传 (Dify workflow language 槽保持空)
    - file_ids 列表: 元素是已通过 /api/files/upload 上传得到的 Dify file UUID
      (端点**不**触发 upload_file 调用,直接构造 file-ref 数组)
    """
    text: str = Field(..., min_length=1, max_length=2000)
    end_user: Optional[str] = None
    language: Optional[str] = None
    file_ids: list[str] = Field(default_factory=list)


class FileUploadResponse(BaseModel):
    file_id: str


# ============== Endpoints ==============

@app.get("/api/health")
async def health() -> dict:
    """详细健康检查（legacy 路径, 保留以兼容旧前端 / k8s probe）。"""
    return {
        "ok": True,
        "backend": "dify",
        "api_base": settings.dify_api_base,
        "end_user": settings.dify_end_user,
    }


@app.get("/health")
async def health_simple() -> dict:
    """M4 简洁 liveness probe（per brief）: 200 + `{"status": "ok"}`, 不触发 Dify 调用。"""
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    text: str = Form(""),
    image: Optional[UploadFile] = File(default=None),
    audio: Optional[UploadFile] = File(default=None),
    language: str = Form("中文"),
) -> ChatResponse:
    """Legacy 阻塞式 chat 端点 (v1 workflow, 保留向后兼容)。

    仍走 v1 API key (settings.dify_api_key)。
    """
    client = DifyClient(
        api_base=settings.dify_api_base,
        api_key=settings.dify_api_key,
        end_user=settings.dify_end_user,
    )

    image_id: Optional[str] = None
    if image is not None:
        content = await image.read()
        if content:
            try:
                image_id = await client.upload_file(
                    filename=image.filename or "image",
                    content=content,
                    content_type=image.content_type or "image/jpeg",
                )
                log.info("Uploaded image to Dify: file_id=%s size=%d", image_id, len(content))
            except DifyError as e:
                return ChatResponse(
                    assistant_text=f"[DifyError:image_upload] {e}",
                    image_id=None,
                    audio_id=None,
                    raw=None,
                )

    audio_id: Optional[str] = None
    if audio is not None:
        content = await audio.read()
        if content:
            ctype = _sniff_audio_type(audio.filename or "", audio.content_type)
            try:
                audio_id = await client.upload_file(
                    filename=audio.filename or "audio.wav",
                    content=content,
                    content_type=ctype,
                )
                log.info(
                    "Uploaded audio to Dify: file_id=%s size=%d ctype=%s",
                    audio_id, len(content), ctype,
                )
            except DifyError as e:
                return ChatResponse(
                    assistant_text=f"[DifyError:audio_upload] {e}",
                    image_id=image_id,
                    audio_id=None,
                    raw=None,
                )

    # ---- Build workflow inputs ----
    # Dify workflow 文件型输入必须是数组,即使只有一个文件
    inputs: dict = {
        settings.dify_input_text: text or "",
        settings.dify_input_language: language,
    }
    if image_id:
        inputs[settings.dify_input_image] = [client.file_ref(image_id, "image")]
    if audio_id:
        inputs[settings.dify_input_audio] = [client.file_ref(audio_id, "audio")]

    log.info("Dify workflow inputs keys=%s", list(inputs.keys()))

    # ---- Run workflow ----
    try:
        raw = await client.run_workflow(inputs=inputs, response_mode="blocking")
    except DifyError as e:
        log.error("Dify workflow error: %s", e)
        return ChatResponse(
            assistant_text=f"[DifyError:workflow] {e}",
            image_id=image_id,
            audio_id=audio_id,
            raw=None,
        )

    assistant_text = extract_assistant_text(raw, preferred_key=settings.dify_output_text)
    return ChatResponse(
        assistant_text=assistant_text,
        image_id=image_id,
        audio_id=audio_id,
        raw=raw,
    )


# ============== M4 Streaming endpoint ==============

def _build_dify_client() -> DifyClient:
    """构造 M4 streaming / upload 端点共用的 DifyClient (走 v2 API key)。"""
    return DifyClient(
        api_base=settings.dify_api_base,
        api_key=settings.dify_v2_api_key,
        end_user=settings.dify_end_user,
    )


def _build_stream_inputs(req: ChatStreamRequest, client: DifyClient) -> dict[str, Any]:
    """组装 Dify workflow inputs。

    - input_text 必填
    - language 可选 (None → 不写入 inputs, Dify workflow 槽保持空)
    - file_ids 全部按 image 类型打包到 input_img_id (v2 workflow file-list 槽)。
      原因: H5 widget 上传即用图, 而 v2 workflow 的 input_img_id 是唯一 image 槽;
      audio 走 multipart blocking 端点 (/api/chat) 走 input_audio_id, 保持分离。
      file_ref 锁定签名见 M2 (PR10)。
    """
    inputs: dict[str, Any] = {
        settings.dify_input_text: req.text,
    }
    if req.language is not None:
        inputs[settings.dify_input_language] = req.language
    if req.file_ids:
        inputs[settings.dify_input_image] = [
            client.file_ref(fid, "image") for fid in req.file_ids
        ]
    return inputs


@app.post("/api/chat/stream")
async def chat_stream(req: ChatStreamRequest) -> StreamingResponse:
    """M4 SSE 流式 chat 端点 (v2 workflow)。

    错误处理分工:
    - SseProxyLayer.proxy() 已自行捕获 DifyAuthError / DifyBadRequestError /
      DifyUpstreamError / 其它 DifyError 并 yield error + end 字节;
      端点层**不重复 catch**。
    - 例外: 0-事件空流 (Dify 200 + 空 body) 时 proxy() **raise** DifyUpstreamError
      而非 yield (M3 Review #1 防御)。本端点必须 catch 这个 raise 并转 SSE bytes,
      否则 H5 widget 会 hang 死。
    """
    client = _build_dify_client()
    proxy = SseProxyLayer(client)
    inputs = _build_stream_inputs(req, client)
    end_user = req.end_user or settings.dify_end_user

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in proxy.proxy(inputs=inputs, end_user=end_user):
                yield chunk
        except DifyUpstreamError as e:
            # 0-事件空流防御 — 翻译 raise 为 SSE bytes
            log.warning("Dify stream produced no events: %s", e)
            yield _sse_bytes("error", {
                "code": "DIFY_UPSTREAM",
                "message": _truncate_error(str(e)),
            })
            yield _sse_bytes("end", {})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲, 让 SSE 实时推送
            "Connection": "keep-alive",
        },
    )


@app.post("/api/files/upload", response_model=FileUploadResponse)
async def upload_file(file: UploadFile = File(...)) -> FileUploadResponse:
    """M4 辅助端点: 上传文件到 Dify, 返回 file_id 用于 /api/chat/stream 的 file_ids 字段。

    走 v2 API key (与 streaming 端点一致)。前端两步流程:
        1) POST /api/files/upload  → {"file_id": "<uuid>"}
        2) POST /api/chat/stream  {"text": "...", "file_ids": ["<uuid>"]}
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")

    client = _build_dify_client()
    file_id = await client.upload_file(
        filename=file.filename or "upload",
        content=content,
        content_type=file.content_type or "application/octet-stream",
    )
    log.info("Uploaded file to Dify: file_id=%s filename=%s size=%d",
             file_id, file.filename, len(content))
    return FileUploadResponse(file_id=file_id)


# ============== Legacy helpers (Coze-era /api/chat blocking) ==============

def _sniff_audio_type(filename: str, declared: str | None) -> str:
    """Normalize audio MIME type for Dify upload (Dify accepts wav/mp3/m4a/webm)."""
    name = (filename or "").lower()
    if name.endswith(".wav"):
        return "audio/wav"
    if name.endswith(".mp3"):
        return "audio/mpeg"
    if name.endswith(".m4a"):
        return "audio/mp4"
    if name.endswith(".webm"):
        return "audio/webm"
    if name.endswith(".ogg") or name.endswith(".oga"):
        return "audio/ogg"
    if name.endswith(".mp4"):
        return "audio/mp4"
    return declared or "audio/wav"
