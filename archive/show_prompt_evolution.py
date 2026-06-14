"""
Pokazuje, jak hyperagent_email przepisywał swój własny kod (prompt/narzędzia/
pętlę) między generacjami — czyli na czym polega jego "samodoskonalenie".

Źródłem są snapshoty zapisywane przez `hyperagent_email/loop.py` po adopcji
self-modyfikacji każdej generacji do `hyperagent_email/workspace_snapshots/gen_<N>/`
(system_prompt.py, tools.py, agent.py). Skrypt diffuje kolejne wersje i pokazuje
DOKŁADNIE, co się zmieniło — wraz z werdyktem danej generacji (z `outputs/gen_<N>.json`),
żeby było widać, czy zmiana coś dała.

Użycie (z korzenia repo):
    python show_prompt_evolution.py                      # diff system_prompt.py gen po gen
    python show_prompt_evolution.py --file tools.py      # diff tools.py
    python show_prompt_evolution.py --file all           # wszystkie trzy pliki
    python show_prompt_evolution.py --gen 5              # pełna treść pliku z generacji 5
    python show_prompt_evolution.py --full               # pełna treść każdej zmienionej wersji
    python show_prompt_evolution.py --list               # które generacje mają snapshoty
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

# Wymuś UTF-8 na stdout — domyślne kodowanie konsoli Windows (np. cp1250) nie
# obsługuje znaków ramki/polskich diakrytyków i wysypywałoby skrypt przy
# przekierowaniu strumienia. errors="replace" gwarantuje brak wyjątku.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent
_SNAPSHOTS_DIR = _ROOT / "hyperagent_email" / "workspace_snapshots"
_OUTPUTS_DIR = _ROOT / "hyperagent_email" / "outputs"

_MANAGED_FILES = ("system_prompt.py", "tools.py", "agent.py")

# ─── Kolory (ANSI, wyłączane gdy nie-TTY lub --no-color) — jak w show_hyperagent.py ──

_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def red(t: str) -> str:    return _c("31", t)
def green(t: str) -> str:  return _c("32", t)
def yellow(t: str) -> str: return _c("33;1", t)
def cyan(t: str) -> str:   return _c("36;1", t)
def bold(t: str) -> str:   return _c("1", t)
def dim(t: str) -> str:    return _c("2", t)


_VERDICT_COLOR = {
    "ATTACK_SUCCESS": green,
    "PARTIAL": yellow,
    "UNCLEAR": yellow,
    "BLOCKED": red,
    "NO_VALID_PAYLOAD": red,
    "ERROR": red,
}


# ─── Wczytywanie snapshotów ──────────────────────────────────────────────────

def _available_generations() -> list[int]:
    """Posortowane numery generacji, dla których istnieje snapshot."""
    if not _SNAPSHOTS_DIR.exists():
        return []
    gens = []
    for d in _SNAPSHOTS_DIR.iterdir():
        if d.is_dir() and d.name.startswith("gen_"):
            try:
                gens.append(int(d.name[len("gen_"):]))
            except ValueError:
                continue
    return sorted(gens)


def _read_snapshot(gen_n: int, filename: str) -> str | None:
    path = _SNAPSHOTS_DIR / f"gen_{gen_n}" / filename
    return path.read_text(encoding="utf-8") if path.exists() else None


def _verdict_of(gen_n: int) -> str | None:
    """Werdykt generacji z outputs/gen_<N>.json (jeśli jest)."""
    path = _OUTPUTS_DIR / f"gen_{gen_n}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("verdict")
    except (json.JSONDecodeError, OSError):
        return None


def _verdict_label(gen_n: int) -> str:
    v = _verdict_of(gen_n)
    if v is None:
        return dim("(werdykt nieznany)")
    return _VERDICT_COLOR.get(v, dim)(v)


# ─── Formatowanie diffów ─────────────────────────────────────────────────────

def _colorize_diff(diff_lines: list[str]) -> str:
    out = []
    for line in diff_lines:
        if line.startswith("+") and not line.startswith("+++"):
            out.append(green(line))
        elif line.startswith("-") and not line.startswith("---"):
            out.append(red(line))
        elif line.startswith("@@"):
            out.append(cyan(line))
        elif line.startswith(("+++", "---")):
            out.append(dim(line))
        else:
            out.append(line)
    return "\n".join(out)


def _diff(old: str, new: str, label_old: str, label_new: str) -> str:
    diff = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=label_old, tofile=label_new, lineterm="", n=2,
    )
    return _colorize_diff(list(diff))


# ─── Widoki ──────────────────────────────────────────────────────────────────

def show_evolution(filename: str, full: bool) -> None:
    gens = _available_generations()
    if not gens:
        print(
            f"Brak snapshotów w {_SNAPSHOTS_DIR}.\n"
            "Snapshoty powstają dopiero przy uruchomieniu loop.py PO tej zmianie — "
            "odpal:\n"
            "  python hyperagent_email\\loop.py --generations 3"
        )
        return

    files = _MANAGED_FILES if filename == "all" else (filename,)
    SEP = "═" * 78

    for fname in files:
        print(f"\n{bold(SEP)}")
        print(f"  {bold('EWOLUCJA')} {cyan(fname)}  ({len(gens)} generacji ze snapshotem)")
        print(bold(SEP))

        prev_content: str | None = None
        prev_gen: int | None = None
        changes = 0

        for gen_n in gens:
            content = _read_snapshot(gen_n, fname)
            if content is None:
                print(f"\n  {dim(f'gen {gen_n}: brak {fname} w snapshocie')}")
                continue

            verdict = _verdict_label(gen_n)

            if prev_content is None:
                print(f"\n  {bold(f'gen {gen_n}')} — wersja bazowa  |  werdykt: {verdict}")
                if full:
                    print(_indent(content))
            elif content == prev_content:
                print(f"\n  {bold(f'gen {gen_n}')} — {dim('bez zmian')} (identyczny jak gen {prev_gen})"
                      f"  |  werdykt: {verdict}")
            else:
                changes += 1
                print(f"\n  {bold(f'gen {prev_gen} → gen {gen_n}')}  {yellow('ZMIANA')}"
                      f"  |  werdykt gen {gen_n}: {verdict}")
                if full:
                    print(_indent(content))
                else:
                    diff_text = _diff(prev_content, content,
                                      f"gen_{prev_gen}/{fname}", f"gen_{gen_n}/{fname}")
                    print(_indent(diff_text) if diff_text else dim("    (brak różnic tekstowych)"))

            prev_content, prev_gen = content, gen_n

        print(f"\n  {dim(f'Zmian w {fname}: {changes} na {len(gens)} generacji')}")

    print(f"\n{bold(SEP)}\n")


def show_single(gen_n: int, filename: str) -> None:
    files = _MANAGED_FILES if filename == "all" else (filename,)
    if gen_n not in _available_generations():
        print(f"Brak snapshotu dla generacji {gen_n}. Dostępne: {_available_generations()}")
        sys.exit(1)
    for fname in files:
        content = _read_snapshot(gen_n, fname)
        print(f"\n{bold('═' * 78)}")
        print(f"  {cyan(fname)}  @ gen {gen_n}  |  werdykt: {_verdict_label(gen_n)}")
        print(bold("═" * 78))
        print(content if content is not None else dim(f"(brak {fname} w tym snapshocie)"))


def list_generations() -> None:
    gens = _available_generations()
    if not gens:
        print(f"Brak snapshotów w {_SNAPSHOTS_DIR}.")
        return
    print(bold(f"\n  Snapshoty workspace ({len(gens)} generacji):"))
    print(f"  {'─' * 60}")
    for gen_n in gens:
        present = [f for f in _MANAGED_FILES if (_SNAPSHOTS_DIR / f"gen_{gen_n}" / f).exists()]
        print(f"  gen {gen_n:<3} | werdykt: {_verdict_label(gen_n):<24} | pliki: {', '.join(present)}")
    print(f"  {'─' * 60}")


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Pokazuje, jak hyperagent_email przepisywał swój prompt/kod między generacjami.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przykłady:\n"
            "  python show_prompt_evolution.py                   # diff system_prompt.py\n"
            "  python show_prompt_evolution.py --file all        # wszystkie trzy pliki\n"
            "  python show_prompt_evolution.py --gen 5           # pełna treść z gen 5\n"
            "  python show_prompt_evolution.py --full            # pełne wersje, nie diff\n"
        ),
    )
    p.add_argument("--file", default="system_prompt.py",
                   help="Który plik śledzić: system_prompt.py (domyślnie) | tools.py | agent.py | all")
    p.add_argument("--gen", type=int, metavar="N", help="Pokaż pełną treść pliku z generacji N")
    p.add_argument("--full", action="store_true", help="Pokaż pełną treść każdej zmienionej wersji (zamiast diffa)")
    p.add_argument("--list", action="store_true", help="Lista generacji ze snapshotami")
    p.add_argument("--no-color", action="store_true", help="Wyłącz kolory ANSI")
    args = p.parse_args()

    if args.no_color:
        global _USE_COLOR
        _USE_COLOR = False

    if args.file not in (*_MANAGED_FILES, "all"):
        print(f"Nieznany plik: {args.file!r}. Dozwolone: {', '.join(_MANAGED_FILES)}, all")
        sys.exit(1)

    if args.list:
        list_generations()
    elif args.gen is not None:
        show_single(args.gen, args.file)
    else:
        show_evolution(args.file, full=args.full)


if __name__ == "__main__":
    main()
