"""
Uruchamia WSZYSTKIE benchmarki jednym poleceniem i zapisuje wyniki do agents_benchmark_results/.

JEDEN BIEG = JEDEN FOLDER (łatwo szukać po runach, podział na daty):
    agents_benchmark_results/runs/<YYYY-MM-DD>/<HH-MM>_<model>_think-<on|off>/
        _console.txt                 ← postęp całego biegu (to samo co na ekranie)
        _manifest.txt                ← podsumowanie + nagłówek: data | model | thinking | num_ctx
        <obszar>/<co_testowane>.txt  ← każde zadanie; w nagłówku data, model, tryb thinking
Data/model/tryb są w NAZWIE folderu ORAZ w nagłówku każdego pliku. Przeznaczone do długich
przebiegów: porażka jednego zadania NIE przerywa reszty (wyjątek ląduje w pliku zadania).

Uruchom:
    python -m agents_benchmark.run_all                              # wszystko (model/thinking z .env)
    python -m agents_benchmark.run_all --model qwen3.6:35b --thinking on
    python -m agents_benchmark.run_all search_agent --thinking off  # jeden obszar, bez reasoningu
    python -m agents_benchmark.run_all supervisor:routing e2e       # wybrane zadania
    python -m agents_benchmark.run_all --list                       # pokaż listę zadań i wyjdź

Wymaga: PostgreSQL (agent_benchmark) + Ollama — jak pojedyncze benchmarki.
"""

import argparse
import contextlib
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import settings
from agents.search_agent import SearchAgent
from agents.email_agent import EmailAgent
from agents.terminal_agent import TerminalAgent
from agents_benchmark.harness import run_suite, build_supervisor, supervisor_frame
from agents_benchmark.search_agent import cases as search_cases
from agents_benchmark.email_agent import cases as email_cases
from agents_benchmark.terminal_agent import cases as terminal_cases
from agents_benchmark.supervisor import cases as supervisor_cases
from agents_benchmark.e2e import run as e2e_run

BENCH = ROOT / "agents_benchmark"
RESULTS = ROOT / "agents_benchmark_results"
RUNS = RESULTS / "runs"   # nowe biegi: runs/<data>/<godz>_<model>_think-<on|off>/ (jeden bieg = jeden folder)


class _Tee:
    """Pisze jednocześnie na ekran i do pliku konsoli biegu."""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
        return len(s)

    def flush(self):
        for st in self.streams:
            st.flush()


@contextlib.contextmanager
def _tee_stdout(f):
    orig = sys.stdout
    sys.stdout = _Tee(orig, f)
    try:
        yield
    finally:
        sys.stdout = orig

PER_AGENT = (
    ("search_agent", SearchAgent, search_cases),
    ("email_agent", EmailAgent, email_cases),
    ("terminal_agent", TerminalAgent, terminal_cases),
)
PER_AGENT_GROUPS = (
    ("tools", "TOOL_CASES"),
    ("skills", "SKILL_CASES"),
    ("roles", "ROLE_CASES"),
    ("permissions", "PERMISSION_CASES"),
)
SUPERVISOR_GROUPS = (
    ("routing", "ROUTING_CASES"),
    ("verify", "VERIFY_CASES"),
    ("orchestration", "ORCHESTRATION_CASES"),
    ("synthesis", "SYNTHESIS_CASES"),
    ("security", "SECURITY_CASES"),
)


@dataclass
class Job:
    area: str            # podkatalog w wynikach
    name: str            # nazwa pliku (co testowane)
    fn: Callable[[], str]  # wykonuje benchmark (drukuje raport na stdout) i zwraca jednoliniowe podsumowanie


def _suite_summary(results) -> str:
    full = sum(r.ok for r in results)
    passed = sum(r.passed for r in results)
    total = sum(r.total for r in results)
    return f"{full}/{len(results)} przypadków pełnych; {passed}/{total} przebiegów PASS"


def _e2e_summary(checks) -> str:
    passed = sum(c.ok for c in checks)
    return f"{passed}/{len(checks)} sprawdzeń PASS"


def build_jobs() -> list[Job]:
    jobs: list[Job] = []
    for area, cls, mod in PER_AGENT:
        seed = BENCH / area / "seed.sql"
        for group, attr in PER_AGENT_GROUPS:
            cases_list = getattr(mod, attr)
            jobs.append(Job(area, group,
                            lambda c=cls, s=seed, cl=cases_list: _suite_summary(run_suite(c, s, cl))))
    sup_seed = BENCH / "supervisor" / "seed.sql"
    for group, attr in SUPERVISOR_GROUPS:
        cases_list = getattr(supervisor_cases, attr)
        jobs.append(Job("supervisor", group,
                        lambda cl=cases_list, s=sup_seed: _suite_summary(
                            run_suite(None, s, cl, build_fn=build_supervisor, frame=supervisor_frame))))
    jobs.append(Job("e2e", "agents", lambda: _e2e_summary(e2e_run.run_agents_phase())))
    jobs.append(Job("e2e", "process", lambda: _e2e_summary(e2e_run.run_process_phase())))
    return jobs


def _matches(job: Job, filters: list[str]) -> bool:
    if not filters:
        return True
    keys = {job.area, job.name, f"{job.area}:{job.name}", f"{job.area}/{job.name}"}
    return any(f in keys for f in filters)


def run_job(job: Job, run_dir: Path, meta: str) -> tuple[str, str, Path, float]:
    out_dir = run_dir / job.area
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{job.name}.txt"
    start = time.time()
    with path.open("w", encoding="utf-8") as f:
        f.write(f"# benchmark: {job.area}/{job.name}\n# {meta}\n"
                f"# start: {datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
        with contextlib.redirect_stdout(f):
            try:
                summary, status = job.fn(), "OK"
            except Exception:
                summary, status = "wyjątek (traceback powyżej)", "ERROR"
                traceback.print_exc()
        f.write(f"\n# status: {status} | {summary} | {time.time() - start:.0f}s\n")
    return status, summary, path, time.time() - start


def main():
    p = argparse.ArgumentParser(description="Uruchom benchmarki i zapisz wyniki jako jeden bieg = jeden folder (data/model/thinking).")
    p.add_argument("only", nargs="*", help="filtry zadań: '<obszar>' albo '<obszar>:<co>' (np. supervisor:routing, e2e)")
    p.add_argument("--list", action="store_true", help="wypisz zadania i zakończ")
    p.add_argument("--model", default=None, help="model do testu (domyślnie z .env/OLLAMA_MODEL)")
    p.add_argument("--thinking", choices=["on", "off"], default=None,
                   help="tryb reasoning (domyślnie z .env/CAPTURE_THINKING); off dla modeli nie-rozumujących")
    args = p.parse_args()

    # Flagi nadpisują konfigurację na czas biegu (build_system_llm czyta settings przy budowie agenta).
    if args.model:
        settings.ollama_model = args.model
    if args.thinking:
        settings.capture_thinking = (args.thinking == "on")

    jobs = [j for j in build_jobs() if _matches(j, args.only)]
    if args.list:
        for j in jobs:
            print(f"{j.area}/{j.name}")
        return
    if not jobs:
        p.error("brak zadań pasujących do filtra")

    now = datetime.now()
    think = "on" if settings.capture_thinking else "off"
    model_safe = settings.ollama_model.replace(":", "-").replace("/", "-")
    meta = f"model: {settings.ollama_model} | thinking: {think} | num_ctx: {settings.ollama_num_ctx}"
    run_dir = RUNS / f"{now:%Y-%m-%d}" / f"{now:%H-%M}_{model_safe}_think-{think}"
    run_dir.mkdir(parents=True, exist_ok=True)

    errors = 0
    start = time.time()
    rows = []
    with (run_dir / "_console.txt").open("w", encoding="utf-8") as cf, _tee_stdout(cf):
        print(f"=== run_all | {now:%Y-%m-%d %H:%M} | {meta} | {len(jobs)} zadań ===")
        print(f"    folder: {run_dir.relative_to(ROOT)}")
        for i, job in enumerate(jobs, 1):
            print(f"[{i:>2}/{len(jobs)}] {job.area}/{job.name} ...", flush=True)
            status, summary, path, dt = run_job(job, run_dir, meta)
            print(f"        {status}  {summary}  ({dt:.0f}s)  -> {path.relative_to(run_dir)}", flush=True)
            rows.append((job.area, job.name, status, summary, dt, path))

        total = time.time() - start
        with (run_dir / "_manifest.txt").open("w", encoding="utf-8") as f:
            f.write(f"run_all | {now:%Y-%m-%d %H:%M} | {meta} | {len(rows)} zadań | {total / 60:.1f} min\n")
            f.write("-" * 72 + "\n")
            for area, name, status, summary, dt, path in rows:
                f.write(f"{status:5} {area + '/' + name:24} {summary}  ({dt:.0f}s)\n")

        errors = sum(1 for r in rows if r[2] != "OK")
        print(f"\n=== koniec | {total / 60:.1f} min | błędy zadań: {errors} | {run_dir.relative_to(ROOT)} ===")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
