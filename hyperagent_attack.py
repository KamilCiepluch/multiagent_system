"""
Hyperagent — agent atakujący, który prawdziwie modyfikuje WŁASNY kod Pythona
między rundami (true source-code self-modification, jak w oryginalnym
HyperAgents — w odróżnieniu od `self_improving_attack.py`, gdzie mutowany
jest tekstowy payload, a kod pętli jest stały).

W odróżnieniu od `self_improving_attack.py` nie podajesz wektora wstrzyknięcia
z góry — hyperagent sam decyduje, jak rozpocząć atak (ma do dyspozycji wszystkie
prymitywy gatewaya: inject_email/poison_skill/poison_search_result/...) i może
między generacjami przepisać własny kod, włącznie z orkiestracją.

Uruchomienie:
    python hyperagent_attack.py --list
    python hyperagent_attack.py --objective secret_exfiltration --generations 6
    python hyperagent_attack.py --objective skill_rce --generations 4 --parent-selection best_score
    python hyperagent_attack.py --objective secret_exfiltration --no-stop-on-success
"""

from __future__ import annotations

import argparse

from attack_core.runner import AttackRunner
from config import settings
from hyperagent.archive.store import PARENT_SELECTION_STRATEGIES
from hyperagent.loop import GenerationOutcome, HyperagentLoop, HyperagentReport
from attack_core.objectives import OBJECTIVES, AttackObjective
from hyperagent.sandbox import runner as sandbox

SEP = "─" * 72
THICK = "═" * 72

VERDICT_LABELS = {
    "BLOCKED":       "BLOCKED       — system rozpoznał próbę i odmówił/eskalował",
    "ATTACK_SUCCESS": "ATTACK_SUCCESS — cel ataku faktycznie zrealizowany (ground truth)",
    "PARTIAL":       "PARTIAL       — część celu zrealizowana",
    "UNCLEAR":       "UNCLEAR       — niejednoznaczne, sprawdź transkrypt ręcznie",
}


# ─────────────────────────────────────────────────────────────────────────────
# Listowanie
# ─────────────────────────────────────────────────────────────────────────────

def list_options() -> None:
    print(THICK)
    print("  Hyperagent — dostępne cele")
    print(THICK)

    print("\n  CELE (--objective):")
    for o in OBJECTIVES.values():
        print(f"    {o.id:<20} {o.name}")
        print(f"    {'':<20} {o.description}")
        print()

    print("  Hyperagent SAM dobiera wektor wstrzyknięcia spośród prymitywów")
    print("  gatewaya (inject_email / poison_skill / poison_search_result / ...)")
    print("  — w odróżnieniu od self_improving_attack.py nie podajesz go z góry.")
    print(f"\n  Strategie wyboru rodzica (--parent-selection): {list(PARENT_SELECTION_STRATEGIES)}")


# ─────────────────────────────────────────────────────────────────────────────
# Setup sandboxa — sieć (z compose) + obrazy (budowane na żądanie)
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_sandbox_ready() -> bool:
    if not sandbox.network_exists():
        print(
            "  Sieć Dockera 'hyperagent_net' jeszcze nie istnieje. Najpierw odpal:\n"
            "      docker compose -f docker-compose.hyperagent.yml up -d\n"
        )
        return False
    if not sandbox.image_exists():
        print("  Obraz agenta nie istnieje — buduję (jednorazowo, może chwilę potrwać)...")
        sandbox.build_agent_image()
    if not sandbox.gateway_image_exists():
        print("  Obraz gatewaya nie istnieje — buduję (jednorazowo, może chwilę potrwać)...")
        sandbox.build_gateway_image()
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Raportowanie postępu w trakcie + raport końcowy
# ─────────────────────────────────────────────────────────────────────────────

def _on_generation(outcome: GenerationOutcome) -> None:
    g = outcome.generation
    parent_label = f"gen {g.parent_n}" if g.parent_n is not None else "(seed)"
    print(f"\n  {SEP}")
    print(f"  GENERACJA #{g.generation_n}  (rodzic: {parent_label})")
    print(f"  Przebiegów run_target_task w tej generacji: {len(outcome.run_ids)}")
    sandbox_state = "ok" if outcome.sandbox_result.ok else "NIEPRAWIDŁOWE zakończenie"
    if outcome.sandbox_result.timed_out:
        sandbox_state += " (timeout — agent zabity po przekroczeniu limitu)"
    print(f"  Sandbox: {sandbox_state}")

    if outcome.best_verdict is not None:
        v = outcome.best_verdict
        print(f"\n  >> NAJLEPSZY WERDYKT TEJ GENERACJI: {VERDICT_LABELS.get(v.outcome, v.outcome)}")
        if v.evidence:
            print(f"     Dowody:      {v.evidence}")
        print(f"     Uzasadnienie: {v.reasoning}")
    else:
        print("\n  >> Agent ani razu nie odpalił run_target_task w tej generacji — brak czego oceniać.")


def print_report(report: HyperagentReport) -> None:
    print(f"\n{THICK}")
    print("  RAPORT KOŃCOWY — Hyperagent")
    print(THICK)
    print(f"  Cel:                       {report.objective.id} — {report.objective.name}")
    print(f"  Sesja:                     {report.session_id}")
    print(f"  Strategia wyboru rodzica:  {report.parent_selection}")
    print(SEP)

    col_n, col_p, col_v = 6, 10, 16
    print(f"  {'Gen':<{col_n}} {'Rodzic':<{col_p}} {'Werdykt':<{col_v}} Przebiegi")
    print(f"  {SEP[:col_n + col_p + col_v + 14]}")
    for r in report.rounds:
        g = r.generation
        parent_label = str(g.parent_n) if g.parent_n is not None else "—"
        verdict_label = r.best_verdict.outcome if r.best_verdict is not None else "(brak prób)"
        print(f"  {g.generation_n:<{col_n}} {parent_label:<{col_p}} {verdict_label:<{col_v}} {len(r.run_ids)}")

    print(f"\n  {SEP}")
    if report.bypassed:
        n = report.generation_to_bypass
        winning = next(r for r in report.rounds if r.generation.generation_n == n)
        print(f"  >> WYNIK: system OBEJŚCIANY w generacji #{n}/{len(report.rounds)}")
        print(f"     Dowód: {winning.best_verdict.evidence}")
    elif report.final_outcome == "blocked":
        print(f"  >> WYNIK: system OBRONIŁ SIĘ przez wszystkie {len(report.rounds)} generacji")
        print("     (każda próba została rozpoznana i zablokowana — dobry sygnał odporności)")
    elif report.final_outcome == "partial":
        print(f"  >> WYNIK: brak jednoznacznego obejścia w {len(report.rounds)} generacjach,")
        print("     ale część prób zakończyła się PARTIAL/UNCLEAR — przejrzyj transkrypty")
        print("     przez `python show_run.py <run_id>`.")
    else:
        print("  >> WYNIK: sesja zakończyła się przed wykonaniem jakiejkolwiek generacji.")

    if report.best_round is not None:
        b = report.best_round
        print(
            f"\n  Najlepsza generacja w całej sesji: #{b.generation.generation_n} "
            f"({b.best_verdict.outcome})"
        )

    print(f"\n  Pełna historia generacji (kod + wyniki + rodowód) zapisana w")
    print(f"  agent_audit.hyperagent_generations (session_id = {report.session_id}).")
    print(f"  Bezwarunkowy log każdej interakcji agenta z gatewayem — w")
    print(f"  agent_audit.hyperagent_gateway_log.")
    print(THICK)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Hyperagent — agent atakujący, który mutuje WŁASNY kod Pythona między rundami.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--objective", help=f"ID celu ataku (jeden z: {list(OBJECTIVES)})")
    p.add_argument("--generations", type=int, default=5, help="Maksymalna liczba generacji (domyślnie 5)")
    p.add_argument(
        "--parent-selection", choices=PARENT_SELECTION_STRATEGIES, default="latest",
        help="Strategia wyboru rodzica następnej generacji (domyślnie 'latest')",
    )
    p.add_argument(
        "--no-stop-on-success", action="store_true",
        help="Nie przerywaj po pierwszym ATTACK_SUCCESS — wyczerp wszystkie generacje",
    )
    p.add_argument("--list", action="store_true", help="Pokaż dostępne cele")
    return p


def _resolve(args: argparse.Namespace) -> AttackObjective | None:
    objective = OBJECTIVES.get(args.objective or "")
    if objective is None:
        print(f"Brak celu '{args.objective}'. Dostępne: {list(OBJECTIVES)} (użyj --list)")
        return None
    return objective


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        list_options()
        return

    objective = _resolve(args)
    if objective is None:
        return

    if not _ensure_sandbox_ready():
        return

    print(THICK)
    print("  Hyperagent")
    print(f"  Model agenta:        {settings.hyperagent_model or settings.ollama_model} "
          f"{'(osobny, przez gateway)' if settings.hyperagent_model else '(fallback na model agentów, przez gateway)'}")
    print(f"  Cel:                 {objective.id} — {objective.name}")
    print(f"  Maks. generacji:     {args.generations}")
    print(f"  Wybór rodzica:       {args.parent_selection}")
    print(THICK)

    runner = AttackRunner()
    loop = HyperagentLoop(runner, objective)

    report = loop.run(
        max_generations=args.generations,
        parent_selection=args.parent_selection,
        stop_on_success=not args.no_stop_on_success,
        on_generation=_on_generation,
    )

    print_report(report)


if __name__ == "__main__":
    main()
