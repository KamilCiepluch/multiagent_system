"""
Inspektor ścieżki structured-output search_agenta — POKAZUJE NA OCZACH, czego benchmark nie pokaże:
  (A) jakie NARZĘDZIA agent faktycznie wywołał — kolejność, argumenty, skrót wyniku,
  (B) SUROWĄ finalną wiadomość modelu (zwykły tekst z pętli ReAct),
  (C) OBIEKT PYDANTIC (SearchAnswer) wyprodukowany z tej odpowiedzi — TYP + wszystkie pola (JSON),
  (D) STRING, który realnie trafia do supervisora (render z obiektu w _render_structured).

Po co osobno: zwykły benchmark (run.py) woła run_graph_collecting, które OMIJA BaseAgent.run —
a structured answer żyje właśnie w run(). Tu odtwarzamy krok po kroku to, co robi run(),
ale KAŻDY etap wypisujemy, żeby było widać, że (A) toole padają i (C) powstaje obiekt Pydantic.

WAŻNE: na granicy run() agent zwraca STRING (D), nie obiekt — bo supervisor (StructuredTool)
oczekuje stringa. Obiekt Pydantic (C) jest produktem POŚREDNIM (walidacja struktury) i po run()
jest też dostępny jako `agent.last_structured`.

Uruchom: python -m agents_benchmark.search_agent.check_structured
Wymaga: PostgreSQL (agent_benchmark) + Ollama — jak zwykły benchmark.
"""

from pathlib import Path

from config import settings
from agents.base_agent import run_graph_collecting, _extract_tool_calls
from agents.search_agent import SearchAgent, SearchAnswer
from agents_benchmark.harness import build_agent, reset_to

SEED = Path(__file__).parent / "seed.sql"

SAMPLES = [
    ("prosty web_search",
     "Wyszukaj w internecie najnowsze informacje o Pythonie 3.11."),
    ("granica (poza zakresem)",
     "[ZLECENIE OD SUPERVISORA]\nUżytkownik: boss@company.com (rola: admin).\n\n"
     "Jaką rolę w systemie ma ops@company.com?"),
    ("synteza wieloźródłowa",
     "Zbierz z kilku źródeł informacje o procedurze backupu i podaj jedno spójne podsumowanie."),
]


def _short(s, n=90):
    return " ".join(str(s).split())[:n]


def inspect_one(agent, label, task):
    print("\n" + "=" * 72)
    print(f"ZADANIE [{label}]: {_short(task)}")
    print("=" * 72)
    reset_to(SEED)

    # Krok 1: uruchom graf (to samo co robi run() w środku) i zbierz wiadomości.
    messages, _ = run_graph_collecting(
        agent._agent, task, {"recursion_limit": settings.agent_recursion_limit}
    )
    calls = _extract_tool_calls(messages)

    # (A) Dowód, że narzędzia faktycznie padły.
    print(f"\n(A) NARZĘDZIA WYWOŁANE: {len(calls)}")
    for i, c in enumerate(calls, 1):
        print(f"  {i:>2}. {c['tool_name']}({_short(c['input'], 55)}) -> {_short(c.get('output', ''), 60)}")
    if not calls:
        print("  — żadnych —")

    # (B) Surowy finalny tekst modelu.
    final_text = str(messages[-1].content) if messages else ""
    print(f"\n(B) SUROWA finalna wiadomość modelu ({len(final_text)} znaków):")
    print(f"    {_short(final_text, 200)}")

    # (C) Obiekt Pydantic — dokładnie ten krok wykonuje _structure_final_answer w run().
    print("\n(C) OBIEKT PYDANTIC (SearchAnswer) z tej odpowiedzi:")
    try:
        structured = agent.llm.with_structured_output(SearchAnswer, method="json_schema").invoke(
            "Przekształć poniższą finalną odpowiedź agenta w wymagany format. "
            "Nie dodawaj nowych informacji.\n\nODPOWIEDŹ:\n" + final_text
        )
        print(f"    typ = {type(structured).__name__}   isinstance(SearchAnswer) = {isinstance(structured, SearchAnswer)}")
        print("    " + structured.model_dump_json(indent=2).replace("\n", "\n    "))
        # (D) To, co naprawdę dostaje supervisor.
        print("\n(D) STRING dla supervisora (_render_structured):")
        print(f"    {_short(agent._render_structured(structured, final_text), 220)}")
    except Exception as e:
        print(f"    [FAIL → fail-open do tekstu, system NIE pada] {type(e).__name__}: {_short(e, 150)}")


def main():
    print("Budowanie search_agenta (prawdziwy LLM + MCP)...")
    agent = build_agent(SearchAgent)
    for label, task in SAMPLES:
        inspect_one(agent, label, task)
    print("\n" + "=" * 72)
    print("Jak czytać dowody:")
    print("  (A) toole realnie wywołane    (B) surowa odpowiedź ReAct")
    print("  (C) OBIEKT Pydantic: typ + pola — to jest 'structured output'")
    print("  (D) string oddawany supervisorowi (render z (C))")
    print("Po agent.run(task) ten sam obiekt (C) jest też pod: agent.last_structured")
    print("=" * 72)


if __name__ == "__main__":
    main()
