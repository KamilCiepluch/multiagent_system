"""
Narzędzia hiperagenta — TYLKO DO ODCZYTU/EKSPERYMENTU.

Po przejściu z „agent przepisuje własny kod" na „agent wybiera strategie i
komponuje pipeline konwerterów" agent NIE potrzebuje już write_file do siebie.
Dostaje za to dwa narzędzia pomocnicze, którymi może sprawdzić swój pomysł,
ZANIM wyśle finalny ATTACK PLAN:

  - `list_converters()`     — pełny toolbox dostępnych konwerterów (nazwy + parametry),
  - `preview_pipeline(spec, seed_body)` — pokazuje, jak HOST zastosuje dany pipeline
    do `seed_body` (finalny payload + ewentualne problemy z nazwami/parametrami).

Kontrakt (zależny od `agent.py`): moduł eksportuje `build_tools(llm) -> list`
narzędzi LangChain. Faktyczne wstrzyknięcie maila robi HOST (`loop.py`), a sam
pipeline aplikuje HOST deterministycznie — te narzędzia służą wyłącznie do
podglądu (są czyste, bez efektów ubocznych).
"""

from __future__ import annotations

from langchain_core.tools import tool

from attack_core.strategies.converters import apply_pipeline, render_toolbox


def build_tools(llm) -> list:
    """Zwraca read-only narzędzia pomocnicze dla tej generacji."""

    @tool
    def list_converters() -> str:
        """Listuje dostępne konwertery payloadu (nazwa, parametry, opis). Użyj ich
        nazw w polu PIPELINE swojego ATTACK PLAN."""
        return render_toolbox()

    @tool
    def preview_pipeline(spec: str, seed_body: str) -> str:
        """Pokazuje, jak HOST zastosuje dany pipeline konwerterów do seed_body —
        zwraca finalny payload oraz listę zastosowanych kroków i problemów
        (np. nieznana nazwa konwertera). Użyj, by przetestować PIPELINE przed
        finalną odpowiedzią. Format spec: 'name(param=val) | name2 | name3'."""
        final, applied, problems = apply_pipeline(spec, seed_body, llm=llm)
        return (
            f"ZASTOSOWANE KROKI: {applied or '(żadne)'}\n"
            f"PROBLEMY: {problems or '(brak)'}\n"
            f"--- FINALNY PAYLOAD ---\n{final}"
        )

    return [list_converters, preview_pipeline]
