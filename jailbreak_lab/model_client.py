"""
Cienki klient CZYSTEGO modelu przez natywne REST API Ollamy (`/api/chat`).

Świadomie NIE używamy tu langchaina ani `config.py` z repo — folder ma być samodzielny i
rozmawiać z modelem bez żadnych protez (niska temperatura, completion-guard, reasoning-capture
itd. z systemu agentowego). Chcemy zobaczyć, co łamie GOŁY model, więc wszystko domyślnie
puste/neutralne, a każdy parametr próbkowania jest jawny i logowany razem z atakiem.

Zależność: `requests`. (Jest w środowisku systemu; jeśli nie — `pip install requests`.)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests


@dataclass
class ChatResult:
    content: str                       # pełny output modelu
    reasoning: str | None = None       # kanał myślenia (modele rozumujące + think=True)
    latency_ms: int = 0                # zmierzony zegarem ściennym
    eval_count: int | None = None      # liczba wygenerowanych tokenów (z Ollamy)
    raw: dict[str, Any] = field(default_factory=dict)


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "gpt-oss:20b"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def list_models(self) -> list[str]:
        """Nazwy zainstalowanych modeli (`ollama list`)."""
        r = requests.get(f"{self.base_url}/api/tags", timeout=30)
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
        think: bool | None = None,
        keep_alive: str | int | None = None,
        timeout: int = 600,
    ) -> ChatResult:
        """Wysyła listę wiadomości ([{role, content}, ...]) do modelu i zwraca ChatResult.

        options:    przechodzi 1:1 do Ollamy (`temperature`, `num_ctx`, `seed`, `top_p`, ...).
        think:      dla modeli rozumujących kieruje myślenie do osobnego pola `message.thinking`
                    zamiast mieszać je z treścią (None = nie wysyłamy pola, model decyduje sam).
        keep_alive: jak długo trzymać model w VRAM po odpowiedzi (np. "10m", 0). Nadpisuje
                    globalne OLLAMA_KEEP_ALIVE — istotne przy seriach strzałów, żeby nie
                    przeładowywać wag co request."""
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
        }
        if options:
            payload["options"] = options
        if think is not None:
            payload["think"] = think
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        t0 = time.perf_counter()
        r = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=timeout)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        r.raise_for_status()
        data = r.json()
        msg = data.get("message", {}) or {}
        return ChatResult(
            content=msg.get("content", "") or "",
            reasoning=msg.get("thinking") or None,
            latency_ms=latency_ms,
            eval_count=data.get("eval_count"),
            raw=data,
        )
