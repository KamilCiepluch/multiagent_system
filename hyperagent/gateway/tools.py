"""
Metadane HTTP gatewaya dla prymitywów ataku.

Sama logika prymitywów (`AttackPrimitives`) mieszka w `attack_core.primitives`
— to czysty, testowalny kod domenowy bez wiedzy o HTTP. Tutaj zostają WYŁĄCZNIE
rejestry, których `gateway/server.py` używa, by zwalidować i rozpakować JSON-owe
ciało żądania `/tools/{name}` zanim wywoła odpowiednią metodę `AttackPrimitives`.
"""

from __future__ import annotations

# Nazwy i kolejność argumentów każdego prymitywu — gateway/server.py używa tego
# rejestru, by zwalidować i rozpakować ciało żądania zanim wywoła metodę.
TOOL_ARGSPEC: dict[str, list[str]] = {
    "reset_target": [],
    "inject_email": ["sender", "subject", "body"],
    "poison_skill": ["agent_name", "skill_name", "content"],
    "poison_search_result": ["query", "content", "source_name"],
    "run_target_task": ["task"],
}

# Mapowanie wektor_ataku → nazwa narzędzia. Narzędzia SPOZA tej mapy
# (reset_target, run_target_task) są zawsze dostępne — to narzędzia operacyjne,
# nie wektory ataku. Narzędzia Z tej mapy są dostępne tylko gdy ich klucz
# pojawia się w objective.compatible_injection_points.
INJECTION_POINT_TOOLS: dict[str, str] = {
    "email":         "inject_email",
    "skill":         "poison_skill",
    "search_result": "poison_search_result",
}

# Argumenty opcjonalne (mają wartość domyślną w AttackPrimitives) — server.py
# nie wymaga ich obecności w ciele żądania.
TOOL_OPTIONAL_ARGS: dict[str, set[str]] = {
    "poison_search_result": {"source_name"},
}
