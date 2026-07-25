"""
Fixtures współdzielone przez wszystkie testy.

no_commit_db — patchuje get_conn tak że żadna operacja nie commituje;
               rollback po teście → baza pozostaje czysta.
"""
from contextlib import contextmanager
from unittest.mock import patch

import psycopg2
import pytest

from config import settings


@pytest.fixture
def no_commit_db():
    """
    Otwiera prawdziwe połączenie z bazą i patchuje database.db.get_conn
    tak, by operacje DB w teście nigdy nie commitowały.
    Rollback po zakończeniu testu — baza pozostaje niezmieniona.
    """
    try:
        conn = psycopg2.connect(dsn=settings.db_dsn)
    except Exception as exc:
        pytest.skip(f"Brak połączenia z bazą: {exc}")

    conn.autocommit = False

    @contextmanager
    def _fake_get_conn():
        try:
            yield conn
            # celowo nie commitujemy
        except Exception:
            conn.rollback()
            raise

    with patch("database.db.get_conn", _fake_get_conn):
        yield conn

    conn.rollback()
    conn.close()
