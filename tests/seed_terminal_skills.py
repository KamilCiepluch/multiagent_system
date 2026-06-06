"""
Jednorazowy seeder skillów terminal_agent — uruchom raz:
    pytest tests/seed_terminal_skills.py -v -s

Po załadowaniu usuń ten plik.
"""
import psycopg2
import pytest
from config import settings


def test_seed_terminal_agent_skills():
    conn = psycopg2.connect(dsn=settings.db_dsn)
    conn.autocommit = True
    cur = conn.cursor()

    with open("seeds/terminal_agent.sql", "r", encoding="utf-8") as f:
        sql = f.read()

    marker = "-- SKILLE AGENTA TERMINALOWEGO"
    start = sql.find(marker)
    assert start != -1, "Nie znaleziono sekcji skillów w pliku"

    cur.execute(sql[start:])

    cur.execute("SELECT name FROM agent_skills WHERE agent_name = 'terminal_agent' ORDER BY name")
    rows = cur.fetchall()
    names = [r[0] for r in rows]
    print(f"\nZaładowane skille terminal_agent: {names}")
    assert names, "Brak skillów po załadowaniu seeda"

    cur.close()
    conn.close()
