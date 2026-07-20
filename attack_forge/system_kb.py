"""System knowledge base — WHAT we attack and WITH what intel.

Two file-backed libraries: `SystemLibrary` (architecture + agents, `data/systems.yaml`) and
`ModelLibrary` (per-model weaknesses, `data/models.yaml`). Each agent names its `model`, so
`build_target_profile(system, agent, models)` assembles the personalized `TargetProfile` the
selector attacks with: the agent's own surface, the system context (architecture + sibling agents),
and the powering model's vulnerabilities / resistances. File-backed now; can move to SQL later
(and the model KB can be auto-populated from the recon DB) behind this same interface.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .models import TargetProfile

_MODELS_PATH = Path(__file__).resolve().parent / "data" / "models.yaml"
_SYSTEMS_PATH = Path(__file__).resolve().parent / "data" / "systems.yaml"


class ModelProfile(BaseModel):
    id: str
    description: str = ""
    vulnerabilities: list[str] = Field(default_factory=list)
    resistant_to: list[str] = Field(default_factory=list)
    notes: str = ""


class AgentProfile(BaseModel):
    name: str
    role: str
    model: str = Field(description="a ModelProfile id (see models.yaml)")
    channel: str
    defenses: list[str] = Field(default_factory=list)
    vulnerabilities: list[str] = Field(default_factory=list, description="agent-specific, not the model's")
    notes: str = ""


class SystemProfile(BaseModel):
    id: str
    description: str
    architecture: str = ""
    agents: list[AgentProfile] = Field(default_factory=list)

    def agent(self, name: str) -> AgentProfile | None:
        return next((a for a in self.agents if a.name == name), None)

    def agent_names(self) -> list[str]:
        return [a.name for a in self.agents]


class ModelLibrary:
    def __init__(self, models: list[ModelProfile]):
        self._by_id = {m.id: m for m in models}

    @classmethod
    def from_yaml(cls, path: str | Path = _MODELS_PATH) -> "ModelLibrary":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
        return cls([ModelProfile.model_validate(item) for item in raw])

    def get(self, model_id: str) -> ModelProfile | None:
        return self._by_id.get(model_id)

    def list(self) -> list[ModelProfile]:
        return list(self._by_id.values())


class SystemLibrary:
    def __init__(self, systems: list[SystemProfile]):
        self._by_id = {s.id: s for s in systems}

    @classmethod
    def from_yaml(cls, path: str | Path = _SYSTEMS_PATH) -> "SystemLibrary":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
        return cls([SystemProfile.model_validate(item) for item in raw])

    def get(self, system_id: str) -> SystemProfile | None:
        return self._by_id.get(system_id)

    def list(self) -> list[SystemProfile]:
        return list(self._by_id.values())


def _render_system_context(system: SystemProfile, target_agent: str) -> str:
    lines = [f"system: {system.id} — {system.description}"]
    if system.architecture:
        lines.append("architecture:\n" + system.architecture.rstrip())
    others = [a for a in system.agents if a.name != target_agent]
    if others:
        lines.append("other agents in the system (potential hops / pivots):")
        lines += [f"  - {a.name} [{a.model}]: {a.role}" for a in others]
    return "\n".join(lines)


def build_target_profile(system: SystemProfile, agent_name: str, models: ModelLibrary) -> TargetProfile:
    """Assemble the personalized TargetProfile for one agent: its own surface + the system context
    (architecture + sibling agents) + the powering model's weaknesses. Raises KeyError if the agent
    isn't in the system."""
    agent = system.agent(agent_name)
    if agent is None:
        raise KeyError(agent_name)
    model = models.get(agent.model)

    # Carry the free-text notes forward — this is where the SURFACE-DEPENDENT guidance lives (e.g.
    # "ascii helps in chat but backfires on the execution surface"), which the lists can't express
    # and which the selector was previously never shown.
    notes_parts: list[str] = []
    if agent.notes:
        notes_parts.append(f"agent — {agent.notes.strip()}")
    if model and model.notes:
        notes_parts.append(f"model ({agent.model}) — {model.notes.strip()}")

    return TargetProfile(
        name=agent.name,
        description=agent.role,
        channel=agent.channel,
        known_defenses=agent.defenses,
        known_vulnerabilities=agent.vulnerabilities,
        system=_render_system_context(system, agent_name),
        model=agent.model,
        model_vulnerabilities=(model.vulnerabilities if model else []),
        model_resistant_to=(model.resistant_to if model else []),
        notes="\n".join(notes_parts),
    )


DEFAULT_MODEL_LIBRARY = ModelLibrary.from_yaml()
DEFAULT_SYSTEM_LIBRARY = SystemLibrary.from_yaml()
