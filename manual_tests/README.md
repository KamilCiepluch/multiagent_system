# manual_tests

Dev scratch scripts to eyeball each attacker-side role of `attack_forge` in isolation — no argparse,
just params at the top of each file. Edit the params, then run/debug the file directly (F5 / ▶ /
drop a breakpoint). Meant for stepping through in a debugger, not automation.

| file | role | shows |
|------|------|-------|
| `s1_selector.py` | S1 selector | what S1 SEES (rendered target + menu) and picks (rationale → tool_names → composition) |
| `s2_author.py`   | S2 author   | the recipe S2 emits (ordered `steps`) + local validation; `MANUAL_TOOLS` to isolate S2 |
| `executor.py`    | executor    | each step's resolved input → tool output (how the message is assembled); `MANUAL_PLAN` to isolate |

**No Postgres / no agent system needed** — these are attacker-side only. They only need the attacker
model reachable (proxy `base_url` + `bearer` come from the repo `.env`); the model itself is set by
`ATTACKER_MODEL` at the top of each script. The `wrap_*` / task steps in `executor.py` call the model;
pure transforms don't.

Run from the repo root, e.g. `python manual_tests/executor.py` (each script puts the repo root on
`sys.path` itself, so a direct debugger run works too).
