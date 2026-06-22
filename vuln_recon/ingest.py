"""
Orkiestracja: utwórz skan → odpal garaka → sparsuj raport → zapisz findingi/trafienia.

Jedyne miejsce stykające warstwę garaka (vuln_recon) z bazą (database.recon_db). Skan jest
„transakcyjny" na poziomie statusu: rekord powstaje PRZED uruchomieniem (status='running'),
a w razie dowolnego błędu zostaje domknięty jako 'failed' z opisem — nigdy nie zostaje wiszący.
"""

from __future__ import annotations

from pathlib import Path

from database import recon_db
from vuln_recon.config import GarakSettings
from vuln_recon.garak_runner import run_garak
from vuln_recon.report_parser import parse_hitlog_file, parse_report_file


def scan_and_store(settings: GarakSettings | None = None) -> str:
    """Pełny przebieg recon dla jednego modelu. Zwraca scan_id (UUID jako string)."""
    settings = settings or GarakSettings()

    scan_id = recon_db.ScanRepository.start(
        target_model=settings.target_model,
        target_type=settings.target_type,
        attacker_model=settings.attacker_model,
        tool="garak",
        probes=settings.probe_list(),
    )
    # Raport nazwany scan_id → ślad na dysku łatwo skojarzyć z wierszem w bazie.
    report_prefix = str((Path(settings.report_dir) / scan_id).resolve())

    try:
        result = run_garak(settings, report_prefix=report_prefix)

        findings = parse_report_file(result["report_path"]) if result["report_path"] else []
        hits = parse_hitlog_file(result["hitlog_path"]) if result["hitlog_path"] else []
        recon_db.FindingRepository.bulk_insert(scan_id, [f.as_row() for f in findings])
        recon_db.HitRepository.bulk_insert(scan_id, [h.as_row() for h in hits])

        ok = result["returncode"] == 0 and result["report_path"] is not None
        recon_db.ScanRepository.finish(
            scan_id,
            status="completed" if ok else "failed",
            report_path=result["report_path"],
            tool_version=result["version"],
            command=result["command"],
            error=None if ok else (
                f"garak returncode={result['returncode']}, "
                f"report={'znaleziony' if result['report_path'] else 'BRAK'}"
            ),
        )
        print(f"\n  Zapisano: {len(findings)} findingów, {len(hits)} trafień → scan {scan_id}")
        return scan_id
    except Exception as e:
        recon_db.ScanRepository.finish(scan_id, status="failed", error=f"{type(e).__name__}: {e}")
        raise
