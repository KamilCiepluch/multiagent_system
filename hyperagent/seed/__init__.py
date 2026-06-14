"""
Generacja 0 — startowa implementacja hyperagenta.

Te pliki (`main.py`, `tools.py`, `SYSTEM_PROMPT.py`) są kopiowane WPROST jako
płaskie pliki — nie importowane jako pakiet — do `/workspace` nowej sesji
(patrz `hyperagent/archive/store.py:seed_generation`). Dlatego `main.py`
używa "płaskich" importów (`import tools`, `from SYSTEM_PROMPT import ...`):
dokładnie tak wygląda jego świat wewnątrz kontenera, gdzie `python main.py`
odpala się z `/workspace` na `sys.path[0]` (patrz `hyperagent/sandbox/Dockerfile`).

To jest TEN SAM kod, który agent będzie czytał i mutował między rundami —
traktuj go jako działający przykład dobrego startu, nie sztywny szkielet.
"""

from __future__ import annotations

from pathlib import Path

SEED_DIR = Path(__file__).parent

# Kolejność bez znaczenia dla działania — ważne, żeby host (archive/store.py)
# wiedział DOKŁADNIE, co skopiować do świeżego /workspace generacji 0.
SEED_FILES = ["main.py", "tools.py", "SYSTEM_PROMPT.py"]
