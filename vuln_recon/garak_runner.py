"""
Uruchamianie Garaka jako SUBPROCESS (`python -m garak ...`).

Świadomie nie importujemy garaka w kodzie — odpalamy go w osobnym procesie (domyślnie tym
samym interpreterze, `sys.executable`), więc ciężka zależność jest odizolowana, a my w pełni
kontrolujemy ścieżkę raportu przez `--report_prefix`.

Flagi zweryfikowane na garak 0.15.1 (`--help`): `--target_type` / `--target_name` (dawne
`--model_type`/`--model_name` deprecated od 0.13.1). Generator Ollama: `--target_type ollama`.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

from vuln_recon.config import GarakSettings


class GarakNotInstalled(RuntimeError):
    """Garak nie jest dostępny w docelowym interpreterze — patrz requirements-recon.txt."""


def attacker_probe_options(settings: GarakSettings) -> str:
    """JSON do `--probe_options`, który PODMIENIA red-team model probe'a atkgen na nasz model
    atakujący. Bez tego atkgen używa domyślnego GPT-2 (garak-llm/attackgeneration-toxicity_gpt2),
    a nasz `attacker_model` byłby tylko etykietą. Nadpisujemy też:
      • red_team_model_config={"timeout": request_timeout} — domyślny ma hf_args (CPU/torch) pod
        GPT-2; podmieniamy na timeout Ollamy (zimne ładowanie modelu rozumującego > 30s),
      • red_team_prompt_template='[query]' — domyślny <|input|>[query]<|response|> jest pod GPT-2;
        chatowy model dostaje czyste zapytanie (placeholder [query] jest wymagany przez garaka).
    Objętość (convs_per_generation/max_calls_per_conv) ograniczamy, gdy podano — przy swapie
    modeli domyślne 5×5 to godziny. Struktura: plugins.probes.<moduł>.<Klasa>.<param>."""
    tox: dict = {
        "red_team_model_type": settings.attacker_type,   # np. ollama.OllamaGeneratorChat
        "red_team_model_name": settings.attacker_model,
        "red_team_model_config": {"timeout": settings.request_timeout},
        "red_team_prompt_template": "[query]",
    }
    if settings.atkgen_convs is not None:
        tox["convs_per_generation"] = settings.atkgen_convs
    if settings.atkgen_calls is not None:
        tox["max_calls_per_conv"] = settings.atkgen_calls
    return json.dumps({"atkgen": {"Tox": tox}})


def target_generator_options(settings: GarakSettings) -> str:
    """JSON do `--generator_options` — podnosi timeout generatora CELU (Ollama). Ten sam powód
    co przy red-teamie: domyślne 30s garaka jest za małe dla zimno-ładowanego, rozumującego celu
    przy keep_alive=0. Ustawiamy obie klasy generatora Ollamy (chat/base)."""
    t = {"timeout": settings.request_timeout}
    return json.dumps({"ollama": {"OllamaGeneratorChat": dict(t), "OllamaGenerator": dict(t)}})


def garak_version(settings: GarakSettings) -> str:
    """Zwraca wersję garaka z docelowego interpretera; podnosi GarakNotInstalled, gdy brak."""
    try:
        out = subprocess.run(
            [settings.python_exe, "-c", "import garak; print(garak.__version__)"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise GarakNotInstalled(f"Nie udało się uruchomić interpretera garaka: {e}") from e
    if out.returncode != 0:
        raise GarakNotInstalled(
            "Garak nie jest zainstalowany w środowisku. Zainstaluj:\n"
            "  pip install -r requirements-recon.txt\n"
            f"(stderr: {out.stderr.strip()[:200]})"
        )
    return out.stdout.strip()


def build_command(settings: GarakSettings, report_prefix: str) -> list[str]:
    """Buduje argv garaka. report_prefix bez rozszerzenia — garak dopisze .report.jsonl itd."""
    argv = [
        settings.python_exe, "-m", "garak",
        "--target_type", settings.target_type,
        "--target_name", settings.target_model,
        "--probes", settings.probes,
        "--report_prefix", report_prefix,
    ]
    # Podnieś timeout generatora celu (Ollama) — domyślne 30s garaka wisi przy zimnym ładowaniu.
    if settings.target_type.startswith("ollama"):
        argv += ["--generator_options", target_generator_options(settings)]
    # Model atakujący wpina się TYLKO przez red-team probe'a atkgen — i tylko gdy go uruchamiamy.
    if settings.attacker_model and "atkgen" in settings.probes:
        argv += ["--probe_options", attacker_probe_options(settings)]
    if settings.extra_args:
        argv += shlex.split(settings.extra_args)
    return argv


def _resolve_outputs(report_prefix: str, report_dir: Path) -> tuple[str | None, str | None]:
    """Lokalizuje raport/hitlog. Najpierw po kontrolowanym prefiksie, potem fallback do
    najnowszego *.report.jsonl w katalogu (gdyby garak znormalizował ścieżkę inaczej)."""
    report = Path(f"{report_prefix}.report.jsonl")
    hitlog = Path(f"{report_prefix}.hitlog.jsonl")
    if not report.exists():
        candidates = sorted(report_dir.glob("*.report.jsonl"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            report = candidates[0]
            hitlog = report.with_name(report.name.replace(".report.jsonl", ".hitlog.jsonl"))
    return (str(report) if report.exists() else None,
            str(hitlog) if hitlog.exists() else None)


def run_garak(settings: GarakSettings, *, report_prefix: str) -> dict:
    """Odpala garaka i zwraca dict: command, report_path, hitlog_path, returncode, version.

    `report_prefix` to pełna ścieżka-baza (bez rozszerzenia). Strumień garaka idzie na
    konsolę (widać postęp). OLLAMA_HOST ustawiamy z base_url, żeby generator trafił do Ollamy.
    """
    version = garak_version(settings)  # twardy fail wcześnie, czytelny komunikat

    report_dir = Path(report_prefix).resolve().parent
    report_dir.mkdir(parents=True, exist_ok=True)

    argv = build_command(settings, report_prefix)
    env = {**os.environ, "OLLAMA_HOST": settings.base_url}

    proc = subprocess.run(argv, env=env)  # dziedziczy stdout/stderr → postęp na żywo
    report_path, hitlog_path = _resolve_outputs(report_prefix, report_dir)

    return {
        "command": subprocess.list2cmdline(argv),
        "report_path": report_path,
        "hitlog_path": hitlog_path,
        "returncode": proc.returncode,
        "version": version,
    }
