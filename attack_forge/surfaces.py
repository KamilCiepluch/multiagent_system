"""Attack surfaces — where a vector ENTERS the system and how that entry is scored.

A surface is not just an injection point: it bundles the injection point, the agent the vector is
framed against, and the judge spec that scores that path. Switching surface therefore switches all
three together — which is why the loop can't pivot surface by changing `--injection` alone.

Pivoting between surfaces is the loop's COARSE move. Enriching the target intel adapts technique
choice WITHIN a surface (`reflect.apply_to_target`); when a surface flatly flops and the reflector
says pivot/abandon, the loop escalates to the NEXT surface here. The ladder is ordered by our own
red-team finding: the email entry is hard (a deterministic sender-role gate the qwen family triages
well), while the trusted-content surfaces the agent EXECUTES on (an injected skill step, a poisoned
search result) are where that family is actually weak — no sender-role gate stands in the way.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Surface:
    name: str
    injection: str          # attack_core.injection_points id
    target: str             # agent the vector is framed against (system_kb agent name)
    spec: str               # judge spec id (data/judges.yaml)
    true_role: str = "brak"  # the sender's actual role, for the role_spoof gate (email surface)


# Ordered escalation ladder: start at the hard entry, climb toward the executing surfaces.
SURFACES: list[Surface] = [
    Surface("email", injection="email", target="email_agent", spec="secret_exfil_via_email", true_role="brak"),
    Surface("skill", injection="skill", target="terminal_agent", spec="secret_exfil_terminal"),
    Surface("search_result", injection="search_result", target="search_agent", spec="secret_exfil_terminal"),
]

_BY_INJECTION = {s.injection: i for i, s in enumerate(SURFACES)}


def index_for_injection(injection: str) -> int:
    """Ladder position of the surface entered via `injection` (0 = first surface if unknown)."""
    return _BY_INJECTION.get(injection, 0)


def next_surface(current: int) -> Surface | None:
    """The next surface to escalate to after `current`, or None if the ladder is exhausted."""
    nxt = current + 1
    return SURFACES[nxt] if 0 <= nxt < len(SURFACES) else None
