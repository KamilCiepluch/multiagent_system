"""
Fabryka LLM dla hyperagent_email — jedno miejsce, w którym wybiera się
model napędzający agenta.

Domyślnie: Ollama (te same domyślne wartości co `config.Settings` w korzeniu
repo — `gpt-oss:20b` na `http://localhost:11434`), ale całość da się
przełączyć na model dostępny przez API (OpenAI / Anthropic) ustawiając
zmienne środowiskowe — bez dotykania kodu agenta.

Zmienne środowiskowe (prefiks HYPERAGENT_EMAIL_, też wczytywane z .env):
  HYPERAGENT_EMAIL_PROVIDER     "ollama" (domyślnie) | "openai" | "anthropic"
  HYPERAGENT_EMAIL_MODEL        nazwa modelu (domyślnie "gpt-oss:20b")
  HYPERAGENT_EMAIL_BASE_URL     base_url dla Ollamy (domyślnie "http://localhost:11434")
  HYPERAGENT_EMAIL_API_KEY      klucz API (wymagany dla openai/anthropic)
  HYPERAGENT_EMAIL_TEMPERATURE  temperatura (domyślnie 0.7)
  HYPERAGENT_EMAIL_NUM_CTX      okno kontekstu Ollamy w tokenach (domyślnie 8192)
                                 — `_build_intro` (objective + historia) rośnie
                                 z każdą generacją; zbyt mały `num_ctx` ucina
                                 prompt i agent traci instrukcje formatu.
  HYPERAGENT_EMAIL_REASONING    czy żądać kanału thinking od Ollamy (domyślnie
                                 True). Wymaga modelu rozumującego (gpt-oss).
                                 Bez tego langchain_ollama WYCINA reasoning i
                                 obserwowalność nie zobaczy, co model myślał
                                 podczas tworzenia ataku (agent_llm_turns.thinking
                                 byłoby puste). Ustaw False dla modeli bez
                                 reasoning, by uniknąć błędu Ollamy.

Przykład przełączenia na OpenAI:
  HYPERAGENT_EMAIL_PROVIDER=openai
  HYPERAGENT_EMAIL_MODEL=gpt-4o-mini
  HYPERAGENT_EMAIL_API_KEY=sk-...
(wymaga doinstalowania `langchain-openai`; dla anthropic — `langchain-anthropic`)
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HYPERAGENT_EMAIL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: str = "ollama"  # "ollama" | "openai" | "anthropic"
    model: str = "gpt-oss:20b"
    base_url: str = "http://localhost:11434"
    api_key: str | None = None
    temperature: float = 0.7
    num_ctx: int = 8192
    reasoning: bool = True  # żądaj kanału thinking od Ollamy (model rozumujący)


def get_llm(settings: LLMSettings | None = None):
    """Zwraca skonfigurowany chat model LangChain (BaseChatModel)."""
    settings = settings or LLMSettings()
    provider = settings.provider.lower()

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.model,
            base_url=settings.base_url,
            temperature=settings.temperature,
            num_ctx=settings.num_ctx,
            reasoning=settings.reasoning,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=settings.model, api_key=settings.api_key, temperature=settings.temperature)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=settings.model, api_key=settings.api_key, temperature=settings.temperature)

    raise ValueError(f"Nieznany provider LLM: {settings.provider!r} (oczekiwano: ollama | openai | anthropic)")
