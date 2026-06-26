"""
SkillGate — middleware `before_agent`, który czyni ładowanie skilli NIEZAWODNYM,
nie odbierając agentowi autonomii.

Rozdzielamy dwie decyzje, które dziś się zlewają:
  • „czy w ogóle rozważyć procedury?"  → źródło zawodności (model po prostu zapomina) → ROBIMY OBOWIĄZKOWYM,
  • „która procedura pasuje / czy ją stosować?" → realny osąd → ZOSTAWIAMY modelowi.

Mechanizm: przed pętlą ReAct model wykonuje JEDEN krok structured-output (natywny json_schema Ollamy —
omija kruchy parser tool-calli) i jawnie artykułuje triage: ocena sytuacji → pasująca procedura albo
świadome „żadna". Treść decyzji jest jego własna (autonomia), ale sam triage jest wymuszony (niezawodność).

Na podstawie decyzji wstrzykujemy do historii ROZWIĄZANE wywołania narzędzi (list_skills, a przy
dopasowaniu — load_skill), tak jakby agent wykonał je sam. Dzięki temu:
  • procedura realnie ląduje w kontekście (gwarancja),
  • przebieg pozostaje zgodny z protokołem agenta („najpierw list_skills, potem load_skill"),
  • benchmark widzi load_skill jako prawdziwe wywołanie (mierzymy trafność osądu, nie pamięć modelu).

Fail-open: gdy structured-output zawiedzie, middleware nie blokuje agenta (zwraca None) — agent działa
po staremu, korzystając z tooli list_skills/load_skill z promptu.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage, ToolMessage
from langchain.agents.middleware import before_agent

from database.db import list_skills as db_list_skills, get_skill as db_get_skill


class SkillTriage(BaseModel):
    """Jawna, ustrukturyzowana decyzja agenta o procedurze do zastosowania."""
    ocena_sytuacji: str = Field(
        description="Krótko (1–2 zdania): o co chodzi w zadaniu i jaka to sytuacja."
    )
    pasujaca_procedura: str | None = Field(
        default=None,
        description=(
            "DOKŁADNA nazwa procedury z podanego katalogu, która reguluje tę sytuację, "
            "albo null jeśli żadna nie pasuje. Procedury dotyczą ZŁOŻONYCH sytuacji "
            "(np. wieloźródłowość, podejrzane/sprzeczne wyniki, granice zakresu, eskalacja, synteza). "
            "Dla prostych, pojedynczych operacji ustaw null."
        ),
    )
    uzasadnienie: str = Field(
        description="Dlaczego ta procedura (albo dlaczego żadna nie pasuje)."
    )


def _task_text(messages: list) -> str:
    """Treść zadania = pierwsza wiadomość użytkownika (HumanMessage)."""
    for m in messages:
        if type(m).__name__ == "HumanMessage":
            return str(m.content)
    return str(messages[0].content) if messages else ""


def _tool_call(name: str, args: dict) -> dict:
    return {"name": name, "args": args, "id": f"skillgate_{uuid.uuid4().hex[:8]}", "type": "tool_call"}


def make_skill_gate(llm, agent_name: str):
    """Zwraca middleware `before_agent` powiązane z danym agentem i modelem."""

    triage_model = llm.with_structured_output(SkillTriage, method="json_schema")

    @before_agent(name=f"skill_gate[{agent_name}]")
    def skill_gate(state, runtime):
        catalog = db_list_skills(agent_name)
        if not catalog:
            return None  # brak procedur — nic do triage

        names = {s.name for s in catalog}
        catalog_txt = "\n".join(f"- {s.name}: {s.description}" for s in catalog)
        task = _task_text(state["messages"])

        prompt = (
            "Jesteś agentem przed wykonaniem zadania. Najpierw oceń sytuację i zdecyduj, "
            "KTÓRA procedura (skill) z katalogu reguluje to zadanie — albo że żadna nie pasuje.\n\n"
            f"ZADANIE:\n{task}\n\n"
            f"KATALOG PROCEDUR ({agent_name}):\n{catalog_txt}\n\n"
            "Zwróć decyzję w wymaganym formacie. Nazwa procedury MUSI być dokładnie jedną z katalogu albo null."
        )

        try:
            triage = triage_model.invoke(prompt)
        except Exception:
            return None  # fail-open: nie blokuj agenta, gdy structured-output zawiedzie

        ocena = getattr(triage, "ocena_sytuacji", "") or ""
        chosen = getattr(triage, "pasujaca_procedura", None)
        uzasadnienie = getattr(triage, "uzasadnienie", "") or ""
        if chosen is not None and chosen not in names:
            chosen = None  # model podał nazwę spoza katalogu — traktuj jak brak dopasowania

        # Krok 1 (zawsze): zarejestruj rozwiązane list_skills — zgodnie z protokołem agenta.
        ls_call = _tool_call("list_skills", {})
        injected: list = [
            AIMessage(content=f"[TRIAGE] {ocena}".strip(), tool_calls=[ls_call]),
            ToolMessage(content=catalog_txt, tool_call_id=ls_call["id"], name="list_skills"),
        ]

        # Krok 2 (gdy dopasowano): zarejestruj rozwiązane load_skill z treścią procedury.
        if chosen:
            skill = db_get_skill(chosen, agent_name)
            body = skill.content if skill else f"(treść procedury '{chosen}' niedostępna)"
            load_call = _tool_call("load_skill", {"name": chosen})
            injected += [
                AIMessage(
                    content=f"Stosuję procedurę '{chosen}'. {uzasadnienie}".strip(),
                    tool_calls=[load_call],
                ),
                ToolMessage(content=body, tool_call_id=load_call["id"], name="load_skill"),
            ]

        return {"messages": injected}

    return skill_gate
