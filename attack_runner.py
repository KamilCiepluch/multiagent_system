"""
Zarządza lifecycle testów ataków: reset agents_db → start → N wywołań → finish.

API:
    runner = AttackRunner()
    runner.reset_main_db()

    attack_id = runner.start_attack("prompt_injection_via_log", "prompt_injection")

    with runner.invocation(attack_id, task="Sprawdź logi systemowe") as run_id:
        result = workflow.invoke({"task": "Sprawdź logi systemowe", "run_id": run_id})

    runner.finish_attack(attack_id, outcome="succeeded")
"""

import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg2

from config import settings
from database import audit_db
from tracing.run_context import set_invocation_id, set_run_id

_SEEDS_DIR = Path(__file__).parent / "seeds"

_SEED_FILES = [
    _SEEDS_DIR / "email_agent.sql",
    _SEEDS_DIR / "terminal_agent.sql",
    _SEEDS_DIR / "search_agent.sql",
]


class AttackRunner:
    def __init__(self):
        self._audit_ok = self._check_audit_db()

    def _check_audit_db(self) -> bool:
        """Sprawdza czy audit DB jest dostępna i ma właściwy schemat."""
        try:
            with audit_db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM attack_runs LIMIT 1")
            return True
        except Exception as e:
            print(
                f"\n[AttackRunner] UWAGA: Audit DB niedostępna — {e}\n"
                f"  Sprawdź czy agent_audit istnieje i schema jest zaaplikowana:\n"
                f"    docker-compose down -v && docker-compose up -d\n"
                f"  Lub ręcznie:\n"
                f"    createdb -U postgres agent_audit\n"
                f"    psql -U postgres -d agent_audit -f database/schema_audit.sql\n"
                f"  Workflow uruchomi się bez trackingu w agent_audit.\n"
            )
            return False

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset_main_db(self) -> None:
        """TRUNCATE CASCADE wszystkich tabel + reseed. Restartuje sekwencje ID."""
        conn = psycopg2.connect(dsn=settings.db_dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    TRUNCATE TABLE
                        emails, email_contacts, tools_outputs,
                        agent_skills, repositories, github_sources,
                        files, tickets, search_results, search_sources, meetings
                    RESTART IDENTITY CASCADE
                    """
                )
            conn.commit()
            for seed_file in _SEED_FILES:
                sql = seed_file.read_text(encoding="utf-8")
                with conn.cursor() as cur:
                    cur.execute(sql)
                conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Attack lifecycle
    # ------------------------------------------------------------------

    def start_attack(
        self,
        name: str,
        attack_type: str | None = None,
        description: str | None = None,
    ) -> str:
        """Rejestruje atak w audit DB, zwraca attack_id (UUID)."""
        if not self._audit_ok:
            return str(uuid.uuid4())
        try:
            attack_id = audit_db.start_attack(name, attack_type, description)
            print(f"[AttackRunner] Atak zarejestrowany: {attack_id}")
            return attack_id
        except Exception as e:
            print(f"[AttackRunner] Błąd start_attack: {e}")
            return str(uuid.uuid4())

    def finish_attack(self, attack_id: str, outcome: str) -> None:
        """Zamyka rekord ataku z wynikiem: succeeded | blocked | partial | error | unknown."""
        if not self._audit_ok:
            return
        try:
            audit_db.finish_attack(attack_id, outcome)
            print(f"[AttackRunner] Atak zakończony ({outcome}): {attack_id}")
        except Exception as e:
            print(f"[AttackRunner] Błąd finish_attack: {e}")

    @contextmanager
    def invocation(self, attack_id: str, task: str):
        """
        Context manager dla jednego wywołania w ramach ataku.
        Ustawia invocation_id i run_id w ContextVar — db.py automatycznie
        loguje wszystkie zmiany DB do audit pod tym invocation_id.

        Użycie:
            with runner.invocation(attack_id, task="...") as run_id:
                workflow.invoke({"task": "...", "run_id": run_id})
        """
        run_id = str(uuid.uuid4())
        invocation_id = None

        if self._audit_ok:
            try:
                n = audit_db.next_invocation_n(attack_id)
                invocation_id = audit_db.start_invocation(attack_id, n, run_id, task)
                print(f"[AttackRunner] Invocation #{n} start (id={invocation_id})")
            except Exception as e:
                print(f"[AttackRunner] Błąd start_invocation: {e}")

        set_run_id(run_id)
        set_invocation_id(invocation_id)
        try:
            yield run_id
        finally:
            set_invocation_id(None)
            if invocation_id is not None:
                try:
                    audit_db.finish_invocation(invocation_id)
                    print(f"[AttackRunner] Invocation #{invocation_id} zakończona")
                except Exception as e:
                    print(f"[AttackRunner] Błąd finish_invocation: {e}")
