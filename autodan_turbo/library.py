"""
Biblioteka strategii — wierne odwzorowanie `framework/library.py` z AutoDAN-Turbo.

Struktura (1:1 z oryginałem):
  self.library : dict kluczowany NAZWĄ strategii ("Strategy")
  wpis         : {
      "Strategy":   str,          # nazwa techniki (klucz)
      "Definition": str,          # zwięzły opis
      "Example":    list[str],    # przykładowe (skuteczne) payloady
      "Score":      list[float],  # wyniki scorera dla tych przykładów
      "States":     list[str],    # KLUCZE retrievalu — STANY OBRONY (milestone'y, np. "m4.0"),
  }                               # czyli sytuacje, z których strategia pomogła się wydostać
                                  # ("*" = prior z katalogu, pasuje do każdego stanu)

`add()` scala wpis o tej samej nazwie przez APPEND (Example/Score/States) — dzięki
temu jedna strategia akumuluje wiele przykładów i wiele kluczy retrievalu w miarę,
jak jest odkrywana ponownie w różnych sytuacjach obronnych.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("autodan_turbo.library")

_LIST_FIELDS = ("Example", "Score", "States")


class Library:
    def __init__(self, library: dict | None = None, *, notify: bool = False):
        self.library: dict = library or {}
        self._notify = notify

    # --- zapis -----------------------------------------------------------

    def add(self, new_strategy: dict, if_notify: bool | None = None) -> None:
        """Dodaje/scala strategię. Wymaga klucza 'Strategy'; pola listowe
        (Example/Score/States) są normalizowane do list i scalane przez append."""
        name = new_strategy.get("Strategy")
        if not name:
            _log.warning("Pomijam strategię bez nazwy ('Strategy'): %r", new_strategy)
            return

        entry = self._normalize(new_strategy)
        if name in self.library:
            self.library[name] = self._merge(self.library[name], entry)
        else:
            self.library[name] = entry

        notify = self._notify if if_notify is None else if_notify
        if notify:
            _log.info("strategia '%s': %s", name, entry.get("Definition", ""))

    @staticmethod
    def _normalize(strategy: dict) -> dict:
        """Gwarantuje obecność wszystkich pól i listowość Example/Score/States."""
        out = {
            "Strategy": strategy["Strategy"],
            "Definition": strategy.get("Definition", ""),
        }
        for field in _LIST_FIELDS:
            value = strategy.get(field, [])
            out[field] = list(value) if isinstance(value, (list, tuple)) else [value]
        return out

    @staticmethod
    def _merge(a: dict, b: dict) -> dict:
        """Scala dwa wpisy tej samej strategii — Definition z 'a', listy złączone."""
        merged = {"Strategy": a["Strategy"], "Definition": a.get("Definition") or b.get("Definition", "")}
        for field in _LIST_FIELDS:
            merged[field] = list(a.get(field, [])) + list(b.get(field, []))
        return merged

    # --- odczyt ----------------------------------------------------------

    def all(self) -> dict:
        return self.library

    def __len__(self) -> int:
        return len(self.library)

    def to_dict(self) -> dict:
        """Serializowalny stan (do JSON przez logio)."""
        return self.library

    @classmethod
    def from_dict(cls, data: dict | None) -> "Library":
        return cls(library=data or {})
