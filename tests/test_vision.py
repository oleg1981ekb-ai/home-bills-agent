"""Тесты распознавания показаний по фото (assistant/vision.py)."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

# Заглушка модулей до импорта vision
anthropic_stub = SimpleNamespace(AsyncAnthropic=None)
sys.modules.setdefault("anthropic", anthropic_stub)
openai_stub = SimpleNamespace(AsyncOpenAI=None, OpenAI=None)
sys.modules.setdefault("openai", openai_stub)

from home_bills_agent.assistant import vision


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeMessage(self._response_text)


class _FakeAnthropicClient:
    def __init__(self, response_text: str, api_key: str = "test") -> None:
        self.messages = _FakeMessages(response_text)
        self.api_key = api_key


class _FakeChoice:
    def __init__(self, text: str) -> None:
        self.message = SimpleNamespace(content=text)


class _FakeOpenRouterResponse:
    def __init__(self, text: str) -> None:
        self.choices = [_FakeChoice(text)]


class _FakeOpenRouterClient:
    def __init__(self, response_text: str, api_key: str = "test") -> None:
        self._response_text = response_text
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls = getattr(self, "calls", []) + [kwargs]
        return _FakeOpenRouterResponse(self._response_text)


def _install_fake_anthropic(monkeypatch, response_text: str) -> _FakeAnthropicClient:
    fake = _FakeAnthropicClient(response_text)
    monkeypatch.setattr(vision, "AsyncAnthropic", lambda api_key: fake)
    monkeypatch.setattr(vision.settings, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(vision.settings, "VISION_PROVIDER", "anthropic")
    return fake


def _install_fake_openrouter(monkeypatch, response_text: str) -> _FakeOpenRouterClient:
    fake = _FakeOpenRouterClient(response_text)
    monkeypatch.setattr(vision, "AsyncOpenAI", lambda api_key, base_url, default_headers: fake)
    monkeypatch.setattr(vision.settings, "OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setattr(vision.settings, "VISION_PROVIDER", "openrouter")
    return fake


def test_recognize_reading_parses_json_anthropic(monkeypatch):
    fake = _install_fake_anthropic(monkeypatch, '{"value": 123, "confidence": 0.95}')
    import asyncio

    result = asyncio.run(vision.recognize_reading(b"img"))
    assert result.value == 123
    assert result.confidence == pytest.approx(0.95)
    call = fake.messages.calls[0]
    assert call["model"] == vision.settings.VISION_MODEL


def test_recognize_reading_parses_json_openrouter(monkeypatch):
    fake = _install_fake_openrouter(monkeypatch, '{"value": 456, "confidence": 0.88}')
    import asyncio

    result = asyncio.run(vision.recognize_reading(b"img"))
    assert result.value == 456
    assert result.confidence == pytest.approx(0.88)
    call = fake.calls[0]
    assert call["model"] == vision.settings.VISION_MODEL


def test_recognize_reading_no_api_key_anthropic(monkeypatch):
    import asyncio
    monkeypatch.setattr(vision.settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(vision.settings, "VISION_PROVIDER", "anthropic")
    result = asyncio.run(vision.recognize_reading(b"img"))
    assert result.value is None
    assert result.confidence == 0.0


def test_recognize_reading_no_api_key_openrouter(monkeypatch):
    import asyncio
    monkeypatch.setattr(vision.settings, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(vision.settings, "VISION_PROVIDER", "openrouter")
    result = asyncio.run(vision.recognize_reading(b"img"))
    assert result.value is None
    assert result.confidence == 0.0


def test_recognize_reading_invalid_json(monkeypatch):
    _install_fake_anthropic(monkeypatch, "не json")
    import asyncio
    result = asyncio.run(vision.recognize_reading(b"img"))
    assert result.value is None
    assert result.confidence == 0.0


def test_recognize_reading_null_value(monkeypatch):
    _install_fake_anthropic(monkeypatch, '{"value": null, "confidence": 0.1}')
    import asyncio
    result = asyncio.run(vision.recognize_reading(b"img"))
    assert result.value is None
    assert result.confidence == pytest.approx(0.1)


def test_is_confident_threshold(monkeypatch):
    monkeypatch.setattr(vision.settings, "CONFIDENCE_MIN", 0.9)
    assert vision.is_confident(vision.VisionResult(value=100, confidence=0.95, raw_response="")) is True
    assert vision.is_confident(vision.VisionResult(value=100, confidence=0.5, raw_response="")) is False


def test_prepare_for_logging():
    r = vision.VisionResult(value=100, confidence=0.95, raw_response="secret")
    out = vision.prepare_for_logging(r)
    assert "100" in out
    assert "0.95" in out
    assert "secret" not in out