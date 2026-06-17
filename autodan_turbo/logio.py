"""
Trwałość artefaktów przebiegu — JSON w `autodan_turbo/logs/`.

AutoDAN-Turbo (oryginał) trzyma bibliotekę strategii i logi jako pliki JSON i przenosi
je między etapami (warm-up zapisuje → lifelong wczytuje+rozwija → test wczytuje
zamrożoną). Robimy tak samo — biblioteka tego wiernego bloczka jest CELOWO niezależna
od pgvera `agent_audit.attack_strategies` (tamta tabela jest dla przyszłej, zintegrowanej
syntezy, nie dla tej reprodukcji metody).
"""

from __future__ import annotations

import json
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"


def _path(name: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / name


def save_json(name: str, data) -> Path:
    """Zapisuje `data` jako JSON do `logs/<name>` (UTF-8, wcięcia, bez ASCII-escape)."""
    path = _path(name)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_json(name: str, default=None):
    """Wczytuje `logs/<name>` lub zwraca `default`, gdy plik nie istnieje."""
    path = LOG_DIR / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def library_filename(objective_id: str, injection_id: str) -> str:
    """Stabilna nazwa pliku biblioteki dla pary cel/wektor (współdzielona przez etapy)."""
    return f"strategy_library__{objective_id}__{injection_id}.json"
