"""
Nocny orkiestrator atkgen (model-vs-model) vs gpt-oss:20b.

Po kolei odpala PEŁNE domyślne atkgen dla dwóch modeli ATAKUJĄCYCH (qwen3.6 27b-ctx8k,
potem qwen3.5 9b-ctx8k), każdy przez CLI `vuln_recon.run` (zapis do schematu recon).
Odporność na zawis (zaobserwowany wcześniej): każdy scan ma TWARDY limit czasu, a po jego
przekroczeniu ubijane jest CAŁE drzewo procesów (taskkill /T) i lecimy dalej. Po każdym
biegu sprzątane są wiszące wpisy 'running'. Na końcu — podsumowanie w logu.

Uruchomienie (w tle, na noc):
    python overnight_atkgen.py
Wymaga: OLLAMA_KEEP_ALIVE=0 na serwerze (modele schodzą jeden-na-raz) + warianty ctx8k modeli.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime

TARGET = "gpt-oss:20b"
ATTACKERS = ["qwen3.6-uncensored:27b-ctx8k", "qwen3.5-uncensored:9b-ctx8k"]
PER_SCAN_TIMEOUT = 9000  # 2.5h — bezpiecznik; pełny atkgen (25 konw.) realnie ~45 min


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cleanup_dangling() -> None:
    """Oznacza wiszące scan'y atkgen ('running') jako failed — np. po ubiciu timeoutem
    (ingest nie zdąży domknąć przy twardym kill)."""
    try:
        from database import recon_db
        with recon_db.get_conn() as c, c.cursor() as cur:
            cur.execute(
                "UPDATE scans SET status='failed', "
                "error=COALESCE(error,'')||'[overnight: ubity timeoutem/sprzatanie]', "
                "finished_at=NOW() WHERE status='running' AND tool='garak'"
            )
            n = cur.rowcount
        if n:
            print(f"{ts()}  [cleanup] {n} wiszacych scan -> failed", flush=True)
    except Exception as e:
        print(f"{ts()}  [cleanup] blad: {e}", flush=True)


def run_one(attacker: str) -> None:
    print(f"\n{ts()}  ===== START atkgen: atak={attacker} cel={TARGET} =====", flush=True)
    cmd = [sys.executable, "-m", "vuln_recon.run", "--target", TARGET,
           "--probes", "atkgen", "--attacker-model", attacker]
    t0 = time.time()
    p = subprocess.Popen(cmd)
    try:
        p.communicate(timeout=PER_SCAN_TIMEOUT)
        print(f"{ts()}  ===== DONE atak={attacker} ({(time.time()-t0)/60:.1f} min) =====", flush=True)
    except subprocess.TimeoutExpired:
        # Ubij CAŁE drzewo (CLI + garak + ewentualne wnuki) — /T zabija dzieci.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        print(f"{ts()}  ===== TIMEOUT atak={attacker} po {PER_SCAN_TIMEOUT}s — ubite, ide dalej =====", flush=True)
    except Exception as e:
        print(f"{ts()}  ===== ERROR atak={attacker}: {type(e).__name__}: {e} =====", flush=True)
    cleanup_dangling()


def summary() -> None:
    print(f"\n{ts()}  ##### PODSUMOWANIE NOCNE (atkgen) #####", flush=True)
    try:
        from database import recon_db
        for s in recon_db.ScanRepository.list(limit=30):
            sc = recon_db.ScanRepository.get(s["id"])
            if sc["probes"] != ["atkgen"]:
                continue
            fnd = recon_db.FindingRepository.for_scan(s["id"])
            nh = len(recon_db.HitRepository.for_scan(s["id"], limit=100000))
            line = f"  {s['id'][:8]} [{sc['status']}] atak={sc['attacker_model']} trafien={nh}"
            for f in fnd:
                line += f"  | {f['failure_rate']*100:.1f}% {f['probe']}/{f['detector']} ({f['passed']}/{f['total']})"
            print(line, flush=True)
    except Exception as e:
        print(f"  blad podsumowania: {e}", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(f"{ts()}  NOCNY ORKIESTRATOR atkgen — {len(ATTACKERS)} atakujacych, "
          f"timeout/scan={PER_SCAN_TIMEOUT}s, cel={TARGET}", flush=True)
    cleanup_dangling()
    for atk in ATTACKERS:
        run_one(atk)
    summary()
    print(f"{ts()}  WSZYSTKO ZAKONCZONE", flush=True)
