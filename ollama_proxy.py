"""
Obejście wady zdalnego proxy Ollamy (Bearer): przy re-enkodowaniu JSON zamienia ono puste
obiekty `{}` na puste tablice `[]`, przez co Ollama odrzuca ciało (`cannot unmarshal array into
Go struct` / `can't find closing '}'`). Najczęstsze źródło to schematy narzędzi bez argumentów
(`parameters.properties = {}`) i property, którym klient ollama gubi typ (`is_verified = {}`).

Transport httpx sanitizuje ciało TUŻ przed wysłaniem — każde puste `{}` dostaje minimalny,
nie-pusty schemat, więc nie ma już czego psuć. Aktywny tylko na ścieżce proxy (gdy jest token).
"""

from __future__ import annotations

import json

import httpx


def fill_empty_objects(node, key=None):
    """Rekurencyjnie zamienia puste `{}` na minimalny schemat, zależnie od kontekstu:
    pusta mapa `properties` → atrapa pola; pusty schemat property → `{"type":"string"}`."""
    if isinstance(node, dict):
        if not node:
            return {"_noop": {"type": "string"}} if key == "properties" else {"type": "string"}
        return {k: fill_empty_objects(v, k) for k, v in node.items()}
    if isinstance(node, list):
        return [fill_empty_objects(v, key) for v in node]
    return node


def _sanitize(request: httpx.Request) -> httpx.Request:
    body = request.read()
    if not body:
        return request
    try:
        data = json.loads(body)
    except ValueError:
        return request
    new = json.dumps(fill_empty_objects(data)).encode()
    if new == body:
        return request
    headers = dict(request.headers)
    headers.pop("content-length", None)  # httpx przeliczy dla nowego ciała
    return httpx.Request(request.method, request.url, headers=headers, content=new)


class SanitizingTransport(httpx.HTTPTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return super().handle_request(_sanitize(request))


class AsyncSanitizingTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await super().handle_async_request(_sanitize(request))
