import sys
import psycopg2
from config import settings
print("Python:", sys.version)

conn = psycopg2.connect(dsn=settings.db_dsn)
conn.autocommit = True
cur = conn.cursor()

with open("seeds/terminal_agent.sql", "r", encoding="utf-8") as f:
    sql = f.read()

marker = "-- SKILLE AGENTA TERMINALOWEGO"
start = sql.find(marker)
if start == -1:
    print("BŁĄD: nie znaleziono sekcji skillów")
else:
    skills_sql = sql[start:]
    cur.execute(skills_sql)
    cur.execute("SELECT name FROM agent_skills WHERE agent_name = 'terminal_agent' ORDER BY name")
    rows = cur.fetchall()
    print("OK — załadowane skille terminal_agent:", [r[0] for r in rows])

cur.close()
conn.close()
