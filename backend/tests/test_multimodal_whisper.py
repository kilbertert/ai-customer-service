"""PR13: WhisperService unit tests. Same fake-client injection pattern as
test_multimodal_vision.py.
"""

import pytest

from services.asr_service import WhisperService, WhisperUnavailableError, get_whisper_service


class _FakeTranscriptionResponse:
    def __init__(self, text):
        self.text = text


class _FakeAudioTranscriptions:
    def __init__(self, text="hello world"):
        self._text = text
        self.last_call = None

    async def create(self, *args, **kwargs):
        if "file" in kwargs:
            self.last_call = kwargs
        elif args:
            self.last_call = {"file": args[0], **kwargs}
        return _FakeTranscriptionResponse(self._text)


class _FakeAudioNamespace:
    def __init__(self, text):
        self.transcriptions = _FakeAudioTranscriptions(text)


class _FakeAsyncOpenAIWhisper:
    def __init__(self, *args, **kwargs):
        self.audio = _FakeAudioNamespace("hello world")


@pytest.mark.asyncio
async def test_whisper_service_transcribe_happy_path():
    svc = WhisperService(api_key="test-key", base_url="https://x")
    svc.client = _FakeAsyncOpenAIWhisper()
    out = await svc.transcribe(b"\x1aE\xdf\xa3...", "audio/webm", language="zh")
    assert out == "hello world"
    last = svc.client.audio.transcriptions.last_call
    assert last["file"][0] == "audio.webm"


def test_whisper_service_rejects_missing_api_key():
    with pytest.raises(WhisperUnavailableError):
        WhisperService(api_key="")


@pytest.mark.asyncio
async def test_whisper_service_swallows_openai_errors():
    class _Broken:
        class audio:
            class transcriptions:
                async def create(self, *a, **kw):
                    raise RuntimeError("simulated 401")

    svc = WhisperService(api_key="test-key")
    svc.client = _Broken()
    with pytest.raises(WhisperUnavailableError):
        await svc.transcribe(b"x", "audio/webm")


def test_get_whisper_service_returns_none_when_no_key(monkeypatch):
    from api.v1.endpoints import get_agent_plaintext_keys

    monkeypatch.setattr(
        "api.v1.endpoints.get_agent_plaintext_keys",
        lambda agent, attr="api_key": None,
    )
    agent = type(
        "FakeAgent",
        (),
        {"whisper_api_key": "", "whisper_base_url": None, "whisper_model": None},
    )()
    assert get_whisper_service(agent) is None
