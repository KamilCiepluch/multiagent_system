"""
Konfiguracja logowania dla hyperagent_email — jedno miejsce, w którym ustawia
się obserwowalność całej pętli samodoskonalenia.

Dwa kanały (zgodnie z decyzją operatora):
- KONSOLA (INFO) — czytelny przebieg na żywo: która generacja, który krok,
  werdykt, czasy. Poziom sterowany zmienną HYPERAGENT_EMAIL_LOG_LEVEL.
- PLIK ROTACYJNY (DEBUG) — `hyperagent_email/logs/hyperagent_email.log`,
  pełny ślad każdego kroku każdej generacji wraz z pełnymi traceback'ami,
  z rotacją (5 plików × 5 MB), żeby trwał między uruchomieniami, ale nie rósł
  bez końca.

Cały pakiet loguje przez logger `hyperagent_email` (i jego dzieci, np.
`hyperagent_email.loop`, `hyperagent_email.workspace.agent`). `setup_logging`
jest idempotentne — wielokrotne wywołanie nie dubluje handlerów.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_PACKAGE_LOGGER = "hyperagent_email"
_LOG_DIR = Path(__file__).resolve().parent / "logs"
_LOG_FILE = _LOG_DIR / "hyperagent_email.log"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5

_CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s %(funcName)s:%(lineno)d | %(message)s"
_CONSOLE_DATEFMT = "%H:%M:%S"


def setup_logging(console_level: str | None = None) -> logging.Logger:
    """Konfiguruje (raz) logger pakietu i zwraca go.

    `console_level` nadpisuje poziom konsoli; bez niego brany jest
    HYPERAGENT_EMAIL_LOG_LEVEL, a w ostateczności INFO. Plik zawsze DEBUG.
    """
    logger = logging.getLogger(_PACKAGE_LOGGER)
    logger.setLevel(logging.DEBUG)
    # Nie propagujemy do roota — własne handlery, bez podwójnych wpisów.
    logger.propagate = False
    if logger.handlers:  # już skonfigurowany (idempotencja)
        return logger

    level_name = (console_level or os.getenv("HYPERAGENT_EMAIL_LOG_LEVEL", "INFO")).upper()
    console_level_val = getattr(logging, level_name, logging.INFO)

    console = logging.StreamHandler()
    console.setLevel(console_level_val)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt=_CONSOLE_DATEFMT))
    logger.addHandler(console)

    try:
        _LOG_DIR.mkdir(exist_ok=True)
        file_handler = RotatingFileHandler(
            _LOG_FILE, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        logger.addHandler(file_handler)
        logger.debug("Logowanie do pliku: %s", _LOG_FILE)
    except OSError as exc:
        logger.warning(
            "Nie udało się otworzyć pliku logu %s (%s) — logowanie tylko na konsolę.",
            _LOG_FILE,
            exc,
        )

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Zwraca logger w przestrzeni pakietu (`hyperagent_email[.name]`)."""
    if not name:
        return logging.getLogger(_PACKAGE_LOGGER)
    return logging.getLogger(f"{_PACKAGE_LOGGER}.{name}")
