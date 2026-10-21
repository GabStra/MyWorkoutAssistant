"""LLM endpoint configuration: env resolution, client factory, and the generic provider profile."""

import json
from types import SimpleNamespace

import pytest

from workout_generator_pkg import api_client, llm_config
from workout_generator_pkg.llm_config import (
    build_llm_client,
    chat_completions_url,
    require_api_key,
    resolve_llm_endpoint,
)

_ENDPOINT_ENV_VARS = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
                      "DEEPSEEK_API_KEY", "OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def hermetic_llm_env(monkeypatch):
    """Resolve the endpoint from os.environ only; never read a developer's real .env."""
    monkeypatch.setattr(llm_config, "load_env_files", lambda: None)
    for name in _ENDPOINT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_preserve_deepseek_behavior():
    config = resolve_llm_endpoint()
    assert config.base_url == "https://api.deepseek.com"
    assert config.model == "deepseek-flash"
    assert config.is_deepseek is True
    assert config.api_key == "none"
    with pytest.raises(RuntimeError, match="Missing API key"):
        require_api_key(config)


def test_env_overrides_select_generic_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("LLM_MODEL", "qwen3-32b")
    config = resolve_llm_endpoint()
    assert config.base_url == "http://127.0.0.1:8080"
    assert config.model == "qwen3-32b"
    assert config.is_deepseek is False
    assert config.api_key == "none"


def test_key_resolution_falls_back_to_legacy_names(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deep-key")
    assert resolve_llm_endpoint().api_key == "deep-key"
    monkeypatch.setenv("LLM_API_KEY", "explicit-key")
    assert resolve_llm_endpoint().api_key == "explicit-key"


def test_build_llm_client_targets_configured_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8080")
    client = build_llm_client(max_retries=0)
    assert str(client.base_url).rstrip("/") == "http://127.0.0.1:8080"


@pytest.mark.parametrize("endpoint_base_url,expected", [
    ("https://api.deepseek.com", "https://api.deepseek.com/chat/completions"),
    ("http://127.0.0.1:8080", "http://127.0.0.1:8080/v1/chat/completions"),
    ("http://127.0.0.1:8080/v1/", "http://127.0.0.1:8080/v1/chat/completions"),
])
def test_chat_completions_url(endpoint_base_url, expected):
    assert chat_completions_url(endpoint_base_url) == expected


def _streaming_client(requests, content='{"ok":true}'):
    def create(**kwargs):
        requests.append(kwargs)
        return iter([SimpleNamespace(
            model=kwargs["model"],
            usage=None,
            choices=[SimpleNamespace(finish_reason="stop", delta=SimpleNamespace(content=content))],
        )])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_json_call_generic_endpoint_omits_deepseek_quirks(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("LLM_MODEL", "qwen3-32b")
    requests = []
    content, finish_reason = api_client.json_call(
        _streaming_client(requests), [{"role": "user", "content": "Return JSON"}])
    assert content == '{"ok":true}' and finish_reason == "stop"
    assert requests[0]["model"] == "qwen3-32b"
    assert "extra_body" not in requests[0]
    assert requests[0]["response_format"] == {"type": "json_object"}


def test_json_call_deepseek_default_keeps_thinking_control():
    requests = []
    content, _ = api_client.json_call(
        _streaming_client(requests), [{"role": "user", "content": "Return JSON"}])
    assert requests[0]["model"] == "deepseek-flash"
    assert requests[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def _chat_client(requests):
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
                content="ok", tool_calls=None, reasoning_content=None))],
            usage=None,
        )

    def with_options(**options):
        requests.append(options)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    return SimpleNamespace(with_options=with_options)


def test_chat_call_generic_endpoint_uses_plain_reasoning_effort(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8080")
    requests = []
    content, tool_calls, _ = api_client.chat_call(
        _chat_client(requests),
        [{"role": "assistant", "content": "hi"}, {"role": "user", "content": "go"}],
    )
    assert content == "ok" and tool_calls is None
    options, request = requests
    assert options == {"max_retries": 0}
    assert request["model"] == "deepseek-flash"
    assert "extra_body" not in request
    assert request["reasoning_effort"] == "high"
    assert all("reasoning_content" not in message for message in request["messages"])


@pytest.mark.parametrize('failure', ['reasoning', 'output', 'invalid_schema', 'twice'])
def test_chat_reasoning_recovery_is_bounded_and_validated(failure):
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        truncated = len(requests) == 1 or failure == 'twice'
        content = ('partial' if failure == 'output' else None) if truncated else (
            '{"ok":"wrong"}' if failure == 'invalid_schema' else '{"ok":true}')
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason='length' if truncated else 'stop',
            message=SimpleNamespace(content=content, tool_calls=None, reasoning_content='thinking'))],
            usage=SimpleNamespace(model_dump=lambda: {'completion_tokens': 24,
                'completion_tokens_details': {'reasoning_tokens': 24 if content is None else 0}}))
    client = SimpleNamespace(with_options=lambda **options: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    messages = [{'role': 'user', 'content': 'Return JSON'}]
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']}
    if failure == 'reasoning':
        assert api_client.chat_call(client, messages, reasoning_effort='low', output_schema=schema)[0] == '{"ok":true}'
    else:
        error = api_client.StructuredResponseError if failure == 'invalid_schema' else api_client.TruncatedResponseError
        with pytest.raises(error):
            api_client.chat_call(client, messages, reasoning_effort='low', output_schema=schema)
    assert len(requests) == (1 if failure == 'output' else 2)
    if len(requests) == 2:
        assert requests[0]['reasoning_effort'] == 'low'
        assert 'reasoning_effort' not in requests[1]
        assert requests[1]['extra_body']['thinking']['type'] == 'disabled'
        assert requests[0]['messages'] == requests[1]['messages']
        assert requests[0]['tools'] == requests[1]['tools']
