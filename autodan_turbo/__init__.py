"""
autodan_turbo — wierny, samodzielny bloczek AutoDAN-Turbo (ICLR 2025,
SafoLab-Wisc/AutoDAN-Turbo) na stacku agents_blocks.

Cel modułu: zmierzyć baseline „jak dobrze znana metoda AutoDAN-Turbo radzi sobie
z naszym wieloagentowym systemem" — ZANIM zbudujemy własną syntezę (hyperagent +
toolkit technik + uczenie). Komponenty (Attacker / Scorer / Summarizer / Library /
Retrieval / pipeline) odwzorowują framework z repo; jedyny most do naszego targetu
to cienki `AgentsBlocksTarget` (patrz `target.py`), który NIE zmienia algorytmu —
zamienia jedynie „bezpośredni" kontrakt `respond(prompt)->tekst` na nasze pośrednie
prompt injection (wstrzyknięcie payloadu + odpalenie zadania biznesowego).

Świadome odstępstwa od oryginału (cosine zamiast FAISS, biblioteka JSON zamiast
pgvector, mały dataset) są opisane w docstringach poszczególnych plików i w planie.
"""

from autodan_turbo.library import Library
from autodan_turbo.retrieval import Retrieval
from autodan_turbo.attacker import Attacker
from autodan_turbo.scorer import Scorer
from autodan_turbo.summarizer import Summarizer
from autodan_turbo.pipeline import AutoDANTurbo, Attempt

__all__ = [
    "Library",
    "Retrieval",
    "Attacker",
    "Scorer",
    "Summarizer",
    "AutoDANTurbo",
    "Attempt",
]
