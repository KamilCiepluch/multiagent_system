"""
Narzędzia hiperagenta — generacja 0 (seed).

Tak jak `system_prompt.py`, ten plik jest CZĘŚCIĄ "siebie" agenta —
`read_file`/`write_file`/`list_files` pozwalają mu go odczytać i nadpisać.
Jedyny twardy wymóg (patrz `system_prompt.py`): moduł musi eksportować
`build_tools(llm) -> list[BaseTool]` z co najmniej `read_file`, `write_file`,
`list_files` — `loop.py` i `agent.py` na tym polegają.

Pliki — `read_file`/`write_file`/`list_files`, zakresowane do `workspace/`
(katalog tego modułu). To TAK agent mutuje swój własny kod.

Agent NIE ma żadnego narzędzia do faktycznego wysłania/wstrzyknięcia maila —
to robi HOST (`loop.py`, poza zasięgiem self-modyfikacji) PO finalnej
odpowiedzi agenta, patrz `objective.py`.

`build_tools(llm)` przyjmuje `llm`, choć żadne z poniższych narzędzi go nie
używa — kontrakt z `agent.py` (`run()` woła `build_tools(llm)` i przekazuje
ten sam `llm` do `create_agent`) jest zachowany na wypadek, gdyby agent w
ramach self-modyfikacji chciał dopisać sobie NOWE narzędzie korzystające z
modelu (np. coś innego niż symulacja ofiary, której już tu nie ma).
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

_WORKSPACE = Path(__file__).resolve().parent


def _resolve(path: str) -> Path:
    target = (_WORKSPACE / path).resolve()
    if target != _WORKSPACE and _WORKSPACE not in target.parents:
        raise ValueError(f"Ścieżka '{path}' wychodzi poza workspace/ — odrzucono.")
    return target


def build_tools(llm) -> list:
    """Zwraca listę narzędzi LangChain dla tej generacji."""

    @tool
    def read_file(path: str) -> str:
        """Czyta plik ze swojego workspace (swój kod: agent.py, tools.py, system_prompt.py)."""
        return _resolve(path).read_text(encoding="utf-8")

    @tool
    def write_file(path: str, content: str) -> str:
        """Nadpisuje plik w swoim workspace — TAK mutujesz swój kod/narzędzia/prompt
        na potrzeby następnej generacji. Tworzy katalogi nadrzędne, jeśli trzeba."""
        target = _resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Zapisano {len(content)} znaków do {path}"

    @tool
    def list_files(path: str = ".") -> str:
        """Listuje zawartość katalogu w swoim workspace (domyślnie korzeń)."""
        target = _resolve(path)
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
        return "\n".join(entries) if entries else "(pusty katalog)"

    return [read_file, write_file, list_files]
