"""
Uruchamia WSZYSTKIE benchmarki jednym poleceniem i zapisuje wyniki do agents_benchmark_results/.

Każde zadanie → osobny plik:  agents_benchmark_results/<obszar>/<co_testowane>_<YYYY_MM_DD_HH_MM>.txt
Jeden znacznik czasu na cały przebieg (pliki z jednego uruchomienia mają wspólny sufiks).
Przeznaczone do długich (wielogodzinnych) przebiegów: porażka jednego zadania NIE przerywa reszty —
wyjątek ląduje w pliku zadania, a przebieg idzie dalej. Na końcu powstaje manifest _run_<stamp>.txt.

Uruchom:
    python -m agents_benchmark.run_all                 # wszystko
    python -m agents_benchmark.run_all search_agent    # tylko jeden obszar
    python -m agents_benchmark.run_all supervisor:routing e2e   # wybrane zadania
    python -m agents_benchmark.run_all --list          # pokaż listę zadań i wyjdź

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


def run_job(job: Job, stamp: str) -> tuple[str, str, Path, float]:
    out_dir = RESULTS / job.area
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{job.name}_{stamp}.txt"
    start = time.time()
    with path.open("w", encoding="utf-8") as f:
        f.write(f"# benchmark: {job.area}/{job.name}\n# start: {datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
        with contextlib.redirect_stdout(f):
            try:
                summary, status = job.fn(), "OK"
            except Exception:
                summary, status = "wyjątek (traceback powyżej)", "ERROR"
                traceback.print_exc()
        f.write(f"\n# status: {status} | {summary} | {time.time() - start:.0f}s\n")
    return status, summary, path, time.time() - start


def main():
    p = argparse.ArgumentParser(description="Uruchom wszystkie benchmarki i zapisz wyniki ze znacznikiem czasu.")
    p.add_argument("only", nargs="*", help="filtry zadań: '<obszar>' albo '<obszar>:<co>' (np. supervisor:routing, e2e)")
    p.add_argument("--list", action="store_true", help="wypisz zadania i zakończ")
    args = p.parse_args()

    jobs = [j for j in build_jobs() if _matches(j, args.only)]
    if args.list:
        for j in jobs:
            print(f"{j.area}/{j.name}")
        return
    if not jobs:
        p.error("brak zadań pasujących do filtra")

    stamp = datetime.now().strftime("%Y_%m_%d_%H_%M")
    RESULTS.mkdir(parents=True, exist_ok=True)
    print(f"=== run_all | znacznik {stamp} | {len(jobs)} zadań | model {settings.ollama_model} ===")
    start = time.time()
    rows = []
    for i, job in enumerate(jobs, 1):
        print(f"[{i:>2}/{len(jobs)}] {job.area}/{job.name} ...", flush=True)
        status, summary, path, dt = run_job(job, stamp)
        print(f"        {status}  {summary}  ({dt:.0f}s)  -> {path.relative_to(ROOT)}", flush=True)
        rows.append((job.area, job.name, status, summary, dt, path))

    total = time.time() - start
    manifest = RESULTS / f"_run_{stamp}.txt"
    with manifest.open("w", encoding="utf-8") as f:
        f.write(f"run_all | {stamp} | model {settings.ollama_model} | {len(rows)} zadań | {total / 60:.1f} min\n")
        f.write("-" * 72 + "\n")
        for area, name, status, summary, dt, path in rows:
            f.write(f"{status:5} {area + '/' + name:24} {summary}  ({dt:.0f}s)  {path.name}\n")

    errors = sum(1 for r in rows if r[2] != "OK")
    print(f"\n=== koniec | {total / 60:.1f} min | błędy zadań: {errors} | manifest: {manifest.relative_to(ROOT)} ===")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
