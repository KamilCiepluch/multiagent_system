"""
Strażnik self-modyfikacji `workspace/` — host-side, POZA zasięgiem agenta.

Agent może nadpisywać pliki w `workspace/` (system_prompt.py, tools.py,
agent.py) — to jest sedno samodoskonalenia. Problem: jedna błędna self-
modyfikacja (błąd składni, złamany kontrakt, usunięte narzędzie) zabetonowałaby
całą pętlę przy następnym `importlib.reload`. Ten moduł temu zapobiega:

- `reload_and_validate(llm)` przeładowuje moduły workspace W POPRAWNEJ
  KOLEJNOŚCI i sprawdza KONTRAKT, na którym polega `loop.py`:
    * `agent.run(llm, objective, history)` istnieje i jest wywoływalne,
    * `tools.build_tools(llm)` istnieje, daje się wywołać i zwraca co najmniej
      narzędzia `read_file`, `write_file`, `list_files`.
  Każde naruszenie -> `WorkspaceContractError` z czytelnym opisem.
- `snapshot()` / `restore()` pozwalają `loop.py` trzymać kopię OSTATNIEJ
  DZIAŁAJĄCEJ wersji kodu i wrócić do niej, gdy nowa self-modyfikacja się nie
  ładuje — bez utraty całej sesji.

Ten plik leży w `hyperagent_email/` (NIE w `workspace/`), więc agent fizycznie
nie ma do niego narzędzi (`read_file`/`write_file` są zakresowane do
`workspace/`) — to sieć bezpieczeństwa, której agent nie może wyłączyć.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from workspace import agent as agent_module
from workspace import system_prompt as system_prompt_module
from workspace import tools as tools_module

from logging_setup import get_logger

_log = get_logger("workspace_guard")

_WORKSPACE = Path(__file__).resolve().parent / "workspace"
# Pliki, które agent może modyfikować i które utrzymujemy w snapshotach.
_MANAGED_FILES = ("system_prompt.py", "tools.py", "agent.py")
_REQUIRED_TOOLS = frozenset({"read_file", "write_file", "list_files"})


class WorkspaceContractError(RuntimeError):
    """Self-modyfikacja `workspace/` złamała kontrakt wymagany przez `loop.py`."""


def snapshot() -> dict[str, str]:
    """Zwraca treść zarządzanych plików workspace — kopia 'last-good' do rollbacku."""
    snap: dict[str, str] = {}
    for name in _MANAGED_FILES:
        path = _WORKSPACE / name
        snap[name] = path.read_text(encoding="utf-8") if path.exists() else ""
    return snap


def restore(snap: dict[str, str]) -> None:
    """Przywraca zarządzane pliki workspace z wcześniejszego snapshotu."""
    for name, content in snap.items():
        (_WORKSPACE / name).write_text(content, encoding="utf-8")
    _log.warning("Przywrócono %d plik(ów) workspace z ostatniej działającej wersji.", len(snap))


def reload_and_validate(llm) -> list[str]:
    """Przeładowuje moduły workspace i waliduje kontrakt.

    Rzuca `WorkspaceContractError` (kontrakt) albo dowolny wyjątek importu
    (SyntaxError/ImportError przy `reload`), jeśli kod jest niezdatny do użycia.
    Zwraca posortowaną listę nazw narzędzi zbudowanych przez `build_tools`
    (dla logu — diagnostyka, jakie narzędzia agent ma w tej generacji).
    """
    # Kolejność istotna: agent.py importuje z tools.py i system_prompt.py,
    # więc te dwa muszą być przeładowane jako pierwsze.
    importlib.reload(tools_module)
    importlib.reload(system_prompt_module)
    importlib.reload(agent_module)

    if not hasattr(agent_module, "run") or not callable(agent_module.run):
        raise WorkspaceContractError(
            "agent.py nie eksportuje wywoływalnego run(llm, objective, history)."
        )
    if not hasattr(tools_module, "build_tools") or not callable(tools_module.build_tools):
        raise WorkspaceContractError("tools.py nie eksportuje wywoływalnego build_tools(llm).")

    try:
        built = tools_module.build_tools(llm)
        tool_names = {getattr(t, "name", "") for t in built}
    except Exception as exc:  # noqa: BLE001 — dowolny błąd budowy narzędzi = złamany kontrakt
        raise WorkspaceContractError(f"build_tools(llm) rzuciło wyjątek: {exc!r}") from exc

    missing = _REQUIRED_TOOLS - tool_names
    if missing:
        raise WorkspaceContractError(
            f"build_tools(llm) nie zwraca wymaganych narzędzi — brakuje: {sorted(missing)}."
        )

    return sorted(n for n in tool_names if n)
