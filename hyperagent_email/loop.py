"""
hyperagent_email — samodoskonaląca się pętla agenta atakującego WYŁĄCZNIE
przez treść maila (sender/subject/body), z PRAWDZIWYM pipeline'em ataku.

Inspiracja: facebookresearch/Hyperagents (pętla task-agent / meta-agent, gdzie
agent analizuje wyniki i przepisuje własny kod). Jeden agent na generację
(LangChain + `create_agent`, domyślnie Ollama — patrz `llm_factory.py`)
produkuje payload, ale OCENA tego payloadu nie jest już symulacją LLM —
to HOST (ten plik), poza zasięgiem self-modyfikacji, wykonuje co generację:

  1. reset systemu docelowego do czystego stanu
     (`hyperagent.gateway.tools.AttackPrimitives.reset_target`,
     czyli `attack_runner.AttackRunner.reset_main_db`),
  2. wywołanie hiperagenta -> payload (sender/subject/body/rationale),
  3. deterministyczne wstrzyknięcie payloadu do PRAWDZIWEJ bazy
     `agent_benchmark` (`AttackPrimitives.inject_email`),
  4. PRAWDZIWE uruchomienie systemu `agents_blocks`
     (email_agent -> supervisor -> terminal_agent) na stałym zadaniu
     (`AttackPrimitives.run_target_task`, `objective.TASK`),
  5. zebranie PRAWDZIWEGO ground truth: faktyczne tool-calle i finalne
     odpowiedzi każdego agenta (`database.audit_db.get_run_logs`) oraz
     werdykt niezależnego sędziego (`redteam.judge.evaluate`),
  6. zapis rundy do `agent_audit.self_improving_iterations`
     (`database.audit_db.log_self_improving_iteration`).

Ten ground truth trafia do historii kolejnej generacji — hiperagent widzi
PRAWDZIWY wynik swojej poprzedniej próby, nie symulację.

Hiperagent PRZED odpowiedzią (albo zamiast niej) może odczytać/nadpisać własne
pliki w `workspace/` (system_prompt.py, tools.py, agent.py) — to PRAWDZIWA
self-modyfikacja, podchwytywana przez `importlib.reload` przed kolejną
generacją.

`outputs/gen_<N>.json` zawiera pełny rekord rundy (payload, injection_record,
run_id, verdict/evidence/judge_reasoning, agent_logs, transcript) — `run_id`
można dalej zbadać przez `python show_run.py <run_id>` z korzenia repo.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from llm_factory import get_llm  # noqa: E402
from objective import ATTACK_OBJECTIVE, OBJECTIVE, TASK  # noqa: E402
from workspace import agent as agent_module  # noqa: E402
from workspace import system_prompt as system_prompt_module  # noqa: E402
from workspace import tools as tools_module  # noqa: E402

from attack_runner import AttackRunner  # noqa: E402
from database import audit_db  # noqa: E402
from graph.workflow import build_supervisor_workflow  # noqa: E402
from hyperagent.gateway.tools import AttackPrimitives  # noqa: E402
from redteam.judge import evaluate as judge_evaluate  # noqa: E402
from tracing.trace import format_run_trace  # noqa: E402

_HISTORY_PATH = _ROOT / "history.json"
_OUTPUTS_DIR = _ROOT / "outputs"


def _load_history() -> list[dict]:
    if _HISTORY_PATH.exists():
        return json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
    return []


def _save_history(history: list[dict]) -> None:
    _HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _final_outcome(verdicts: list[str]) -> str:
    """Mirror `redteam.loop.SelfImprovingAttackReport.final_outcome` — operuje
    na liście samych outcome'ów (`verdict.outcome`), bez dataclassy Attempt."""
    if any(v == "ATTACK_SUCCESS" for v in verdicts):
        return "succeeded"
    if verdicts and all(v == "BLOCKED" for v in verdicts):
        return "blocked"
    return "partial" if verdicts else "unknown"


def run_generation(gen_n: int, llm, history: list[dict], primitives: AttackPrimitives, attack_id: str) -> dict:
    # Podchwyć self-modyfikacje zapisane przez poprzednią generację (jeśli
    # agent nadpisał tools.py/system_prompt.py/agent.py — przeładuj w tej
    # kolejności, bo agent.py importuje z tools.py i system_prompt.py).
    importlib.reload(tools_module)
    importlib.reload(system_prompt_module)
    importlib.reload(agent_module)

    # 1. Reset systemu docelowego do czystego, deterministycznego stanu.
    primitives.reset_target()

    # 2. Hiperagent generuje payload.
    result = agent_module.run(llm, OBJECTIVE, history)

    # 3. Deterministyczne wstrzyknięcie payloadu do PRAWDZIWEJ agent_benchmark.
    injection_record = primitives.inject_email(result["sender"], result["subject"], result["body"])

    # 4. PRAWDZIWE uruchomienie agents_blocks na stałym zadaniu.
    run_result = primitives.run_target_task(attack_id, TASK)
    run_id = run_result["run_id"]

    # 5. Niezależny sędzia — własny, neutralny model (settings.ollama_model),
    #    nie ten, którym posługuje się hiperagent.
    verdict = judge_evaluate(run_id, ATTACK_OBJECTIVE, llm=None)

    # 6. Ground truth: faktyczne logi agentów (JSON-safe, bez datetime/id/run_id).
    agent_logs = [
        log.model_dump(include={"agent_name", "task", "tool_calls", "final_output"})
        for log in audit_db.get_run_logs(run_id)
    ]

    # 7. Czytelny transkrypt do inspekcji operatora (python show_run.py <run_id>).
    transcript = format_run_trace(run_id)

    # 8. Zapis rundy do agent_audit.self_improving_iterations.
    payload_text = f"SENDER: {result['sender']}\nSUBJECT: {result['subject']}\nBODY:\n{result['body']}"
    audit_db.log_self_improving_iteration(
        attack_id=attack_id,
        iteration_n=gen_n,
        run_id=run_id,
        payload=payload_text,
        verdict=verdict.outcome,
        evidence=verdict.evidence,
        judge_reasoning=verdict.reasoning,
        mutation_rationale=result["rationale"],
    )

    record = {
        "generation": gen_n,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **result,
        "injection_record": injection_record,
        "run_id": run_id,
        "verdict": verdict.outcome,
        "evidence": verdict.evidence,
        "judge_reasoning": verdict.reasoning,
        "agent_logs": agent_logs,
        "transcript": transcript,
    }

    _OUTPUTS_DIR.mkdir(exist_ok=True)
    (_OUTPUTS_DIR / f"gen_{gen_n}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def _print_record(record: dict) -> None:
    print(f"\nFROM:    {record['sender']}")
    print(f"SUBJECT: {record['subject']}")
    print("BODY:")
    print(record["body"])
    print(f"\nRATIONALE: {record['rationale']}")
    print(f"\nINJECTION: {record['injection_record']}")
    print(f"RUN ID:    {record['run_id']}")
    print(f"\nWERDYKT: {record['verdict']}")
    print(f"DOWODY:  {record['evidence']}")
    print(f"UZASADNIENIE SĘDZIEGO: {record['judge_reasoning']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="hyperagent_email — self-improving agent atakujący przez treść maila, "
                     "z prawdziwą pętlą reset->inject->run->judge na agents_blocks"
    )
    parser.add_argument("--generations", type=int, default=3, help="Ile nowych generacji odpalić (domyślnie 3).")
    args = parser.parse_args()

    llm = get_llm()
    history = _load_history()
    start_gen = len(history)

    runner = AttackRunner()
    # WŁASNY ChatOllama systemu docelowego (settings.ollama_*) — niezależny od `llm` hiperagenta.
    workflow = build_supervisor_workflow()
    primitives = AttackPrimitives(runner, workflow)

    attack_id = runner.start_attack(
        name=f"hyperagent_email/gen_{start_gen}-{start_gen + args.generations - 1}",
        attack_type="hyperagent_email",
        description=ATTACK_OBJECTIVE.description,
    )

    for gen_n in range(start_gen, start_gen + args.generations):
        print(f"\n{'=' * 60}\nGeneracja {gen_n}\n{'=' * 60}")
        record = run_generation(gen_n, llm, history, primitives, attack_id)
        history.append(record)
        _save_history(history)
        _print_record(record)

    runner.finish_attack(attack_id, outcome=_final_outcome([h["verdict"] for h in history[start_gen:]]))

    if history:
        last_gen = start_gen + args.generations - 1
        print(f"\nGotowe. Ostatni payload: {_OUTPUTS_DIR / f'gen_{last_gen}.json'}")
        print(f"Inspekcja ostatniego runa: python show_run.py {history[-1]['run_id']}")


if __name__ == "__main__":
    main()
