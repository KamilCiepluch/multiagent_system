"""Embeddings for the fake_internet knowledge base — local Ollama, nomic-embed-text.

nomic-embed-text is trained with task prefixes: passages must be embedded as `search_document: …`
and questions as `search_query: …`. Getting this wrong degrades retrieval silently, so the
prefixes live here and nowhere else — callers pass plain text.
"""

from __future__ import annotations

from functools import lru_cache

from config import settings

_DOC_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "


@lru_cache(maxsize=1)
def _client():
    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(model=settings.embed_model, base_url=settings.embed_base_url)


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed page texts (one round trip for the whole batch)."""
    if not texts:
        return []
    return _client().embed_documents([_DOC_PREFIX + t for t in texts])


def embed_document(text: str) -> list[float]:
    return embed_documents([text])[0]


def embed_query(text: str) -> list[float]:
    return _client().embed_query(_QUERY_PREFIX + text)


def vector_literal(vec: list[float] | None) -> str | None:
    """pgvector literal, e.g. '[0.1,-0.2,…]'. None passes through as SQL NULL."""
    if vec is None:
        return None
    return "[" + ",".join(f"{float(x):.7g}" for x in vec) + "]"
