"""
Konfiguracja bloczka AutoDAN-Turbo — jedno miejsce na wybór modeli i temperatur.

AutoDAN-Turbo używa potencjalnie RÓŻNYCH modeli dla każdej roli (attacker / scorer /
summarizer) — odzwierciedlamy to, choć domyślnie wszystkie spadają na ten sam stack
co agenci (`config.settings.ollama_*`), więc bez konfiguracji „po prostu działa".

Zmienne środowiskowe (prefiks AUTODAN_, też z .env):
  AUTODAN_ATTACKER_MODEL      model attackera   (domyślnie = ollama_model)
  AUTODAN_SCORER_MODEL        model scorera     (domyślnie = ollama_model)
  AUTODAN_SUMMARIZER_MODEL    model summarizera (domyślnie = ollama_model)
  AUTODAN_BASE_URL            base_url Ollamy   (domyślnie = ollama_base_url)
  AUTODAN_EMBED_MODEL         model embeddingów (domyślnie nomic-embed-text, 768d)
  AUTODAN_ATTACKER_TEMPERATURE   (domyślnie 1.0 — jak oryginał, kreatywne payloady)
  AUTODAN_SCORER_TEMPERATURE     (domyślnie 0.0 — deterministyczna ocena)
  AUTODAN_SUMMARIZER_TEMPERATURE (domyślnie 0.5)
  AUTODAN_NUM_CTX             okno kontekstu Ollamy (domyślnie 8192)
  AUTODAN_REASONING          żądaj kanału thinking (domyślnie False — czysty tekst,
                             prostsze parsowanie; ustaw True dla modeli rozumujących)
  AUTODAN_KEEP_ALIVE         jak długo Ollama trzyma model atakującego/scorera/summarizera
                             w pamięci PO wywołaniu (domyślnie None = domyślne Ollamy ~5min).
                             Ustaw "0" gdy model atakującego RÓŻNI się od modelu docelowego,
                             a VRAM nie mieści obu — model zwalnia się natychmiast po użyciu,
                             więc do pamięci ładuje się raz jeden, raz drugi (kosztem ponownego
                             ładowania). Przy JEDNYM wspólnym modelu zostaw None (bez przeładowań).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from config import settings as _root


class AutoDanSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTODAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    attacker_model: str = _root.ollama_model
    scorer_model: str = _root.ollama_model
    summarizer_model: str = _root.ollama_model
    base_url: str = _root.ollama_base_url
    embed_model: str = "nomic-embed-text"

    attacker_temperature: float = 1.0
    scorer_temperature: float = 0.0
    summarizer_temperature: float = 0.5
    num_ctx: int = 8192
    reasoning: bool = False
    # None = domyślny keep_alive Ollamy; "0" = zwolnij model od razu po wywołaniu
    # (dynamiczne ładowanie jeden-na-raz, gdy atakujący ≠ docelowy i mało VRAM).
    keep_alive: str | None = None


def build_chat(model: str, temperature: float, settings: AutoDanSettings | None = None):
    """Buduje ChatOllama dla danej roli — spójnie z `hyperagent_email/llm_factory`."""
    settings = settings or AutoDanSettings()
    from langchain_ollama import ChatOllama

    kwargs = {
        "model": model,
        "base_url": settings.base_url,
        "temperature": temperature,
        "num_ctx": settings.num_ctx,
        "reasoning": settings.reasoning,
    }
    if settings.keep_alive is not None:
        kwargs["keep_alive"] = settings.keep_alive
    return ChatOllama(**kwargs)


def build_embeddings(settings: AutoDanSettings | None = None):
    """Lokalne embeddingi (OllamaEmbeddings) do retrievalu po odpowiedzi targetu."""
    settings = settings or AutoDanSettings()
    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(model=settings.embed_model, base_url=settings.base_url)
