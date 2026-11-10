"""Shared OpenAI-compatible LLM endpoint configuration.

Resolves the LLM endpoint from the environment (optionally loading a project
.env file) so every script can target any OpenAI-compatible server, including
local llama.cpp instances. Unset variables fall back to the OpenCode Go defaults
(the provider ZCode itself uses):

- LLM_BASE_URL: endpoint base URL (default https://opencode.ai/zen/go/v1)
- LLM_API_KEY: API key, falling back to OPENCODE_API_KEY, DEEPSEEK_API_KEY then OPENAI_API_KEY
- LLM_MODEL: model name (default constants.DEEPSEEK_MODEL)
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from openai import OpenAI

from .constants import DEEPSEEK_MODEL

DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"

# Local servers commonly run without authentication; this sentinel keeps the
# OpenAI client's required api_key argument satisfied in that case.
UNAUTHENTICATED_API_KEY = "none"

# Hosts that serve an unauthenticated local model rather than a hosted API.
_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


@dataclass(frozen=True)
class LlmEndpointConfig:
    base_url: str
    api_key: str
    model: str
    is_deepseek: bool


def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs from a .env file into os.environ."""
    if not path.exists() or not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and value:
            os.environ.setdefault(key, value)


def load_env_files() -> None:
    """Load .env from the working directory and the repository root when present."""
    repo_root = Path(__file__).resolve().parents[1]
    seen = set()
    for candidate in (Path.cwd() / ".env", repo_root / ".env"):
        resolved = str(candidate.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        _load_env_file(candidate)


def is_deepseek_base_url(base_url: str) -> bool:
    """True when the endpoint host is DeepSeek's API (drives provider-specific request quirks)."""
    host = urlparse(base_url).hostname or ""
    return "deepseek" in host.lower()


def resolve_llm_endpoint() -> LlmEndpointConfig:
    """Resolve the LLM endpoint from the environment with OpenCode Go fallbacks.

    A missing key resolves to the "none" sentinel; require_api_key turns that
    into the friendly error for endpoints that actually need one.
    """
    load_env_files()
    base_url = (os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    deepseek = is_deepseek_base_url(base_url)
    api_key = (os.getenv("LLM_API_KEY") or os.getenv("OPENCODE_API_KEY")
               or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))
    if not api_key:
        api_key = UNAUTHENTICATED_API_KEY
    model = os.getenv("LLM_MODEL") or DEEPSEEK_MODEL
    return LlmEndpointConfig(base_url=base_url, api_key=api_key, model=model, is_deepseek=deepseek)


def require_api_key(config: LlmEndpointConfig) -> str:
    """Return the endpoint's API key, raising the friendly error when it is required but missing."""
    host = urlparse(config.base_url).hostname or ""
    if host not in _LOCAL_HOSTNAMES and config.api_key == UNAUTHENTICATED_API_KEY:
        raise RuntimeError(
            "Missing API key. Set LLM_API_KEY (or OPENCODE_API_KEY) in the environment "
            "or in a project .env file. Local endpoints need no key and run unauthenticated."
        )
    return config.api_key


def llm_session_headers(config: LlmEndpointConfig, session_id: str | None = None) -> dict[str, str]:
    """Identify this application and its conversation to OpenCode's routing service."""
    if urlparse(config.base_url).hostname != "opencode.ai":
        return {}
    return {"User-Agent": "MyWorkoutAssistant-WorkoutGenerator/1.0",
            "x-opencode-session": session_id or str(uuid.uuid4())}


def build_llm_client(http_client=None, max_retries=None, *, session_id=None):
    """Build an OpenAI client pointed at the configured endpoint.

    http_client and max_retries follow the OpenAI SDK semantics; None keeps the
    SDK default so callers preserve their previous construction behavior.
    Pass the persisted conversation ID when available. Other calls use one
    session ID for the lifetime of the client.
    """
    config = resolve_llm_endpoint()
    require_api_key(config)
    kwargs = {"api_key": config.api_key, "base_url": config.base_url}
    headers = llm_session_headers(config, session_id)
    if headers:
        kwargs["default_headers"] = headers
    if http_client is not None:
        kwargs["http_client"] = http_client
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    return OpenAI(**kwargs)


def chat_completions_url(base_url: str) -> str:
    """Chat-completions URL for raw (non-SDK) HTTP calls.

    DeepSeek keeps its historical path; other hosts get /v1 inserted unless the
    base URL already ends with it (llama.cpp, vLLM, LM Studio and Ollama all
    serve /v1/chat/completions).
    """
    base = base_url.rstrip("/")
    if is_deepseek_base_url(base) or base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"
