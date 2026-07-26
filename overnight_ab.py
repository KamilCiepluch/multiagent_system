"""
Nocny test A/B: czy warstwa wiedzy (--seed) podnosi ASR? (throwaway, nie commitować)

Kontrolowane porównanie: dla każdego trialu odpala lifelong DWA razy — bez --seed i z --seed —
za każdym razem od CZYSTEGO startu (kasuje zapisaną bibliotekę, żeby biegi się nie kontaminowały).
Wariablą jest TYLKO obecność katalogu jako prioru. Wynik: ile biegów z sukcesem w każdej grupie.

Wyniki dopisywane na bieżąco do autodan_turbo/logs/overnight_results.txt (gitignored).
"""

import subprocess
import sys
import re
import os
import time
import datetime

PY = r"C:\Users\kamil\.conda\envs\system_agentowy2\python.exe"
LIB = "autodan_turbo/logs/strategy_library__data_read__api_keys__email.json"
RESULTS = "autodan_turbo/logs/overnight_results.txt"
BUDGET_HOURS = 7.0       # przestań startować nowe triale po tylu godzinach
MAX_TRIALS = 100         # bezpiecznik
EPOCHS = 4
LL_ITERS = 2
TIMEOUT = 2400  # 40 min na bieg — guard przed zawieszeniem

BASE = [PY, "-u", "-m", "autodan_turbo.run", "--stage", "lifelong",
        "--goal", "data_read", "--asset", "api_keys", "--injection", "email",
        "--epochs", str(EPOCHS), "--lifelong-iterations", str(LL_ITERS)]


def parse(out: str):
    asr = re.search(r"ASR \(ground-truth ATTACK_SUCCESS\): (\d+)/(\d+)", out)
    depth = re.search(r"Graded depth — max: ([\d.]+)", out)
    outcome = ("succeeded" if "zakończony (succeeded)" in out
               else "blocked" if "zakończony (blocked)" in out else "?")
    s = int(asr.group(1)) if asr else None
    n = int(asr.group(2)) if asr else None
    d = depth.group(1) if depth else "?"
    return s, n, outcome, d


def log(line: str):
    print(line, flush=True)
    with open(RESULTS, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    deadline = time.time() + BUDGET_HOURS * 3600
    log(f"\n===== OVERNIGHT A/B start {datetime.datetime.now():%Y-%m-%d %H:%M} | "
        f"budżet={BUDGET_HOURS}h epochs={EPOCHS} ll_iters={LL_ITERS} =====")
    agg = {"noseed": [], "seed": []}
    trial = 0
    while time.time() < deadline and trial < MAX_TRIALS:
        trial += 1
        for mode in ("noseed", "seed"):
            if time.time() >= deadline:
                break
            try:
                os.remove(LIB)  # czysty start — brak kontaminacji między biegami
            except FileNotFoundError:
                pass
            cmd = BASE + (["--seed"] if mode == "seed" else [])
            t0 = time.time()
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   timeout=TIMEOUT, env=env)
                s, n, outcome, d = parse(r.stdout)
                dt = int(time.time() - t0)
                agg[mode].append(1 if outcome == "succeeded" else 0)
                log(f"trial {trial} | {mode:6} | ASR={s}/{n} | outcome={outcome} "
                    f"| maxdepth={d} | {dt}s")
            except subprocess.TimeoutExpired:
                log(f"trial {trial} | {mode:6} | TIMEOUT po {TIMEOUT}s")
            except Exception as e:
                log(f"trial {trial} | {mode:6} | ERROR {type(e).__name__}: {str(e)[:120]}")

    log("-" * 50)
    for mode in ("noseed", "seed"):
        runs = agg[mode]
        succ = sum(runs)
        pct = f" ({succ/len(runs):.0%})" if runs else ""
        log(f"PODSUMOWANIE {mode}: {succ}/{len(runs)} biegów z sukcesem{pct}")
    log(f"===== OVERNIGHT A/B koniec {datetime.datetime.now():%Y-%m-%d %H:%M} =====")


if __name__ == "__main__":
    main()
