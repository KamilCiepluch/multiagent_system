"""
Archiwum generacji — "prosta baza plików per run ze skryptami" (życzenie
użytkownika), zaimplementowana jako snapshoty całych drzew `/workspace`
spakowane jako tar.gz i przechowywane w `hyperagent_generations` (BYTEA).
Bezpośredni odpowiednik `archive.jsonl` z oryginalnego HyperAgents — tylko
kod trzymany w bazie (host i tak ma do niej zaufany dostęp), nie w systemie
plików hosta.

Przepływ jednej generacji w `hyperagent.loop`:

    select_parent(generations) -> checkout(..., workspace)
        -> [agent działa w sandboxie, mutuje workspace]
        -> snapshot_generation(..., workspace)

Generacja 0 nie ma rodzica do odtworzenia — `seed_generation` kopiuje płaskie
pliki z `hyperagent.seed` (patrz tam: `SEED_FILES`) do świeżego workspace'u
i zapisuje je jako pierwszy snapshot, żeby `loop.py` mogło traktować WSZYSTKIE
generacje (łącznie z zerową) przez ten sam checkout/snapshot, bez specjalnych
przypadków.
"""

from __future__ import annotations

import io
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from database import audit_db
from hyperagent.seed import SEED_DIR, SEED_FILES

PARENT_SELECTION_STRATEGIES = ("latest", "best_score")

# Ranking werdyktów sędziego (attack_core.judge.OUTCOMES) od najgorszego do
# najlepszego z perspektywy poszukiwania obejścia — używany zarówno tutaj
# (`best_score` wraca do generacji najbliższej realizacji celu, nawet jeśli
# to nie najnowsza gałąź — prawdziwa eksploracja drzewa, nie ślepe podążanie
# jednym łańcuchem) jak i w `hyperagent.loop` (wybór najlepszego werdyktu
# spośród kilku przebiegów `run_target_task` w obrębie jednej generacji).
# Generacje/przebiegi bez wyniku (np. generacja 0 — nigdy nie atakowała)
# lądują poniżej BLOCKED: nie ma żadnego dowodu, że ta gałąź do czegokolwiek
# prowadzi — eksplicytny brak dowodu jest gorszy niż udokumentowana porażka.
OUTCOME_RANK = {"BLOCKED": 0, "UNCLEAR": 1, "PARTIAL": 2, "ATTACK_SUCCESS": 3}


@dataclass(frozen=True)
class Generation:
    """Metadane jednej generacji w archiwum — mirror wiersza `hyperagent_generations`
    BEZ `code_archive` (zbyt duże, by trzymać całe drzewo w pamięci naraz —
    patrz `checkout`, które pobiera kod jednej generacji na żądanie)."""

    id: int
    generation_n: int
    parent_n: int | None
    score: str | None
    evidence: list
    run_ids: list[str]
    notes: str | None
    created_at: Any = None


def list_generations(session_id: str) -> list[Generation]:
    """Całe archiwum sesji (bez kodu) — host-side, do wyboru rodzica i raportu."""
    return [Generation(*row) for row in audit_db.get_hyperagent_generations(session_id)]


def select_parent(generations: list[Generation], method: str = "latest") -> Generation:
    """Wybiera generację-rodzica dla następnej rundy.

    - `latest`: zawsze ostatnia — proste, liniowe doskonalenie (refine-loop)
    - `best_score`: generacja o najlepszym dotychczasowym werdykcie — prawdziwa
      eksploracja drzewa: gdy gałąź wpada w ślepą uliczkę (wynik się pogarsza),
      można wrócić do wcześniejszej, lepszej i kontynuować z niej, zamiast
      brnąć dalej w to, co już nie działa
    """
    if not generations:
        raise ValueError("Archiwum jest puste — brak rodzica do wyboru (oczekiwano co najmniej generacji 0).")
    if method == "latest":
        return max(generations, key=lambda g: g.generation_n)
    if method == "best_score":
        return max(generations, key=lambda g: (OUTCOME_RANK.get(g.score, -1), g.generation_n))
    raise ValueError(f"Nieznana strategia wyboru rodzica '{method}' (dostępne: {PARENT_SELECTION_STRATEGIES})")


# ----------------------------------------------------------------------
# Pakowanie/rozpakowywanie drzewa kodu — tar.gz jako BYTEA
# ----------------------------------------------------------------------

def pack_workspace(workspace_dir: Path) -> bytes:
    """Pakuje całe drzewo `workspace_dir` (kod ZMUTOWANY przez agenta w
    sandboxie, po zakończeniu jego rundy) do tar.gz w pamięci — dosłowny
    snapshot bez filtrowania: agent mógł dodać/usunąć/przepisać dowolny
    plik, archiwum ma to odzwierciedlać 1:1, żeby `checkout` następnej
    generacji odtworzył DOKŁADNIE to, co poprzedniczka zostawiła."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for entry in sorted(workspace_dir.rglob("*")):
            tar.add(entry, arcname=entry.relative_to(workspace_dir).as_posix(), recursive=False)
    return buf.getvalue()


def _safe_extractall(tar: tarfile.TarFile, target_dir: Path) -> None:
    """Rozpakowuje z walidacją ścieżek — mirror `seed/tools.py:_resolve_in_workspace`.
    Snapshoty pochodzą z naszego własnego pakowania, ale ich ZAWARTOŚĆ to kod,
    który agent dowolnie przepisywał (mógł np. spróbować zapisać plik z nazwą
    `../cokolwiek` przez `write_file` — zob. tam walidację ścieżek), więc
    traktujemy nazwy wpisów jak niezaufane wejście i odrzucamy wszystko, co
    próbowałoby wyjść poza katalog docelowy."""
    target_resolved = target_dir.resolve()
    for member in tar.getmembers():
        member_path = (target_dir / member.name).resolve()
        if member_path != target_resolved and target_resolved not in member_path.parents:
            raise ValueError(f"Archiwum zawiera ścieżkę poza katalogiem docelowym: '{member.name}'")
    tar.extractall(target_dir)


def unpack_into(archive_bytes: bytes, workspace_dir: Path) -> None:
    """Rozpakowuje snapshot do `workspace_dir` (tworzy katalog, jeśli trzeba —
    powinien być pusty/świeży: to nowy `/workspace` dla kolejnej generacji)."""
    workspace_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        _safe_extractall(tar, workspace_dir)


# ----------------------------------------------------------------------
# Operacje na archiwum — checkout / snapshot / seed
# ----------------------------------------------------------------------

def checkout(session_id: str, generation: Generation, workspace_dir: Path) -> None:
    """Przywraca kod danej generacji do `workspace_dir` — tak rodzic 'ożywa'
    jako punkt startowy następnej rundy (host pobiera snapshot z archiwum,
    montuje `workspace_dir` jako `/workspace` świeżego kontenera agenta)."""
    code = audit_db.get_hyperagent_generation_code(session_id, generation.generation_n)
    if code is None:
        raise ValueError(f"Brak snapshotu kodu dla generacji {generation.generation_n} sesji {session_id}.")
    unpack_into(code, workspace_dir)


def snapshot_generation(
    session_id: str,
    generation_n: int,
    parent_n: int | None,
    workspace_dir: Path,
    *,
    score: str | None = None,
    evidence: list | None = None,
    run_ids: list[str] | None = None,
    notes: str | None = None,
) -> Generation:
    """Pakuje `workspace_dir` PO przebiegu agenta (już zmutowany kod) i
    zapisuje jako nową generację archiwum — bezpośredni odpowiednik wpisu
    w `archive.jsonl` oryginalnego HyperAgents, tylko z kodem w bazie
    zamiast w systemie plików hosta."""
    archive_bytes = pack_workspace(workspace_dir)
    gen_id = audit_db.save_hyperagent_generation(
        session_id, generation_n, parent_n, archive_bytes,
        score=score, evidence=evidence, run_ids=run_ids, notes=notes,
    )
    return Generation(
        id=gen_id, generation_n=generation_n, parent_n=parent_n,
        score=score, evidence=evidence or [], run_ids=run_ids or [], notes=notes,
    )


def seed_generation(session_id: str, workspace_dir: Path) -> Generation:
    """Tworzy generację 0 — JEDYNĄ bez rodzica: kopiuje płaskie pliki
    z `hyperagent.seed` (patrz `SEED_FILES`) do świeżego `workspace_dir`
    i od razu zapisuje je jako pierwszy snapshot. Dzięki temu `loop.py`
    nie potrzebuje żadnego specjalnego przypadku dla startu — generacja 0
    przechodzi przez dokładnie ten sam checkout/snapshot co każda kolejna."""
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for name in SEED_FILES:
        shutil.copy2(SEED_DIR / name, workspace_dir / name)
    return snapshot_generation(session_id, generation_n=0, parent_n=None, workspace_dir=workspace_dir, notes="seed")
