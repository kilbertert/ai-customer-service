from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.config import settings
from app.coze_client import CozeClient, CozeError
from app.schemas import ChatResponse

app = FastAPI(
    title="China Charge - H5 Chat Backend",
    version="0.1.0",
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


def _dig_first_text(value: object, *, depth: int = 0) -> str | None:
    if depth >= 10:
        return None

    if isinstance(value, str):
        s = value.strip()
        return s or None

    if isinstance(value, dict):
        # Most common keys from Coze responses
        for k in ("output", "answer", "result", "text", "message", "content"):
            if k in value:
                found = _dig_first_text(value.get(k), depth=depth + 1)
                if found:
                    return found

        # Also try "data" wrapper
        if "data" in value:
            found = _dig_first_text(value.get("data"), depth=depth + 1)
            if found:
                return found

        # Fallback: scan values (stable order) to find first string deep inside
        for v in value.values():
            found = _dig_first_text(v, depth=depth + 1)
            if found:
                return found
        return None

    if isinstance(value, list):
        for item in value:
            found = _dig_first_text(item, depth=depth + 1)
            if found:
                return found
        return None

    return None


def _extract_assistant_text(raw: dict) -> str:
    """
    Coze workflow response格式不固定，这里尽最大努力只抽取“最终文本”。
    如果实在找不到，就返回可读的 JSON 字符串（用于排障）。
    """
    found = _dig_first_text(raw)
    if found:
        # 有些工作流会把 {"output":"..."} 序列化成字符串返回，这里再尝试一次 JSON 解析
        s = found.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                import json

                parsed = json.loads(s)
                inner = _dig_first_text(parsed)
                if inner:
                    return inner
            except Exception:
                pass
        return found

    try:
        import json

        return json.dumps(raw, ensure_ascii=False, indent=2)
    except Exception:
        return str(raw)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    # 仅用于避免浏览器自动请求导致 404 日志；如需真正图标可替换为静态文件服务
    return Response(status_code=204)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    text: str = Form(""),
    image: Optional[UploadFile] = File(default=None),
    audio: Optional[UploadFile] = File(default=None),
    language: str = Form("中文"),
) -> ChatResponse:
    client = CozeClient(api_base=settings.coze_api_base, token=settings.coze_api_token)

    image_id: Optional[str] = None
    if image is not None:
        content = await image.read()
        if not content:
            image_id = None
        else:
            image_id = await client.upload_file(
                filename=image.filename or "image",
                content=content,
                content_type=image.content_type,
            )

    audio_id: Optional[str] = None
    if audio is not None:
        content = await audio.read()
        print(f"Audio received: filename={audio.filename}, content_type={audio.content_type}, size={len(content) if content else 0}")
        # 打印文件前几个字节用于调试
        if content and len(content) > 12:
            header = content[:12]
            print(f"Audio file header (hex): {header.hex()}")
        if not content:
            audio_id = None
        else:
            # 使用用户上传的文件名和 content_type
            content_type = audio.content_type or "audio/wav"
            filename = audio.filename or "audio.wav"
            # 根据文件名推断 content_type
            if filename.endswith('.wav'):
                content_type = 'audio/wav'
            elif filename.endswith('.mp3'):
                content_type = 'audio/mpeg'
            elif filename.endswith('.m4a'):
                content_type = 'audio/mp4'
            print(f"Uploading to Coze: filename={filename}, content_type={content_type}, size={len(content)}")
            audio_id = await client.upload_file(
                filename=filename,
                content=content,
                content_type=content_type,
            )
            print(f"Audio uploaded to Coze: file_id={audio_id}")

    import json
    params: dict[str, object] = {settings.coze_param_text: text, settings.coze_param_language: language}
    if image_id:
        params[settings.coze_param_image_id] = json.dumps({"file_id": image_id}, ensure_ascii=False)
    if audio_id:
        # 尝试不同的格式：有些 Coze 工作流可能期望直接的 file_id 字符串
        params[settings.coze_param_audio_id] = json.dumps({"file_id": audio_id}, ensure_ascii=False)
    print(f"Params: {params}")
    try:
        raw = await client.run_workflow(workflow_id=settings.coze_workflow_id, parameters=params)
    except CozeError as e:
        error_msg = str(e)
        if "file content or filename is invalid" in error_msg:
            error_msg += " (音频格式可能不被支持，请尝试使用图片或其他方式)"
        return ChatResponse(assistant_text=f"[CozeError] {error_msg}", image_id=image_id, audio_id=audio_id, raw=None)

    assistant_text = _extract_assistant_text(raw)
    return ChatResponse(assistant_text=assistant_text, image_id=image_id, audio_id=audio_id, raw=raw)

