"""
CLI warstwy recon — skan podatności modelu (Garak) + odczyt zgromadzonej wiedzy.

Skan (zapisuje do schematu `recon` w agent_core):
    python -m vuln_recon.run --target gpt-oss:20b --probes dan.DanInTheWild
    python -m vuln_recon.run --target gpt-oss:20b --probes promptinject --attacker-model jaahas/qwen3.5-uncensored:9b

Odczyt wiedzy:
    python -m vuln_recon.run --list-scans
    python -m vuln_recon.run --show <scan_id>
    python -m vuln_recon.run --top gpt-oss:20b      # ranking podatności (po rodzinie probe'a)

Wymaga: zainstalowanego garaka (pip install -r requirements-recon.txt) oraz schematu `recon`
w bazie agent_core (świeży build robi to z schema_core.sql; na działającej bazie:
psql -d agent_core -f database/migrations/add_recon_schema.sql).
"""

from __future__ import annotations

import argparse
import sys

from database import recon_db
from vuln_recon.config import GarakSettings
from vuln_recon.ingest import scan_and_store

THICK = "═" * 72
SEP = "─" * 72


def _pct(x) -> str:
    return f"{float(x):.0%}" if x is not None else "—"


def cmd_list_scans() -> None:
    scans = recon_db.ScanRepository.list()
    print(THICK)
    print(f"  Skany recon ({len(scans)})")
    print(THICK)
    for s in scans:
        print(f"  {s['id']}  [{s['status']:<9}] {s['tool']:<6} cel={s['target_model']}"
              + (f"  atakujący={s['attacker_model']}" if s['attacker_model'] else "")
              + f"  {s['started_at']:%Y-%m-%d %H:%M}")
    if not scans:
        print("  (brak — uruchom skan: --target <model> --probes <probe>)")


def cmd_show(scan_id: str) -> None:
    scan = recon_db.ScanRepository.get(scan_id)
    if not scan:
        print(f"Nie ma skanu {scan_id}.")
        return
    print(THICK)
    print(f"  Skan {scan['id']}  [{scan['status']}]")
    print(THICK)
    print(f"  narzędzie:  {scan['tool']} {scan['tool_version'] or ''}")
    print(f"  atakowany:  {scan['target_model']} (generator: {scan['target_type']})")
    print(f"  atakujący:  {scan['attacker_model'] or '— (probe statyczny)'}")
    print(f"  probe'y:    {scan['probes']}")
    if scan["error"]:
        print(f"  błąd:       {scan['error']}")

    findings = recon_db.FindingRepository.for_scan(scan_id)
    print(SEP)
    print(f"  Findingi ({len(findings)}) — failure_rate = odsetek prób, które ZŁAMAŁY model:")
    for f in findings:
        print(f"    {_pct(f['failure_rate']):>5}  {f['probe']:<28} {f['detector']:<28} "
              f"({f['passed']}/{f['total']} passed)")

    hits = recon_db.HitRepository.for_scan(scan_id, limit=5)
    if hits:
        print(SEP)
        print(f"  Przykładowe trafienia (prompty, które złamały model) — pokazuję {len(hits)}:")
        for h in hits:
            prompt = (h["prompt"] or "").replace("\n", " ")[:160]
            print(f"    [{h['probe']}] {prompt}…")
    print(THICK)


def cmd_top(target_model: str) -> None:
    rows = recon_db.top_vulnerabilities(target_model)
    print(THICK)
    print(f"  Ranking podatności: {target_model}  (po rodzinie probe'a, ze wszystkich skanów)")
    print(THICK)
    if not rows:
        print("  (brak danych — uruchom najpierw skan tego modelu)")
        return
    for r in rows:
        print(f"    {_pct(r['failure_rate']):>5}  {r['probe_family']:<20} "
              f"({r['failures']}/{r['total']} prób złamało, skanów: {r['scans']})")
    print(THICK)


def cmd_scan(args) -> None:
    overrides = {"target_model": args.target, "target_type": args.target_type}
    if args.probes:
        overrides["probes"] = args.probes
    if args.attacker_model:
        overrides["attacker_model"] = args.attacker_model
    if args.atkgen_convs is not None:
        overrides["atkgen_convs"] = args.atkgen_convs
    if args.atkgen_calls is not None:
        overrides["atkgen_calls"] = args.atkgen_calls
    if args.extra_args:
        overrides["extra_args"] = args.extra_args
    settings = GarakSettings(**overrides)

    print(THICK)
    print(f"  Garak recon  |  atakowany={settings.target_model} (gen={settings.target_type})")
    print(f"  probe'y={settings.probes}"
          + (f"  atakujący={settings.attacker_model}" if settings.attacker_model else ""))
    if settings.attacker_model and "atkgen" not in settings.probes:
        print("  UWAGA: model atakujący działa TYLKO z probem 'atkgen' — przy tych probe'ach "
              "zostanie zignorowany (dodaj --probes atkgen).")
    print(THICK)
    scan_id = scan_and_store(settings)
    # Po skanie od razu pokaż wynik (findingi + przykładowe trafienia) — bez drugiej komendy.
    print()
    cmd_show(scan_id)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Recon podatności modelu (Garak) → schemat recon.")
    p.add_argument("--target", help="model ATAKOWANY (np. gpt-oss:20b)")
    p.add_argument("--target-type", default="ollama", help="generator garak (domyślnie ollama)")
    p.add_argument("--probes", help="spec probe'ów garaka (np. dan.DanInTheWild, 'dan,promptinject')")
    p.add_argument("--attacker-model", help="model red-team/atkgen (opcjonalny)")
    p.add_argument("--atkgen-convs", type=int, help="atkgen: liczba konwersacji (convs_per_generation; domyślnie garak=5)")
    p.add_argument("--atkgen-calls", type=int, help="atkgen: maks. tur w konwersacji (max_calls_per_conv; domyślnie garak=5)")
    p.add_argument("--extra-args", help="surowe dodatkowe flagi do garaka, np. '--generations 1'")
    p.add_argument("--list-scans", action="store_true", help="lista skanów")
    p.add_argument("--show", metavar="SCAN_ID", help="szczegóły skanu (findingi + trafienia)")
    p.add_argument("--top", metavar="MODEL", help="ranking podatności modelu")
    return p


def main() -> None:
    # Konsola Windows bywa cp1250 — ramki/Unicode w raporcie wywalają print.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    args = build_parser().parse_args()
    if args.list_scans:
        cmd_list_scans()
    elif args.show:
        cmd_show(args.show)
    elif args.top:
        cmd_top(args.top)
    elif args.target:
        cmd_scan(args)
    else:
        build_parser().print_help()


if __name__ == "__main__":
    main()
