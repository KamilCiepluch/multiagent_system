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

# attack_core/ jest jeden poziom pod korzeniem repo, a katalog `seeds/` leży w
# korzeniu — stąd `.parent.parent` (po przeniesieniu z attack_runner.py z korzenia).
_SEEDS_DIR = Path(__file__).parent.parent / "seeds"

# Podmienialne datasety świata-celu (agent_benchmark). Dataset = uporządkowana lista plików SQL
# (TYLKO ŚWIAT) wykonywanych po TRUNCATE. SKILLE są osobno: jedno źródło prawdy w folderze
# `agent_skills/<agent>/<nazwa>.md`, ładowane przez `database.skills.load_into` po świecie (wspólne
# dla wszystkich datasetów — „skille zostaw"). `default` = oryginalne seedy świata; nowy scenariusz
# = świat w seeds/datasets/<nazwa>/. Wybór datasetu: settings.benchmark_dataset.
DATASETS: dict[str, list[Path]] = {
    "default": [
        _SEEDS_DIR / "email_agent.sql",
        _SEEDS_DIR / "terminal_agent.sql",
        _SEEDS_DIR / "search_agent.sql",
    ],
    "attack_v1": [
        _SEEDS_DIR / "datasets" / "attack_v1" / "email.sql",
        _SEEDS_DIR / "datasets" / "attack_v1" / "terminal.sql",
        _SEEDS_DIR / "datasets" / "attack_v1" / "search.sql",
    ],
}


def seed_files_for(dataset: str | None = None) -> list[Path]:
    """Zwraca uporządkowaną listę plików seed dla datasetu (domyślnie settings.benchmark_dataset)."""
    name = dataset or settings.benchmark_dataset
    if name not in DATASETS:
        raise ValueError(f"Nieznany benchmark dataset '{name}'. Dostępne: {list(DATASETS)}")
    return DATASETS[name]


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

    def reset_main_db(self, dataset: str | None = None) -> None:
        """TRUNCATE CASCADE wszystkich tabel + reseed wybranym datasetem. Restartuje sekwencje ID.

        `dataset` domyślnie z `settings.benchmark_dataset` (env BENCHMARK_DATASET); 'default' =
        oryginalne, niezmienione seedy. Konsumenci (autodan_turbo/target, payload_attack/loop,
        primitives) wołają bez argumentu → przejmują dataset z konfiguracji."""
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
            for seed_file in seed_files_for(dataset):
                sql = seed_file.read_text(encoding="utf-8")
                with conn.cursor() as cur:
                    cur.execute(sql)
                conn.commit()
            # Skille są wspólne dla wszystkich datasetów — ładowane z folderu agent_skills/
            # (jedno źródło prawdy), nie z seedów świata.
            from database import skills
            skills.load_into(conn)
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
                # Run w `logs` MUSI powstać przed wpisem w `audit` — FK
                # audit.attack_invocations.run_id → logs.runs(run_id). run_logger
                # uzupełni potem tryb/szczegóły (create_run jest idempotentne).
                from database import logs_db
                logs_db.create_run(run_id, task, None)
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
