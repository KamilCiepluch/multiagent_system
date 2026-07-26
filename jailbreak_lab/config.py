"""
Domyślne ustawienia playgroundu (samodzielne, nadpisywalne zmiennymi środowiskowymi).
Trzymamy to osobno od `config.py` z repo, żeby folder był niezależny.
"""

import os

# Adres Ollamy (ten sam host co reszta repo, ale bez importu jej configu).
OLLAMA_BASE_URL = os.environ.get("JB_OLLAMA_URL", "http://localhost:11434")

# Model startowy REPL — można zmienić w locie komendą /model.
DEFAULT_MODEL = os.environ.get("JB_MODEL", "gpt-oss:20b")

# Startowa temperatura. Dla testu GOŁEGO modelu domyślnie 0.8 (natywna Ollamy) — chcemy
# widzieć realne, nie „przyduszone" zachowanie. Zmiana w locie: /temp.
DEFAULT_TEMPERATURE = float(os.environ.get("JB_TEMPERATURE", "0.8"))
