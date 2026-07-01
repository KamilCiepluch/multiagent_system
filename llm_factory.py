"""
Fabryka LLM systemu docelowego — jeden przełącznik providera (ollama | nvidia).

Domyślnie `ollama` (zachowanie bez zmian, lokalny stack). `LLM_PROVIDER=nvidia`
→ `ChatNVIDIA` (build.nvidia.com / self-hosted NIM): model z `NVIDIA_MODEL`, klucz
czytany automatycznie z env `NVIDIA_API_KEY`. Parametry Ollama-specyficzne
(`reasoning`, `num_ctx`, `base_url`) są dla nvidia pomijane (nie istnieją po stronie API).

Cel: móc przetestować cały system agentowy na MOCNYM modelu przez API — bez protez,
które dokładaliśmy pod słaby lokalny model (niska temperatura, completion-guard itd.) —
zmieniając tylko JEDNĄ zmienną środowiskową, bez dotykania logiki agentów.
"""

from __future__ import annotations

from config import settings


def build_system_llm(*, temperature: float | None = None, reasoning: bool | None = None):
    """Zwraca LLM agentów/supervisora wg `settings.llm_provider`.

    temperature: None → `settings.agent_temperature`.
    reasoning:   None → `settings.capture_thinking` (dotyczy tylko ollamy; nvidia ignoruje)."""
    temp = settings.agent_temperature if temperature is None else temperature
    provider = (settings.llm_provider or "ollama").lower()

    if provider == "nvidia":
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
        # timeout > domyślne 60s: darmowy tier bywa wolny (30–50s/wywołanie), a tool-calle
        # z dłuższym outputem potrafią przekroczyć 60s → fałszywy ReadTimeout psułby wynik.
        kwargs: dict = {"model": settings.nvidia_model, "temperature": temp, "timeout": 180}
        if settings.nvidia_base_url:
            kwargs["base_url"] = settings.nvidia_base_url
        if settings.nvidia_api_key:  # z .env; inaczej ChatNVIDIA weźmie env NVIDIA_API_KEY
            kwargs["api_key"] = settings.nvidia_api_key
        return ChatNVIDIA(**kwargs)

    from langchain_ollama import ChatOllama
    reason = settings.capture_thinking if reasoning is None else reasoning
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        num_ctx=settings.ollama_num_ctx,
        reasoning=reason,
        temperature=temp,
    )
