"""PR13: VisionService unit tests.

We inject a fake OpenAI client via ``VisionService.client`` after
construction — no class-level monkeypatching needed.
"""

import pytest

from services.vision_service import VisionService, VisionUnavailableError, get_vision_service


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessageContent(content)


class _FakeMessageContent:
    def __init__(self, content):
        self.content = content


class _FakeChatCompletions:
    def __init__(self, content="a 1x1 red PNG with text 'Hello'"):
        self._content = content

    async def create(self, *args, **kwargs):
        msgs = kwargs.get("messages") or (args[0] if args else [])
        assert msgs, "no messages"
        content = msgs[0]["content"]
        assert isinstance(content, list), "content should be a list for multimodal"
        kinds = [c.get("type") for c in content]
        assert "text" in kinds and "image_url" in kinds
        image = next(c for c in content if c["type"] == "image_url")
        url = image["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        return _FakeChatCompletions._Resp(self._content)


class _FakeChatCompletions_Resp:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


# Attach the inner _Resp class so the staticmethod-style return above
# resolves correctly.
_FakeChatCompletions._Resp = _FakeChatCompletions_Resp


class _FakeChatNamespace:
    def __init__(self, content):
        self.completions = _FakeChatCompletions(content)


class _FakeAsyncOpenAIVision:
    def __init__(self, *args, **kwargs):
        self.chat = _FakeChatNamespace("a 1x1 red PNG with text 'Hello'")


@pytest.mark.asyncio
async def test_vision_service_describe_image_happy_path():
    svc = VisionService(api_key="test-key", base_url="https://x", model="gpt-4o")
    svc.client = _FakeAsyncOpenAIVision()
    desc = await svc.describe_image(b"\x89PNG\r\n\x1a\n", "image/png")
    assert "red PNG" in desc


def test_vision_service_rejects_missing_api_key():
    with pytest.raises(VisionUnavailableError):
        VisionService(api_key="")


@pytest.mark.asyncio
async def test_vision_service_swallows_openai_errors():
    class _Broken:
        class chat:
            class completions:
                async def create(self, *a, **kw):
                    raise RuntimeError("simulated 500")

    svc = VisionService(api_key="test-key")
    svc.client = _Broken()
    with pytest.raises(VisionUnavailableError):
        await svc.describe_image(b"x", "image/png")


def test_get_vision_service_returns_none_when_no_key(monkeypatch):
    from api.v1.endpoints import get_agent_plaintext_keys

    monkeypatch.setattr(
        "api.v1.endpoints.get_agent_plaintext_keys",
        lambda agent, attr="api_key": None,
    )
    agent = type(
        "FakeAgent",
        (),
        {"vision_api_key": "", "vision_base_url": None, "vision_model": None},
    )()
    assert get_vision_service(agent) is None
