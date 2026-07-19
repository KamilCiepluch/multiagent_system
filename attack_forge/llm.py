"""Strategist LLM factory (attacker-side), independent of the target-system factory.

Model comes from `settings.meta_attacker_*`, falling back to `ollama_*`. When a bearer token is
set we talk to the remote Ollama proxy (Authorization header + the sanitizing httpx transport
that fixes empty `{}` JSON, exactly as in `llm_factory`). Locally the token is unset → plain stack.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402


def build_strategist_llm(*, model: str | None = None, temperature: float = 0.6, reasoning: bool | None = None):
    from langchain_ollama import ChatOllama

    model = model or settings.meta_attacker_model or settings.ollama_model
    base_url = settings.meta_attacker_base_url or settings.ollama_base_url
    reason = settings.capture_thinking if reasoning is None else reasoning

    extra = {}
    if settings.ollama_bearer_token:
        from ollama_proxy import SanitizingTransport, AsyncSanitizingTransport

        extra["client_kwargs"] = {"headers": {"Authorization": f"Bearer {settings.ollama_bearer_token}"}}
        extra["sync_client_kwargs"] = {"transport": SanitizingTransport()}
        extra["async_client_kwargs"] = {"transport": AsyncSanitizingTransport()}

    return ChatOllama(
        model=model,
        base_url=base_url,
        num_ctx=settings.ollama_num_ctx,
        reasoning=reason,
        temperature=temperature,
        **extra,
    )


def build_target_llm(*, temperature: float | None = None, reasoning: bool | None = None):
    """The TARGET system's LLM — delegates to the main repo's `llm_factory.build_system_llm`,
    so attack_forge always fires at the same model/proxy config the real agents run on."""
    from llm_factory import build_system_llm

    return build_system_llm(temperature=temperature, reasoning=reasoning)
