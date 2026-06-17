"""
Retrieval strategii — wierne odwzorowanie `framework/retrival.py` z AutoDAN-Turbo.

Najważniejszy, nieoczywisty element metody: KLUCZEM retrievalu jest embedding
ODPOWIEDZI targetu z POPRZEDNIEJ iteracji (a nie celu/żądania). Logika: podobna
odpowiedź obronna → podobna sytuacja → ta sama strategia historycznie pomagała.

Odstępstwo techniczne: oryginał używa FAISS (IndexFlatL2); my liczymy cosine w numpy.
Dla małej biblioteki to równoważne (brute-force najbliższych sąsiadów), bez ciężkiej
zależności. Ranking podobieństwa robi najlepszy (najbliższy) embedding strategii,
a „score" strategii to ŚREDNIA jej zapisanych wyników.

Trzy progi skuteczności (1:1 z oryginałem):
  avg_score ≥ 5      → zwróć tylko PIERWSZĄ (najbardziej podobną) skuteczną strategię
  2 ≤ avg_score < 5  → zwróć do k strategii „umiarkowanych" (wciąż do użycia)
  avg_score < 2      → zwróć do k NIESKUTECZNYCH, ale tylko gdy nie ma nic lepszego
                       (te trafiają do attacker.find_new_strategy jako „czego unikać")

`pop` zwraca `(strategies, use)` — `use=True` → attacker.use_strategy,
`use=False` → attacker.find_new_strategy (unikaj). Pusta lista przy pustej bibliotece.
"""

from __future__ import annotations

import logging

import numpy as np

_log = logging.getLogger("autodan_turbo.retrieval")

_HIGH = 5.0
_MODERATE = 2.0


class Retrieval:
    def __init__(self, embeddings, *, high: float = _HIGH, moderate: float = _MODERATE):
        self._embeddings = embeddings
        self._high = high
        self._moderate = moderate

    def embed(self, text: str) -> list[float]:
        return self._embeddings.embed_query(text or "")

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        na = np.linalg.norm(a)
        nb = np.linalg.norm(b)
        if na == 0.0 or nb == 0.0:
            return -1.0
        return float(np.dot(a, b) / (na * nb))

    def pop(self, library: dict, query_response: str, k: int = 5) -> tuple[list[dict], bool]:
        """Zwraca (lista strategii, czy_skuteczne) dla danej odpowiedzi targetu."""
        if not library:
            return [], False

        query = np.asarray(self.embed(query_response), dtype=np.float32)

        # Najlepsze (najbliższe) podobieństwo per strategia — ranking po nim.
        ranked: list[tuple[float, str]] = []
        for name, entry in library.items():
            sims = [
                self._cosine(query, np.asarray(vec, dtype=np.float32))
                for vec in entry.get("Embeddings", [])
                if vec is not None and len(vec) > 0
            ]
            if sims:
                ranked.append((max(sims), name))
        if not ranked:
            return [], False

        ranked.sort(key=lambda t: t[0], reverse=True)
        # Top-2k unikalnych kandydatów (w oryginale: top-2k przed filtrem progów).
        candidates = [name for _, name in ranked[: 2 * k]]

        def avg_score(name: str) -> float:
            scores = library[name].get("Score", [])
            return float(np.mean(scores)) if scores else 0.0

        # Próg 1: pierwsza wysoko skuteczna w kolejności podobieństwa.
        for name in candidates:
            if avg_score(name) >= self._high:
                return [library[name]], True

        # Próg 2: umiarkowane (wciąż do użycia), do k.
        moderate = [library[n] for n in candidates if self._moderate <= avg_score(n) < self._high]
        if moderate:
            return moderate[:k], True

        # Próg 3: nieskuteczne — tylko jako „czego unikać".
        ineffective = [library[n] for n in candidates if avg_score(n) < self._moderate]
        return ineffective[:k], False
