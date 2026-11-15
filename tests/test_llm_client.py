import logging
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.contracts import Intent
from app.llm import client as client_module
from app.llm.client import complete


class Out(BaseModel):
    kind: str


class FakeCompletions:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.replies.pop(0)
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture
def fake(monkeypatch):
    """Install a fake client that returns the given replies, one per call."""
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    def install(replies):
        completions = FakeCompletions(replies)
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        monkeypatch.setattr(client_module, "_client", lambda: fake_client)
        return completions

    return install


def test_valid_response(fake):
    completions = fake(['{"kind": "cancel"}'])
    result = complete("system", "user", Out)
    assert result.kind == "cancel"
    assert len(completions.calls) == 1
    call = completions.calls[0]
    assert call["model"] == "test-model"
    assert call["temperature"] == 0
    assert call["response_format"] == {"type": "json_object"}
    assert call["timeout"] == client_module.TIMEOUT_SECONDS


def test_invalid_json_then_valid_retries_once(fake):
    completions = fake(["not json", '{"kind": "confirm"}'])
    result = complete("system", "user", Out)
    assert result.kind == "confirm"
    assert len(completions.calls) == 2
    assert "invalid" in completions.calls[1]["messages"][-1]["content"]


def test_invalid_twice_raises(fake):
    completions = fake(["nope", "still nope"])
    with pytest.raises(ValueError, match="valid JSON"):
        complete("system", "user", Out)
    assert len(completions.calls) == 2


def test_valid_json_with_wrong_shape_is_rejected(fake):
    fake(['{"x": 1}', '{"x": 2}'])
    with pytest.raises(ValueError):
        complete("system", "user", Out)


def test_no_retry_when_retries_is_zero(fake):
    completions = fake(["bad"])
    with pytest.raises(ValueError):
        complete("system", "user", Out, retries=0)
    assert len(completions.calls) == 1


def test_stub_provider_returns_valid_intent_without_a_client(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "stub")

    def boom():
        raise AssertionError("no client must be built for the stub")

    monkeypatch.setattr(client_module, "_client", boom)
    result = complete("system", "user", Intent)
    assert result.kind == "action"
    assert result.resources[0].type.value == "storage"


def _recorder(name):
    class Recorder:
        def __init__(self, **kwargs):
            self.name = name
            self.kwargs = kwargs
    return Recorder


def test_provider_switch_azure(monkeypatch):
    monkeypatch.setattr(client_module, "AzureOpenAI", _recorder("azure"))
    monkeypatch.setattr(client_module, "OpenAI", _recorder("openai"))
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.invalid")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "v")
    assert client_module._client().name == "azure"


def test_provider_switch_openai_compatible(monkeypatch):
    monkeypatch.setattr(client_module, "AzureOpenAI", _recorder("azure"))
    monkeypatch.setattr(client_module, "OpenAI", _recorder("openai"))
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    c = client_module._client()
    assert c.name == "openai"
    assert c.kwargs["base_url"] == "https://example.invalid/v1"


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        client_module._client()


def test_secrets_never_appear_in_logs(fake, monkeypatch, caplog):
    monkeypatch.setenv("LLM_API_KEY", "sk-secret-123")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "az-secret-456")
    caplog.set_level(logging.DEBUG)
    fake(["bad", '{"kind": "cancel"}'])
    complete("system", "user", Out)
    assert "sk-secret-123" not in caplog.text
    assert "az-secret-456" not in caplog.text