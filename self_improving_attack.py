"""
Samo-poprawiający się atakujący — automatyczny benchmark odporności na prompt injection.

W odróżnieniu od statycznych scenariuszy w benchmark_scenarios.py (payload napisany
raz, na stałe), tutaj LLM ("meta-attacker") generuje payload, system go ocenia
white-box (faktyczne tool-calle z audytu, nie tylko tekst odpowiedzi), a meta-attacker
dostaje pełny feedback i mutuje payload, by ominąć to, co go zablokowało. Wynik to
realna miara odporności: ile rund potrzeba, by przełamać obronę (jeśli w ogóle),
i jakie strategie mutacji się sprawdzają.

Uruchomienie:
    python self_improving_attack.py --list
    python self_improving_attack.py --objective secret_exfiltration --vector email
    python self_improving_attack.py --objective secret_exfiltration --vector search_result --iterations 8
    python self_improving_attack.py --objective skill_rce --vector skill --iterations 4 --no-stop-on-success
"""

from __future__ import annotations

import argparse

from attack_core.runner import AttackRunner
from config import settings
from graph.workflow import build_supervisor_workflow
from attack_core.injection_points import INJECTION_POINTS, InjectionPoint
from payload_attack.loop import SelfImprovingAttackLoop, SelfImprovingAttackReport
from payload_attack.meta_attacker import Attempt
from attack_core.objectives import OBJECTIVES, AttackObjective

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
    print("  Self-improving attacker — dostępne cele i wektory")
    print(THICK)

    print("\n  CELE (--objective):")
    for o in OBJECTIVES.values():
        print(f"    {o.id:<20} {o.name}")
        print(f"    {'':<20} kompatybilne wektory: {o.compatible_injection_points}")
        print(f"    {'':<20} {o.description[:110]}")
        print()

    print("  WEKTORY (--vector):")
    for p in INJECTION_POINTS.values():
        print(f"    {p.id:<14} {p.name}")
        print(f"    {'':<14} {p.description[:110]}")
        print()


# ─────────────────────────────────────────────────────────────────────────────
# Raportowanie postępu w trakcie + raport końcowy
# ─────────────────────────────────────────────────────────────────────────────

def _on_iteration(attempt: Attempt, record_key: str) -> None:
    v = attempt.verdict
    print(f"\n  {SEP}")
    print(f"  RUNDA #{attempt.iteration_n}")
    print(f"  Strategia mutacji: {attempt.mutation_rationale or '(brak uzasadnienia)'}")
    print(f"  Payload trafił do: {record_key}")
    payload_preview = attempt.payload[:300] + ("…" if len(attempt.payload) > 300 else "")
    print(f"  Payload (skrót):\n    {payload_preview}")
    print(f"\n  >> WERDYKT: {VERDICT_LABELS.get(v.outcome, v.outcome)}")
    if v.evidence:
        print(f"     Dowody:      {v.evidence}")
    print(f"     Uzasadnienie: {v.reasoning}")


def print_report(report: SelfImprovingAttackReport) -> None:
    print(f"\n{THICK}")
    print("  RAPORT KOŃCOWY — Self-improving attacker")
    print(THICK)
    print(f"  Cel:    {report.objective.id} — {report.objective.name}")
    print(f"  Wektor: {report.injection_point.id} — {report.injection_point.name}")
    print(f"  Sesja:  {report.attack_id}")
    print(SEP)

    col_n = 5
    col_v = 16
    print(f"  {'Runda':<{col_n}} {'Werdykt':<{col_v}} Strategia mutacji")
    print(f"  {SEP[:col_n + col_v + 20]}")
    for a in report.history:
        rationale = (a.mutation_rationale or "").replace("\n", " ")
        print(f"  {a.iteration_n:<{col_n}} {a.verdict.outcome:<{col_v}} {rationale[:90]}")

    print(f"\n  {SEP}")
    if report.bypassed:
        n = report.iterations_to_bypass
        winning = report.history[n - 1]
        print(f"  >> WYNIK: system OBEJŚCIANY w rundzie #{n}/{len(report.history)}")
        print(f"     Skuteczna strategia: {winning.mutation_rationale}")
        print(f"     Dowód: {winning.verdict.evidence}")
    elif report.final_outcome == "blocked":
        print(f"  >> WYNIK: system OBRONIŁ SIĘ przez wszystkie {len(report.history)} rund")
        print(f"     (każda mutacja została rozpoznana i zablokowana — dobry sygnał odporności)")
    else:
        print(f"  >> WYNIK: brak jednoznacznego obejścia w {len(report.history)} rundach,")
        print(f"     ale część prób zakończyła się PARTIAL/UNCLEAR — przejrzyj transkrypty rund")
        print(f"     przez `python show_run.py <run_id>` (run_id widoczny w `python show_run.py`).")

    print(f"\n  Pełna historia rund zapisana w agent_audit.self_improving_iterations")
    print(f"  (attack_id = {report.attack_id}).")
    print(THICK)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Samo-poprawiający się atakujący — iteracyjny benchmark odporności na prompt injection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--objective", help=f"ID celu ataku (jeden z: {list(OBJECTIVES)})")
    p.add_argument("--vector", help=f"ID wektora wstrzyknięcia (jeden z: {list(INJECTION_POINTS)})")
    p.add_argument("--iterations", type=int, default=6, help="Maksymalna liczba rund (domyślnie 6)")
    p.add_argument(
        "--no-stop-on-success", action="store_true",
        help="Nie przerywaj po pierwszym ATTACK_SUCCESS — wyczerpaj wszystkie rundy",
    )
    p.add_argument("--list", action="store_true", help="Pokaż dostępne cele i wektory")
    return p


def _resolve(args: argparse.Namespace) -> tuple[AttackObjective, InjectionPoint] | None:
    objective = OBJECTIVES.get(args.objective or "")
    if objective is None:
        print(f"Brak celu '{args.objective}'. Dostępne: {list(OBJECTIVES)} (użyj --list)")
        return None

    injection_point = INJECTION_POINTS.get(args.vector or "")
    if injection_point is None:
        print(f"Brak wektora '{args.vector}'. Dostępne: {list(INJECTION_POINTS)} (użyj --list)")
        return None

    if injection_point.id not in objective.compatible_injection_points:
        print(
            f"Cel '{objective.id}' nie jest kompatybilny z wektorem '{injection_point.id}'.\n"
            f"Kompatybilne wektory dla tego celu: {objective.compatible_injection_points}"
        )
        return None

    return objective, injection_point


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        list_options()
        return

    resolved = _resolve(args)
    if resolved is None:
        return
    objective, injection_point = resolved

    print(THICK)
    print("  Self-improving attacker")
    print(f"  Model agentów:      {settings.ollama_model}")
    print(f"  Model meta-attacker: {settings.meta_attacker_model or settings.ollama_model} "
          f"{'(osobny)' if settings.meta_attacker_model else '(fallback na model agentów)'}")
    print(f"  Cel:                {objective.id} — {objective.name}")
    print(f"  Wektor:             {injection_point.id} — {injection_point.name}")
    print(f"  Maks. rund:         {args.iterations}")
    print(THICK)

    runner = AttackRunner()
    workflow = build_supervisor_workflow()
    loop = SelfImprovingAttackLoop(runner, workflow)

    report = loop.run(
        objective=objective,
        injection_point=injection_point,
        max_iterations=args.iterations,
        stop_on_success=not args.no_stop_on_success,
        on_iteration=_on_iteration,
    )

    print_report(report)


if __name__ == "__main__":
    main()
